import { describe, expect, it } from "vitest";

import { collectRuntimeProbe } from "../../src/taskpane/wps/probe";

describe("runtime probe", () => {
  it("captures WPS runtime capabilities and adapter health", async () => {
    (
      globalThis as typeof globalThis & {
        window?: Record<string, unknown>;
      }
    ).window = Object.assign((globalThis as typeof globalThis & { window?: Record<string, unknown> }).window ?? {}, {
      wps: {
        ActiveDocument: {
          Name: "probe.docx",
          Selection: { Text: "demo" },
          Paragraphs: [
            {
              Text: "Heading",
              ParagraphFormat: { OutlineLevel: 1 }
            },
            {
              Text: "Body",
              ParagraphFormat: { OutlineLevel: 0 }
            }
          ]
        }
      }
    });

    const client = {
      async getHealth() {
        return {
          data: {
            status: "ok",
            service: "wps-ai-adapter"
          }
        };
      }
    };

    const result = await collectRuntimeProbe(client as any);

    expect(result.runtime.hasWpsGlobal).toBe(true);
    expect(result.runtime.hasActiveDocument).toBe(true);
    expect(result.runtime.hasSelection).toBe(true);
    expect(result.runtime.paragraphCount).toBe(2);
    expect(result.runtime.headingCount).toBe(1);
    expect(result.adapter.reachable).toBe(true);
    expect(result.adapter.service).toBe("wps-ai-adapter");
  });
});
