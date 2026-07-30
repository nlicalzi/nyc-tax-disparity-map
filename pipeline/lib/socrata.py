"""Shared Socrata SoQL pagination helper.

Pulls only the columns/rows needed via $select/$where, paginates with
$limit/$offset, and returns a pandas DataFrame. Never used to pull a full
raw table into an agent's context — callers write the result straight to
parquet in data/cache/.
"""
import os
import sys
import time

import pandas as pd
import requests

DOMAIN = "https://data.cityofnewyork.us/resource"


def _token() -> str:
    token = os.environ.get("SOCRATA_APP_TOKEN")
    if not token:
        raise RuntimeError("SOCRATA_APP_TOKEN not set (source .env first)")
    return token


def fetch_all(
    dataset_id: str,
    select: str,
    where: str | None = None,
    order: str = ":id",
    page_size: int = 50000,
    max_rows: int | None = None,
    progress_label: str | None = None,
) -> pd.DataFrame:
    headers = {"X-App-Token": _token()}
    url = f"{DOMAIN}/{dataset_id}.json"
    label = progress_label or dataset_id

    pages: list[pd.DataFrame] = []
    offset = 0
    while True:
        params = {
            "$select": select,
            "$order": order,
            "$limit": page_size,
            "$offset": offset,
        }
        if where:
            params["$where"] = where

        for attempt in range(5):
            resp = requests.get(url, headers=headers, params=params, timeout=60)
            if resp.status_code == 200:
                break
            wait = 2**attempt
            print(
                f"  [{label}] HTTP {resp.status_code}, retry in {wait}s "
                f"(offset={offset})",
                file=sys.stderr,
            )
            time.sleep(wait)
        else:
            resp.raise_for_status()

        rows = resp.json()
        if not rows:
            break

        pages.append(pd.DataFrame(rows))
        offset += len(rows)
        print(f"  [{label}] fetched {offset} rows", file=sys.stderr)

        if len(rows) < page_size:
            break
        if max_rows is not None and offset >= max_rows:
            break

    if not pages:
        return pd.DataFrame()

    df = pd.concat(pages, ignore_index=True)
    if max_rows is not None:
        df = df.iloc[:max_rows]
    return df
