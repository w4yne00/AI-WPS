# Word Writing Policy Library Implementation Plan

> **Status:** Approved for implementation.
>
> **Design:** [`2026-07-24-writing-policy-library-design.md`](../specs/2026-07-24-writing-policy-library-design.md)
>
> **Supersedes:** [`2026-07-16-enterprise-terminology-style-knowledge-implementation-plan.md`](./2026-07-16-enterprise-terminology-style-knowledge-implementation-plan.md)

**Goal:** Replace the unpublished `enterprise_knowledge` prototype with the first formal `writing_policy` baseline, deliver traceable preset packs plus upgrade-safe organization data, and apply them only to Word Smart Write, Smart Imitation, and Document Review without changing existing business chains.

**Target release:** `v0.20.0-alpha`

**Architecture:** Versioned read-only JSON packs and a local organization SQLite database are merged by a deterministic resolver. Each Word task adds one bounded policy block to its existing single model request, then runs a lightweight nonblocking local audit. FastAPI and `standalone_adapter.py` expose equivalent local management APIs. The Word taskpane provides a compact task selector, result disclosure, and drill-down settings UI. Excel, PPT, Format Review, writeback, polling, timeout, and workflow profile behavior remain unchanged.

**Implementation method:** Test-first, one task at a time. Every task starts with a failing focused test, implements the smallest complete behavior, runs focused tests, then runs affected regression tests. Do not retain `/enterprise-knowledge/*`, `enterprise_knowledge`, `knowledgeUsage`, or old-database migration aliases because this release is the first formal installation baseline.

## Global Constraints

- Do not read candidate content from the dirty `yangqi-tech-writing` worktree. Use `git show v1.1.0:<path>` at commit `d3640165569071251248a5fafb2def6ef2fe2cf4`.
- Do not modify or commit historical delivery archives already dirty in `dist-phase1-delivery-kit/`.
- Do not add a model call, Dify input variable, runtime network dependency, Ribbon button, or Excel/PPT setting.
- Do not modify model timeout, long-job polling, think filtering, Word writeback, or workflow profile selection.
- Do not rebuild an empty organization database after load or migration failure.
- Use `apply_patch` for manual edits and preserve Python 3.8 and ES5-compatible frontend syntax.
- Run `git diff --check` after every task and the complete regression suite before packaging.

## Task 1: Lock the New Naming and Scope Contract

**Files**

- Move: `adapter_service/app/services/enterprise_knowledge/` to `adapter_service/app/services/writing_policy/`
- Move: `adapter_service/app/api/enterprise_knowledge.py` to `adapter_service/app/api/writing_policies.py`
- Modify: `adapter_service/app/main.py`
- Modify: `adapter_service/standalone_adapter.py`
- Modify: `adapter_service/app/core/models.py`
- Modify: `adapter_service/app/services/provider_client.py`
- Modify: `adapter_service/app/services/word/rewriter.py`
- Modify: `adapter_service/app/services/word/smart_imitator.py`
- Modify: `adapter_service/app/services/word/document_reviewer.py`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js`
- Move: `adapter_service/tests/test_enterprise_knowledge_*.py` to `adapter_service/tests/test_writing_policy_*.py`
- Move: `formal-plugin-kit/tests/enterprise-knowledge-word.test.js` to `formal-plugin-kit/tests/writing-policy-word.test.js`
- Modify: `adapter_service/tests/test_review_mode_contract.py`
- Modify: `formal-plugin-kit/tests/taskpane-experience-contract.test.js`
- Add: `adapter_service/tests/test_writing_policy_scope_contract.py`

**Red**

- Add source-contract tests that require:
  - `app.services.writing_policy`
  - `/writing-policies/*`
  - `writingPolicyScene`, `writingPolicyUsage`, and `writingPolicyAudit`
  - no `/enterprise-knowledge`, `enterprise_knowledge_block`, or `knowledgeUsage`
  - Word-only taskpane markup and no Excel/PPT writing-policy entry
- Run:

```bash
PYTHONPATH=adapter_service python3 -m unittest \
  adapter_service.tests.test_writing_policy_scope_contract -v
node formal-plugin-kit/tests/writing-policy-word.test.js
```

Expected: fail because the old prototype naming still exists.

**Green**

- Perform a mechanical domain rename while preserving the prototype's existing behavior:
  - package `writing_policy`
  - API prefix `/writing-policies`
  - DB path `run/writing_policies.db`
  - provider argument `writing_policy_block`
  - request/response vocabulary `writingPolicyScene`, `writingPolicyUsage`, and `writingPolicyAudit`
- Rename frontend IDs, helper names, endpoint strings, tests, and fixtures to the new vocabulary.
- Do not keep import shims, old routes, response aliases, or old DB migration logic.
- Record explicit protected surfaces in tests:
  - Format Review does not call the policy service.
  - Excel and PPT source trees contain no writing-policy routes or controls.
  - three Word services still call their provider once.
- Keep this step mechanical: do not add presets, new schema semantics, scene resolution, audit findings, or redesigned UI yet.

**Verify**

```bash
rg -n "enterprise_knowledge|enterprise-knowledge|knowledgeUsage" \
  adapter_service/app formal-plugin-kit/wps-ai-assistant_1.0.0
git diff --check
```

The `rg` command must return no runtime references. Historical docs may still contain the terms.

**Commit**

```text
test: lock writing policy naming and Word-only scope
```

## Task 2: Build the Preset Pack Schema and Candidate Generator

**Files**

- Modify: `adapter_service/app/services/writing_policy/__init__.py`
- Modify: `adapter_service/app/services/writing_policy/models.py`
- Add: `adapter_service/app/services/writing_policy/packs.py`
- Add: `adapter_service/writing_policy_packs/schema-v1.json`
- Add: `adapter_service/tools/build_writing_policy_candidates.py`
- Add: `adapter_service/tests/test_writing_policy_packs.py`
- Add: `adapter_service/tests/test_writing_policy_candidates.py`
- Add: `docs/writing-policy-sources.md`

**Red**

- Test strict pack validation:
  - schema version, pack ID, version, source, entries
  - stable unique entry IDs across all packs
  - typed term/style/anti-template fields
  - valid task and scene IDs
  - bounded field lengths and priorities
- Test candidate generation from an injected `git show` reader, not a working-tree path.
- Test duplicate, near-duplicate, conflicting, missing-source, and unreviewed-item reports.

**Green**

- Implement immutable typed pack models and a loader that returns a frozen snapshot.
- Implement a deterministic candidate generator that:
  - records tag, commit, source path, and source locator
  - writes review CSV and XLSX with identical columns
  - never marks candidates approved automatically
  - rejects candidates lacking a stable ID or source
- The tool may use the repository's existing constrained XLSX writer logic; do not add a dependency.
- Document source handling, MIT attribution, and the original-paraphrase rule for standards.

**Verify**

```bash
PYTHONPATH=adapter_service python3 -m unittest \
  adapter_service.tests.test_writing_policy_packs \
  adapter_service.tests.test_writing_policy_candidates -v
git diff --check
```

**Commit**

```text
feat: add writing policy pack schema and review generator
```

## Task 3: Review and Freeze the Four Initial Preset Packs

**Human gate**

This task cannot be completed by code alone. Generate the candidate review workbook, inspect every candidate, and obtain an explicit approved/rejected decision. Unreviewed rows must not become enabled presets.

**Files**

- Add: `adapter_service/writing_policy_packs/yangqi-tech-writing-base.json`
- Add: `adapter_service/writing_policy_packs/cybersecurity-terms.json`
- Add: `adapter_service/writing_policy_packs/technical-document-style.json`
- Add: `adapter_service/writing_policy_packs/official-document-style.json`
- Add: `adapter_service/writing_policy_packs/manifest.json`
- Add: `adapter_service/writing_policy_packs/THIRD_PARTY_NOTICES.md`
- Add: `adapter_service/tests/test_writing_policy_baseline.py`
- Do not package: draft candidate CSV/XLSX files

**Red**

- Test that every enabled item:
  - has an approved review decision in the frozen review manifest
  - has one or more source references
  - has no duplicate or conflicting stable ID
  - belongs to the expected pack and type
- Test baseline bounds and distribution as warnings, not hard product quotas.
- Test manifest hashes for each pack.

**Green**

- Read source material from the clean tag:

```bash
git -C /Users/wayne/Documents/guoqi-write-style \
  show v1.1.0:SKILL.md
```

- Curate only the confirmed short-text writing core.
- Add source identifiers for government and cybersecurity references.
- Paraphrase rules for product use; do not bulk-copy source standards.
- Freeze approved rows into four version `1.0.0` JSON packs.
- Add MIT notice and exact upstream commit.

**Verify**

```bash
PYTHONPATH=adapter_service python3 -m unittest \
  adapter_service.tests.test_writing_policy_packs \
  adapter_service.tests.test_writing_policy_baseline -v
git diff --check
```

**Commit**

```text
data: add reviewed writing policy baseline packs
```

## Task 4: Replace the Store with an Upgrade-Safe Organization Database

**Files**

- Modify: `adapter_service/app/services/writing_policy/store.py`
- Add: `adapter_service/app/services/writing_policy/migrations.py`
- Modify: `adapter_service/tests/test_writing_policy_store.py`
- Modify: `adapter_service/tests/conftest.py`

**Red**

- Test a fresh `run/writing_policies.db` schema.
- Test organization terms, organization rules, preset override, preset disable, restore, uniqueness, transaction rollback, and timestamps.
- Test additive schema migration with a pre-migration backup.
- Test three-backup rotation.
- Test that corrupt DB and failed migration raise a typed degraded error without recreating or truncating the file.
- Test file permissions where supported.

**Green**

- Implement:
  - `schema_metadata`
  - `organization_terms`
  - `organization_rules`
  - `preset_overrides`
  - `policy_imports`
- Use validated typed JSON only for union override payloads.
- Open the database lazily and keep initialization idempotent.
- Create timestamped backups before migration and import.
- Preserve stable preset IDs and organization IDs.
- Replace the renamed prototype schema with the confirmed organization-layer schema; there is no old production data migration.

**Verify**

```bash
PYTHONPATH=adapter_service python3 -m unittest \
  adapter_service.tests.test_writing_policy_store -v
git diff --check
```

**Commit**

```text
feat: add upgrade-safe writing policy store
```

## Task 5: Implement Deterministic Resolution and Prompt Budgets

**Files**

- Delete after replacement: `adapter_service/app/services/writing_policy/matcher.py`
- Add: `adapter_service/app/services/writing_policy/resolver.py`
- Add: `adapter_service/app/services/writing_policy/prompt.py`
- Delete after replacement: `adapter_service/tests/test_writing_policy_matcher.py`
- Add: `adapter_service/tests/test_writing_policy_resolver.py`
- Add: `adapter_service/tests/test_writing_policy_prompt.py`

**Red**

- Test scene choices: auto, yangqi, cybersecurity, official, disabled.
- Test conservative auto fallback to base only.
- Test preset disable, organization override, organization custom rules, task/scene scope, and context keyword filtering.
- Test precedence:
  - protected content
  - current user instruction/template intent
  - organization layer
  - preset layer
  - generic anti-template
- Test deterministic tie ordering by priority and stable ID.
- Test 30-term, 8-rule, 5-style/3-anti reservation and 3000-character bounds.
- Test complete-entry truncation and no full-pack injection.

**Green**

- Implement an immutable effective-policy snapshot.
- Implement deterministic scene detection with explainable evidence and base-only fallback.
- Merge preset and organization layers without mutating either source.
- Build the prompt block with protected-content instructions first.
- Return usage metadata containing counts, pack versions, truncation, scene, and degraded state.

**Verify**

```bash
PYTHONPATH=adapter_service python3 -m unittest \
  adapter_service.tests.test_writing_policy_resolver \
  adapter_service.tests.test_writing_policy_prompt -v
git diff --check
```

**Commit**

```text
feat: resolve bounded effective writing policies
```

## Task 6: Add the Nonblocking Local Result Audit

**Files**

- Add: `adapter_service/app/services/writing_policy/audit.py`
- Add: `adapter_service/tests/test_writing_policy_audit.py`
- Modify: `adapter_service/app/services/writing_policy/models.py`

**Red**

- Test protected numbers, dates, responsibility subjects, explicit clauses, and matched organization terms.
- Test forbidden and nonstandard term variants.
- Test deterministic T1/T2/T3 expression suggestions.
- Test no false “AI generated” label or authorship claim.
- Test audit failure returns a degraded audit object without discarding model output.
- Test log metadata excludes source text and rule bodies.

**Green**

- Use deterministic string/token comparison and rule patterns only.
- Separate:
  - `needsReview`
  - `expressionSuggestions`
- Bound findings and evidence excerpts.
- Return a one-line passed state when no finding exists.
- Keep audit outside provider request and make it nonblocking.

**Verify**

```bash
PYTHONPATH=adapter_service python3 -m unittest \
  adapter_service.tests.test_writing_policy_audit -v
git diff --check
```

**Commit**

```text
feat: audit model results against writing policies
```

## Task 7: Implement Management API and CSV/XLSX Round-Trip

**Files**

- Modify: `adapter_service/app/services/writing_policy/imports.py`
- Modify: `adapter_service/app/services/writing_policy/service.py`
- Modify: `adapter_service/app/api/writing_policies.py`
- Modify: `adapter_service/app/main.py`
- Modify: `adapter_service/standalone_adapter.py`
- Modify: `adapter_service/tests/test_writing_policy_imports.py`
- Modify: `adapter_service/tests/test_writing_policy_api.py`
- Modify: `adapter_service/tests/test_writing_policy_service.py`

**Red**

- Test FastAPI and standalone parity for all `/writing-policies/*` routes.
- Test list filters, pagination, create, edit, delete, override, disable, and restore.
- Test effective and organization-only CSV/XLSX export.
- Test explicit import operation semantics: create, override, disable, restore, delete.
- Test preview counts, errors, conflicts, token expiry, file digest binding, pre-apply backup, atomic apply, and rollback.
- Test request body limits and sanitized diagnostics.
- Test that no legacy route is registered.

**Green**

- Implement the API contract from the design document.
- Reuse existing ZIP/XML XLSX support; do not add a package.
- Keep CSV and XLSX columns identical.
- Require an explicit operation column; missing exported rows never imply deletion.
- Preserve preset ID, source, version, layer, scopes, and override status.
- Use the service facade to convert load failures into typed degraded responses.
- Update main middleware route classification and body-size handling to the new prefix.

**Verify**

```bash
PYTHONPATH=adapter_service python3 -m unittest \
  adapter_service.tests.test_writing_policy_imports \
  adapter_service.tests.test_writing_policy_api \
  adapter_service.tests.test_writing_policy_service -v
git diff --check
```

**Commit**

```text
feat: expose writing policy management and round-trip APIs
```

## Task 8: Integrate the Three Word Services with One Model Call

**Files**

- Modify: `adapter_service/app/core/models.py`
- Modify: `adapter_service/app/services/provider_client.py`
- Modify: `adapter_service/app/services/word/rewriter.py`
- Modify: `adapter_service/app/services/word/smart_imitator.py`
- Modify: `adapter_service/app/services/word/document_reviewer.py`
- Modify: `adapter_service/app/api/word.py`
- Modify: `adapter_service/tests/test_enterprise_provider.py`
- Modify: `adapter_service/tests/test_word_rewrite.py`
- Modify: `adapter_service/tests/test_word_smart_imitation.py`
- Modify: `adapter_service/tests/test_word_document_review.py`
- Modify: `adapter_service/tests/test_review_mode_contract.py`

**Red**

- Test optional `writingPolicyScene`, default `auto`, and disabled behavior.
- Test `writingPolicyUsage` and `writingPolicyAudit` serialization.
- Test provider prompt builders receive `writing_policy_block`.
- Assert exactly one provider call per task.
- Assert document review long-job state and timeout behavior are unchanged.
- Assert policy resolution or audit failure is fail-open with a Chinese degraded message.
- Assert think-tag filtering still applies before result audit.

**Green**

- Resolve policy before each existing provider call.
- Append the bounded block to the existing `query`; do not add Dify variables.
- Audit the final visible result after think-content removal.
- Attach optional metadata without changing primary result fields.
- For document review, merge policy findings into the existing issue model while preserving original issue ordering and review-record behavior.

**Verify**

```bash
PYTHONPATH=adapter_service python3 -m unittest \
  adapter_service.tests.test_enterprise_provider \
  adapter_service.tests.test_word_rewrite \
  adapter_service.tests.test_word_smart_imitation \
  adapter_service.tests.test_word_document_review \
  adapter_service.tests.test_review_mode_contract -v
git diff --check
```

**Commit**

```text
feat: apply writing policies to Word model tasks
```

## Task 9: Add Task Selectors and Compact Result Disclosure

**Files**

- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`
- Modify: `formal-plugin-kit/tests/taskpane-helpers.test.js`
- Modify: `formal-plugin-kit/tests/writing-policy-word.test.js`
- Modify: `formal-plugin-kit/tests/layout-smoke.test.js`

**Red**

- Test one compact selector appears only in Smart Write, Smart Imitation, and Document Review.
- Test task-specific local preference keys.
- Test auto is the default and only known scene values are sent.
- Test result disclosure renders:
  - concise usage summary
  - “需要核对”
  - “表达建议”
  - passed state
  - degraded Chinese status
- Test copy, writeback, comparison, review-record toggle, and result text are not replaced by audit content.
- Test no vector icon is added to primary result buttons.

**Green**

- Add pure normalization and rendering helpers first.
- Render one compact select near the existing workflow selector.
- Persist selection per Word task.
- Use an accessible disclosure control for details.
- Use text, icon, and color together for severity, while keeping primary action buttons text-only.
- Do not synchronously render or search the full policy library.

**Verify**

```bash
node formal-plugin-kit/tests/taskpane-helpers.test.js
node formal-plugin-kit/tests/writing-policy-word.test.js
node formal-plugin-kit/tests/layout-smoke.test.js
git diff --check
```

**Commit**

```text
feat: show Word writing policy selection and audit feedback
```

## Task 10: Replace Word Settings with the Drill-Down Policy Library

**Files**

- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.html`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.css`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane-helpers.js`
- Modify: `formal-plugin-kit/wps-ai-assistant_1.0.0/taskpane.js`
- Modify: `formal-plugin-kit/tests/writing-policy-word.test.js`
- Modify: `formal-plugin-kit/tests/taskpane-experience-contract.test.js`
- Modify: `formal-plugin-kit/tests/layout-smoke.test.js`

**Red**

- Test settings home has one “写作规范库” row.
- Test segmented “预置规范 / 组织规范” view.
- Test only current packs and rule types are shown.
- Test preset edit creates an override and restore removes it.
- Test organization create/edit/delete, empty-note omission, and two-axis scope controls.
- Test import/export/backup/diagnostics live under a secondary More view.
- Test loading, empty, error, degraded, confirmation, and stale-response states.
- Test no nested cards, corners no larger than 8px, and horizontally scrollable future tabs.

**Green**

- Replace old enterprise-knowledge IDs, copy, state, and endpoints.
- Keep each level focused on one main action:
  - settings home
  - library layers
  - pack/type list
  - item editor
  - More tools
- Use Word blue, system font, compact spacing, and progressive disclosure.
- Keep advanced diagnostics collapsed.
- Use request sequence guards so stale responses cannot overwrite newer edits.

**Verify**

```bash
node formal-plugin-kit/tests/writing-policy-word.test.js
node formal-plugin-kit/tests/taskpane-experience-contract.test.js
node formal-plugin-kit/tests/layout-smoke.test.js
git diff --check
```

Start the local adapter and verify with Playwright at desktop and narrow taskpane widths:

```bash
PYTHONPATH=adapter_service python3 -m uvicorn app.main:app \
  --host 127.0.0.1 --port 18100
```

Capture at least:

- Word task selector and collapsed result audit.
- Expanded “需要核对” and “表达建议”.
- settings home and library entry.
- preset pack list, organization list, item editor, and More view.
- degraded and empty states.

**Commit**

```text
feat: redesign Word writing policy settings
```

## Task 11: Protect Installation and Package the Baseline

**Files**

- Modify: `phase1-delivery-kit/installer/install_phase1.sh`
- Modify: `packaging/build_phase1_delivery_kit.sh`
- Modify: `adapter_service/tests/test_packaging_scripts.py`
- Modify: `phase1-delivery-kit/docs/phase1-acceptance-checklist.md`
- Add: `phase1-delivery-kit/docs/writing-policy-library.md`
- Add: `phase1-delivery-kit/templates/writing-policy-import-template.csv`
- Add: `phase1-delivery-kit/templates/writing-policy-import-template.xlsx`

**Red**

- Test package contains four packs, manifest, source/license notice, guide, and templates.
- Test package excludes:
  - `run/writing_policies.db`
  - backups
  - candidate review drafts
  - API keys
  - logs
- Test installer preserves an existing DB checksum and organization records during overwrite.
- Test first install creates the parent directory but lets adapter initialize the DB.
- Test legacy `enterprise_knowledge.db` is neither imported nor deleted.

**Green**

- Copy reviewed presets and documentation into the package.
- Make installer skip all existing organization data and backups.
- Keep API URL, workflow profiles, key files, and other current preservation rules unchanged.
- Add target-machine acceptance steps for first install and simulated future overwrite.

**Verify**

```bash
PYTHONPATH=adapter_service python3 -m unittest \
  adapter_service.tests.test_packaging_scripts -v
bash -n \
  packaging/build_phase1_delivery_kit.sh \
  phase1-delivery-kit/installer/install_phase1.sh \
  phase1-delivery-kit/scripts/phase1_smoke_test.sh
git diff --check
```

**Commit**

```text
build: preserve writing policy data in delivery installs
```

## Task 12: Version, Documentation, Full Regression, and Delivery

**Files**

- Modify: all current version-bearing Word, Excel, PPT, adapter, README, handoff, acceptance, and package files
- Modify: `README.md`
- Modify: `docs/codex-handoff.md`
- Modify: `phase1-delivery-kit/README.md`
- Modify: `phase1-delivery-kit/docs/phase1-acceptance-record.md`
- Modify: `formal-plugin-kit/tests/layout-smoke.test.js`

**Version**

- Product version: `v0.20.0-alpha`
- Rule number: `AI-WPS-P1-WORD-EXCEL-PPT-0.20.0-<release-date>`
- Use one date-tagged three-host formal delivery archive.

**Full regression**

```bash
PYTHONPATH=adapter_service \
  /Users/wayne/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
  -m unittest discover -s adapter_service/tests -v

for test_file in formal-plugin-kit/tests/*.test.js; do
  node "$test_file"
done

bash -n \
  packaging/build_phase1_delivery_kit.sh \
  phase1-delivery-kit/installer/install_phase1.sh \
  phase1-delivery-kit/scripts/phase1_smoke_test.sh

DATE_TAG=<release-date> bash packaging/build_phase1_delivery_kit.sh
git diff --check
```

**Delivery inspection**

- Verify a single archive contains `wps`, `et`, and `wpp`.
- Verify all three frontend versions and adapter health version match.
- Verify pack hashes and source manifest.
- Verify no live organization database, backup, key, log, or draft review file.
- Extract to a temporary directory and run package smoke tests.
- Simulate overwrite against a seeded `writing_policies.db`; compare exported organization data before and after.

**Target-machine acceptance**

- Kylin V10 first install creates a usable library.
- Create organization terms, style rules, anti-template rules, overrides, and disabled presets.
- Restart adapter and WPS; verify persistence.
- Run all three Word tasks with auto and explicit scenes.
- Exercise a slow think-mode Document Review and verify existing long-job behavior.
- Force pack and DB read failures separately; verify fail-open Chinese status.
- Install the same package again; verify organization data and API/workflow configuration remain intact.
- Confirm Format Review, Excel Smart Analysis, PPT Smart Summary, Ribbon separation, and writeback regressions.

**Commit and push**

```text
release: package v0.20.0-alpha writing policy library
```

Push only after the full regression, package inspection, and target acceptance record are complete.

## Final Definition of Done

- All 18 design acceptance criteria pass.
- The human review gate is recorded for every enabled preset.
- Runtime code contains no old enterprise-knowledge naming or API aliases.
- Three Word tasks make exactly one provider call and expose optional policy metadata.
- Organization data survives restart, import failure, migration failure, and overwrite installation.
- The policy feature fails open without misreporting a model connection error.
- No change is observed in Format Review, Excel, PPT, writeback, think filtering, workflow profiles, timeouts, or long-job polling.
- README, handoff, package guide, acceptance checklist, and acceptance record match the delivered version.
