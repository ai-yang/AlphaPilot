import React, { useEffect, useState } from "react";
import type { Artifact, Job, Page, Result, Run } from "./research.generated";
import { research, terminalJob } from "./researchClient";
import { LazyPlot } from "./components/LazyPlot";

const statuses: Record<string, string> = { queued: "排队中", starting: "启动中", running: "执行中", cancelling: "取消中", succeeded: "已完成", failed: "失败", cancelled: "已取消", lost: "执行丢失" };
export function JsonResult({ value }: { value: unknown }) { return <pre className="json">{JSON.stringify(value, null, 2)}</pre>; }
export function ResearchTable({ rows }: { rows: Record<string, unknown>[] }) {
  const columns = [...new Set(rows.flatMap(r => Object.keys(r)))];
  return <div className="table-wrap"><table><thead><tr>{columns.map(c => <th key={c}>{c}</th>)}</tr></thead><tbody>{rows.map((r, i) => <tr key={i}>{columns.map(c => <td key={c}>{typeof r[c] === "object" ? JSON.stringify(r[c]) : String(r[c] ?? "")}</td>)}</tr>)}</tbody></table>{!rows.length && <p>没有记录</p>}</div>;
}
export function ArtifactViewer({ artifact }: { artifact: Artifact }) {
  const [value, setValue] = useState<unknown>(); const [rows, setRows] = useState<Record<string, unknown>[]>([]); const [cursor, setCursor] = useState<string | null>(null); const [error, setError] = useState("");
  const [series, setSeries] = useState<{ rows: Record<string, unknown>[]; downsampled: boolean; total_points: number }>();
  const table = async (next?: string) => {
    try { const p = await research.get<Page<Record<string, unknown>>>(`/artifacts/${artifact.artifact_id}/table?limit=50${next ? `&cursor=${encodeURIComponent(next)}` : ""}`); setRows(p.items); setCursor(p.next_cursor); }
    catch (e) { setError(String(e)); }
  };
  useEffect(() => {
    let active = true; setError(""); setValue(undefined); setRows([]); setSeries(undefined);
    void (async () => {
      try {
        if (artifact.name.endsWith(".csv")) {
          if (["cumulative", "report"].includes(artifact.kind)) {
            const data = await research.get<typeof series>(`/artifacts/${artifact.artifact_id}/series`); if (active) setSeries(data);
          } else {
            const p = await research.get<Page<Record<string, unknown>>>(`/artifacts/${artifact.artifact_id}/table?limit=50`);
            if (active) { setRows(p.items); setCursor(p.next_cursor); }
          }
        } else if (artifact.size <= 1024 * 1024 && /json|text/.test(artifact.media_type)) {
          const text = await research.text(artifact); if (active) setValue(artifact.name.endsWith(".json") ? JSON.parse(text) : text);
        }
      } catch (e) { if (active) setError(String(e)); }
    })();
    return () => { active = false; };
  }, [artifact.artifact_id]);
  return <section><h3>{artifact.kind} · {artifact.name}</h3><p>{artifact.size} bytes · SHA256: <code>{artifact.sha256}</code></p>
    <button className="button" onClick={() => research.download(artifact).catch(e => setError(String(e)))}>下载完整产物</button>
    {error && <p role="alert">{error}</p>}{value !== undefined && <JsonResult value={value} />}
    {series && <><p>{series.downsampled ? `曲线已降采样；原始 ${series.total_points} 个点。指标按完整数据计算。` : `完整曲线，共 ${series.total_points} 个点。`}</p><LazyPlot data={Object.keys(series.rows[0] || {}).filter(k => k !== "date" && typeof series.rows[0][k] === "number").map(k => ({ x: series.rows.map(r => r.date), y: series.rows.map(r => r[k]), type: "scatter", mode: "lines", name: k }))} layout={{ autosize: true, height: 360, margin: { t: 30, l: 60, r: 30, b: 50 } }} config={{ responsive: true }} style={{ width: "100%" }} /></>}
    {!!rows.length && <><ResearchTable rows={rows} /><button className="button small" onClick={() => table()}>第一页</button><button className="button small" disabled={!cursor} onClick={() => cursor && table(cursor)}>下一页</button></>}
  </section>;
}
export function RunDetail({ runId, activeJob = false }: { runId: string; activeJob?: boolean }) {
  const [run, setRun] = useState<Run>(); const [error, setError] = useState(""); const [selected, setSelected] = useState<Artifact>();
  useEffect(() => {
    let active = true; let timer: number | undefined;
    const poll = async () => {
      try { const r = await research.get<Run>(`/runs/${runId}`); if (active) { setRun(r); setError(""); } }
      catch (e) { if (active) setError(String(e)); }
      finally { if (active && activeJob) timer = window.setTimeout(poll, 5000); }
    };
    void poll(); return () => { active = false; if (timer) window.clearTimeout(timer); };
  }, [runId, activeJob]);
  return <div>{error && <p role="alert">{error}</p>}{run && <><JsonResult value={run.metadata} /><div className="row-actions">{run.artifacts.map(a => <button className="button small" key={a.artifact_id} onClick={() => setSelected(a)}>{a.kind} · {a.name}</button>)}</div>{selected && <ArtifactViewer key={selected.artifact_id} artifact={selected} />}</>}</div>;
}
export function JobDetail({ jobId }: { jobId: string }) {
  const [job, setJob] = useState<Job>(); const [result, setResult] = useState<Result>(); const [log, setLog] = useState(""); const [error, setError] = useState(""); const [run, setRun] = useState("");
  useEffect(() => {
    let active = true; let timer: number | undefined; let cursor = 0; setLog(""); setRun(""); setError("");
    const poll = async () => {
      if (document.hidden) { if (active) timer = window.setTimeout(poll, 2000); return; }
      try {
        const [detail, result, logs] = await Promise.all([research.get<Job>(`/jobs/${jobId}`), research.get<Result>(`/jobs/${jobId}/result`), research.get<{ text: string; next_cursor: number; complete: boolean }>(`/jobs/${jobId}/logs?cursor=${cursor}`)]);
        if (!active) return; setJob(detail); setResult(result); setLog(s => (s + logs.text).slice(-262144)); cursor = logs.next_cursor; setError("");
        if (!terminalJob(detail.status) || !logs.complete) timer = window.setTimeout(poll, 2000);
      } catch (e) { if (active) { setError(String(e)); timer = window.setTimeout(poll, 5000); } }
    };
    void poll(); return () => { active = false; if (timer) window.clearTimeout(timer); };
  }, [jobId]);
  return <section className="panel"><h3>{jobId} · {job ? statuses[job.status] : "读取中"}</h3>{error && <p role="alert">{error}</p>}
    {job?.error && <JsonResult value={job.error} />}<details><summary>实际执行参数与资源快照</summary><JsonResult value={job?.normalized_input} /></details>
    <p>{job?.progress.percent == null ? "进度未知" : `${job.progress.percent}%`} {job?.progress.stage} {job?.progress.message}</p>
    <details open><summary>增量日志（保留最近 256 KiB）</summary><pre className="log">{log}</pre></details>
    <h3>结果：{result?.availability}</h3><JsonResult value={result} />
    <div className="row-actions">{job?.run_ids?.map(id => <button key={id} className="button small" onClick={() => setRun(id)}>运行 {id}</button>)}</div>{run && <RunDetail key={run} runId={run} activeJob={!!job && !terminalJob(job.status)} />}
  </section>;
}
export function ResearchJobs({ compact = false }: { compact?: boolean }) {
  const [jobs, setJobs] = useState<Job[]>([]); const [cursor, setCursor] = useState<string>(); const [next, setNext] = useState<string | null>(null); const [selected, setSelected] = useState(""); const [error, setError] = useState("");
  useEffect(() => {
    let active = true; let timer: number | undefined; let inFlight = false;
    const poll = async () => {
      if (inFlight || !active) return;
      inFlight = true;
      try { const p = await research.get<Page<Job>>(`/jobs?limit=${compact ? 5 : 50}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`); if (active) { setJobs(p.items); setNext(p.next_cursor); setError(""); } }
      catch (e) { if (active) setError(String(e)); }
      finally { inFlight = false; if (active) { if (timer) window.clearTimeout(timer); timer = window.setTimeout(poll, 5000); } }
    };
    void poll(); window.addEventListener("research-jobs", poll); return () => { active = false; if (timer) window.clearTimeout(timer); window.removeEventListener("research-jobs", poll); };
  }, [cursor, compact]);
  async function action(job: Job, remove: boolean) {
    try { if (remove) await research.delete(`/jobs/${job.job_id}`); else await research.post(`/jobs/${job.job_id}/cancel`); window.dispatchEvent(new Event("research-jobs")); if (remove && selected === job.job_id) setSelected(""); }
    catch (e) { setError(String(e)); }
  }
  return <section className="panel"><h2>共享任务队列</h2>{error && <p role="alert">{error}</p>}<div className="table-wrap"><table><thead><tr><th>任务</th><th>类型</th><th>状态</th><th>客户端</th><th>操作</th></tr></thead><tbody>{jobs.map(j => <tr key={j.job_id}><td><button className="button small" onClick={() => setSelected(j.job_id)}>{j.job_id}</button></td><td>{j.kind}</td><td>{statuses[j.status]}</td><td>{j.client_id}</td><td><button className="button small" disabled={j.status === "cancelling"} onClick={() => action(j, terminalJob(j.status))}>{terminalJob(j.status) ? "删除任务记录" : "取消"}</button></td></tr>)}</tbody></table></div>
    {!compact && <><button className="button small" disabled={!cursor} onClick={() => setCursor(undefined)}>第一页</button><button className="button small" disabled={!next} onClick={() => setCursor(next || undefined)}>下一页</button></>}
    {selected && <JobDetail key={selected} jobId={selected} />}
  </section>;
}
