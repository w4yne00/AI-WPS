import type { AppState } from "./state";

export function renderApp(state: AppState): void {
  const statusNode = document.getElementById("status");
  const resultPanel = document.getElementById("result-panel");
  const applyButton = document.getElementById("apply-button") as HTMLButtonElement | null;

  if (statusNode) {
    const suffix = state.appliedMessage ? ` | ${state.appliedMessage}` : "";
    statusNode.textContent = `Adapter health: ${state.healthStatus}${suffix}`;
  }

  if (applyButton) {
    applyButton.disabled = state.loading || !state.pendingApplyAction;
  }

  if (resultPanel) {
    if (state.error) {
      resultPanel.textContent = state.error;
      return;
    }

    if (state.rewriteResult) {
      resultPanel.textContent = [
        `Mode: ${state.rewriteResult.rewriteMode}`,
        "",
        "Original:",
        state.rewriteResult.originalText,
        "",
        "Rewritten:",
        state.rewriteResult.rewrittenText,
        "",
        `Hints: ${state.rewriteResult.diffHints.join(", ")}`
      ].join("\n");
      return;
    }

    if (state.formatChanges.length > 0) {
      const summary = state.formatSummary
        ? `Template ${state.formatSummary.templateId}, ${state.formatSummary.changeCount} changes`
        : "Format preview";
      resultPanel.textContent = [
        summary,
        ...state.formatChanges.map(
          (change) =>
            `P${change.paragraphIndex}: ${change.currentStyle} -> ${change.targetStyle} (${change.reason})`
        )
      ].join("\n");
      return;
    }

    if (state.issues.length > 0) {
      resultPanel.textContent = state.issues
        .map((issue) => `${issue.ruleId}: ${issue.message}`)
        .join("\n");
      return;
    }

    resultPanel.textContent = "Waiting for implementation.";
  }
}
