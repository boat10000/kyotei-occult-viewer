#!/usr/bin/env python3
"""Fetch BOAT RACE official race pages into a local cache.

This script intentionally fetches only the daily index by default. Race-level
pages are fetched only when the caller opts in with --details/--odds/--preview
or --results. Requests are sequential, cached, and rate-limited.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import re
import ssl
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


BASE_URL = "https://www.boatrace.jp"
MBRACE_URL = "https://www1.mbrace.or.jp"
OPENAPI_URL = "https://boatraceopenapi.github.io"
DEFAULT_USER_AGENT = (
    "kyotei-occult-viewer-data-fetcher/0.1 "
    "(local cache; low frequency; https://boat10000.github.io/kyotei-occult-viewer/)"
)
JST = dt.timezone(dt.timedelta(hours=9), name="JST")


def normalize_date(value: str) -> tuple[str, str]:
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


def date_range(start: str, end: str) -> list[tuple[str, str]]:
    start_dash, _start_compact = normalize_date(start)
    end_dash, _end_compact = normalize_date(end)
    current = dt.date.fromisoformat(start_dash)
    last = dt.date.fromisoformat(end_dash)
    if current > last:
        raise argparse.ArgumentTypeError("start date must be on or before end date")
    dates: list[tuple[str, str]] = []
    while current <= last:
        dashed = current.isoformat()
        dates.append((dashed, dashed.replace("-", "")))
        current += dt.timedelta(days=1)
    return dates


def now_iso() -> str:
    return dt.datetime.now(JST).isoformat(timespec="seconds")


def clean_text(fragment: str) -> str:
    text = re.sub(r"(?i)<br\s*/?>", "\n", fragment)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text).replace("\xa0", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*", "\n", text)
    return text.strip()


def absolute_url(path_or_url: str) -> str:
    return urllib.parse.urljoin(BASE_URL, html.unescape(path_or_url))


def index_url(date_compact: str) -> str:
    return f"{BASE_URL}/owpc/pc/race/index?hd={date_compact}"


def race_url(kind: str, date_compact: str, jcd: str, rno: int) -> str:
    endpoint = {
        "racelist": "racelist",
        "odds3t": "odds3t",
        "beforeinfo": "beforeinfo",
        "raceresult": "raceresult",
    }[kind]
    query = urllib.parse.urlencode({"hd": date_compact, "jcd": jcd, "rno": str(rno)})
    return f"{BASE_URL}/owpc/pc/race/{endpoint}?{query}"


def resultlist_url(date_compact: str, jcd: str) -> str:
    query = urllib.parse.urlencode({"hd": date_compact, "jcd": jcd})
    return f"{BASE_URL}/owpc/pc/race/resultlist?{query}"


def official_download_url(kind: str, date_compact: str) -> str:
    yy = date_compact[2:4]
    mm = date_compact[4:6]
    dd = date_compact[6:8]
    month = date_compact[:6]
    prefix = kind.lower()
    return f"{MBRACE_URL}/od2/{kind}/{month}/{prefix}{yy}{mm}{dd}.lzh"


def openapi_url(kind: str, date_compact: str) -> str:
    year = date_compact[:4]
    endpoint = {"programs": "programs", "previews": "previews", "results": "results"}[kind]
    return f"{OPENAPI_URL}/{endpoint}/v3/{year}/{date_compact}.json"


def safe_filename(kind: str, url: str, jcd: str | None = None, rno: int | None = None) -> str:
    if kind == "index":
        return "official_index.html"
    if kind == "resultlist" and jcd:
        return f"official_resultlist_{jcd}.html"
    if jcd and rno is not None:
        return f"official_{kind}_{jcd}_{rno:02d}.html"
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
    return f"official_{kind}_{digest}.html"


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "entries": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"version": 1, "entries": []}


def save_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def read_cached_text(path: Path) -> str | None:
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8", errors="replace")


def ssl_context() -> ssl.SSLContext:
    try:
        import certifi  # type: ignore

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def fetch_url(url: str, user_agent: str, timeout: float, retries: int) -> tuple[int, str]:
    headers = {"User-Agent": user_agent, "Accept": "text/html,application/json;q=0.9,*/*;q=0.8"}
    last_error: Exception | None = None
    context = ssl_context()
    for attempt in range(retries + 1):
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                raw = response.read()
                encoding = response.headers.get_content_charset() or "utf-8"
                try:
                    text = raw.decode(encoding)
                except UnicodeDecodeError:
                    text = raw.decode("cp932", errors="replace")
                return int(response.status), text
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt >= retries:
                break
            time.sleep(min(8.0, 2.0**attempt))
    raise RuntimeError(f"failed to fetch {url}: {last_error}")


def fetch_bytes(url: str, user_agent: str, timeout: float, retries: int) -> tuple[int, bytes]:
    headers = {"User-Agent": user_agent, "Accept": "application/octet-stream,application/json;q=0.9,*/*;q=0.8"}
    last_error: Exception | None = None
    context = ssl_context()
    for attempt in range(retries + 1):
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                return int(response.status), response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return int(exc.code), b""
            last_error = exc
            if attempt >= retries:
                break
            time.sleep(min(8.0, 2.0**attempt))
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt >= retries:
                break
            time.sleep(min(8.0, 2.0**attempt))
    raise RuntimeError(f"failed to fetch {url}: {last_error}")


def extract_lzh_text(archive: Path, output_path: Path) -> bool:
    lha = shutil.which("lha") or shutil.which("lhasa")
    if not lha:
        print("warning: lha/lhasa command not found; saved .lzh but skipped extraction", file=sys.stderr)
        return False
    with tempfile.TemporaryDirectory(prefix="boatrace_lzh_") as tmp_name:
        tmp_dir = Path(tmp_name)
        try:
            subprocess.run(
                [lha, "x", str(archive.resolve())],
                cwd=tmp_dir,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            print(f"warning: failed to extract {archive}: {exc.stderr.strip()}", file=sys.stderr)
            return False
        text_files = sorted(tmp_dir.glob("*.txt")) + sorted(tmp_dir.glob("*.TXT"))
        if not text_files:
            print(f"warning: no TXT file found in {archive}", file=sys.stderr)
            return False
        raw = text_files[0].read_bytes()
        try:
            text = raw.decode("cp932")
        except UnicodeDecodeError:
            text = raw.decode("utf-8", errors="replace")
        output_path.write_text(text, encoding="utf-8")
        return True


def parse_venues_from_index(index_html: str) -> list[dict[str, str | None]]:
    venues: list[dict[str, str | None]] = []
    seen: set[str] = set()
    for block in re.findall(r"(?is)<tbody[^>]*>(.*?)</tbody>", index_html):
        if "raceindex?jcd=" not in block:
            continue
        jcd_match = re.search(r"raceindex\?jcd=(\d{2})&amp;hd=(\d{8})", block)
        if not jcd_match:
            jcd_match = re.search(r"raceindex\?jcd=(\d{2})[&\"]", html.unescape(block))
        if not jcd_match:
            continue
        jcd = jcd_match.group(1)
        if jcd in seen:
            continue
        seen.add(jcd)
        name_match = re.search(r'text_place1_\d+\.png"[^>]*alt="([^"]+)"', block)
        title_match = re.search(r'(?is)<a href="/owpc/pc/race/raceindex\?jcd=' + re.escape(jcd) + r"&amp;hd=\d{8}\">(.*?)</a>", block)
        class_values = " ".join(re.findall(r'class="([^"]+)"', block))
        grade = grade_from_classes(class_values)
        text = clean_text(block)
        status_match = re.search(r"(?is)<td[^>]*colspan=\"3\"[^>]*>(.*?)</td>", block)
        status = clean_text(status_match.group(1)) if status_match else first_match_text(text, ["発売中", "発売締切", "最終Ｒ発売終了", "中止", "順延"])
        day_label = None
        day_match = re.search(r"\d{1,2}/\d{1,2}-\d{1,2}/\d{1,2}\s*(\S+日|最終日|初日)", text)
        if day_match:
            day_label = day_match.group(1)
        venues.append(
            {
                "jcd": jcd,
                "name": html.unescape(name_match.group(1)) if name_match else None,
                "grade": grade,
                "title": clean_text(title_match.group(1)) if title_match else None,
                "day_label": day_label,
                "status": status,
            }
        )
    return venues


def grade_from_classes(class_values: str) -> str | None:
    checks = [
        ("is-SG", "SG"),
        ("is-G1", "G1"),
        ("is-G2", "G2"),
        ("is-G3", "G3"),
        ("is-ippan", "一般"),
    ]
    for needle, label in checks:
        if needle in class_values:
            return label
    return None


def first_match_text(text: str, needles: list[str]) -> str | None:
    for needle in needles:
        if needle in text:
            return needle
    return None


def plan_requests(args: argparse.Namespace, raw_dir: Path, date_compact: str) -> list[dict[str, Any]]:
    planned: list[dict[str, Any]] = [
        {
            "kind": "index",
            "url": index_url(date_compact),
            "file": "official_index.html",
            "jcd": None,
            "rno": None,
        }
    ]
    wants_race_pages = args.details or args.odds or args.preview or args.results
    if not wants_race_pages:
        return planned

    if args.jcd:
        jcds = [args.jcd]
    else:
        cached_index = read_cached_text(raw_dir / "official_index.html")
        if cached_index:
            jcds = [venue["jcd"] for venue in parse_venues_from_index(cached_index) if venue.get("jcd")]
        else:
            print(
                "note: no cached official_index.html; run once without race-level options "
                "or specify --jcd to expand detail URLs",
                file=sys.stderr,
            )
            return planned

    races = [args.rno] if args.rno else list(range(1, 13))
    for jcd in jcds:
        if args.results:
            url = resultlist_url(date_compact, jcd)
            planned.append(
                {
                    "kind": "resultlist",
                    "url": url,
                    "file": safe_filename("resultlist", url, jcd=jcd),
                    "jcd": jcd,
                    "rno": None,
                }
            )
        for rno in races:
            if args.details:
                url = race_url("racelist", date_compact, jcd, rno)
                planned.append(
                    {
                        "kind": "racelist",
                        "url": url,
                        "file": safe_filename("racelist", url, jcd=jcd, rno=rno),
                        "jcd": jcd,
                        "rno": rno,
                    }
                )
            if args.odds:
                url = race_url("odds3t", date_compact, jcd, rno)
                planned.append(
                    {
                        "kind": "odds3t",
                        "url": url,
                        "file": safe_filename("odds3t", url, jcd=jcd, rno=rno),
                        "jcd": jcd,
                        "rno": rno,
                    }
                )
            if args.preview:
                url = race_url("beforeinfo", date_compact, jcd, rno)
                planned.append(
                    {
                        "kind": "beforeinfo",
                        "url": url,
                        "file": safe_filename("beforeinfo", url, jcd=jcd, rno=rno),
                        "jcd": jcd,
                        "rno": rno,
                    }
                )
            if args.results:
                url = race_url("raceresult", date_compact, jcd, rno)
                planned.append(
                    {
                        "kind": "raceresult",
                        "url": url,
                        "file": safe_filename("raceresult", url, jcd=jcd, rno=rno),
                        "jcd": jcd,
                        "rno": rno,
                    }
                )
    return planned


def plan_download_requests(args: argparse.Namespace, _raw_dir: Path, date_compact: str) -> list[dict[str, Any]]:
    wants_specific = args.details or args.results
    kinds: list[str] = []
    if args.details or not wants_specific:
        kinds.append("B")
    if args.results or not wants_specific:
        kinds.append("K")
    planned: list[dict[str, Any]] = []
    for kind in kinds:
        suffix = kind.lower()
        planned.append(
            {
                "kind": f"official_download_{suffix}",
                "url": official_download_url(kind, date_compact),
                "file": f"official_download_{suffix}.lzh",
                "text_file": f"official_download_{suffix}.txt",
                "binary": True,
                "jcd": None,
                "rno": None,
            }
        )
    return planned


def plan_openapi_requests(args: argparse.Namespace, _raw_dir: Path, date_compact: str) -> list[dict[str, Any]]:
    wants_specific = args.details or args.preview or args.results
    kinds: list[str] = []
    if args.details or not wants_specific:
        kinds.append("programs")
    if args.preview:
        kinds.append("previews")
    if args.results or not wants_specific:
        kinds.append("results")
    return [
        {
            "kind": f"openapi_{kind}",
            "url": openapi_url(kind, date_compact),
            "file": f"openapi_{kind}.json",
            "binary": False,
            "jcd": None,
            "rno": None,
        }
        for kind in kinds
    ]


def plan_source_requests(args: argparse.Namespace, raw_dir: Path, date_compact: str) -> list[dict[str, Any]]:
    if args.source == "official-screen":
        return plan_requests(args, raw_dir, date_compact)
    if args.source in {"official", "official-download"}:
        return plan_download_requests(args, raw_dir, date_compact)
    if args.source == "openapi":
        return plan_openapi_requests(args, raw_dir, date_compact)
    raise ValueError(f"unsupported source: {args.source}")


def run_one_date(args: argparse.Namespace, date_dash: str, date_compact: str) -> int:
    raw_dir = Path(args.raw_dir) / date_compact
    raw_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = raw_dir / "manifest.json"
    manifest = load_manifest(manifest_path)
    manifest.update(
        {
            "date": date_dash,
            "date_compact": date_compact,
            "fetched_at": manifest.get("fetched_at"),
            "policy": {
                "rate_limit_seconds": args.sleep,
                "parallel": False,
                "cache_required": True,
                "user_agent": args.user_agent,
            },
        }
    )

    planned = plan_source_requests(args, raw_dir, date_compact)
    if args.dry_run:
        for item in planned:
            print(f"{item['kind']}\t{item['file']}\t{item['url']}")
        return 0

    fetched_any = False
    for idx, item in enumerate(planned):
        target = raw_dir / item["file"]
        entry = {
            "kind": item["kind"],
            "url": item["url"],
            "file": item["file"],
            "jcd": item.get("jcd"),
            "rno": item.get("rno"),
        }
        if target.exists() and not args.force:
            print(f"cache: {target}")
            entry.update({"cached": True, "status": None, "fetched_at": None})
            text_file = item.get("text_file")
            if text_file and not (raw_dir / text_file).exists():
                extracted = extract_lzh_text(target, raw_dir / text_file)
                entry["text_file"] = text_file if extracted else None
        else:
            if fetched_any and args.sleep > 0:
                time.sleep(args.sleep)
            print(f"fetch: {item['url']}")
            if item.get("binary"):
                status, body = fetch_bytes(item["url"], args.user_agent, args.timeout, args.retries)
                if status == 404:
                    print(f"skip missing: {item['url']}", file=sys.stderr)
                    entry.update({"cached": False, "status": status, "fetched_at": now_iso(), "missing": True})
                    manifest["entries"] = [e for e in manifest.get("entries", []) if e.get("file") != item["file"]]
                    manifest["entries"].append(entry)
                    manifest["fetched_at"] = now_iso()
                    save_manifest(manifest_path, manifest)
                    fetched_any = True
                    continue
                target.write_bytes(body)
                text_file = item.get("text_file")
                if text_file:
                    extracted = extract_lzh_text(target, raw_dir / text_file)
                    entry["text_file"] = text_file if extracted else None
            else:
                status, text = fetch_url(item["url"], args.user_agent, args.timeout, args.retries)
                target.write_text(text, encoding="utf-8")
            fetched_any = True
            entry.update({"cached": False, "status": status, "fetched_at": now_iso()})
        manifest["entries"] = [e for e in manifest.get("entries", []) if e.get("file") != item["file"]]
        manifest["entries"].append(entry)
        manifest["fetched_at"] = now_iso()
        save_manifest(manifest_path, manifest)
    print(f"saved manifest: {manifest_path}")
    return 0


def run(args: argparse.Namespace) -> int:
    if args.date:
        dates = [normalize_date(args.date)]
    elif args.start_date and args.end_date:
        dates = date_range(args.start_date, args.end_date)
    else:
        raise SystemExit("provide --date or both --start-date and --end-date")
    exit_code = 0
    for date_dash, date_compact in dates:
        print(f"date: {date_dash}")
        try:
            exit_code = max(exit_code, run_one_date(args, date_dash, date_compact))
        except RuntimeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            exit_code = 1
    return exit_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="JST date as YYYY-MM-DD or YYYYMMDD")
    parser.add_argument("--start-date", help="JST start date as YYYY-MM-DD or YYYYMMDD")
    parser.add_argument("--end-date", help="JST end date as YYYY-MM-DD or YYYYMMDD")
    parser.add_argument(
        "--source",
        choices=["official-screen", "official", "official-download", "openapi"],
        default="official-screen",
        help="data source; --source official uses the official B/K download files",
    )
    parser.add_argument("--jcd", help="venue code, e.g. 01")
    parser.add_argument("--rno", type=int, choices=range(1, 13), metavar="1-12", help="limit race number")
    parser.add_argument("--details", action="store_true", help="fetch official racelist pages")
    parser.add_argument("--odds", action="store_true", help="fetch official trifecta odds pages")
    parser.add_argument("--preview", action="store_true", help="fetch official beforeinfo pages")
    parser.add_argument("--results", action="store_true", help="fetch official resultlist and raceresult pages")
    parser.add_argument("--dry-run", action="store_true", help="print planned URLs without fetching")
    parser.add_argument("--cache", action="store_true", help="accepted for CLI readability; cache is always used")
    parser.add_argument("--force", action="store_true", help="ignore cached files and refetch")
    parser.add_argument("--raw-dir", default="data/raw", help="raw cache root")
    parser.add_argument("--sleep", type=float, default=1.0, help="seconds to wait between network requests")
    parser.add_argument("--timeout", type=float, default=30.0, help="per-request timeout seconds")
    parser.add_argument("--retries", type=int, default=2, help="retry count with exponential backoff")
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT, help="explicit User-Agent")
    return parser


if __name__ == "__main__":
    raise SystemExit(run(build_parser().parse_args()))
