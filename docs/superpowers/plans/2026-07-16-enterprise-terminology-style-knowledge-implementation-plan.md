# Word Enterprise Terminology and Style Knowledge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a persistent, locally managed enterprise terminology and writing-style knowledge base that is selectively applied to Word Smart Write, Smart Imitation, and Document Review without changing their existing request, preview, copy, long-job, or writeback behavior.

**Architecture:** A focused `enterprise_knowledge` service package owns SQLite persistence, strict CSV/XLSX parsing, preview tokens, deterministic matching, prompt-block formatting, backups, and diagnostics. Existing Word services call one facade before the current provider methods, pass an optional prompt block into the existing builders, and attach optional `knowledgeUsage` metadata to responses. FastAPI and standalone adapters expose equivalent local management endpoints; only the Word taskpane receives the drill-down management UI and result usage strip.

**Tech Stack:** Python 3.8 standard library (`sqlite3`, `csv`, `zipfile`, `xml.etree.ElementTree`, `base64`, `hashlib`, `tempfile`), FastAPI/Pydantic already in the repository, WPS JS/HTML/CSS ES5-compatible frontend, Node.js contract tests, Python `unittest`, Bash packaging scripts.

---

## Locked File Map

### New adapter files

- `adapter_service/app/services/enterprise_knowledge/__init__.py`: public package exports.
- `adapter_service/app/services/enterprise_knowledge/models.py`: scopes, limits, normalization, domain exceptions, and serializable match/usage data contracts.
- `adapter_service/app/services/enterprise_knowledge/store.py`: SQLite schema, CRUD, uniqueness checks, transactions, CSV export, database snapshots, and three-backup rotation.
- `adapter_service/app/services/enterprise_knowledge/imports.py`: UTF-8 CSV and constrained first-sheet XLSX parsing, shared template columns, template generation, row validation, preview-token storage, and atomic apply orchestration.
- `adapter_service/app/services/enterprise_knowledge/matcher.py`: deterministic term/style scoring, override resolution, budgets, complete-rule truncation, and prompt-block rendering.
- `adapter_service/app/services/enterprise_knowledge/service.py`: singleton facade used by Word tasks and HTTP adapters; converts knowledge failures into explicit degraded usage metadata.
- `adapter_service/app/api/enterprise_knowledge.py`: FastAPI request models and local management/download endpoints.

### New tests

- `adapter_service/tests/test_enterprise_knowledge_store.py`: schema, CRUD, conflicts, rollback, export, backup rotation.
- `adapter_service/tests/test_enterprise_knowledge_imports.py`: CSV/XLSX templates, parsing, safety budgets, preview TTL, conflict handling.
- `adapter_service/tests/test_enterprise_knowledge_matcher.py`: exact matching, aliases, forbidden forms, task-style override, ordering, and budgets.
- `adapter_service/tests/test_enterprise_knowledge_api.py`: FastAPI route functions, response sanitization, download behavior, and request validation.
- `formal-plugin-kit/tests/enterprise-knowledge-word.test.js`: Word-only taskpane source and pure-helper contracts.

### Existing files to modify

- `adapter_service/app/core/models.py`: optional `knowledgeUsage` response schema only; no Word request changes.
- `adapter_service/app/services/provider_client.py`: optional knowledge block parameters in three prompt builders/provider methods and trace-safe diagnostic merge.
- `adapter_service/app/services/word/rewriter.py`: Smart Write knowledge preparation and response metadata.
- `adapter_service/app/services/word/smart_imitator.py`: Smart Imitation knowledge preparation and response metadata.
- `adapter_service/app/services/word/document_reviewer.py`: Document Review knowledge preparation and response metadata while preserving timeout fallback.
- `adapter_service/app/api/word.py`: no route changes; only model serialization compatibility tests may touch this file if required.
- `adapter_service/app/main.py`: register the new FastAPI router and a 7 MB import-preview request limit.
- `adapter_service/standalone_adapter.py`: endpoint parity for GET/POST/PATCH/DELETE and binary downloads.
- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js`: pure normalization, validation, usage-summary, and import-preview view-model helpers.
- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html`: Word-only summary, drill-down views, editor, import page, and result usage strip.
- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css`: compact Word-theme knowledge management and responsive result-strip styles.
- `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`: navigation, CRUD, import/export/download, dirty-state protection, and usage rendering.
- `formal-plugin-kit/tests/taskpane-helpers.test.js`: focused helper assertions where they fit the existing suite.
- `formal-plugin-kit/tests/layout-smoke.test.js`: Word-only presence and Excel/PPT absence contracts.
- `phase1-delivery-kit/installer/install_phase1.sh`: preserve/restore the knowledge database and its three backups.
- `packaging/build_phase1_delivery_kit.sh`: include import templates and enterprise-knowledge operations documentation.
- `adapter_service/tests/test_packaging_scripts.py`: installer and delivery-content contracts.
- `README.md`, `docs/codex-handoff.md`, `docs/operations/enterprise-knowledge-management.md`, and release metadata/cache-busting files: document and publish `v0.19.0-alpha` after all behavior passes.

## Stable Data Contracts

Use these names consistently across tasks:

```python
KNOWLEDGE_SCOPES = (
    "global",
    "word.smart_write",
    "word.smart_imitation",
    "word.document_review",
)

@dataclass(frozen=True)
class KnowledgeMatchResult:
    prompt_block: str
    usage: Dict[str, object]
    matched_item_ids: Tuple[str, ...]
    diagnostic: Dict[str, object] = field(default_factory=dict)

    def diagnostic_patch(self) -> Dict[str, object]:
        return dict(self.diagnostic)

# Public response alias form
{
    "applied": True,
    "degraded": False,
    "degradedReason": "",
    "termMatchCount": 2,
    "styleRuleCount": 1,
    "truncatedCount": 0,
    "matchedItems": [{"id": "term-001", "type": "term", "name": "卫星互联网运营管理平台"}],
}
```

The HTTP item payload is discriminated by `type`:

```json
{
  "type": "term",
  "scope": "global",
  "category": "系统",
  "preferredText": "卫星互联网运营管理平台",
  "aliases": ["卫星网管平台"],
  "forbiddenVariants": ["卫星网管系统"],
  "definition": "统一平台名称",
  "contextKeywords": ["运营", "网管"],
  "priority": "high",
  "enabled": true,
  "note": ""
}
```

```json
{
  "type": "style",
  "scope": "word.smart_write",
  "name": "结论先行",
  "ruleText": "先给出结论，再说明依据。",
  "positiveExample": "总体方案已完成，下一步开展联调。",
  "negativeExample": "经过大量工作，我们终于完成了总体方案。",
  "contextKeywords": ["汇报", "进展"],
  "alwaysApply": false,
  "priority": "medium",
  "enabled": true,
  "note": ""
}
```

---

### Task 1: Add Domain Contracts and Response Models

**Files:**
- Create: `adapter_service/app/services/enterprise_knowledge/__init__.py`
- Create: `adapter_service/app/services/enterprise_knowledge/models.py`
- Modify: `adapter_service/app/core/models.py`
- Test: `adapter_service/tests/test_enterprise_knowledge_matcher.py`
- Test: `adapter_service/tests/test_word_rewrite.py`
- Test: `adapter_service/tests/test_word_smart_imitation.py`
- Test: `adapter_service/tests/test_word_document_review.py`

- [ ] **Step 1: Write failing domain normalization and response compatibility tests**

```python
from app.core.models import RewriteResponseData
from app.services.enterprise_knowledge.models import normalize_key, public_usage


class EnterpriseKnowledgeContractTests(unittest.TestCase):
    def test_normalize_key_collapses_case_width_and_whitespace(self):
        self.assertEqual(normalize_key(" ＡI  平台 "), "ai 平台")

    def test_old_rewrite_response_remains_valid_without_usage(self):
        value = RewriteResponseData(
            originalText="原文", rewrittenText="结果", rewriteMode="rewrite", provider="mock"
        ).dict(by_alias=True)
        self.assertIsNone(value.get("knowledgeUsage"))

    def test_public_usage_never_exposes_rule_text(self):
        usage = public_usage(
            applied=True,
            terms=1,
            styles=0,
            truncated=0,
            matched_items=[{"id": "t1", "type": "term", "name": "标准名", "ruleText": "secret"}],
        )
        self.assertEqual(
            usage["matchedItems"], [{"id": "t1", "type": "term", "name": "标准名"}]
        )
```

- [ ] **Step 2: Run the focused test and verify import/model failures**

Run:

```bash
PYTHONPATH=adapter_service python3 -m unittest adapter_service.tests.test_enterprise_knowledge_matcher adapter_service.tests.test_word_rewrite adapter_service.tests.test_word_smart_imitation adapter_service.tests.test_word_document_review -v
```

Expected: FAIL because `app.services.enterprise_knowledge` and `knowledgeUsage` do not exist.

- [ ] **Step 3: Implement stable constants, normalization, domain error, and public usage shaping**

`models.py` must define `KNOWLEDGE_SCOPES`, `TASK_SCOPES`, `PRIORITIES`, all fixed limits, `KnowledgeError(code, message)`, `normalize_key()` using `unicodedata.normalize("NFKC", value).casefold()` plus whitespace collapse, `KnowledgeMatchResult`, and `public_usage()`. `public_usage()` must cap `matchedItems` at 20 and copy only `id`, `type`, and `name`.

```python
MAX_IMPORT_BYTES = 5 * 1024 * 1024
MAX_IMPORT_ROWS = 5000
MAX_CELL_CHARS = 2000
MAX_XLSX_EXPANDED_BYTES = 20 * 1024 * 1024
MAX_TERM_MATCHES = 30
MAX_STYLE_RULES = 8
MAX_PROMPT_CHARS = 3000
MAX_PUBLIC_MATCHED_ITEMS = 20
PREVIEW_TTL_SECONDS = 600
MAX_DATABASE_BACKUPS = 3
```

- [ ] **Step 4: Add optional aliased Pydantic response fields**

Add `KnowledgeUsageItem` and `KnowledgeUsage` before `RewriteResult`, then add this exact optional field to `RewriteResult` and `DocumentReviewResponseData`:

```python
knowledge_usage: Optional[KnowledgeUsage] = Field(default=None, alias="knowledgeUsage")
```

Do not modify `WordDocumentRequest` or any request option model.

- [ ] **Step 5: Run focused tests and commit**

Run the command from Step 2. Expected: PASS with all existing response tests unchanged.

```bash
git add adapter_service/app/services/enterprise_knowledge/__init__.py adapter_service/app/services/enterprise_knowledge/models.py adapter_service/app/core/models.py adapter_service/tests/test_enterprise_knowledge_matcher.py adapter_service/tests/test_word_rewrite.py adapter_service/tests/test_word_smart_imitation.py adapter_service/tests/test_word_document_review.py
git commit -m "feat: add enterprise knowledge contracts"
```

---

### Task 2: Build the SQLite Store

**Files:**
- Create: `adapter_service/app/services/enterprise_knowledge/store.py`
- Create: `adapter_service/tests/test_enterprise_knowledge_store.py`

- [ ] **Step 1: Write failing store tests for schema, CRUD, and uniqueness**

```python
class EnterpriseKnowledgeStoreTests(unittest.TestCase):
    def test_term_crud_and_cross_field_uniqueness(self):
        with TemporaryDirectory() as tmp:
            store = EnterpriseKnowledgeStore(Path(tmp) / "enterprise_knowledge.db")
            created = store.create_item(term_payload("卫星互联网运营管理平台", ["卫星网管平台"]))
            self.assertEqual(store.list_items("global", "term", "网管")[0]["id"], created["id"])
            with self.assertRaises(KnowledgeError) as raised:
                store.create_item(term_payload("卫星网管平台", []))
            self.assertEqual(raised.exception.code, "term_text_conflict")

    def test_task_style_name_can_override_global_but_is_unique_in_scope(self):
        with TemporaryDirectory() as tmp:
            store = EnterpriseKnowledgeStore(Path(tmp) / "enterprise_knowledge.db")
            store.create_item(style_payload("global", "结论先行"))
            store.create_item(style_payload("word.smart_write", "结论先行"))
            with self.assertRaises(KnowledgeError):
                store.create_item(style_payload("word.smart_write", " 结论先行 "))
```

- [ ] **Step 2: Run and verify failure**

Run: `PYTHONPATH=adapter_service python3 -m unittest adapter_service.tests.test_enterprise_knowledge_store -v`

Expected: FAIL with missing `EnterpriseKnowledgeStore`.

- [ ] **Step 3: Implement schema initialization and JSON-list serialization**

Create the three tables `knowledge_terms`, `style_rules`, and `knowledge_imports` from the design spec. Enable `PRAGMA foreign_keys=ON`, use `sqlite3.Row`, create indexes for `scope`, `enabled`, and normalized names, and store list fields as compact UTF-8 JSON. Every public method opens its own connection through `_connect()` and closes it through a context manager.

Required public methods are `__init__(db_path: Path)`, `summary() -> Dict[str, object]`, `list_items(scope: str, item_type: str, query: str = "") -> List[Dict[str, object]]`, `get_item(item_id: str) -> Dict[str, object]`, `create_item(payload: Dict[str, object]) -> Dict[str, object]`, `update_item(item_id: str, payload: Dict[str, object]) -> Dict[str, object]`, `delete_item(item_id: str) -> Dict[str, object]`, and `enabled_items(task_scope: str) -> Tuple[List[Dict], List[Dict]]`.

- [ ] **Step 4: Enforce deterministic conflict rules inside transactions**

Before term insert/update, compare normalized preferred text, aliases, and forbidden variants against every other term token. Before style insert/update, compare normalized name only within the same scope. Reject task-scoped terms and unknown scopes with `KnowledgeError`; never silently overwrite conflicts.

- [ ] **Step 5: Add rollback and summary tests**

```python
def test_apply_items_rolls_back_every_row_on_failure(self):
    with TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "enterprise_knowledge.db"
        store = EnterpriseKnowledgeStore(db_path)
        valid = term_payload("标准名称", ["旧名称"])
        conflict = term_payload("旧名称", [])
        with self.assertRaises(KnowledgeError):
            store.apply_items_atomically(
                [valid, conflict],
                {"fileName": "terms.csv", "format": "csv", "rowCount": 2},
            )
        self.assertEqual(store.summary()["totalCount"], 0)
        with sqlite3.connect(str(db_path)) as connection:
            import_count = connection.execute("SELECT COUNT(*) FROM knowledge_imports").fetchone()[0]
        self.assertEqual(import_count, 0)

def test_summary_reports_counts_and_latest_update(self):
    with TemporaryDirectory() as tmp:
        store = EnterpriseKnowledgeStore(Path(tmp) / "enterprise_knowledge.db")
        store.create_item(term_payload("标准名称", []))
        store.create_item(style_payload("global", "结论先行"))
        summary = store.summary()
        self.assertEqual(summary["totalCount"], 2)
        self.assertEqual(summary["enabledCount"], 2)
        self.assertEqual(summary["termCount"], 1)
        self.assertEqual(summary["styleCount"], 1)
        self.assertEqual(summary["status"], "ready")
        self.assertTrue(summary["updatedAt"])
```

Implement `apply_items_atomically(items: Sequence[Dict], import_meta: Dict[str, object])`, `record_import(import_meta: Dict[str, object], stats: Dict[str, int])`, and the summary fields used by the taskpane.

- [ ] **Step 6: Run tests and commit**

Run: `PYTHONPATH=adapter_service python3 -m unittest adapter_service.tests.test_enterprise_knowledge_store -v`

Expected: PASS.

```bash
git add adapter_service/app/services/enterprise_knowledge/store.py adapter_service/tests/test_enterprise_knowledge_store.py
git commit -m "feat: persist enterprise knowledge in sqlite"
```

---

### Task 3: Implement Safe CSV/XLSX Templates and Parsing

**Files:**
- Create: `adapter_service/app/services/enterprise_knowledge/imports.py`
- Create: `adapter_service/tests/test_enterprise_knowledge_imports.py`

- [ ] **Step 1: Write failing round-trip template tests**

```python
class EnterpriseKnowledgeImportTests(unittest.TestCase):
    def test_generated_csv_and_xlsx_use_the_same_headers(self):
        csv_rows = parse_csv(generate_csv_template(), "template.csv")
        xlsx_rows = parse_xlsx(generate_xlsx_template(), "template.xlsx")
        self.assertEqual(set(csv_rows[0].keys()), set(IMPORT_COLUMNS))
        self.assertEqual(set(xlsx_rows[0].keys()), set(IMPORT_COLUMNS))

    def test_xlsx_rejects_macros_external_links_and_zip_traversal(self):
        payloads = (macro_workbook_bytes(), external_link_workbook_bytes(), traversal_zip_bytes())
        for payload in payloads:
            with self.assertRaises(KnowledgeError) as raised:
                parse_import_file("bad.xlsx", XLSX_MIME, payload)
            self.assertEqual(raised.exception.code, "unsafe_xlsx")
```

- [ ] **Step 2: Run and verify failure**

Run: `PYTHONPATH=adapter_service python3 -m unittest adapter_service.tests.test_enterprise_knowledge_imports -v`

Expected: FAIL because import functions are absent.

- [ ] **Step 3: Implement one shared column definition and deterministic template bytes**

```python
IMPORT_COLUMNS = (
    "类型", "适用范围", "名称", "标准写法/规则", "别名/禁用写法",
    "推荐示例", "不推荐示例", "关键词", "优先级", "始终应用", "启用", "备注",
)
LIST_SEPARATOR = "|"
```

`generate_csv_template()` returns UTF-8 BOM CSV with one instruction/example row. `generate_xlsx_template()` writes a minimal no-macro `.xlsx` using fixed ZIP member names and XML generated from the same `IMPORT_COLUMNS`; use a fixed ZIP timestamp `(1980, 1, 1, 0, 0, 0)` so repeated builds are byte-stable.

- [ ] **Step 4: Implement strict decoding and first-sheet XLSX parsing**

Required entry point:

```python
def parse_import_file(file_name: str, mime_type: str, content: bytes) -> List[Dict[str, str]]:
    validate_file_size(content)
    suffix = Path(file_name).suffix.lower()
    if suffix == ".csv":
        return parse_csv(content, file_name)
    if suffix == ".xlsx":
        return parse_xlsx(content, file_name)
    raise KnowledgeError("unsupported_import_type", "仅支持 UTF-8 CSV 或标准 XLSX 模板。")
```

Reject formulas, macros, external relationships, merged cells, ZIP absolute/traversal paths, members with suspicious compression ratio, expanded size above 20 MB, more than 5000 data rows, cells above 2000 characters, wrong/missing headers, and non-UTF-8 CSV.

- [ ] **Step 5: Add field mapping and row-validation tests**

Assert exact mapping to the item payload contracts, Chinese boolean values `是/否`, priorities `高/中/低`, allowed scopes, term-global-only behavior, required fields, duplicate rows, and line-numbered Chinese errors.

Implement:

```python
def validate_import_rows(rows: Sequence[Dict[str, str]]) -> Dict[str, object]:
    return {
        "items": valid_items,
        "errors": errors,
        "rowCount": len(rows),
    }
```

- [ ] **Step 6: Run tests and commit**

Run the command from Step 2. Expected: PASS.

```bash
git add adapter_service/app/services/enterprise_knowledge/imports.py adapter_service/tests/test_enterprise_knowledge_imports.py
git commit -m "feat: parse enterprise knowledge templates"
```

---

### Task 4: Add Import Preview, Atomic Apply, Export, and Backups

**Files:**
- Modify: `adapter_service/app/services/enterprise_knowledge/imports.py`
- Modify: `adapter_service/app/services/enterprise_knowledge/store.py`
- Modify: `adapter_service/tests/test_enterprise_knowledge_imports.py`
- Modify: `adapter_service/tests/test_enterprise_knowledge_store.py`

- [ ] **Step 1: Write failing preview-token and backup tests**

```python
class EnterpriseKnowledgeImportLifecycleTests(unittest.TestCase):
    def test_preview_token_expires_and_is_single_use(self):
        clock = FakeClock(1000.0)
        previews = ImportPreviewStore(clock=clock)
        items = [term_payload("标准名称", [])]
        preview = previews.create("terms.csv", items, conflicts=[])
        self.assertEqual(previews.consume(preview["previewToken"])["items"], items)
        with self.assertRaises(KnowledgeError):
            previews.consume(preview["previewToken"])

    def test_successful_import_keeps_only_three_preimport_backups(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = EnterpriseKnowledgeStore(root / "enterprise_knowledge.db")
            for index in range(5):
                store.apply_preview(
                    [term_payload("名称%d" % index, [])],
                    {"fileName": "terms-%d.csv" % index, "format": "csv", "rowCount": 1},
                )
            self.assertEqual(len(list(root.glob("enterprise_knowledge.db.backup-*"))), 3)
```

- [ ] **Step 2: Run and verify failure**

Run both enterprise knowledge test modules. Expected: FAIL for missing preview and backup APIs.

- [ ] **Step 3: Implement in-memory preview storage with injected clock**

`ImportPreviewStore` uses a lock, `secrets.token_urlsafe(24)`, monotonic expiry, and a maximum of 20 live previews. It stores parsed/validated item dictionaries and conflict decisions, never raw bytes or Base64. `get()` supports preview display; `consume()` removes the token before apply so retries cannot duplicate an import.

- [ ] **Step 4: Implement conflict preview and apply selection**

`build_import_preview(store, rows)` returns `newCount`, `updateCount`, `conflictCount`, `errorCount`, `errors`, and conflicts with `rowNumber`, `incomingName`, and `existingItemId`. `apply_import_preview(token, acceptedConflictRows)` imports all valid non-conflicting rows plus only explicitly accepted resolutions. Global term conflicts can only choose `keep_existing` or `skip`; no incoming overwrite option is accepted.

- [ ] **Step 5: Implement snapshot, rotation, CSV export, and backup download source**

Use SQLite backup API, not filesystem copy while a transaction may be active:

```python
with self._connect() as source, sqlite3.connect(str(backup_path)) as target:
    source.backup(target)
```

Create a pre-import snapshot only when the database already exists and the preview has at least one item to write. Rotate backups by parsed timestamp/mtime to three. `export_csv(scope)` returns UTF-8 BOM bytes with the standard import columns. `database_snapshot_bytes()` writes a temporary consistent snapshot, reads bytes, and deletes the temporary file in `finally`.

- [ ] **Step 6: Run tests and commit**

Run:

```bash
PYTHONPATH=adapter_service python3 -m unittest adapter_service.tests.test_enterprise_knowledge_store adapter_service.tests.test_enterprise_knowledge_imports -v
```

Expected: PASS.

```bash
git add adapter_service/app/services/enterprise_knowledge/store.py adapter_service/app/services/enterprise_knowledge/imports.py adapter_service/tests/test_enterprise_knowledge_store.py adapter_service/tests/test_enterprise_knowledge_imports.py
git commit -m "feat: preview and back up knowledge imports"
```

---

### Task 5: Implement Deterministic Matching and Prompt Budgets

**Files:**
- Create: `adapter_service/app/services/enterprise_knowledge/matcher.py`
- Modify: `adapter_service/tests/test_enterprise_knowledge_matcher.py`

- [ ] **Step 1: Write failing matching tests**

Cover these exact cases:

```python
class EnterpriseKnowledgeMatcherTests(unittest.TestCase):
  def test_alias_and_forbidden_variant_match_once_and_prefer_exact_priority(self):
    terms = [term_item("t1", "标准名称", aliases=["旧名称"], forbidden=["错误名称"], priority="high")]
    result = build_match_result(terms, [], "word.smart_write", ["旧名称与错误名称均出现"])
    self.assertEqual(result.usage["termMatchCount"], 1)
    self.assertIn("标准名称", result.prompt_block)

  def test_task_style_replaces_same_named_global_style(self):
    styles = [
        style_item("s1", "global", "结论先行", "全局规则", always_apply=True),
        style_item("s2", "word.smart_write", "结论先行", "任务规则", always_apply=True),
    ]
    result = build_match_result([], styles, "word.smart_write", ["项目汇报"])
    self.assertIn("任务规则", result.prompt_block)
    self.assertNotIn("全局规则", result.prompt_block)

  def test_limits_and_complete_rule_truncation(self):
    terms = [term_item("t%d" % index, "标准名称%d" % index, aliases=["命中%d" % index]) for index in range(35)]
    styles = [style_item("s%d" % index, "global", "规则%d" % index, "完整规则%d" % index, always_apply=True) for index in range(12)]
    source = " ".join("命中%d" % index for index in range(35))
    result = build_match_result(terms, styles, "word.smart_write", [source])
    self.assertLessEqual(result.usage["termMatchCount"], 30)
    self.assertLessEqual(result.usage["styleRuleCount"], 8)
    self.assertLessEqual(len(result.prompt_block), 3000)
    self.assertGreater(result.usage["truncatedCount"], 0)
    self.assertLessEqual(len(result.usage["matchedItems"]), 20)
```

The same test class defines `term_item()` and `style_item()` fixtures that return complete dictionaries using the stable payload contracts. Add separate concrete assertions that an `alwaysApply` style is selected without a keyword and that a keyword-only style is omitted when no keyword matches.

- [ ] **Step 2: Run and verify failure**

Run: `PYTHONPATH=adapter_service python3 -m unittest adapter_service.tests.test_enterprise_knowledge_matcher -v`

Expected: FAIL with missing matcher.

- [ ] **Step 3: Implement normalization and deterministic ranking**

`match_knowledge(terms, styles, task_scope, source_parts)` concatenates non-empty source parts for matching only. Terms match normalized preferred text, aliases, or forbidden variants as literal substrings and deduplicate by item ID. Sort terms by exact preferred/alias/forbidden match class, priority rank, normalized preferred text, then ID. Styles qualify when `alwaysApply` or any context keyword matches; task scope styles outrank global styles, and a task style with the same normalized name removes the global one.

- [ ] **Step 4: Render complete entries under all three budgets**

The required signature is `build_match_result(terms: Sequence[Dict], styles: Sequence[Dict], task_scope: str, source_parts: Sequence[str]) -> KnowledgeMatchResult`.

Build each term/style as an indivisible string. Add terms first, then styles. Stop before an entry would exceed 3000 characters. Count every qualifying item not included due to item or character limits in `truncatedCount`. Empty matches return `applied=True`, zero counts, and an empty `prompt_block`; a storage/matcher failure is handled later by the facade, not here.

- [ ] **Step 5: Assert prompt text preserves generation structure constraints**

The block must start with `企业术语与写作规范（必须遵守）：` and end with: `以上规范不得要求新增原文不存在、用户也未要求的标题、列表、表格或事实。` Document Review uses the same block and tells the model to report violations as `professional` issues.

- [ ] **Step 6: Run tests and commit**

Run the command from Step 2. Expected: PASS.

```bash
git add adapter_service/app/services/enterprise_knowledge/matcher.py adapter_service/tests/test_enterprise_knowledge_matcher.py
git commit -m "feat: match relevant enterprise knowledge"
```

---

### Task 6: Add the Knowledge Facade and Degraded Diagnostics

**Files:**
- Create: `adapter_service/app/services/enterprise_knowledge/service.py`
- Modify: `adapter_service/app/services/enterprise_knowledge/__init__.py`
- Create: `adapter_service/tests/test_enterprise_knowledge_service.py`
- Modify: `adapter_service/app/services/provider_client.py`
- Modify: `adapter_service/tests/test_enterprise_provider.py`

- [ ] **Step 1: Write failing facade and diagnostic sanitization tests**

```python
class BrokenStore:
    def enabled_items(self, task_scope):
        raise OSError("database unavailable")


class EnterpriseKnowledgeServiceTests(unittest.TestCase):
    def test_prepare_failure_returns_explicit_degraded_usage_without_source_text(self):
        service = EnterpriseKnowledgeService(store=BrokenStore())
        result = service.prepare("word.smart_write", ["公司绝密原文"])
        self.assertEqual(result.prompt_block, "")
        self.assertFalse(result.usage["applied"])
        self.assertTrue(result.usage["degraded"])
        self.assertNotIn("公司绝密原文", str(service.diagnostics()))

    def test_provider_debug_merge_requires_matching_trace_and_whitelists_fields(self):
        record_provider_debug({"traceId": "trace-a", "stage": "request"})
        merge_provider_debug("trace-a", {"knowledgeTermCount": 2, "sourceText": "secret"})
        debug = get_last_provider_debug()
        self.assertEqual(debug["knowledgeTermCount"], 2)
        self.assertNotIn("sourceText", debug)
```

- [ ] **Step 2: Run and verify failure**

Run the new service tests and `test_enterprise_provider.py`. Expected: FAIL for missing facade and merge helper.

- [ ] **Step 3: Implement facade construction and singleton path**

```python
def default_database_path() -> Path:
    configured = os.getenv("AI_WPS_ENTERPRISE_KNOWLEDGE_DB", "").strip()
    return Path(configured) if configured else Path(__file__).resolve().parents[4] / "run" / "enterprise_knowledge.db"


```

Implement `get_enterprise_knowledge_service() -> EnterpriseKnowledgeService` as a lock-protected singleton keyed by the resolved database path. `prepare(task_scope, source_parts)` loads enabled global terms plus global/task styles, calls the matcher, records only counts, IDs, elapsed milliseconds, stage, and a short error code. On any knowledge-layer exception it returns an empty block with `applied=false`, `degraded=true`, and Chinese `degradedReason`; it never raises into the Word model task.

- [ ] **Step 4: Implement safe provider-debug merge**

Add `merge_provider_debug(trace_id, patch)` beside `record_provider_debug`. Under the existing lock, merge only when `traceId` matches and only these keys: `knowledgeApplied`, `knowledgeDegraded`, `knowledgeErrorCode`, `knowledgeTermCount`, `knowledgeStyleCount`, `knowledgeTruncatedCount`, `knowledgeElapsedMs`, and `knowledgeItemIds`. Cap IDs at 20. Never include source text, file contents, full rules, paths, or keys.

- [ ] **Step 5: Run tests and commit**

Run:

```bash
PYTHONPATH=adapter_service python3 -m unittest adapter_service.tests.test_enterprise_knowledge_service adapter_service.tests.test_enterprise_provider -v
```

Expected: PASS.

```bash
git add adapter_service/app/services/enterprise_knowledge adapter_service/app/services/provider_client.py adapter_service/tests/test_enterprise_knowledge_service.py adapter_service/tests/test_enterprise_provider.py
git commit -m "feat: add resilient enterprise knowledge service"
```

---

### Task 7: Inject Knowledge into the Three Existing Word Tasks

**Files:**
- Modify: `adapter_service/app/services/provider_client.py`
- Modify: `adapter_service/app/services/word/rewriter.py`
- Modify: `adapter_service/app/services/word/smart_imitator.py`
- Modify: `adapter_service/app/services/word/document_reviewer.py`
- Modify: `adapter_service/tests/test_enterprise_provider.py`
- Modify: `adapter_service/tests/test_word_rewrite.py`
- Modify: `adapter_service/tests/test_word_smart_imitation.py`
- Modify: `adapter_service/tests/test_word_document_review.py`

- [ ] **Step 1: Write failing prompt placement and service integration tests**

For each task, inject a fake knowledge service returning `KnowledgeMatchResult("企业术语区块", usage, ("t1",))`. Assert the provider receives the block and the returned Word result contains identical `knowledgeUsage`. Add a degraded fake and assert the provider still runs with an empty block and returns degraded metadata.

Prompt tests must assert:

```python
assert prompt.index("企业术语与写作规范") < prompt.index("待处理原文：")
assert "不要额外新增原文没有" in prompt  # Smart Write preserved
assert prompt.index("企业术语与写作规范") < prompt.index("仿写模板：")
assert prompt.index("企业术语与写作规范") < prompt.index("待审查内容：")
assert "category 只能使用" in prompt      # Review JSON contract preserved
```

- [ ] **Step 2: Run focused Word tests and verify failure**

Run the four modules listed in Task 1 Step 2. Expected: FAIL because constructors and provider methods do not accept knowledge data.

- [ ] **Step 3: Add optional builder/provider parameters without changing callers by default**

Add `enterprise_knowledge_block: str = ""` to `build_smart_write_prompt`, `build_smart_imitation_prompt`, `build_document_review_prompt`, and the corresponding `ProviderClient` methods. Insert the non-empty block as its own section immediately before the source/template/review content. Existing calls without the argument must generate byte-for-byte equivalent prompts.

- [ ] **Step 4: Integrate the facade at Word service boundaries**

Each constructor accepts `knowledge_service: Optional[EnterpriseKnowledgeService] = None`. Prepare inputs exactly as follows:

```python
# Smart Write
knowledge = self.knowledge_service.prepare(
    "word.smart_write", [source_text, request.options.user_instruction]
)

# Smart Imitation
knowledge = self.knowledge_service.prepare(
    "word.smart_imitation", [template_text, requirement, reference_material]
)

# Document Review
knowledge = self.knowledge_service.prepare(
    "word.document_review", [source_text, document_type, review_prompt]
)
```

Pass `knowledge.prompt_block` to the provider and return `knowledgeUsage: knowledge.usage`. Preserve Smart Write `diffHints`, Smart Imitation preview-only behavior, Document Review provider timeout/fallback/raw-answer behavior, and every existing request field.

- [ ] **Step 5: Merge knowledge diagnostics after provider completion/fallback**

Call `merge_provider_debug(trace_id, knowledge.diagnostic_patch())` after the provider call, including mock and fallback paths. A knowledge failure must not replace the provider request/error stage already stored for that trace.

- [ ] **Step 6: Run tests and commit**

Run:

```bash
PYTHONPATH=adapter_service python3 -m unittest adapter_service.tests.test_enterprise_provider adapter_service.tests.test_word_rewrite adapter_service.tests.test_word_smart_imitation adapter_service.tests.test_word_document_review -v
```

Expected: PASS, including existing Dify input compatibility and long-review fallback assertions.

```bash
git add adapter_service/app/services/provider_client.py adapter_service/app/services/word/rewriter.py adapter_service/app/services/word/smart_imitator.py adapter_service/app/services/word/document_reviewer.py adapter_service/tests/test_enterprise_provider.py adapter_service/tests/test_word_rewrite.py adapter_service/tests/test_word_smart_imitation.py adapter_service/tests/test_word_document_review.py
git commit -m "feat: apply enterprise knowledge to word tasks"
```

---

### Task 8: Expose FastAPI Management and Download Endpoints

**Files:**
- Create: `adapter_service/app/api/enterprise_knowledge.py`
- Modify: `adapter_service/app/main.py`
- Create: `adapter_service/tests/test_enterprise_knowledge_api.py`

- [ ] **Step 1: Write failing direct-route tests**

Test summary/list/create/update/delete, both template downloads, preview/apply, CSV export, DB backup, diagnostics, invalid Base64, declared-size mismatch, unsupported type, expired token, and `KnowledgeError` to `AdapterError` status mapping. Patch `get_enterprise_knowledge_service()` to an isolated temporary store.

```python
request = ImportPreviewRequest(
    fileName="terms.csv",
    mimeType="text/csv",
    sizeBytes=len(csv_bytes),
    contentBase64=base64.b64encode(csv_bytes).decode("ascii"),
)
response = preview_import(request)
self.assertIn("previewToken", response["data"])
```

- [ ] **Step 2: Run and verify failure**

Run: `PYTHONPATH=adapter_service python3 -m unittest adapter_service.tests.test_enterprise_knowledge_api -v`

Expected: FAIL because the router does not exist.

- [ ] **Step 3: Implement Pydantic request models and envelope routes**

Use alias field names from the stable contracts. Implement the exact paths from the spec, including `POST /enterprise-knowledge/imports/preview`, `POST /enterprise-knowledge/imports/apply`, template downloads, `GET /enterprise-knowledge/export.csv`, `GET /enterprise-knowledge/backup`, and `GET /enterprise-knowledge/diagnostics`. Apply exact HTTP mappings: validation `400`, missing item/token `404`, uniqueness conflict `409`, oversized payload `413`, storage corruption/unavailable `503`. All JSON routes use the repository `envelope()` helper and preserve `traceId`/`taskType` conventions.

- [ ] **Step 4: Implement binary responses with safe filenames**

Return FastAPI `Response` for CSV/XLSX/backup with `Content-Disposition` filenames containing only ASCII:

```text
enterprise-knowledge-import-template.csv
enterprise-knowledge-import-template.xlsx
enterprise-knowledge-export.csv
enterprise-knowledge-backup.db
```

- [ ] **Step 5: Register router and request-body limit**

Include `enterprise_knowledge_router` in `app/main.py`. Extend the existing size middleware so only `POST /enterprise-knowledge/imports/preview` permits up to `7 * 1024 * 1024`; do not raise PPT/document-file limits or global limits.

- [ ] **Step 6: Run tests and commit**

Run the API test and `test_health.py`. Expected: PASS.

```bash
git add adapter_service/app/api/enterprise_knowledge.py adapter_service/app/main.py adapter_service/tests/test_enterprise_knowledge_api.py
git commit -m "feat: expose enterprise knowledge api"
```

---

### Task 9: Add Standalone Adapter Endpoint Parity

**Files:**
- Modify: `adapter_service/standalone_adapter.py`
- Modify: `adapter_service/tests/test_enterprise_knowledge_api.py`
- Modify: `adapter_service/tests/test_packaging_scripts.py`

- [ ] **Step 1: Write failing standalone route-contract tests**

Start the standalone handler on an ephemeral local port or call a small extracted dispatch helper. Assert GET summary/template/export/backup/diagnostics, POST item/preview/apply, PATCH item, DELETE item, matching status codes, JSON envelopes, and binary content types.

- [ ] **Step 2: Run and verify failure**

Run the API and packaging tests. Expected: FAIL because standalone routes are absent.

- [ ] **Step 3: Add JSON route parity using the shared service facade**

Parse query parameters with `urllib.parse.parse_qs`. Decode request JSON through existing helpers, then construct the same normalized payloads used by FastAPI. Do not import FastAPI router types into standalone mode. Map `KnowledgeError` through one `_write_knowledge_error()` helper.

- [ ] **Step 4: Add binary response helper and download parity**

Implement `_write_bytes(status, content, content_type, file_name)` with explicit `Content-Length` and `Content-Disposition`. Do not route binary data through JSON `envelope()`.

- [ ] **Step 5: Run tests and commit**

Run:

```bash
PYTHONPATH=adapter_service python3 -m unittest adapter_service.tests.test_enterprise_knowledge_api adapter_service.tests.test_packaging_scripts -v
```

Expected: PASS.

```bash
git add adapter_service/standalone_adapter.py adapter_service/tests/test_enterprise_knowledge_api.py adapter_service/tests/test_packaging_scripts.py
git commit -m "feat: support knowledge api in standalone adapter"
```

---

### Task 10: Add Word Pure Helpers and Result Usage Strip

**Files:**
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`
- Create: `formal-plugin-kit/tests/enterprise-knowledge-word.test.js`
- Modify: `formal-plugin-kit/tests/taskpane-helpers.test.js`

- [ ] **Step 1: Write failing helper and source-contract tests**

```javascript
assert.deepStrictEqual(helpers.normalizeKnowledgeUsage(null), null);
assert.strictEqual(
  helpers.knowledgeUsageSummary({applied: true, termMatchCount: 2, styleRuleCount: 1}, "word.smart_write"),
  "企业知识：已应用 2 条术语、1 条风格规则"
);
assert.strictEqual(
  helpers.knowledgeUsageSummary({applied: false, degraded: true}, "word.document_review"),
  "企业知识未应用，本次结果仅使用模型工作流生成"
);
assert.ok(wordHtml.includes('id="knowledge-usage-strip"'));
assert.ok(!excelHtml.includes('id="knowledge-usage-strip"'));
assert.ok(!pptHtml.includes('id="knowledge-usage-strip"'));
```

- [ ] **Step 2: Run and verify failure**

Run:

```bash
node formal-plugin-kit/tests/taskpane-helpers.test.js
node formal-plugin-kit/tests/enterprise-knowledge-word.test.js
```

Expected: FAIL for missing helpers/DOM.

- [ ] **Step 3: Implement pure usage normalization and safe details rendering data**

Export `normalizeKnowledgeUsage`, `knowledgeUsageSummary`, and `knowledgeUsageDetails`. Clamp counts to non-negative integers, cap details at 20, allow only `term/style`, and treat missing metadata as `null`. Labels are `术语/风格规则`; Smart Write/Imitation use `已应用`, Document Review uses `已检查`.

- [ ] **Step 4: Add the separate strip above result output**

Add a hidden `<section id="knowledge-usage-strip">` between result toolbar and `#result-output`, containing summary text and a native `<details>` list. Render with DOM `textContent`, never concatenate item names into HTML. Missing metadata hides the strip. Degraded metadata shows the warning even with zero counts.

- [ ] **Step 5: Wire all three result paths without touching preview/writeback state**

Call `renderKnowledgeUsage(data.knowledgeUsage, taskType)` from `setSmartWriteResult`, Smart Imitation completion, and `renderDocumentReviewResult`. Clear only the strip when starting/resetting a task. Do not modify `state.rewriteResult`, comparison Markdown, copied text, `pendingApplyAction`, `applyRewrite`, review statuses, review records, or result-output rendering.

- [ ] **Step 6: Run frontend tests and commit**

Run the commands from Step 2 plus `node formal-plugin-kit/tests/layout-smoke.test.js`. Expected: PASS.

```bash
git add formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js formal-plugin-kit/tests/enterprise-knowledge-word.test.js formal-plugin-kit/tests/taskpane-helpers.test.js formal-plugin-kit/tests/layout-smoke.test.js
git commit -m "feat: show enterprise knowledge usage in word"
```

---

### Task 11: Build the Drill-Down Word Knowledge Manager

**Files:**
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`
- Modify: `formal-plugin-kit/tests/enterprise-knowledge-word.test.js`

- [ ] **Step 1: Write failing four-level navigation and validation contracts**

Assert IDs for `enterprise-knowledge-summary-card`, `knowledge-scope-view`, `knowledge-list-view`, `knowledge-editor-view`, one back button per subview, term/style segmented control, search, add icon button with tooltip, overflow menu, advanced `<details>`, and delete confirmation. Assert no enterprise knowledge IDs exist in Excel/PPT taskpanes.

Pure validation cases:

```javascript
assert.deepStrictEqual(
  helpers.validateKnowledgeDraft({type: "term", scope: "word.smart_write"}),
  {ok:false, field:"scope", message:"企业术语首版仅支持全局范围。"}
);
assert.deepStrictEqual(
  helpers.validateKnowledgeDraft({type: "style", scope: "global", name:"", ruleText:""}),
  {ok:false, field:"name", message:"请输入规则名称。"}
);
```

- [ ] **Step 2: Run and verify failure**

Run the enterprise knowledge frontend test. Expected: FAIL.

- [ ] **Step 3: Add compact view markup and one-task-per-level layout**

Settings home receives only the summary card and “进入管理”. Scope view has exactly four rows and a separate batch-import entry. List view has only term/style switch, search, one add icon, list rows, and overflow menu. Editor is full-page; common fields are visible, advanced fields are inside closed `<details>`, and delete is at the bottom.

- [ ] **Step 4: Implement navigation and state with request sequence protection**

Add state keys:

```javascript
knowledgeView: "home",
knowledgeScope: "global",
knowledgeType: "term",
knowledgeItems: [],
knowledgeSummary: null,
knowledgeLoadSequence: 0,
knowledgeMutationBusy: false,
knowledgeEditor: null,
knowledgeEditorDirty: false
```

Every GET increments/compares `knowledgeLoadSequence`; leaving a dirty editor asks for confirmation; save/delete are duplicate-submit protected. Failure to load disables mutation and shows retry instead of treating the list as empty.

- [ ] **Step 5: Implement CRUD and accessible list behavior**

Use the new endpoints, render item text with `textContent`, click a row to edit, preserve search on return, clear sensitive/large draft state on close, and display server conflict messages next to the responsible field. Disable deleting an item while a mutation is pending and require the existing modal pattern for confirmation.

- [ ] **Step 6: Add unsupported-adapter behavior**

If summary returns 404, render the disabled card text `当前 adapter 版本不支持企业知识库` and prevent entry. Network/503 errors render `企业知识库暂不可用` with retry; they must not disable existing Word tasks.

- [ ] **Step 7: Run tests and commit**

Run enterprise knowledge, helper, workflow settings Word, and layout smoke tests. Expected: PASS.

```bash
git add formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js formal-plugin-kit/tests/enterprise-knowledge-word.test.js
git commit -m "feat: manage word enterprise knowledge"
```

---

### Task 12: Add Import, Conflict Review, Template, Export, and Backup UI

**Files:**
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`
- Modify: `formal-plugin-kit/tests/enterprise-knowledge-word.test.js`

- [ ] **Step 1: Write failing import-flow helper and DOM tests**

Test extension/size checks, Base64 request shaping without logging content, preview stats, row error labels, conflict decisions restricted to `keep_existing/skip`, expired-token reset, and required buttons for CSV template, XLSX template, scope CSV export, and full backup.

- [ ] **Step 2: Run and verify failure**

Run the enterprise knowledge frontend test. Expected: FAIL.

- [ ] **Step 3: Implement the dedicated import page**

The page advances through `选择文件 -> 校验 -> 处理冲突 -> 应用`. It accepts one `.csv` or `.xlsx`, checks `file.size <= 5 * 1024 * 1024`, uses `FileReader.readAsArrayBuffer`, converts to Base64 in chunks, posts exactly `fileName/mimeType/sizeBytes/contentBase64`, then releases the ArrayBuffer/Base64 references after the request settles.

- [ ] **Step 4: Implement explicit preview and conflict actions**

Show counts and the first 100 errors/conflicts with total counts. Default every global term conflict to `keep_existing`; allow `skip`; never expose overwrite. Applying sends only `previewToken` and per-row conflict decisions. A 404/410 token response returns to file selection with `导入预览已过期，请重新选择文件。`.

- [ ] **Step 5: Implement browser downloads through adapter URLs**

Use authenticated-free local `fetch`, Blob, and temporary anchor downloads for both templates, current-scope CSV export, and DB backup. Revoke object URLs in `finally`. Do not include API URL, keys, or task results in filenames or request bodies.

- [ ] **Step 6: Run tests and commit**

Run enterprise knowledge, helper, and layout tests. Expected: PASS.

```bash
git add formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js formal-plugin-kit/tests/enterprise-knowledge-word.test.js
git commit -m "feat: add word knowledge import workflow"
```

---

### Task 13: Protect Runtime Data and Include Delivery Documentation

**Files:**
- Modify: `phase1-delivery-kit/installer/install_phase1.sh`
- Modify: `packaging/build_phase1_delivery_kit.sh`
- Modify: `adapter_service/tests/test_packaging_scripts.py`
- Create: `docs/operations/enterprise-knowledge-management.md`
- Modify: `README.md`

- [ ] **Step 1: Write failing installer and package-content tests**

Assert the installer preserves/restores `run/enterprise_knowledge.db` and globbed `run/enterprise_knowledge.db.backup-*` without changing existing URL/key/profile protection. Assert build output includes the operations guide and generated CSV/XLSX import templates.

- [ ] **Step 2: Run and verify failure**

Run: `PYTHONPATH=adapter_service python3 -m unittest adapter_service.tests.test_packaging_scripts -v`

Expected: FAIL for missing knowledge artifacts/protection.

- [ ] **Step 3: Extend installer preservation narrowly**

Copy the live DB and each matching backup into `$ADAPTER_CONFIG_BACKUP/run/`, then restore them after adapter replacement. Quote every path, tolerate no matches, and retain at most the already-existing three backups. Do not alter `config/adapter.json`, `provider_api_key`, or `provider_api_keys` logic.

- [ ] **Step 4: Add deterministic template generation to packaging**

Invoke Python with `PYTHONPATH="$ROOT_DIR/adapter_service"` to call `generate_csv_template()` and `generate_xlsx_template()` into `$TMP_DIR/docs/import-templates/`. This is a mechanical build output, not a new dependency. Add the operations guide to `$TMP_DIR/docs/operations/`.

- [ ] **Step 5: Write operator documentation**

Document scope semantics, template columns and `|` escaping, import limits, conflict handling, backup/export differences, install preservation, degraded behavior, diagnostics privacy, and recovery from a corrupt DB. README should add one concise Word feature section and link to the guide; do not claim Excel/PPT knowledge support.

- [ ] **Step 6: Run tests and commit**

Run packaging tests. Expected: PASS.

```bash
git add phase1-delivery-kit/installer/install_phase1.sh packaging/build_phase1_delivery_kit.sh adapter_service/tests/test_packaging_scripts.py docs/operations/enterprise-knowledge-management.md README.md
git commit -m "docs: package enterprise knowledge management"
```

---

### Task 14: Full Regression, Visual QA, Versioning, and Release Package

**Files:**
- Modify: version/cache metadata files identified by `rg -n "0\.18\.1-alpha|0\.18\.1" formal-plugin-kit adapter-start-kit phase1-delivery-kit config README.md docs/codex-handoff.md`
- Modify: `docs/codex-handoff.md`
- Modify: `README.md`
- Modify: acceptance/release documentation already used by `packaging/build_phase1_delivery_kit.sh`
- Test: all Python and frontend suites

- [ ] **Step 1: Run the complete Python regression suite**

Run:

```bash
PYTHONPATH=adapter_service python3 -m unittest discover adapter_service/tests -v
```

Expected: PASS with no skipped enterprise-knowledge behavior other than dependency-gated API tests in environments lacking existing FastAPI/Pydantic.

- [ ] **Step 2: Run all frontend contract suites**

Run:

```bash
for test_file in formal-plugin-kit/tests/*.test.js; do node "$test_file"; done
```

Expected: every suite exits 0. Verify Excel/PPT tests still assert no Word enterprise-knowledge UI.

- [ ] **Step 3: Run manual adapter smoke checks**

Start the adapter on a free port with a temporary `AI_WPS_ENTERPRISE_KNOWLEDGE_DB`. Create one term and one Smart Write style, call `/word/smart-write`, inspect `/provider/debug-last`, export CSV, download backup, and simulate an unreadable DB. Expected: the normal result has usage counts; the broken DB still returns a model/mock result with explicit degraded metadata; diagnostics contain no source text or rule bodies.

- [ ] **Step 4: Run browser visual QA at both target sizes**

Use the repository dev server and Playwright/agent-browser to capture Word taskpane screenshots at `420x900` and `320x700` for settings summary, scope list, long item list, editor with advanced settings closed/open, import conflicts, normal usage strip, and degraded strip. Check no horizontal scrolling, overlap, clipped long words, nested cards, or oversized headings. Confirm the strip does not push result controls offscreen and advanced fields default closed.

- [ ] **Step 5: Run WPS behavior protection checks**

On a WPS-capable test host, verify Smart Write selection extraction, structured preview, comparison highlighting, copy, and existing writeback; Smart Imitation preview/copy only; Document Review `clientJobId` recovery, issue state, record toggle, and no writeback. Confirm switching named workflows does not change knowledge entries and Excel/PPT Ribbons/taskpanes remain unchanged.

- [ ] **Step 6: Bump release metadata to `v0.19.0-alpha`**

Update all three host taskpane cache parameters/manifests and adapter/start scripts consistently. Set the version rule to `AI-WPS-P1-WORD-EXCEL-PPT-0.19.0-20260716`. Change `packaging/build_phase1_delivery_kit.sh` to produce the versioned name `ai-wps-phase1-delivery-${DATE_TAG}-v0190`. Update handoff with new endpoints, database location/protection, prompt behavior, UI behavior, test commands, and protected logic.

- [ ] **Step 7: Build and inspect one unified delivery package**

Run:

```bash
DATE_TAG=20260716 bash packaging/build_phase1_delivery_kit.sh
tar -tzf dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260716-v0190.tar.gz | sort
shasum -a 256 dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260716-v0190.tar.gz
```

Expected: one package containing Word/Excel/PPT plugins, adapter, installer, both import templates, operations guide, and no runtime database, API key, `.DS_Store`, `__pycache__`, or source-map secrets.

- [ ] **Step 8: Commit only the new release artifact and intended source changes**

Before staging, run `git status --short` and explicitly exclude all unrelated historical `dist-phase1-delivery-kit` deletions/modifications/untracked archives. Earlier tasks already committed implementation files, so this release commit stages only the exact version/document files below and the new dated archive.

```bash
git add README.md docs/codex-handoff.md packaging/build_phase1_delivery_kit.sh adapter-start-kit/scripts/start_uvicorn_adapter.sh phase1-delivery-kit/README.md phase1-delivery-kit/docs/phase1-acceptance-record.md formal-plugin-kit/tests/layout-smoke.test.js formal-plugin-kit/wps-ai-assistant_1.0.0/manifest.json formal-plugin-kit/wps-ai-assistant_1.0.0/ribbon.js formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js formal-plugin-kit/wps-ai-assistant-et_1.0.0/index.html formal-plugin-kit/wps-ai-assistant-et_1.0.0/manifest.json formal-plugin-kit/wps-ai-assistant-et_1.0.0/ribbon.js formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.html formal-plugin-kit/wps-ai-assistant-et_1.0.0/taskpane.js formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/index.html formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/manifest.json formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/ribbon.js formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.html formal-plugin-kit/wps-ai-assistant-wpp_1.0.0/taskpane.js
git add dist-phase1-delivery-kit/ai-wps-phase1-delivery-20260716-v0190.tar.gz
git commit -m "release: package v0.19.0 enterprise knowledge"
```

- [ ] **Step 9: Stop before pushing**

Run `git status --short --branch` and `git log -3 --oneline`. Report the package path, SHA256, tests, visual QA, and remaining historical dirty files. Push `main` only after the user explicitly requests GitHub publication.

---

## Self-Review Checklist

- Every confirmed design requirement maps to a task: storage (2), import/export/backups (3–4, 12–13), matching/budgets (5), degradation/diagnostics (6), three Word tasks (7), both adapter modes (8–9), result feedback (10), drill-down UX (11–12), install protection/release (13–14).
- Existing Word request payloads remain unchanged; only optional response metadata is added.
- Smart Write writeback/comparison, Smart Imitation read-only behavior, Document Review long-job recovery and review record logic are protected by focused and full regression tests.
- Excel and PPT receive no knowledge UI or task integration; layout contracts assert absence.
- No new runtime dependency is introduced; XLSX generation/parsing is standard-library only.
- No plan step defers implementation with unnamed follow-up work or references another task as a substitute for exact behavior.
- Stable names are consistent: `knowledgeUsage`, `degradedReason`, `termMatchCount`, `styleRuleCount`, `truncatedCount`, `matchedItems`, `EnterpriseKnowledgeService.prepare()`, and `KnowledgeMatchResult.prompt_block`.
- The only deliberate spec clarification is covered: template-download endpoints, backup download, and Base64 preview request sizing.
