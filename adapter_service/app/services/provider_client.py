import json
import os
import re
import socket
import threading
from pathlib import Path
from typing import Dict, List, Optional
from urllib import error, request as urllib_request

from app.core.config import AppSettings, TaskRoute, load_settings
from app.core.errors import ProviderAuthError, ProviderTimeoutError, ProviderUnavailableError
from app.core.logging import get_logger
from app.core.models import ExcelAnalysisRequest
from app.services.workflow_profiles import WorkflowProfileError, WorkflowProfileStore


logger = get_logger(__name__)
LOCAL_KEY_PATH = Path(__file__).resolve().parents[3] / "run" / "provider_api_key"
ROUTE_KEY_DIR = Path(__file__).resolve().parents[3] / "run" / "provider_api_keys"
_LAST_PROVIDER_DEBUG: Dict = {}
_LAST_PROVIDER_DEBUG_LOCK = threading.Lock()
FORMAT_REVIEW_ROLE_TIMEOUT_SECONDS = 60
DOCUMENT_REVIEW_TIMEOUT_SECONDS = 1800
EXCEL_ANALYSIS_TIMEOUT_SECONDS = DOCUMENT_REVIEW_TIMEOUT_SECONDS
DIFY_INPUT_MODE_LEGACY = "legacy-input-query"
DIFY_INPUT_MODE_USER_INPUT = "user-input-node"
DIFY_INPUT_MODES = (DIFY_INPUT_MODE_LEGACY, DIFY_INPUT_MODE_USER_INPUT)
_PROVIDER_INPUT_MODE_CACHE: Dict[str, str] = {}


STYLE_TEXT = {
    "standard": "采用国企技术方案常用的正式、准确、克制表达，术语统一，避免口语化和夸张表述",
    "default": "采用国企技术方案常用的正式、准确、克制表达，术语统一，避免口语化和夸张表述",
    "formal": "采用国企技术方案常用的正式、准确、克制表达，术语统一，避免口语化和夸张表述",
    "structured": "按“背景、问题、措施、结论”组织内容，强化层级、逻辑连接和可执行表述",
    "reporting": "采用汇报材料表达，先给结论，再说明进展、问题、风险和下一步安排，语言稳健",
}

FOCUS_TEXT = {
    "complete": "保留原文关键信息、事实、条件和约束，不遗漏责任、时间、对象和结论",
    "default": "保留原文关键信息、事实、条件和约束，不遗漏责任、时间、对象和结论",
    "conclusion": "优先突出核心结论、关键判断、主要风险、影响范围和需要关注的问题",
    "risk": "优先突出核心结论、关键判断、主要风险、影响范围和需要关注的问题",
    "conclusion_risk": "优先突出核心结论、关键判断、主要风险、影响范围和需要关注的问题",
    "next_step": "优先突出解决措施、实施路径、责任分工、时间节点和下一步安排",
    "implementation": "优先突出解决措施、实施路径、责任分工、时间节点和下一步安排",
    "plan_next": "优先突出解决措施、实施路径、责任分工、时间节点和下一步安排",
    "acceptance": "优先突出交付物、验收标准、问题闭环、证据材料和后续跟踪要求",
}

LENGTH_TEXT = {
    "same": "保持与原文相近的篇幅，只优化措辞、结构和信息组织",
    "default": "保持与原文相近的篇幅，只优化措辞、结构和信息组织",
    "concise": "压缩冗余表达，保留关键信息和必要限定，输出更短更直接的版本",
    "expanded": "在不编造事实的前提下补足必要背景、逻辑衔接、措施说明和结论表达",
}

DOCUMENT_TYPE_TEXT = {
    "technical_solution": "技术方案",
    "contract_acceptance": "合同验收文档",
    "test_outline": "测试大纲和细则",
}

DOCUMENT_REVIEW_PROMPTS = {
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

DEFAULT_DOCUMENT_REVIEW_PROMPT = DOCUMENT_REVIEW_PROMPTS["technical_solution"]


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
        "2. {0}。".format(STYLE_TEXT.get(style, STYLE_TEXT["standard"])),
        "3. {0}。".format(FOCUS_TEXT.get(focus, FOCUS_TEXT["complete"])),
        "4. {0}。".format(LENGTH_TEXT.get(length, LENGTH_TEXT["same"])),
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
        "表达风格：{0}".format(STYLE_TEXT.get(style, STYLE_TEXT["standard"])),
        "侧重点：{0}".format(FOCUS_TEXT.get(focus, FOCUS_TEXT["complete"])),
        "篇幅要求：{0}".format(LENGTH_TEXT.get(length, LENGTH_TEXT["same"])),
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
            "3. 保持待处理原文的段落数量和换行结构，适合直接替换用户选中的段落。",
            "4. 如果原文有多个段落，输出也应保留相近分段；不要把连续多个段落压成一整段。",
            "5. 原文已有标题、列表、序号、表格或强调格式时，应尽量保持对应结构和层级。",
            "6. 不要额外新增原文没有、用户也未要求的 Markdown 标题、项目符号、编号列表或表格。",
            "7. 只输出最终正文，不要解释处理过程。",
        ]
    )
    return "\n".join(lines)


def build_smart_imitation_prompt(template_text: str, requirement: str, reference_material: str = "") -> str:
    reference_text = reference_material.strip() or "未提供参考素材。"
    return "\n".join(
        [
            "你是企业办公文档智能仿写助手。",
            "",
            "仿写模板：",
            template_text.strip(),
            "",
            "仿写需求：",
            requirement.strip(),
            "",
            "参考素材：",
            reference_text,
            "",
            "要求：",
            "1. 学习仿写模板的句式、层次、表达节奏和段落结构。",
            "2. 生成内容必须服务于仿写需求。",
            "3. 如提供参考素材，应优先基于参考素材，不编造事实、数据、结论或机构名称。",
            "4. 不要照抄模板中的具体事实、对象、项目名称或数字，除非用户明确要求保留。",
            "5. 尽量保持模板的段落数量、标题层级、列表结构和语气风格。",
            "6. 只输出仿写后的正文，不解释仿写过程。",
        ]
    )


def _provider_safe_str(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    return ""


def build_excel_analysis_prompt(request: ExcelAnalysisRequest) -> str:
    headers = ", ".join(request.table.headers) if request.table.headers else "未识别到表头"
    sample_lines = []
    for row in request.table.rows[:30]:
        sample_lines.append(" | ".join(_provider_safe_str(cell) for cell in row))
    sample_text = "\n".join(sample_lines) if sample_lines else "无可用样本行。"
    requirement = request.options.analysis_requirement.strip() or "请基于表格数据生成通用分析报告。"
    truncated_text = "是，数据已截断，只能基于样本和统计信息分析。" if request.table.truncated else "否。"
    scope_type_text = "选区" if request.scope.scope_type == "selection" else "当前工作表已用区域"
    return "\n".join(
        [
            "你是企业表格数据分析助手。",
            "请基于用户提交的 WPS 表格数据生成中文分析报告。",
            "",
            "工作簿：{0}".format(request.workbook_id),
            "工作表：{0}".format(request.scope.sheet_name or "未命名工作表"),
            "范围：{0}".format(request.scope.address or "未识别"),
            "范围类型：{0}".format(scope_type_text),
            "行数：{0}".format(request.table.row_count),
            "列数：{0}".format(request.table.column_count),
            "数据已截断：{0}".format(truncated_text),
            "表头：{0}".format(headers),
            "",
            "用户分析要求：",
            requirement,
            "",
            "样本数据：",
            sample_text,
            "",
            "输出要求：",
            "1. 只基于表格数据和用户分析要求，不编造不存在的事实、原因、结论或数据。",
            "2. 默认输出一个 JSON 对象，字段为 structuredReport 和 plainText。",
            "3. structuredReport 包含 overview、findings、risks、actions。",
            "4. findings、risks、actions 均为字符串数组。",
            "5. plainText 为可直接复制到 Word 或 PPT 的中文汇报段落。",
            "6. 如果数据已截断，必须说明分析基于有限样本。",
            "7. 不要输出公式，不要声称已经修改单元格，不要要求前端自动写回 Excel。",
        ]
    )


def get_default_document_review_prompt(document_type: str = "technical_solution") -> str:
    return DOCUMENT_REVIEW_PROMPTS.get(document_type, DEFAULT_DOCUMENT_REVIEW_PROMPT)


def build_document_review_prompt(
    text: str,
    document_type: str,
    review_prompt: str = "",
) -> str:
    prompt_text = review_prompt.strip() or get_default_document_review_prompt(document_type)
    document_type_text = DOCUMENT_TYPE_TEXT.get(document_type, "技术方案")
    return "\n".join(
        [
            "你是一名企业文档审查专家。",
            "请审查下面的文档内容，重点发现错别字、语言逻辑表达、通畅性和对应文档类型的专业性问题。",
            "文档类型：{0}".format(document_type_text),
            "",
            "审查重点：",
            prompt_text,
            "",
            "输出要求：",
            "1. 只返回一个 Markdown json 代码块，不要输出代码块以外的解释性文字。",
            "2. json 顶层字段为 summary 和 issues。",
            "3. issues 为数组，每项包含 category、severity、location、originalText、problem、suggestion、suggestedRewrite。",
            "4. category 只能使用 typo、expression、logic、fluency、professional。",
            "5. severity 只能使用 high、medium、low。",
            "6. location 可用章节名、段落号或“选中文本”描述；无法定位时写“未定位”。",
            "7. suggestedRewrite 只针对可直接替换的局部文本给出，无法直接改写时留空字符串。",
            "8. 不要检查字体、字号、行距、页边距等格式合规问题。",
            "9. 只输出本次审查发现的问题列表；不要输出前端处理状态、复制动作或处理记录。",
            "",
            "待审查内容：",
            text.strip(),
        ]
    )


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


def build_provider_request_payload(
    settings: AppSettings,
    input_data: Dict,
    query: str,
    input_mode: str = DIFY_INPUT_MODE_LEGACY,
) -> Dict:
    inputs = {"query": query} if input_mode == DIFY_INPUT_MODE_LEGACY else {}
    return {
        "inputs": inputs,
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


def _provider_input_mode_cache_key(
    settings: AppSettings,
    task_type: str,
    api_key_ref: str,
) -> str:
    return "|".join(
        [
            settings.provider_base_url.rstrip("/"),
            settings.provider_chat_path or "/chat-messages",
            task_type,
            api_key_ref,
        ]
    )


def _sanitize_provider_error_body(
    raw: str,
    query: str = "",
    api_key: str = "",
    limit: int = 480,
) -> str:
    del query, api_key
    raw_text = str(raw or "")
    byte_length = len(raw_text.encode("utf-8", errors="replace"))
    try:
        parsed = json.loads(raw_text)
    except (TypeError, json.JSONDecodeError):
        sanitized = json.dumps(
            {
                "summary": "provider_error_body_redacted",
                "byteLength": byte_length,
            },
            separators=(",", ":"),
        )
    else:
        sanitized_fields = {}
        if isinstance(parsed, dict):
            for field in ("code", "status", "type"):
                value = parsed.get(field)
                if isinstance(value, bool):
                    continue
                if isinstance(value, (str, int)):
                    identifier = str(value)
                    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}", identifier):
                        sanitized_fields[field] = identifier
        sanitized_fields["message"] = "[redacted]"
        sanitized = json.dumps(
            sanitized_fields,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    return str(sanitized)[:limit]


def _read_http_error_body(
    exc: error.HTTPError,
    query: str = "",
    api_key: str = "",
    limit: int = 480,
) -> str:
    try:
        raw = exc.read(4096).decode("utf-8", errors="replace")
    except Exception:
        return ""
    return _sanitize_provider_error_body(
        raw,
        query=query,
        api_key=api_key,
        limit=limit,
    )


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


def _summarize_answer_format(answer: str) -> Dict:
    value = str(answer or "")
    features = {
        "containsHeading": bool(re.search(r"(?m)^\s{0,3}#{1,6}\s+\S", value)),
        "containsOrderedList": bool(re.search(r"(?m)^\s*\d+\.\s+\S", value)),
        "containsUnorderedList": bool(re.search(r"(?m)^\s*[-*+]\s+\S", value)),
        "containsBold": bool(re.search(r"\*\*[^*\n]+\*\*", value)),
        "containsParagraphBreak": "\n\n" in value,
    }
    return {
        "containsMarkdown": any(features.values()),
        **features,
    }


def _sanitize_provider_response(body: Dict) -> Dict:
    answer = str(body.get("answer", "") or "") if isinstance(body, dict) else ""
    data = body.get("data", {}) if isinstance(body, dict) else {}
    outputs = data.get("outputs", {}) if isinstance(data, dict) else {}
    output_answer = ""
    if isinstance(outputs, dict):
        output_answer = str(outputs.get("answer", outputs.get("result", "")) or "")
    result_answer = answer or output_answer
    return {
        "bodyKeys": sorted(body.keys()) if isinstance(body, dict) else [],
        "answerLength": len(result_answer),
        "answerFormat": _summarize_answer_format(result_answer),
        "conversationIdSet": bool(body.get("conversation_id")) if isinstance(body, dict) else False,
        "messageIdSet": bool(body.get("message_id") or body.get("id")) if isinstance(body, dict) else False,
    }


def reset_provider_debug() -> None:
    with _LAST_PROVIDER_DEBUG_LOCK:
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
        if "bodyPreview" in error_info:
            debug["error"]["bodyPreview"] = _sanitize_provider_error_body(
                str(error_info.get("bodyPreview", "")),
                limit=480,
            )
    compatibility_error_info = event.get("compatibilityError", {})
    if isinstance(compatibility_error_info, dict) and compatibility_error_info:
        debug["compatibilityError"] = {
            "type": str(compatibility_error_info.get("type", "")),
            "status": compatibility_error_info.get("status", ""),
            "message": _preview_text(
                str(compatibility_error_info.get("message", "")),
                160,
            ),
        }
        if "bodyPreview" in compatibility_error_info:
            debug["compatibilityError"]["bodyPreview"] = (
                _sanitize_provider_error_body(
                    str(compatibility_error_info.get("bodyPreview", "")),
                    limit=480,
                )
            )
    validation_info = event.get("validation", {})
    if isinstance(validation_info, dict) and validation_info:
        debug["validation"] = validation_info
    for field in (
        "provider",
        "providerName",
        "providerType",
        "skipReason",
        "providerBaseUrlConfigured",
        "authSource",
        "taskAuthSource",
        "taskApiKeyRef",
        "workflowProfileId",
        "workflowProfileName",
        "inputMode",
        "compatibilityFallback",
        "attemptCount",
    ):
        if field in event:
            debug[field] = event[field]
    with _LAST_PROVIDER_DEBUG_LOCK:
        _LAST_PROVIDER_DEBUG.clear()
        _LAST_PROVIDER_DEBUG.update(debug)


def get_last_provider_debug() -> Dict:
    with _LAST_PROVIDER_DEBUG_LOCK:
        return dict(_LAST_PROVIDER_DEBUG)


def _extract_json_payload(answer: str):
    raw = (answer or "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    fence = re.search(r"```(?:json)?\s*(.*?)```", raw, re.IGNORECASE | re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1).strip())
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


def _extract_document_review_payload_text(payload: Dict) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("result", "answer", "text", "output", "content", "message"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    outputs = payload.get("outputs")
    if isinstance(outputs, dict):
        return _extract_document_review_payload_text(outputs)
    return ""


def _document_review_parse_fallback(raw_answer: str, reason: str, fallback_text: str = "") -> Dict:
    raw_text = (fallback_text or raw_answer or "").strip()
    return {
        "summary": "模型后台已返回内容，但未解析为标准问题列表；下方显示原始回复。",
        "issues": [],
        "rawAnswer": raw_text,
        "parseFallbackReason": reason,
    }


def _normalize_document_review_category(value: str) -> str:
    text = str(value or "").strip().lower()
    if text in {"typo", "expression", "logic", "fluency", "professional"}:
        return text
    if "错" in text or "别字" in text or "typo" in text:
        return "typo"
    if "逻辑" in text or "logic" in text or "因果" in text or "矛盾" in text:
        return "logic"
    if "通畅" in text or "通顺" in text or "fluency" in text:
        return "fluency"
    if "专业" in text or "术语" in text or "professional" in text:
        return "professional"
    return "expression"


def _normalize_review_severity(value: str) -> str:
    text = str(value or "").strip().lower()
    if text in {"high", "medium", "low"}:
        return text
    if text in {"高", "严重", "critical", "error"}:
        return "high"
    if text in {"低", "提示", "info"}:
        return "low"
    return "medium"


def parse_document_review_answer(answer: str) -> Dict:
    raw_answer = (answer or "").strip()
    payload = _extract_json_payload(answer)
    if payload is None:
        if raw_answer:
            return _document_review_parse_fallback(raw_answer, "non_json_answer")
        return {"summary": "", "issues": [], "rawAnswer": "", "parseFallbackReason": ""}

    if isinstance(payload, list):
        raw_issues = payload
        summary = ""
    elif isinstance(payload, dict):
        raw_issues = payload.get("issues", [])
        summary = str(payload.get("summary", "")).strip()
        if not isinstance(raw_issues, list):
            return _document_review_parse_fallback(
                raw_answer,
                "unsupported_json_shape",
                _extract_document_review_payload_text(payload),
            )
        if not raw_issues and not summary:
            fallback_text = _extract_document_review_payload_text(payload)
            if fallback_text:
                return _document_review_parse_fallback(
                    raw_answer,
                    "unsupported_json_shape",
                    fallback_text,
                )
    else:
        return _document_review_parse_fallback(raw_answer, "unsupported_json_shape")

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
                "category": _normalize_document_review_category(item.get("category", "")),
                "severity": _normalize_review_severity(item.get("severity", "")),
                "location": str(item.get("location", "") or "未定位").strip(),
                "originalText": str(item.get("originalText", "")).strip(),
                "problem": problem or "未说明具体问题。",
                "suggestion": suggestion or "请补充明确、可验证的表述。",
                "suggestedRewrite": str(item.get("suggestedRewrite", "")).strip(),
            }
        )

    if not summary:
        summary = "发现 {0} 项文档审查问题。".format(len(issues)) if issues else "未发现明显文档审查问题。"
    return {
        "summary": summary,
        "issues": issues,
        "rawAnswer": "",
        "parseFallbackReason": "",
    }


def strip_think_tag_content(value: str) -> str:
    return re.sub(r"<think\b[^>]*>.*?</think\s*>", "", str(value or ""), flags=re.IGNORECASE | re.DOTALL).strip()


def extract_answer(body: Dict, output_key: str = "") -> str:
    answer = body.get("answer")
    if isinstance(answer, str) and answer.strip():
        cleaned_answer = strip_think_tag_content(answer)
        if cleaned_answer:
            return cleaned_answer

    data = body.get("data", {})
    if isinstance(data, dict):
        outputs = data.get("outputs")
        if isinstance(outputs, dict):
            keys = [output_key] if output_key else []
            keys.extend(["result", "answer", "text", "output", "rewrittenText"])
            for key in keys:
                value = outputs.get(key)
                if isinstance(value, str) and value.strip():
                    cleaned_value = strip_think_tag_content(value)
                    if cleaned_value:
                        return cleaned_value
                if isinstance(value, (dict, list)):
                    return json.dumps(value, ensure_ascii=False)
        for key in ("answer", "text", "rewrittenText"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                cleaned_value = strip_think_tag_content(value)
                if cleaned_value:
                    return cleaned_value

    raise ProviderUnavailableError("Enterprise AI response did not contain an answer.")


def _excel_text_list(value) -> List[str]:
    if not isinstance(value, list):
        return []
    return [_provider_safe_str(item).strip() for item in value if _provider_safe_str(item).strip()]


def parse_excel_analysis_answer(answer: str) -> Dict:
    cleaned = strip_think_tag_content(answer or "").strip()
    payload = _extract_json_payload(cleaned)
    if isinstance(payload, dict):
        report = payload.get("structuredReport") or payload.get("structured_report") or {}
        if not isinstance(report, dict):
            report = {}
        return {
            "structuredReport": {
                "overview": _provider_safe_str(report.get("overview")).strip(),
                "findings": _excel_text_list(report.get("findings")),
                "risks": _excel_text_list(report.get("risks")),
                "actions": _excel_text_list(report.get("actions")),
            },
            "plainText": _provider_safe_str(payload.get("plainText") or payload.get("plain_text") or cleaned).strip(),
        }

    return {
        "structuredReport": {
            "overview": "模型后台已返回表格分析结果，但未按结构化 JSON 输出。",
            "findings": [],
            "risks": [],
            "actions": [],
        },
        "plainText": cleaned,
    }


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


def normalize_task_api_key_ref(task_type: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in (task_type or "default")).strip("_") or "default"


class ProviderClient:
    def __init__(
        self,
        settings: Optional[AppSettings] = None,
        workflow_profile_store: Optional[WorkflowProfileStore] = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.reload_settings = settings is None
        self.workflow_profile_store = workflow_profile_store or (
            WorkflowProfileStore() if settings is None else None
        )

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
        self.refresh_settings()
        return bool(self.settings.provider_base_url.strip() and self.get_api_key_for_task(task_type, key_base_path))

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

    def get_task_api_key_ref(self, task_type: str) -> str:
        profile = self.get_active_workflow_profile(task_type)
        if profile and profile.get("apiKeyRef"):
            return str(profile["apiKeyRef"])
        refs = self.settings.task_api_key_refs or {}
        return refs.get(task_type) or normalize_task_api_key_ref(task_type)

    def get_active_workflow_profile(self, task_type: str) -> Optional[Dict]:
        if self.workflow_profile_store is None:
            return None
        try:
            return self.workflow_profile_store.get_active_profile(task_type)
        except WorkflowProfileError:
            return None

    def get_auth_source_for_task(self, task_type: str, key_base_path: Optional[Path] = None) -> str:
        api_key_ref = self.get_task_api_key_ref(task_type)
        if load_route_api_key(api_key_ref, key_base_path):
            return "task-file"
        return self.get_auth_source(key_base_path)

    def get_api_key(self, api_key_ref: str = "default", key_base_path: Optional[Path] = None) -> str:
        route_key = load_route_api_key(api_key_ref, key_base_path)
        if route_key:
            return route_key
        return os.getenv(self.settings.provider_api_key_env) or load_local_api_key(
            key_base_path / "provider_api_key" if key_base_path else None
        )

    def get_task_api_key(self, route: TaskRoute, key_base_path: Optional[Path] = None) -> str:
        return self.get_api_key_for_task(route.task_id, key_base_path)

    def get_api_key_for_task(self, task_type: str, key_base_path: Optional[Path] = None) -> str:
        api_key_ref = self.get_task_api_key_ref(task_type)
        task_key = load_route_api_key(api_key_ref, key_base_path)
        if task_key:
            return task_key
        return self.get_api_key("default", key_base_path)

    def build_task_api_key_status(self, key_base_path: Optional[Path] = None) -> Dict:
        tasks = [
            ("word.smart_write", "智能编写"),
            ("word.smart_imitation", "智能仿写"),
            ("word.document_review", "文档审查"),
            ("word.format_review", "格式审查"),
            ("excel.analysis", "Excel 智能分析"),
        ]
        status = {}
        for task_type, label in tasks:
            profile_data = None
            if self.workflow_profile_store is not None:
                try:
                    profile_data = self.workflow_profile_store.list_for_task(task_type)
                except WorkflowProfileError:
                    profile_data = None
            active_id = str((profile_data or {}).get("activeProfileId", ""))
            active_profile = next(
                (
                    item
                    for item in (profile_data or {}).get("profiles", [])
                    if item.get("id") == active_id
                ),
                {},
            )
            api_key_ref = self.get_task_api_key_ref(task_type)
            task_key_configured = bool(load_route_api_key(api_key_ref, key_base_path))
            status[task_type] = {
                "label": label,
                "apiKeyRef": api_key_ref,
                "taskKeyConfigured": task_key_configured,
                "configured": bool(self.settings.provider_base_url.strip() and self.get_api_key_for_task(task_type, key_base_path)),
                "authSource": "task-file" if task_key_configured else self.get_auth_source(key_base_path),
                "activeProfileId": active_id,
                "activeProfileName": str(active_profile.get("name", "")),
                "profileCount": int((profile_data or {}).get("profileCount", 0)),
            }
        return status

    def build_route_url(self, route: TaskRoute) -> str:
        return "{0}{1}".format(self.settings.provider_base_url.rstrip("/"), route.path or self.settings.provider_chat_path)

    def task_route_configured_count(self, key_base_path: Optional[Path] = None) -> int:
        return 0

    def build_route_diagnostics(self, key_base_path: Optional[Path] = None) -> Dict:
        path = self.settings.provider_chat_path or "/chat-messages"
        url = "{0}{1}".format(self.settings.provider_base_url.rstrip("/"), path) if self.settings.provider_base_url.strip() else ""
        return {
            "version": "0.16.0-alpha",
            "providerBaseUrlConfigured": bool(self.settings.provider_base_url.strip()),
            "providerChatPath": path,
            "url": url,
            "path": path,
            "payloadStyle": "chat",
            "responseMode": self.settings.provider_mode,
            "configured": self.is_configured(key_base_path),
            "authSource": self.get_auth_source(key_base_path),
            "taskApiKeys": self.build_task_api_key_status(key_base_path),
            "taskRouteCount": 0,
            "taskRouteConfiguredCount": 0,
            "routes": {},
        }

    def build_debug_metadata(
        self,
        task_type: str,
        provider: str = "enterprise-dify-chat",
        workflow_profile: Optional[Dict] = None,
        api_key_ref: str = "",
    ) -> Dict:
        profile = workflow_profile if workflow_profile is not None else self.get_active_workflow_profile(task_type)
        metadata = {
            "provider": provider,
            "providerName": self.settings.provider_name,
            "providerType": self.settings.provider_type,
            "providerBaseUrlConfigured": bool(self.settings.provider_base_url.strip()),
            "authSource": self.get_auth_source_for_task(task_type),
            "taskAuthSource": self.get_auth_source_for_task(task_type),
            "taskApiKeyRef": api_key_ref or self.get_task_api_key_ref(task_type),
        }
        if profile:
            metadata["workflowProfileId"] = str(profile.get("id", ""))
            metadata["workflowProfileName"] = str(profile.get("name", ""))
        return metadata

    def post_task(
        self,
        task_type: str,
        trace_id: str,
        input_data: Dict,
        query: str,
        timeout_seconds: Optional[int] = None,
    ) -> Dict:
        self.refresh_settings()
        timeout = timeout_seconds or self.settings.timeout_seconds
        url = "{0}{1}".format(
            self.settings.provider_base_url.rstrip("/"),
            self.settings.provider_chat_path or "/chat-messages",
        )
        workflow_profile = self.get_active_workflow_profile(task_type)
        api_key_ref = (
            str(workflow_profile.get("apiKeyRef", ""))
            if workflow_profile
            else self.get_task_api_key_ref(task_type)
        )
        task_api_key = load_route_api_key(api_key_ref) or self.get_api_key("default")
        debug_metadata = self.build_debug_metadata(
            task_type,
            workflow_profile=workflow_profile,
            api_key_ref=api_key_ref,
        )
        cache_key = _provider_input_mode_cache_key(
            self.settings,
            task_type,
            api_key_ref,
        )
        preferred_mode = _PROVIDER_INPUT_MODE_CACHE.get(
            cache_key,
            DIFY_INPUT_MODE_LEGACY,
        )
        alternate_mode = (
            DIFY_INPUT_MODE_USER_INPUT
            if preferred_mode == DIFY_INPUT_MODE_LEGACY
            else DIFY_INPUT_MODE_LEGACY
        )
        attempt_modes = (preferred_mode, alternate_mode)
        logger.info(
            "traceId=%s task=%s url=%s authSource=%s payloadStyle=chat queryLength=%s inputKeysIgnored=%s",
            trace_id,
            task_type,
            url,
            "task-file" if load_route_api_key(api_key_ref) else self.get_auth_source(),
            len(query or ""),
            sorted((input_data or {}).keys()),
        )
        compatibility_error = None
        for attempt_index, input_mode in enumerate(attempt_modes, start=1):
            attempt_metadata = {
                "inputMode": input_mode,
                "compatibilityFallback": attempt_index > 1,
                "attemptCount": attempt_index,
            }
            route_payload = build_provider_request_payload(
                self.settings,
                {},
                query,
                input_mode=input_mode,
            )
            payload = json.dumps(route_payload).encode("utf-8")
            record_provider_debug(
                {
                    "traceId": trace_id,
                    "taskType": task_type,
                    "url": url,
                    **debug_metadata,
                    **attempt_metadata,
                    **(
                        {"compatibilityError": compatibility_error}
                        if compatibility_error
                        else {}
                    ),
                    "request": {"body": route_payload},
                }
            )
            req = urllib_request.Request(
                url,
                data=payload,
                method="POST",
                headers={
                    "Authorization": "Bearer {0}".format(
                        task_api_key
                    ),
                    "Content-Type": "application/json",
                    "X-Trace-Id": trace_id,
                },
            )
            try:
                with urllib_request.urlopen(req, timeout=timeout) as response:
                    raw_body = response.read().decode("utf-8")
                    try:
                        body = json.loads(raw_body)
                    except json.JSONDecodeError as exc:
                        record_provider_debug(
                            {
                                "traceId": trace_id,
                                "taskType": task_type,
                                "url": url,
                                **debug_metadata,
                                **attempt_metadata,
                                **(
                                    {"compatibilityError": compatibility_error}
                                    if compatibility_error
                                    else {}
                                ),
                                "request": {"body": route_payload},
                                "error": {
                                    "type": "JSONDecodeError",
                                    "message": "Provider returned non-JSON response.",
                                    "bodyPreview": _sanitize_provider_error_body(
                                        raw_body,
                                        query=query,
                                        api_key=task_api_key,
                                        limit=240,
                                    ),
                                },
                            }
                        )
                        raise ProviderUnavailableError(
                            "Enterprise AI returned a non-JSON response."
                        ) from exc
                    _PROVIDER_INPUT_MODE_CACHE[cache_key] = input_mode
                    record_provider_debug(
                        {
                            "traceId": trace_id,
                            "taskType": task_type,
                            "url": url,
                            **debug_metadata,
                            **attempt_metadata,
                            **(
                                {"compatibilityError": compatibility_error}
                                if compatibility_error
                                else {}
                            ),
                            "request": {"body": route_payload},
                            "response": {
                                "status": getattr(response, "status", 200),
                                "body": body,
                            },
                        }
                    )
                    return body
            except error.HTTPError as exc:
                error_body = _read_http_error_body(
                    exc,
                    query=query,
                    api_key=task_api_key,
                )
                error_info = {
                    "type": "HTTPError",
                    "status": exc.code,
                    "message": str(exc),
                    "bodyPreview": error_body,
                }
                if exc.code == 400 and attempt_index == 1:
                    compatibility_error = error_info
                record_provider_debug(
                    {
                        "traceId": trace_id,
                        "taskType": task_type,
                        "url": url,
                        **debug_metadata,
                        **attempt_metadata,
                        **(
                            {"compatibilityError": compatibility_error}
                            if compatibility_error
                            else {}
                        ),
                        "request": {"body": route_payload},
                        "error": error_info,
                    }
                )
                if exc.code == 400 and attempt_index == 1:
                    continue
                if exc.code in (401, 403):
                    raise ProviderAuthError() from exc
                raise ProviderUnavailableError(
                    "Enterprise AI returned HTTP {0}.".format(exc.code)
                ) from exc
            except error.URLError as exc:
                reason = getattr(exc, "reason", "")
                record_provider_debug(
                    {
                        "traceId": trace_id,
                        "taskType": task_type,
                        "url": url,
                        **debug_metadata,
                        **attempt_metadata,
                        **(
                            {"compatibilityError": compatibility_error}
                            if compatibility_error
                            else {}
                        ),
                        "request": {"body": route_payload},
                        "error": {"type": "URLError", "message": str(reason)},
                    }
                )
                if "timed out" in str(reason).lower():
                    raise ProviderTimeoutError() from exc
                raise ProviderUnavailableError(
                    "Enterprise AI endpoint is unreachable."
                ) from exc
            except (TimeoutError, socket.timeout) as exc:
                record_provider_debug(
                    {
                        "traceId": trace_id,
                        "taskType": task_type,
                        "url": url,
                        **debug_metadata,
                        **attempt_metadata,
                        **(
                            {"compatibilityError": compatibility_error}
                            if compatibility_error
                            else {}
                        ),
                        "request": {"body": route_payload},
                        "error": {"type": "TimeoutError", "message": str(exc)},
                    }
                )
                raise ProviderTimeoutError() from exc

    def record_skipped_debug(
        self,
        task_type: str,
        trace_id: str,
        query: str,
        skip_reason: str,
        provider: str = "local",
    ) -> None:
        self.refresh_settings()
        record_provider_debug(
            {
                "traceId": trace_id,
                "taskType": task_type,
                **self.build_debug_metadata(task_type, provider=provider),
                "skipReason": skip_reason,
                "request": {"body": build_provider_request_payload(self.settings, {}, query)},
            }
        )

    def record_unconfigured_debug(self, task_type: str, trace_id: str, query: str) -> None:
        self.record_skipped_debug(
            task_type=task_type,
            trace_id=trace_id,
            query=query,
            skip_reason="provider_not_configured",
            provider="mock",
        )

    def excel_analysis(self, request: ExcelAnalysisRequest, trace_id: str) -> Dict:
        prompt = build_excel_analysis_prompt(request)
        task_type = "excel.analysis"
        if not self.is_task_configured(task_type):
            logger.info("traceId=%s provider=mock task=excel.analysis", trace_id)
            self.record_unconfigured_debug(task_type, trace_id, prompt)
            return {
                "structuredReport": {
                    "overview": "已读取 {0} 行、{1} 列表格数据。".format(
                        request.table.row_count,
                        request.table.column_count,
                    ),
                    "findings": ["请配置 Excel 智能分析模型后台后获取完整分析。"],
                    "risks": [],
                    "actions": ["在设置页保存 excel.analysis 的任务级 API Key。"],
                },
                "plainText": "已读取表格数据。请配置 Excel 智能分析模型后台后生成正式分析报告。",
                "provider": "mock",
                "prompt": prompt,
            }

        body = self.post_task(
            task_type,
            trace_id,
            {
                "scene": "excel",
                "rowCount": request.table.row_count,
                "columnCount": request.table.column_count,
                "truncated": request.table.truncated,
            },
            prompt,
            timeout_seconds=max(self.settings.timeout_seconds, EXCEL_ANALYSIS_TIMEOUT_SECONDS),
        )
        parsed = parse_excel_analysis_answer(extract_answer(body))
        logger.info("traceId=%s provider=enterprise-dify-chat task=excel.analysis", trace_id)
        return {
            **parsed,
            "provider": "enterprise-dify-chat/{0}".format(self.get_auth_source_for_task(task_type)),
            "prompt": prompt,
            "conversationId": body.get("conversation_id", ""),
            "messageId": body.get("message_id", ""),
        }

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

    def smart_imitation(
        self,
        template_text: str,
        requirement: str,
        reference_material: str,
        trace_id: str,
    ) -> Dict:
        prompt = build_smart_imitation_prompt(template_text, requirement, reference_material)
        task_type = "word.smart_imitation"
        if not self.is_task_configured(task_type):
            logger.info("traceId=%s provider=mock task=word.smart_imitation", trace_id)
            self.record_unconfigured_debug(task_type, trace_id, prompt)
            return {
                "rewrittenText": self._mock_rewrite(template_text, "imitate", requirement),
                "provider": "mock",
                "prompt": prompt,
            }

        body = self.post_task(task_type, trace_id, {}, prompt)
        rewritten_text = extract_answer(body)
        logger.info("traceId=%s provider=enterprise-dify-chat task=word.smart_imitation", trace_id)
        return {
            "rewrittenText": rewritten_text,
            "provider": "enterprise-dify-chat/{0}".format(self.get_auth_source_for_task(task_type)),
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

    def document_review(
        self,
        text: str,
        trace_id: str,
        document_type: str = "technical_solution",
        review_prompt: str = "",
    ) -> Dict:
        source_text = text.strip()
        prompt = build_document_review_prompt(
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

        task_type = "word.document_review"
        if not self.is_task_configured(task_type):
            logger.info("traceId=%s provider=mock task=word.document_review", trace_id)
            self.record_unconfigured_debug(task_type, trace_id, prompt)
            result = self._mock_document_review(source_text, document_type)
            result["prompt"] = prompt
            return result

        body = self.post_task(
            task_type,
            trace_id,
            {},
            prompt,
            timeout_seconds=max(self.settings.timeout_seconds, DOCUMENT_REVIEW_TIMEOUT_SECONDS),
        )

        parsed = parse_document_review_answer(extract_answer(body))
        logger.info("traceId=%s provider=enterprise-dify-chat task=word.document_review", trace_id)
        return {
            "summary": parsed["summary"],
            "issues": parsed["issues"],
            "rawAnswer": parsed.get("rawAnswer", ""),
            "parseFallbackReason": parsed.get("parseFallbackReason", ""),
            "provider": "enterprise-dify-chat/{0}".format(self.get_auth_source_for_task(task_type)),
            "prompt": prompt,
            "conversationId": body.get("conversation_id", ""),
            "messageId": body.get("message_id", ""),
        }

    def format_review_roles(self, trace_id: str, input_data: Dict, prompt: str) -> Dict:
        return self.post_task(
            "word.format_review",
            trace_id,
            input_data,
            prompt,
            timeout_seconds=min(self.settings.timeout_seconds, FORMAT_REVIEW_ROLE_TIMEOUT_SECONDS),
        )

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

    def _mock_document_review(self, text: str, document_type: str) -> Dict:
        issues: List[Dict] = []
        vague_terms = ["相关", "等", "尽快", "友好", "高效", "优化", "合理", "多种", "必要时"]
        for term in vague_terms:
            if term in text:
                issues.append(
                    {
                        "category": "expression",
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
                    "category": "professional",
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
                    "category": "professional",
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
                    "category": "professional",
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
                    "category": "professional",
                    "severity": "medium",
                    "location": "测试说明",
                    "originalText": "",
                    "problem": "测试大纲和细则可能缺少测试范围、前置条件、测试步骤或预期结果。",
                    "suggestion": "补充测试范围、测试数据、前置条件、执行步骤、预期结果和通过准则。",
                    "suggestedRewrite": "",
                }
            )

        summary = (
            "当前使用 mock 文档审查，发现 {0} 项可能影响理解、交付或验收的问题。".format(len(issues))
            if issues else
            "当前使用 mock 文档审查，未发现明显问题。"
        )
        return {
            "summary": summary,
            "issues": issues,
            "provider": "mock",
        }
