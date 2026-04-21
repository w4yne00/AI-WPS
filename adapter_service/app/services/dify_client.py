import os
from typing import Dict

import requests

from app.core.config import load_settings


class DifyClient:
    def __init__(self) -> None:
        self.settings = load_settings()

    def rewrite(self, text: str, mode: str, trace_id: str) -> Dict:
        api_key = os.getenv(self.settings.dify_api_key_env)
        if not api_key:
            return {
                "rewrittenText": self._mock_rewrite(text, mode),
                "provider": "mock",
            }

        response = requests.post(
            "{0}/workflows/run".format(self.settings.dify_base_url.rstrip("/")),
            headers={
                "Authorization": "Bearer {0}".format(api_key),
                "Content-Type": "application/json",
                "X-Trace-Id": trace_id,
            },
            json={
                "inputs": {
                    "text": text,
                    "mode": mode,
                },
                "response_mode": "blocking",
                "user": "wps-ai-assistant",
                "workflow_id": self.settings.dify_workflow_id,
            },
            timeout=self.settings.timeout_seconds,
        )
        response.raise_for_status()
        body = response.json()
        output = body.get("data", {}).get("outputs", {})
        rewritten_text = (
            output.get("rewrittenText")
            or output.get("text")
            or output.get("answer")
            or self._mock_rewrite(text, mode)
        )
        return {
            "rewrittenText": rewritten_text,
            "provider": "dify",
        }

    def _mock_rewrite(self, text: str, mode: str) -> str:
        prefix_map = {
            "rewrite": "Rewritten draft:",
            "polish": "Polished draft:",
            "formalize": "Formalized draft:",
            "continue": "Continued draft:"
        }
        prefix = prefix_map.get(mode, "Rewritten draft:")
        return "{0}\n{text}".format(prefix, text=text.strip())
