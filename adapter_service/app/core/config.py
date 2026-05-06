import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


BASE_DIR = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_PATH = BASE_DIR / "config/adapter.json"
EXAMPLE_CONFIG_PATH = BASE_DIR / "config/adapter.example.json"


@dataclass
class AppSettings:
    service_port: int = 18100
    provider_id: str = "enterprise-chat-api"
    provider_name: str = "企业大模型接口"
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


def _normalize_provider_id(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in value.strip())
    return safe or "enterprise-chat-api"


def _default_provider_from_payload(payload: dict) -> dict:
    provider_id = _normalize_provider_id(payload.get("providerId", payload.get("providerType", "enterprise-chat-api")))
    return {
        "id": provider_id,
        "name": payload.get("providerName", "企业大模型接口"),
        "type": payload.get("providerType", "enterprise-chat-api"),
        "baseUrl": payload.get("providerBaseUrl", payload.get("difyBaseUrl", "https://aibot.chinasatnet.com.cn/v1")),
        "apiKeyEnv": payload.get("providerApiKeyEnv", payload.get("difyApiKeyEnv", "ENTERPRISE_AI_API_KEY")),
        "chatPath": payload.get("providerChatPath", "/chat-messages"),
        "mode": payload.get("providerMode", "blocking"),
    }


def normalize_providers(payload: dict) -> List[dict]:
    raw_providers = payload.get("providers")
    if not isinstance(raw_providers, list) or not raw_providers:
        return [_default_provider_from_payload(payload)]

    providers = []
    for index, item in enumerate(raw_providers):
        if not isinstance(item, dict):
            continue
        fallback_id = "provider-{0}".format(index + 1)
        provider_id = _normalize_provider_id(str(item.get("id", fallback_id)))
        providers.append(
            {
                "id": provider_id,
                "name": item.get("name") or provider_id,
                "type": item.get("type", item.get("providerType", "enterprise-chat-api")),
                "baseUrl": item.get("baseUrl", item.get("providerBaseUrl", "")),
                "apiKeyEnv": item.get("apiKeyEnv", item.get("providerApiKeyEnv", "ENTERPRISE_AI_API_KEY")),
                "chatPath": item.get("chatPath", item.get("providerChatPath", "/chat-messages")),
                "mode": item.get("mode", item.get("providerMode", "blocking")),
            }
        )

    return providers or [_default_provider_from_payload(payload)]


def get_active_provider(payload: dict) -> dict:
    providers = normalize_providers(payload)
    active_id = _normalize_provider_id(str(payload.get("activeProviderId", providers[0]["id"])))
    for provider in providers:
        if provider["id"] == active_id:
            return provider
    return providers[0]


def load_config_payload(config_path: Optional[Path] = None) -> dict:
    path = config_path or DEFAULT_CONFIG_PATH
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    if EXAMPLE_CONFIG_PATH.exists():
        return json.loads(EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8"))
    return {}


def save_config_payload(payload: dict, config_path: Optional[Path] = None) -> None:
    path = config_path or DEFAULT_CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def save_provider_base_url(
    base_url: str,
    config_path: Optional[Path] = None,
    provider_id: Optional[str] = None,
    provider_name: Optional[str] = None,
) -> None:
    value = base_url.strip().rstrip("/")
    if not (value.startswith("http://") or value.startswith("https://")):
        raise ValueError("Provider base URL must start with http:// or https://")
    payload = load_config_payload(config_path)
    providers = normalize_providers(payload)
    current_active_id = _normalize_provider_id(str(payload.get("activeProviderId", get_active_provider(payload)["id"])))
    target_id = _normalize_provider_id(provider_id or current_active_id)
    found = False
    for provider in providers:
        if provider["id"] == target_id:
            provider["baseUrl"] = value
            if provider_name and provider_name.strip():
                provider["name"] = provider_name.strip()
            found = True
            break
    if not found:
        providers.append(
            {
                "id": target_id,
                "name": provider_name.strip() if provider_name and provider_name.strip() else target_id,
                "type": "enterprise-chat-api",
                "baseUrl": value,
                "apiKeyEnv": "ENTERPRISE_AI_API_KEY",
                "chatPath": "/chat-messages",
                "mode": "blocking",
            }
        )
    payload["providers"] = providers
    payload["activeProviderId"] = current_active_id
    if target_id == current_active_id:
        payload["providerBaseUrl"] = value
        if provider_name and provider_name.strip():
            payload["providerName"] = provider_name.strip()
    save_config_payload(payload, config_path)


def save_active_provider(provider_id: str, config_path: Optional[Path] = None) -> None:
    target_id = _normalize_provider_id(provider_id)
    payload = load_config_payload(config_path)
    providers = normalize_providers(payload)
    if not any(provider["id"] == target_id for provider in providers):
        raise ValueError("Provider id does not exist: {0}".format(target_id))
    payload["providers"] = providers
    payload["activeProviderId"] = target_id
    active = get_active_provider(payload)
    payload["providerName"] = active["name"]
    payload["providerBaseUrl"] = active["baseUrl"]
    payload["providerType"] = active["type"]
    payload["providerApiKeyEnv"] = active["apiKeyEnv"]
    payload["providerChatPath"] = active["chatPath"]
    payload["providerMode"] = active["mode"]
    save_config_payload(payload, config_path)


def load_settings(config_path: Optional[Path] = None) -> AppSettings:
    path = config_path or DEFAULT_CONFIG_PATH
    if not path.exists():
        path = EXAMPLE_CONFIG_PATH

    if not path.exists():
        return AppSettings()

    payload = json.loads(path.read_text(encoding="utf-8"))
    active_provider = get_active_provider(payload)
    return AppSettings(
        service_port=payload.get("servicePort", 18100),
        provider_id=active_provider["id"],
        provider_name=active_provider["name"],
        provider_type=active_provider["type"],
        provider_base_url=active_provider["baseUrl"],
        provider_api_key_env=active_provider["apiKeyEnv"],
        provider_chat_path=active_provider["chatPath"],
        provider_mode=active_provider["mode"],
        dify_base_url=payload.get("difyBaseUrl", "http://intranet-dify.local/v1"),
        dify_api_key_env=payload.get("difyApiKeyEnv", "DIFY_API_KEY"),
        dify_workflow_id=payload.get("difyWorkflowId", "wps-word-rewrite"),
        log_path=payload.get("logPath", "./logs/adapter.log"),
        template_root=payload.get("templateRoot", "./templates"),
        timeout_seconds=payload.get("timeoutSeconds", 30),
    )
