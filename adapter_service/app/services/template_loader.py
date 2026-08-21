from pathlib import Path
from typing import Dict, List, Optional

from app.core.config import BASE_DIR, load_settings
from app.services.word.format_rule_pack import (
    ACTIVE_RULE_PACK_ID,
    FormatRulePackError,
    FormatRulePackLoader,
)


class TemplateLoader:
    def __init__(
        self,
        template_root: Optional[str] = None,
        rule_pack_loader: Optional[FormatRulePackLoader] = None,
    ) -> None:
        self.template_root = Path(template_root) if template_root else BASE_DIR / load_settings().template_root
        if not self.template_root.is_absolute():
            self.template_root = BASE_DIR / self.template_root
        self.rule_pack_loader = rule_pack_loader or FormatRulePackLoader()

    def list_templates(self) -> List[dict]:
        try:
            metadata = self.rule_pack_loader.list_metadata()
        except FileNotFoundError as exc:
            raise FormatRulePackError("FORMAT_RULE_PACK_REQUIRED") from exc
        return [
            {
                "id": item["templateId"],
                "name": item["name"],
                "path": str(self.rule_pack_loader.active_path),
            }
            for item in metadata
            if item["templateId"] == ACTIVE_RULE_PACK_ID and item["active"] is True
        ]

    def get_template(self, template_id: str) -> Dict:
        try:
            return self.rule_pack_loader.load(template_id)["template"]
        except FileNotFoundError as exc:
            raise FormatRulePackError("FORMAT_RULE_PACK_REQUIRED {0}".format(template_id)) from exc
