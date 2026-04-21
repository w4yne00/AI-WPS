from fastapi import APIRouter

from app.services.template_loader import TemplateLoader

router = APIRouter()


@router.get("/templates")
def get_templates() -> dict:
    loader = TemplateLoader()
    return {"success": True, "data": {"templates": loader.list_templates()}}
