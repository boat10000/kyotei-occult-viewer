#!/usr/bin/env python3
"""Normalize cached BOAT RACE official pages into data/normalized/YYYYMMDD.json."""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
from pathlib import Path
from typing import Any


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


def now_iso() -> str:
    return dt.datetime.now(JST).isoformat(timespec="seconds")


def clean_text(fragment: str) -> str:
    text = re.sub(r"(?i)<br\s*/?>", "\n", fragment)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text).replace("\xa0", " ")
    text = text.replace("\u3000", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*", "\n", text)
    return text.strip()


def flat_text(fragment: str) -> str:
    return re.sub(r"\s+", " ", clean_text(fragment).replace("\n", " ")).strip()


def to_int(value: str | None) -> int | None:
    if value is None:
        return None
    value = value.strip().replace(",", "")
    if value in {"", "-", "－"}:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def to_float(value: str | None) -> float | None:
    if value is None:
        return None
    value = value.strip().replace(",", "")
    if value in {"", "-", "－"}:
        return None
    if value.startswith("."):
        value = "0" + value
    try:
        return float(value)
    except ValueError:
        return None


def first(patterns: list[str], text: str, flags: int = re.S) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags)
        if match:
            return match.group(1)
    return None


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


def parse_index(index_html: str) -> list[dict[str, Any]]:
    venues: list[dict[str, Any]] = []
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
        name = first([r'text_place1_\d+\.png"[^>]*alt="([^"]+)"'], block)
        title = first(
            [r'<a href="/owpc/pc/race/raceindex\?jcd=' + re.escape(jcd) + r"&amp;hd=\d{8}\">(.*?)</a>"],
            block,
        )
        class_values = " ".join(re.findall(r'class="([^"]+)"', block))
        text = flat_text(block)
        day_label = first([r"\d{1,2}/\d{1,2}-\d{1,2}/\d{1,2}\s*(初日|最終日|\S+日)"], text, 0)
        status_match = re.search(r"(?is)<td[^>]*colspan=\"3\"[^>]*>(.*?)</td>", block)
        status = flat_text(status_match.group(1)) if status_match else None
        if not status:
            for candidate in ["発売中", "発売締切", "最終Ｒ発売終了", "中止", "順延"]:
                if candidate in text:
                    status = candidate
                    break
        venues.append(
            {
                "jcd": jcd,
                "name": html.unescape(name) if name else None,
                "grade": grade_from_classes(class_values),
                "title": flat_text(title) if title else None,
                "day_label": day_label,
                "status": status,
                "races": [],
            }
        )
    return venues


def empty_weather() -> dict[str, Any]:
    return {
        "weather": None,
        "wind_direction": None,
        "wind_speed_m": None,
        "wave_cm": None,
        "air_temp_c": None,
        "water_temp_c": None,
    }


def empty_conditions() -> dict[str, bool]:
    return {"fixed_entry": False, "stabilizer": False}


def empty_preview() -> dict[str, Any]:
    return {
        "exhibition_time": None,
        "tilt": None,
        "adjust_weight": None,
        "parts_changed": [],
        "exhibition_entry": None,
        "exhibition_st": None,
    }


def parse_stat_triplet(text: str) -> tuple[float | None, float | None, float | None]:
    values = [piece.strip() for piece in clean_text(text).splitlines() if piece.strip()]
    values = [re.sub(r"[^\d.\-]", "", value) for value in values]
    return (
        to_float(values[0]) if len(values) > 0 else None,
        to_float(values[1]) if len(values) > 1 else None,
        to_float(values[2]) if len(values) > 2 else None,
    )


def parse_boat_block(block: str) -> dict[str, Any] | None:
    cells = re.findall(r"(?is)<td[^>]*rowspan=\"4\"[^>]*>(.*?)</td>", block)
    if len(cells) < 8 or "profile?toban=" not in block:
        return None
    lane = to_int(clean_text(cells[0]))
    info = cells[2]
    reg = first([r"profile\?toban=(\d+)"], info) or first([r"\b(\d{4})\b"], clean_text(info), 0)
    racer_class = first([r"/\s*<span[^>]*>\s*([AB]\d)\s*</span>"], info)
    name = first([r"(?is)<div[^>]*is-fs18[^>]*>.*?<a[^>]*>(.*?)</a>"], info)
    info_lines = [line.strip() for line in clean_text(info).splitlines() if line.strip()]
    branch = birthplace = None
    age = None
    weight = None
    for line in info_lines:
        if "歳" in line or "kg" in line:
            branch_match = None
        else:
            branch_match = re.search(r"([^/\s]+)/([^\s/]+)", line)
        if branch_match:
            branch = branch_match.group(1)
            birthplace = branch_match.group(2)
        age_weight = re.search(r"(\d+)歳/([\d.]+)kg", line)
        if age_weight:
            age = to_int(age_weight.group(1))
            weight = to_float(age_weight.group(2))

    flst_lines = [line.strip() for line in clean_text(cells[3]).splitlines() if line.strip()]
    f_count = to_int(flst_lines[0].lstrip("F")) if len(flst_lines) > 0 else None
    l_count = to_int(flst_lines[1].lstrip("L")) if len(flst_lines) > 1 else None
    avg_st = to_float(flst_lines[2]) if len(flst_lines) > 2 else None
    national = parse_stat_triplet(cells[4])
    local = parse_stat_triplet(cells[5])
    motor = parse_stat_triplet(cells[6])
    boat = parse_stat_triplet(cells[7])

    return {
        "lane": lane,
        "registration_no": reg,
        "class": racer_class,
        "name": flat_text(name) if name else None,
        "branch": branch,
        "birthplace": birthplace,
        "age": age,
        "weight_kg": weight,
        "f_count": f_count,
        "l_count": l_count,
        "avg_st": avg_st,
        "national": {"win_rate": national[0], "quinella_rate": national[1], "trio_rate": national[2]},
        "local": {"win_rate": local[0], "quinella_rate": local[1], "trio_rate": local[2]},
        "motor": {"no": str(to_int(clean_text(cells[6]).splitlines()[0])) if clean_text(cells[6]).splitlines() else None, "quinella_rate": motor[1], "trio_rate": motor[2]},
        "boat": {"no": str(to_int(clean_text(cells[7]).splitlines()[0])) if clean_text(cells[7]).splitlines() else None, "quinella_rate": boat[1], "trio_rate": boat[2]},
        "preview": empty_preview(),
    }


def parse_racelist(html_text: str, jcd: str, race_no: int) -> dict[str, Any]:
    text = flat_text(html_text)
    race_name = first(
        [
            r'<h3 class="title16_titleDetail__add2020">\s*([^<]+?)\s*\d{4}m',
            r'<span class="title2_mainLabel">([^<]+)</span>',
            r'<h3[^>]*class="[^"]*title2_title[^"]*"[^>]*>\s*<span[^>]*>(.*?)</span>',
        ],
        html_text,
    )
    if race_name and "月" in race_name and "日" in race_name:
        race_name = None
    deadline = first(
        [
            r"締切予定時刻[^0-9]*(\d{1,2}:\d{2})",
            r"締切[^0-9]*(\d{1,2}:\d{2})",
        ],
        text,
        0,
    )
    distance = to_int(first([r"(\d{4})m"], text, 0))
    boats = []
    for block in re.findall(r"(?is)<tbody[^>]*class=\"[^\"]*is-fs12[^\"]*\"[^>]*>(.*?)</tbody>", html_text):
        boat = parse_boat_block(block)
        if boat:
            boats.append(boat)
    boats.sort(key=lambda item: item.get("lane") or 99)
    return {
        "race_no": race_no,
        "race_name": flat_text(race_name) if race_name else None,
        "distance_m": distance,
        "deadline": deadline,
        "conditions": {
            "fixed_entry": "進入固定" in text,
            "stabilizer": "安定板" in text,
        },
        "weather": empty_weather(),
        "boats": boats,
        "odds": {"trifecta": {}, "updated_at": None, "is_final_odds": False},
        "result": {"trifecta": None, "payout_yen": None, "popularity": None, "is_canceled": "中止" in text, "refunds": []},
    }


def parse_result(html_text: str) -> dict[str, Any]:
    text = flat_text(html_text)
    is_canceled = any(word in text for word in ["中止", "不成立"])
    segment = ""
    for tbody in re.findall(r"(?is)<tbody[^>]*>(.*?)</tbody>", html_text):
        if "3連単" in tbody:
            segment = flat_text(tbody)
            break
    if not segment:
        match = re.search(r"(?is)3連単(.{0,1600}?)(?:3連複|2連単|拡連複|単勝|複勝|</table>)", html_text)
        if match:
            segment = flat_text(match.group(1))
        else:
            idx = text.find("3連単")
            segment = text[idx : idx + 500] if idx >= 0 else text[:500]

    combination = None
    combo_match = re.search(r"([1-6])\s*[-－]\s*([1-6])\s*[-－]\s*([1-6])", segment)
    if not combo_match:
        combo_match = re.search(r"\b([1-6])\s+([1-6])\s+([1-6])\b", segment)
    if combo_match:
        combination = "-".join(combo_match.groups())
    payout = None
    payout_match = re.search(r"(?:[¥￥]\s*|&yen;\s*)([\d,]+)", segment)
    if not payout_match:
        payout_match = re.search(r"([\d,]+)\s*円", segment)
    if payout_match:
        payout = to_int(payout_match.group(1))
    popularity = None
    pop_match = re.search(r"(\d+)\s*人気", segment)
    if not pop_match:
        pop_match = re.search(r"[¥￥]\s*[\d,]+\s+(\d+)\b", segment)
    if pop_match:
        popularity = to_int(pop_match.group(1))
    refunds: list[str] = []
    refund_match = re.search(r"返還(?:艇番)?\s*([1-6,\s]+)", text)
    if refund_match:
        refunds = re.findall(r"[1-6]", refund_match.group(1))
    return {
        "trifecta": combination,
        "payout_yen": payout,
        "popularity": popularity,
        "is_canceled": is_canceled,
        "refunds": refunds,
    }


def parse_preview(html_text: str) -> dict[str, Any]:
    text = flat_text(html_text)
    weather = empty_weather()
    weather["weather"] = first(
        [
            r'weather1_bodyUnit is-weather.*?<span class="weather1_bodyUnitLabelTitle">([^<]+)</span>',
            r"天候\s*([^\s]+)",
        ],
        html_text,
    )
    weather["wind_speed_m"] = to_float(first([r"風速\s*([\d.]+)m"], text, 0))
    weather["wave_cm"] = to_float(first([r"波高\s*([\d.]+)cm"], text, 0))
    weather["air_temp_c"] = to_float(first([r"気温\s*([\d.]+)℃"], text, 0))
    weather["water_temp_c"] = to_float(first([r"水温\s*([\d.]+)℃"], text, 0))
    wind_direction = first([r"風向\s*([^\s]+)", r"weather1_bodyUnitImage (is-wind\d+)"], html_text)
    weather["wind_direction"] = wind_direction
    previews: dict[int, dict[str, Any]] = {}
    for lane in range(1, 7):
        previews[lane] = empty_preview()
    for block in re.findall(r"(?is)<tbody[^>]*>(.*?)</tbody>", html_text):
        lane_match = re.search(r"is-boatColor([1-6])", block)
        if not lane_match:
            continue
        lane = int(lane_match.group(1))
        cells = re.findall(r"(?is)<td[^>]*rowspan=\"(?:2|4)\"[^>]*>(.*?)</td>", block)
        if len(cells) >= 6:
            previews[lane]["exhibition_time"] = to_float(clean_text(cells[4]))
            previews[lane]["tilt"] = to_float(clean_text(cells[5]))
        if len(cells) >= 8:
            parts = [part for part in re.split(r"\s+", flat_text(cells[7])) if part and part != "-"]
            previews[lane]["parts_changed"] = parts
        if len(cells) >= 9:
            previews[lane]["adjust_weight"] = to_float(clean_text(cells[8]))
    entry_order = 0
    for block in re.findall(r"(?is)<div class=\"table1_boatImage1\">(.*?)</div>", html_text):
        lane_match = re.search(r"table1_boatImage1Number is-type([1-6])\">([1-6])</span>", block)
        st_match = re.search(r"table1_boatImage1Time\">([^<]+)</span>", block)
        if lane_match:
            entry_order += 1
            lane = int(lane_match.group(2))
            previews[lane]["exhibition_entry"] = entry_order
            if st_match:
                previews[lane]["exhibition_st"] = to_float(st_match.group(1))
    return {"weather": weather, "previews": previews}


def parse_odds(html_text: str) -> dict[str, Any]:
    text = flat_text(html_text)
    odds: dict[str, float | None] = {}
    header_match = re.search(r"(?is)<thead[^>]*class=\"[^\"]*is-p15-7[^\"]*\"[^>]*>(.*?)</thead>", html_text)
    first_lanes: list[str] = []
    if header_match:
        first_lanes = re.findall(r"is-boatColor([1-6])\">([1-6])</th>", header_match.group(1))
        first_lanes = [lane for _class_lane, lane in first_lanes]
    current_seconds: list[str | None] = [None] * len(first_lanes)
    body_match = re.search(r"(?is)<tbody[^>]*class=\"[^\"]*is-p3-0[^\"]*\"[^>]*>(.*?)</tbody>", html_text)
    if first_lanes and body_match:
        for row in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", body_match.group(1)):
            cells = re.findall(r"(?is)<td([^>]*)>(.*?)</td>", row)
            cursor = 0
            for group_index, first_lane in enumerate(first_lanes):
                if cursor >= len(cells):
                    break
                attrs, value = cells[cursor]
                if "rowspan" in attrs and "oddsPoint" not in attrs:
                    current_seconds[group_index] = flat_text(value)
                    cursor += 1
                    if cursor >= len(cells):
                        break
                    attrs, value = cells[cursor]
                third = flat_text(value)
                cursor += 1
                if cursor >= len(cells):
                    break
                _odds_attrs, odds_value = cells[cursor]
                cursor += 1
                second = current_seconds[group_index]
                if first_lane and second and third:
                    key = f"{first_lane}-{second}-{third}"
                    if len(set(key.split("-"))) == 3:
                        odds[key] = to_float(flat_text(odds_value))
    if not odds:
        for match in re.finditer(r"([1-6])\s*[-－]\s*([1-6])\s*[-－]\s*([1-6])\s+([\d.]+)", text):
            key = "-".join(match.groups()[:3])
            odds[key] = to_float(match.group(4))
    is_final = "最終オッズ" in text or "確定オッズ" in text
    updated_at = first([r"更新時間\s*(\d{1,2}:\d{2})", r"更新時刻\s*(\d{1,2}:\d{2})"], text, 0)
    return {"trifecta": odds, "updated_at": updated_at, "is_final_odds": is_final}


def load_manifest(raw_dir: Path) -> dict[str, Any]:
    path = raw_dir / "manifest.json"
    if not path.exists():
        return {"entries": []}
    return json.loads(path.read_text(encoding="utf-8"))


def race_key(jcd: str, rno: int) -> tuple[str, int]:
    return jcd, rno


def ensure_venue(venues_by_jcd: dict[str, dict[str, Any]], jcd: str) -> dict[str, Any]:
    if jcd not in venues_by_jcd:
        venues_by_jcd[jcd] = {
            "jcd": jcd,
            "name": None,
            "grade": None,
            "title": None,
            "day_label": None,
            "status": None,
            "races": [],
        }
    return venues_by_jcd[jcd]


def normalize(args: argparse.Namespace) -> dict[str, Any]:
    date_dash, date_compact = normalize_date(args.date)
    raw_dir = Path(args.raw_dir) / date_compact
    manifest = load_manifest(raw_dir)
    source_notes: list[str] = []
    entries = manifest.get("entries", [])
    index_path = raw_dir / "official_index.html"
    venues = parse_index(index_path.read_text(encoding="utf-8", errors="replace")) if index_path.exists() else []
    if not venues:
        source_notes.append("official_index.html not found or no venues parsed")
    venues_by_jcd = {venue["jcd"]: venue for venue in venues if venue.get("jcd")}
    races_by_key: dict[tuple[str, int], dict[str, Any]] = {}

    for path in sorted(raw_dir.glob("official_racelist_*_*.html")):
        match = re.search(r"official_racelist_(\d{2})_(\d{2})\.html$", path.name)
        if not match:
            continue
        jcd, rno_s = match.group(1), match.group(2)
        race = parse_racelist(path.read_text(encoding="utf-8", errors="replace"), jcd, int(rno_s))
        races_by_key[race_key(jcd, int(rno_s))] = race
        ensure_venue(venues_by_jcd, jcd)

    for path in sorted(raw_dir.glob("official_beforeinfo_*_*.html")):
        match = re.search(r"official_beforeinfo_(\d{2})_(\d{2})\.html$", path.name)
        if not match:
            continue
        jcd, rno = match.group(1), int(match.group(2))
        race = races_by_key.setdefault(
            race_key(jcd, rno),
            {
                "race_no": rno,
                "race_name": None,
                "distance_m": None,
                "deadline": None,
                "conditions": empty_conditions(),
                "weather": empty_weather(),
                "boats": [],
                "odds": {"trifecta": {}, "updated_at": None, "is_final_odds": False},
                "result": {"trifecta": None, "payout_yen": None, "popularity": None, "is_canceled": False, "refunds": []},
            },
        )
        parsed = parse_preview(path.read_text(encoding="utf-8", errors="replace"))
        race["weather"] = parsed["weather"]
        for boat in race.get("boats", []):
            lane = boat.get("lane")
            if lane in parsed["previews"]:
                boat["preview"].update(parsed["previews"][lane])

    for path in sorted(raw_dir.glob("official_odds3t_*_*.html")):
        match = re.search(r"official_odds3t_(\d{2})_(\d{2})\.html$", path.name)
        if not match:
            continue
        jcd, rno = match.group(1), int(match.group(2))
        race = races_by_key.setdefault(
            race_key(jcd, rno),
            {
                "race_no": rno,
                "race_name": None,
                "distance_m": None,
                "deadline": None,
                "conditions": empty_conditions(),
                "weather": empty_weather(),
                "boats": [],
                "odds": {"trifecta": {}, "updated_at": None, "is_final_odds": False},
                "result": {"trifecta": None, "payout_yen": None, "popularity": None, "is_canceled": False, "refunds": []},
            },
        )
        race["odds"] = parse_odds(path.read_text(encoding="utf-8", errors="replace"))

    for path in sorted(raw_dir.glob("official_raceresult_*_*.html")):
        match = re.search(r"official_raceresult_(\d{2})_(\d{2})\.html$", path.name)
        if not match:
            continue
        jcd, rno = match.group(1), int(match.group(2))
        race = races_by_key.setdefault(
            race_key(jcd, rno),
            {
                "race_no": rno,
                "race_name": None,
                "distance_m": None,
                "deadline": None,
                "conditions": empty_conditions(),
                "weather": empty_weather(),
                "boats": [],
                "odds": {"trifecta": {}, "updated_at": None, "is_final_odds": False},
                "result": {"trifecta": None, "payout_yen": None, "popularity": None, "is_canceled": False, "refunds": []},
            },
        )
        race["result"] = parse_result(path.read_text(encoding="utf-8", errors="replace"))
        ensure_venue(venues_by_jcd, jcd)

    for (jcd, _rno), race in sorted(races_by_key.items()):
        venue = ensure_venue(venues_by_jcd, jcd)
        venue["races"].append(race)

    for venue in venues_by_jcd.values():
        venue["races"].sort(key=lambda race: race.get("race_no") or 99)

    return {
        "date": date_dash,
        "source": {
            "official": True,
            "fetched_at": manifest.get("fetched_at") or now_iso(),
            "notes": source_notes,
            "raw_manifest_entries": len(entries),
        },
        "venues": sorted(venues_by_jcd.values(), key=lambda venue: venue.get("jcd") or ""),
    }


def run(args: argparse.Namespace) -> int:
    _date_dash, date_compact = normalize_date(args.date)
    normalized = normalize(args)
    output = Path(args.output) if args.output else Path(args.output_dir) / f"{date_compact}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {output}")
    print(f"venues={len(normalized['venues'])} races={sum(len(v['races']) for v in normalized['venues'])}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="JST date as YYYY-MM-DD or YYYYMMDD")
    parser.add_argument("--raw-dir", default="data/raw", help="raw cache root")
    parser.add_argument("--output-dir", default="data/normalized", help="normalized output root")
    parser.add_argument("--output", help="explicit output file")
    return parser


if __name__ == "__main__":
    raise SystemExit(run(build_parser().parse_args()))
