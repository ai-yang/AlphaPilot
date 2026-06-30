export type ApiError = { detail?: string };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init
  });
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`;
    try {
      const body = (await res.json()) as ApiError;
      if (body.detail) message = body.detail;
    } catch {
      /* keep status message */
    }
    throw new Error(message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: JSON.stringify(body ?? {}) }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body ?? {}) }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" })
};

export function qs(params: Record<string, unknown>): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  });
  const text = search.toString();
  return text ? `?${text}` : "";
}

export type Job = {
  job_id: string;
  kind: string;
  status: string;
  pid?: number | null;
  created_at?: string;
  started_at?: string | null;
  finished_at?: string | null;
  error?: string | null;
  result_summary?: string | null;
  params?: Record<string, unknown>;
  progress?: JobProgress;
};

export type JobProgress = {
  job_id?: string;
  status?: string;
  percent: number;
  stage: string;
  message?: string;
  updated_at?: string;
  completed?: number;
  total?: number;
  pending?: number;
  current_symbol?: string;
  current_file?: string;
  latest_data_date?: string;
  progress_source?: string;
};

export type Factor = {
  factor_name: string;
  factor_expression: string;
  categories?: string[];
};

export type Schedule = {
  schedule_id: string;
  name: string;
  kind: string;
  time: string;
  enabled: boolean;
  kwargs: Record<string, unknown>;
  last_run_at?: string | null;
  last_run_date?: string | null;
  last_job_id?: string | null;
  next_run_at?: string | null;
};
