import json
import os
from pathlib import Path
from typing import Dict, Optional
from urllib import error, request as urllib_request

from app.core.config import AppSettings, load_settings
from app.core.errors import ProviderAuthError, ProviderTimeoutError, ProviderUnavailableError
from app.core.logging import get_logger


logger = get_logger(__name__)
LOCAL_KEY_PATH = Path(__file__).resolve().parents[3] / "run" / "provider_api_key"


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


def build_typo_prompt(text: str) -> str:
    return "\n".join(
        [
            "你是一名中文技术文件校对助手。",
            "请检查下面文本中的错别字、用词错误、明显病句或疑似错误表达。",
            "要求：",
            "1. 只返回 JSON，不要输出解释性前后缀。",
            "2. JSON 格式为数组，每一项包含 original、suggestion、reason。",
            "3. 如果没有发现问题，返回空数组 []。",
            "4. 不要改写全文，只指出明确或高度疑似的问题。",
            "",
            "待检查文本：",
            text.strip(),
        ]
    )


def parse_typo_issues(answer: str) -> list:
    raw = (answer or "").strip()
    if not raw:
        return []
    start = raw.find("[")
    end = raw.rfind("]")
    if start >= 0 and end >= start:
        raw = raw[start:end + 1]
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    issues = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        original = str(item.get("original", "")).strip()
        suggestion = str(item.get("suggestion", "")).strip()
        reason = str(item.get("reason", "")).strip()
        if original and suggestion:
            issues.append(
                {
                    "original": original,
                    "suggestion": suggestion,
                    "reason": reason,
                }
            )
    return issues


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


def get_local_api_key_path(path: Optional[Path] = None) -> Path:
    return path or LOCAL_KEY_PATH


def save_local_api_key(api_key: str, path: Optional[Path] = None) -> None:
    target = get_local_api_key_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(api_key.strip(), encoding="utf-8")


def clear_local_api_key(path: Optional[Path] = None) -> None:
    target = get_local_api_key_path(path)
    if target.exists():
        target.unlink()


def load_local_api_key(path: Optional[Path] = None) -> str:
    target = get_local_api_key_path(path)
    if not target.exists():
        return ""
    return target.read_text(encoding="utf-8").strip()


class ProviderClient:
    def __init__(self, settings: Optional[AppSettings] = None) -> None:
        self.settings = settings or load_settings()

    def is_configured(self) -> bool:
        return bool(self.get_api_key())

    def get_auth_source(self) -> str:
        if os.getenv(self.settings.provider_api_key_env):
            return "env"
        if load_local_api_key():
            return "file"
        return "none"

    def get_api_key(self) -> str:
        return os.getenv(self.settings.provider_api_key_env) or load_local_api_key()

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
        api_key = self.get_api_key()
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
            "provider": "enterprise-chat-api/{0}".format(self.get_auth_source()),
            "prompt": prompt,
            "conversationId": body.get("conversation_id", ""),
            "messageId": body.get("message_id", ""),
        }

    def proofread_typos(self, text: str, trace_id: str) -> list:
        source_text = text.strip()
        if not source_text or not self.get_api_key():
            return []

        prompt = build_typo_prompt(source_text)
        payload = json.dumps(
            {
                "input_data": {
                    "scene": "word",
                    "proofread_mode": "typo",
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
                "Authorization": "Bearer {0}".format(self.get_api_key()),
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

        answer = extract_answer(body)
        logger.info("traceId=%s provider=enterprise-chat-api task=word.proofread.typo", trace_id)
        return parse_typo_issues(answer)

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
