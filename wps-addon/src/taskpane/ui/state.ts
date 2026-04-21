import type { ProofreadIssue, TemplateSummary } from "../api/types";

export interface AppState {
  healthStatus: string;
  loading: boolean;
  selectedTemplateId?: string;
  templates: TemplateSummary[];
  issues: ProofreadIssue[];
  error?: string;
  traceId?: string;
}

export const initialState: AppState = {
  healthStatus: "unknown",
  loading: false,
  templates: [],
  issues: []
};
