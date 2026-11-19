"""Forecast cache: a replay's forecasts are reused only when everything that determines them is unchanged.

The key covers the model spec (features, params, tree count, offset, weather sources, development dates), a fingerprint
of every input table column the replay reads, the source of replay(), decomposition.py and any offset function, the
LightGBM version, and train.CODE_VERSION as a manual override for anything else. Only
forecasts are cached; the scored set, metrics and DM tests are always recomputed. `train.py --no-cache` refits all.
"""
import hashlib
import json
import pickle
from pathlib import Path

import pandas as pd

CACHE_DIR = Path("data/cache/forecasts")


def fingerprint(frame: pd.DataFrame | pd.Series, columns: list | None = None) -> str:
    """Hash of the values and index of the given columns"""
    data = frame[columns] if columns is not None else frame
    return hashlib.sha256(pd.util.hash_pandas_object(data, index=True).to_numpy().tobytes()).hexdigest()


def file_fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def key(spec: dict) -> str:
    return hashlib.sha256(json.dumps(spec, sort_keys=True, default=str).encode()).hexdigest()[:24]


def load(cache_key: str) -> dict | None:
    path = CACHE_DIR / f"{cache_key}.pkl"
    if not path.exists():
        return None
    with path.open("rb") as f:
        return pickle.load(f)


def save(cache_key: str, forecasts: dict, spec: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with (CACHE_DIR / f"{cache_key}.pkl").open("wb") as f:
        pickle.dump(forecasts, f)
    # The spec beside it says what the file holds
    (CACHE_DIR / f"{cache_key}.json").write_text(json.dumps(spec, sort_keys=True, default=str, indent=1))
