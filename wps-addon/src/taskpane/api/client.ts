import type {
  ApiEnvelope,
  ConfigSummary,
  FormatPreviewResult,
  ProofreadResult,
  RewriteResult,
  TemplateSummary,
  WordDocumentRequest
} from "./types";

const DEFAULT_BASE_URL = "http://127.0.0.1:18100";

export class AdapterClient {
  constructor(private readonly baseUrl = DEFAULT_BASE_URL) {}

  async getHealth(): Promise<ApiEnvelope<{ service: string; status: string; version: string }>> {
    return this.get("/health");
  }

  async getConfig(): Promise<ApiEnvelope<ConfigSummary>> {
    return this.get("/config");
  }

  async getTemplates(): Promise<ApiEnvelope<{ templates: TemplateSummary[] }>> {
    return this.get("/templates");
  }

  async postWordProofread(
    payload: WordDocumentRequest
  ): Promise<ApiEnvelope<ProofreadResult>> {
    return this.post("/word/proofread", payload);
  }

  async postWordFormatPreview(
    payload: WordDocumentRequest
  ): Promise<ApiEnvelope<FormatPreviewResult>> {
    return this.post("/word/format-preview", payload);
  }

  async postWordRewrite(
    payload: WordDocumentRequest
  ): Promise<ApiEnvelope<RewriteResult>> {
    return this.post("/word/rewrite", payload);
  }

  private async get<T>(path: string): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`);
    return this.handleResponse<T>(response);
  }

  private async post<T>(path: string, payload: unknown): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload)
    });
    return this.handleResponse<T>(response);
  }

  private async handleResponse<T>(response: Response): Promise<T> {
    if (!response.ok) {
      throw new Error(`Adapter request failed with status ${response.status}`);
    }

    return (await response.json()) as T;
  }
}

export function getDefaultBaseUrl(): string {
  return DEFAULT_BASE_URL;
}
