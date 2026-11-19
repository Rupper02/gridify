"""Experiment tracking with MLflow, stored locally in data/ (nothing leaves the machine).

One parent run per train.py execution; one child run per model. Open the dashboard from the forecast/ folder (the
path is relative: started anywhere else, MLflow creates a new empty database there):
    uv run mlflow ui --backend-store-uri sqlite:///data/mlflow.db
"""
import os
import time
from pathlib import Path

# MLflow sends anonymous usage telemetry to its developers by default; keep everything on this machine
os.environ["MLFLOW_DISABLE_TELEMETRY"] = "true"
os.environ["DO_NOT_TRACK"] = "true"
os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"

import mlflow  # noqa: E402
import pandas as pd
from mlflow import MlflowClient
from mlflow.entities import Metric, Param

TRACKING_URI = "sqlite:///data/mlflow.db"
ARTIFACTS = Path("data/mlartifacts")
EXPERIMENT = "newmarket-development"


def start(description: str, experiment: str = EXPERIMENT) -> tuple[MlflowClient, str]:
    """The client and the parent run of this execution, in `experiment` (one per scoring period)"""
    mlflow.set_tracking_uri(TRACKING_URI)
    client = MlflowClient()
    found = client.get_experiment_by_name(experiment)
    experiment_id = found.experiment_id if found else client.create_experiment(
        experiment, artifact_location=(ARTIFACTS / experiment).resolve().as_uri())
    parent = client.create_run(experiment_id, run_name=f"{experiment} replay {time.strftime('%Y-%m-%d %H:%M')}",
                               tags={"mlflow.note.content": description})
    return client, parent.info.run_id


def child(client: MlflowClient, parent: str, name: str, params: dict) -> str:
    run = client.create_run(client.get_run(parent).info.experiment_id, run_name=name,
                            tags={"mlflow.parentRunId": parent})
    client.log_batch(run.info.run_id, params=[Param(k, str(v)[:6000]) for k, v in params.items()])
    return run.info.run_id


def log_refit(client: MlflowClient, run_id: str, step: int, monday: pd.Timestamp, curve: list, importance: dict,
              last: bool) -> None:
    """One weekly refit: its final training loss, each input's share of the gain, and the full curve for the last refit"""
    now = int(time.time() * 1000)
    metrics = [Metric("train_loss_final", curve[-1], now, step),
               Metric("refit_monday_ordinal", monday.toordinal(), now, step)]
    total = sum(importance.values()) or 1.0
    metrics += [Metric(f"importance/{name}", gain / total, now, step) for name, gain in importance.items()]
    if last:
        metrics += [Metric("train_loss_by_tree_last_refit", loss, now, tree) for tree, loss in enumerate(curve)]
    for i in range(0, len(metrics), 1000):
        client.log_batch(run_id, metrics=metrics[i:i + 1000])


def log_scores(client: MlflowClient, run_id: str, scores: dict, weekly: pd.Series) -> None:
    """Final scores and the out-of-sample MAE of each forecast week (step = week number)"""
    now = int(time.time() * 1000)
    metrics = [Metric(k, float(v), now, 0) for k, v in scores.items()]
    metrics += [Metric("weekly_MAE", float(v), now, step) for step, v in enumerate(weekly)]
    client.log_batch(run_id, metrics=metrics)
    client.set_terminated(run_id)
