"""Extract: fetch the latest stored results of Dune queries via the API.

Only stored results are read; queries are never re-executed.
Every result is cached in data/raw/, so the pipeline also runs offline.
"""
import json
import os
import time
from datetime import datetime, timezone

import pandas as pd
import requests
from dotenv import load_dotenv

import config


class DuneAPIError(Exception):
    pass


def get_api_key() -> str:
    load_dotenv(config.BASE_DIR / ".env")
    key = os.getenv("DUNE_API_KEY")
    if not key or key == "your_api_key_here":
        raise DuneAPIError("DUNE_API_KEY missing. Copy .env.example to .env and add your key.")
    return key


def _request(session: requests.Session, url: str, params: dict | None) -> dict:
    """GET with retries for rate limits, server errors and timeouts."""
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            resp = session.get(url, params=params, timeout=config.REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            if attempt == config.MAX_RETRIES:
                raise DuneAPIError(f"Network error: {exc}") from exc
            time.sleep(2 ** attempt)
            continue

        if resp.status_code == 200:
            return resp.json()
        if resp.status_code in (429, 500, 502, 503, 504) and attempt < config.MAX_RETRIES:
            time.sleep(2 ** attempt)
            continue
        raise DuneAPIError(f"HTTP {resp.status_code}: {resp.text[:300]}")
    raise DuneAPIError("Retries exhausted")


def fetch_latest_result(query_id: int, api_key: str) -> tuple[pd.DataFrame, dict]:
    """Read all rows of the latest stored result, page by page."""
    session = requests.Session()
    session.headers.update({"X-Dune-API-Key": api_key})

    url = f"{config.API_BASE}/query/{query_id}/results"
    params = {"limit": config.PAGE_SIZE, "offset": 0}
    rows, columns, meta = [], None, {}

    while True:
        payload = _request(session, url, params)
        if payload.get("state") not in (None, "QUERY_STATE_COMPLETED"):
            raise DuneAPIError(f"Query {query_id} state: {payload.get('state')}")

        result = payload.get("result") or {}
        rows.extend(result.get("rows", []))
        if columns is None:
            columns = (result.get("metadata") or {}).get("column_names")
            meta = {
                "query_id": query_id,
                "execution_id": payload.get("execution_id"),
                "execution_ended_at": payload.get("execution_ended_at"),
                "total_row_count": (result.get("metadata") or {}).get("total_row_count"),
            }

        next_uri = payload.get("next_uri")
        if not next_uri:
            break
        url, params = next_uri, None  # next_uri already contains limit/offset

    df = pd.DataFrame(rows, columns=columns)
    expected = meta.get("total_row_count")
    if expected is not None and len(df) != expected:
        raise DuneAPIError(f"Query {query_id}: got {len(df)} rows, expected {expected}")
    return df, meta


def extract_all(offline: bool = False) -> dict[str, pd.DataFrame]:
    """Fetch every configured query; fall back to the cache on failure."""
    config.RAW_DIR.mkdir(parents=True, exist_ok=True)
    meta_path = config.RAW_DIR / "_metadata.json"
    metadata = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    api_key = None if offline else get_api_key()

    frames = {}
    for name, query_id in config.QUERIES.items():
        cache = config.RAW_DIR / f"{name}.csv"

        if not offline:
            try:
                df, meta = fetch_latest_result(query_id, api_key)
                df.to_csv(cache, index=False)
                meta["fetched_at"] = datetime.now(timezone.utc).isoformat()
                metadata[name] = meta
                print(f"[api]   {name}: {len(df)} rows")
                frames[name] = df
                continue
            except DuneAPIError as exc:
                print(f"[warn]  {name}: API failed ({exc}); trying cache")

        if not cache.exists():
            raise FileNotFoundError(f"No cached result for {name} at {cache}")
        frames[name] = pd.read_csv(cache)
        print(f"[cache] {name}: {len(frames[name])} rows")

    meta_path.write_text(json.dumps(metadata, indent=2))
    return frames
