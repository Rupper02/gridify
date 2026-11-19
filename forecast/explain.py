"""SHAP contributions (SHapley Additive exPlanations) for the working model with forecast temperature, every refit.

The working model W is 4a L1 without d364 (lab notebook). Each refit's model is trained by train.train_one, the same
function the replay uses, so SHAP explains the model that was scored; it explains the week it forecast, from IFS inputs.
LightGBM gives exact per-row contributions natively (predict(..., pred_contrib=True)): one value per input plus the
base value, summing to the forecast. Writes data/runs/shap_working.csv and two plots in data/plots/.
"""
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

from load import NEWMARKET_FILE, load_demand
from train import (FEATURES, HOLIDAYS_FILE, LADDER, LGBM_PARAMS, OUT_DIR, WEATHER, calendar_features, era5_temps,
                   half_hours, history_features, ifs_temps, load_holidays, refit_mondays, train_one, weather_features)

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

PLOTS = Path("data/plots")
PARAMS = {**LGBM_PARAMS, "objective": "regression_l1"}
INPUTS = [f for f in FEATURES + LADDER["4a"] if f != "d364"] + WEATHER

if __name__ == "__main__":
    rows = half_hours(load_demand(NEWMARKET_FILE))
    table = rows.join(history_features(rows), on=["date", "slot"]).join(calendar_features(rows, load_holidays(HOLIDAYS_FILE)))
    actual = table.join(weather_features(rows, era5_temps(rows)))
    forecast = table.join(weather_features(rows, ifs_temps(rows)))

    refit = refit_mondays(forecast)
    zero = pd.Series(0.0, index=actual.index)
    per_refit = {}
    for monday, week in forecast.loc[refit.index].groupby(refit):
        week = week[week["temp"].notna()]
        model, _ = train_one(actual, INPUTS, monday, zero, PARAMS)
        if model is None or week.empty:
            continue
        contrib = pd.DataFrame(model.predict(week[INPUTS], pred_contrib=True), index=week.index, columns=INPUTS + ["base"])
        per_refit[monday] = contrib[INPUTS].abs().mean()

    shap = pd.DataFrame(per_refit).T.rename_axis("refit_monday")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    shap.to_csv(OUT_DIR / "shap_working.csv")
    first, last = shap.index[0], shap.index[-1]
    print(shap.loc[[first, last]].T.sort_values(last, ascending=False).round(3))

    PLOTS.mkdir(parents=True, exist_ok=True)
    order = shap.loc[last].sort_values().index
    fig, ax = plt.subplots(figsize=(8, 6))
    y = np.arange(len(order))
    ax.barh(y - 0.2, shap.loc[first, order], 0.4, label=f"first refit ({first:%d %b %Y})")
    ax.barh(y + 0.2, shap.loc[last, order], 0.4, label=f"last refit ({last:%d %b %Y})")
    ax.set_yticks(y, order)
    ax.set_xlabel("mean |contribution| to the forecast (MW)")
    ax.set_title("Working model with forecast temperature: what moves each forecast")
    ax.legend()
    fig.tight_layout()
    fig.savefig(PLOTS / "6_shap_first_last_refit.png", dpi=150)

    fig, ax = plt.subplots(figsize=(9, 5))
    for name in ["temp", "temp_day_mean", "hdd", "doy_sin", "doy_cos", "d1_morning", "d1_same", "d2"]:
        ax.plot(shap.index, shap[name], label=name)
    ax.set_ylabel("mean |contribution| (MW)")
    ax.set_title("Working model: contribution of selected inputs, refit by refit (development period)")
    ax.legend(ncol=2)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(PLOTS / "7_shap_by_refit.png", dpi=150)
    print(f"plots: {PLOTS / '6_shap_first_last_refit.png'}, {PLOTS / '7_shap_by_refit.png'}")
