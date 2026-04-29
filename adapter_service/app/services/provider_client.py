import json
import os
from typing import Dict, Optional
from urllib import error, request as urllib_request

from app.core.config import AppSettings, load_settings
from app.core.errors import ProviderAuthError, ProviderTimeoutError, ProviderUnavailableError
from app.core.logging import get_logger


logger = get_logger(__name__)


STYLE_TEXT = {
    "default": "正式、清晰、简洁",
    "formal": "正式、清晰、简洁",
    "structured": "结构清晰、层次分明",
    "reporting": "更像工作汇报材料，突出结论与执行状态",
}

FOCUS_TEXT = {
    "default": "保持内容完整",
    "conclusion": "优先突出结论和关键判断",
    "risk": "优先突出风险、问题与影响",
    "next_step": "优先突出下一步计划和行动项",
    "implementation": "优先突出实施路径、步骤与安排",
}

LENGTH_TEXT = {
    "default": "保持原有篇幅附近",
    "concise": "尽量精简表达，避免冗余",
    "same": "保持篇幅基本不变",
    "expanded": "可适度扩写，使表达更完整",
}


def build_rewrite_prompt(
    text: str,
    mode: str,
    user_instruction: str = "",
    style: str = "default",
    focus: str = "default",
    length: str = "default",
) -> str:
    mode_text = "续写" if mode == "continue" else "改写"
    lines = [
        "你是一名企业办公文档助手。",
        "请对下面内容进行{0}。".format(mode_text),
        "要求：",
        "1. 保留原意，不编造事实。",
        "2. 使用{0}的中文表达。".format(STYLE_TEXT.get(style, STYLE_TEXT["default"])),
        "3. {0}。".format(FOCUS_TEXT.get(focus, FOCUS_TEXT["default"])),
        "4. {0}。".format(LENGTH_TEXT.get(length, LENGTH_TEXT["default"])),
        "5. 输出结果直接给出正文，不要解释你的处理过程。",
    ]

    if user_instruction.strip():
        lines.extend([
            "",
            "用户附加要求：",
            user_instruction.strip(),
        ])

    lines.extend([
        "",
        "待处理内容：",
        text.strip(),
    ])
    return "\n".join(lines)


def extract_answer(body: Dict) -> str:
    answer = body.get("answer")
    if isinstance(answer, str) and answer.strip():
        return answer.strip()

    data = body.get("data", {})
    if isinstance(data, dict):
        for key in ("answer", "text", "rewrittenText"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    raise ProviderUnavailableError("Enterprise AI response did not contain an answer.")


class ProviderClient:
    def __init__(self, settings: Optional[AppSettings] = None) -> None:
        self.settings = settings or load_settings()

    def is_configured(self) -> bool:
        return bool(os.getenv(self.settings.provider_api_key_env))

    def rewrite(
        self,
        text: str,
        mode: str,
        trace_id: str,
        user_instruction: str = "",
        style: str = "default",
        focus: str = "default",
        length: str = "default",
    ) -> Dict:
        prompt = build_rewrite_prompt(
            text=text,
            mode=mode,
            user_instruction=user_instruction,
            style=style,
            focus=focus,
            length=length,
        )
        api_key = os.getenv(self.settings.provider_api_key_env)
        if not api_key:
            logger.info("traceId=%s provider=mock task=word.rewrite", trace_id)
            return {
                "rewrittenText": self._mock_rewrite(text, mode, user_instruction),
                "provider": "mock",
                "prompt": prompt,
            }

        payload = json.dumps(
            {
                "input_data": {
                    "scene": "word",
                    "rewrite_mode": mode,
                    "trace_id": trace_id,
                },
                "query": prompt,
                "conversation_id": "",
                "mode": self.settings.provider_mode,
                "user": "wps-ai-assistant",
                "files": [],
            }
        ).encode("utf-8")
        url = "{0}{1}".format(
            self.settings.provider_base_url.rstrip("/"),
            self.settings.provider_chat_path,
        )
        req = urllib_request.Request(
            url,
            data=payload,
            method="POST",
            headers={
                "Authorization": "Bearer {0}".format(api_key),
                "Content-Type": "application/json",
                "X-Trace-Id": trace_id,
            },
        )

        try:
            with urllib_request.urlopen(req, timeout=self.settings.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            if exc.code in (401, 403):
                raise ProviderAuthError() from exc
            raise ProviderUnavailableError("Enterprise AI returned HTTP {0}.".format(exc.code)) from exc
        except error.URLError as exc:
            reason = getattr(exc, "reason", "")
            if "timed out" in str(reason).lower():
                raise ProviderTimeoutError() from exc
            raise ProviderUnavailableError("Enterprise AI endpoint is unreachable.") from exc

        rewritten_text = extract_answer(body)
        logger.info("traceId=%s provider=enterprise-chat-api task=word.rewrite", trace_id)
        return {
            "rewrittenText": rewritten_text,
            "provider": "enterprise-chat-api",
            "prompt": prompt,
            "conversationId": body.get("conversation_id", ""),
            "messageId": body.get("message_id", ""),
        }

    def _mock_rewrite(self, text: str, mode: str, user_instruction: str) -> str:
        prefix_map = {
            "rewrite": "改写结果：",
            "continue": "续写结果：",
            "polish": "润色结果：",
            "formalize": "正式化结果：",
        }
        suffix = ""
        if user_instruction.strip():
            suffix = "\n附加要求已考虑：{0}".format(user_instruction.strip())
        return "{0}\n{1}{2}".format(prefix_map.get(mode, "改写结果："), text.strip(), suffix)
