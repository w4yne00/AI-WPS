import { AdapterClient } from "../api/client";
import { isWordProofreadResponse } from "../api/types";
import { initialState, type AppState } from "./state";
import { renderApp } from "./render";

const client = new AdapterClient();
const state: AppState = { ...initialState };

export async function initializeApp(): Promise<void> {
  try {
    state.loading = true;
    renderApp(state);

    const [health, templates] = await Promise.all([
      client.getHealth(),
      client.getTemplates()
    ]);

    state.healthStatus = health.data.status;
    state.templates = templates.data.templates;
    state.selectedTemplateId = state.templates[0]?.id;
    state.loading = false;
    renderApp(state);
  } catch (error) {
    state.loading = false;
    state.error = error instanceof Error ? error.message : "Unknown error";
    renderApp(state);
  }
}

export async function runProofread(): Promise<void> {
  const payload = {
    documentId: "placeholder-doc",
    scene: "word" as const,
    selectionMode: "document" as const,
    content: {
      plainText: "Placeholder document content.",
      paragraphs: [],
      headings: []
    },
    options: {
      templateId: state.selectedTemplateId,
      trackChanges: true
    }
  };

  const response = await client.postWordProofread(payload);
  if (!isWordProofreadResponse(response)) {
    throw new Error("Unexpected proofread response shape");
  }

  state.issues = response.data.issues;
  state.traceId = response.traceId;
  renderApp(state);
}
