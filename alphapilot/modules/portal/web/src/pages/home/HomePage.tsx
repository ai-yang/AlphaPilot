import { Link } from "react-router-dom";
import { Job } from "../../api";
import { research } from "../../researchClient";
import { Alert, InfoDot, JobsPanel, PageTitle } from "../../components";
import { useAsync } from "../../hooks";
import { useI18n } from "../../i18n";

type Status = {
  metrics: Record<string, string | number>;
  recent_jobs: Job[];
  recent_mining: string[];
  systems: string[];
  modules: Record<string, string[]>;
  config: Record<string, unknown>;
};

export function HomePage() {
  const { t } = useI18n();
  const state = useAsync(() => research.get<Status>("/status"), []);
  const metrics = state.data?.metrics || {};
  return (
    <>
      <PageTitle title="AlphaPilot" subtitle={t("homeSubtitle")} />
      {state.error ? <Alert tone="error">{state.error}</Alert> : null}
      <div className="metric-grid">
        {([
          [t("symbols"), metrics.symbols, t("tipSymbols")],
          [t("factors"), metrics.factors, t("tipFactors")],
          [t("strategies"), metrics.strategies, t("tipStrategies")],
          [t("backtests"), metrics.backtests, t("tipBacktests")]
        ] as Array<[string, string | number | undefined, string]>).map(([label, value, tip]) => (
          <div className="metric" key={label}>
            <span className="metric-label">{label}<InfoDot tip={tip} /></span>
            <strong>{state.loading && value === undefined ? "..." : String(value ?? "-")}</strong>
          </div>
        ))}
      </div>
      <div className="grid two">
        <section className="panel">
          <h2>{t("quickActions")}</h2>
          <div className="action-grid">
            <Link className="action" to="/mining">{t("actionMine")}</Link>
            <Link className="action" to="/market">{t("actionMarket")}</Link>
            <Link className="action" to="/backtest">{t("actionBacktest")}</Link>
            <Link className="action" to="/library">{t("actionLibrary")}</Link>
          </div>
        </section>
        <section className="panel">
          <h2>{t("recentMining")}</h2>
          {(state.data?.recent_mining || []).length ? (
            <ul className="plain-list">{state.data?.recent_mining.map((name) => <li key={name}>{name}</li>)}</ul>
          ) : (
            <div className="empty">{t("empty")}</div>
          )}
        </section>
      </div>
      <JobsPanel compact />
    </>
  );
}
