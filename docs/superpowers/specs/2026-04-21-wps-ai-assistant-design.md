# WPS AI Assistant Plugin Design

## 1. Background and Goal

Build an intelligent AI assistant plugin for the company's intranet office terminal `12.1.2`, targeting `Kylin V10` on `ARM`.

Known constraints:

- WPS runs on Kylin V10 and the target form is a `WPS native plugin`
- The terminal cannot access the public internet
- All dependencies must be packaged and installed offline
- Local Python version is `3.8`
- The company intranet already provides a `Dify`-based agent platform and reasoning models

Product scope is split into two phases:

- Phase 1: `platform foundation + Word`
- Phase 2: `Excel + PPT`

This document first defines the complete product planning, then narrows Phase 1 into a concrete architecture and delivery scope.

## 2. Product Planning

### 2.1 Target capabilities

The full product target includes:

- Word: format proofreading
- Word: automatic formatting
- Word: draft rewrite and continuation based on the current document
- PPT: outline generation based on a document or topic
- Excel: report generation
- Excel: multi-sheet and multi-file comparison
- Platform foundation: plugin framework, Dify integration, offline installation, configuration, logging, diagnostics

### 2.2 Phase plan

#### Phase 1

Deliver a usable and demo-ready baseline:

- WPS plugin framework
- Local adapter service
- Offline installation package
- Word proofreading
- Word formatting
- Word rewrite and continuation based on current document or selection

#### Phase 2

Extend business capabilities on the same foundation:

- Excel report generation
- Excel multi-table comparison
- PPT outline generation

The core rule is: Phase 2 must reuse Phase 1 foundation, not rebuild the system.

## 3. Key Design Decisions

### 3.1 Plugin form

Use a `WPS native JS/HTML plugin` as the primary form.

Reasoning:

- Official WPS add-in documentation confirms a native add-in model based on `manifest.xml`, ribbon integration, and JS APIs
- Word, Excel, and presentation object models are exposed through official APIs
- Python is better used as a local auxiliary service than as the plugin body

### 3.2 Architecture choice

Choose `lightweight WPS plugin + local Python adapter service + intranet Dify HTTP API`.

Rejected alternatives:

- Pure plugin direct-to-Dify: fastest to start, but rules, logging, configuration, and offline dependency management become hard to maintain
- Plugin + local service + enterprise gateway: strong governance, but too heavy for Phase 1 MVP

Why the chosen approach is recommended:

- Keeps WPS-side code thin and focused on UI plus document APIs
- Moves rules, templates, orchestration, and offline operations to a controllable local layer
- Lets Excel and PPT reuse the same task routing and service interfaces in Phase 2

## 4. Overall Architecture

### 4.1 Layered structure

The system is divided into three layers.

#### Layer A: WPS plugin frontend

Responsibilities:

- Ribbon buttons
- Task pane UI
- Settings page
- Reading current document and selection through WPS APIs
- Preview and confirmation before applying changes
- Writing approved results back into Word

This layer must not contain complex rule logic.

#### Layer B: Plugin bridge layer

Responsibilities:

- Convert WPS document objects into normalized structured payloads
- Convert service responses into write-back operations
- Isolate WPS API differences from business logic

This layer is intentionally thin and reusable for future Excel and PPT scenes.

#### Layer C: Local Python 3.8 adapter service

Responsibilities:

- Local HTTP service for plugin calls
- Configuration loading
- Template matching
- Rule execution
- Task routing
- Dify API encapsulation
- Logging and diagnostics
- Offline resource loading

This layer is the control plane for the product.

### 4.2 External dependency boundary

The only required remote dependency in Phase 1 is the intranet `Dify HTTP API`.

All public internet dependencies must be removed from runtime. Package acquisition and dependency preparation happen before deployment, then are installed offline on target terminals.

## 5. Phase 1 Architecture

### 5.1 Phase 1 modules

Phase 1 is broken into five modules.

#### Module 1: WPS plugin frontend

Entrypoints:

- `Format Proofread`
- `Auto Format`
- `Rewrite / Continue`

Responsibilities:

- Trigger tasks from Ribbon or task pane
- Collect parameters
- Read document or selection
- Show previews and results
- Require user confirmation before applying changes

#### Module 2: Plugin bridge

Responsibilities:

- Extract document structure
- Normalize paragraphs, headings, and style metadata
- Build standard requests to the adapter service
- Apply approved changes back to the document

#### Module 3: Local adapter service

Responsibilities:

- Expose localhost APIs
- Validate requests
- Load rules and templates
- Route tasks to Word engines or Dify
- Record trace logs
- Return structured results

#### Module 4: Word capability services

Sub-capabilities:

- Proofreading engine
- Formatting engine
- AI rewrite engine

#### Module 5: Offline installation and operations package

Responsibilities:

- Bundle plugin files
- Bundle Python runtime and dependency wheels
- Bundle templates and configuration
- Provide install, start, uninstall, and diagnostic scripts

### 5.2 Phase 1 data flow

Core flow:

1. User clicks a Word feature in WPS
2. Plugin reads current document or selection
3. Plugin sends structured request to localhost adapter
4. Adapter runs rules or calls Dify
5. Adapter returns structured result
6. Plugin shows preview
7. User confirms
8. Plugin writes changes back to the document

### 5.3 Core product rules

- AI output must never be written directly without preview
- Rule engines and AI engines must stay separate
- Structured document extraction must be preserved; do not reduce the payload to plain text only

## 6. Phase 1 Functional Scope

### 6.1 In scope

#### Foundation

- Ribbon entry
- Task pane
- Settings page
- Local service communication
- Logging entry
- Health check and diagnostics
- Offline install package

#### Word proofreading

Cover at least:

- heading hierarchy
- font and size consistency
- paragraph spacing
- numbering consistency
- whitespace and punctuation problems
- common layout issues

#### Word auto formatting

Formatting policy:

- Prefer company template rules
- Fallback to general office formatting rules when no company template matches
- Always preview before apply

#### Word rewrite / continuation

Input mode:

- current selection
- current document

Output mode:

- rewrite
- polish
- formalize
- continue from existing content

Phase 1 does not include blank-page drafting.

### 6.2 Out of scope

- full blank-document draft generation
- Excel AI formulas
- complete PPT page generation
- online hot update
- online dependency download
- document cloud collaboration
- knowledge base governance platform

## 7. Interfaces and Data Structures

### 7.1 Local HTTP APIs

Recommended initial endpoints:

- `GET /health`
- `GET /config`
- `GET /templates`
- `POST /word/proofread`
- `POST /word/format-preview`
- `POST /word/rewrite`
- `POST /task/log`

### 7.2 Request structure

The plugin must send structured document content, not plain text only.

Example:

```json
{
  "documentId": "local-doc-001",
  "scene": "word",
  "selectionMode": "document",
  "content": {
    "plainText": "...",
    "paragraphs": [
      {
        "index": 1,
        "text": "First paragraph",
        "styleName": "Body",
        "fontName": "SimSun",
        "fontSize": 12,
        "alignment": "left",
        "outlineLevel": 0
      }
    ],
    "headings": [
      {
        "level": 1,
        "text": "Project Proposal"
      }
    ]
  },
  "options": {
    "templateId": "general-office",
    "trackChanges": true
  }
}
```

### 7.3 Unified response envelope

All capabilities should return the same outer structure.

```json
{
  "success": true,
  "traceId": "trace-20260421-001",
  "taskType": "word.proofread",
  "message": "completed",
  "data": {},
  "errors": []
}
```

### 7.4 Capability-specific payloads

#### Proofreading result

- `issues[]`
- each issue contains location, rule id, severity, original text, suggestion, and whether it is auto-fixable

#### Formatting preview result

- `changes[]`
- `summary`

Each change should include target paragraph, current style, target style, and reason.

#### Rewrite result

- `originalText`
- `rewrittenText`
- `rewriteMode`
- `diffHints[]`

### 7.5 Template structure

Templates should be external configuration files, not hardcoded business rules.

Suggested layout:

- `templates/company/*.json`
- `templates/general/*.json`

Each template should define:

- page settings
- heading levels
- body text rules
- proofreading rules

## 8. Error Handling and Diagnostics

### 8.1 Failure handling

- Plugin startup must call `health check`
- If local adapter is unavailable, show clear diagnostic text instead of raw stack traces
- Dify failures must be normalized into stable error codes
- Distinguish timeout, auth failure, unreachable endpoint, and model response failure
- Template mismatch must downgrade to general office rules instead of stopping the workflow
- Write-back failures must keep the plugin in preview state
- Long-running AI tasks must support timeout and cancellation

### 8.2 Logging and audit

Two log layers are required:

- plugin frontend operation log
- local adapter service log

Minimum trace fields:

- `traceId`
- task type
- document scope
- template id
- start time
- duration
- result status
- error code

Logging rule:

- Do not log full document content by default
- Keep only summaries and required diagnostics

Configurable items:

- log path
- retention days
- masking level

## 9. Offline Installation Design

Phase 1 installation assumes fully offline manual deployment.

Suggested package structure:

- `wps-plugin/`
- `runtime/`
- `adapter/`
- `templates/`
- `scripts/`
- `docs/`

Expected script set:

- install script
- start script
- uninstall script
- diagnostic script

Phase 1 does not require online updates, but file layout and configuration should stay compatible with later unified software distribution.

## 10. Acceptance Criteria

Phase 1 is accepted only if all of the following are true:

- Can be installed offline on `Kylin V10 ARM`
- WPS plugin loads successfully
- Plugin can read the active Word document
- Plugin can call the localhost adapter service
- Proofreading returns a structured issue list
- Auto formatting produces a preview and applies approved changes
- Rewrite or continuation returns a result based on current document or selection
- Main failure paths show clear user-facing errors and produce logs
- Updating templates or Dify configuration does not require code changes

## 11. Risks and Validation Points

The main Phase 1 risks are not model quality but platform compatibility.

Highest-priority validation items:

- Whether the target Kylin WPS build fully supports the planned native JS/HTML plugin model
- Which WPS APIs are available for Word document traversal and write-back on the target environment
- Whether localhost communication from the plugin runtime is allowed
- Whether Python 3.8 runtime and packaged dependencies run cleanly on the target ARM environment
- How the plugin is installed and loaded on the target terminal image

These should be treated as environment probes early in implementation.

## 12. Recommended Next Step

After this design is approved, move directly into a Phase 1 implementation plan for:

- foundation bootstrap
- plugin-to-localhost communication
- Word document extraction
- proofreading engine
- formatting preview engine
- rewrite engine
- offline packaging
