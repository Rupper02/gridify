"""Run 13: gam.gam_forecasts with extra smooth terms (README section 14.1, item D). gam.py stays frozen; with no extra
terms this reproduces it (checked in ladder.py before anything is scored).

Each extra term is one cubic regression spline of a daily series (same knot rule as the temperature terms), trained on
the ERA5 version and forecast from the IFS run of D-1.
"""
import numpy as np
import pandas as pd

from decomposition import MORNING_SLOTS, ar_forecast, calendar_design, fit_ar
from gam import spline_basis


def gam_forecasts_extra(days: pd.DataFrame, holidays: set, actual_slot: pd.DataFrame, actual_day: pd.Series,
                        forecast_slot: pd.DataFrame, forecast_day: pd.Series, start: str, end: str,
                        extra_actual: list = (), extra_forecast: list = ()) -> tuple[pd.Series, pd.DataFrame]:
    """Forecast for every (date, slot) of the period, indexed like history_features, and every fit's rank"""
    calendar = calendar_design(days.index, holidays)
    actual_day = actual_day.reindex(days.index).to_numpy()
    forecast_day = forecast_day.reindex(days.index).to_numpy()
    extra_a = [e.reindex(days.index).to_numpy() for e in extra_actual]
    extra_f = [e.reindex(days.index).to_numpy() for e in extra_forecast]
    targets = days.index[(days.index >= start) & (days.index <= end)]
    issue = targets - pd.Timedelta(days=1)
    refit = issue - pd.to_timedelta(issue.dayofweek, unit="D")
    out, ranks = {}, []
    for monday in refit.unique():
        week = targets[refit == monday]
        train = days.index < monday
        for slot in range(48):
            y = days[slot].to_numpy()
            slot_actual = actual_slot[slot].reindex(days.index).to_numpy()
            slot_forecast = forecast_slot[slot].reindex(days.index).to_numpy()
            fit_rows = train & ~np.isnan(y) & ~np.isnan(actual_day) & ~np.isnan(slot_actual)
            for e in extra_a:
                fit_rows &= ~np.isnan(e)

            def design(day_temp, slot_temp, extras):
                columns = [calendar, spline_basis(day_temp, actual_day[fit_rows]),
                           spline_basis(slot_temp, slot_actual[fit_rows])]
                columns += [spline_basis(x, train_x[fit_rows]) for x, train_x in zip(extras, extra_a)]
                return np.column_stack(columns)

            x_actual = design(actual_day, slot_actual, extra_a)
            beta, _, rank, _ = np.linalg.lstsq(x_actual[fit_rows], y[fit_rows], rcond=None)
            ranks.append({"refit_monday": monday, "slot": slot, "rank": rank, "columns": x_actual.shape[1],
                          "rows": int(fit_rows.sum())})
            resid = y - x_actual @ beta
            phi = fit_ar(np.where(train, resid, np.nan))
            x_forecast = design(forecast_day, slot_forecast, extra_f)
            for day in week:
                position = days.index.get_loc(day)
                if np.isnan(x_forecast[position]).any():
                    continue
                last_known = position - (1 if slot < MORNING_SLOTS else 2)
                r = ar_forecast(resid[:last_known + 1], phi, position - last_known)
                out[(day, slot)] = x_forecast[position] @ beta + r
    return pd.Series(out).rename_axis(["date", "slot"]), pd.DataFrame(ranks)
