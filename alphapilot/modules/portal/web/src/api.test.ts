import { afterEach, describe, expect, it, vi } from "vitest";
import { api, qs } from "./api";

function mockFetch(response: {
  ok?: boolean;
  status?: number;
  statusText?: string;
  json?: unknown;
}) {
  const fn = vi.fn().mockResolvedValue({
    ok: response.ok ?? true,
    status: response.status ?? 200,
    statusText: response.statusText ?? "OK",
    json: async () => response.json ?? {},
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("api client", () => {
  it("GET sends JSON content-type and parses the body", async () => {
    const fetchMock = mockFetch({ json: { hello: "world" } });
    const out = await api.get<{ hello: string }>("/api/status");
    expect(out).toEqual({ hello: "world" });
    const [path, init] = fetchMock.mock.calls[0];
    expect(path).toBe("/api/status");
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
  });

  it("POST serializes the body and sets the method", async () => {
    const fetchMock = mockFetch({ json: { ok: true } });
    await api.post("/api/factors", { factor_name: "f", factor_expression: "$close" });
    const [, init] = fetchMock.mock.calls[0];
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      factor_name: "f",
      factor_expression: "$close",
    });
  });

  it("POST with no body sends an empty object", async () => {
    const fetchMock = mockFetch({ json: {} });
    await api.post("/api/jobs/clear");
    const [, init] = fetchMock.mock.calls[0];
    expect(init.body).toBe("{}");
  });

  it("PATCH and DELETE use the right verbs", async () => {
    const fetchMock = mockFetch({ json: {} });
    await api.patch("/api/notify", { config: {} });
    await api.delete("/api/factors/x");
    expect(fetchMock.mock.calls[0][1].method).toBe("PATCH");
    expect(fetchMock.mock.calls[1][1].method).toBe("DELETE");
  });

  it("throws the server detail message on error responses", async () => {
    mockFetch({ ok: false, status: 400, statusText: "Bad Request", json: { detail: "bad expr" } });
    await expect(api.get("/api/factors/validate")).rejects.toThrow("bad expr");
  });

  it("falls back to status text when no detail is present", async () => {
    mockFetch({ ok: false, status: 500, statusText: "Server Error", json: {} });
    await expect(api.get("/api/x")).rejects.toThrow("500 Server Error");
  });

  it("returns undefined for 204 No Content", async () => {
    mockFetch({ status: 204, json: {} });
    const out = await api.delete("/api/factors/x");
    expect(out).toBeUndefined();
  });
});

describe("qs", () => {
  it("builds a query string and drops empty values", () => {
    expect(qs({ a: 1, b: "x", c: "", d: null, e: undefined })).toBe("?a=1&b=x");
  });

  it("returns an empty string when nothing is set", () => {
    expect(qs({ a: "", b: null })).toBe("");
  });
});
