"""Run 16: carry-over of the development candidate to Bungay and the 15 development sites, development period only
(README section 14.1, item H; specification written before running). Nothing is chosen per site: every site gets
exactly Newmarket's recipe. No 2025 data is read for any site (demand and weather are cut at 1 January 2025 UTC, the
end of 31 December 2024 local).

    uv run python carryover.py fetch-bungay        Bungay's extra weather: ERA5 to 2024-12-31, IFS runs of 2024 only
    uv run python carryover.py check               the generic code on Newmarket must reproduce the saved columns
    uv run python carryover.py cheap [KEY ...]     every model except Timestral, per site with complete weather
    uv run python carryover.py timestral KEY       Timestral-123M with forecast temperature for one site
    uv run python carryover.py report              per-site and pooled tables
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from chronos_run import chronos_forecasts
from decomposition import decomposition_forecasts
from fetch_weather import WEATHER_DIR, era5_file, get_json, runs_dir
from fetch_weather_extra import VARIABLES, era5_extra_file, fetch_runs, frame as payload_frame, runs_extra_dir
from gam import gam_forecasts
from gam_extra import gam_forecasts_extra
from ladder import BANDS, RUNGS, to_half
from load import SITES
from sites import dev_sites, load_site_demand
from timestral_run import REVISIONS, day_part
from train import (DEV_END, DEV_START, FEATURES, HOLIDAYS_FILE, LADDER, LGBM_PARAMS, WEATHER, calendar_features,
                   day_slot_matrix, diebold_mariano, half_hours, history_features, load_holidays, replay, slot_matrix,
                   to_half_hours, weather_features)

CUT = pd.Timestamp("2025-01-01", tz="UTC")
OUT_DIR = Path("data/runs/carryover")
FETCH_CONSOLES = [Path("data/runs/dev_sites_weather_fetch.txt"), Path("data/runs/bungay_weather_fetch.txt")]
N_RUNS = 293            # the 00 UTC runs of 14 March - 31 December 2024
TIMESTRAL_SIZE = "123M"
TOLERANCE = 1e-9
# Chronos-2 returns 32-bit floats: the check differed by 2^-21 (one float32 step); amended after the check, README 14.1 H
CHRONOS_TOLERANCE = 1e-5
W_NW, W = "f4a_l1_no364_nw", "f4a_l1_no364"
NO_WEATHER = ["f0a", "f0b", "f1a", W_NW, "f9_nw"]           # as report.py
CHEAP = NO_WEATHER + [W, "f7", "f9", "W_13f", "GAM_13f", "run9_13g", "f11"]
WITH_TIMESTRAL = ["f12", "f15a", "f15b"]
NAMES = {"f0a": "0a last week", "f0b": "0b 4-week mean", "f1a": "1a decomposition", W_NW: "W no weather",
         "f9_nw": "9 no weather", W: "W", "f7": "GAM", "f9": "run 9", "W_13f": "W + 5 inputs",
         "GAM_13f": "GAM + radiation", "run9_13g": "13g", "f11": "Chronos-2", "f12": "Timestral",
         "f15a": "15a", "f15b": "15b"}
DM_PAIRS = [("f9", "run9_13g"), ("run9_13g", "f15a"), ("f9", "f15a"), ("f11", "f12"), ("f9", "f12")]


def site_list() -> list:
    """Bungay first, then the development sites in draw order: (key, demand file, transformers)"""
    dev = dev_sites()
    return [("bungay", SITES["bungay"]["file"], 2)] + list(zip(dev["key"], dev["file"], dev["transformers"]))


def demand_of(key: str, path: Path, transformers: int) -> pd.Series:
    demand = load_site_demand(path, transformers)
    return demand[demand.index.tz_convert("UTC") < CUT]


def read(path: Path, rename: dict | None = None, cut: bool = False) -> pd.DataFrame:
    """An hourly file; with `cut`, nothing after 00:00 UTC on 1 January 2025 (the end instant of 31 December 2024,
    needed to interpolate its last half-hour and as the stamp of its last preceding-hour mean)"""
    frame = pd.read_csv(path, parse_dates=["time_utc"]).set_index("time_utc").rename(columns=rename or {})
    return frame[frame.index <= CUT] if cut else frame


def site_weather(key: str):
    """ERA5 hourly ('temp' + VARIABLES) and a function giving the IFS 00 UTC run of a day (None if missing)"""
    if key in SITES:
        # Newmarket and Bungay: temperature and the extra variables in separate files
        era5 = read(era5_file(key), {"temperature_c": "temp"}, cut=True).join(
            read(era5_extra_file(key), cut=True)[VARIABLES], how="outer")

        def run(day):
            temp, extra = runs_dir(key) / f"{day:%Y-%m-%d}.csv", runs_extra_dir(key) / f"{day:%Y-%m-%d}.csv"
            if not temp.exists() or day > pd.Timestamp(DEV_END):
                return None
            hourly = read(temp, {"temperature_c": "temp"})
            if extra.exists():
                return hourly.join(read(extra)[VARIABLES], how="outer")
            return hourly.assign(**{v: np.nan for v in VARIABLES})
    else:
        era5 = read(WEATHER_DIR / f"{key}_era5_all_hourly.csv", {"temperature_2m": "temp"}, cut=True)

        def run(day):
            path = WEATHER_DIR / f"{key}_ifs_00z_all_runs" / f"{day:%Y-%m-%d}.csv"
            if not path.exists() or day > pd.Timestamp(DEV_END):
                return None
            return read(path, {"temperature_2m": "temp"})
    return era5, run


def weather_ready(key: str) -> bool:
    folder = runs_extra_dir(key) if key in SITES else WEATHER_DIR / f"{key}_ifs_00z_all_runs"
    if folder.exists() and len(list(folder.glob("*.csv"))) >= N_RUNS:
        return True
    return any(f"{key}: IFS runs done" in c.read_text(errors="ignore") for c in FETCH_CONSOLES if c.exists())


def half_hour_weather(rows: pd.DataFrame, era5: pd.DataFrame, run) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Temperature and the five rung variables at each half-hour: ERA5 (actual) and the IFS run of D-1 (forecast)"""
    utc = rows.index.tz_convert("UTC")
    specs = {"temp": False, **{v: preceding for v, preceding in RUNGS.values()}}
    actual = pd.DataFrame({v: to_half(era5[v], utc, p).to_numpy() for v, p in specs.items()}, index=rows.index)
    forecast = pd.DataFrame(np.nan, index=rows.index, columns=list(specs))
    for day in rows["date"].unique():
        hourly = run(pd.Timestamp(day) - pd.Timedelta(days=1))
        if hourly is None:
            continue
        on_day = rows.index[rows["date"] == day]
        for v, p in specs.items():
            forecast.loc[on_day, v] = to_half(hourly[v], on_day.tz_convert("UTC"), p).to_numpy()
    return actual, forecast


def cheap_models(demand: pd.Series, era5: pd.DataFrame, run) -> pd.DataFrame:
    """Every model of the recipe except Timestral, on every development half-hour (NaN where a model has none)"""
    rows = half_hours(demand)
    holidays = load_holidays(HOLIDAYS_FILE)
    table = rows.join(history_features(rows), on=["date", "slot"]).join(calendar_features(rows, holidays))
    actual_w, forecast_w = half_hour_weather(rows, era5, run)
    actual = table.join(weather_features(rows, actual_w["temp"]))
    forecast = table.join(weather_features(rows, forecast_w["temp"]))
    added = []
    for v, _ in RUNGS.values():
        for t, w in ((actual, actual_w), (forecast, forecast_w)):
            t[v] = w[v]
            t[f"{v}_day_mean"] = w[v].groupby(rows["date"]).transform("mean")
        added += [v, f"{v}_day_mean"]
    days = day_slot_matrix(rows)
    era5_day, ifs_day = actual_w["temp"].groupby(rows["date"]).mean(), forecast_w["temp"].groupby(rows["date"]).mean()
    era5_slot, ifs_slot = slot_matrix(rows, actual_w["temp"]), slot_matrix(rows, forecast_w["temp"])

    def by_slot(series: pd.Series) -> pd.Series:
        return rows.join(series.rename("f"), on=["date", "slot"])["f"]

    out = pd.DataFrame({"mw": rows["mw"], "f0a": table["d7"], "f0b": table["d7_28_mean"]}, index=rows.index)
    out["f1a"] = by_slot(decomposition_forecasts(days, holidays, DEV_START, DEV_END))
    l1 = {**LGBM_PARAMS, "objective": "regression_l1"}
    w_inputs = [f for f in FEATURES + LADDER["4a"] if f != "d364"]
    out[W_NW] = replay(table, w_inputs, {"f": table}, params=l1)["f"]
    out[W] = replay(actual, w_inputs + WEATHER, {"f": forecast}, params=l1)["f"]
    out["W_13f"] = replay(actual, w_inputs + WEATHER + added, {"f": forecast}, params=l1)["f"]
    out["f7"] = by_slot(gam_forecasts(days, holidays, era5_slot, era5_day, ifs_slot, ifs_day, DEV_START, DEV_END)[0])
    radiation = RUNGS["13a"][0]
    gam_13f, ranks = gam_forecasts_extra(days, holidays, era5_slot, era5_day, ifs_slot, ifs_day, DEV_START, DEV_END,
                                         [actual_w[radiation].groupby(rows["date"]).mean()],
                                         [forecast_w[radiation].groupby(rows["date"]).mean()])
    out["GAM_13f"] = by_slot(gam_13f)
    out.attrs["gam_13f_rank_deficient"] = int((ranks["rank"] < ranks["columns"]).sum())

    def ifs_temp(run_day, instants):
        hourly = run(run_day)
        return None if hourly is None else to_half_hours(hourly["temp"], instants).to_numpy()

    chronos = chronos_forecasts(demand, actual_w["temp"], ifs_temp, DEV_START, DEV_END)
    out["f11"], out["f11_nw"] = chronos["f11"].reindex(out.index), chronos["f11_nw"].reindex(out.index)
    # As train.py: weather models only on days whose forecast run of D-1 exists; the 13f models also need the five
    no_run = forecast["temp_day_mean"].isna()
    out.loc[no_run, [W, "W_13f", "f7", "GAM_13f", "f11"]] = np.nan
    out.loc[forecast[[f"{v}_day_mean" for v, _ in RUNGS.values()]].isna().any(axis=1), ["W_13f", "GAM_13f"]] = np.nan
    out["f9_nw"] = 0.5 * out["f1a"] + 0.5 * out[W_NW]
    out["f9"] = 0.5 * out["f7"] + 0.5 * out[W]
    out["run9_13g"] = 0.5 * out["GAM_13f"] + 0.5 * out["W_13f"]
    return out[(rows["date"] >= DEV_START) & (rows["date"] <= DEV_END)]


def timestral_temp(demand: pd.Series, era5_temp: pd.Series, run, days) -> pd.Series:
    """Run 12's Timestral with forecast temperature (timestral_run.timestral_forecasts, its covariate branch only)"""
    import torch
    from timestral import TimestralForecaster

    torch.manual_seed(0)
    forecaster = TimestralForecaster.from_pretrained(f"mistralai/Timestral-{TIMESTRAL_SIZE}",
                                                     revision=REVISIONS[TIMESTRAL_SIZE])
    target, temp = demand.tz_convert("UTC"), era5_temp.tz_convert("UTC")
    parts = []
    for day in days:
        origin = pd.Timestamp(day - pd.Timedelta(days=1)).replace(hour=9).tz_localize("Europe/London").tz_convert("UTC")
        day_end = pd.Timestamp(day + pd.Timedelta(days=1)).tz_localize("Europe/London").tz_convert("UTC")
        horizon = pd.date_range(origin, day_end, freq="30min", inclusive="left")
        hourly = run(day - pd.Timedelta(days=1))
        if hourly is None:
            continue
        context = target[target.index < origin].iloc[-forecaster.max_context:]
        future = to_half_hours(hourly["temp"], horizon).to_numpy()
        known = np.concatenate([temp.reindex(context.index).to_numpy(), future]).astype(np.float32)[None, None]
        result = forecaster.forecast(context.to_numpy(dtype=np.float32), prediction_length=len(horizon),
                                     known_covariates=known)
        parts.append(day_part(result.median[0, 0].numpy(), horizon, day))
    return pd.concat(parts).sort_index()


def save(frame: pd.DataFrame, path: Path) -> None:
    out = frame.copy()
    out.index = out.index.tz_convert("UTC")
    out.to_csv(path)


def load_saved(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, index_col=0)
    frame.index = pd.to_datetime(frame.index, utc=True).tz_convert("Europe/London")
    frame["date"] = pd.DatetimeIndex(frame.index.date)
    return frame


def nmae(frame: pd.DataFrame, col: str) -> float:
    return (frame[col] - frame["mw"]).abs().sum() / frame["mw"].sum()


def check_newmarket() -> None:
    """The generic path on Newmarket against the saved development columns (frozen file, run 13, run 12)"""
    from load import NEWMARKET_FILE, load_demand
    demand = load_demand(NEWMARKET_FILE)
    demand = demand[demand.index.tz_convert("UTC") < CUT]
    era5, run = site_weather("newmarket")
    began = time.perf_counter()
    mine = cheap_models(demand, era5, run)
    print(f"Newmarket cheap models: {time.perf_counter() - began:.0f} s")
    frozen = load_saved(Path("data/runs/dev_runs_frozen.csv"))
    ladder = load_saved(Path("data/runs/dev_run13_ladder.csv"))
    failed = []
    for col, source, saved in [(c, frozen, c) for c in ["f0a", "f0b", "f1a", W_NW, "f9_nw", W, "f7", "f9", "f11_nw", "f11"]] + \
            [("W_13f", ladder, "W_13f"), ("GAM_13f", ladder, "GAM_13f"), ("run9_13g", ladder, "run9_13g")]:
        diff = np.abs(mine[col].reindex(source.index) - source[saved]).max()
        missing = int(mine[col].reindex(source.index).isna().sum())
        if missing or not diff < (CHRONOS_TOLERANCE if col in ("f11", "f11_nw") else TOLERANCE):
            failed.append(col)
        print(f"  {col:10s} largest difference {diff:.2e}, missing on the scored half-hours {missing}")
    # Scored set: every cheap model must exist exactly on the frozen file's half-hours (f11 and the 13f ones too)
    scored = mine.dropna(subset=["mw", *CHEAP]).index
    print(f"  scored half-hours from the generic path {len(scored)}, frozen file {len(frozen)}, "
          f"same set: {scored.equals(frozen.index)}")
    run12 = load_saved(Path("data/runs/dev_run12_timestral.csv"))
    picks = pd.date_range(DEV_START, DEV_END, freq="D")[[0, 146, 292]]
    t = timestral_temp(demand, era5_temp_series(demand, era5), run, picks)
    tdiff = np.abs(t.reindex(run12.index).dropna() - run12["f12"].reindex(t.index).dropna()).max()
    print(f"  Timestral on {len(picks)} days against run 12: largest difference {tdiff:.2e} ({len(t)} half-hours)")
    ok = not failed and scored.equals(frozen.index) and tdiff < 1e-4
    print("check passed" if ok else "CHECK FAILED: not running any site")
    if not ok:
        raise SystemExit(1)


def era5_temp_series(demand: pd.Series, era5: pd.DataFrame) -> pd.Series:
    rows = half_hours(demand)
    return to_half_hours(era5["temp"], rows.index.tz_convert("UTC")).set_axis(rows.index)


def report() -> None:
    per_site, pooled = [], {}
    for key, *_ in site_list():
        cheap_file, t_file = OUT_DIR / f"{key}_cheap.csv", OUT_DIR / f"{key}_timestral.csv"
        if not cheap_file.exists():
            print(f"{key}: no cheap-model file (weather incomplete or not run)")
            continue
        frame = load_saved(cheap_file)
        has_t = t_file.exists()
        if has_t:
            frame["f12"] = load_saved(t_file)["f12"].reindex(frame.index)
            frame["f15a"] = (frame["GAM_13f"] + frame["W_13f"] + frame["f12"]) / 3
            frame["f15b"] = 0.5 * frame["run9_13g"] + 0.5 * frame["f12"]
        models = CHEAP + (WITH_TIMESTRAL if has_t else [])
        scored = frame.dropna(subset=["mw", *models])
        dev_metered = frame["mw"].dropna()
        low = int((dev_metered < 0.1 * dev_metered.median()).sum())
        comp = min(NO_WEATHER, key=lambda c: nmae(scored, c))
        row = {"site": key, "half_hours": len(scored), "days": scored["date"].nunique(), "mean_mw": scored["mw"].mean(),
               "below_10pct_median": low, "comparator": NAMES[comp], "timestral": has_t,
               **{c: nmae(scored, c) for c in models}}
        for c in ("f9", "run9_13g") + (("f15a",) if has_t else ()):
            row[f"margin_{c}"] = 1 - nmae(scored, c) / nmae(scored, comp)
        for a, b in DM_PAIRS:
            if a in models and b in models:
                row[f"dm_{b}_vs_{a}"], row[f"p_{b}_vs_{a}"] = diebold_mariano(scored, a, b)
        per_site.append(row)
        pooled[key] = scored.assign(comp=scored[comp])
    table = pd.DataFrame(per_site).set_index("site")
    table.to_csv(OUT_DIR / "run16_per_site.csv")
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 50)
    show = [c for c in CHEAP + WITH_TIMESTRAL if c in table]
    print("NMAE per site (each on its own scored half-hours: metered and forecast by every model it has)")
    print((table[show] * 100).round(2).rename(columns=NAMES).to_string())
    print("\n" + table[["half_hours", "days", "mean_mw", "below_10pct_median", "comparator"]].round(2).to_string())
    margins = [c for c in table if c.startswith("margin_")]
    print("\nMargins over each site's comparator (best no-weather model)")
    print((table[margins] * 100).round(1).to_string())
    for a, b in DM_PAIRS:
        col = f"dm_{b}_vs_{a}"
        if col in table:
            sub = table[[col, f"p_{b}_vs_{a}"]].dropna()
            print(f"\n{NAMES[b]} vs {NAMES[a]} (positive = {NAMES[b]} better): positive at {int((sub[col] > 0).sum())} of "
                  f"{len(sub)} sites, significantly better (p < 0.05) at {int(((sub[col] > 0) & (sub.iloc[:, 1] < 0.05)).sum())}, "
                  f"significantly worse at {int(((sub[col] < 0) & (sub.iloc[:, 1] < 0.05)).sum())}")
            print("  " + "  ".join(f"{s} {d:+.2f} ({p:.2g})" for s, (d, p) in sub.iterrows()))

    def pooled_lines(keys: list, models: list, label: str) -> None:
        allrows = pd.concat([pooled[k] for k in keys])
        print(f"\nPooled over {len(keys)} sites ({label}): sum of absolute errors / sum of demand; plain mean of site NMAEs")
        for c in ["comp"] + models:
            plain = np.mean([nmae(pooled[k], c) for k in keys])
            print(f"  {NAMES.get(c, 'comparator (per site)'):22s} {nmae(allrows, c):7.3%}  {plain:7.3%}")
        months = allrows["date"].dt.to_period("M")
        print("  pooled NMAE by month: " + "; ".join(
            f"{m.strftime('%b')} " + " ".join(f"{NAMES.get(c, 'comp')} {nmae(part, c):.2%}" for c in ["comp"] + models)
            for m, part in allrows.groupby(months)))

    pooled_lines(list(table.index), CHEAP, "every site with the cheap models")
    with_t = list(table.index[table["timestral"]])
    if with_t:
        pooled_lines(with_t, CHEAP + WITH_TIMESTRAL, "the sites with Timestral, on their Timestral scored sets")


def fetch_bungay() -> None:
    out = era5_extra_file("bungay")
    if not out.exists():
        payload = get_json("https://archive-api.open-meteo.com/v1/archive", {
            "latitude": SITES["bungay"]["lat"], "longitude": SITES["bungay"]["lon"], "start_date": "2022-12-01",
            "end_date": "2024-12-31", "hourly": ",".join(VARIABLES), "models": "era5", "timezone": "GMT",
            "wind_speed_unit": "ms"})
        payload_frame(payload, VARIABLES).to_csv(out, index=False)
        print(f"ERA5 saved: {out}")
    fetch_runs("bungay", "2024-03-14", "2024-12-31")
    print("bungay: IFS runs done")


if __name__ == "__main__":
    command = sys.argv[1]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sites = {key: (path, n) for key, path, n in site_list()}
    if command == "fetch-bungay":
        fetch_bungay()
    elif command == "check":
        check_newmarket()
    elif command == "cheap":
        for key in sys.argv[2:] or list(sites):
            out = OUT_DIR / f"{key}_cheap.csv"
            if out.exists():
                continue
            if not weather_ready(key):
                print(f"{key}: IFS runs incomplete, skipped")
                continue
            began = time.perf_counter()
            era5, run = site_weather(key)
            frame = cheap_models(demand_of(key, *sites[key]), era5, run)
            save(frame, out)
            print(f"{key}: saved {out} in {time.perf_counter() - began:.0f} s "
                  f"(GAM + radiation rank-deficient fits {frame.attrs.get('gam_13f_rank_deficient')})", flush=True)
    elif command == "timestral":
        key = sys.argv[2]
        out = OUT_DIR / f"{key}_timestral.csv"
        demand = demand_of(key, *sites[key])
        era5, run = site_weather(key)
        began = time.perf_counter()
        f12 = timestral_temp(demand, era5_temp_series(demand, era5), run, pd.date_range(DEV_START, DEV_END, freq="D"))
        save(f12.rename("f12").to_frame(), out)
        print(f"{key}: Timestral-{TIMESTRAL_SIZE} saved {out} in {time.perf_counter() - began:.0f} s", flush=True)
    elif command == "report":
        report()
