import type { AppState } from "./state";

export function renderApp(state: AppState): void {
  const statusNode = document.getElementById("status");
  const resultPanel = document.getElementById("result-panel");

  if (statusNode) {
    statusNode.textContent = `Adapter health: ${state.healthStatus}`;
  }

  if (resultPanel) {
    if (state.error) {
      resultPanel.textContent = state.error;
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
