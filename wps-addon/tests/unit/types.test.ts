import { describe, expect, it } from "vitest";

import { getDefaultBaseUrl } from "../../src/taskpane/api/client";
import {
  isWordFormatPreviewResponse,
  isWordProofreadResponse
} from "../../src/taskpane/api/types";

describe("response contracts", () => {
  it("accepts the common envelope", () => {
    expect(
      isWordProofreadResponse({
        success: true,
        traceId: "trace-1",
        taskType: "word.proofread",
        message: "completed",
        data: { issues: [] },
        errors: []
      })
    ).toBe(true);
  });

  it("uses localhost as the default adapter host", () => {
    expect(getDefaultBaseUrl()).toBe("http://127.0.0.1:18100");
  });

  it("rejects invalid proofread payloads", () => {
    expect(
      isWordProofreadResponse({
        success: true,
        traceId: "trace-1",
        taskType: "word.proofread",
        message: "completed",
        data: {},
        errors: []
      })
    ).toBe(false);
  });

  it("accepts valid format preview payloads", () => {
    expect(
      isWordFormatPreviewResponse({
        success: true,
        traceId: "trace-2",
        taskType: "word.format_preview",
        message: "completed",
        data: {
          changes: [],
          summary: {
            changeCount: 0,
            templateId: "general-office"
          }
        },
        errors: []
      })
    ).toBe(true);
  });
});
