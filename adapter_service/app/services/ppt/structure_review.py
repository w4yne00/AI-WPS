import re
from copy import deepcopy
from typing import Callable, Dict, List, Optional, Tuple

from app.core.errors import AdapterError
from app.core.models import PptStructureReviewRequest
from app.services.provider_client import ProviderClient


PPT_STRUCTURE_MAX_SLIDES = 60
PPT_STRUCTURE_BODY_FALLBACK_MAX_CHARS = 120
PPT_STRUCTURE_BODY_FALLBACK_MAX_SLIDES = 10
PPT_STRUCTURE_LONG_TITLE_CHARS = 30
_NUMBERED_TITLE = re.compile(r"^\s*(\d{1,3})(?:[.、．)）\s]|$)")


def _copy_request(request: PptStructureReviewRequest) -> PptStructureReviewRequest:
    if hasattr(request, "model_copy"):
        return request.model_copy(deep=True)
    if hasattr(request, "copy"):
        return request.copy(deep=True)
    return deepcopy(request)


def normalize_structure_request(
    request: PptStructureReviewRequest,
) -> PptStructureReviewRequest:
    normalized = _copy_request(request)
    scope = normalized.scope
    if scope.total_slides < 1 or scope.start_slide < 1 or scope.end_slide < 1:
        raise AdapterError(
            "PPT_STRUCTURE_PAGE_INVALID",
            "起始页和结束页必须为正整数。",
            status_code=400,
        )
    if scope.end_slide < scope.start_slide:
        raise AdapterError(
            "PPT_STRUCTURE_RANGE_REVERSED",
            "结束页不能小于起始页。",
            status_code=400,
        )
    if (
        scope.start_slide > scope.total_slides
        or scope.end_slide > scope.total_slides
    ):
        raise AdapterError(
            "PPT_STRUCTURE_PAGE_OUT_OF_RANGE",
            "起止页必须在 1 至 {0} 页之间。".format(scope.total_slides),
            status_code=400,
        )
    range_size = scope.end_slide - scope.start_slide + 1
    if range_size > PPT_STRUCTURE_MAX_SLIDES:
        raise AdapterError(
            "PPT_STRUCTURE_RANGE_TOO_LARGE",
            "单次结构审查最多支持 60 页，请明确选择不超过 60 页的起止范围。",
            status_code=400,
        )
    expected_indexes = list(range(scope.start_slide, scope.end_slide + 1))
    actual_indexes = [slide.index for slide in normalized.slides]
    if actual_indexes != expected_indexes:
        raise AdapterError(
            "PPT_STRUCTURE_SLIDES_INCOMPLETE",
            "结构审查读取的页码与请求范围不一致，请重新读取后再试。",
            status_code=400,
        )

    fallback_count = 0
    for slide in normalized.slides:
        slide.title = slide.title.strip()[:200]
        slide.subtitle = slide.subtitle.strip()[:300]
        fallback = slide.body_fallback.strip()
        if slide.title:
            slide.body_fallback = ""
            slide.body_fallback_omitted = False
            continue
        fallback_count += 1
        if fallback_count > PPT_STRUCTURE_BODY_FALLBACK_MAX_SLIDES:
            slide.body_fallback = ""
            slide.body_fallback_omitted = True
            continue
        slide.body_fallback_omitted = False
        slide.body_fallback = fallback[:PPT_STRUCTURE_BODY_FALLBACK_MAX_CHARS]
    return normalized


def inspect_structure_titles(request: PptStructureReviewRequest) -> Dict[str, List[Dict]]:
    high_priority = []
    general = []
    titles: Dict[str, List[int]] = {}
    numbered: List[Tuple[int, int]] = []
    for slide in request.slides:
        title = slide.title.strip()
        if not title:
            if slide.body_fallback_omitted:
                high_priority.append(
                    {
                        "source": "local",
                        "code": "missing_title_information_insufficient",
                        "message": "第 {0} 页无主标题，且已达到 {1} 页正文兜底上限，信息不足。".format(
                            slide.index,
                            PPT_STRUCTURE_BODY_FALLBACK_MAX_SLIDES,
                        ),
                        "slideNumbers": [slide.index],
                    }
                )
                continue
            high_priority.append(
                {
                    "source": "local",
                    "code": "missing_title",
                    "message": "第 {0} 页缺少主标题。".format(slide.index),
                    "slideNumbers": [slide.index],
                }
            )
            continue
        titles.setdefault(title.casefold(), []).append(slide.index)
        if len(title) > PPT_STRUCTURE_LONG_TITLE_CHARS:
            general.append(
                {
                    "source": "local",
                    "code": "long_title",
                    "message": "第 {0} 页主标题超过 {1} 个字符，建议压缩为单一判断。".format(
                        slide.index, PPT_STRUCTURE_LONG_TITLE_CHARS
                    ),
                    "slideNumbers": [slide.index],
                }
            )
        match = _NUMBERED_TITLE.match(title)
        if match:
            numbered.append((slide.index, int(match.group(1))))

    for title, pages in titles.items():
        if len(pages) > 1:
            high_priority.append(
                {
                    "source": "local",
                    "code": "duplicate_title",
                    "message": "第 {0} 页主标题完全重复：{1}。".format(
                        "、".join(str(page) for page in pages), title
                    ),
                    "slideNumbers": pages,
                }
            )

    for position in range(1, len(numbered)):
        previous_page, previous_number = numbered[position - 1]
        page, number = numbered[position]
        if number > previous_number + 1:
            general.append(
                {
                    "source": "local",
                    "code": "numbering_gap",
                    "message": "第 {0} 页到第 {1} 页的标题编号从 {2} 跳到 {3}。".format(
                        previous_page, page, previous_number, number
                    ),
                    "slideNumbers": [previous_page, page],
                }
            )
    return {"highPriorityIssues": high_priority, "generalSuggestions": general}


def _normalize_page_list(
    value,
    start_slide: int,
    end_slide: int,
    excluded_pages=None,
) -> List[int]:
    if not isinstance(value, list):
        return []
    excluded = excluded_pages or set()
    normalized = []
    for page in value:
        try:
            number = int(page)
        except (TypeError, ValueError):
            continue
        if (
            start_slide <= number <= end_slide
            and number not in excluded
            and number not in normalized
        ):
            normalized.append(number)
    return normalized


def _normalize_finding(
    value: Dict,
    default_source: str,
    start_slide: int,
    end_slide: int,
    excluded_pages=None,
) -> Optional[Dict]:
    if not isinstance(value, dict):
        return None
    message = str(value.get("message", "") or "").strip()
    if not message:
        return None
    pages = value.get("slideNumbers")
    normalized_pages = _normalize_page_list(
        pages,
        start_slide,
        end_slide,
        excluded_pages=excluded_pages,
    )
    if isinstance(pages, list) and pages and not normalized_pages:
        return None
    return {
        "source": str(value.get("source") or default_source),
        "code": str(value.get("code") or "semantic_review"),
        "message": message,
        "slideNumbers": normalized_pages,
    }


def _finding_semantic_key(item: Dict) -> str:
    code = str(item.get("code", "") or "").casefold()
    message = str(item.get("message", "") or "").casefold()
    combined = "{0} {1}".format(code, message)
    if (
        re.search(r"(?:missing|absent|empty)[_-]?(?:title|heading)", code)
        or re.search(r"(?:title|heading)[_-]?(?:missing|absent|empty)", code)
        or re.search(r"(?:title|heading)[_-]?(?:needed|required)", code)
        or re.search(r"(?:need|require)[s]?[_-]?(?:title|heading)", code)
        or re.search(r"(?:缺少|没有|无|缺失)主?标题|主?标题(?:缺少|没有|缺失|为空)", message)
        or re.search(r"(?:需要|建议|请).{0,8}(?:补充|添加|增加|设置).{0,6}(?:页面)?主?标题", message)
    ):
        return "missing_title"
    if (
        re.search(r"duplicate[d]?[_-]?(?:title|heading)", code)
        or re.search(r"(?:title|heading)[_-]?duplicate[d]?", code)
        or re.search(r"主?标题.{0,8}(?:完全)?重复|重复.{0,8}主?标题", message)
    ):
        return "duplicate_title"
    if (
        re.search(r"long[_-]?(?:title|heading)", code)
        or re.search(r"(?:title|heading)[_-]?(?:long|length)", code)
        or re.search(r"主?标题.{0,12}(?:过长|超过.{0,6}字符)", message)
    ):
        return "long_title"
    if (
        "numbering_gap" in code
        or re.search(r"(?:编号|序号).{0,12}(?:跳号|跳到|不连续|缺失)", combined)
    ):
        return "numbering_gap"
    without_pages = re.sub(r"第\s*\d+\s*页", "", message)
    return re.sub(r"[\W_]+", "", without_pages, flags=re.UNICODE)


def _finding_dedup_key(item: Dict) -> Tuple[Tuple[int, ...], str]:
    return (
        tuple(sorted(item.get("slideNumbers", []))),
        _finding_semantic_key(item),
    )


def _merge_findings(
    local_values: List[Dict],
    model_values: List[Dict],
    start_slide: int,
    end_slide: int,
    model_excluded_pages=None,
) -> List[Dict]:
    merged = []
    keys = set()
    for source, values in (("local", local_values), ("model", model_values)):
        for value in values if isinstance(values, list) else []:
            item = _normalize_finding(
                value,
                source,
                start_slide,
                end_slide,
                excluded_pages=(
                    model_excluded_pages if source == "model" else None
                ),
            )
            if item is None:
                continue
            key = _finding_dedup_key(item)
            if key in keys:
                continue
            keys.add(key)
            merged.append(item)
    return merged


def _sanitize_chapters(
    values, start_slide: int, end_slide: int, excluded_pages=None
) -> List[Dict]:
    excluded = excluded_pages or set()
    sanitized = []
    for value in values if isinstance(values, list) else []:
        if not isinstance(value, dict):
            continue
        try:
            chapter_start = int(value.get("startSlide"))
            chapter_end = int(value.get("endSlide"))
        except (TypeError, ValueError):
            continue
        title = str(value.get("title", "") or "").strip()
        if (
            title
            and start_slide <= chapter_start <= chapter_end <= end_slide
            and not any(
                chapter_start <= page <= chapter_end for page in excluded
            )
        ):
            sanitized.append(
                {
                    **value,
                    "title": title,
                    "startSlide": chapter_start,
                    "endSlide": chapter_end,
                }
            )
    return sanitized


def _sanitize_slide_recommendations(
    values, start_slide: int, end_slide: int, excluded_pages=None
) -> List[Dict]:
    excluded = excluded_pages or set()
    sanitized = []
    for value in values if isinstance(values, list) else []:
        if not isinstance(value, dict):
            continue
        try:
            slide_number = int(value.get("slideNumber"))
        except (TypeError, ValueError):
            continue
        suggestion = str(value.get("suggestion", "") or "").strip()
        if (
            suggestion
            and start_slide <= slide_number <= end_slide
            and slide_number not in excluded
        ):
            sanitized.append(
                {**value, "slideNumber": slide_number, "suggestion": suggestion}
            )
    return sanitized


def _sanitize_outline(
    values, start_slide: int, end_slide: int, excluded_pages=None
) -> List[Dict]:
    sanitized = []
    for value in values if isinstance(values, list) else []:
        if not isinstance(value, dict):
            continue
        title = str(value.get("title", "") or "").strip()
        raw_pages = value.get("slideNumbers")
        pages = _normalize_page_list(
            raw_pages,
            start_slide,
            end_slide,
            excluded_pages=excluded_pages,
        )
        if not title or (isinstance(raw_pages, list) and raw_pages and not pages):
            continue
        sanitized.append({**value, "title": title, "slideNumbers": pages})
    return sanitized


def _build_outline_text(outline: List[Dict]) -> str:
    lines = ["推荐目录"]
    for position, item in enumerate(outline if isinstance(outline, list) else [], 1):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "") or "").strip()
        if title:
            lines.append("{0}. {1}".format(item.get("order") or position, title))
    return "\n".join(lines)


class PptStructureReviewer:
    def __init__(self, provider_client: Optional[ProviderClient] = None) -> None:
        self.provider_client = provider_client or ProviderClient()

    def snapshot_task_auth(self) -> Optional[Dict]:
        resolver = getattr(self.provider_client, "resolve_task_auth", None)
        if not callable(resolver):
            return None
        try:
            return deepcopy(resolver("ppt.structure_review"))
        except Exception as exc:
            raise AdapterError(
                "PPT_STRUCTURE_AUTH_SNAPSHOT_FAILED",
                "结构审查工作流配置暂时无法读取，请检查设置后重试。",
                status_code=503,
            ) from exc

    def review(
        self,
        request: PptStructureReviewRequest,
        trace_id: str,
        task_auth: Optional[Dict] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> Dict:
        if progress_callback:
            progress_callback("preparing")
        normalized = normalize_structure_request(request)
        local = inspect_structure_titles(normalized)
        if progress_callback:
            progress_callback("provider_processing")
        kwargs = {}
        if task_auth is not None:
            kwargs["task_auth"] = task_auth
        if progress_callback is not None:
            kwargs["progress_callback"] = progress_callback
        model = self.provider_client.ppt_structure_review(
            normalized,
            trace_id=trace_id,
            **kwargs
        )
        scope = normalized.scope
        omitted_pages = {
            slide.index
            for slide in normalized.slides
            if slide.body_fallback_omitted
        }
        reviewed_range = {
            "startSlide": scope.start_slide,
            "endSlide": scope.end_slide,
            "totalSlides": scope.total_slides,
            "isFullDeck": scope.start_slide == 1 and scope.end_slide == scope.total_slides,
        }
        high = _merge_findings(
            local["highPriorityIssues"],
            model.get("highPriorityIssues", []),
            scope.start_slide,
            scope.end_slide,
            model_excluded_pages=omitted_pages,
        )
        general = _merge_findings(
            local["generalSuggestions"],
            model.get("generalSuggestions", []),
            scope.start_slide,
            scope.end_slide,
            model_excluded_pages=omitted_pages,
        )
        high_keys = {_finding_dedup_key(item) for item in high}
        general = [
            item for item in general if _finding_dedup_key(item) not in high_keys
        ]
        chapters = _sanitize_chapters(
            model.get("inferredChapters", []),
            scope.start_slide,
            scope.end_slide,
            excluded_pages=omitted_pages,
        )
        recommendations = _sanitize_slide_recommendations(
            model.get("slideRecommendations", []),
            scope.start_slide,
            scope.end_slide,
            excluded_pages=omitted_pages,
        )
        outline = _sanitize_outline(
            model.get("recommendedOutline", []),
            scope.start_slide,
            scope.end_slide,
            excluded_pages=omitted_pages,
        )
        review_conclusion = "本次审查第 {0}–{1} 页（演示文稿共 {2} 页）。\n{3}".format(
            scope.start_slide,
            scope.end_slide,
            scope.total_slides,
            str(model.get("overallStoryline", "") or "").strip(),
        ).strip()
        outline_text = _build_outline_text(outline)
        plain_text = "\n\n".join(
            part
            for part in (
                review_conclusion,
                "高优先级问题\n" + "\n".join("- " + item["message"] for item in high),
                "一般建议\n" + "\n".join("- " + item["message"] for item in general),
                outline_text,
            )
            if part.strip()
        )
        return {
            "reviewedRange": reviewed_range,
            "overallStoryline": str(model.get("overallStoryline", "") or "").strip(),
            "inferredChapters": chapters,
            "highPriorityIssues": high,
            "generalSuggestions": general,
            "slideRecommendations": recommendations,
            "recommendedOutline": outline,
            "reviewConclusion": review_conclusion,
            "outlineText": outline_text,
            "plainText": plain_text,
            "rawAnswer": model.get("rawAnswer"),
            "parseFallbackReason": model.get("parseFallbackReason"),
            "provider": model.get("provider", "mock"),
        }
