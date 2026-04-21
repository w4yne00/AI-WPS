import { describe, expect, it } from "vitest";

import type { RewriteResult } from "../../src/taskpane/api/types";
import { applyRewriteResult, applyFormattingChanges } from "../../src/taskpane/wps/writeback";

describe("Word writeback", () => {
  it("applies rewrite text into the current selection", () => {
    (
      globalThis as typeof globalThis & {
        window?: Record<string, unknown>;
      }
    ).window = Object.assign((globalThis as typeof globalThis & { window?: Record<string, unknown> }).window ?? {}, {
      __WPS_MOCK_DOCUMENT__: {
        Content: { Text: "Original document" },
        Selection: { Text: "Original selection", Range: { Text: "Original selection" } },
        Paragraphs: [{ Text: "Original document" }]
      }
    });

    const result: RewriteResult = {
      originalText: "Original selection",
      rewrittenText: "Rewritten selection",
      rewriteMode: "continue",
      diffHints: ["Text content changed"]
    };

    applyRewriteResult(result, "selection");

    const doc = (globalThis as typeof globalThis & { window?: Record<string, any> }).window
      ?.__WPS_MOCK_DOCUMENT__;
    expect(doc.Selection.Text).toBe("Rewritten selection");
    expect(doc.Selection.Range.Text).toBe("Rewritten selection");
  });

  it("applies format changes into paragraph metadata", () => {
    (
      globalThis as typeof globalThis & {
        window?: Record<string, unknown>;
      }
    ).window = Object.assign((globalThis as typeof globalThis & { window?: Record<string, unknown> }).window ?? {}, {
      __WPS_MOCK_DOCUMENT__: {
        Paragraphs: [
          {
            Text: "Heading",
            StyleNameLocal: "Body",
            Font: { NameFarEast: "SimSun", Size: 12 },
            ParagraphFormat: { OutlineLevel: 0 }
          }
        ]
      }
    });

    applyFormattingChanges(
      [
        {
          paragraphIndex: 1,
          currentStyle: "Body",
          targetStyle: "Heading 1",
          reason: "align heading font with template"
        }
      ],
      [
        {
          index: 1,
          text: "Heading",
          styleName: "Body",
          fontName: "SimSun",
          fontSize: 12,
          alignment: "left",
          outlineLevel: 0
        }
      ]
    );

    const doc = (globalThis as typeof globalThis & { window?: Record<string, any> }).window
      ?.__WPS_MOCK_DOCUMENT__;
    expect(doc.Paragraphs[0].StyleNameLocal).toBe("Heading 1");
    expect(doc.Paragraphs[0].Font.NameFarEast).toBe("SimHei");
    expect(doc.Paragraphs[0].ParagraphFormat.OutlineLevel).toBe(1);
  });
});
