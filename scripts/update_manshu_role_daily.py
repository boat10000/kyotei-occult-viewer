#!/usr/bin/env python3
"""Fetch one day of data and publish the manshu role-ranking JSON.

This is the safe daily automation entrypoint used by GitHub Actions. It keeps
the public page static and refreshes only data/output/manshu_role_ranking_*.json.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import sys
import tempfile
from pathlib import Path


JST = dt.timezone(dt.timedelta(hours=9), name="JST")


def normalize_date(value: str | None) -> tuple[str, str]:
    if not value:
        today = dt.datetime.now(JST).date().isoformat()
        return today, today.replace("-", "")
    raw = value.strip()
    if re.fullmatch(r"\d{8}", raw):
        compact = raw
        dashed = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        dashed = raw
        compact = raw.replace("-", "")
    else:
        raise argparse.ArgumentTypeError("date must be YYYY-MM-DD or YYYYMMDD")
    dt.date.fromisoformat(dashed)
    return dashed, compact


def run_command(cmd: list[str], dry_run: bool = False) -> None:
    print("+ " + " ".join(cmd), flush=True)
    if dry_run:
        return
    subprocess.run(cmd, check=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="JST date as YYYY-MM-DD or YYYYMMDD. Defaults to today in JST.")
    parser.add_argument("--source", choices=["official", "official-download", "openapi"], default="official")
    parser.add_argument("--mode", choices=["morning", "preview"], default="morning")
    parser.add_argument("--top", type=int, default=24)
    parser.add_argument("--skip-fetch", action="store_true", help="reuse existing raw cache and skip network fetch")
    parser.add_argument("--force", action="store_true", help="ignore cached raw files when fetching")
    parser.add_argument("--dry-run", action="store_true", help="print commands without running them")
    parser.add_argument("--raw-dir", default="data/raw")
    parser.add_argument("--normalized-dir", default="data/normalized")
    parser.add_argument("--output-dir", default="data/output")
    parser.add_argument("--work-dir", help="temporary analysis output directory; defaults to a temp directory")
    return parser


def run(args: argparse.Namespace) -> int:
    date_dash, date_compact = normalize_date(args.date)
    python = sys.executable or "python3"

    with tempfile.TemporaryDirectory(prefix="manshu_role_daily_") as tmp_name:
        work_dir = Path(args.work_dir) if args.work_dir else Path(tmp_name)
        work_dir.mkdir(parents=True, exist_ok=True)
        race_csv = work_dir / f"race_dataset_{date_compact}.csv"
        race_parquet = work_dir / f"race_dataset_{date_compact}.parquet"
        feature_dictionary = work_dir / "feature_dictionary.md"
        quality_report = work_dir / "data_quality_report.md"
        boat_csv = work_dir / f"boat_role_dataset_{date_compact}.csv"
        boat_parquet = work_dir / f"boat_role_dataset_{date_compact}.parquet"
        boat_dictionary = work_dir / "boat_role_feature_dictionary.md"
        output_json = Path(args.output_dir) / f"manshu_role_ranking_{date_compact}.json"

        if not args.skip_fetch:
            fetch_cmd = [
                python,
                "scripts/fetch_boatrace_data.py",
                "--date",
                date_dash,
                "--source",
                args.source,
                "--cache",
                "--raw-dir",
                args.raw_dir,
            ]
            if args.force:
                fetch_cmd.append("--force")
            run_command(fetch_cmd, dry_run=args.dry_run)

        run_command(
            [
                python,
                "scripts/normalize_boatrace_data.py",
                "--date",
                date_dash,
                "--raw-dir",
                args.raw_dir,
                "--output-dir",
                args.normalized_dir,
            ],
            dry_run=args.dry_run,
        )
        run_command(
            [
                python,
                "scripts/build_manshu_dataset.py",
                "--date",
                date_dash,
                "--normalized-dir",
                args.normalized_dir,
                "--raw-dir",
                args.raw_dir,
                "--output-csv",
                str(race_csv),
                "--output-parquet",
                str(race_parquet),
                "--feature-dictionary",
                str(feature_dictionary),
                "--quality-report",
                str(quality_report),
            ],
            dry_run=args.dry_run,
        )
        run_command(
            [
                python,
                "scripts/build_boat_role_dataset.py",
                "--race-dataset",
                str(race_csv),
                "--output-csv",
                str(boat_csv),
                "--output-parquet",
                str(boat_parquet),
                "--dictionary",
                str(boat_dictionary),
                "--include-unlabeled",
            ],
            dry_run=args.dry_run,
        )
        run_command(
            [
                python,
                "scripts/generate_manshu_role_ranking.py",
                "--dataset",
                str(boat_csv),
                "--date",
                date_dash,
                "--mode",
                args.mode,
                "--top",
                str(args.top),
                "--output",
                str(output_json),
                "--source-dataset-label",
                f"daily temporary boat role dataset for {date_dash}",
            ],
            dry_run=args.dry_run,
        )
        if not args.dry_run:
            print(f"updated {output_json}", flush=True)
    return 0


if __name__ == "__main__":
    import os

    os.chdir(Path(__file__).resolve().parents[1])
    raise SystemExit(run(build_parser().parse_args()))
