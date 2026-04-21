import type { FormatPreviewChange, Paragraph, RewriteResult } from "../api/types";

interface MutableParagraphLike {
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

interface MutableSelectionLike {
  Text?: string;
  Range?: {
    Text?: string;
  };
}

interface MutableDocumentLike {
  Name?: string;
  Content?: {
    Text?: string;
  };
  Paragraphs?: MutableParagraphLike[];
  paragraphs?: MutableParagraphLike[];
  Selection?: MutableSelectionLike;
}

declare global {
  interface Window {
    wps?: {
      ActiveDocument?: MutableDocumentLike;
    };
    __WPS_MOCK_DOCUMENT__?: MutableDocumentLike;
  }
}

function getMutableActiveDocument(): MutableDocumentLike {
  return window.wps?.ActiveDocument ?? window.__WPS_MOCK_DOCUMENT__ ?? {};
}

function getParagraphs(document: MutableDocumentLike): MutableParagraphLike[] {
  return document.Paragraphs ?? document.paragraphs ?? [];
}

function applyParagraphStyle(
  paragraph: MutableParagraphLike,
  targetStyle: string,
  sourceParagraph?: Paragraph
): void {
  paragraph.StyleNameLocal = targetStyle;
  paragraph.styleName = targetStyle;
  paragraph.Font = paragraph.Font ?? {};
  paragraph.ParagraphFormat = paragraph.ParagraphFormat ?? {};

  if (targetStyle === "Body") {
    paragraph.Font.NameFarEast = "SimSun";
    paragraph.Font.Name = "SimSun";
    paragraph.Font.Size = 12;
    paragraph.ParagraphFormat.OutlineLevel = 0;
  } else if (targetStyle.startsWith("Heading")) {
    const level = Number(targetStyle.split(" ")[1] ?? sourceParagraph?.outlineLevel ?? 1);
    paragraph.Font.NameFarEast = "SimHei";
    paragraph.Font.Name = "SimHei";
    paragraph.Font.Size = level === 1 ? 16 : 14;
    paragraph.ParagraphFormat.OutlineLevel = level;
  }
}

export function applyFormattingChanges(
  changes: FormatPreviewChange[],
  sourceParagraphs: Paragraph[]
): void {
  const document = getMutableActiveDocument();
  const paragraphs = getParagraphs(document);

  changes.forEach((change) => {
    const paragraph = paragraphs[change.paragraphIndex - 1];
    const sourceParagraph = sourceParagraphs[change.paragraphIndex - 1];
    if (!paragraph) {
      return;
    }

    applyParagraphStyle(paragraph, change.targetStyle, sourceParagraph);
  });
}

export function applyRewriteResult(
  result: RewriteResult,
  selectionMode: "document" | "selection"
): void {
  const document = getMutableActiveDocument();
  if (selectionMode === "selection" && document.Selection) {
    document.Selection.Text = result.rewrittenText;
    if (document.Selection.Range) {
      document.Selection.Range.Text = result.rewrittenText;
    }
    return;
  }

  if (document.Content) {
    document.Content.Text = result.rewrittenText;
  }

  const paragraphs = getParagraphs(document);
  if (paragraphs.length > 0) {
    paragraphs[0].Text = result.rewrittenText;
    paragraphs[0].text = result.rewrittenText;
  }
}
