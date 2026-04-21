import { describe, expect, it } from "vitest";

import { getDefaultBaseUrl } from "../../src/taskpane/api/client";
import { isWordProofreadResponse } from "../../src/taskpane/api/types";

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
});
