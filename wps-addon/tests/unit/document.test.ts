import { describe, expect, it } from "vitest";

import { collectHeadings, collectParagraphs, extractActiveDocument } from "../../src/taskpane/wps/document";

describe("Word document extraction", () => {
  it("normalizes the active document into the request payload", () => {
    (
      globalThis as typeof globalThis & {
        window?: Record<string, unknown>;
      }
    ).window = Object.assign((globalThis as typeof globalThis & { window?: Record<string, unknown> }).window ?? {}, {
      __WPS_MOCK_DOCUMENT__: {
        Name: "demo.docx",
        Content: {
          Text: "Heading\nBody text"
        },
        Paragraphs: [
          {
            Text: "Heading",
            StyleNameLocal: "Heading 1",
            Font: {
              NameFarEast: "SimHei",
              Size: 16
            },
            ParagraphFormat: {
              Alignment: "center",
              OutlineLevel: 1
            }
          },
          {
            Text: "Body text",
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
      }
    });

    const payload = extractActiveDocument();

    expect(payload.documentId).toBe("demo.docx");
    expect(payload.selectionMode).toBe("document");
    expect(payload.content.paragraphs).toHaveLength(2);
    expect(payload.content.headings).toEqual([{ level: 1, text: "Heading" }]);
  });

  it("derives headings from outlined paragraphs", () => {
    const headings = collectHeadings(
      collectParagraphs({
        Paragraphs: [
          {
            Text: "Section",
            ParagraphFormat: { OutlineLevel: 2 }
          },
          {
            Text: "Body",
            ParagraphFormat: { OutlineLevel: 0 }
          }
        ]
      })
    );

    expect(headings).toEqual([{ level: 2, text: "Section" }]);
  });
});
