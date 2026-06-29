#!/usr/bin/env python3
"""Dispatch BOATERS monitoring once for morning watchlist races near T-10.

This is designed for a Codex heartbeat that wakes frequently.  The script reads
today's fixed morning watchlist TOP10, finds races whose deadline is about
10 minutes away, and runs the heavier BOATERS monitor only for those race_id(s).
Handled race_ids are recorded so a one-minute heartbeat does not repeat them.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


JST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "output"
PUBLIC_BASE = "https://mm1601.github.io/kyotei-occult-viewer/data/output"


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=JST)
    return dt.astimezone(JST)


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fetch_json(url: str, path: Path) -> Path | None:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Codex BOATERS deadline watch)",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            if response.status >= 400:
                return None
            body = response.read().decode("utf-8", errors="replace")
    except Exception:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def ranking_candidates(date_text: str, public_base: str) -> tuple[dict[str, Any], Path | None]:
    key = date_text.replace("-", "")
    paths = [
        OUT / f"boaters_manshu_morning_ranking_{key}.json",
        OUT / f"boaters_manshu_ranking_codex_{key}.json",
        OUT / f"boaters_manshu_ranking_{key}.json",
    ]
    for path in paths:
        payload = load_json(path, None)
        if isinstance(payload, dict):
            return payload, path

    for name in (f"boaters_manshu_ranking_codex_{key}.json", f"boaters_manshu_ranking_{key}.json"):
        path = OUT / name
        fetched = fetch_json(f"{public_base.rstrip('/')}/{name}", path)
        if fetched:
            payload = load_json(fetched, None)
            if isinstance(payload, dict):
                return payload, fetched
    return {}, None


def watchlist_rows(payload: dict[str, Any], top_n: int) -> list[dict[str, Any]]:
    rows = payload.get("morning_candidates")
    if not isinstance(rows, list) or not rows:
        source = payload.get("races") or []
        rows = [
            row
            for row in source
            if str(row.get("ranking_type") or "") == "morning_watchlist"
            or str(row.get("candidate_phase") or "") == "morning_watchlist"
        ]
    if not rows:
        rows = payload.get("races") or []

    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        race_id = str(row.get("race_id") or f"{row.get('place_id')}:{row.get('round')}")
        if not race_id or race_id in seen:
            continue
        seen.add(race_id)
        unique.append(row)
        if len(unique) >= top_n:
            break
    return unique


def race_label(row: dict[str, Any]) -> str:
    return f"{row.get('place_name') or ''}{row.get('round') or ''}R"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="JST date. Defaults to today.")
    parser.add_argument("--now", help="Override current JST timestamp.")
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--target-minutes", type=float, default=10.0)
    parser.add_argument("--early-tolerance-minutes", type=float, default=1.0)
    parser.add_argument("--late-tolerance-minutes", type=float, default=4.0)
    parser.add_argument("--threshold", type=float, default=27.0)
    parser.add_argument("--public-base", default=PUBLIC_BASE)
    parser.add_argument("--no-run", action="store_true", help="Only report due races; do not run the BOATERS monitor.")
    parser.add_argument("--no-push", action="store_true", help="Pass --no-push to the BOATERS monitor.")
    args = parser.parse_args()

    now = parse_dt(args.now) if args.now else datetime.now(JST)
    if now is None:
        raise SystemExit("--now must be an ISO datetime")
    date_text = args.date or now.date().isoformat()
    key = date_text.replace("-", "")

    payload, source_path = ranking_candidates(date_text, args.public_base)
    rows = watchlist_rows(payload, args.top_n)
    state_path = OUT / f"boaters_deadline_instruction_state_{key}.json"
    state = load_json(state_path, {"handled": {}})
    handled = state.setdefault("handled", {})

    lower = args.target_minutes - args.late_tolerance_minutes
    upper = args.target_minutes + args.early_tolerance_minutes
    due: list[dict[str, Any]] = []
    inspected: list[dict[str, Any]] = []
    for rank, row in enumerate(rows, start=1):
        race_id = str(row.get("race_id") or "")
        deadline = parse_dt(row.get("deadline_time"))
        if not race_id or deadline is None:
            inspected.append({"race_id": race_id, "rank": rank, "status": "skip_no_deadline"})
            continue
        minutes = (deadline - now).total_seconds() / 60
        item = {
            "race_id": race_id,
            "rank": rank,
            "race": race_label(row),
            "deadline_time": row.get("deadline_time"),
            "minutes_to_deadline": round(minutes, 2),
        }
        if race_id in handled:
            item["status"] = "already_handled"
        elif lower <= minutes <= upper:
            item["status"] = "due"
            due.append({**row, **item})
        else:
            item["status"] = "not_due"
        inspected.append(item)

    result: dict[str, Any] = {
        "version": "boaters-deadline-watch-v1",
        "date": date_text,
        "generated_at": now.isoformat(timespec="seconds"),
        "source_path": str(source_path) if source_path else None,
        "top_n": args.top_n,
        "target_minutes": args.target_minutes,
        "window_minutes": [lower, upper],
        "due_races": [
            {
                "race_id": row.get("race_id"),
                "rank": row.get("rank"),
                "race": row.get("race"),
                "deadline_time": row.get("deadline_time"),
                "minutes_to_deadline": row.get("minutes_to_deadline"),
            }
            for row in due
        ],
        "inspected": inspected,
    }

    if not rows:
        result["status"] = "no_watchlist_already_reported" if state.get("no_watchlist_reported") else "no_watchlist"
        state["no_watchlist_reported"] = True
        state["updated_at"] = now.isoformat(timespec="seconds")
        save_json(state_path, state)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if not due:
        result["status"] = "no_due"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.no_run:
        result["status"] = "due_dry_run"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "monitor_boaters_manshu_alerts.py"),
        "--date",
        date_text,
        "--top-n",
        str(args.top_n),
        "--threshold",
        str(args.threshold),
        "--alert-threshold",
        "38",
        "--core-alert-threshold",
        "40",
        "--lookahead-minutes",
        str(args.target_minutes + args.early_tolerance_minutes),
        "--grace-minutes",
        "0",
        "--scan-risers",
        "--notify-risers",
        "--riser-top-n",
        "10",
        "--riser-threshold",
        "40",
    ]
    for row in due:
        cmd.extend(["--only-race-id", str(row.get("race_id"))])
    if args.no_push:
        cmd.append("--no-push")

    completed = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    result["command"] = cmd
    result["monitor_returncode"] = completed.returncode
    monitor_payload: dict[str, Any] | None = None
    if completed.stdout:
        try:
            monitor_payload = json.loads(completed.stdout)
            result["monitor_payload"] = monitor_payload
        except json.JSONDecodeError:
            result["monitor_stdout"] = completed.stdout[-4000:]
    if completed.stderr:
        result["monitor_stderr"] = completed.stderr[-4000:]

    due_ids = {str(row.get("race_id")) for row in due}
    inspected_rows = (monitor_payload or {}).get("inspected") or []
    ready_ids = {
        str(item.get("race_id"))
        for item in inspected_rows
        if str(item.get("race_id")) in due_ids
        and item.get("status") == "checked"
        and item.get("preview_ready") is not False
    }
    failed_ids = {
        str(item.get("race_id"))
        for item in inspected_rows
        if str(item.get("race_id")) in due_ids and item.get("status") == "fetch_failed"
    }
    missing_ready_ids = due_ids - ready_ids
    min_minutes_to_deadline = min((float(row.get("minutes_to_deadline") or 0) for row in due), default=0)
    final_retry_point = lower + 0.25
    should_retry = (
        completed.returncode != 0
        or bool(failed_ids)
        or bool(missing_ready_ids)
    ) and min_minutes_to_deadline > final_retry_point

    if should_retry:
        result["status"] = "waiting_for_boaters_data"
        result["retry_reason"] = {
            "failed_race_ids": sorted(failed_ids),
            "missing_ready_race_ids": sorted(missing_ready_ids),
            "minutes_to_deadline": min_minutes_to_deadline,
            "retry_until_minutes_to_deadline": lower,
        }
        attempts = state.setdefault("attempts", {})
        for row in due:
            attempts.setdefault(str(row.get("race_id")), []).append(
                {
                    "attempted_at": now.isoformat(timespec="seconds"),
                    "race": row.get("race"),
                    "deadline_time": row.get("deadline_time"),
                    "minutes_to_deadline": row.get("minutes_to_deadline"),
                    "monitor_returncode": completed.returncode,
                    "failed": str(row.get("race_id")) in failed_ids,
                    "ready": str(row.get("race_id")) in ready_ids,
                }
            )
        state["updated_at"] = now.isoformat(timespec="seconds")
        save_json(state_path, state)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    status = "monitor_ok" if completed.returncode == 0 else "monitor_failed"
    if completed.returncode == 0 and missing_ready_ids:
        status = "data_unavailable_final"
    result["status"] = status
    for row in due:
        handled[str(row.get("race_id"))] = {
            "handled_at": now.isoformat(timespec="seconds"),
            "race": row.get("race"),
            "deadline_time": row.get("deadline_time"),
            "monitor_returncode": completed.returncode,
        }
    state["updated_at"] = now.isoformat(timespec="seconds")
    save_json(state_path, state)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if completed.returncode == 0 else completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
