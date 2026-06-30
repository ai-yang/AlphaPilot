import pickle
from pathlib import Path

import pandas as pd
import qlib
from mlflow.entities import ViewType
from mlflow.tracking import MlflowClient

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
    metrics.to_csv(output_path)

    print(f"Output has been saved to {output_path}")

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
                else:
                    with out_path.open("wb") as f:
                        pickle.dump(obj, f)
                print(f"Saved {filename}")
            except Exception as exc:
                print(f"Warning: could not export {recorder_key}: {exc}")
            break  # this artifact's tag resolved; stop probing
