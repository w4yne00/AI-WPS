"""Safety policy for the dormant Word image-semantics capability.

This module deliberately owns the gate only.  WPS image export and provider
upload are implemented by the follow-up image pipeline; until then, the
closed policy must be observable and must not call either side effect.
"""

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional
from urllib.parse import urlsplit

from app.core.config import load_config_payload, save_config_payload
from app.core.errors import AdapterError


IMAGE_INPUT_MODES = ("disabled", "openai_image_url", "dify_file")
IMAGE_SEMANTICS_DEFAULT_ENABLED = False
IMAGE_SEMANTICS_CONFIG_VERSION = 1
IMAGE_PIXEL_STATUS = "pixel_inspected"
IMAGE_TEXT_STATUS = "text_evidence_only"
IMAGE_NOT_ASSESSABLE_STATUS = "not_assessable"
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
    enabled = runtime.get("enabled") is True and runtime.get("wpsAcceptanceConfirmed") is True
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
    elif runtime.get("wpsAcceptanceConfirmed") is not True:
        reason = "image_semantics_wps_acceptance_required"
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
            }
            for image in images
        ],
    }


class ImageSemanticConfigStore:
    """Persist the product-level image semantic switch without implicit opt-in."""

    def __init__(self, config_path: Path):
        self.config_path = Path(config_path)

    def get(self) -> Dict[str, Any]:
        payload = load_config_payload(self.config_path)
        format_review = payload.get("formatReview") if isinstance(payload.get("formatReview"), dict) else {}
        image_semantics = format_review.get("imageSemantics")
        if not isinstance(image_semantics, dict):
            image_semantics = {}
        return {
            "enabled": image_semantics.get("enabled") is True,
            "wpsAcceptanceConfirmed": image_semantics.get("wpsAcceptanceConfirmed") is True,
            "configVersion": int(image_semantics.get("configVersion") or IMAGE_SEMANTICS_CONFIG_VERSION),
            "updatedAt": str(image_semantics.get("updatedAt") or ""),
        }

    def set_enabled(self, enabled: bool, wps_acceptance_confirmed: bool = False) -> Dict[str, Any]:
        if enabled and not wps_acceptance_confirmed and not self.get()["wpsAcceptanceConfirmed"]:
            raise _error(
                "IMAGE_SEMANTICS_WPS_ACCEPTANCE_REQUIRED",
                "开启图片语义前必须确认目标 WPS 图片导出验收已完成。",
            )
        payload = load_config_payload(self.config_path)
        format_review = payload.get("formatReview")
        if not isinstance(format_review, dict):
            format_review = {}
        current = format_review.get("imageSemantics")
        if not isinstance(current, dict):
            current = {}
        next_config = {
            "enabled": bool(enabled),
            "wpsAcceptanceConfirmed": bool(
                wps_acceptance_confirmed or current.get("wpsAcceptanceConfirmed") is True
            ),
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
    "IMAGE_INPUT_MODES",
    "ImageSemanticConfigStore",
    "ImageSemanticRuntime",
    "collect_image_inventory",
    "image_pixel_policy",
]
