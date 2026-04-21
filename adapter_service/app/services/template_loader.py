import json
from pathlib import Path
from typing import Dict, List, Optional

from app.core.config import load_settings


class TemplateLoader:
    def __init__(self, template_root: Optional[str] = None) -> None:
        settings = load_settings()
        root = template_root or settings.template_root
        self.template_root = Path(root)

    def list_templates(self) -> List[dict]:
        templates: List[dict] = []
        for pattern in ("company/*.json", "general/*.json"):
            for path in sorted(self.template_root.glob(pattern)):
                data = json.loads(path.read_text(encoding="utf-8"))
                templates.append(
                    {
                        "id": data["id"],
                        "name": data.get("name", data["id"]),
                        "path": str(path),
                    }
                )
        return templates

    def get_template(self, template_id: str) -> Dict:
        for pattern in ("company/*.json", "general/*.json"):
            for path in sorted(self.template_root.glob(pattern)):
                data = json.loads(path.read_text(encoding="utf-8"))
                if data["id"] == template_id:
                    return data
        raise FileNotFoundError("Template not found: {0}".format(template_id))
