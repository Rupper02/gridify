"""Run 7: the GAM (Generalised Additive Model), 1a's structure with weather, one model per half-hour slot.

Per slot: least squares on 1a's layers 1 and 2 plus two cubic regression splines, of the daily mean temperature of D and
of the slot's own temperature (knots at the 20/40/60/80% quantiles of the training values; values outside the training
range clamped to its ends). Then 1a's AR(7) on the residuals. Unpenalised, so nothing to tune. Trained on ERA5; the
forecast takes D's temperatures from the IFS run of D-1 and the AR lags from ERA5-based residuals of past days.
"""
import numpy as np
import pandas as pd
from scipy.interpolate import BSpline

from decomposition import MORNING_SLOTS, ar_forecast, calendar_design, fit_ar

KNOT_QUANTILES = [0.2, 0.4, 0.6, 0.8]
DEGREE = 3


def spline_basis(x: np.ndarray, train_values: np.ndarray) -> np.ndarray:
    """Cubic B-spline basis on knots from the training values; the first column is dropped (the constant is in layer 1)"""
    lo, hi = np.nanmin(train_values), np.nanmax(train_values)
    interior = np.nanquantile(train_values, KNOT_QUANTILES)
    knots = np.r_[[lo] * (DEGREE + 1), interior, [hi] * (DEGREE + 1)]
    basis = np.full((len(x), len(interior) + DEGREE + 1), np.nan)
    ok = ~np.isnan(x)
    basis[ok] = BSpline.design_matrix(np.clip(x[ok], lo, hi), knots, DEGREE).toarray()
    return basis[:, 1:]


def gam_forecasts(days: pd.DataFrame, holidays: set, actual_slot: pd.DataFrame, actual_day: pd.Series,
                  forecast_slot: pd.DataFrame, forecast_day: pd.Series, start: str, end: str,
                  use_temperature: bool = True, keep_slots: tuple = (6, 24, 36)) -> tuple[pd.Series, pd.DataFrame, dict]:
    """Forecast for every (date, slot) of the period whose D-1 forecast run exists, indexed like history_features.

    Also returns the least-squares rank of every fit (to flag rank-deficient ones) and, for `keep_slots` at the first
    and last refit, what is needed to plot the fitted temperature curves. With use_temperature=False the model is 1a.
    """
    calendar = calendar_design(days.index, holidays)
    actual_day = actual_day.reindex(days.index).to_numpy()
    forecast_day = forecast_day.reindex(days.index).to_numpy()
    targets = days.index[(days.index >= start) & (days.index <= end)]
    issue = targets - pd.Timedelta(days=1)
    refit = issue - pd.to_timedelta(issue.dayofweek, unit="D")
    out, ranks, curves = {}, [], {}
    mondays = refit.unique()
    for monday in mondays:
        week = targets[refit == monday]
        train = days.index < monday
        for slot in range(48):
            y = days[slot].to_numpy()
            slot_actual = actual_slot[slot].reindex(days.index).to_numpy()
            slot_forecast = forecast_slot[slot].reindex(days.index).to_numpy()
            fit_rows = train & ~np.isnan(y) & ~np.isnan(actual_day) & ~np.isnan(slot_actual)

            def design(day_temp, slot_temp):
                if not use_temperature:
                    return calendar
                return np.column_stack([calendar, spline_basis(day_temp, actual_day[fit_rows]),
                                        spline_basis(slot_temp, slot_actual[fit_rows])])

            x_actual = design(actual_day, slot_actual)
            beta, _, rank, _ = np.linalg.lstsq(x_actual[fit_rows], y[fit_rows], rcond=None)
            ranks.append({"refit_monday": monday, "slot": slot, "rank": rank, "columns": x_actual.shape[1],
                          "rows": int(fit_rows.sum())})
            if use_temperature and slot in keep_slots and monday in (mondays[0], mondays[-1]):
                curves[(monday, slot)] = {"beta": beta, "n_calendar": calendar.shape[1],
                                          "day_train": actual_day[fit_rows], "slot_train": slot_actual[fit_rows]}
            resid = y - x_actual @ beta
            phi = fit_ar(np.where(train, resid, np.nan))
            x_forecast = design(forecast_day, slot_forecast)
            for day in week:
                position = days.index.get_loc(day)
                if np.isnan(x_forecast[position]).any():
                    continue
                last_known = position - (1 if slot < MORNING_SLOTS else 2)
                r = ar_forecast(resid[:last_known + 1], phi, position - last_known)
                out[(day, slot)] = x_forecast[position] @ beta + r
    return pd.Series(out).rename_axis(["date", "slot"]), pd.DataFrame(ranks), curves


def plot_curves(curves: dict, path) -> None:
    """Fitted temperature effects (each spline term alone, other inputs fixed) per kept slot, first and last refit"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    mondays = sorted({monday for monday, _ in curves})
    slots = sorted({slot for _, slot in curves})
    fig, axes = plt.subplots(2, len(slots), figsize=(4 * len(slots), 7), sharey="row")
    for col, slot in enumerate(slots):
        for monday in mondays:
            fit = curves[(monday, slot)]
            n_cal, beta = fit["n_calendar"], fit["beta"]
            n_basis = (len(beta) - n_cal) // 2
            for row, (name, train, part) in enumerate([
                    ("daily mean temperature of D", fit["day_train"], beta[n_cal:n_cal + n_basis]),
                    ("the slot's temperature", fit["slot_train"], beta[n_cal + n_basis:])]):
                grid = np.linspace(np.nanmin(train), np.nanmax(train), 200)
                effect = spline_basis(grid, train) @ part
                axes[row, col].plot(grid, effect - effect.mean(), label=f"refit {monday:%d %b %Y}")
                axes[row, col].set_xlabel(f"{name} (°C)")
        axes[0, col].set_title(f"slot {slot} ({slot // 2:02d}:{30 * (slot % 2):02d})")
    for row in range(2):
        axes[row, 0].set_ylabel("effect on demand (MW, centred)")
    axes[0, 0].legend()
    fig.suptitle("Run 7 GAM: the two temperature terms one by one; they partly cancel, so neither is the temperature "
                 "response on its own (see plot 9)")
    fig.tight_layout()
    fig.savefig(path, dpi=150)


def plot_combined(curves: dict, path, bins: int = 15) -> None:
    """Both temperature terms together along typical days: each bin of the slot's training temperature paired with the
    median daily mean temperature of the training days in that bin"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    mondays = sorted({monday for monday, _ in curves})
    slots = sorted({slot for _, slot in curves})
    fig, axes = plt.subplots(1, len(slots), figsize=(4 * len(slots), 4), sharey=True)
    for ax, slot in zip(np.atleast_1d(axes), slots):
        for monday in mondays:
            fit = curves[(monday, slot)]
            n_cal, beta = fit["n_calendar"], fit["beta"]
            n_basis = (len(beta) - n_cal) // 2
            day_train, slot_train = fit["day_train"], fit["slot_train"]
            edges = np.quantile(slot_train, np.linspace(0, 1, bins + 1))
            which = np.clip(np.searchsorted(edges, slot_train, side="right") - 1, 0, bins - 1)
            slot_t = np.array([np.median(slot_train[which == b]) for b in range(bins)])
            day_t = np.array([np.median(day_train[which == b]) for b in range(bins)])
            effect = (spline_basis(day_t, day_train) @ beta[n_cal:n_cal + n_basis]
                      + spline_basis(slot_t, slot_train) @ beta[n_cal + n_basis:])
            ax.plot(slot_t, effect - effect.mean(), marker="o", ms=3, label=f"refit {monday:%d %b %Y}")
        ax.set_title(f"slot {slot} ({slot // 2:02d}:{30 * (slot % 2):02d})")
        ax.set_xlabel("the slot's temperature, with its typical daily mean (°C)")
    np.atleast_1d(axes)[0].set_ylabel("combined temperature effect (MW, centred)")
    np.atleast_1d(axes)[0].legend()
    fig.suptitle("Run 7 GAM: combined temperature effect along typical days")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
