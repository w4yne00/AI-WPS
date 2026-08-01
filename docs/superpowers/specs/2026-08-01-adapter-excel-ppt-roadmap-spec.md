# AI-WPS Adapter、Excel 与 PPT 三版本演进规格

日期：2026-08-01

状态：已确认，等待拆分本地工单

发布边界：仅保存在本地仓库，不发布 GitHub

## Problem Statement

AI-WPS 的 Word 功能已经覆盖智能编写、智能仿写、文档审查、格式审查和写作规范库，继续叠加 Word 业务功能会扩大稳定链路的回归面。当前更紧迫的问题是三类长任务各自创建后台线程并分别维护内存状态，没有统一并发和排队边界；Word 文档审查和 Excel 智能分析在任务记录达到容量时还可能移除仍在运行的任务，造成模型后台仍在执行但前端无法继续查询结果。

与此同时，Word 和 Excel 任务窗格通过高频轮询读取 WPS 选区，即使页面隐藏也持续访问宿主对象，存在可避免的前端开销。麒麟 V10 真机尚未完成事件兼容和性能门禁，因此不能把缺少测量的数据笼统归因于模型或 Adapter 性能。

Excel 目前只有通用智能分析，缺少低 Token、高频使用的公式生成与解释能力。PPT 目前可以总结当前页，也可以根据 Markdown/DOCX 生成整套内容建议，但无法检查已有演示文稿的章节、顺序和叙事结构。用户需要在不自动修改工作簿或幻灯片的前提下获得这两类辅助能力。

## Solution

按三个独立版本交付：

1. `v0.20.1-alpha` 建立三宿主共享的有界长任务协调器，并优化 Word/Excel 选区监听。默认同时运行 2 个长任务，FIFO 排队最多 8 个。任务页展示真实排队位置、处理阶段和耗时；只有排队中的任务可以取消。终态结果保留 2 小时、最多 50 条，运行中任务绝不因容量被淘汰。Adapter 重启后明确提示任务中断，不伪装为可恢复。
2. `v0.21.0-alpha` 为 Excel 新增独立“公式助手”，包含“生成公式 / 解释排错”两个模式。只读取用户明确框选的最多 30 行 × 20 列数据和公式信息，返回一个主公式、解释、适用位置、假设、兼容风险和本地基础检查结果。首版只预览和复制。
3. `v0.22.0-alpha` 为 PPT 新增独立“结构审查”。正常页面只读取页码、主标题和可选副标题；无标题页最多读取 120 个正文字符，最多兜底 10 页。单次最多审查 60 页，Adapter 合并本地确定性检查和一次模型语义审查，输出分级问题、逐页建议和推荐目录。首版只预览和复制。

三个版本保持 Word 已稳定功能、格式审查、Excel 智能分析、PPT 智能总结、工作流档案、Dify 输入兼容、think 内容过滤、超时和写回边界不变。

## User Stories

1. As a Word user, I want document review jobs to remain queryable while they are running, so that a slow model does not appear to lose the task.
2. As an Excel user, I want intelligent analysis jobs to remain queryable while they are running, so that the result is not lost when other jobs are submitted.
3. As a PPT user, I want smart summary jobs to remain queryable while they are running, so that closing and reopening the task pane does not duplicate the model request.
4. As a user with multiple WPS hosts open, I want long tasks to share a bounded queue, so that one workstation cannot create unlimited model connections and threads.
5. As a user, I want at most two long tasks to execute concurrently by default, so that slow model workloads remain controlled.
6. As a user, I want additional long tasks to enter an FIFO queue, so that execution order is predictable.
7. As a user, I want to see my queue position, so that I understand why model processing has not started.
8. As a user, I want to see real phases and elapsed time, so that I can distinguish queuing, preparation, upload, model processing and parsing.
9. As a user, I do not want an estimated progress percentage, so that the interface does not imply precision the model backend cannot provide.
10. As a user, I want to cancel a queued task, so that I can release work that has not started.
11. As a user, I do not want a running task labelled as cancelled when Dify may still be computing it, so that task status remains truthful.
12. As a user, I want completed results to remain available for two hours, so that I can reopen the task pane after the model finishes.
13. As an operator, I want only terminal jobs to be removed for capacity or TTL reasons, so that active work is never orphaned.
14. As an operator, I want a full queue to reject new work with a Chinese explanation, so that resource pressure is visible and controlled.
15. As an operator, I want task diagnostics to show queue depth, running count, phase durations and sanitized error codes, so that I can locate delays without reading sensitive content.
16. As a security administrator, I want API keys excluded from job responses, logs, diagnostics and persistent storage, so that queue diagnostics do not expand secret exposure.
17. As a user, I want a queued task to use the workflow profile and API configuration selected when I submitted it, so that later configuration changes do not alter existing work.
18. As a PPT user, I want a queued document summary to retain ownership of its staged file, so that a 30-minute upload token does not expire before execution starts.
19. As a PPT user, I want staged files deleted after completion, failure or queued cancellation, so that local source documents are not retained unnecessarily.
20. As a user, I want an explicit interruption message after Adapter restart, so that I do not wait for a job that cannot be resumed through blocking `/chat-messages`.
21. As a Word user, I want selection status to update from WPS events when supported, so that the task pane does not repeatedly read COM objects every 800 ms.
22. As an Excel user, I want range status to update from WPS events when supported, so that the task pane does not repeatedly inspect the worksheet every 1200 ms.
23. As a user, I want a visible-page polling fallback, so that selection status still updates when Linux WPS does not reliably emit events.
24. As a user, I want host polling paused when the task pane is hidden, in settings or busy, so that background UI work does not compete with the active WPS task.
25. As an Excel user, I want a dedicated Formula Assistant Ribbon entry, so that formula work is separate from general data analysis.
26. As an Excel user, I want to choose Generate Formula or Explain and Debug, so that the assistant does not guess my intent from selection contents.
27. As an Excel user, I want Formula Assistant to have its own workflow profiles and API keys, so that its output contract can evolve independently from intelligent analysis.
28. As an Excel user, I want the assistant to read only my explicit selection, so that unrelated worksheet data is not transmitted.
29. As an Excel user, I want the selection limited to 30 rows and 20 columns, so that formula requests remain responsive and Token-bounded.
30. As an Excel user, I want to see when selected data was truncated, so that I understand the context the model actually received.
31. As an Excel user, I want one primary recommended formula, so that I have a clear default rather than several undifferentiated alternatives.
32. As an advanced Excel user, I want one optional alternative formula when it materially differs, so that I can choose a compatibility or readability tradeoff.
33. As an Excel user, I want the suggested target cell or range shown, so that I know where the formula is intended to be used.
34. As an Excel user, I want a plain-language explanation of the formula, so that I can verify its logic before use.
35. As an Excel user, I want assumptions and referenced columns stated explicitly, so that hidden model assumptions are visible.
36. As an Excel user, I want existing formulas explained by component, so that I can maintain workbooks I did not author.
37. As an Excel user, I want suspected formula problems and a corrected formula when appropriate, so that debugging is actionable.
38. As an Excel user, I want basic local checks for prefix, brackets, quotes, length, external references and function compatibility, so that obvious risks are visible before copying.
39. As an Excel user, I want the interface to say “基础检查通过” rather than “公式正确”, so that syntactic checks are not confused with calculation correctness.
40. As an Excel user, I want to copy the formula and explanation without automatic insertion, so that the workbook remains under my control.
41. As a PPT user, I want a dedicated Structure Review Ribbon entry, so that reviewing an existing deck is distinct from generating or summarizing content.
42. As a PPT user, I want Structure Review to have independent workflow profiles and API keys, so that its review output is not coupled to Smart Summary.
43. As a PPT user, I want the reviewer to read page number, main title and optional subtitle, so that the whole-deck input remains compact.
44. As a PPT user, I want a small body-text fallback only for untitled slides, so that charts and image pages can still have a role inferred without sending all slide text.
45. As a PPT user, I want body fallback capped at 120 characters and 10 slides, so that exceptional pages do not defeat the Token budget.
46. As a PPT user, I want a single review limited to 60 slides, so that long decks do not cause oversized model input or output.
47. As a PPT user with more than 60 slides, I want to choose an explicit start and end page, so that the interface does not falsely claim to review the whole deck.
48. As a PPT user, I want deterministic checks for blank titles, duplicate titles, long titles and numbering gaps, so that stable problems do not depend on model behavior.
49. As a PPT user, I want one model call to assess storyline, chapter structure, ordering and missing content, so that semantic review remains useful without multi-call inconsistency.
50. As a PPT user, I want high-priority issues separated from general suggestions, so that I can address structural problems first.
51. As a PPT user, I want page-numbered recommendations, so that every suggestion is traceable to the current deck.
52. As a PPT user, I want a recommended title order and inferred chapter outline, so that I can manually reorganize the deck.
53. As a PPT user, I want to copy the review conclusion or recommended outline, so that I can reuse the advice without modifying slides automatically.
54. As a PPT user, I do not want an uncalibrated numeric quality score, so that model opinion is not presented as an objective metric.
55. As a Word user, I want Smart Write, Smart Imitation, Format Review and existing writeback behavior unchanged, so that performance work does not regress stable workflows.
56. As an Excel user, I want existing Smart Analysis behavior unchanged, so that Formula Assistant is additive and independently configurable.
57. As a PPT user, I want existing current-slide and document Smart Summary behavior unchanged, so that Structure Review does not alter file upload or summary output.
58. As an administrator, I want Word, Excel and PPT Ribbon entries to remain host-isolated, so that each WPS application only displays its own functions.
59. As a target-machine tester, I want explicit Kylin V10 gates for events, formulas and slide collection access, so that local mocks are not mistaken for Linux WPS compatibility.
60. As a release operator, I want each of the three versions independently packageable and reversible, so that Adapter, Excel and PPT regressions can be isolated.

## Implementation Decisions

- The work ships as three sequential releases: Adapter stability first, Excel Formula Assistant second, PPT Structure Review third. Each release must pass target-machine acceptance before the next starts.
- A shared long-task coordinator replaces independent thread-per-job behavior for Word Document Review, Excel Smart Analysis and PPT Smart Summary, and is also used by Formula Assistant and Structure Review.
- Smart Write, Smart Imitation and Format Review remain outside the queue and retain their current direct request behavior.
- Default capacity is two running jobs and eight queued jobs across all hosts. Scheduling is FIFO. Capacity values are configurable but diagnostics must expose the effective values.
- Public job states are queued, running, completed, failed and cancelled. Public phases distinguish queued, preparing, uploading where applicable, provider processing, parsing and terminal completion.
- Queue responses include queue position, current phase, elapsed time, phase timings where available and whether queued cancellation is allowed. They do not expose synthetic percentages.
- `clientJobId` remains the idempotency key. A duplicate submission returns the existing job and never starts a second provider call or file upload.
- Only queued jobs can be cancelled. Running blocking provider requests are not presented as cancellable because disconnecting the client cannot guarantee Dify computation stops.
- Running and queued jobs are never evicted for capacity. Completed, failed and cancelled jobs expire two hours after entering a terminal state; no more than 50 terminal jobs are retained.
- Expiry and duration logic use a monotonic clock. User-visible timestamps may use wall clock, but wall-clock changes cannot expire an active job.
- Job input and provider configuration are snapshotted at submission. The snapshot includes task type, input, workflow profile, API URL, path, input-mode decision and resolved authentication.
- Resolved credentials exist only in job memory, are excluded from serialization and diagnostics, and are released after completion, failure or queued cancellation.
- Adapter restart is a hard interruption boundary. Locally saved frontend job IDs that no longer exist receive a specific Chinese interruption response and a retry action.
- PPT document tasks consume their one-time local file token during queue submission and transfer the staged file to job ownership. Dify upload occurs only after the job receives an execution slot.
- Job-owned files are removed on queued cancellation, completion, failure and process cleanup. The same staged source cannot be submitted twice.
- Existing task endpoints remain stable. Their response envelopes gain queue state, phase, timing and cancellation metadata. A queued-cancellation operation is added under each job family with equivalent FastAPI and standalone behavior.
- The shared coordinator exposes a small runner interface so each task retains its existing request validation, provider call and result parser. Task-specific code does not implement its own queue, TTL or capacity policy.
- Advanced diagnostics show aggregate queue state and recent sanitized terminal metadata only. No unified task center, durable job history or cross-host navigation is introduced.
- Word uses `WindowSelectionChange` when available; Excel uses `SheetSelectionChange` when available. Both use a visible-page low-frequency polling fallback, approximately two seconds, with changed-only DOM updates.
- Host event listeners are removed or suspended when the page is hidden or no longer needs scope updates. Event failure must activate polling rather than freeze the displayed scope.
- Formula Assistant is a new Excel Ribbon command and independent task type `excel.formula_assistant`, with its own workflow profile tab and API key management.
- Formula Assistant uses the shared background job protocol and current Dify `/chat-messages` compatibility behavior, including legacy `inputs.query`, new user-input-node fallback and think-content filtering.
- Formula Assistant has explicit generate and explain/debug modes. It never chooses a mode only because formulas happen to exist in the selection.
- Excel extraction is selection-only. It captures address, headers, cell text, limited type information and existing formulas for at most 30 rows by 20 columns. It never falls back to the worksheet UsedRange.
- Formula output contains one primary formula, an optional materially different alternative, suggested target, explanation, assumptions, compatibility notes, verification checklist and plain-copy forms.
- Explain/debug output contains the original formula, component explanation, referenced ranges, detected concerns, and a corrected formula only when a correction is justified.
- Formula lint is local and non-executing. It checks leading equals, balanced brackets and quotes, bounded length, external workbook or URL references, obvious out-of-selection references, and a maintained compatibility warning list.
- Formula lint never evaluates formulas in hidden cells and never claims semantic or calculation correctness. The visible success language is limited to a basic check.
- Formula Assistant is preview/copy only. It does not assign `Formula`, fill a range, alter workbook calculation, create sheets or participate in undo history.
- Structure Review is a new PPT Ribbon command and independent task type `ppt.structure_review`, with its own workflow profile tab and API key management.
- Structure Review reads only the requested range of slide indices. It normally extracts index, main title and optional subtitle.
- For slides without a detected title, extraction may include at most 120 characters of body text, for no more than 10 slides per request. Other slide body text is not read or sent.
- A single request covers at most 60 slides. Larger presentations require an explicit start and end page; output must label the reviewed range and must not imply full-deck coverage.
- Local structure checks identify deterministic issues such as missing or duplicate titles, excessive title length and obvious numbering discontinuities.
- One model call adds semantic analysis of storyline, inferred chapters, ordering, repetition and missing content. Local and model findings are merged and deduplicated.
- Structure Review output contains overall storyline, inferred chapters, high-priority issues, general suggestions, page-numbered recommendations, and a recommended title order or outline. It does not contain a numeric quality score.
- Structure Review is preview/copy only. It does not create, delete, reorder or edit slides, shapes, text, layouts, themes, charts, notes or animations.
- Excel Formula Assistant and PPT Structure Review each receive their own prompt-engineering Markdown template in the formal package.
- The current Apple Design-derived task-pane system remains: Excel green, PPT orange, system fonts, compact disclosure, no nested cards, no decorative icon in primary result buttons, keyboard focus and reduced-motion support.

## Testing Decisions

- Good tests assert externally visible state transitions, API responses, provider invocation count, data bounds, cleanup and user-visible rendering. They do not assert thread names, lock use, private queue containers or exact internal class layout.
- The primary seam is the background job HTTP contract. Existing and new job families are tested through submission, polling, queued cancellation and terminal retrieval with fake runners and a fake monotonic clock.
- Queue contract tests cover FIFO order, two-running/eight-queued defaults, full-capacity rejection, idempotent duplicate submission, no running-job eviction, terminal TTL, terminal capacity, phase timing and sanitized errors.
- Snapshot tests change workflow profiles and credentials after submission, then verify the provider receives the original in-memory snapshot without exposing its secret in responses or diagnostics.
- PPT file lifecycle tests verify token consumption at submission, no upload before an execution slot, one upload for duplicate IDs, cleanup on every terminal path and cleanup after queued cancellation.
- FastAPI and standalone dispatch are tested for equivalent status, error and cancellation envelopes.
- Existing Document Review, Excel Smart Analysis and PPT Smart Summary tests are extended rather than replaced, preserving their current route, result and long-polling contracts.
- WPS host extraction is tested through simulated host objects at the helper boundary. Word event handling, Excel event handling, fallback polling, visibility pausing and changed-only updates are observable without a real document.
- Excel extraction tests cover formulas, values, headers, 30×20 limits, total text bounds, truncation messages, missing selection and the prohibition on UsedRange fallback.
- Formula lint tests cover safe formulas, malformed brackets and quotes, oversized input, external workbook references, URL/network functions, compatibility warnings and false claims of correctness.
- Formula Assistant route tests verify mode-specific validation, one provider call, think filtering, structured result fallback, copy text and no workbook write path.
- PPT extraction tests cover title and subtitle separation, blank-title fallback, 120-character truncation, ten-fallback-page limit, start/end validation and 60-slide limit.
- Structure Review tests cover deterministic findings, one semantic provider call, deduplication, page-numbered issues, reviewed-range disclosure, recommended outline and absence of a numeric score.
- Frontend helper and task-pane contract tests verify new Ribbon isolation, workflow tabs, queue state rendering, cancellation visibility, result copy actions, Chinese errors and no automatic write action.
- Browser tests cover Excel and PPT task/settings pages at 420×900 and 320×700, including queued, running, completed, failed, empty and degraded states, with zero page-level horizontal overflow.
- Regression tests protect Word Smart Write formatting, comparison highlighting and writeback; Smart Imitation preview/copy-only behavior; Document Review record toggling and think filtering; Format Review behavior; Excel Smart Analysis; PPT current-page/document Smart Summary; workflow profiles and package preservation.
- Kylin V10 acceptance is mandatory for WPS event delivery, fallback polling, Formula/FormulaLocal access, large selection extraction, Slides collection traversal, subtitle handling, 60-slide extraction, long queue waits and Adapter restart messaging.
- Performance acceptance records idle visible and hidden task-pane host reads, event-to-scope update latency, fallback update latency, queue wait, provider time, parse time, total time and memory behavior with 50 retained terminal results.
- Each release runs the full Python and frontend suites, syntax/type checks, real-browser layout checks, first-install/overwrite protection tests and single three-host package audit before delivery.

## Out of Scope

- New Word business features.
- Migrating Smart Write, Smart Imitation or Format Review into the shared queue.
- True cross-Adapter-restart recovery while using blocking Dify `/chat-messages`.
- Claiming that closing a local HTTP connection cancels Dify computation.
- Estimated progress percentages.
- A unified task center, durable task history or cloud job history.
- Automatic Excel formula insertion, hidden-cell evaluation, range fill, worksheet creation, chart generation or data-cleaning writeback.
- Reading Excel UsedRange when Formula Assistant lacks an explicit selection.
- Guaranteeing formula calculation correctness or full compatibility across all WPS versions.
- PPT slide creation, deletion, reordering, text writeback, layout changes, theme changes, chart changes, note generation or animation changes.
- Reading all PPT body text or automatically splitting a deck into multiple model calls.
- PPT numeric quality scores.
- PPT speaker-note generation and visual-layout review; these remain future candidates after the three releases pass target-machine acceptance.
- Runtime changes to the writing policy library, provider timeout budgets, Dify payload compatibility, API URL/Key preservation or three-host installation model unless required by the shared queue contract.

## Further Notes

- Current code already provides idempotent background routes and client-side recovery for the three existing long tasks; the shared coordinator should deepen this existing seam instead of introducing a second task framework.
- Current Word and Excel scope indicators rely on 800 ms and 1200 ms polling respectively. WPS type definitions expose the intended selection events, but Linux runtime support remains a target-machine fact to verify rather than an assumption.
- Current WPS ET type definitions expose Formula, FormulaLocal, FormulaR1C1 and HasFormula. Their presence supports the design but does not replace Kylin V10 validation.
- Current PPT extraction already separates main title, optional subtitle, body blocks and adjacent titles. Structure Review should reuse this proven title-detection behavior across a bounded slide range.
- The strongest Adapter correctness risk is not raw model latency: it is unbounded per-request worker creation and inconsistent capacity eviction across separate job stores. The stability release addresses that risk before adding model features.
- Version confidence: Adapter queue and result-retention design is high; Excel formula property compatibility and WPS selection events are medium until target-machine validation; PPT bounded title extraction is medium-high with the same caveat.
