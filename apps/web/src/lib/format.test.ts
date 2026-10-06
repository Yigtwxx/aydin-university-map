import { describe, expect, it } from "vitest";

import { formatDistance, formatDuration } from "./format";

describe("formatDistance", () => {
  it.each([
    [7.4, "tr", "7 m"],
    [123, "en", "125 m"],
    [1530, "tr", "1,5 km"],
    [1530, "en", "1.5 km"],
  ] as const)("formats %d m in %s as %s", (metres, locale, expected) => {
    expect(formatDistance(metres, locale)).toBe(expected);
  });
});

describe("formatDuration", () => {
  it("never shows less than one minute", () => {
    expect(formatDuration(12, "en")).toBe("1 min");
  });

  it("uses the Turkish abbreviation", () => {
    expect(formatDuration(310, "tr")).toBe("5 dk");
  });
});
