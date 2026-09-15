import React, { useEffect, useState } from "react";
import type { Run, Series } from "./research.generated";
import { research } from "./researchClient";
import { LazyPlot } from "./components/LazyPlot";
import { ResearchTable } from "./ResearchJobs";

function numericMetrics(value: unknown, prefix = "", output: Record<string, number> = {}) {
  if (typeof value === "number" && Number.isFinite(value)) output[prefix] = value;
  else if (Array.isArray(value)) value.forEach((entry, i) => {
    const label = entry?.factor_name ?? entry?.index ?? i;
    numericMetrics(entry, prefix ? `${prefix}.${label}` : String(label), output);
  });
  else if (value && typeof value === "object") Object.entries(value).forEach(([key, child]) => numericMetrics(child, prefix ? `${prefix}.${key}` : key, output));
  return output;
}

type Comparison = { run: Run; metrics: Record<string, number>; curve?: Series };
export function ResearchCompare({ runs }: { runs: Run[] }) {
  const [rows, setRows] = useState<Comparison[]>([]);
  const [metric, setMetric] = useState(""); const [ascending, setAscending] = useState(false);
  const [curve, setCurve] = useState("策略(含成本)"); const [error, setError] = useState("");
  const signature = runs.map(r => r.run_id).join(",");
  useEffect(() => {
    let active = true; setRows([]); setError("");
    void Promise.all(runs.map(async run => {
      const artifacts = run.artifacts.filter(a => ["evaluation", "backtest_summary"].includes(a.kind));
      const metrics: Record<string, number> = {};
      for (const artifact of artifacts) {
        const data = JSON.parse(await research.text(artifact));
        numericMetrics(data.metrics, "metrics", metrics);
        numericMetrics(data.summary, "summary", metrics);
      }
      const cumulative = run.artifacts.find(a => a.kind === "cumulative");
      const curve = cumulative ? await research.get<Series>(`/artifacts/${cumulative.artifact_id}/series`) : undefined;
      return { run, metrics, curve };
    })).then(data => { if (active) setRows(data); }).catch(e => { if (active) setError(String(e)); });
    return () => { active = false; };
  }, [signature]);
  const metrics = [...new Set(rows.flatMap(row => Object.keys(row.metrics)))].sort();
  const curves = [...new Set(rows.flatMap(row => Object.keys(row.curve?.rows[0] || {}).filter(key => key !== "date")))];
  const selectedMetric = metrics.includes(metric) ? metric : metrics[0];
  const selectedCurve = curves.includes(curve) ? curve : curves[0];
  const ranked = [...rows].sort((a, b) => {
    const left = a.metrics[selectedMetric]; const right = b.metrics[selectedMetric];
    if (left == null) return right == null ? 0 : 1;
    if (right == null) return -1;
    return (left - right) * (ascending ? 1 : -1);
  });
  return <section><h3>运行比较与指标排序</h3><p>比较已选择的运行；请结合各运行的数据集、日期区间和执行参数判断结果。指标取自完整数据，曲线可能降采样。</p>
    {error && <p role="alert">{error}</p>}
    <label>排序指标<select value={selectedMetric || ""} onChange={e => setMetric(e.target.value)}>{metrics.map(key => <option key={key}>{key}</option>)}</select></label>
    <label><input type="checkbox" checked={ascending} onChange={e => setAscending(e.target.checked)} />按指标升序</label>
    <ResearchTable rows={ranked.map(row => ({ run_id: row.run.run_id, status: row.run.metadata.status, ...row.metrics }))} />
    {!!curves.length && <><label>比较曲线<select value={selectedCurve} onChange={e => setCurve(e.target.value)}>{curves.map(key => <option key={key}>{key}</option>)}</select></label>
      <LazyPlot data={rows.filter(row => row.curve).map(row => ({ x: row.curve!.rows.map(point => point.date), y: row.curve!.rows.map(point => point[selectedCurve]), name: `${row.run.run_id}${row.curve!.downsampled ? "（降采样）" : ""}`, type: "scatter", mode: "lines" }))} layout={{ autosize: true, height: 360, margin: { t: 30, l: 60, r: 30, b: 50 } }} config={{ responsive: true }} style={{ width: "100%" }} /></>}
  </section>;
}
