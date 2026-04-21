import json
from pathlib import Path
from typing import List, Optional

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
