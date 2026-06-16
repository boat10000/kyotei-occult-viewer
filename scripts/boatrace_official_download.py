#!/usr/bin/env python3
"""Parse BOAT RACE official B/K download text files.

The official download files are local cache inputs only. This module converts
the decoded TXT files into the same normalized shape used by the screen parser.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any


JST = dt.timezone(dt.timedelta(hours=9), name="JST")

VENUE_NAMES = {
    "01": "桐生",
    "02": "戸田",
    "03": "江戸川",
    "04": "平和島",
    "05": "多摩川",
    "06": "浜名湖",
    "07": "蒲郡",
    "08": "常滑",
    "09": "津",
    "10": "三国",
    "11": "びわこ",
    "12": "住之江",
    "13": "尼崎",
    "14": "鳴門",
    "15": "丸亀",
    "16": "児島",
    "17": "宮島",
    "18": "徳山",
    "19": "下関",
    "20": "若松",
    "21": "芦屋",
    "22": "福岡",
    "23": "唐津",
    "24": "大村",
}

ASCII_TRANSLATION = str.maketrans(
    "０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ"
    "ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ：．－",
    "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz:.-",
)


def now_iso() -> str:
    return dt.datetime.now(JST).isoformat(timespec="seconds")


def normalize_date(value: str) -> tuple[str, str]:
    raw = value.strip()
    if re.fullmatch(r"\d{8}", raw):
        compact = raw
        dashed = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        dashed = raw
        compact = raw.replace("-", "")
    else:
        raise ValueError("date must be YYYY-MM-DD or YYYYMMDD")
    dt.date.fromisoformat(dashed)
    return dashed, compact


def zen_to_ascii(text: str) -> str:
    return text.translate(ASCII_TRANSLATION)


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = zen_to_ascii(value).replace("\u3000", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return text.strip()


def to_int(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if text in {"", "-", "－"}:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if text in {"", "-", "－"}:
        return None
    if text.startswith("."):
        text = "0" + text
    try:
        return float(text)
    except ValueError:
        return None


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


def empty_result() -> dict[str, Any]:
    return {
        "trifecta": None,
        "payout_yen": None,
        "popularity": None,
        "is_canceled": False,
        "refunds": [],
        "finish_order": [],
        "decision": None,
    }


def empty_race(race_no: int) -> dict[str, Any]:
    return {
        "race_no": race_no,
        "race_name": None,
        "distance_m": None,
        "deadline": None,
        "conditions": empty_conditions(),
        "weather": empty_weather(),
        "boats": [],
        "odds": {"trifecta": {}, "updated_at": None, "is_final_odds": False},
        "result": empty_result(),
    }


def grade_from_text(text: str | None) -> str | None:
    if not text:
        return None
    normalized = zen_to_ascii(text).upper()
    for grade in ["SG", "G1", "G2", "G3"]:
        if grade in normalized:
            return grade
    if "一般" in text:
        return "一般"
    return None


def split_sections(text: str, marker: str) -> list[tuple[str, str]]:
    pattern = re.compile(rf"(?ms)^(\d{{2}}){marker}\s*(.*?)(?=^\d{{2}}{marker}|^END|\Z)")
    return [(match.group(1), match.group(2)) for match in pattern.finditer(text)]


def parse_section_meta(section: str, jcd: str, kind: str) -> dict[str, Any]:
    lines = [line.strip() for line in section.splitlines() if line.strip()]
    joined = "\n".join(lines[:12])
    venue = VENUE_NAMES.get(jcd)
    if not venue and lines:
        venue_match = re.search(r"ボートレース(.+?)(?:\s|$)", joined)
        if venue_match:
            venue = clean_text(venue_match.group(1)) or venue
    if not venue and lines:
        venue = clean_text(re.sub(r"\[成績\].*", "", lines[0]))
    title = None
    for line in lines:
        if "＊＊＊" in line or "内容について" in line or "ボートレース" in line:
            continue
        if kind == "B" and "番組表" in line:
            continue
        if kind == "K" and "競走成績" in line:
            continue
        if len(line.strip()) >= 8 and not re.search(r"^\d{1,2}R|\[払戻金\]|START|END", zen_to_ascii(line)):
            title = clean_text(line)
            if title:
                break
    day_label = None
    day_match = re.search(r"第\s*([0-9０-９一二三四五六七八九十]+)\s*日", joined)
    if day_match:
        day_label = f"第{clean_text(day_match.group(1))}日"
    header_grade = None
    first_line = clean_text(lines[0]) if lines else ""
    if first_line:
        pieces = re.split(r"\s{2,}", first_line)
        header_grade = pieces[1] if len(pieces) > 1 else first_line
    return {
        "jcd": jcd,
        "name": venue,
        "grade": grade_from_text(header_grade or title),
        "title": title,
        "day_label": day_label,
        "status": "downloaded",
    }


def parse_program_boat(line: str) -> dict[str, Any] | None:
    normalized = zen_to_ascii(line).replace("\u3000", " ")
    pattern = re.compile(
        r"^\s*([1-6])\s+(\d{4})(.+?)(\d{2})([^\d\s]{2})(\d{2})([AB]\d)\s+"
        r"(\d+\.\d{2})\s+(\d+\.\d{2})\s+(\d+\.\d{2})\s+(\d+\.\d{2})\s+"
        r"(\d+)\s+(\d+\.\d{2})\s*(\d+)\s+(\d+\.\d{2})"
    )
    match = pattern.search(normalized)
    if not match:
        return None
    (
        lane,
        registration_no,
        name,
        age,
        branch,
        weight,
        racer_class,
        national_win,
        national_two,
        local_win,
        local_two,
        motor_no,
        motor_two,
        boat_no,
        boat_two,
    ) = match.groups()
    return {
        "lane": to_int(lane),
        "registration_no": registration_no,
        "class": racer_class,
        "name": clean_text(name),
        "branch": branch,
        "birthplace": None,
        "age": to_int(age),
        "weight_kg": to_float(weight),
        "f_count": None,
        "l_count": None,
        "avg_st": None,
        "national": {"win_rate": to_float(national_win), "quinella_rate": to_float(national_two), "trio_rate": None},
        "local": {"win_rate": to_float(local_win), "quinella_rate": to_float(local_two), "trio_rate": None},
        "motor": {"no": motor_no, "quinella_rate": to_float(motor_two), "trio_rate": None},
        "boat": {"no": boat_no, "quinella_rate": to_float(boat_two), "trio_rate": None},
        "preview": empty_preview(),
    }


def parse_program_races(section: str) -> list[dict[str, Any]]:
    normalized = zen_to_ascii(section)
    header_pattern = re.compile(
        r"(?m)^\s*([0-9]{1,2})R\s+(.+?)\s+H([0-9]{3,4})m\s+電話投票締切予定([0-9]{1,2}:[0-9]{2})"
    )
    matches = list(header_pattern.finditer(normalized))
    races: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        body_start = match.end()
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized)
        body = normalized[body_start:body_end]
        race_no = int(match.group(1))
        race = empty_race(race_no)
        race["race_name"] = clean_text(match.group(2))
        race["distance_m"] = to_int(match.group(3))
        race["deadline"] = match.group(4)
        body_text = clean_text(body) or ""
        race["conditions"] = {
            "fixed_entry": "進入固定" in body_text or "進入固定" in (race["race_name"] or ""),
            "stabilizer": "安定板" in body_text,
        }
        boats = []
        for line in body.splitlines():
            boat = parse_program_boat(line)
            if boat:
                boats.append(boat)
        race["boats"] = sorted(boats, key=lambda boat: boat.get("lane") or 99)
        races.append(race)
    return races


def parse_program_text(text: str) -> dict[str, Any]:
    venues: dict[str, dict[str, Any]] = {}
    for jcd, section in split_sections(text, "BBGN"):
        venue = parse_section_meta(section, jcd, "B")
        venue["races"] = parse_program_races(section)
        venues[jcd] = venue
    return venues


def parse_result_row(line: str) -> dict[str, Any] | None:
    normalized = zen_to_ascii(line).replace("\u3000", " ")
    pattern = re.compile(
        r"^\s*(\d{2}|F|L|S[0-9]?|K[0-9]?|欠|妨|転|落|失)\s+([1-6])\s+(\d{4})\s+(.+?)\s+"
        r"(\d+)\s+(\d+)\s+(\d+\.\d{2})\s+([1-6])\s+([FL]?\d+\.\d{2}|[FL]\d+\.\d{2})"
    )
    match = pattern.search(normalized)
    if not match:
        return None
    rank, lane, registration_no, name, motor_no, boat_no, exhibition, entry, st = match.groups()
    st_label = st
    is_refund = st_label.startswith(("F", "L")) or rank in {"F", "L"}
    st_value = to_float(st_label.lstrip("FL"))
    return {
        "finish": to_int(rank) if rank.isdigit() else rank,
        "lane": to_int(lane),
        "registration_no": registration_no,
        "name": clean_text(name),
        "motor_no": motor_no,
        "boat_no": boat_no,
        "exhibition_time": to_float(exhibition),
        "exhibition_entry": to_int(entry),
        "start_timing": st_value,
        "start_timing_raw": st_label,
        "is_refund": is_refund,
    }


def parse_result_races(section: str) -> dict[int, dict[str, Any]]:
    normalized = zen_to_ascii(section)
    header_pattern = re.compile(
        r"(?m)^\s*([0-9]{1,2})R\s+(.+?)\s+H([0-9]{3,4})m\s+(\S+)\s+風\s+(.+?)\s+([0-9]+)m\s+波\s+([0-9]+)cm"
    )
    matches = list(header_pattern.finditer(normalized))
    results: dict[int, dict[str, Any]] = {}
    for index, match in enumerate(matches):
        body_start = match.end()
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized)
        body = normalized[body_start:body_end]
        race_no = int(match.group(1))
        decision = None
        decision_match = re.search(r"ﾚｰｽﾀｲﾑ\s+(.+?)\s*$", body, re.M)
        if decision_match:
            decision = clean_text(decision_match.group(1))
        payout_match = re.search(r"[3３]連単\s+([1-6]-[1-6]-[1-6])\s+(\d+)\s+人気\s+(\d+)", body)
        rows = [row for row in (parse_result_row(line) for line in body.splitlines()) if row]
        refunds = sorted({str(row["lane"]) for row in rows if row.get("is_refund") and row.get("lane")})
        finish_order = [
            {"finish": row["finish"], "lane": row["lane"], "registration_no": row["registration_no"]}
            for row in rows
            if isinstance(row.get("finish"), int)
        ]
        results[race_no] = {
            "race_no": race_no,
            "race_name": clean_text(match.group(2)),
            "distance_m": to_int(match.group(3)),
            "weather": {
                "weather": clean_text(match.group(4)),
                "wind_direction": clean_text(match.group(5)),
                "wind_speed_m": to_float(match.group(6)),
                "wave_cm": to_float(match.group(7)),
                "air_temp_c": None,
                "water_temp_c": None,
            },
            "rows": rows,
            "result": {
                "trifecta": payout_match.group(1) if payout_match else None,
                "payout_yen": to_int(payout_match.group(2)) if payout_match else None,
                "popularity": to_int(payout_match.group(3)) if payout_match else None,
                "is_canceled": any(word in body for word in ["中止", "不成立"]),
                "refunds": refunds,
                "finish_order": finish_order,
                "decision": decision,
            },
        }
    return results


def parse_result_text(text: str) -> dict[str, dict[int, dict[str, Any]]]:
    venues: dict[str, dict[int, dict[str, Any]]] = {}
    for jcd, section in split_sections(text, "KBGN"):
        venues[jcd] = parse_result_races(section)
    return venues


def get_any(obj: dict[str, Any], names: list[str], default: Any = None) -> Any:
    for name in names:
        if name in obj and obj[name] not in (None, ""):
            return obj[name]
    return default


def normalize_deadline(value: Any) -> str | None:
    if value in (None, ""):
        return None
    match = re.search(r"(\d{1,2}):(\d{2})", str(value))
    if not match:
        return None
    return f"{int(match.group(1)):02d}:{match.group(2)}"


def augment_with_openapi_programs(venues: dict[str, dict[str, Any]], raw_dir: Path) -> list[str]:
    path = raw_dir / "openapi_programs.json"
    if not path.exists():
        return []
    notes = ["BoatraceOpenAPI v3 programs used as non-official augmentation"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ["openapi_programs.json could not be decoded"]
    programs = payload.get("programs") if isinstance(payload, dict) else None
    if not isinstance(programs, list):
        return ["openapi_programs.json did not contain a programs list"]
    by_key: dict[tuple[str, int], dict[str, Any]] = {}
    for program in programs:
        if not isinstance(program, dict):
            continue
        jcd = str(get_any(program, ["stadium_number", "race_stadium_number", "jcd"], "")).zfill(2)
        race_no = to_int(get_any(program, ["race_number", "number", "race_no"]))
        if jcd and race_no:
            by_key[(jcd, race_no)] = program
    for venue in venues.values():
        jcd = venue.get("jcd")
        for race in venue.get("races", []):
            program = by_key.get((jcd, race.get("race_no")))
            if not program:
                continue
            venue["grade"] = get_any(program, ["grade_label", "grade"], venue.get("grade"))
            venue["title"] = get_any(program, ["title"], venue.get("title"))
            venue["day_label"] = get_any(program, ["day_label"], venue.get("day_label"))
            race["race_name"] = get_any(program, ["race_name", "name"], race.get("race_name"))
            race["deadline"] = normalize_deadline(get_any(program, ["closed_at", "deadline"])) or race.get("deadline")
            race["distance_m"] = to_int(get_any(program, ["distance"], race.get("distance_m"))) or race.get("distance_m")
    return notes


def merge_results(venues: dict[str, dict[str, Any]], result_by_venue: dict[str, dict[int, dict[str, Any]]]) -> None:
    for jcd, races in result_by_venue.items():
        venue = venues.setdefault(
            jcd,
            {
                "jcd": jcd,
                "name": VENUE_NAMES.get(jcd),
                "grade": None,
                "title": None,
                "day_label": None,
                "status": "downloaded",
                "races": [],
            },
        )
        by_no = {race.get("race_no"): race for race in venue.get("races", [])}
        for race_no, parsed in races.items():
            race = by_no.get(race_no)
            if not race:
                race = empty_race(race_no)
                race["race_name"] = parsed.get("race_name")
                race["distance_m"] = parsed.get("distance_m")
                venue["races"].append(race)
                by_no[race_no] = race
            race["weather"] = parsed.get("weather", empty_weather())
            race["result"] = parsed.get("result", empty_result())
            rows_by_lane = {row["lane"]: row for row in parsed.get("rows", []) if row.get("lane")}
            boats_by_lane = {boat.get("lane"): boat for boat in race.get("boats", [])}
            for lane, row in rows_by_lane.items():
                boat = boats_by_lane.get(lane)
                if not boat:
                    boat = {
                        "lane": lane,
                        "registration_no": row.get("registration_no"),
                        "class": None,
                        "name": row.get("name"),
                        "branch": None,
                        "birthplace": None,
                        "age": None,
                        "weight_kg": None,
                        "f_count": None,
                        "l_count": None,
                        "avg_st": None,
                        "national": {"win_rate": None, "quinella_rate": None, "trio_rate": None},
                        "local": {"win_rate": None, "quinella_rate": None, "trio_rate": None},
                        "motor": {"no": row.get("motor_no"), "quinella_rate": None, "trio_rate": None},
                        "boat": {"no": row.get("boat_no"), "quinella_rate": None, "trio_rate": None},
                        "preview": empty_preview(),
                    }
                    race["boats"].append(boat)
                    boats_by_lane[lane] = boat
                boat["preview"]["exhibition_time"] = row.get("exhibition_time")
                boat["preview"]["exhibition_entry"] = row.get("exhibition_entry")
                boat["preview"]["exhibition_st"] = row.get("start_timing")
    for venue in venues.values():
        venue["races"].sort(key=lambda race: race.get("race_no") or 99)
        for race in venue["races"]:
            race["boats"].sort(key=lambda boat: boat.get("lane") or 99)


def normalized_from_download(raw_dir: Path, date_dash: str) -> dict[str, Any] | None:
    program_path = raw_dir / "official_download_b.txt"
    result_path = raw_dir / "official_download_k.txt"
    if not program_path.exists() and not result_path.exists():
        return None
    notes: list[str] = []
    venues: dict[str, dict[str, Any]] = {}
    if program_path.exists():
        venues.update(parse_program_text(program_path.read_text(encoding="utf-8", errors="replace")))
    else:
        notes.append("official_download_b.txt not found")
    if result_path.exists():
        merge_results(venues, parse_result_text(result_path.read_text(encoding="utf-8", errors="replace")))
    else:
        notes.append("official_download_k.txt not found")
    notes.extend(augment_with_openapi_programs(venues, raw_dir))
    return {
        "date": date_dash,
        "source": {
            "official": True,
            "fetched_at": now_iso(),
            "notes": notes,
            "raw_manifest_entries": 0,
            "primary": "official_download",
        },
        "venues": sorted(venues.values(), key=lambda venue: venue.get("jcd") or ""),
    }
