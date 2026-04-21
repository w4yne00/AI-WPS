import { AdapterClient } from "../api/client";
import {
  isWordFormatPreviewResponse,
  isWordProofreadResponse,
  isWordRewriteResponse
} from "../api/types";
import { extractActiveDocument, extractCurrentSelection } from "../wps/document";
import { applyFormattingChanges, applyRewriteResult } from "../wps/writeback";
import { initialState, type AppState } from "./state";
import { renderApp } from "./render";

const client = new AdapterClient();
const state: AppState = { ...initialState };
let latestDocumentPayload = {
  documentId: "placeholder-doc",
  scene: "word" as const,
  selectionMode: "document" as const,
  content: {
    plainText: "",
    paragraphs: [],
    headings: []
  },
  options: {
    trackChanges: true
  }
};
let latestSelectionMode: "document" | "selection" = "document";

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
  try {
    state.loading = true;
    state.error = undefined;
    renderApp(state);

    const payload = extractActiveDocument();
    latestDocumentPayload = payload;
    latestSelectionMode = payload.selectionMode;
    payload.options.templateId = state.selectedTemplateId;

    const response = await client.postWordProofread(payload);
    if (!isWordProofreadResponse(response)) {
      throw new Error("Unexpected proofread response shape");
    }

    state.loading = false;
    state.issues = response.data.issues;
    state.formatChanges = [];
    state.formatSummary = undefined;
    state.rewriteResult = undefined;
    state.pendingApplyAction = undefined;
    state.appliedMessage = undefined;
    state.traceId = response.traceId;
    renderApp(state);
  } catch (error) {
    state.loading = false;
    state.error = error instanceof Error ? error.message : "Unknown error";
    renderApp(state);
  }
}

export async function runFormatPreview(): Promise<void> {
  try {
    state.loading = true;
    state.error = undefined;
    renderApp(state);

    const payload = extractActiveDocument();
    latestDocumentPayload = payload;
    latestSelectionMode = payload.selectionMode;
    payload.options.templateId = state.selectedTemplateId;

    const response = await client.postWordFormatPreview(payload);
    if (!isWordFormatPreviewResponse(response)) {
      throw new Error("Unexpected format preview response shape");
    }

    state.loading = false;
    state.issues = [];
    state.formatChanges = response.data.changes;
    state.formatSummary = response.data.summary;
    state.rewriteResult = undefined;
    state.pendingApplyAction = "format";
    state.appliedMessage = undefined;
    state.traceId = response.traceId;
    renderApp(state);
  } catch (error) {
    state.loading = false;
    state.error = error instanceof Error ? error.message : "Unknown error";
    renderApp(state);
  }
}

export async function runRewrite(): Promise<void> {
  try {
    state.loading = true;
    state.error = undefined;
    renderApp(state);

    const payload = extractCurrentSelection();
    latestDocumentPayload = payload;
    latestSelectionMode = payload.selectionMode;
    payload.options.templateId = state.selectedTemplateId;

    const response = await client.postWordRewrite(payload);
    if (!isWordRewriteResponse(response)) {
      throw new Error("Unexpected rewrite response shape");
    }

    state.loading = false;
    state.issues = [];
    state.formatChanges = [];
    state.formatSummary = undefined;
    state.rewriteResult = response.data;
    state.pendingApplyAction = "rewrite";
    state.appliedMessage = undefined;
    state.traceId = response.traceId;
    renderApp(state);
  } catch (error) {
    state.loading = false;
    state.error = error instanceof Error ? error.message : "Unknown error";
    renderApp(state);
  }
}

export function applyPreview(): void {
  if (state.pendingApplyAction === "format") {
    applyFormattingChanges(state.formatChanges, latestDocumentPayload.content.paragraphs);
    state.appliedMessage = "Format changes applied.";
    state.pendingApplyAction = undefined;
    renderApp(state);
    return;
  }

  if (state.pendingApplyAction === "rewrite" && state.rewriteResult) {
    applyRewriteResult(state.rewriteResult, latestSelectionMode);
    state.appliedMessage = "Rewrite result applied.";
    state.pendingApplyAction = undefined;
    renderApp(state);
  }
}
