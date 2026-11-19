"""Run 1a: the three-layer decomposition of Iftikhar et al. (2023), one model per half-hour slot, no weather.

Layers 1 and 2 (long run and regular pattern) are one least-squares fit per slot: a linear trend, the yearly cycle (two
sine/cosine pairs), day of week, bank holiday and the Christmas period. Layer 3 forecasts what is left with an AR(7) on
the same slot's daily residuals. Readings end at 09:00 on D-1, so slots 0-17 are one day ahead and slots 18-47 two.
Refit every Monday at the issue time on the days before it, like the LightGBM runs.
"""
import numpy as np
import pandas as pd

AR_LAGS = 7
MORNING_SLOTS = 18


def calendar_design(dates: pd.DatetimeIndex, holidays: set) -> np.ndarray:
    years = (dates - pd.Timestamp("2023-01-01")).days.to_numpy() / 365.25
    angle = 2 * np.pi * dates.dayofyear.to_numpy() / 365.25
    dow = np.eye(7)[dates.dayofweek.to_numpy()][:, 1:]
    christmas = ((dates.month == 12) & (dates.day >= 24)) | ((dates.month == 1) & (dates.day <= 2))
    return np.column_stack([
        np.ones(len(dates)), years,
        np.sin(angle), np.cos(angle), np.sin(2 * angle), np.cos(2 * angle),
        dow, dates.isin(holidays).astype(float), christmas.astype(float),
    ])


def fit_ar(resid: np.ndarray) -> np.ndarray:
    """AR coefficients from every day whose own value and seven lags are all metered (gaps are skipped, not filled)"""
    lags = np.column_stack([resid[AR_LAGS - k:len(resid) - k] for k in range(1, AR_LAGS + 1)])
    target = resid[AR_LAGS:]
    ok = ~np.isnan(target) & ~np.isnan(lags).any(axis=1)
    return np.linalg.lstsq(lags[ok], target[ok], rcond=None)[0]


def ar_forecast(known: np.ndarray, phi: np.ndarray, steps: int) -> float:
    """Step the AR forward from the last known residuals; an unmetered lag counts as 0, the pattern's own expectation"""
    history = list(np.nan_to_num(known[-AR_LAGS:]))
    for _ in range(steps):
        history.append(float(np.dot(phi, history[::-1][:AR_LAGS])))
    return history[-1]


def fitted_normal(days: pd.DataFrame, holidays: set, monday: pd.Timestamp) -> pd.Series:
    """Layers 1 and 2 as fitted on the days before `monday`, evaluated on every day: the expected level per (date, slot)"""
    design = calendar_design(days.index, holidays)
    train = days.index < monday
    normal = {}
    for slot in range(48):
        y = days[slot].to_numpy()
        ok = train & ~np.isnan(y)
        normal[slot] = design @ np.linalg.lstsq(design[ok], y[ok], rcond=None)[0]
    return pd.DataFrame(normal, index=days.index).stack().rename_axis(["date", "slot"])


def decomposition_forecasts(days: pd.DataFrame, holidays: set, start: str, end: str) -> pd.Series:
    """Forecast for every (date, slot) of the period, indexed like history_features"""
    design = calendar_design(days.index, holidays)
    targets = days.index[(days.index >= start) & (days.index <= end)]
    issue = targets - pd.Timedelta(days=1)
    refit = issue - pd.to_timedelta(issue.dayofweek, unit="D")
    out = {}
    for monday in refit.unique():
        week = targets[refit == monday]
        train = days.index < monday
        for slot in range(48):
            y = days[slot].to_numpy()
            ok = train & ~np.isnan(y)
            beta = np.linalg.lstsq(design[ok], y[ok], rcond=None)[0]
            resid = y - design @ beta
            phi = fit_ar(np.where(train, resid, np.nan))
            for day in week:
                position = days.index.get_loc(day)
                # Last day whose reading for this slot is in by 09:00 on D-1
                last_known = position - (1 if slot < MORNING_SLOTS else 2)
                steps = position - last_known
                r = ar_forecast(resid[:last_known + 1], phi, steps)
                out[(day, slot)] = design[position] @ beta + r
    return pd.Series(out).rename_axis(["date", "slot"])
