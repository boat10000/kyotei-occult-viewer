#!/usr/bin/env python3
import argparse
import json
import sqlite3
import ssl
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "data" / "output"
DB_PATH = OUTPUT_DIR / "boaters_all_races.sqlite"
GRAPHQL_URL = "https://api.boaters-boatrace.com/graphql"
START_DATE = "2014-01-01"
END_DATE = "2026-06-18"
BOATERS_VERSION = "2026-06-11-88d49e"

try:
    import certifi

    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except Exception:
    SSL_CONTEXT = ssl.create_default_context()

PLACE_NAMES = {
    1: "桐生",
    2: "戸田",
    3: "江戸川",
    4: "平和島",
    5: "多摩川",
    6: "浜名湖",
    7: "蒲郡",
    8: "常滑",
    9: "津",
    10: "三国",
    11: "びわこ",
    12: "住之江",
    13: "尼崎",
    14: "鳴門",
    15: "丸亀",
    16: "児島",
    17: "宮島",
    18: "徳山",
    19: "下関",
    20: "若松",
    21: "芦屋",
    22: "福岡",
    23: "唐津",
    24: "大村",
}

PLACE_SLUGS = {
    1: "kiryu",
    2: "toda",
    3: "edogawa",
    4: "heiwajima",
    5: "tamagawa",
    6: "hamanako",
    7: "gamagori",
    8: "tokoname",
    9: "tsu",
    10: "mikuni",
    11: "biwako",
    12: "suminoe",
    13: "amagasaki",
    14: "naruto",
    15: "marugame",
    16: "kojima",
    17: "miyajima",
    18: "tokuyama",
    19: "shimonoseki",
    20: "wakamatsu",
    21: "ashiya",
    22: "fukuoka",
    23: "karatsu",
    24: "omura",
}

LIST_QUERY = """
query FetchRaceDaysForDate($date: ISO8601Date!) {
  raceDaysForDate(date: $date) {
    id
    setsuId
    statusText
    dayNumber
    date
    setsu {
      id
      raceKind
      place
      category
      title
      firstDate
      lastDate
    }
    races {
      id
      raceId
      round
      deadlineTime
      raceGrade
      result {
        id
        isSuspended
      }
    }
  }
}
"""

RACE_FRAGMENT = """
id
raceId
round
title
raceGrade
deadlineTime
sinnyuMethod
isAdvertised
raceDay {
  id
  date
  setsu {
    id
    place
    raceKind
    category
    title
    firstDate
    lastDate
  }
}
racers {
  id
  isAbsent
  boatNumber
  regN
  rank
  name
}
racerOddsProba {
  raceId
  racerAiProba1
  racerAiProba2
  racerAiProba3
  racerAiProba4
  racerAiProba5
  racerAiProba6
  racerOddsProba1
  racerOddsProba2
  racerOddsProba3
  racerOddsProba4
  racerOddsProba5
  racerOddsProba6
}
aiProba {
  raceId
  aiProbaRacer13ren
  aiProbaRacer23ren
  aiProbaRacer33ren
  aiProbaRacer43ren
  aiProbaRacer53ren
  aiProbaRacer63ren
}
wakuAggregations(boatNumbers: [1, 2, 3, 4, 5, 6]) {
  raceId
  aggType
  waku
  shinnyu
  raceCntWithWaku
  resultIs1AvgWithWaku
  resultIs2AvgWithWaku
  resultIs3AvgWithWaku
  result3renAvgWithWaku
  result3renCntWithWaku
}
startAggregations(boatNumbers: [1, 2, 3, 4, 5, 6]) {
  id
  aggType
  waku
  shinnyu
  startTimeAvgWithWaku
  startTimeRankAvgWithWaku
}
winMethodAggregations(boatNumbers: [1, 2, 3, 4, 5, 6]) {
  aggregationRange
  makurareRate
  makuriRate
  makurizasareRate
  makurizashiRate
  nigashiRate
  nigeRate
  raceCountWithWaku
  raceDate
  raceId
  racerRegN
  sasareRate
  sashiRate
  waku
  shinnyu
}
beforeInfo {
  id
  weatherDegree
  weather
  windSpeed
  windDirection
  waterDegree
  waveHeight
  racers {
    id
    startSinnyu
    startTenjiTime
    boatNumber
    partsExchange
    pera
    startTenjiRank
    tenjiRank
    tenjiTime
    tilt
    weight
    weightAdjust
  }
}
originalTenjis {
  id
  boatNumber
  chokusenTime
  hanshuTime
  isshuTime
  mawariashiTime
}
result {
  id
  raceDate
  place
  round
  isSuspended
  winMethod
  weatherDegree
  weather
  windSpeed
  windDirection
  waterDegree
  waveHeight
  resultPayout3t1
  resultPayout3f1
  resultPayout2t1
  resultPayout2f1
  resultPayoutW1
  resultPayout1t1
  resultPayout1f1
  winningNumber3t1
  winningNumber3f1
  winningNumber2t1
  winningNumber2f1
  winningNumber1t1
  winningNumber1f1
  racers {
    id
    isAbsent
    startSinnyu
    startFlying
    chakuPosition
    chakuOrder
    startTime
    winMethod
    resultTime
    henkan
    deokure
    boatNumber
  }
}
"""


def pct(value):
    if value is None:
        return None
    return round(float(value) * 100, 4)


def bool_int(value):
    if value is None:
        return None
    return 1 if bool(value) else 0


def daterange(start, end):
    current = date.fromisoformat(start)
    last = date.fromisoformat(end)
    while current <= last:
        yield current.isoformat()
        current += timedelta(days=1)


def gql_request(query, variables, operation_name, session_id, retries=4):
    body = json.dumps(
        {
            "operationName": operation_name,
            "variables": variables,
            "query": query,
        }
    ).encode("utf-8")
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Content-Type": "application/json",
        "Accept": "*/*",
        "X-BOATERS-VERSION": BOATERS_VERSION,
        "X-BOATERS-SESSION-ID": session_id,
    }
    last_error = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(GRAPHQL_URL, data=body, headers=headers)
            with urllib.request.urlopen(request, timeout=60, context=SSL_CONTEXT) as response:
                data = json.loads(response.read().decode("utf-8"))
            if data.get("errors"):
                raise RuntimeError(json.dumps(data["errors"], ensure_ascii=False))
            return data.get("data") or {}
        except (urllib.error.URLError, TimeoutError, RuntimeError) as exc:
            last_error = exc
            time.sleep(min(2 ** attempt, 12))
    raise RuntimeError(str(last_error))


def race_day_query(rounds):
    aliases = []
    for round_no in sorted(rounds):
        aliases.append(
            f"r{round_no}: raceRoundDetail(date: $date, locationId: $locationId, round: {round_no}) {{ {RACE_FRAGMENT} }}"
        )
    return "query RaceDayAll($date: ISO8601Date!, $locationId: Int!) {\n" + "\n".join(aliases) + "\n}"


def race_date_query(races):
    aliases = []
    for item in races:
        place_id = int(item["place_id"])
        round_no = int(item["round"])
        race_date = item["date"]
        aliases.append(
            f"p{place_id}r{round_no}: raceRoundDetail(date: \"{race_date}\", locationId: {place_id}, round: {round_no}) {{ {RACE_FRAGMENT} }}"
        )
    return "query RaceDateAll {\n" + "\n".join(aliases) + "\n}"


def connect(db_path):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init_db(con):
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS metadata (
          key TEXT PRIMARY KEY,
          value TEXT
        );

        CREATE TABLE IF NOT EXISTS race_days (
          date TEXT NOT NULL,
          place_id INTEGER NOT NULL,
          place_name TEXT,
          slug TEXT,
          race_day_id TEXT,
          setsu_id TEXT,
          status_text TEXT,
          day_number INTEGER,
          race_kind TEXT,
          category TEXT,
          series_title TEXT,
          series_first_date TEXT,
          series_last_date TEXT,
          indexed_at TEXT,
          PRIMARY KEY (date, place_id)
        );

        CREATE TABLE IF NOT EXISTS race_day_races (
          date TEXT NOT NULL,
          place_id INTEGER NOT NULL,
          round INTEGER NOT NULL,
          crawled_race_id TEXT,
          race_id TEXT,
          deadline_time TEXT,
          race_grade TEXT,
          result_id TEXT,
          is_suspended INTEGER,
          detail_status TEXT DEFAULT 'pending',
          detail_error TEXT,
          detail_fetched_at TEXT,
          PRIMARY KEY (date, place_id, round)
        );

        CREATE TABLE IF NOT EXISTS races (
          race_id TEXT PRIMARY KEY,
          crawled_race_id TEXT,
          date TEXT,
          place_id INTEGER,
          place_name TEXT,
          slug TEXT,
          round INTEGER,
          title TEXT,
          race_grade TEXT,
          deadline_time TEXT,
          sinnyu_method TEXT,
          is_advertised INTEGER,
          race_kind TEXT,
          category TEXT,
          series_title TEXT,
          series_first_date TEXT,
          series_last_date TEXT,
          is_suspended INTEGER,
          result_win_method TEXT,
          weather_degree REAL,
          weather TEXT,
          wind_speed REAL,
          wind_direction INTEGER,
          water_degree REAL,
          wave_height REAL,
          result_payout3t1 INTEGER,
          result_payout3f1 INTEGER,
          result_payout2t1 INTEGER,
          result_payout2f1 INTEGER,
          result_payout_w1 INTEGER,
          result_payout1t1 INTEGER,
          result_payout1f1 INTEGER,
          winning_number3t1 TEXT,
          winning_number3f1 TEXT,
          winning_number2t1 TEXT,
          winning_number2f1 TEXT,
          winning_number1t1 TEXT,
          winning_number1f1 TEXT,
          fetched_at TEXT
        );

        CREATE TABLE IF NOT EXISTS race_boats (
          race_id TEXT NOT NULL,
          date TEXT,
          place_id INTEGER,
          round INTEGER,
          boat_number INTEGER NOT NULL,
          racer_id TEXT,
          reg_no INTEGER,
          racer_name TEXT,
          rank TEXT,
          is_absent INTEGER,
          ai_3ren_pct REAL,
          general_3ren_pct REAL,
          general_3ren_count INTEGER,
          st_rank_general REAL,
          st_time_avg_general REAL,
          ai_prediction_pct REAL,
          odds_prediction_pct REAL,
          tenji_time REAL,
          isshu_time REAL,
          avg_isshu_diff REAL,
          chokusen_time REAL,
          hanshu_time REAL,
          mawariashi_time REAL,
          before_start_sinnyu INTEGER,
          start_tenji_time REAL,
          start_tenji_rank INTEGER,
          tenji_rank INTEGER,
          tilt REAL,
          weight REAL,
          weight_adjust REAL,
          finish INTEGER,
          finish_order INTEGER,
          result_start_sinnyu INTEGER,
          result_start_time REAL,
          result_win_method TEXT,
          result_time REAL,
          start_flying INTEGER,
          henkan INTEGER,
          deokure INTEGER,
          nige_pct_year REAL,
          sasare_pct_year REAL,
          makurare_pct_year REAL,
          sashi_pct_year REAL,
          makuri_pct_year REAL,
          makurizashi_pct_year REAL,
          makurizasare_pct_year REAL,
          nigashi_pct_year REAL,
          win_method_race_count_year INTEGER,
          PRIMARY KEY (race_id, boat_number)
        );

        CREATE TABLE IF NOT EXISTS waku_aggregations (
          race_id TEXT NOT NULL,
          agg_type TEXT NOT NULL,
          waku INTEGER NOT NULL,
          shinnyu INTEGER,
          race_count INTEGER,
          result_is1_avg REAL,
          result_is2_avg REAL,
          result_is3_avg REAL,
          result_3ren_avg REAL,
          result_3ren_count INTEGER,
          PRIMARY KEY (race_id, agg_type, waku, shinnyu)
        );

        CREATE TABLE IF NOT EXISTS start_aggregations (
          race_id TEXT NOT NULL,
          agg_type TEXT NOT NULL,
          waku INTEGER NOT NULL,
          shinnyu INTEGER,
          start_time_avg REAL,
          start_time_rank_avg REAL,
          PRIMARY KEY (race_id, agg_type, waku, shinnyu)
        );

        CREATE TABLE IF NOT EXISTS win_method_aggregations (
          race_id TEXT NOT NULL,
          aggregation_range TEXT NOT NULL,
          waku INTEGER NOT NULL,
          shinnyu INTEGER,
          nige_rate REAL,
          sasare_rate REAL,
          makurare_rate REAL,
          sashi_rate REAL,
          makuri_rate REAL,
          makurizashi_rate REAL,
          makurizasare_rate REAL,
          nigashi_rate REAL,
          race_count_with_waku INTEGER,
          race_date TEXT,
          racer_reg_no INTEGER,
          PRIMARY KEY (race_id, aggregation_range, waku, shinnyu)
        );

        CREATE INDEX IF NOT EXISTS idx_race_day_races_status
          ON race_day_races(detail_status, date, place_id);
        CREATE INDEX IF NOT EXISTS idx_races_date_place_round
          ON races(date, place_id, round);
        CREATE INDEX IF NOT EXISTS idx_race_boats_date
          ON race_boats(date, place_id, round, boat_number);
        CREATE INDEX IF NOT EXISTS idx_race_boats_finish
          ON race_boats(finish);
        CREATE INDEX IF NOT EXISTS idx_races_payout3t
          ON races(result_payout3t1);

        CREATE VIEW IF NOT EXISTS v_race_boat_analysis AS
        SELECT
          b.race_id,
          b.date,
          r.place_name,
          b.place_id,
          b.round,
          b.boat_number,
          b.racer_name,
          b.rank,
          b.finish,
          CASE WHEN b.finish BETWEEN 1 AND 3 THEN 1 ELSE 0 END AS in_top3,
          r.result_payout3t1,
          CASE WHEN r.result_payout3t1 >= 10000 THEN 1 ELSE 0 END AS is_manshu,
          b.ai_3ren_pct,
          b.general_3ren_pct,
          CASE
            WHEN b.ai_3ren_pct IS NOT NULL AND b.general_3ren_pct IS NOT NULL
            THEN b.ai_3ren_pct + b.general_3ren_pct
          END AS ai_plus_general_3ren_pct,
          RANK() OVER (
            PARTITION BY b.race_id
            ORDER BY
              CASE
                WHEN b.ai_3ren_pct IS NOT NULL AND b.general_3ren_pct IS NOT NULL
                THEN b.ai_3ren_pct + b.general_3ren_pct
              END DESC
          ) AS ai_plus_general_rank,
          b.st_rank_general,
          b.ai_prediction_pct,
          b.tenji_time,
          b.isshu_time,
          b.avg_isshu_diff,
          b.nige_pct_year,
          b.sasare_pct_year,
          b.makurare_pct_year,
          b.result_start_time,
          b.result_start_sinnyu,
          r.result_win_method
        FROM race_boats b
        JOIN races r ON r.race_id = b.race_id;

        CREATE VIEW IF NOT EXISTS v_manshu_races AS
        SELECT
          r.*,
          GROUP_CONCAT(
            CASE WHEN b.finish BETWEEN 1 AND 3
              THEN b.boat_number || ':' || b.racer_name || '(' || b.finish || ')'
            END,
            ', '
          ) AS top3_boats
        FROM races r
        LEFT JOIN race_boats b ON b.race_id = r.race_id
        WHERE r.result_payout3t1 >= 10000
        GROUP BY r.race_id;
        """
    )
    con.execute(
        "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
        ("schema_version", "1"),
    )
    con.commit()


def upsert_race_day(con, race_day, indexed_at):
    setsu = race_day.get("setsu") or {}
    place_id = setsu.get("place")
    if place_id is None:
        return
    con.execute(
        """
        INSERT INTO race_days (
          date, place_id, place_name, slug, race_day_id, setsu_id, status_text,
          day_number, race_kind, category, series_title, series_first_date,
          series_last_date, indexed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(date, place_id) DO UPDATE SET
          place_name=excluded.place_name,
          slug=excluded.slug,
          race_day_id=excluded.race_day_id,
          setsu_id=excluded.setsu_id,
          status_text=excluded.status_text,
          day_number=excluded.day_number,
          race_kind=excluded.race_kind,
          category=excluded.category,
          series_title=excluded.series_title,
          series_first_date=excluded.series_first_date,
          series_last_date=excluded.series_last_date,
          indexed_at=excluded.indexed_at
        """,
        (
            race_day.get("date"),
            place_id,
            PLACE_NAMES.get(place_id),
            PLACE_SLUGS.get(place_id),
            race_day.get("id"),
            race_day.get("setsuId") or setsu.get("id"),
            race_day.get("statusText"),
            race_day.get("dayNumber"),
            setsu.get("raceKind"),
            setsu.get("category"),
            setsu.get("title"),
            setsu.get("firstDate"),
            setsu.get("lastDate"),
            indexed_at,
        ),
    )
    for race in race_day.get("races") or []:
        result = race.get("result") or {}
        current = con.execute(
            """
            SELECT detail_status FROM race_day_races
            WHERE date=? AND place_id=? AND round=?
            """,
            (race_day.get("date"), place_id, race.get("round")),
        ).fetchone()
        detail_status = current["detail_status"] if current else "pending"
        con.execute(
            """
            INSERT INTO race_day_races (
              date, place_id, round, crawled_race_id, race_id, deadline_time,
              race_grade, result_id, is_suspended, detail_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(date, place_id, round) DO UPDATE SET
              crawled_race_id=excluded.crawled_race_id,
              race_id=excluded.race_id,
              deadline_time=excluded.deadline_time,
              race_grade=excluded.race_grade,
              result_id=excluded.result_id,
              is_suspended=excluded.is_suspended
            """,
            (
                race_day.get("date"),
                place_id,
                race.get("round"),
                race.get("id"),
                race.get("raceId"),
                race.get("deadlineTime"),
                race.get("raceGrade"),
                result.get("id"),
                bool_int(result.get("isSuspended")),
                detail_status,
            ),
        )


def index_dates(con, start_date, end_date, sleep, session_id, refresh=False, progress_every=50):
    indexed_dates = 0
    indexed_races = 0
    errors = {}
    for day in daterange(start_date, end_date):
        if not refresh:
            existing = con.execute(
                "SELECT 1 FROM race_days WHERE date=? LIMIT 1", (day,)
            ).fetchone()
            if existing:
                continue
        try:
            data = gql_request(
                LIST_QUERY,
                {"date": day},
                "FetchRaceDaysForDate",
                session_id=session_id,
            )
            race_days = data.get("raceDaysForDate") or []
            now = datetime.now().isoformat(timespec="seconds")
            for race_day in race_days:
                upsert_race_day(con, race_day, now)
                indexed_races += len(race_day.get("races") or [])
            con.commit()
            indexed_dates += 1
            if progress_every and indexed_dates % progress_every == 0:
                print(
                    f"[index] dates={indexed_dates} races={indexed_races} latest={day}",
                    flush=True,
                )
            if sleep:
                time.sleep(sleep)
        except Exception as exc:
            errors[day] = str(exc)
            con.commit()
    return {"indexed_dates": indexed_dates, "indexed_races": indexed_races, "index_errors": errors}


def keyed_by_boat(items):
    result = {}
    for item in items or []:
        boat = item.get("boatNumber") or item.get("waku")
        if boat is not None:
            result[int(boat)] = item
    return result


def general_waku_by_boat(rows):
    return {
        int(item["waku"]): item
        for item in rows or []
        if item and item.get("aggType") == "一般" and item.get("waku") is not None
    }


def general_start_by_boat(rows):
    return {
        int(item["waku"]): item
        for item in rows or []
        if item and item.get("aggType") == "一般" and item.get("waku") is not None
    }


def year_win_by_boat(rows):
    return {
        int(item["waku"]): item
        for item in rows or []
        if item
        and item.get("aggregationRange") == "Year"
        and item.get("waku") is not None
    }


def int_finish(value):
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def clean_pk(value):
    if value is None:
        return "__null__"
    return value


def save_race(con, race, fallback_date, fallback_place_id, fetched_at):
    if not race:
        return None
    race_id = race.get("raceId")
    if not race_id:
        return None
    race_day = race.get("raceDay") or {}
    setsu = race_day.get("setsu") or {}
    result = race.get("result") or {}
    place_id = setsu.get("place") or fallback_place_id
    race_date = race_day.get("date") or fallback_date
    con.execute(
        """
        INSERT OR REPLACE INTO races (
          race_id, crawled_race_id, date, place_id, place_name, slug, round,
          title, race_grade, deadline_time, sinnyu_method, is_advertised,
          race_kind, category, series_title, series_first_date, series_last_date,
          is_suspended, result_win_method, weather_degree, weather, wind_speed,
          wind_direction, water_degree, wave_height, result_payout3t1,
          result_payout3f1, result_payout2t1, result_payout2f1, result_payout_w1,
          result_payout1t1, result_payout1f1, winning_number3t1,
          winning_number3f1, winning_number2t1, winning_number2f1,
          winning_number1t1, winning_number1f1, fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            race_id,
            race.get("id"),
            race_date,
            place_id,
            PLACE_NAMES.get(place_id),
            PLACE_SLUGS.get(place_id),
            race.get("round"),
            race.get("title"),
            race.get("raceGrade"),
            race.get("deadlineTime"),
            race.get("sinnyuMethod"),
            bool_int(race.get("isAdvertised")),
            setsu.get("raceKind"),
            setsu.get("category"),
            setsu.get("title"),
            setsu.get("firstDate"),
            setsu.get("lastDate"),
            bool_int(result.get("isSuspended")),
            result.get("winMethod"),
            result.get("weatherDegree"),
            result.get("weather"),
            result.get("windSpeed"),
            result.get("windDirection"),
            result.get("waterDegree"),
            result.get("waveHeight"),
            result.get("resultPayout3t1"),
            result.get("resultPayout3f1"),
            result.get("resultPayout2t1"),
            result.get("resultPayout2f1"),
            result.get("resultPayoutW1"),
            result.get("resultPayout1t1"),
            result.get("resultPayout1f1"),
            result.get("winningNumber3t1"),
            result.get("winningNumber3f1"),
            result.get("winningNumber2t1"),
            result.get("winningNumber2f1"),
            result.get("winningNumber1t1"),
            result.get("winningNumber1f1"),
            fetched_at,
        ),
    )

    con.execute("DELETE FROM race_boats WHERE race_id=?", (race_id,))
    con.execute("DELETE FROM waku_aggregations WHERE race_id=?", (race_id,))
    con.execute("DELETE FROM start_aggregations WHERE race_id=?", (race_id,))
    con.execute("DELETE FROM win_method_aggregations WHERE race_id=?", (race_id,))

    for item in race.get("wakuAggregations") or []:
        con.execute(
            """
            INSERT OR REPLACE INTO waku_aggregations (
              race_id, agg_type, waku, shinnyu, race_count, result_is1_avg,
              result_is2_avg, result_is3_avg, result_3ren_avg, result_3ren_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                race_id,
                item.get("aggType"),
                item.get("waku"),
                item.get("shinnyu"),
                item.get("raceCntWithWaku"),
                pct(item.get("resultIs1AvgWithWaku")),
                pct(item.get("resultIs2AvgWithWaku")),
                pct(item.get("resultIs3AvgWithWaku")),
                pct(item.get("result3renAvgWithWaku")),
                item.get("result3renCntWithWaku"),
            ),
        )
    for item in race.get("startAggregations") or []:
        con.execute(
            """
            INSERT OR REPLACE INTO start_aggregations (
              race_id, agg_type, waku, shinnyu, start_time_avg, start_time_rank_avg
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                race_id,
                item.get("aggType"),
                item.get("waku"),
                item.get("shinnyu"),
                item.get("startTimeAvgWithWaku"),
                item.get("startTimeRankAvgWithWaku"),
            ),
        )
    for item in race.get("winMethodAggregations") or []:
        con.execute(
            """
            INSERT OR REPLACE INTO win_method_aggregations (
              race_id, aggregation_range, waku, shinnyu, nige_rate, sasare_rate,
              makurare_rate, sashi_rate, makuri_rate, makurizashi_rate,
              makurizasare_rate, nigashi_rate, race_count_with_waku, race_date,
              racer_reg_no
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                race_id,
                item.get("aggregationRange"),
                item.get("waku"),
                item.get("shinnyu"),
                pct(item.get("nigeRate")),
                pct(item.get("sasareRate")),
                pct(item.get("makurareRate")),
                pct(item.get("sashiRate")),
                pct(item.get("makuriRate")),
                pct(item.get("makurizashiRate")),
                pct(item.get("makurizasareRate")),
                pct(item.get("nigashiRate")),
                item.get("raceCountWithWaku"),
                item.get("raceDate"),
                item.get("racerRegN"),
            ),
        )

    racers = keyed_by_boat(race.get("racers"))
    before = keyed_by_boat((race.get("beforeInfo") or {}).get("racers"))
    original = keyed_by_boat(race.get("originalTenjis"))
    results = keyed_by_boat(result.get("racers"))
    waku_general = general_waku_by_boat(race.get("wakuAggregations"))
    start_general = general_start_by_boat(race.get("startAggregations"))
    win_year = year_win_by_boat(race.get("winMethodAggregations"))
    ai_proba = race.get("aiProba") or {}
    odds_proba = race.get("racerOddsProba") or {}

    isshu_values = [
        item.get("isshuTime")
        for item in original.values()
        if isinstance(item.get("isshuTime"), (int, float))
    ]
    avg_isshu = sum(isshu_values) / len(isshu_values) if isshu_values else None

    for boat in range(1, 7):
        racer = racers.get(boat) or {}
        before_item = before.get(boat) or {}
        original_item = original.get(boat) or {}
        result_item = results.get(boat) or {}
        waku = waku_general.get(boat) or {}
        start = start_general.get(boat) or {}
        win = win_year.get(boat) or {}
        isshu = original_item.get("isshuTime")
        avg_diff = round(avg_isshu - isshu, 4) if avg_isshu is not None and isinstance(isshu, (int, float)) else None

        con.execute(
            """
            INSERT OR REPLACE INTO race_boats (
              race_id, date, place_id, round, boat_number, racer_id, reg_no,
              racer_name, rank, is_absent, ai_3ren_pct, general_3ren_pct,
              general_3ren_count, st_rank_general, st_time_avg_general,
              ai_prediction_pct, odds_prediction_pct, tenji_time, isshu_time,
              avg_isshu_diff, chokusen_time, hanshu_time, mawariashi_time,
              before_start_sinnyu, start_tenji_time, start_tenji_rank, tenji_rank,
              tilt, weight, weight_adjust, finish, finish_order,
              result_start_sinnyu, result_start_time, result_win_method,
              result_time, start_flying, henkan, deokure, nige_pct_year,
              sasare_pct_year, makurare_pct_year, sashi_pct_year, makuri_pct_year,
              makurizashi_pct_year, makurizasare_pct_year, nigashi_pct_year,
              win_method_race_count_year
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                race_id,
                race_date,
                place_id,
                race.get("round"),
                boat,
                racer.get("id"),
                racer.get("regN"),
                racer.get("name"),
                racer.get("rank"),
                bool_int(racer.get("isAbsent")),
                pct(ai_proba.get(f"aiProbaRacer{boat}3ren")),
                pct(waku.get("result3renAvgWithWaku")),
                waku.get("result3renCntWithWaku"),
                start.get("startTimeRankAvgWithWaku"),
                start.get("startTimeAvgWithWaku"),
                pct(odds_proba.get(f"racerAiProba{boat}")),
                pct(odds_proba.get(f"racerOddsProba{boat}")),
                before_item.get("tenjiTime"),
                isshu,
                avg_diff,
                original_item.get("chokusenTime"),
                original_item.get("hanshuTime"),
                original_item.get("mawariashiTime"),
                before_item.get("startSinnyu"),
                before_item.get("startTenjiTime"),
                before_item.get("startTenjiRank"),
                before_item.get("tenjiRank"),
                before_item.get("tilt"),
                before_item.get("weight"),
                before_item.get("weightAdjust"),
                int_finish(result_item.get("chakuPosition")),
                result_item.get("chakuOrder"),
                result_item.get("startSinnyu"),
                result_item.get("startTime"),
                result_item.get("winMethod"),
                result_item.get("resultTime"),
                bool_int(result_item.get("startFlying")),
                bool_int(result_item.get("henkan")),
                bool_int(result_item.get("deokure")),
                pct(win.get("nigeRate")),
                pct(win.get("sasareRate")),
                pct(win.get("makurareRate")),
                pct(win.get("sashiRate")),
                pct(win.get("makuriRate")),
                pct(win.get("makurizashiRate")),
                pct(win.get("makurizasareRate")),
                pct(win.get("nigashiRate")),
                win.get("raceCountWithWaku"),
            ),
        )
    con.execute(
        """
        UPDATE race_day_races
        SET race_id=?, detail_status='done', detail_error=NULL, detail_fetched_at=?
        WHERE date=? AND place_id=? AND round=?
        """,
        (race_id, fetched_at, fallback_date, fallback_place_id, race.get("round")),
    )
    return race_id


def detail_groups(con, start_date, end_date, max_groups=None, refresh=False):
    status_clause = "" if refresh else "AND detail_status != 'done'"
    rows = con.execute(
        f"""
        SELECT date, place_id, GROUP_CONCAT(round) AS rounds
        FROM race_day_races
        WHERE date BETWEEN ? AND ? {status_clause}
        GROUP BY date, place_id
        ORDER BY date, place_id
        """,
        (start_date, end_date),
    ).fetchall()
    groups = []
    for row in rows:
        rounds = [int(x) for x in row["rounds"].split(",") if x]
        groups.append((row["date"], row["place_id"], rounds))
        if max_groups is not None and len(groups) >= max_groups:
            break
    return groups


def detail_dates(con, start_date, end_date, max_dates=None, refresh=False):
    status_clause = "" if refresh else "AND detail_status != 'done'"
    dates = con.execute(
        f"""
        SELECT DISTINCT date
        FROM race_day_races
        WHERE date BETWEEN ? AND ? {status_clause}
        ORDER BY date
        """,
        (start_date, end_date),
    ).fetchall()
    result = []
    for row in dates:
        races = con.execute(
            f"""
            SELECT date, place_id, round
            FROM race_day_races
            WHERE date=? {status_clause}
            ORDER BY place_id, round
            """,
            (row["date"],),
        ).fetchall()
        result.append((row["date"], races))
        if max_dates is not None and len(result) >= max_dates:
            break
    return result


def fetch_details(con, start_date, end_date, sleep, session_id, max_groups=None, refresh=False, progress_every=25):
    groups = detail_groups(con, start_date, end_date, max_groups=max_groups, refresh=refresh)
    fetched_groups = 0
    fetched_races = 0
    errors = {}
    for race_date, place_id, rounds in groups:
        try:
            data = gql_request(
                race_day_query(rounds),
                {"date": race_date, "locationId": place_id},
                "RaceDayAll",
                session_id=session_id,
            )
            fetched_at = datetime.now().isoformat(timespec="seconds")
            for round_no in sorted(rounds):
                race = data.get(f"r{round_no}")
                if race:
                    save_race(con, race, race_date, place_id, fetched_at)
                    fetched_races += 1
                else:
                    con.execute(
                        """
                        UPDATE race_day_races
                        SET detail_status='error', detail_error=?, detail_fetched_at=?
                        WHERE date=? AND place_id=? AND round=?
                        """,
                        ("raceRoundDetail returned null", fetched_at, race_date, place_id, round_no),
                    )
            con.commit()
            fetched_groups += 1
            if progress_every and fetched_groups % progress_every == 0:
                print(
                    f"[details] groups={fetched_groups}/{len(groups)} races={fetched_races} latest={race_date}_{PLACE_SLUGS.get(place_id, place_id)}",
                    flush=True,
                )
            if sleep:
                time.sleep(sleep)
        except Exception as exc:
            fetched_at = datetime.now().isoformat(timespec="seconds")
            key = f"{race_date}_{PLACE_SLUGS.get(place_id, place_id)}"
            errors[key] = str(exc)
            con.execute(
                """
                UPDATE race_day_races
                SET detail_status='error', detail_error=?, detail_fetched_at=?
                WHERE date=? AND place_id=? AND round IN ({})
                """.format(",".join("?" for _ in rounds)),
                (str(exc), fetched_at, race_date, place_id, *rounds),
            )
            con.commit()
    return {"detail_groups": fetched_groups, "detail_races": fetched_races, "detail_errors": errors}


def fetch_details_daily(con, start_date, end_date, sleep, session_id, max_dates=None, refresh=False, progress_every=10):
    days = detail_dates(con, start_date, end_date, max_dates=max_dates, refresh=refresh)
    fetched_dates = 0
    fetched_races = 0
    errors = {}
    for race_date, races in days:
        try:
            data = gql_request(
                race_date_query(races),
                {},
                "RaceDateAll",
                session_id=session_id,
                retries=3,
            )
            fetched_at = datetime.now().isoformat(timespec="seconds")
            for item in races:
                place_id = int(item["place_id"])
                round_no = int(item["round"])
                race = data.get(f"p{place_id}r{round_no}")
                if race:
                    save_race(con, race, race_date, place_id, fetched_at)
                    fetched_races += 1
                else:
                    con.execute(
                        """
                        UPDATE race_day_races
                        SET detail_status='error', detail_error=?, detail_fetched_at=?
                        WHERE date=? AND place_id=? AND round=?
                        """,
                        ("raceRoundDetail returned null", fetched_at, race_date, place_id, round_no),
                    )
            con.commit()
            fetched_dates += 1
            if progress_every and fetched_dates % progress_every == 0:
                print(
                    f"[details-daily] dates={fetched_dates}/{len(days)} races={fetched_races} latest={race_date}",
                    flush=True,
                )
            if sleep:
                time.sleep(sleep)
        except Exception as exc:
            fetched_at = datetime.now().isoformat(timespec="seconds")
            errors[race_date] = str(exc)
            con.execute(
                """
                UPDATE race_day_races
                SET detail_status='error', detail_error=?, detail_fetched_at=?
                WHERE date=? AND detail_status != 'done'
                """,
                (str(exc), fetched_at, race_date),
            )
            con.commit()
    return {"detail_dates": fetched_dates, "detail_races": fetched_races, "detail_errors": errors}


def fetch_race_date_payload(race_date, races, session_id):
    plain_races = [dict(item) for item in races]
    data = gql_request(
        race_date_query(plain_races),
        {},
        "RaceDateAll",
        session_id=session_id,
        retries=3,
    )
    return race_date, plain_races, data


def fetch_details_daily_parallel(
    con,
    start_date,
    end_date,
    sleep,
    session_id,
    max_dates=None,
    refresh=False,
    progress_every=10,
    workers=3,
):
    days = detail_dates(con, start_date, end_date, max_dates=max_dates, refresh=refresh)
    fetched_dates = 0
    fetched_races = 0
    errors = {}

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_date = {}
        for race_date, races in days:
            future = executor.submit(fetch_race_date_payload, race_date, races, session_id)
            future_to_date[future] = race_date
            if sleep:
                time.sleep(sleep)

        for future in as_completed(future_to_date):
            race_date = future_to_date[future]
            try:
                race_date, races, data = future.result()
                fetched_at = datetime.now().isoformat(timespec="seconds")
                for item in races:
                    place_id = int(item["place_id"])
                    round_no = int(item["round"])
                    race = data.get(f"p{place_id}r{round_no}")
                    if race:
                        save_race(con, race, race_date, place_id, fetched_at)
                        fetched_races += 1
                    else:
                        con.execute(
                            """
                            UPDATE race_day_races
                            SET detail_status='error', detail_error=?, detail_fetched_at=?
                            WHERE date=? AND place_id=? AND round=?
                            """,
                            ("raceRoundDetail returned null", fetched_at, race_date, place_id, round_no),
                        )
                con.commit()
                fetched_dates += 1
                if progress_every and fetched_dates % progress_every == 0:
                    print(
                        f"[details-daily] dates={fetched_dates}/{len(days)} races={fetched_races} latest_saved={race_date} workers={workers}",
                        flush=True,
                    )
            except Exception as exc:
                fetched_at = datetime.now().isoformat(timespec="seconds")
                errors[race_date] = str(exc)
                con.execute(
                    """
                    UPDATE race_day_races
                    SET detail_status='error', detail_error=?, detail_fetched_at=?
                    WHERE date=? AND detail_status != 'done'
                    """,
                    (str(exc), fetched_at, race_date),
                )
                con.commit()
    return {"detail_dates": fetched_dates, "detail_races": fetched_races, "detail_errors": errors}


def status(con, db_path):
    def one(sql):
        return con.execute(sql).fetchone()[0]

    return {
        "db_path": str(db_path),
        "date_min": one("SELECT MIN(date) FROM race_day_races"),
        "date_max": one("SELECT MAX(date) FROM race_day_races"),
        "race_days": one("SELECT COUNT(*) FROM race_days"),
        "race_index_rows": one("SELECT COUNT(*) FROM race_day_races"),
        "detail_done_rows": one("SELECT COUNT(*) FROM race_day_races WHERE detail_status='done'"),
        "detail_pending_rows": one("SELECT COUNT(*) FROM race_day_races WHERE detail_status='pending'"),
        "detail_error_rows": one("SELECT COUNT(*) FROM race_day_races WHERE detail_status='error'"),
        "races": one("SELECT COUNT(*) FROM races"),
        "race_boats": one("SELECT COUNT(*) FROM race_boats"),
        "manshu_races": one("SELECT COUNT(*) FROM races WHERE result_payout3t1 >= 10000"),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument(
        "--mode",
        choices=["index", "details", "details-daily", "full", "full-daily", "status"],
        default="status",
    )
    parser.add_argument("--start-date", default=START_DATE)
    parser.add_argument("--end-date", default=END_DATE)
    parser.add_argument("--sleep", type=float, default=0.08)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--max-detail-groups", type=int, default=None)
    parser.add_argument("--max-detail-dates", type=int, default=None)
    parser.add_argument("--progress-every", type=int, default=50)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()

    db_path = Path(args.db)
    con = connect(db_path)
    init_db(con)
    session_id = f"codex-db-{int(time.time())}"

    report = {}
    if args.mode in ("index", "full", "full-daily"):
        report.update(
            index_dates(
                con,
                args.start_date,
                args.end_date,
                sleep=args.sleep,
                session_id=session_id,
                refresh=args.refresh,
                progress_every=args.progress_every,
            )
        )
    if args.mode in ("details", "full"):
        report.update(
            fetch_details(
                con,
                args.start_date,
                args.end_date,
                sleep=args.sleep,
                session_id=session_id,
                max_groups=args.max_detail_groups,
                refresh=args.refresh,
                progress_every=args.progress_every,
            )
        )
    if args.mode in ("details-daily", "full-daily"):
        if args.workers > 1:
            report.update(
                fetch_details_daily_parallel(
                    con,
                    args.start_date,
                    args.end_date,
                    sleep=args.sleep,
                    session_id=session_id,
                    max_dates=args.max_detail_dates,
                    refresh=args.refresh,
                    progress_every=args.progress_every,
                    workers=args.workers,
                )
            )
        else:
            report.update(
                fetch_details_daily(
                    con,
                    args.start_date,
                    args.end_date,
                    sleep=args.sleep,
                    session_id=session_id,
                    max_dates=args.max_detail_dates,
                    refresh=args.refresh,
                    progress_every=args.progress_every,
                )
            )
    report["status"] = status(con, db_path)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
