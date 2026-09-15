import type { Asset, Artifact, Dataset, Job, JobSpec, Page, RegisteredModel, Template } from "./research.generated";

let token = "";
export const terminalJob = (status: string) => ["succeeded", "failed", "cancelled", "lost"].includes(status);
export const getResearchToken = () => token;
export function setResearchToken(value: string) {
  token = value.trim();
  window.dispatchEvent(new Event("research-connection"));
}
export class ResearchError extends Error {
  constructor(public status: number, public code: string, message: string, public details?: unknown) { super(message); }
}
async function response(path: string, init: RequestInit = {}) {
  if (!token) throw new ResearchError(401, "UNAUTHENTICATED", "请先连接研究服务");
  if (!path.startsWith("/") || path.startsWith("//")) throw new Error("Expected a research API resource");
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const res = await fetch(`/api/v1${path}`, { ...init, headers });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    if (res.status === 401) setResearchToken("");
    throw new ResearchError(res.status, body.code || "HTTP_ERROR", body.message || res.statusText, body.details);
  }
  return res;
}
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await response(path, init);
  return res.status === 204 ? undefined as T : res.json();
}
export const research = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body: unknown = {}, key: string = crypto.randomUUID()) => request<T>(path, { method: "POST", headers: { "Idempotency-Key": key }, body: JSON.stringify(body) }),
  edit: <T>(path: string, body: unknown, revision: number, method = "PATCH") => request<T>(path, { method, headers: { "If-Match": String(revision) }, body: JSON.stringify(body) }),
  delete: <T>(path: string, revision?: number) => request<T>(path, { method: "DELETE", headers: revision === undefined ? {} : { "If-Match": String(revision) } }),
  upload: async (file: File) => { const body = new FormData(); body.append("file", file); const uploaded = await request<{ upload_id: string }>("/uploads", { method: "POST", body }); return { upload_id: uploaded.upload_id }; },
  submit: (job: JobSpec, key: string) => research.post<Job>("/jobs", job, key),
  all: async <T>(path: string): Promise<T[]> => {
    const items: T[] = []; let cursor: string | null = null;
    do {
      const result: Page<T> = await request(`${path}${path.includes("?") ? "&" : "?"}limit=200${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`);
      items.push(...result.items); cursor = result.next_cursor;
    } while (cursor);
    return items;
  },
  text: async (artifact: Artifact) => (await response(`/artifacts/${artifact.artifact_id}/content`)).text(),
  download: async (artifact: Artifact) => {
    const blob = await (await response(`/artifacts/${artifact.artifact_id}/content`)).blob();
    const url = URL.createObjectURL(blob); const link = document.createElement("a");
    link.href = url; link.download = artifact.name; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  },
};
export type Catalogs = { datasets: Dataset[]; templates: Template[]; models: RegisteredModel[]; factors: Asset[]; strategies: Asset[]; pools: Asset[]; sessions: Asset[]; categories?: Asset[] };
export async function loadCatalogs(): Promise<Catalogs> {
  const [datasets, templates, models, factors, strategies, pools, sessions, categories] = await Promise.all([
    research.all<Dataset>("/datasets"), research.all<Template>("/templates"), research.all<RegisteredModel>("/models"),
    research.all<Asset>("/factors"), research.all<Asset>("/strategies"), research.all<Asset>("/stock-pools"), research.all<Asset>("/signal-sessions"), research.get<{ items: Asset[] }>("/factors/categories"),
  ]);
  return { datasets, templates, models, factors, strategies, pools, sessions, categories: categories.items };
}
