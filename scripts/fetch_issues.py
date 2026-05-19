#!/usr/bin/env python3
"""Fetch closed issues (not PRs) from pandas-dev/pandas via the GitHub API."""

from __future__ import annotations

import http.client
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

REPO = "pandas-dev/pandas"
API_BASE = f"https://api.github.com/repos/{REPO}/issues"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "datasets/raw/issues.json"
STATE_PATH = OUTPUT_PATH.parent / "fetch_state.json"
PER_PAGE = 100
MAX_ISSUES = 2000
MAX_RETRIES = 5
REQUEST_TIMEOUT_SEC = 120
RETRY_BASE_SEC = 2
RETRIABLE_HTTP_CODES = {403, 429, 500, 502, 503, 504}
TRANSIENT_ERRORS = (
    urllib.error.URLError,
    TimeoutError,
    http.client.IncompleteRead,
    ConnectionResetError,
    BrokenPipeError,
)


def _backoff_delay(attempt: int, retry_after: str | None = None) -> float:
    if retry_after:
        return float(retry_after)
    return RETRY_BASE_SEC * (2 ** (attempt - 1))


def _retry_or_raise(attempt: int, exc: BaseException) -> None:
    if attempt >= MAX_RETRIES:
        raise exc
    delay = _backoff_delay(attempt)
    print(
        f"Transient error ({type(exc).__name__}: {exc}), "
        f"retrying in {delay:.0f}s ({attempt}/{MAX_RETRIES})...",
        flush=True,
    )
    time.sleep(delay)


def request_json(url: str) -> tuple[Any, dict[str, str]]:
    token = os.environ.get("GITHUB_TOKEN")
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "maintainers-copilot-fetch-issues",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = urllib.request.Request(url, headers=headers)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(
                request, timeout=REQUEST_TIMEOUT_SEC
            ) as response:
                raw = response.read()
                headers_out = dict(response.headers)
            return json.loads(raw.decode()), headers_out
        except urllib.error.HTTPError as exc:
            if exc.code not in RETRIABLE_HTTP_CODES:
                raise
            retry_after = exc.headers.get("Retry-After")
            if attempt >= MAX_RETRIES:
                raise
            delay = _backoff_delay(attempt, retry_after)
            print(
                f"HTTP {exc.code}, retrying in {delay:.0f}s "
                f"({attempt}/{MAX_RETRIES})...",
                flush=True,
            )
            time.sleep(delay)
        except TRANSIENT_ERRORS as exc:
            _retry_or_raise(attempt, exc)

    raise RuntimeError(f"Request failed after {MAX_RETRIES} attempts: {url}")


def parse_issue(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "number": item["number"],
        "title": item["title"],
        "body": item.get("body"),
        "labels": [label["name"] for label in item.get("labels", [])],
        "created_at": item["created_at"],
        "closed_at": item["closed_at"],
    }


def load_progress() -> tuple[list[dict[str, Any]], set[int], int]:
    issues: list[dict[str, Any]] = []
    seen: set[int] = set()
    next_page = 1

    if OUTPUT_PATH.exists():
        issues = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        seen = {issue["number"] for issue in issues}

    if STATE_PATH.exists():
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        next_page = int(state["next_page"])

    return issues, seen, next_page


def save_progress(issues: list[dict[str, Any]], next_page: int) -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    issues_tmp = OUTPUT_PATH.with_suffix(".tmp")
    issues_tmp.write_text(
        json.dumps(issues, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    issues_tmp.replace(OUTPUT_PATH)

    state_tmp = STATE_PATH.with_suffix(".tmp")
    state_tmp.write_text(
        json.dumps({"next_page": next_page}) + "\n",
        encoding="utf-8",
    )
    state_tmp.replace(STATE_PATH)


def fetch_closed_issues() -> list[dict[str, Any]]:
    issues, seen, page = load_progress()

    if issues:
        print(f"Resuming: {len(issues)} issues loaded, starting at page {page}")

    while len(issues) < MAX_ISSUES:
        query = urllib.parse.urlencode(
            {"state": "closed", "per_page": PER_PAGE, "page": page}
        )
        batch, _ = request_json(f"{API_BASE}?{query}")

        if not batch:
            break

        added = 0
        for item in batch:
            if "pull_request" in item:
                continue
            parsed = parse_issue(item)
            if parsed["number"] in seen:
                continue
            if len(issues) >= MAX_ISSUES:
                break
            issues.append(parsed)
            seen.add(parsed["number"])
            added += 1

        save_progress(issues, page + 1)
        print(f"Page {page}: +{added} issues ({len(issues)} total, saved)")

        if len(issues) >= MAX_ISSUES:
            break
        if len(batch) < PER_PAGE:
            break

        page += 1

    return issues


def main() -> None:
    issues = fetch_closed_issues()
    print(f"Done. {len(issues)} issues in {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
