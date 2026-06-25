#!/usr/bin/env python3
"""Phase 0 audit and baseline capture for research_v2.

This script is intentionally read-only with respect to production assets. It
hashes and inspects existing files, then writes only research_v2 artifacts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
JST = timezone(timedelta(hours=9))

SCRIPT_TARGETS = [
    "scripts/rank_daily_manshu_candidates.py",
    "scripts/build_manshu_dataset.py",
    "scripts/build_boat_role_dataset.py",
    "scripts/generate_manshu_role_ranking.py",
    "scripts/backtest_role_formations.py",
    "scripts/backtest_boaters_composite_buy_strategies.py",
    "scripts/fetch_boatrace_data.py",
    "scripts/normalize_boatrace_data.py",
    "scripts/validate_manshu_model.py",
]

AUDIT_TARGETS = [
    "manshu.html",
    "manshu_chokuzen.html",
    *SCRIPT_TARGETS,
    "data/analysis/race_dataset.csv",
    "data/analysis/boat_role_dataset.csv",
    "data/model/manshu_condition_combo_search.csv",
    ".github/workflows/boaters-ntfy-monitor.yml",
]

FEATURE_KEYWORDS = {
    "現在の万舟率ランキング生成": ["manshu_rate_pct", "all_venue_rank_top", "strict_rank_top", "composite_edges"],
    "頭候補、軸候補、消し候補": ["role_morning", "role_preview", "head", "axis", "toss", "kill"],
    "朝版と直前版": ["morning", "preview", "直前", "展示待ち"],
    "展示タイム": ["exhibition_time", "tenji", "展示タイム"],
    "展示ST": ["exhibition_st", "展示ST"],
    "1周タイム": ["isshu", "1周"],
    "周回、回り足、直線": ["まわり足", "直線", "laps", "straight"],
    "チルト": ["tilt", "チルト"],
    "スリット隊形": ["slit", "スリット"],
    "天候、風、波": ["weather", "wind", "wave", "天候", "風", "波"],
    "オッズ": ["odds", "オッズ"],
    "バックテスト": ["backtest", "Backtest", "検証"],
    "18点フォーメーション": ["formation", "B", "18"],
    "回収率": ["roi", "return_rate", "回収率"],
    "最大連敗": ["losing_streak", "最大連敗"],
    "最大ドローダウン": ["drawdown", "ドローダウン"],
    "前向き検証": ["forward", "前向き"],
    "特徴量重要度": ["feature_importance", "permutation", "importance"],
    "クラスタリング": ["cluster", "KMeans", "クラスタ"],
    "追加データの継続保存": ["fetch", "cache", "normalized", "manifest"],
}


def now_iso() -> str:
    return datetime.now(JST).isoformat(timespec="seconds")


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def sha256(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return "unknown"


def git_status() -> list[str]:
    try:
        out = subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True)
        return [line for line in out.splitlines() if line.strip()]
    except Exception:
        return []


def read_text(path: Path, limit: int = 500_000) -> str:
    if not path.exists() or not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")[:limit]


def schema_of(value: Any, depth: int = 0) -> Any:
    if depth > 4:
        return "..."
    if isinstance(value, dict):
        return {key: schema_of(value[key], depth + 1) for key in sorted(value.keys())}
    if isinstance(value, list):
        if not value:
            return []
        return [schema_of(value[0], depth + 1)]
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    return "str"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def classify_features(corpus: str) -> dict[str, str]:
    output: dict[str, str] = {}
    for label, needles in FEATURE_KEYWORDS.items():
        matches = sum(1 for needle in needles if needle.lower() in corpus.lower())
        if matches >= 2:
            output[label] = "実装済み"
        elif matches == 1:
            output[label] = "一部実装"
        else:
            output[label] = "未実装"
    return output


def ranking_snapshot(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": rel(path), "exists": False}
    data = load_json(path)
    races = data.get("strict_races") or data.get("races") or []
    return {
        "path": rel(path),
        "exists": True,
        "version": data.get("version"),
        "date": data.get("date"),
        "logic_label": data.get("logic_label"),
        "summary": data.get("summary"),
        "schema": schema_of(data),
        "top10": [
            {
                "rank": row.get("rank"),
                "place_name": row.get("place_name"),
                "round": row.get("round"),
                "manshu_rate_pct": row.get("manshu_rate_pct"),
                "status": row.get("status"),
                "result": row.get("result"),
            }
            for row in races[:10]
        ],
    }


def python_environment() -> dict[str, Any]:
    packages: dict[str, str] = {}
    for name in ["numpy", "pandas", "sklearn", "scipy", "joblib"]:
        try:
            module = __import__(name)
            packages[name] = str(getattr(module, "__version__", "installed"))
        except Exception as exc:
            packages[name] = f"missing: {exc}"
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": packages,
    }


def write_audit(path: Path, manifest: dict[str, Any], classifications: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = ["| 項目 | 判定 | 根拠 |", "| --- | --- | --- |"]
    evidence = {
        "現在の万舟率ランキング生成": "`rank_daily_manshu_candidates.py` と保存済み `boaters_manshu_ranking_YYYYMMDD.json` が存在。",
        "頭候補、軸候補、消し候補": "`build_boat_role_dataset.py` の `head/axis/toss/opponent` とフォーメーションA-Dが存在。",
        "朝版と直前版": "role dataset に `morning` / `preview` が存在。",
        "展示タイム": "正規化データとrole datasetに `exhibition_time` が存在。",
        "展示ST": "正規化データに `exhibition_st` が存在。",
        "1周タイム": "BOATERS側ランキングメトリクスに `isshu` 系が存在。公式正規化データには限定的。",
        "周回、回り足、直線": "現在の公式正規化データには明確な列なし。BOATERS側由来は一部メトリクスのみ。",
        "チルト": "`tilt` 列はあるが、現データでは取得率0%に近い。",
        "スリット隊形": "`rank_daily_manshu_candidates.py` にスリット隊形補正が存在。",
        "天候、風、波": "正規化データに `weather/wind/wave` が存在。",
        "オッズ": "取得スクリプトは `odds3t` 対応。ただし保存済み分析データでの継続利用は限定的。",
        "バックテスト": "`backtest_role_formations.py` と `backtest_boaters_composite_buy_strategies.py` が存在。",
        "18点フォーメーション": "既存Bフォーメーションは概ね18点相当。ただしレースごとに重複除外で変動しうる。",
        "回収率": "既存に参考回収率あり。今回research_v2で会計式を明示して再計算対象。",
        "最大連敗": "`generate_manshu_role_ranking.py` に既存検証値の定数あり。汎用集計はresearch_v2で追加対象。",
        "最大ドローダウン": "`generate_manshu_role_ranking.py` に既存検証値の定数あり。汎用集計はresearch_v2で追加対象。",
        "前向き検証": "保存済み日別ランキングJSONは5/1以降の前向きログとして扱える。欠落日は後ろ向き扱い。",
        "特徴量重要度": "専用出力は未確認。research_v2で追加対象。",
        "クラスタリング": "専用出力は未確認。research_v2で追加対象。",
        "追加データの継続保存": "`fetch_boatrace_data.py` と `normalize_boatrace_data.py` があるが、追加候補全体は未整備。",
    }
    for item, status in classifications.items():
        rows.append(f"| {item} | {status} | {evidence.get(item, '')} |")

    workflow_files = "\n".join(f"- `{item}`" for item in manifest["workflow_files"])
    target_files = "\n".join(
        f"- `{item['path']}`: {'あり' if item['exists'] else 'なし'}"
        for item in manifest["audited_files"]
    )
    text = [
        "# research_v2 Current System Audit",
        "",
        "この監査は、本番ツールを変更せずに既存コード・保存済みJSON・出力ファイルを読んで作成したものです。",
        "",
        f"- 監査時刻: {manifest['generated_at']}",
        f"- Git commit: `{manifest['git_commit']}`",
        f"- Git status entries: {len(manifest['git_status'])}",
        "",
        "## 判定サマリ",
        "",
        *rows,
        "",
        "## 監査対象ファイル",
        "",
        target_files,
        "",
        "## workflow",
        "",
        workflow_files or "- なし",
        "",
        "## データフロー図",
        "",
        "```mermaid",
        "flowchart TD",
        '  A["公式/BOATERS取得"] --> B["data/raw / BOATERS DB"]',
        '  B --> C["data/normalized / data/analysis"]',
        '  C --> D["既存ランキング生成"]',
        '  D --> E["boaters_manshu_ranking_YYYYMMDD.json"]',
        '  E --> F["manshu.html 本番表示"]',
        '  E --> G["research_v2 保存済み予測ログ検証"]',
        '  C --> H["research_v2 頭/展示/クラスタ検証"]',
        '  G --> I["reports/research_v2"]',
        '  H --> I',
        "```",
        "",
        "## 重要な監査結論",
        "",
        "- 現行本番ランキングは保存済みJSONを公開ページが読む構成であり、今回の研究ではこのJSONを変更しない。",
        "- `boaters_manshu_ranking_YYYYMMDD.json` と `boaters_manshu_ranking_codex_YYYYMMDD.json` は、存在する日について本番当時の予測記録として扱う。",
        "- 予測時点にない結果列、払戻、人気、決まり手は特徴量に入れない。評価ラベルとしてのみ使用する。",
        "- 展示系は既に一部入っているが、朝版と直前版の増分効果を独立に評価する仕組みは不足している。",
        "- 回収率は既存に参考値があるが、今回のresearch_v2で会計式・返還欠損ルール・ドローダウンを明示して再集計する。",
    ]
    path.write_text("\n".join(text) + "\n", encoding="utf-8")


def build(args: argparse.Namespace) -> dict[str, Any]:
    workflow_files = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / ".github" / "workflows").glob("*"))
    audited_files = []
    corpus_parts = []
    for target in AUDIT_TARGETS:
        path = ROOT / target
        text = read_text(path)
        corpus_parts.append(text)
        audited_files.append(
            {
                "path": target,
                "exists": path.exists(),
                "sha256": sha256(path),
                "bytes": path.stat().st_size if path.exists() and path.is_file() else None,
            }
        )
    corpus = "\n".join(corpus_parts)
    rankings = {}
    for key in args.sample_dates:
        compact = key.replace("-", "")
        rankings[compact] = {
            "normal": ranking_snapshot(ROOT / "data" / "output" / f"boaters_manshu_ranking_{compact}.json"),
            "codex": ranking_snapshot(ROOT / "data" / "output" / f"boaters_manshu_ranking_codex_{compact}.json"),
        }
    manifest = {
        "version": "research-v2-baseline-1",
        "generated_at": now_iso(),
        "git_commit": git_commit(),
        "git_status": git_status(),
        "audited_files": audited_files,
        "script_hashes": {target: sha256(ROOT / target) for target in SCRIPT_TARGETS},
        "manshu_html_hash": sha256(ROOT / "manshu.html"),
        "workflow_files": workflow_files,
        "ranking_snapshots": rankings,
        "feature_status": classify_features(corpus),
        "python_environment": python_environment(),
        "execution": {
            "command": "python scripts/research_v2/phase0_audit_baseline.py",
            "cwd": str(ROOT),
            "new_features_default_off": True,
            "production_files_modified_by_this_script": False,
        },
    }
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sample-dates",
        nargs="*",
        default=["2026-05-01", "2026-06-18", "2026-06-24", "2026-06-25"],
    )
    parser.add_argument("--audit-out", default="docs/research_v2/current_system_audit.md")
    parser.add_argument("--manifest-out", default="reports/research_v2/baseline_manifest.json")
    parser.add_argument("--hash-out", default="data/output/research_v2/baseline_hashes.json")
    args = parser.parse_args()
    manifest = build(args)
    audit_path = ROOT / args.audit_out
    manifest_path = ROOT / args.manifest_out
    hash_path = ROOT / args.hash_out
    write_audit(audit_path, manifest, manifest["feature_status"])
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    hash_path.parent.mkdir(parents=True, exist_ok=True)
    hash_path.write_text(
        json.dumps(
            {
                "version": manifest["version"],
                "git_commit": manifest["git_commit"],
                "manshu_html_hash": manifest["manshu_html_hash"],
                "script_hashes": manifest["script_hashes"],
            },
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"audit": args.audit_out, "manifest": args.manifest_out}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
