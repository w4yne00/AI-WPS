import json
import os
from pathlib import Path
from typing import Dict, List, Optional
from urllib import error, request as urllib_request

from app.core.config import AppSettings, TaskRoute, load_settings
from app.core.errors import ProviderAuthError, ProviderTimeoutError, ProviderUnavailableError
from app.core.logging import get_logger


logger = get_logger(__name__)
LOCAL_KEY_PATH = Path(__file__).resolve().parents[3] / "run" / "provider_api_key"
ROUTE_KEY_DIR = Path(__file__).resolve().parents[3] / "run" / "provider_api_keys"
_LAST_PROVIDER_DEBUG: Dict = {}


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
    "technical_solution": "技术方案",
    "contract_acceptance": "合同验收文档",
    "test_outline": "测试大纲和细则",
}

TECHNICAL_REVIEW_PROMPTS = {
    "technical_solution": "\n".join(
        [
            "请从以下维度审查技术方案内容：",
            "1. 功能描述准确性：检查功能边界、输入输出、前置条件、异常流程、权限和依赖是否描述清楚，避免夸大或遗漏关键约束。",
            "2. 术语专业性：检查技术术语、产品名称、接口名称、模块名称是否准确、一致，避免口语化和同一概念多种叫法。",
            "3. 设计合理性：检查方案是否说明架构边界、模块职责、数据流、容错机制、安全性、可扩展性和部署约束。",
            "4. 要求明确性：检查需求、验收标准和测试要求是否可执行、可验证、无歧义，避免“尽快、友好、高效、支持多种”等不可验收表述。",
            "请优先指出影响理解、实现、验收或交付风险的问题，并给出可直接落地的修改建议。",
        ]
    ),
    "contract_acceptance": "\n".join(
        [
            "请从以下维度审查合同验收文档内容：",
            "1. 验收范围：检查验收对象、交付边界、版本范围、排除项和依赖条件是否明确。",
            "2. 验收证据：检查是否明确交付物清单、测试记录、签署材料、问题闭环记录和可追溯证明。",
            "3. 判定标准：检查通过/不通过标准、缺陷等级、整改时限、复验方式和例外处理是否可执行。",
            "4. 合同一致性：检查文档表述是否与合同条款、技术协议、变更单和项目范围保持一致。",
            "5. 风险闭环：检查遗留问题、限制条件、责任归属和后续计划是否清楚，避免留下验收争议。",
            "请优先指出可能影响验收签署、责任划分或后续交付的风险，并给出可落地修改建议。",
        ]
    ),
    "test_outline": "\n".join(
        [
            "请从以下维度审查测试大纲和细则内容：",
            "1. 测试范围：检查测试对象、版本、环境、接口、模块边界和不测范围是否明确。",
            "2. 测试目标：检查测试目标是否与需求、设计、验收标准对应，是否覆盖关键业务路径和异常场景。",
            "3. 用例完整性：检查前置条件、输入数据、操作步骤、预期结果、判定准则和清理步骤是否可复现。",
            "4. 覆盖充分性：检查功能、性能、安全、兼容、异常、边界值和回归测试是否按风险分层覆盖。",
            "5. 缺陷闭环：检查缺陷记录、等级划分、复测策略、通过条件和测试报告输出是否明确。",
            "请优先指出会导致测试不可执行、不可复现、不可验收或覆盖不足的问题，并给出可落地修改建议。",
        ]
    ),
}

DEFAULT_TECHNICAL_REVIEW_PROMPT = TECHNICAL_REVIEW_PROMPTS["technical_solution"]


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
        "6. 不要原样返回待处理内容；如果原文已经较好，也必须在措辞、结构或信息组织上做出有效优化。",
    ]

    if user_instruction.strip():
        lines.extend(
            [
                "",
                "用户附加要求：",
                user_instruction.strip(),
            ]
        )

    lines.extend(
        [
            "",
            "待处理内容：",
            text.strip(),
        ]
    )
    return "\n".join(lines)


def build_smart_write_prompt(
    text: str,
    action: str,
    user_prompt: str = "",
    style: str = "default",
    focus: str = "default",
    length: str = "default",
) -> str:
    action_text = {
        "rewrite": "改写润色",
        "continue": "续写扩展",
        "summarize": "提炼总结",
        "custom": "自定义编写",
    }.get(action, "改写润色")
    lines = [
        "你是企业办公文档智能编写助手。",
        "任务类型：{0}".format(action_text),
        "表达风格：{0}".format(STYLE_TEXT.get(style, STYLE_TEXT["default"])),
        "侧重点：{0}".format(FOCUS_TEXT.get(focus, FOCUS_TEXT["default"])),
        "篇幅要求：{0}".format(LENGTH_TEXT.get(length, LENGTH_TEXT["default"])),
    ]
    if user_prompt.strip():
        lines.extend(["用户补充要求：", user_prompt.strip()])
    lines.extend(
        [
            "",
            "待处理原文：",
            text.strip(),
            "",
            "要求：",
            "1. 必须基于待处理原文生成新内容。",
            "2. 不允许原样返回原文。",
            "3. 只输出最终正文，不要解释处理过程。",
        ]
    )
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


def get_default_technical_review_prompt(document_type: str = "technical_solution") -> str:
    return TECHNICAL_REVIEW_PROMPTS.get(document_type, DEFAULT_TECHNICAL_REVIEW_PROMPT)


def build_technical_review_prompt(
    text: str,
    document_type: str,
    review_prompt: str = "",
) -> str:
    prompt_text = review_prompt.strip() or get_default_technical_review_prompt(document_type)
    document_type_text = DOCUMENT_TYPE_TEXT.get(document_type, "技术方案")
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


def build_document_proofread_prompt() -> str:
    return "\n".join(
        [
            "你是一名企业技术文档审校器，不是自由改写器。",
            "请基于 input_data 中的 document_text、document_structure、template_type、check_scope 和 local_rule_findings 做综合审校。",
            "审校范围包括：错别字、语病、表述不规范、逻辑不清、章节命名不统一。",
            "格式合规问题请参考 local_rule_findings，不要虚构无法从结构化数据判断的页眉页脚、页码或表格深层格式问题。",
            "必须只返回结构化 JSON，不要输出解释性前后缀。",
            "JSON 格式：",
            '{"issues":[{"category":"typo|grammar|expression|logic|heading_consistency","severity":"info|warning|error","paragraphIndex":1,"original":"原文片段","suggestion":"修改建议","message":"问题说明","reason":"判断依据","confidence":0.0}]}',
            '如果没有发现问题，返回 {"issues":[]}。',
        ]
    )


def build_document_proofread_payload(
    document_text: str,
    document_structure: Dict,
    template_type: str,
    template_version: str,
    trace_id: str,
    local_rule_findings: Optional[List[Dict]] = None,
    task_id: str = "word.proofread",
) -> Dict:
    return {
        "input_data": {
            "scene": "word",
            "task_id": task_id,
            "taskType": task_id,
            "proofread_mode": "document_quality",
            "trace_id": trace_id,
            "document_text": document_text,
            "document_structure": document_structure,
            "template_type": template_type,
            "template_version": template_version,
            "check_scope": {
                "check_format": True,
                "check_expression": True,
                "check_typos": True,
                "check_logic": True,
                "check_heading_consistency": True,
            },
            "local_rule_findings": local_rule_findings or [],
        },
        "query": build_document_proofread_prompt(),
        "conversation_id": "",
        "mode": "blocking",
        "user": "wps-ai-assistant",
        "files": [],
    }


def infer_payload_style(path: str, provider_type: str = "") -> str:
    normalized = (path or "").rstrip("/")
    if normalized.endswith("/workflows/run"):
        return "workflow"
    if normalized.endswith("/chat-messages"):
        return "chat"
    if provider_type == "enterprise-dify-workflow":
        return "workflow"
    return "chat"


def is_workflow_provider(settings: AppSettings) -> bool:
    return infer_payload_style(settings.provider_chat_path, settings.provider_type) == "workflow"


def build_provider_request_payload(settings: AppSettings, input_data: Dict, query: str) -> Dict:
    return {
        "inputs": {"query": query},
        "query": query,
        "conversation_id": "",
        "response_mode": settings.provider_mode,
        "user": "wps-ai-assistant",
        "files": [],
    }


def build_route_request_payload(settings: AppSettings, route: TaskRoute, input_data: Dict, query: str) -> Dict:
    response_mode = route.response_mode or settings.provider_mode
    return {
        "inputs": {"query": query},
        "query": query,
        "conversation_id": "",
        "response_mode": response_mode,
        "user": "wps-ai-assistant",
        "files": [],
    }


def _preview_text(value: str, limit: int = 4) -> str:
    text = (value or "").replace("\r", " ").replace("\n", " ").strip()
    if not text:
        return ""
    return text[:limit] + "..."


def _sanitize_provider_body(body: Dict) -> Dict:
    inputs = body.get("inputs") if isinstance(body.get("inputs"), dict) else {}
    query = str(body.get("query", "") or "")
    return {
        "bodyKeys": sorted(body.keys()),
        "inputsKeys": sorted(inputs.keys()),
        "queryLength": len(query),
        "queryPreview": _preview_text(query),
        "responseMode": body.get("response_mode", body.get("mode", "")),
        "conversationIdSet": bool(body.get("conversation_id")),
        "filesCount": len(body.get("files") or []),
        "user": body.get("user", ""),
    }


def _sanitize_provider_response(body: Dict) -> Dict:
    answer = str(body.get("answer", "") or "") if isinstance(body, dict) else ""
    data = body.get("data", {}) if isinstance(body, dict) else {}
    outputs = data.get("outputs", {}) if isinstance(data, dict) else {}
    output_answer = ""
    if isinstance(outputs, dict):
        output_answer = str(outputs.get("answer", outputs.get("result", "")) or "")
    return {
        "bodyKeys": sorted(body.keys()) if isinstance(body, dict) else [],
        "answerLength": len(answer or output_answer),
        "conversationIdSet": bool(body.get("conversation_id")) if isinstance(body, dict) else False,
        "messageIdSet": bool(body.get("message_id") or body.get("id")) if isinstance(body, dict) else False,
    }


def reset_provider_debug() -> None:
    _LAST_PROVIDER_DEBUG.clear()


def record_provider_debug(event: Dict) -> None:
    debug = {
        "traceId": event.get("traceId", ""),
        "taskType": event.get("taskType", ""),
        "url": event.get("url", ""),
    }
    request_info = event.get("request", {})
    if isinstance(request_info, dict):
        body = request_info.get("body", {})
        if isinstance(body, dict):
            debug["request"] = _sanitize_provider_body(body)
    response_info = event.get("response", {})
    if isinstance(response_info, dict) and response_info:
        debug["response"] = {
            "status": response_info.get("status", 200),
            **_sanitize_provider_response(response_info.get("body", {})),
        }
    error_info = event.get("error", {})
    if isinstance(error_info, dict) and error_info:
        debug["error"] = {
            "type": str(error_info.get("type", "")),
            "status": error_info.get("status", ""),
            "message": _preview_text(str(error_info.get("message", "")), 160),
        }
    for field in ("provider", "skipReason", "providerBaseUrlConfigured", "authSource"):
        if field in event:
            debug[field] = event[field]
    _LAST_PROVIDER_DEBUG.clear()
    _LAST_PROVIDER_DEBUG.update(debug)


def get_last_provider_debug() -> Dict:
    return dict(_LAST_PROVIDER_DEBUG)


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


def _extract_json_payload(answer: str):
    raw = (answer or "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    object_start = raw.find("{")
    array_start = raw.find("[")
    if array_start >= 0 and (object_start < 0 or array_start < object_start):
        array_end = raw.rfind("]")
        if array_end >= array_start:
            try:
                return json.loads(raw[array_start:array_end + 1])
            except json.JSONDecodeError:
                return None

    object_end = raw.rfind("}")
    if object_start >= 0 and object_end >= object_start:
        try:
            return json.loads(raw[object_start:object_end + 1])
        except json.JSONDecodeError:
            pass

    if array_start >= 0:
        array_end = raw.rfind("]")
        if array_end >= array_start:
            try:
                return json.loads(raw[array_start:array_end + 1])
            except json.JSONDecodeError:
                return None
    return None


def parse_document_proofread_issues(answer: str) -> List[Dict]:
    payload = _extract_json_payload(answer)
    if payload is None:
        return []
    if isinstance(payload, dict):
        raw_issues = payload.get("issues", [])
    elif isinstance(payload, list):
        raw_issues = payload
    else:
        return []

    allowed_categories = {
        "typo",
        "grammar",
        "expression",
        "logic",
        "heading_consistency",
    }
    allowed_severities = {"info", "warning", "error"}
    issues: List[Dict] = []
    for item in raw_issues:
        if not isinstance(item, dict):
            continue
        category = str(item.get("category", "expression")).strip() or "expression"
        if category not in allowed_categories:
            category = "expression"
        severity = str(item.get("severity", "warning")).strip() or "warning"
        if severity not in allowed_severities:
            severity = "warning"
        message = str(item.get("message", "")).strip()
        suggestion = str(item.get("suggestion", item.get("replacement", ""))).strip()
        original = str(item.get("original", "")).strip()
        reason = str(item.get("reason", "")).strip()
        if not (message or suggestion or original):
            continue
        parsed = {
            "category": category,
            "severity": severity,
            "paragraphIndex": item.get("paragraphIndex", item.get("paragraph_index")),
            "original": original,
            "suggestion": suggestion,
            "message": message or "AI detected a document quality issue.",
            "reason": reason,
            "confidence": item.get("confidence"),
        }
        issues.append(parsed)
    return issues


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


def extract_answer(body: Dict, output_key: str = "") -> str:
    answer = body.get("answer")
    if isinstance(answer, str) and answer.strip():
        return answer.strip()

    data = body.get("data", {})
    if isinstance(data, dict):
        outputs = data.get("outputs")
        if isinstance(outputs, dict):
            keys = [output_key] if output_key else []
            keys.extend(["result", "answer", "text", "output", "rewrittenText"])
            for key in keys:
                value = outputs.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
                if isinstance(value, (dict, list)):
                    return json.dumps(value, ensure_ascii=False)
        for key in ("answer", "text", "rewrittenText"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    raise ProviderUnavailableError("Enterprise AI response did not contain an answer.")


def get_local_api_key_path(path: Optional[Path] = None) -> Path:
    return path or LOCAL_KEY_PATH


def get_route_api_key_path(api_key_ref: str, base_path: Optional[Path] = None) -> Path:
    safe_ref = "".join(ch for ch in (api_key_ref or "default") if ch.isalnum() or ch in ("-", "_", "."))
    safe_ref = safe_ref or "default"
    root = base_path or LOCAL_KEY_PATH.parent
    return root / "provider_api_keys" / safe_ref


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


def save_route_api_key(api_key_ref: str, api_key: str, base_path: Optional[Path] = None) -> None:
    target = get_route_api_key_path(api_key_ref, base_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(api_key.strip(), encoding="utf-8")


def clear_route_api_key(api_key_ref: str, base_path: Optional[Path] = None) -> None:
    target = get_route_api_key_path(api_key_ref, base_path)
    if target.exists():
        target.unlink()


def load_route_api_key(api_key_ref: str, base_path: Optional[Path] = None) -> str:
    target = get_route_api_key_path(api_key_ref, base_path)
    if not target.exists():
        return ""
    return target.read_text(encoding="utf-8").strip()


class ProviderClient:
    def __init__(self, settings: Optional[AppSettings] = None) -> None:
        self.settings = settings or load_settings()
        self.reload_settings = settings is None

    def refresh_settings(self) -> None:
        if self.reload_settings:
            self.settings = load_settings()

    def resolve_task_route(self, task_type: str) -> TaskRoute:
        routes = self.settings.task_routes or {}
        route = routes.get(task_type) or TaskRoute(task_id=task_type, enabled=True)
        if not route.path:
            route.path = self.settings.provider_chat_path
        if not route.payload_style:
            route.payload_style = infer_payload_style(route.path, self.settings.provider_type)
        if not route.response_mode:
            route.response_mode = self.settings.provider_mode
        if not route.api_key_ref:
            route.api_key_ref = "default"
        return route

    def build_task_input_data(self, task_type: str, trace_id: str, payload: Optional[Dict] = None) -> Dict:
        route = self.resolve_task_route(task_type)
        input_data = {
            "scene": "word",
            "task_id": route.task_id,
            "taskType": task_type,
            "trace_id": trace_id,
        }
        if payload:
            input_data.update(payload)
        return input_data

    def is_configured(self, key_base_path: Optional[Path] = None) -> bool:
        self.refresh_settings()
        return bool(self.settings.provider_base_url.strip() and self.get_api_key("default", key_base_path))

    def is_task_configured(self, task_type: str, key_base_path: Optional[Path] = None) -> bool:
        return self.is_configured(key_base_path)

    def get_auth_source(self, key_base_path: Optional[Path] = None) -> str:
        if os.getenv(self.settings.provider_api_key_env):
            return "env"
        if load_local_api_key(key_base_path / "provider_api_key" if key_base_path else None):
            return "file"
        return "none"

    def get_route_auth_source(self, api_key_ref: str) -> str:
        if load_route_api_key(api_key_ref):
            return "route-file"
        if api_key_ref and api_key_ref != "default":
            return "none"
        return self.get_auth_source()

    def get_api_key(self, api_key_ref: str = "default", key_base_path: Optional[Path] = None) -> str:
        route_key = load_route_api_key(api_key_ref, key_base_path)
        if route_key:
            return route_key
        return os.getenv(self.settings.provider_api_key_env) or load_local_api_key(
            key_base_path / "provider_api_key" if key_base_path else None
        )

    def get_task_api_key(self, route: TaskRoute, key_base_path: Optional[Path] = None) -> str:
        return self.get_api_key("default", key_base_path)

    def build_route_url(self, route: TaskRoute) -> str:
        return "{0}{1}".format(self.settings.provider_base_url.rstrip("/"), route.path or self.settings.provider_chat_path)

    def task_route_configured_count(self, key_base_path: Optional[Path] = None) -> int:
        return 0

    def build_route_diagnostics(self, key_base_path: Optional[Path] = None) -> Dict:
        path = self.settings.provider_chat_path or "/chat-messages"
        url = "{0}{1}".format(self.settings.provider_base_url.rstrip("/"), path) if self.settings.provider_base_url.strip() else ""
        return {
            "version": "0.11.8-alpha",
            "providerBaseUrlConfigured": bool(self.settings.provider_base_url.strip()),
            "providerChatPath": path,
            "url": url,
            "path": path,
            "payloadStyle": "chat",
            "responseMode": self.settings.provider_mode,
            "configured": self.is_configured(key_base_path),
            "authSource": self.get_auth_source(key_base_path),
            "taskRouteCount": 0,
            "taskRouteConfiguredCount": 0,
            "routes": {},
        }

    def post_task(self, task_type: str, trace_id: str, input_data: Dict, query: str) -> Dict:
        self.refresh_settings()
        route_payload = build_provider_request_payload(self.settings, {}, query)
        url = "{0}{1}".format(
            self.settings.provider_base_url.rstrip("/"),
            self.settings.provider_chat_path or "/chat-messages",
        )
        logger.info(
            "traceId=%s task=%s url=%s authSource=%s payloadStyle=chat queryLength=%s inputKeysIgnored=%s",
            trace_id,
            task_type,
            url,
            self.get_auth_source(),
            len(query or ""),
            sorted((input_data or {}).keys()),
        )
        payload = json.dumps(
            route_payload
        ).encode("utf-8")
        record_provider_debug(
            {
                "traceId": trace_id,
                "taskType": task_type,
                "url": url,
                "request": {"body": route_payload},
            }
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
                record_provider_debug(
                    {
                        "traceId": trace_id,
                        "taskType": task_type,
                        "url": url,
                        "request": {"body": route_payload},
                        "response": {"status": getattr(response, "status", 200), "body": body},
                    }
                )
                return body
        except error.HTTPError as exc:
            record_provider_debug(
                {
                    "traceId": trace_id,
                    "taskType": task_type,
                    "url": url,
                    "request": {"body": route_payload},
                    "error": {"type": "HTTPError", "status": exc.code, "message": str(exc)},
                }
            )
            if exc.code in (401, 403):
                raise ProviderAuthError() from exc
            raise ProviderUnavailableError("Enterprise AI returned HTTP {0}.".format(exc.code)) from exc
        except error.URLError as exc:
            reason = getattr(exc, "reason", "")
            record_provider_debug(
                {
                    "traceId": trace_id,
                    "taskType": task_type,
                    "url": url,
                    "request": {"body": route_payload},
                    "error": {"type": "URLError", "message": str(reason)},
                }
            )
            if "timed out" in str(reason).lower():
                raise ProviderTimeoutError() from exc
            raise ProviderUnavailableError("Enterprise AI endpoint is unreachable.") from exc

    def record_unconfigured_debug(self, task_type: str, trace_id: str, query: str) -> None:
        record_provider_debug(
            {
                "traceId": trace_id,
                "taskType": task_type,
                "provider": "mock",
                "skipReason": "provider_not_configured",
                "providerBaseUrlConfigured": bool(self.settings.provider_base_url.strip()),
                "authSource": self.get_auth_source(),
                "request": {"body": build_provider_request_payload(self.settings, {}, query)},
            }
        )

    def smart_write(
        self,
        text: str,
        action: str,
        trace_id: str,
        user_prompt: str = "",
        style: str = "default",
        focus: str = "default",
        length: str = "default",
        selection_mode: str = "selection",
    ) -> Dict:
        prompt = build_smart_write_prompt(
            text=text,
            action=action,
            user_prompt=user_prompt,
            style=style,
            focus=focus,
            length=length,
        )
        task_type = "word.smart_write"
        if not self.is_task_configured(task_type):
            logger.info("traceId=%s provider=mock task=word.smart_write", trace_id)
            self.record_unconfigured_debug(task_type, trace_id, prompt)
            return {
                "rewrittenText": self._mock_rewrite(text, action, user_prompt),
                "provider": "mock",
                "prompt": prompt,
            }

        body = self.post_task(
            task_type,
            trace_id,
            {},
            prompt,
        )

        rewritten_text = extract_answer(body)
        logger.info("traceId=%s provider=enterprise-dify-chat task=word.smart_write", trace_id)
        return {
            "rewrittenText": rewritten_text,
            "provider": "enterprise-dify-chat/{0}".format(self.get_auth_source()),
            "prompt": prompt,
            "conversationId": body.get("conversation_id", ""),
            "messageId": body.get("message_id", ""),
        }

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
        task_type = "word.continue" if mode == "continue" else "word.rewrite"
        if not self.is_task_configured(task_type):
            logger.info("traceId=%s provider=mock task=word.rewrite", trace_id)
            self.record_unconfigured_debug(task_type, trace_id, prompt)
            return {
                "rewrittenText": self._mock_rewrite(text, mode, user_instruction),
                "provider": "mock",
                "prompt": prompt,
            }

        body = self.post_task(
            task_type,
            trace_id,
            {},
            prompt,
        )

        rewritten_text = extract_answer(body)
        logger.info("traceId=%s provider=enterprise-dify-chat task=word.rewrite", trace_id)
        return {
            "rewrittenText": rewritten_text,
            "provider": "enterprise-dify-chat/{0}".format(self.get_auth_source()),
            "prompt": prompt,
            "conversationId": body.get("conversation_id", ""),
            "messageId": body.get("message_id", ""),
        }

    def proofread_typos(self, text: str, trace_id: str) -> list:
        source_text = text.strip()
        if not source_text or not self.is_task_configured("word.proofread"):
            return []

        prompt = build_typo_prompt(source_text)
        body = self.post_task(
            "word.proofread",
            trace_id,
            {},
            prompt,
        )

        answer = extract_answer(body)
        logger.info("traceId=%s provider=enterprise-dify-chat task=word.proofread.typo", trace_id)
        return parse_typo_issues(answer)

    def proofread_document(
        self,
        document_text: str,
        document_structure: Dict,
        template_type: str,
        template_version: str,
        trace_id: str,
        local_rule_findings: Optional[List[Dict]] = None,
    ) -> List[Dict]:
        if not document_text.strip() or not self.is_task_configured("word.proofread"):
            return []

        payload = build_document_proofread_payload(
            document_text=document_text,
            document_structure=document_structure,
            template_type=template_type,
            template_version=template_version,
            trace_id=trace_id,
            local_rule_findings=local_rule_findings,
            task_id=self.resolve_task_route("word.proofread").task_id,
        )
        body = self.post_task("word.proofread", trace_id, {}, payload["query"])

        answer = extract_answer(body)
        logger.info("traceId=%s provider=enterprise-dify-chat task=word.proofread.document", trace_id)
        return parse_document_proofread_issues(answer)

    def technical_review(
        self,
        text: str,
        trace_id: str,
        document_type: str = "technical_solution",
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

        if not self.is_task_configured("word.technical_review"):
            logger.info("traceId=%s provider=mock task=word.technical_review", trace_id)
            self.record_unconfigured_debug("word.technical_review", trace_id, prompt)
            result = self._mock_technical_review(source_text, document_type)
            result["prompt"] = prompt
            return result

        body = self.post_task(
            "word.technical_review",
            trace_id,
            {},
            prompt,
        )

        parsed = parse_technical_review_answer(
            extract_answer(body)
        )
        logger.info("traceId=%s provider=enterprise-dify-chat task=word.technical_review", trace_id)
        return {
            "summary": parsed["summary"],
            "issues": parsed["issues"],
            "provider": "enterprise-dify-chat/{0}".format(self.get_auth_source()),
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
