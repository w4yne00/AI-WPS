import json
from io import BytesIO
import pytest
from app.core.errors import AdapterError
from app.services.ppt.material_store import PptMaterialStore
from app.services.ppt.template_page import (
    PptTemplatePageCoordinator,
    evaluate_template_page_capacity,
)


def test_evaluate_template_page_capacity():
    # Normal case
    normal_points = [
        "分层解耦：采用服务化解耦架构，支撑各模块独立演进与灰度发布",
        "安全可控：全栈适配自主可控基础设施，全面符合等级保护三级安全规范",
        "弹性伸缩：基于动态容器编排与流量调度，保障突发高并发场景平稳可用",
    ]
    res = evaluate_template_page_capacity(normal_points)
    assert res["is_overflow"] is False
    assert res["total_characters"] > 0
    assert res["estimated_lines"] <= 8
    assert res["point_count"] == 3

    # Overflow by point count (> 4)
    too_many_points = ["要点1", "要点2", "要点3", "要点4", "要点5"]
    assert evaluate_template_page_capacity(too_many_points)["is_overflow"] is True

    # Overflow by total characters (> 260)
    huge_point = ["非常非常长的文本内容" * 30]
    assert evaluate_template_page_capacity(huge_point)["is_overflow"] is True


@pytest.fixture
def page_setup(tmp_path):
    store = PptMaterialStore(tmp_path)
    from app.services.long_task_coordinator import LongTaskCoordinator
    coord = PptTemplatePageCoordinator(store=store, coordinator=LongTaskCoordinator())
    return {"store": store, "coord": coord, "tmp_path": tmp_path}


def test_ppt_template_page_submission_validation(page_setup):
    coord = page_setup["coord"]
    # Missing session
    with pytest.raises(AdapterError) as exc:
        coord.submit_job({"clientJobId": "cjob1"})
    assert exc.value.status_code == 422

    # Invalid clientJobId
    with pytest.raises(AdapterError) as exc2:
        coord.submit_job({"documentSessionId": "sess_1", "clientJobId": "??invalid!!"})
    assert exc2.value.status_code == 422


def test_ppt_template_page_generation_lifecycle(page_setup, monkeypatch):
    coord = page_setup["coord"]
    store = page_setup["store"]

    # Seed material in store
    cat = {
        "totalDocuments": 1,
        "totalCharacters": 500,
        "documents": [{"materialId": "mat_1", "fileName": "总体建设方案.docx", "characterCount": 500}],
        "blocks": [
            {"materialId": "mat_1", "blockId": 1, "kind": "heading", "text": "第一章 总体架构"},
            {"materialId": "mat_1", "blockId": 2, "kind": "paragraph", "text": "架构必须分层解耦并达到等保三级。"},
        ],
        "fragments": {
            "1": {
                "fragmentId": 1,
                "materialId": "mat_1",
                "blockId": 2,
                "fileName": "总体建设方案.docx",
                "heading": "第一章 总体架构",
                "text": "架构必须分层解耦并达到等保三级。",
            }
        },
    }
    monkeypatch.setattr(store, "get_catalog", lambda s: cat)

    # Mock provider response
    mock_model_output = {
        "schemaVersion": "ppt.template_page.v1",
        "title": "总体架构设计与安全原则",
        "keyPoints": [
            "分层解耦：采用业务域服务化解耦架构，支撑各模块独立演进与灰度发布",
            "安全可控：全栈适配自主可控基础设施，全面符合等级保护三级安全规范",
        ],
        "speakerNotes": "各位领导，本页展示的是系统总体架构设计。我们严格遵循分层解耦与安全可控原则...",
        "fragmentIds": [1],
        "missingItems": [],
    }

    class DummyProvider:
        def resolve_task_auth(self, *args, **kwargs):
            return {"providerBaseUrl": "http://mock", "apiKey": "mock_key"}

        def post_task(self, *args, **kwargs):
            return {"answer": json.dumps(mock_model_output)}

    coord.provider = DummyProvider()

    req = {
        "documentSessionId": "sess_ppt_test",
        "clientJobId": "cjob_page_1",
        "pageIndex": 3,
        "pageRole": "content",
        "outlineTitle": "总体架构设计",
        "outlineKeyPoints": ["分层解耦", "安全可控"],
        "outlineFragmentIds": [1],
        "instruction": "重点强调安全合规",
        "userFacts": "",
    }

    job = coord.submit_job(req)
    assert job["jobId"]
    assert job["taskType"] == "ppt.template_page"

    # Wait or check completed job
    retrieved = coord.wait_job(job["jobId"], "sess_ppt_test")
    assert retrieved["status"] == "completed"
    res = retrieved["result"]
    assert res["schemaVersion"] == "ppt.template_page.v1"
    assert res["title"] == "总体架构设计与安全原则"
    assert len(res["keyPoints"]) == 2
    assert "speakerNotes" in res
    assert len(res["sources"]) == 1
    assert res["sources"][0]["fileName"] == "总体建设方案.docx"
    assert res["estimatedLines"] > 0
    assert res["totalCharacters"] > 0
    assert len(res["basisMaterials"]) == 1


def test_ppt_template_page_fake_fragment_id_rejected(page_setup, monkeypatch):
    coord = page_setup["coord"]
    store = page_setup["store"]
    monkeypatch.setattr(store, "get_catalog", lambda s: {"fragments": {}})

    fake_output = {
        "schemaVersion": "ppt.template_page.v1",
        "title": "架构页",
        "keyPoints": ["要点一"],
        "speakerNotes": "讲稿",
        "fragmentIds": [9999],  # does not exist
        "missingItems": [],
    }

    class DummyProvider:
        def resolve_task_auth(self, *args, **kwargs):
            return {"providerBaseUrl": "http://mock", "apiKey": "mock_key"}

        def post_task(self, *args, **kwargs):
            return {"answer": json.dumps(fake_output)}

    coord.provider = DummyProvider()

    req = {
        "documentSessionId": "sess_ppt_test",
        "clientJobId": "cjob_fake",
        "pageIndex": 2,
        "outlineTitle": "测试",
        "outlineKeyPoints": ["要点"],
    }

    job = coord.submit_job(req)
    retrieved = coord.wait_job(job["jobId"], "sess_ppt_test")
    assert retrieved["status"] == "failed"
    assert "出处片段编号不存在" in retrieved["error"]["message"]


def test_agenda_and_cover_use_template_slots_without_truncation(page_setup, monkeypatch):
    coord = page_setup["coord"]
    store = page_setup["store"]
    monkeypatch.setattr(store, "get_catalog", lambda s: {"documents": [], "fragments": {}, "blocks": []})

    class DummyProvider:
        def resolve_task_auth(self, *args, **kwargs):
            return {"providerBaseUrl": "http://mock", "apiKey": "mock_key"}

        def post_task(self, *args, **kwargs):
            role = json.loads(kwargs["query"])["pageRole"]
            points = ["架构", "路径", "保障", "多余目录"] if role == "agenda" else ["副标题", "不应静默丢弃"]
            return {"answer": json.dumps({
                "schemaVersion": "ppt.template_page.v1",
                "title": "目录" if role == "agenda" else "封面",
                "keyPoints": points,
                "speakerNotes": "讲稿",
                "fragmentIds": [],
                "missingItems": [],
            })}

    coord.provider = DummyProvider()
    agenda = coord.wait_job(coord.submit_job({
        "documentSessionId": "sess_role",
        "clientJobId": "agenda_slots",
        "pageIndex": 2,
        "pageRole": "agenda",
        "outlineTitle": "目录",
        "outlineKeyPoints": ["架构", "路径", "保障", "多余目录"],
    })["jobId"], "sess_role")
    assert agenda["status"] == "completed"
    assert agenda["result"]["isOverflow"] is True
    assert len(agenda["result"]["keyPoints"]) == 4

    cover = coord.wait_job(coord.submit_job({
        "documentSessionId": "sess_role",
        "clientJobId": "cover_slots",
        "pageIndex": 1,
        "pageRole": "cover",
        "outlineTitle": "封面",
        "outlineKeyPoints": ["副标题"],
    })["jobId"], "sess_role")
    assert cover["result"]["isOverflow"] is True
    assert cover["result"]["keyPoints"] == ["副标题", "不应静默丢弃"]


def test_explicit_newlines_count_against_template_capacity():
    points = [('一\n' * 12).strip(), ('二\r\n' * 12).strip()]
    capacity = evaluate_template_page_capacity(points)
    assert capacity['estimated_lines'] == 24
    assert capacity['is_overflow'] is True


def test_submission_returns_before_provider_and_cancellation_survives_late_result(tmp_path):
    import threading
    from app.services.long_task_coordinator import LongTaskCoordinator
    coord = PptTemplatePageCoordinator(store=PptMaterialStore(tmp_path), coordinator=LongTaskCoordinator())
    entered, release, returned = threading.Event(), threading.Event(), threading.Event()
    submitted = {}

    def provider(*args, **kwargs):
        entered.set()
        assert release.wait(3), 'test provider was not released'
        return json.dumps({'schemaVersion': 'ppt.template_page.v1', 'title': '标题', 'keyPoints': ['要点'], 'speakerNotes': '讲稿'})

    coord._call_provider_model = provider

    def submit():
        submitted.update(coord.submit_job({'documentSessionId': 'sess', 'clientJobId': 'async_page'}))
        returned.set()

    worker = threading.Thread(target=submit)
    worker.start()
    try:
        assert entered.wait(2)
        assert returned.wait(0.5), 'submission blocked on provider'
        job_id = submitted['jobId']
        cancel = coord.cancel_job(job_id, 'sess')
        assert cancel['status'] == 'cancelled' or cancel.get('cancelRequested')
    finally:
        release.set()
        worker.join(3)
    final = coord.wait_job(job_id, 'sess')
    assert final['status'] == 'cancelled'
    assert final.get('result') is None


@pytest.fixture
def shared_outline_model(tmp_path, monkeypatch):
    from app.core.config import AppSettings
    from app.services.direct_services import DirectServiceStore
    from app.services.long_task_coordinator import LongTaskCoordinator
    from app.services.model_configurations import ModelConfigurationStore
    from app.services.provider_client import ProviderClient

    config = tmp_path / "adapter.json"
    config.write_text("{}\n", encoding="utf-8")
    services = DirectServiceStore(config, tmp_path / "keys")
    service = services.create_service(
        name="大纲共用服务", service_base_url="https://outline.example/v1",
        default_model="outline-model",
    )
    services.replace_api_key(service["id"], "synthetic-key", expected_revision=1)
    services.activate_direct_service(service["id"], "ppt.material_outline", {
        "serviceId": service["id"], "modelName": "", "temperature": 0,
        "maxOutputTokens": 2000, "contextWindowTokens": 64000,
        "imageInputMode": "openai_image_url",
    })
    provider = ProviderClient(
        AppSettings(), model_configuration_store=ModelConfigurationStore(config, tmp_path / "keys"),
        direct_service_store=services,
    )
    calls = []

    def urlopen(request, timeout, *_):
        calls.append({"url": request.full_url, "body": json.loads(request.data), "timeout": timeout})
        answer = {"schemaVersion": "ppt.template_page.v1", "title": "建设成果",
                  "keyPoints": ["覆盖十二个网点"], "speakerNotes": "建设成果讲稿", "fragmentIds": []}
        body = {"answer": json.dumps(answer)} if request.full_url.endswith("/chat-messages") else {
            "choices": [{"message": {"content": json.dumps(answer)}}]}
        response = BytesIO(json.dumps(body).encode())
        response.status = 200
        return response

    monkeypatch.setattr("app.services.provider_client._open_task_response", urlopen)
    store = PptMaterialStore(tmp_path / "materials")
    coord = PptTemplatePageCoordinator(store=store, provider=provider, coordinator=LongTaskCoordinator())
    return coord, services, service, calls


@pytest.mark.parametrize("role", ["content", "cover", "agenda", "transition"])
def test_template_pages_call_outline_model_with_template_prompt(shared_outline_model, role):
    coord, services, service, calls = shared_outline_model
    job = coord.submit_job({"documentSessionId": "shared", "clientJobId": "page_" + role,
                            "pageRole": role, "outlineTitle": "建设成果", "outlineKeyPoints": ["覆盖十二个网点"]})
    result = coord.wait_job(job["jobId"], "shared")
    assert result["status"] == "completed", result.get("error")
    assert result["taskType"] == "ppt.template_page"
    assert result["result"]["schemaVersion"] == "ppt.template_page.v1"
    assert result["result"]["pageRole"] == role
    assert len(calls) == 1
    assert calls[0]["url"] == "https://outline.example/v1/chat/completions"
    body = calls[0]["body"]
    assert body["model"] == "outline-model"
    assert body["temperature"] == 0
    assert body["max_tokens"] == 2000
    assert "ppt.template_page.v1" in body["messages"][0]["content"]
    assert "ppt.material_outline.v1" not in body["messages"][0]["content"]
    assert json.loads(body["messages"][1]["content"])["pageRole"] == role


def test_template_page_freezes_outline_binding_before_queue_execution(shared_outline_model, monkeypatch):
    import threading
    from app.services.provider_client import get_last_provider_debug
    from app.services.system_prompts import SystemPromptStore
    coord, services, service, calls = shared_outline_model
    prompt = SystemPromptStore().load("ppt.template_page")
    entered, release = threading.Event(), threading.Event()
    run_job = coord._run_job

    def queued(snapshot, progress):
        entered.set()
        assert release.wait(3), "queued page was not released"
        return run_job(snapshot, progress)

    monkeypatch.setattr(coord, "_run_job", queued)
    job = coord.submit_job({"documentSessionId": "shared", "clientJobId": "queued_page"})
    try:
        assert entered.wait(2)
        services.activate_direct_service(service["id"], "ppt.material_outline", {
            "serviceId": service["id"], "modelName": "new-outline-model", "customModel": True,
        })
        monkeypatch.setattr(SystemPromptStore, "load", lambda *args: {
            "content": "Changed prompt after submission", "version": "changed", "hashPrefix": "changed"})
    finally:
        release.set()
    result = coord.wait_job(job["jobId"], "shared")
    assert result["status"] == "completed", result.get("error")
    assert calls[0]["body"]["model"] == "outline-model"
    assert calls[0]["body"]["messages"][0]["content"] == prompt["content"]
    assert get_last_provider_debug()["validation"]["promptVersion"] == prompt["version"]
    assert get_last_provider_debug()["validation"]["promptHashPrefix"] == prompt["hashPrefix"]


def test_template_page_ignores_legacy_independent_binding(shared_outline_model):
    coord, services, service, calls = shared_outline_model
    services.activate_direct_service(service["id"], "ppt.template_page", {
        "serviceId": service["id"], "modelName": "old-independent-model", "customModel": True,
    })
    job = coord.submit_job({"documentSessionId": "shared", "clientJobId": "legacy_page"})
    result = coord.wait_job(job["jobId"], "shared")
    assert result["status"] == "completed", result.get("error")
    assert calls[0]["body"]["model"] == "outline-model"


def test_template_page_missing_outline_binding_does_not_fall_back_to_legacy(shared_outline_model):
    coord, services, service, calls = shared_outline_model
    services.activate_direct_service(service["id"], "ppt.template_page", {
        "serviceId": service["id"], "modelName": "old-independent-model", "customModel": True,
    })
    config = services.config_path
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["activeModelConfigurations"].pop("ppt.material_outline")
    payload["taskModelSelections"].pop("ppt.material_outline")
    config.write_text(json.dumps(payload), encoding="utf-8")
    job = coord.submit_job({"documentSessionId": "shared", "clientJobId": "missing_outline"})
    result = coord.wait_job(job["jobId"], "shared")
    assert result["status"] == "failed"
    assert result["error"]["code"] == "MODEL_CONFIG_INCOMPLETE"
    assert "资料大纲" in result["error"]["message"]
    assert calls == []


def test_template_page_uses_outline_workflow_binding(shared_outline_model):
    coord, services, service, calls = shared_outline_model
    configurations = coord.provider.model_configuration_store
    workflow = configurations.create_configuration(
        "ppt.material_outline", "大纲工作流", "workflow_platform",
        service_base_url="https://workflow.example/v1",
    )
    configurations.replace_api_key(workflow["id"], "synthetic-workflow-key")
    configurations.activate_configuration(workflow["id"])
    job = coord.submit_job({"documentSessionId": "shared", "clientJobId": "workflow_page"})
    result = coord.wait_job(job["jobId"], "shared")
    assert result["status"] == "completed", result.get("error")
    assert result["result"]["schemaVersion"] == "ppt.template_page.v1"
    assert len(calls) == 1
    assert calls[0]["url"] == "https://workflow.example/v1/chat-messages"
    query = calls[0]["body"]["query"]
    assert "ppt.template_page.v1" in query
    assert "ppt.material_outline.v1" not in query
    from app.services.system_prompts import SystemPromptStore
    assert query.count(SystemPromptStore().load("ppt.template_page")["content"]) == 1
    assert json.loads(query.rsplit("\n\n", 1)[1])["pageRole"] == "content"


def test_template_page_applies_outline_context_budget_without_counting_prompt_twice(shared_outline_model):
    from app.services.provider_client import get_last_provider_debug
    coord, services, service, calls = shared_outline_model
    services.activate_direct_service(service["id"], "ppt.material_outline", {
        "serviceId": service["id"], "modelName": "", "contextWindowTokens": 3000, "maxOutputTokens": 1000,
    })
    job = coord.submit_job({"documentSessionId": "shared", "clientJobId": "context_page"})
    result = coord.wait_job(job["jobId"], "shared")
    assert result["status"] == "completed", result.get("error")
    assert len(calls) == 1
    assert calls[0]["body"]["max_tokens"] == 1000
    validation = get_last_provider_debug()["validation"]
    assert validation["contextWindowTokens"] == 3000
    assert validation["inputBudgetTokens"] == 1700
