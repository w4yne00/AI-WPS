import type { Heading, Paragraph, WordDocumentRequest } from "../api/types";

interface WpsParagraphLike {
  Text?: string;
  text?: string;
  StyleNameLocal?: string;
  styleName?: string;
  Font?: {
    NameFarEast?: string;
    Name?: string;
    Size?: number;
  };
  ParagraphFormat?: {
    Alignment?: string | number;
    OutlineLevel?: number;
  };
}

interface WpsSelectionLike {
  Text?: string;
  Range?: {
    Text?: string;
  };
}

interface WpsDocumentLike {
  Name?: string;
  Content?: {
    Text?: string;
  };
  Paragraphs?: WpsParagraphLike[];
  paragraphs?: WpsParagraphLike[];
  Selection?: WpsSelectionLike;
}

declare global {
  interface Window {
    wps?: {
      ActiveDocument?: WpsDocumentLike;
    };
    __WPS_MOCK_DOCUMENT__?: WpsDocumentLike;
  }
}

function getActiveDocument(): WpsDocumentLike {
  const runtimeDocument = window.wps?.ActiveDocument;
  if (runtimeDocument) {
    return runtimeDocument;
  }

  if (window.__WPS_MOCK_DOCUMENT__) {
    return window.__WPS_MOCK_DOCUMENT__;
  }

  return {
    Name: "placeholder-doc",
    Content: {
      Text: "Placeholder document content."
    },
    Paragraphs: [
      {
        Text: "Placeholder document content.",
        StyleNameLocal: "Body",
        Font: {
          NameFarEast: "SimSun",
          Size: 12
        },
        ParagraphFormat: {
          Alignment: "left",
          OutlineLevel: 0
        }
      }
    ]
  };
}

function toParagraph(paragraph: WpsParagraphLike, index: number): Paragraph {
  return {
    index,
    text: paragraph.Text ?? paragraph.text ?? "",
    styleName: paragraph.StyleNameLocal ?? paragraph.styleName ?? "Body",
    fontName: paragraph.Font?.NameFarEast ?? paragraph.Font?.Name,
    fontSize: paragraph.Font?.Size,
    alignment: String(paragraph.ParagraphFormat?.Alignment ?? "left"),
    outlineLevel: paragraph.ParagraphFormat?.OutlineLevel ?? 0
  };
}

export function collectParagraphs(document: WpsDocumentLike): Paragraph[] {
  const paragraphs = document.Paragraphs ?? document.paragraphs ?? [];
  return paragraphs.map((paragraph, index) => toParagraph(paragraph, index + 1));
}

export function collectHeadings(paragraphs: Paragraph[]): Heading[] {
  return paragraphs
    .filter((paragraph) => (paragraph.outlineLevel ?? 0) > 0)
    .map((paragraph) => ({
      level: paragraph.outlineLevel ?? 1,
      text: paragraph.text
    }));
}

export function extractActiveDocument(): WordDocumentRequest {
  const document = getActiveDocument();
  const paragraphs = collectParagraphs(document);
  return {
    documentId: document.Name ?? "placeholder-doc",
    scene: "word",
    selectionMode: "document",
    content: {
      plainText: document.Content?.Text ?? paragraphs.map((paragraph) => paragraph.text).join("\n"),
      paragraphs,
      headings: collectHeadings(paragraphs)
    },
    options: {
      trackChanges: true
    }
  };
}

export function extractCurrentSelection(): WordDocumentRequest {
  const document = getActiveDocument();
  const activeDocument = extractActiveDocument();
  const selectionText =
    document.Selection?.Text ?? document.Selection?.Range?.Text ?? activeDocument.content.plainText;

  return {
    ...activeDocument,
    selectionMode: "selection",
    content: {
      ...activeDocument.content,
      plainText: selectionText
    }
  };
}
