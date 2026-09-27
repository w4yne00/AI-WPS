import json
import threading
import time
from io import BytesIO
from unittest.mock import patch
import pytest
from app.core.errors import AdapterError

try:
    from fastapi.testclient import TestClient
    from app.main import app
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

SAMPLE_PAGE_RESPONSE = json.dumps({
    "schemaVersion": "ppt.template_page.v1",
    "pageIndex": 2,
    "pageRole": "content",
    "title": "核心架构设计",
    "keyPoints": [
        "分层解耦：采用标准接口与隔离层设计",
        "安全可控：遵循自主可控信创标准要求"
    ],
    "speakerNotes": "本页阐述核心架构设计要点与信创安全考量。",
    "fragmentIds": [],
    "missingItems": [],
    "basisMaterials": []
})


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi required")
def test_fastapi_ppt_template_page_endpoints():
    from app.api import ppt as ppt_api

    client = TestClient(app)

    req = {
        "documentSessionId": "sess_api_test",
        "clientJobId": "cjob_api_1",
        "pageIndex": 2,
        "pageRole": "content",
        "outlineTitle": "核心架构设计",
        "outlineKeyPoints": ["分层解耦", "安全可控"],
        "outlineFragmentIds": [],
    }

    coord = ppt_api.ppt_template_page

    # 1. Start job with provider mock
    with patch.object(coord, "_call_provider_model", return_value=SAMPLE_PAGE_RESPONSE):
        resp = client.post("/ppt/template-page/jobs", json=req)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["taskType"] == "ppt.template_page"
        assert "data" in data
        job_id = data["data"]["jobId"]
        assert job_id

        # Wait for worker thread to complete
        for _ in range(20):
            resp_get = client.get(f"/ppt/template-page/jobs/{job_id}?documentSessionId=sess_api_test")
            assert resp_get.status_code == 200
            data_get = resp_get.json()
            if data_get["data"]["status"] in ("completed", "failed"):
                break
            time.sleep(0.05)

        assert data_get["data"]["status"] == "completed"
        assert data_get["data"]["result"]["title"] == "核心架构设计"
        assert len(data_get["data"]["result"]["keyPoints"]) == 2

    # 2. Session mismatch query
    resp_mismatch = client.get(f"/ppt/template-page/jobs/{job_id}?documentSessionId=other_sess")
    assert resp_mismatch.status_code == 403

    # 3. Cancel already completed job
    resp_cancel = client.post(
        f"/ppt/template-page/jobs/{job_id}/cancel",
        json={"documentSessionId": "sess_api_test"}
    )
    assert resp_cancel.status_code == 200
    data_cancel = resp_cancel.json()
    assert data_cancel["success"] is True
    assert data_cancel["data"]["status"] == "completed"

    # 4. Oversized payload returns 413
    oversized = "a" * (65 * 1024)
    resp_oversized = client.post("/ppt/template-page/jobs", json={
        "documentSessionId": "sess_api_test",
        "clientJobId": "cjob_oversized",
        "instruction": oversized,
    })
    assert resp_oversized.status_code == 413


def test_standalone_ppt_template_page_endpoints():
    import standalone_adapter

    def _invoke(method, path, payload=None):
        raw = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8") if payload is not None else b""
        captured = {}
        handler = object.__new__(standalone_adapter.Handler)
        handler.path = path
        handler.headers = {"Content-Length": str(len(raw))}
        handler.rfile = BytesIO(raw)
        handler._write = lambda status, body: captured.update(status=status, body=body)
        getattr(handler, method)()
        return captured

    req = {
        "documentSessionId": "sess_std_page",
        "clientJobId": "std_cjob_1",
        "pageIndex": 1,
        "pageRole": "content",
        "outlineTitle": "架构总体设计",
        "outlineKeyPoints": ["高内聚", "低耦合"],
        "outlineFragmentIds": [],
    }

    coord = standalone_adapter.PPT_TEMPLATE_PAGE_COORDINATOR

    # 1. Start job with provider mock
    with patch.object(coord, "_call_provider_model", return_value=SAMPLE_PAGE_RESPONSE):
        res_post = _invoke("do_POST", "/ppt/template-page/jobs", req)
        assert res_post["status"] == 200
        body = res_post["body"]
        assert body["success"] is True
        assert body["taskType"] == "ppt.template_page"
        job_id = body["data"]["jobId"]
        assert job_id

        # Query job until completed
        for _ in range(20):
            res_get = _invoke("do_GET", f"/ppt/template-page/jobs/{job_id}?documentSessionId=sess_std_page")
            assert res_get["status"] == 200
            if res_get["body"]["data"]["status"] in ("completed", "failed"):
                break
            time.sleep(0.05)

        assert res_get["body"]["data"]["status"] == "completed"
        assert res_get["body"]["data"]["result"]["title"] == "核心架构设计"

    # 2. Session mismatch
    res_mismatch = _invoke("do_GET", f"/ppt/template-page/jobs/{job_id}?documentSessionId=wrong_sess")
    assert res_mismatch["status"] == 403

    # 3. Cancel
    res_cancel = _invoke("do_POST", f"/ppt/template-page/jobs/{job_id}/cancel", {"documentSessionId": "sess_std_page"})
    assert res_cancel["status"] == 200
    assert res_cancel["body"]["data"]["status"] == "completed"

    # 4. Oversized payload returns 413
    oversized = "x" * (65 * 1024)
    res_oversized = _invoke("do_POST", "/ppt/template-page/jobs", {
        "documentSessionId": "sess_std_page",
        "clientJobId": "std_cjob_oversized",
        "instruction": oversized,
    })
    assert res_oversized["status"] == 413
