export interface Paragraph {
  index: number;
  text: string;
  styleName?: string;
  fontName?: string;
  fontSize?: number;
  alignment?: string;
  outlineLevel?: number;
}

export interface Heading {
  level: number;
  text: string;
}

export interface WordDocumentRequest {
  documentId: string;
  scene: "word";
  selectionMode: "document" | "selection";
  content: {
    plainText: string;
    paragraphs: Paragraph[];
    headings: Heading[];
  };
  options: {
    templateId?: string;
    trackChanges: boolean;
  };
}

export interface ApiEnvelope<TData> {
  success: boolean;
  traceId: string;
  taskType: string;
  message: string;
  data: TData;
  errors: Array<Record<string, unknown>>;
}

export interface ProofreadIssue {
  ruleId: string;
  severity: "info" | "warning" | "error";
  message: string;
  paragraphIndex?: number;
  suggestion?: string;
  autoFixable: boolean;
}

export interface ProofreadResult {
  issues: ProofreadIssue[];
}

export interface TemplateSummary {
  id: string;
  name: string;
  path: string;
}

export interface ConfigSummary {
  servicePort: number;
  difyBaseUrl: string;
  logPath: string;
  templateRoot: string;
  timeoutSeconds: number;
}

export function isWordProofreadResponse(
  value: unknown
): value is ApiEnvelope<ProofreadResult> {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const candidate = value as Partial<ApiEnvelope<ProofreadResult>>;
  return (
    typeof candidate.success === "boolean" &&
    typeof candidate.traceId === "string" &&
    typeof candidate.taskType === "string" &&
    typeof candidate.message === "string" &&
    typeof candidate.data === "object" &&
    candidate.data !== null &&
    Array.isArray((candidate.data as ProofreadResult).issues) &&
    Array.isArray(candidate.errors)
  );
}
