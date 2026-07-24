from dataclasses import dataclass
from typing import Sequence, Tuple

from .models import normalize_key


SCENE_LABELS = {
    "auto": "自动匹配",
    "yangqi": "G企技术材料",
    "cybersecurity": "网络安全技术材料",
    "official": "党政公文",
    "disabled": "不使用写作规范",
}

SCENE_PACK_IDS = {
    "yangqi": (
        "yangqi-tech-writing-base",
        "technical-document-style",
    ),
    "cybersecurity": (
        "yangqi-tech-writing-base",
        "technical-document-style",
        "cybersecurity-terminology",
    ),
    "official": (
        "yangqi-tech-writing-base",
        "official-document-style",
    ),
    "disabled": (),
}

_CYBERSECURITY_MARKERS = (
    "网络安全",
    "信息安全",
    "等级保护",
    "等保",
    "访问控制",
    "身份鉴别",
    "安全审计",
    "安全事件",
    "应急响应",
    "漏洞",
    "恶意代码",
    "入侵检测",
    "入侵防御",
    "防火墙",
    "零信任",
    "关键信息基础设施",
)
_OFFICIAL_DECISIVE_MARKERS = (
    "党政公文",
    "公文",
    "主送机关",
    "发文字号",
    "请示",
    "批复",
    "函复",
)
_OFFICIAL_SUPPORTING_MARKERS = (
    "通知",
    "通报",
    "纪要",
    "报送",
    "发文",
    "承办",
)
_TECHNICAL_MARKERS = (
    "技术方案",
    "可行性研究",
    "可研",
    "设计方案",
    "技术规范",
    "招标",
    "投标",
    "验收",
    "测试大纲",
    "系统建设",
    "项目实施",
    "运维方案",
)


@dataclass(frozen=True)
class SceneResolution:
    requested_scene: str
    resolved_scene: str
    auto_fallback: bool
    evidence: Tuple[str, ...]


def _matched_markers(text: str, markers: Sequence[str]) -> Tuple[str, ...]:
    return tuple(marker for marker in markers if normalize_key(marker) in text)


def resolve_scene(requested_scene: str, source_parts: Sequence[str]) -> SceneResolution:
    requested = requested_scene if requested_scene in SCENE_LABELS else "auto"
    if requested != "auto":
        return SceneResolution(requested, requested, False, ())

    source = normalize_key(" ".join(part for part in source_parts if part))
    cybersecurity = _matched_markers(source, _CYBERSECURITY_MARKERS)
    if cybersecurity:
        return SceneResolution("auto", "cybersecurity", False, cybersecurity[:5])

    official_decisive = _matched_markers(source, _OFFICIAL_DECISIVE_MARKERS)
    official_supporting = _matched_markers(source, _OFFICIAL_SUPPORTING_MARKERS)
    if official_decisive or len(official_supporting) >= 2:
        evidence = official_decisive + official_supporting
        return SceneResolution("auto", "official", False, evidence[:5])

    technical = _matched_markers(source, _TECHNICAL_MARKERS)
    if technical:
        return SceneResolution("auto", "yangqi", False, technical[:5])

    return SceneResolution("auto", "yangqi", True, ())
