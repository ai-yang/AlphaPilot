import React, { useEffect, useState } from "react";
import { getResearchToken, research, setResearchToken } from "./researchClient";

export function useResearchConnection() {
  const [connected, setConnected] = useState(Boolean(getResearchToken()));
  useEffect(() => {
    const update = () => setConnected(Boolean(getResearchToken()));
    window.addEventListener("research-connection", update);
    return () => window.removeEventListener("research-connection", update);
  }, []);
  return connected;
}
export function ResearchConnection() {
  const connected = useResearchConnection();
  const [value, setValue] = useState(""); const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  return <form className="row-actions" onSubmit={async e => {
    e.preventDefault(); setBusy(true); setError(""); setResearchToken(value);
    try {
      const info = await research.get<{ api_version: string }>("/capabilities");
      if (info.api_version.split(".")[0] !== "1") throw new Error("研究 API 主版本不兼容");
      setValue("");
    } catch (e) { setResearchToken(""); setError(String(e)); } finally { setBusy(false); }
  }}>
    {connected ? <button type="button" className="button small" onClick={() => setResearchToken("")}>断开研究服务</button> : <>
      <input aria-label="研究服务 Token" placeholder="研究服务 Token" type="password" autoComplete="off" value={value} onChange={e => setValue(e.target.value)} />
      <button className="button small" disabled={!value.trim() || busy}>连接研究服务</button>
    </>}
    {error && <span role="alert">{error}</span>}
  </form>;
}
export function ResearchGate({ children }: { children: React.ReactNode }) {
  return useResearchConnection() ? <>{children}</> : <section className="panel"><h2>连接研究服务</h2><p>在上方输入此客户端的研究服务 Token。凭据仅保存在当前页面内存中，刷新后需要重新连接。</p><p>本机管理员可使用 <code>alphapilot research_token create --client_id gui --scopes research:read,research:write,jobs:submit,jobs:cancel,data:write,signals:write,schedules:write</code> 创建凭据。</p></section>;
}
