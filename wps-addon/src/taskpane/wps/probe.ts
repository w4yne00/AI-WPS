import { AdapterClient, getDefaultBaseUrl } from "../api/client";
import type { RuntimeProbeResult } from "../api/types";
import { collectHeadings, collectParagraphs } from "./document";

interface ProbeDocumentLike {
  Name?: string;
  Paragraphs?: unknown[];
  paragraphs?: unknown[];
  Selection?: unknown;
}

declare global {
  interface Window {
    wps?: {
      ActiveDocument?: ProbeDocumentLike;
    };
    __WPS_MOCK_DOCUMENT__?: ProbeDocumentLike;
  }
}

function getRuntimeDocument(): ProbeDocumentLike | undefined {
  return window.wps?.ActiveDocument ?? window.__WPS_MOCK_DOCUMENT__;
}

export async function collectRuntimeProbe(
  client: AdapterClient = new AdapterClient()
): Promise<RuntimeProbeResult> {
  const document = getRuntimeDocument();
  const paragraphs = document ? collectParagraphs(document) : [];
  const headings = collectHeadings(paragraphs);

  const probe: RuntimeProbeResult = {
    runtime: {
      hasWpsGlobal: typeof window.wps !== "undefined",
      hasActiveDocument: Boolean(document),
      hasSelection: Boolean(document?.Selection),
      activeDocumentName: document?.Name,
      paragraphCount: paragraphs.length,
      headingCount: headings.length
    },
    adapter: {
      reachable: false,
      baseUrl: getDefaultBaseUrl()
    }
  };

  try {
    const health = await client.getHealth();
    probe.adapter = {
      reachable: true,
      status: health.data.status,
      service: health.data.service,
      baseUrl: getDefaultBaseUrl()
    };
  } catch (error) {
    probe.adapter = {
      reachable: false,
      baseUrl: getDefaultBaseUrl(),
      error: error instanceof Error ? error.message : "Unknown error"
    };
  }

  return probe;
}
