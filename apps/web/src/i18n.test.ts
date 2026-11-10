import { resources } from "@mandi/i18n";
import { describe, expect, it } from "vitest";

function keys(obj: unknown, prefix = ""): string[] {
  if (Array.isArray(obj) || typeof obj !== "object" || obj === null) return [prefix];
  return Object.entries(obj).flatMap(([k, v]) => keys(v, prefix ? `${prefix}.${k}` : k));
}

describe("UI translations", () => {
  const en = keys(resources.en.translation).sort();
  for (const [code, res] of Object.entries(resources)) {
    it(`${code} has exactly the English keys`, () => {
      expect(keys(res.translation).sort()).toEqual(en);
    });
  }
});
