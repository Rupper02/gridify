import json
import os

import dagster as dg
import pandas as pd
from openai import OpenAI

from grid_simulator.config import (
    EXTRACTION_MODEL,
    EXTRACTION_RESPONSE_FORMAT,
    EXTRACTION_SYSTEM_PROMPT,
    MAX_CONNECTION_MW,
    OPENROUTER_BASE_URL,
    REQUESTS_DIR,
)


@dg.asset
def raw_connection_requests(context: dg.AssetExecutionContext) -> pd.DataFrame:
    rows = []
    for path in sorted(REQUESTS_DIR.glob("*.txt")):
        rows.append({"request_id": path.stem,
                     "text": path.read_text(encoding="UTF-8")})
    df = pd.DataFrame(rows)
    context.add_output_metadata({"requests": len(df)})
    return df


@dg.asset
def extracted_connections(
    context: dg.AssetExecutionContext,
    raw_connection_requests: pd.DataFrame,
) -> pd.DataFrame:
    client = OpenAI(
        api_key=os.environ["OPENROUTER_API_KEY"], base_url=OPENROUTER_BASE_URL)

    rows = []
    for req in raw_connection_requests.itertuples(index=False):
        response = client.chat.completions.create(
            model=EXTRACTION_MODEL,
            messages=[
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": req.text},
            ],
            response_format=EXTRACTION_RESPONSE_FORMAT,
        )
        data = json.loads(response.choices[0].message.content)
        data["request_id"] = req.request_id
        rows.append(data)

    df = pd.DataFrame(rows)
    context.add_output_metadata({"extracted": len(df), "model": EXTRACTION_MODEL})
    return df


@dg.asset
def triaged_connections(
    context: dg.AssetExecutionContext,
    extracted_connections: pd.DataFrame,
    canonical_buses: pd.DataFrame,
) -> pd.DataFrame:
    valid_bus_ids = set(canonical_buses["bus_id"])

    def review_reasons(row) -> list[str]:
        reasons = []
        if pd.isna(row.bus_id):
            reasons.append("missing a bus")
        elif int(row.bus_id) not in valid_bus_ids:
            reasons.append("bus is not in model")
        if pd.isna(row.rating_mw):
            reasons.append("missing rating")
        elif not (0 < row.rating_mw <= MAX_CONNECTION_MW):
            reasons.append("rating is out of range")
        if pd.isna(row.technology):
            reasons.append("missing gen technology")
        return reasons

    out = extracted_connections.copy()
    reasons = out.apply(review_reasons, axis=1)
    out["status"] = reasons.apply(
        lambda r: "auto_accept" if not r else "needs_review")
    out["review_reasons"] = reasons.apply(lambda r: ", ".join(r))

    context.add_output_metadata({
        "auto_accept": int((out["status"] == "auto_accept").sum()),
        "needs_review": int((out["status"] == "needs_review").sum()),
    })
    return out
