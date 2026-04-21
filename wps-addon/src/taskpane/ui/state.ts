import type { FormatPreviewChange, ProofreadIssue, TemplateSummary } from "../api/types";

export interface AppState {
  healthStatus: string;
  loading: boolean;
  selectedTemplateId?: string;
  templates: TemplateSummary[];
  issues: ProofreadIssue[];
  formatChanges: FormatPreviewChange[];
  formatSummary?: {
    changeCount: number;
    templateId: string;
  };
  error?: string;
  traceId?: string;
}

export const initialState: AppState = {
  healthStatus: "unknown",
  loading: false,
  templates: [],
  issues: [],
  formatChanges: []
};
