import { describe, expect, it } from "vitest";
import {
  buildParams,
  dataActionSpecs,
  defaultValuesFor,
  visibleFields,
  type FieldSpec,
} from "./paramSpecs";

const specs: FieldSpec[] = [
  { key: "name", label: "Name", type: "text", required: true },
  { key: "count", label: "Count", type: "number", defaultValue: 5 },
  { key: "flag", label: "Flag", type: "checkbox", defaultValue: false },
  { key: "mode", label: "Mode", type: "select", defaultValue: "a" },
  {
    key: "extra",
    label: "Extra",
    type: "text",
    visibleWhen: (v) => v.mode === "b",
  },
  { key: "_uiOnly", label: "UI", type: "text", defaultValue: "ignored" },
  { key: "yaml_params.topk", label: "TopK", type: "number" },
];

describe("defaultValuesFor", () => {
  it("uses declared defaults and sensible empties", () => {
    const v = defaultValuesFor(specs);
    expect(v.count).toBe(5);
    expect(v.flag).toBe(false);
    expect(v.name).toBe("");
  });
});

describe("visibleFields", () => {
  it("hides fields whose visibleWhen is false", () => {
    const keys = visibleFields(specs, { mode: "a" }).map((f) => f.key);
    expect(keys).not.toContain("extra");
  });

  it("shows conditional fields when the predicate passes", () => {
    const keys = visibleFields(specs, { mode: "b" }).map((f) => f.key);
    expect(keys).toContain("extra");
  });
});

describe("buildParams", () => {
  it("coerces numbers, booleans and drops empties + UI-only keys", () => {
    const params = buildParams(specs, {
      name: "hi",
      count: "7",
      flag: true,
      mode: "a",
      _uiOnly: "x",
      "yaml_params.topk": "30",
    });
    expect(params).toEqual({ name: "hi", count: 7, flag: true, mode: "a", yaml_params: { topk: 30 } });
    expect(params).not.toHaveProperty("_uiOnly");
  });

  it("throws when a required field is missing", () => {
    expect(() => buildParams(specs, { name: "" })).toThrow(/required/i);
  });

  it("merges valid advanced JSON overrides", () => {
    const params = buildParams(specs, { name: "hi", mode: "a" }, '{"seed": 1}');
    expect(params.seed).toBe(1);
  });

  it("rejects advanced JSON that is not an object", () => {
    expect(() => buildParams(specs, { name: "hi", mode: "a" }, "[1,2,3]")).toThrow(/object/i);
  });
});

describe("real spec catalogs", () => {
  it("dataActionSpecs default to the pipeline action", () => {
    const v = defaultValuesFor(dataActionSpecs);
    expect(v.action).toBe("pipeline");
  });
});
