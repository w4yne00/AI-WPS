import json
import os
from pathlib import Path
from typing import Dict, List, Optional
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

DOCUMENT_TYPE_TEXT = {
    "general_technical": "通用技术文档",
    "technical_solution": "技术方案",
    "contract_acceptance": "合同验收文档",
    "test_outline": "测试大纲和细则",
}

DEFAULT_TECHNICAL_REVIEW_PROMPT = "\n".join(
    [
        "请从以下维度审查技术文档内容：",
        "1. 功能描述准确性：检查功能边界、输入输出、前置条件、异常流程、权限和依赖是否描述清楚，避免夸大或遗漏关键约束。",
        "2. 术语专业性：检查技术术语、产品名称、接口名称、模块名称是否准确、一致，避免口语化和同一概念多种叫法。",
        "3. 设计合理性：检查方案是否说明架构边界、模块职责、数据流、容错机制、安全性、可扩展性和部署约束。",
        "4. 要求明确性：检查需求、验收标准和测试要求是否可执行、可验证、无歧义，避免“尽快、友好、高效、支持多种”等不可验收表述。",
        "请优先指出影响理解、实现、验收或交付风险的问题，并给出可直接落地的修改建议。",
    ]
)


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


def get_default_technical_review_prompt() -> str:
    return DEFAULT_TECHNICAL_REVIEW_PROMPT


def build_technical_review_prompt(
    text: str,
    document_type: str,
    review_prompt: str = "",
) -> str:
    prompt_text = review_prompt.strip() or DEFAULT_TECHNICAL_REVIEW_PROMPT
    document_type_text = DOCUMENT_TYPE_TEXT.get(document_type, document_type or "通用技术文档")
    return "\n".join(
        [
            "你是一名资深技术文档审查专家。",
            "请审查下面的文档内容，重点判断描述是否准确、术语是否专业、设计是否合理、要求是否明确。",
            "文档类型：{0}".format(document_type_text),
            "",
            "审查重点：",
            prompt_text,
            "",
            "输出要求：",
            "1. 只返回 JSON 对象，不要输出 Markdown、解释性前后缀或代码块。",
            "2. JSON 顶层字段为 summary 和 issues。",
            "3. issues 为数组，每项包含 category、severity、location、originalText、problem、suggestion、suggestedRewrite。",
            "4. category 只能使用 accuracy、terminology、design、requirement。",
            "5. severity 只能使用 high、medium、low。",
            "6. location 可用章节名、段落号或“选中文本”描述；无法定位时写“未定位”。",
            "7. suggestedRewrite 只针对可直接替换的局部文本给出，无法直接改写时留空字符串。",
            "",
            "待审查内容：",
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


def _extract_json_payload(raw: str):
    source = (raw or "").strip()
    if not source:
        return None

    object_start = source.find("{")
    list_start = source.find("[")
    if list_start >= 0 and (object_start < 0 or list_start < object_start):
        list_end = source.rfind("]")
        if list_end >= list_start:
            source = source[list_start:list_end + 1]
    else:
        object_end = source.rfind("}")
        if object_start >= 0 and object_end >= object_start:
            source = source[object_start:object_end + 1]

    try:
        return json.loads(source)
    except json.JSONDecodeError:
        return None


def _normalize_review_category(value: str) -> str:
    text = str(value or "").strip().lower()
    if text in {"accuracy", "terminology", "design", "requirement"}:
        return text
    if "术语" in text or "term" in text:
        return "terminology"
    if "设计" in text or "架构" in text or "design" in text:
        return "design"
    if "要求" in text or "需求" in text or "验收" in text or "require" in text:
        return "requirement"
    return "accuracy"


def _normalize_review_severity(value: str) -> str:
    text = str(value or "").strip().lower()
    if text in {"high", "medium", "low"}:
        return text
    if text in {"高", "严重", "critical", "error"}:
        return "high"
    if text in {"低", "提示", "info"}:
        return "low"
    return "medium"


def parse_technical_review_answer(answer: str) -> Dict:
    payload = _extract_json_payload(answer)
    if payload is None:
        return {
            "summary": (answer or "").strip(),
            "issues": [],
        }

    if isinstance(payload, list):
        raw_issues = payload
        summary = ""
    elif isinstance(payload, dict):
        raw_issues = payload.get("issues", [])
        summary = str(payload.get("summary", "")).strip()
    else:
        return {"summary": "", "issues": []}

    if not isinstance(raw_issues, list):
        raw_issues = []

    issues = []
    for item in raw_issues:
        if not isinstance(item, dict):
            continue
        problem = str(item.get("problem", "")).strip()
        suggestion = str(item.get("suggestion", "")).strip()
        if not problem and not suggestion:
            continue
        issues.append(
            {
                "category": _normalize_review_category(item.get("category", "")),
                "severity": _normalize_review_severity(item.get("severity", "")),
                "location": str(item.get("location", "") or "未定位").strip(),
                "originalText": str(item.get("originalText", "")).strip(),
                "problem": problem or "未说明具体问题。",
                "suggestion": suggestion or "请补充明确、可验证的表述。",
                "suggestedRewrite": str(item.get("suggestedRewrite", "")).strip(),
            }
        )

    if not summary:
        summary = "发现 {0} 项技术文档审查问题。".format(len(issues)) if issues else "未发现明显技术文档审查问题。"
    return {
        "summary": summary,
        "issues": issues,
    }


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
        return bool(self.settings.provider_base_url.strip() and self.get_api_key())

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
        if not self.is_configured():
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
        if not source_text or not self.is_configured():
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

    def technical_review(
        self,
        text: str,
        trace_id: str,
        document_type: str = "general_technical",
        review_prompt: str = "",
    ) -> Dict:
        source_text = text.strip()
        prompt = build_technical_review_prompt(
            text=source_text,
            document_type=document_type,
            review_prompt=review_prompt,
        )
        if not source_text:
            return {
                "summary": "未检测到可审查的文档内容。",
                "issues": [],
                "provider": "mock",
                "prompt": prompt,
            }

        if not self.is_configured():
            logger.info("traceId=%s provider=mock task=word.technical_review", trace_id)
            result = self._mock_technical_review(source_text, document_type)
            result["prompt"] = prompt
            return result

        payload = json.dumps(
            {
                "input_data": {
                    "scene": "word",
                    "review_mode": "technical_document",
                    "document_type": document_type,
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

        parsed = parse_technical_review_answer(extract_answer(body))
        logger.info("traceId=%s provider=enterprise-chat-api task=word.technical_review", trace_id)
        return {
            "summary": parsed["summary"],
            "issues": parsed["issues"],
            "provider": "enterprise-chat-api/{0}".format(self.get_auth_source()),
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

    def _mock_technical_review(self, text: str, document_type: str) -> Dict:
        issues: List[Dict] = []
        vague_terms = ["相关", "等", "尽快", "友好", "高效", "优化", "合理", "多种", "必要时"]
        for term in vague_terms:
            if term in text:
                issues.append(
                    {
                        "category": "requirement",
                        "severity": "medium",
                        "location": "未定位",
                        "originalText": term,
                        "problem": "存在不易验收或边界不清的表述。",
                        "suggestion": "补充明确范围、量化指标、完成条件或验收方法。",
                        "suggestedRewrite": "",
                    }
                )
                break

        if ("接口" in text or "API" in text) and not any(
            keyword in text for keyword in ["入参", "出参", "返回", "异常", "状态码", "权限"]
        ):
            issues.append(
                {
                    "category": "accuracy",
                    "severity": "high",
                    "location": "接口描述",
                    "originalText": "",
                    "problem": "接口相关描述可能缺少入参、出参、异常处理、状态码或权限边界。",
                    "suggestion": "补充接口调用条件、请求参数、返回字段、失败场景和权限要求。",
                    "suggestedRewrite": "",
                }
            )

        if document_type == "technical_solution" and not any(
            keyword in text for keyword in ["架构", "模块", "数据流", "容错", "部署", "安全"]
        ):
            issues.append(
                {
                    "category": "design",
                    "severity": "medium",
                    "location": "方案设计",
                    "originalText": "",
                    "problem": "技术方案可能缺少架构边界、模块职责、数据流、容错或部署约束。",
                    "suggestion": "补充整体架构、关键模块职责、数据流转、异常兜底和部署约束。",
                    "suggestedRewrite": "",
                }
            )

        if document_type == "contract_acceptance" and not any(
            keyword in text for keyword in ["验收标准", "验收方法", "通过条件", "不通过", "交付物"]
        ):
            issues.append(
                {
                    "category": "requirement",
                    "severity": "high",
                    "location": "验收要求",
                    "originalText": "",
                    "problem": "合同验收文档可能缺少可执行的验收标准、验收方法或通过条件。",
                    "suggestion": "明确交付物、验收步骤、通过/不通过判定条件和问题整改机制。",
                    "suggestedRewrite": "",
                }
            )

        if document_type == "test_outline" and not any(
            keyword in text for keyword in ["测试范围", "前置条件", "测试步骤", "预期结果", "通过准则"]
        ):
            issues.append(
                {
                    "category": "requirement",
                    "severity": "medium",
                    "location": "测试说明",
                    "originalText": "",
                    "problem": "测试大纲和细则可能缺少测试范围、前置条件、测试步骤或预期结果。",
                    "suggestion": "补充测试范围、测试数据、前置条件、执行步骤、预期结果和通过准则。",
                    "suggestedRewrite": "",
                }
            )

        summary = (
            "当前使用 mock 技术审查，发现 {0} 项可能影响实现或验收的问题。".format(len(issues))
            if issues else
            "当前使用 mock 技术审查，未发现明显技术文档审查问题。"
        )
        return {
            "summary": summary,
            "issues": issues,
            "provider": "mock",
        }
