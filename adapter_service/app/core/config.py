import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


BASE_DIR = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_PATH = BASE_DIR / "config/adapter.json"
EXAMPLE_CONFIG_PATH = BASE_DIR / "config/adapter.example.json"


@dataclass
class AppSettings:
    service_port: int = 18100
    provider_type: str = "enterprise-chat-api"
    provider_base_url: str = "https://aibot.chinasatnet.com.cn/v1"
    provider_api_key_env: str = "ENTERPRISE_AI_API_KEY"
    provider_chat_path: str = "/chat-messages"
    provider_mode: str = "blocking"
    dify_base_url: str = "http://intranet-dify.local/v1"
    dify_api_key_env: str = "DIFY_API_KEY"
    dify_workflow_id: str = "wps-word-rewrite"
    log_path: str = "./logs/adapter.log"
    template_root: str = "./templates"
    timeout_seconds: int = 30


def load_settings(config_path: Optional[Path] = None) -> AppSettings:
    path = config_path or DEFAULT_CONFIG_PATH
    if not path.exists():
        path = EXAMPLE_CONFIG_PATH

    if not path.exists():
        return AppSettings()

    payload = json.loads(path.read_text(encoding="utf-8"))
    return AppSettings(
        service_port=payload.get("servicePort", 18100),
        provider_type=payload.get("providerType", "enterprise-chat-api"),
        provider_base_url=payload.get("providerBaseUrl", payload.get("difyBaseUrl", "https://aibot.chinasatnet.com.cn/v1")),
        provider_api_key_env=payload.get("providerApiKeyEnv", payload.get("difyApiKeyEnv", "ENTERPRISE_AI_API_KEY")),
        provider_chat_path=payload.get("providerChatPath", "/chat-messages"),
        provider_mode=payload.get("providerMode", "blocking"),
        dify_base_url=payload.get("difyBaseUrl", "http://intranet-dify.local/v1"),
        dify_api_key_env=payload.get("difyApiKeyEnv", "DIFY_API_KEY"),
        dify_workflow_id=payload.get("difyWorkflowId", "wps-word-rewrite"),
        log_path=payload.get("logPath", "./logs/adapter.log"),
        template_root=payload.get("templateRoot", "./templates"),
        timeout_seconds=payload.get("timeoutSeconds", 30),
    )
