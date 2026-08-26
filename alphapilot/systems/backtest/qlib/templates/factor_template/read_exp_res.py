import math
import pickle
from pathlib import Path

import pandas as pd
import qlib


def _average_daily_turnover(report):
    """Aggregate Qlib step turnover to daily totals before averaging."""
    if not isinstance(report, pd.DataFrame) or report.empty:
        raise ValueError("portfolio report must be a non-empty DataFrame")
    if "turnover" not in report.columns:
        raise ValueError("portfolio report is missing the turnover column")
    if isinstance(report.index, pd.MultiIndex):
        if "datetime" not in report.index.names:
            raise ValueError("portfolio report MultiIndex has no datetime level")
        raw_datetimes = report.index.get_level_values("datetime")
    else:
        raw_datetimes = report.index
    datetimes = pd.DatetimeIndex(pd.to_datetime(raw_datetimes, errors="coerce"))
    turnover = pd.to_numeric(report["turnover"], errors="coerce")
    if datetimes.isna().any():
        raise ValueError("portfolio report index contains invalid datetimes")
    if turnover.isna().any() or not bool(turnover.map(math.isfinite).all()):
        raise ValueError("portfolio report turnover contains non-finite values")
    if bool((turnover < 0).any()):
        raise ValueError("portfolio report turnover contains negative values")
    bars = pd.Series(
        turnover.to_numpy(dtype=float, copy=False),
        index=datetimes.normalize(),
        dtype=float,
    )
    daily = bars.groupby(level=0, sort=True).sum(min_count=1)
    return float(daily.mean())

qlib.init()

from qlib.workflow import R

# here is the documents of the https://qlib.readthedocs.io/en/latest/component/recorder.html

# TODO: list all the recorder and metrics

# Assuming you have already listed the experiments
experiments = R.list_experiments()

# Iterate through each experiment to find the latest recorder
experiment_name = None
latest_recorder = None
for experiment in experiments:
    recorders = R.list_recorders(experiment_name=experiment)
    for recorder_id in recorders:
        if recorder_id is not None:
            experiment_name = experiment
            recorder = R.get_recorder(recorder_id=recorder_id, experiment_name=experiment)
            end_time = recorder.info["end_time"]
            if latest_recorder is None or end_time > latest_recorder.info["end_time"]:
                latest_recorder = recorder

# Check if the latest recorder is found
if latest_recorder is None:
    print("No recorders found")
else:
    print(f"Latest recorder: {latest_recorder}")

    # Load the specified file from the latest recorder
    metrics = pd.Series(latest_recorder.list_metrics())

    output_path = Path(__file__).resolve().parent / "qlib_res.csv"

    # PortAnaRecord names artifacts by the rebalance-freq tag (daily="1day",
    # intraday="5min"/"15min"/...). Probe candidates and export whichever the run
    # actually produced, preserving the tag in the positions/indicators filenames.
    rebalance_tags = ["1day", "5min", "15min", "30min", "60min"]
    portfolio_specs = [
        ("report_normal_{tag}.pkl", "ret.pkl"),
        ("positions_normal_{tag}.pkl", "positions_normal_{tag}.pkl"),
        ("indicators_normal_{tag}.pkl", "indicators_normal_{tag}.pkl"),
    ]
    for key_tpl, name_tpl in portfolio_specs:
        for tag in rebalance_tags:
            recorder_key = "portfolio_analysis/" + key_tpl.format(tag=tag)
            try:
                obj = latest_recorder.load_object(recorder_key)
            except Exception:
                continue
            filename = name_tpl.format(tag=tag)
            out_path = Path(__file__).resolve().parent / filename
            try:
                if filename == "ret.pkl":
                    obj.to_pickle(out_path)
                    if isinstance(obj, pd.DataFrame) and "turnover" in obj.columns:
                        metrics.loc["average_daily_turnover"] = _average_daily_turnover(obj)
                else:
                    with out_path.open("wb") as f:
                        pickle.dump(obj, f)
                print(f"Saved {filename}")
            except Exception as exc:
                print(f"Warning: could not export {recorder_key}: {exc}")
            break  # this artifact's tag resolved; stop probing

    metrics.to_csv(output_path)
    print(f"Output has been saved to {output_path}")
