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

    if (state.issues.length > 0) {
      resultPanel.textContent = state.issues
        .map((issue) => `${issue.ruleId}: ${issue.message}`)
        .join("\n");
      return;
    }

    resultPanel.textContent = "Waiting for implementation.";
  }
}
