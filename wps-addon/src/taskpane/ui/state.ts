import type {
  FormatPreviewChange,
  ProofreadIssue,
  RewriteResult,
  RuntimeProbeResult,
  TemplateSummary
} from "../api/types";

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
  rewriteResult?: RewriteResult;
  runtimeProbe?: RuntimeProbeResult;
  pendingApplyAction?: "format" | "rewrite";
  appliedMessage?: string;
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
