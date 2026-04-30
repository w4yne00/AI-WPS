from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.provider_client import ProviderClient, clear_local_api_key, save_local_api_key

router = APIRouter()


class ProviderApiKeyRequest(BaseModel):
    api_key: str = Field(alias="apiKey")


@router.get("/provider/status")
def get_provider_status() -> dict:
    client = ProviderClient()
    return {
        "success": True,
        "data": {
            "configured": client.is_configured(),
            "authSource": client.get_auth_source(),
            "providerType": client.settings.provider_type,
        },
    }


@router.post("/provider/api-key")
def save_provider_api_key(request: ProviderApiKeyRequest) -> dict:
    save_local_api_key(request.api_key)
    client = ProviderClient()
    return {
        "success": True,
        "message": "saved",
        "data": {
            "configured": client.is_configured(),
            "authSource": client.get_auth_source(),
        },
    }


@router.delete("/provider/api-key")
def delete_provider_api_key() -> dict:
    clear_local_api_key()
    client = ProviderClient()
    return {
        "success": True,
        "message": "cleared",
        "data": {
            "configured": client.is_configured(),
            "authSource": client.get_auth_source(),
        },
    }
