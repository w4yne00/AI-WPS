"""Safety policy for Word image-semantics supplementation.

The product switch defaults on for new installs. Closing it remains an
operations stop: no export slots, no PNG, no pixel upload.
"""

import hashlib
import json
import os
import stat
import struct
import shutil
import time
import uuid
import zlib
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional
from urllib.parse import urlsplit

from app.core.config import load_config_payload, save_config_payload
from app.core.errors import AdapterError


IMAGE_INPUT_MODES = ("disabled", "openai_image_url", "dify_file")
IMAGE_SEMANTICS_DEFAULT_ENABLED = True
IMAGE_SEMANTICS_CONFIG_VERSION = 2
IMAGE_PIXEL_STATUS = "pixel_inspected"
IMAGE_TEXT_STATUS = "text_evidence_only"
IMAGE_NOT_ASSESSABLE_STATUS = "not_assessable"
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_DIMENSION = 8192
MAX_IMAGE_PIXELS = 20_000_000
MAX_IMAGE_GROUP_SIZE = 4
_IMAGE_BLOCK_TYPES = {
    "image",
    "picture",
    "inlinePicture",
    "floatingPicture",
    "inline_image",
    "floating_image",
}


def _error(code: str, message: str, status_code: int = 409) -> AdapterError:
    return AdapterError(code, message, status_code=status_code)


def _service_host(service_base_url: str) -> str:
    try:
        return (urlsplit(str(service_base_url or "")).hostname or "").lower()
    except ValueError:
        return ""


def _image_binding(configuration: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "configVersion": int(configuration.get("configVersion") or 1),
        "serviceHost": _service_host(str(configuration.get("serviceBaseUrl", ""))),
        "accessMethod": str(configuration.get("accessMethod", "")),
        "imageInputMode": str(configuration.get("imageInputMode", "disabled")),
        "modelName": str(configuration.get("modelName", "")),
    }


def _binding_matches(record: Any, binding: Dict[str, Any]) -> bool:
    if not isinstance(record, dict):
        return False
    return all(record.get(key) == value for key, value in binding.items())


def image_pixel_policy(
    runtime_config: Optional[Dict[str, Any]],
    model_configuration: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Return the auditable decision for sending image pixels.

    The result is intentionally false unless every independent safety gate is
    present and bound to the current model configuration revision.
    """

    runtime = runtime_config if isinstance(runtime_config, dict) else {}
    configuration = model_configuration if isinstance(model_configuration, dict) else {}
    mode = str(configuration.get("imageInputMode", "disabled"))
    binding = _image_binding(configuration)
    authorization = configuration.get("imageExternalAuthorization")
    validation = configuration.get("imageSemanticValidation")
    enabled = runtime.get("enabled") is True
    allowed = (
        enabled
        and mode in IMAGE_INPUT_MODES[1:]
        and _binding_matches(authorization, {**binding})
        and bool(authorization.get("authorized"))
        and _binding_matches(validation, {**binding})
        and bool(validation.get("validated"))
    )
    if runtime.get("enabled") is not True:
        reason = "image_semantics_disabled"
    elif mode == "disabled":
        reason = "image_input_mode_disabled"
    elif not _binding_matches(authorization, binding) or not bool((authorization or {}).get("authorized")):
        reason = "image_external_authorization_required"
    elif not _binding_matches(validation, binding) or not bool((validation or {}).get("validated")):
        reason = "image_capability_validation_required"
    else:
        reason = "ready"
    return {
        "allowed": allowed,
        "reason": reason,
        "mode": mode,
        "binding": binding,
        "targetHost": binding["serviceHost"],
    }


def _iter_image_candidates(document_structure: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    structure = document_structure if isinstance(document_structure, dict) else {}
    seen = set()

    def visit(value: Any, image_hint: bool = False) -> Iterable[Dict[str, Any]]:
        if isinstance(value, list):
            for item in value:
                yield from visit(item, image_hint=image_hint)
            return
        if not isinstance(value, dict):
            return
        block_type = str(value.get("blockType") or value.get("type") or "")
        image_id = str(value.get("imageId") or value.get("pictureId") or value.get("objectId") or "")
        is_image = image_hint or block_type in _IMAGE_BLOCK_TYPES or bool(image_id and value.get("isImage"))
        if is_image:
            key = image_id or "inline:{0}".format(
                hashlib.sha256(
                    json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
                ).hexdigest()
            )
            if key not in seen:
                seen.add(key)
                yield value
        for key in ("images", "pictures"):
            nested = value.get(key)
            if isinstance(nested, (list, dict)):
                yield from visit(nested, image_hint=True)
        for key in ("formatBlocks", "blocks", "objects"):
            nested = value.get(key)
            if isinstance(nested, (list, dict)):
                yield from visit(nested, image_hint=False)

    yield from visit(structure)


def _text_evidence_status(image: Dict[str, Any]) -> str:
    alt_text = str(image.get("altText") or image.get("alternativeText") or "").strip()
    nearby = image.get("nearbyText") or image.get("contextText") or image.get("adjacentText") or ""
    if isinstance(nearby, list):
        nearby = " ".join(str(item) for item in nearby)
    if alt_text or str(nearby).strip():
        return IMAGE_TEXT_STATUS
    return IMAGE_NOT_ASSESSABLE_STATUS


def collect_image_inventory(document_structure: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Collect image facts without opening, exporting, or uploading pixels."""

    images = list(_iter_image_candidates(document_structure or {}))
    missing_caption = [
        image for image in images
        if str(image.get("captionStatus") or image.get("figureCaptionStatus") or "").lower()
        in {"missing", "absent", "none"}
    ]
    text_only = sum(1 for image in missing_caption if _text_evidence_status(image) == IMAGE_TEXT_STATUS)
    not_assessable = len(missing_caption) - text_only
    return {
        "imageCount": len(images),
        "supportedImageCount": sum(
            1 for image in images if image.get("supported", image.get("supportedType", True)) is not False
        ),
        "missingFigureCaptionCount": len(missing_caption),
        "textEvidenceOnlyCount": text_only,
        "imageNotAssessableCount": not_assessable,
        "notAssessableCount": not_assessable,
        "pixelExportCount": 0,
        "pixelUploadCount": 0,
        "pixelInspectedCount": 0,
        "imageSemanticStatus": "disabled",
        "imageSemanticReason": "image_semantics_disabled",
        "images": [
            {
                "imageId": str(image.get("imageId") or image.get("pictureId") or image.get("objectId") or ""),
                "captionStatus": str(image.get("captionStatus") or image.get("figureCaptionStatus") or "unknown"),
                "evidenceStatus": _text_evidence_status(image),
                "supported": image.get("supported", image.get("supportedType", True)) is not False,
                "groupId": str(image.get("groupId") or image.get("imageGroupId") or image.get("imageId") or image.get("objectId") or ""),
                "fingerprint": str(image.get("fingerprint") or image.get("objectFingerprint") or ""),
                "altText": str(image.get("altText") or image.get("alternativeText") or "").strip(),
                "nearbyText": " ".join(str(item) for item in image.get("nearbyText", []))
                if isinstance(image.get("nearbyText"), list)
                else str(image.get("nearbyText") or image.get("contextText") or image.get("adjacentText") or "").strip(),
                "associationStatus": str(image.get("associationStatus") or "missing"),
            }
            for image in images
        ],
    }


def select_image_export_groups(
    images: Iterable[Dict[str, Any]], remaining_calls: int
) -> List[List[Dict[str, Any]]]:
    """Select stable, complete image groups eligible for optional caption calls."""

    try:
        call_limit = max(0, int(remaining_calls))
    except (TypeError, ValueError):
        call_limit = 0
    if call_limit == 0:
        return []
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    order: List[str] = []
    for image in images or []:
        if not isinstance(image, dict):
            continue
        caption_status = str(
            image.get("captionStatus") or image.get("figureCaptionStatus") or ""
        ).lower()
        if caption_status not in {"missing", "absent", "none"}:
            continue
        if image.get("supported", image.get("supportedType", True)) is False:
            continue
        if str(image.get("associationStatus") or "").lower() in {"ambiguous", "unmatched"}:
            continue
        image_id = str(
            image.get("imageId") or image.get("pictureId") or image.get("objectId") or ""
        ).strip()
        if not image_id:
            continue
        group_id = str(image.get("groupId") or image.get("imageGroupId") or image_id).strip()
        if group_id not in grouped:
            grouped[group_id] = []
            order.append(group_id)
        grouped[group_id].append(deepcopy(image))
    selected = []
    for group_id in order:
        group = grouped[group_id]
        if len(group) > MAX_IMAGE_GROUP_SIZE:
            continue
        selected.append(group)
        if len(selected) >= call_limit:
            break
    return selected


def _safe_png_dimensions(path: Path) -> Dict[str, int]:
    """Validate the PNG container and return its dimensions without Pillow."""

    try:
        content = path.read_bytes()
    except OSError as exc:
        raise _error("IMAGE_ASSET_FILE_UNREADABLE", "图片导出文件无法读取。", 409) from exc
    if len(content) > MAX_IMAGE_BYTES:
        raise _error("IMAGE_ASSET_SIZE_LIMIT", "图片导出文件超过 5 MiB 上限。", 413)
    signature = b"\x89PNG\r\n\x1a\n"
    if len(content) < len(signature) or content[: len(signature)] != signature:
        raise _error("IMAGE_ASSET_PNG_INVALID", "图片导出文件不是有效 PNG。", 409)
    offset = len(signature)
    width = height = None
    has_iend = False
    iend_end = None
    while offset + 12 <= len(content):
        length = struct.unpack(">I", content[offset : offset + 4])[0]
        chunk_end = offset + 12 + length
        if chunk_end > len(content):
            raise _error("IMAGE_ASSET_PNG_INVALID", "图片导出 PNG 区块不完整。", 409)
        chunk_type = content[offset + 4 : offset + 8]
        chunk_data = content[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack(">I", content[offset + 8 + length : chunk_end])[0]
        if zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF != expected_crc:
            raise _error("IMAGE_ASSET_PNG_INVALID", "图片导出 PNG 校验失败。", 409)
        if chunk_type == b"IHDR":
            if length != 13 or width is not None:
                raise _error("IMAGE_ASSET_PNG_INVALID", "图片导出 PNG 头部无效。", 409)
            width, height = struct.unpack(">II", chunk_data[:8])
            if width <= 0 or height <= 0:
                raise _error("IMAGE_ASSET_DIMENSION_LIMIT", "图片尺寸必须为正数。", 413)
        if chunk_type == b"IEND":
            has_iend = True
            iend_end = chunk_end
            break
        offset = chunk_end
    if width is None or height is None or not has_iend or iend_end != len(content):
        raise _error("IMAGE_ASSET_PNG_INVALID", "图片导出 PNG 缺少完整图像结构。", 409)
    if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
        raise _error("IMAGE_ASSET_DIMENSION_LIMIT", "图片单边超过 8192 像素上限。", 413)
    if width * height > MAX_IMAGE_PIXELS:
        raise _error("IMAGE_ASSET_PIXEL_LIMIT", "图片像素数超过 2,000 万上限。", 413)
    return {"width": width, "height": height, "sizeBytes": len(content)}


class ImageAssetStore:
    """Own short-lived, Adapter-controlled PNG slots for one image group."""

    def __init__(self, staging_root: Path, clock=time.time) -> None:
        self.root = Path(staging_root)
        if not self.root.is_absolute():
            raise _error("IMAGE_ASSET_STORAGE_INVALID", "图片受控槽位必须使用绝对路径。", 500)
        self.clock = clock
        self._groups: Dict[str, Dict[str, Any]] = {}

    def _ensure_root(self) -> None:
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            os.chmod(str(self.root), 0o700)
        except OSError:
            pass

    def allocate_group(
        self,
        snapshot_id: str,
        candidates: List[Dict[str, Any]],
        document_binding: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not isinstance(candidates, list) or not candidates or len(candidates) > MAX_IMAGE_GROUP_SIZE:
            raise _error("IMAGE_ASSET_GROUP_LIMIT", "单个图片对象组必须包含 1 到 4 张图片。")
        normalized = []
        seen = set()
        for candidate in candidates:
            if not isinstance(candidate, dict):
                raise _error("IMAGE_ASSET_GROUP_INVALID", "图片对象组候选格式无效。")
            image_id = str(candidate.get("imageId") or "").strip()
            if not image_id or image_id in seen:
                raise _error("IMAGE_ASSET_GROUP_INVALID", "图片对象组标识必须唯一。")
            seen.add(image_id)
            normalized.append({
                "imageId": image_id,
                "groupId": str(candidate.get("groupId") or candidate.get("imageGroupId") or image_id),
                "fingerprint": str(candidate.get("fingerprint") or candidate.get("objectFingerprint") or ""),
                "captionStatus": str(candidate.get("captionStatus") or "missing"),
            })
        group_id = "image-group-" + uuid.uuid4().hex
        self._ensure_root()
        group_dir = self.root / group_id
        group_dir.mkdir(mode=0o700)
        assets = []
        for index, candidate in enumerate(normalized):
            asset_id = "image-asset-" + uuid.uuid4().hex
            slot_path = group_dir / ("asset-{0}.png".format(index))
            assets.append({
                "assetId": asset_id,
                "imageId": candidate["imageId"],
                "groupId": group_id,
                "fingerprint": candidate["fingerprint"],
                "slotPath": str(slot_path),
                "status": "allocated",
            })
        record = {
            "groupId": group_id,
            "snapshotId": str(snapshot_id),
            "documentBinding": deepcopy(document_binding or {}),
            "candidates": normalized,
            "assets": assets,
            "status": "allocated",
            "createdAt": self.clock(),
        }
        self._groups[group_id] = record
        try:
            self._write_record(record)
        except AdapterError:
            self.delete_group(group_id)
            raise
        return {
            "groupId": group_id,
            "status": "allocated",
            "assets": deepcopy(assets),
            "documentBinding": deepcopy(record["documentBinding"]),
        }

    def commit_group(self, group_id: str, document_binding: Dict[str, Any]) -> Dict[str, Any]:
        record = self._groups.get(str(group_id))
        if not record or record.get("status") != "allocated":
            raise _error("IMAGE_ASSET_GROUP_NOT_FOUND", "图片导出对象组不存在或已清理。", 404)
        if record.get("documentBinding") != (document_binding or {}):
            self.delete_group(group_id)
            raise _error("IMAGE_EXPORT_DOCUMENT_CHANGED", "检测到文档身份或编辑状态变化，已停止图片导出。")
        try:
            for asset in record["assets"]:
                path = self._validate_slot(asset["slotPath"])
                dimensions = _safe_png_dimensions(path)
                asset.update(dimensions)
                asset["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
                asset["pixelEvidenceVerified"] = True
                asset["status"] = "committed"
        except (AdapterError, OSError) as exc:
            self.delete_group(group_id)
            if isinstance(exc, AdapterError):
                raise
            raise _error("IMAGE_ASSET_FILE_UNREADABLE", "图片导出文件无法读取。", 409) from exc
        record["status"] = "committed"
        record["committedAt"] = self.clock()
        try:
            self._write_record(record)
        except AdapterError:
            self.delete_group(group_id)
            raise
        return {
            "groupId": record["groupId"],
            "status": record["status"],
            "assets": deepcopy(record["assets"]),
            "documentBinding": deepcopy(record["documentBinding"]),
        }

    def get_group(self, group_id: str) -> Optional[Dict[str, Any]]:
        record = self._groups.get(str(group_id))
        return deepcopy(record) if record else None

    def delete_group(self, group_id: str) -> None:
        record = self._groups.pop(str(group_id), None)
        if not record:
            return
        group_dir = self.root / str(group_id)
        try:
            shutil.rmtree(str(group_dir))
        except OSError:
            pass

    def cleanup_all(self) -> None:
        for group_id in list(self._groups):
            self.delete_group(group_id)

    def cleanup_snapshot(self, snapshot_id: str) -> None:
        for group_id, record in list(self._groups.items()):
            if str(record.get("snapshotId")) == str(snapshot_id):
                self.delete_group(group_id)

    def _validate_slot(self, slot_path: str) -> Path:
        root = self.root.resolve()
        path = Path(slot_path)
        resolved = path.resolve(strict=False)
        try:
            resolved.relative_to(root)
        except (ValueError, OSError) as exc:
            raise _error("IMAGE_ASSET_PATH_INVALID", "图片槽位路径不在 Adapter 受控目录内。") from exc
        try:
            file_stat = path.lstat()
        except OSError as exc:
            raise _error("IMAGE_ASSET_FILE_UNREADABLE", "图片导出文件不存在。", 409) from exc
        if stat.S_ISLNK(file_stat.st_mode) or not stat.S_ISREG(file_stat.st_mode):
            raise _error("IMAGE_ASSET_PATH_INVALID", "图片槽位必须是非符号链接普通文件。")
        current_uid = getattr(os, "getuid", lambda: file_stat.st_uid)()
        if file_stat.st_uid != current_uid:
            raise _error("IMAGE_ASSET_OWNER_INVALID", "图片槽位文件属主不符合要求。")
        return path

    def _write_record(self, record: Dict[str, Any]) -> None:
        group_dir = self.root / str(record["groupId"])
        record_path = group_dir / "record.json"
        try:
            record_path.write_text(json.dumps(record, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            os.chmod(str(record_path), 0o600)
        except OSError as exc:
            raise _error("IMAGE_ASSET_STORAGE_WRITE_FAILED", "图片受控槽位记录写入失败。", 503) from exc


class ImageSemanticConfigStore:
    """Persist the product-level image semantic switch. Missing data defaults on."""

    def __init__(self, config_path: Path):
        self.config_path = Path(config_path)

    def _key_dir(self) -> Path:
        sibling = self.config_path.parent / "provider_api_keys"
        if sibling.exists():
            return sibling
        from app.core.runtime_paths import resolve_runtime_paths

        return resolve_runtime_paths().api_key_dir

    def _ensure_outbound_overlay(self) -> None:
        from app.services.model_configurations import ModelConfigurationStore

        ModelConfigurationStore(self.config_path, self._key_dir()).list_for_task(
            "word.format_review"
        )

    def get(self) -> Dict[str, Any]:
        self._ensure_outbound_overlay()
        payload = load_config_payload(self.config_path)
        format_review = payload.get("formatReview") if isinstance(payload.get("formatReview"), dict) else {}
        image_semantics = format_review.get("imageSemantics")
        if not isinstance(image_semantics, dict):
            image_semantics = {}
        if "enabled" not in image_semantics:
            enabled = IMAGE_SEMANTICS_DEFAULT_ENABLED
        else:
            enabled = image_semantics.get("enabled") is True
        return {
            "enabled": enabled,
            "configVersion": int(image_semantics.get("configVersion") or IMAGE_SEMANTICS_CONFIG_VERSION),
            "updatedAt": str(image_semantics.get("updatedAt") or ""),
        }

    def set_enabled(self, enabled: bool) -> Dict[str, Any]:
        self._ensure_outbound_overlay()
        payload = load_config_payload(self.config_path)
        format_review = payload.get("formatReview")
        if not isinstance(format_review, dict):
            format_review = {}
        current = format_review.get("imageSemantics")
        if not isinstance(current, dict):
            current = {}
        next_config = {
            "enabled": bool(enabled),
            "configVersion": int(current.get("configVersion") or 0) + 1,
        }
        format_review["imageSemantics"] = next_config
        payload["formatReview"] = format_review
        save_config_payload(payload, self.config_path)
        return self.get()


class ImageSemanticRuntime:
    """Apply the gate around future export and upload callbacks."""

    def __init__(
        self,
        export_picture: Optional[Callable[[Dict[str, Any]], Any]] = None,
        upload_picture: Optional[Callable[[Any], Any]] = None,
    ) -> None:
        self.export_picture = export_picture
        self.upload_picture = upload_picture

    def process_group(
        self,
        candidates: List[Dict[str, Any]],
        runtime_config: Optional[Dict[str, Any]],
        model_configuration: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        policy = image_pixel_policy(runtime_config, model_configuration)
        if not policy["allowed"]:
            statuses = [_text_evidence_status(item) for item in candidates]
            status = IMAGE_TEXT_STATUS if candidates and all(item == IMAGE_TEXT_STATUS for item in statuses) else IMAGE_NOT_ASSESSABLE_STATUS
            return {
                "status": status,
                "reason": policy["reason"],
                "slotCreated": False,
                "pixelExported": False,
                "pixelUploaded": False,
            }
        if not candidates or len(candidates) > 4 or not self.export_picture or not self.upload_picture:
            return {
                "status": IMAGE_NOT_ASSESSABLE_STATUS,
                "reason": "image_pipeline_not_available",
                "slotCreated": False,
                "pixelExported": False,
                "pixelUploaded": False,
            }
        asset = self.export_picture({"candidates": deepcopy(candidates), "binding": policy["binding"]})
        if asset is None:
            return {
                "status": IMAGE_NOT_ASSESSABLE_STATUS,
                "reason": "image_export_failed",
                "slotCreated": True,
                "pixelExported": False,
                "pixelUploaded": False,
            }
        uploaded = self.upload_picture(asset)
        if not uploaded:
            return {
                "status": IMAGE_NOT_ASSESSABLE_STATUS,
                "reason": "image_upload_failed",
                "slotCreated": True,
                "pixelExported": True,
                "pixelUploaded": False,
            }
        return {
            "status": IMAGE_PIXEL_STATUS,
            "reason": "pixel_uploaded",
            "slotCreated": True,
            "pixelExported": True,
            "pixelUploaded": True,
        }


__all__ = [
    "MAX_IMAGE_BYTES",
    "MAX_IMAGE_DIMENSION",
    "MAX_IMAGE_GROUP_SIZE",
    "MAX_IMAGE_PIXELS",
    "IMAGE_INPUT_MODES",
    "ImageAssetStore",
    "ImageSemanticConfigStore",
    "ImageSemanticRuntime",
    "collect_image_inventory",
    "image_pixel_policy",
    "select_image_export_groups",
]
