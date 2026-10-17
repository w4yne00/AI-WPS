# AI-WPS v0.26.0-preview.1

Offline installation candidate for Word, Excel and PPT on Kylin V10 ARM64 with Python 3.8. The package includes 13 model task types and template-based full-deck generation.

[English](./README.md) | [中文](./README-ZH.md)

## Install and verify

Save your documents and close WPS, Excel and PPT before installation. Extract the archive, enter its directory, then run:

```bash
bash installer/install_ai_wps.sh
bash scripts/ai_wps_smoke_test.sh
```

The default installation root is `$HOME/ai-wps`. Open WPS and configure the enterprise model connection in the task pane. The package contains no local credentials or production configuration.

A successful installation creates “重启 AI-WPS 后台服务” on the target user's desktop. This shortcut restarts and checks the current installed Adapter, preserving its Python interpreter, port, state and backup directories, and custom system-service settings. Reinstallation updates the same shortcut. If the desktop cannot mark it as trusted automatically, right-click it and choose “Allow Launching” or “Allow Executing” before first use. The installer checks that WPS has exited; it does not close your documents.

Upgrading an existing Preview installation preserves configuration, API keys, runtime data and backups. The installer stops the old Adapter, checks the candidate, switches the Adapter and all three add-ins together, then starts and checks the new Adapter. A failed switch restores the previous generation.

A first Preview installation only detects `$TARGET_HOME/ai-wps-phase1`; it does not import, overwrite or delete legacy data. It may stop an old Adapter holding the target port and replace the shared WPS add-in directories. Keep the legacy directory and reconfigure the new installation explicitly.

## Included capabilities

| Host | Capabilities |
| --- | --- |
| Word | Smart Write, Smart Imitation, on-demand writing from DOCX/DOC, document review and format review; reusable writing policies |
| Excel | Analysis, formula assistance, Smart Fill preview/copy, and material-based ledger generation with confirmed write-back to a blank worksheet area |
| PPT | Slide/document summary, structure review, material-based outline, template body-page generation and full-deck generation with confirmed append |

Review, analysis, formula assistance and Smart Fill do not write to the document. Writing, ledger and template-generation actions require the supported preview and confirmation steps. Regeneration creates a new task; retries and recovery retain the original task identity. Results and write confirmations are isolated by document session. PPT generation appends pages without changing existing pages. A document, outline or preview change invalidates prior confirmation; inspect and recover any partial append before continuing.

Workflow-platform connections remain per task and use `/chat-messages`. Shared direct services store the URL and API key once and use OpenAI-compatible `/chat/completions`. Each task can inherit the service default or select its own model and parameters. All three hosts support adding and deleting manually entered models.

For Word Smart Write and Smart Imitation, catalog models are checked for streaming capability before activation. Manually entered models are saved first and checked in the background. Format review checks semantic and visual capability separately; direct image input uses `openai_image_url`. Checks use synthetic content and may incur model charges. Failed background checks retain the saved selection and display the error.

Validated Word writing models enable incremental read-only previews by default. Set `AI_WPS_ENABLE_DIRECT_STREAMING=0` to use blocking calls. PPT material outlines receive streaming output but show the outline only after complete validation. Cancellation and failed output do not become successful history entries.

Format review includes automatic/manual TOC exemptions, suspected-TOC disclosure, location-grouped issues and optional image semantics. Disabling the image-semantics master switch prevents document image export and upload.

## Package contents and audit

- `installer/install_ai_wps.sh`: unified installer.
- `packages/`: three WPS add-ins, Adapter, locked offline dependencies and startup tools.
- `docs/operations/`, `docs/prompt-templates/`, `reference-workflows/`: configuration and workflow instructions.
- `release-manifest.json`: version, source commit, archive identity and baseline.
- `release-allowlist.json`, `release-file-hashes.json`: exact package inventory and integrity checks.
- `docs/v0260-preview1-target-machine-acceptance.md`: manual acceptance record.

To audit the extracted package:

```bash
python3 scripts/audit_delivery.py .
python3 scripts/audit_v0260_preview1_delivery.py .
```

The build checks source provenance, allowlist assembly, rule compilation, Python 3.8 compatibility, plugin and backend regression, syntax, archive integrity and installation lifecycle. Tests, caches, historical delivery instructions, local configuration, keys and runtime data are excluded. The external `.sha256` file verifies the archive itself.

Automated success records only `candidate`. Real WPS interactions and enterprise model acceptance remain `manual-pending` under Issue #154. Package verification does not update an existing installation.
