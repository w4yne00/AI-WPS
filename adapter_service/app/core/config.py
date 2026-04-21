import json
from dataclasses import dataclass
from pathlib import Path


DEFAULT_CONFIG_PATH = Path("config/adapter.json")
EXAMPLE_CONFIG_PATH = Path("config/adapter.example.json")


@dataclass
class AppSettings:
    service_port: int = 18100
    dify_base_url: str = "http://intranet-dify.local/v1"
    dify_api_key_env: str = "DIFY_API_KEY"
    log_path: str = "./logs/adapter.log"
    template_root: str = "./templates"
    timeout_seconds: int = 30


def load_settings(config_path: Path | None = None) -> AppSettings:
    path = config_path or DEFAULT_CONFIG_PATH
    if not path.exists():
        path = EXAMPLE_CONFIG_PATH

    if not path.exists():
        return AppSettings()

    payload = json.loads(path.read_text(encoding="utf-8"))
    return AppSettings(
        service_port=payload.get("servicePort", 18100),
        dify_base_url=payload.get("difyBaseUrl", "http://intranet-dify.local/v1"),
        dify_api_key_env=payload.get("difyApiKeyEnv", "DIFY_API_KEY"),
        log_path=payload.get("logPath", "./logs/adapter.log"),
        template_root=payload.get("templateRoot", "./templates"),
        timeout_seconds=payload.get("timeoutSeconds", 30),
    )
