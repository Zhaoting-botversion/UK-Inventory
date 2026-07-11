from __future__ import annotations

import argparse
import io
import json
import re
import shutil
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from importlib.machinery import SourcelessFileLoader
from pathlib import Path

from googleapiclient.http import MediaIoBaseDownload

from unit_change_engine import DB_PATH, compare_versions, extract_price_records, insert_version, store_events


SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
WORK_PROJECTS_DIR = BASE_DIR.parent
LOG_DIR = WORK_PROJECTS_DIR / "迁移资料到Google Drive" / "logs"
DRIVE_STATE_PATH = SCRIPT_DIR / "drive_state.json"
DOWNLOAD_DIR = Path(r"C:\tmp\UK_Inventory_Unit_Changes")
UPDATER_PYC_PATH = WORK_PROJECTS_DIR / "迁移资料到Google Drive" / "__pycache__" / "uk_update_pricelists.cpython-312.pyc"
PRICE_EXTENSIONS = {".pdf", ".xlsx", ".xlsm", ".xls", ".csv"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build unit-level changes from recent upload logs.")
    parser.add_argument("--hours", type=int, default=24, help="Read update logs modified in the last N hours.")
    parser.add_argument("--dry-run", action="store_true", help="Only print candidate pairs.")
    parser.add_argument("--reset-db", action="store_true", help="Delete inventory_units.sqlite before importing.")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of pairs to ingest.")
    return parser.parse_args()


def norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def load_uk_update_module():
    if not UPDATER_PYC_PATH.exists():
        raise FileNotFoundError(f"Missing compiled updater: {UPDATER_PYC_PATH}")
    loader = SourcelessFileLoader("uk_update_pricelists_cached_for_unit_changes", str(UPDATER_PYC_PATH))
    return loader.load_module()


def normalize_phase(file_name: str) -> str:
    stem = Path(file_name).stem.lower()
    stem = re.sub(r"\b(?:cn|agent|customer|distribution|daily|weekly|master|full|availability|price|pricelist|price\s*list|list)\b", " ", stem)
    stem = re.sub(r"\b\d{1,2}[._-]\d{1,2}[._-]\d{2,4}\b", " ", stem)
    stem = re.sub(r"\b\d{1,2}[._-]\d{1,2}\b", " ", stem)
    stem = re.sub(r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|june|jul|july|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{2,4}\b", " ", stem)
    stem = re.sub(r"\b(?:jan|feb|mar|apr|may|jun|june|jul|july|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{2,4}\b", " ", stem)
    stem = re.sub(r"\b20\d{2}\b", " ", stem)
    stem = re.sub(r"\bready\s+to\s+move(?:\s+in)?\b", " ", stem)
    stem = re.sub(r"\b(?:updated|new|latest|june|july|summer|fete|global|platinum|launch)\b", " ", stem)
    return re.sub(r"[^a-z0-9]+", " ", stem).strip()


def display_project_name(name: str) -> str:
    return re.sub(r"^[A-Z]{1,3}\d{0,2}[A-Z]?\s*[-–]\s*", "", name).strip()


def match_project(log_project: str, projects: dict) -> dict | None:
    exact = {row.get("project", ""): row for row in projects.values()}
    if log_project in exact:
        return exact[log_project]
    target = norm(log_project)
    for row in projects.values():
        project = row.get("project", "")
        if norm(display_project_name(project)) == target or target in norm(project):
            return row
    return None


def read_recent_logs(hours: int) -> list[dict]:
    cutoff = datetime.now() - timedelta(hours=hours)
    logs = []
    for path in sorted(LOG_DIR.glob("uk_update_*.json"), key=lambda p: p.stat().st_mtime):
        if datetime.fromtimestamp(path.stat().st_mtime) < cutoff:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logs.append({"path": str(path), "error": str(exc), "uploaded": []})
            continue
        data["_log_name"] = path.name
        data["_mtime"] = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
        logs.append(data)
    return logs


def price_file(name: str) -> bool:
    return Path(name).suffix.lower() in PRICE_EXTENSIONS


def build_pairs(logs: list[dict], state: dict) -> tuple[list[dict], list[dict]]:
    projects = state.get("projects", {})
    pairs = []
    unmatched = []
    seen = set()
    for log in logs:
        for uploaded in log.get("uploaded", []):
            project_name = uploaded.get("project", "")
            file_name = uploaded.get("file", "")
            if not price_file(file_name):
                continue
            project = match_project(project_name, projects)
            if not project:
                unmatched.append({"project": project_name, "file": file_name, "reason": "project not found", "log": log.get("_log_name")})
                continue
            key = normalize_phase(file_name)
            old_candidates = [
                item for item in project.get("old_files", [])
                if price_file(item.get("file", ""))
                and item.get("file", "") != file_name
                and (item.get("file_id", "") != uploaded.get("id", ""))
                and normalize_phase(item.get("file", "")) == key
            ]
            if not old_candidates:
                unmatched.append({"project": project_name, "file": file_name, "reason": "old version not found", "log": log.get("_log_name")})
                continue
            old = sorted(old_candidates, key=lambda row: row.get("modified_at", ""), reverse=True)[0]
            pair_key = (project.get("project"), uploaded.get("id") or uploaded.get("file"), old.get("file_id") or old.get("file"))
            if pair_key in seen:
                continue
            seen.add(pair_key)
            pairs.append({
                "project": project.get("project", project_name),
                "log_project": project_name,
                "phase_key": key,
                "new_file": file_name,
                "new_file_id": uploaded.get("id") or next((item.get("file_id") for item in project.get("latest_files", []) if item.get("file") == file_name), ""),
                "old_file": old.get("file", ""),
                "old_file_id": old.get("file_id", ""),
                "log": log.get("_log_name"),
            })
    return pairs, unmatched


def parse_modified_at(value: str) -> datetime | None:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
        return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
    except ValueError:
        return None


def build_state_pairs(state: dict, hours: int, existing_keys: set[tuple[str, str, str]]) -> tuple[list[dict], list[dict]]:
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    pairs = []
    unmatched = []
    for project in state.get("projects", {}).values():
        project_name = project.get("project", "")
        for uploaded in project.get("latest_files", []):
            file_name = uploaded.get("file", "")
            if not price_file(file_name):
                continue
            modified_at = parse_modified_at(uploaded.get("modified_at", ""))
            if modified_at and modified_at < cutoff:
                continue
            key = normalize_phase(file_name)
            old_candidates = [
                item for item in project.get("old_files", [])
                if price_file(item.get("file", ""))
                and item.get("file", "") != file_name
                and (item.get("file_id", "") != uploaded.get("file_id", ""))
                and normalize_phase(item.get("file", "")) == key
            ]
            if not old_candidates:
                unmatched.append({"project": project_name, "file": file_name, "reason": "old version not found in Drive snapshot", "log": "drive_state"})
                continue
            old = sorted(old_candidates, key=lambda row: row.get("modified_at", ""), reverse=True)[0]
            pair_key = (project_name, uploaded.get("file_id") or uploaded.get("file"), old.get("file_id") or old.get("file"))
            if pair_key in existing_keys:
                continue
            existing_keys.add(pair_key)
            pairs.append({
                "project": project_name,
                "log_project": project_name,
                "phase_key": key,
                "new_file": file_name,
                "new_file_id": uploaded.get("file_id", ""),
                "old_file": old.get("file", ""),
                "old_file_id": old.get("file_id", ""),
                "log": "drive_state",
            })
    return pairs, unmatched


def safe_part(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._ -]+", "_", value).strip(" ._") or "item"


def clear_database() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()


def download_drive_file_to(service, file_id: str, name: str, folder: Path, retries: int = 4) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name
    for attempt in range(1, retries + 1):
        try:
            request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
            buffer = io.BytesIO()
            downloader = MediaIoBaseDownload(buffer, request, chunksize=512 * 1024)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            target.write_bytes(buffer.getvalue())
            return target
        except Exception:
            if attempt >= retries:
                raise
            time.sleep(min(2 * attempt, 8))
    return target


def download_pair(service, pair: dict) -> tuple[Path, Path]:
    target = DOWNLOAD_DIR / safe_part(pair["project"]) / safe_part(pair["phase_key"])
    old_path = download_drive_file_to(service, pair["old_file_id"], pair["old_file"], target / "old")
    new_path = download_drive_file_to(service, pair["new_file_id"], pair["new_file"], target / "new")
    return old_path, new_path


def import_pair(pair: dict, old_path: Path, new_path: Path) -> dict:
    label_old = Path(pair["old_file"]).stem
    label_new = Path(pair["new_file"]).stem
    project_key = pair["project"]
    if pair.get("phase_key"):
        project_key = f"{pair['project']} · {pair['phase_key']}"
    old_records, old_error = extract_price_records(old_path)
    new_records, new_error = extract_price_records(new_path)
    old_version_id = insert_version(project_key, pair["old_file"], str(old_path), label_old, old_records, old_error)
    new_version_id = insert_version(project_key, pair["new_file"], str(new_path), label_new, new_records, new_error)
    old_version = {"id": old_version_id, "project_name": project_key, "source_file": pair["old_file"]}
    new_version = {"id": new_version_id, "project_name": project_key, "source_file": pair["new_file"]}
    events = compare_versions(project_key, old_version, new_version)
    store_events(events)
    with sqlite3.connect(DB_PATH) as conn:
        old_count = conn.execute("select count(*) from unit_snapshots where version_id=?", (old_version_id,)).fetchone()[0]
        new_count = conn.execute("select count(*) from unit_snapshots where version_id=?", (new_version_id,)).fetchone()[0]
        event_count = conn.execute(
            "select count(*) from unit_change_events where old_version_id=? and new_version_id=?",
            (old_version_id, new_version_id),
        ).fetchone()[0]
    return {
        "project": pair["project"],
        "project_key": project_key,
        "old_file": pair["old_file"],
        "new_file": pair["new_file"],
        "old_units": old_count,
        "new_units": new_count,
        "events": event_count,
        "old_error": old_error,
        "new_error": new_error,
    }


def project_key_for_pair(pair: dict) -> str:
    if pair.get("phase_key"):
        return f"{pair['project']} · {pair['phase_key']}"
    return pair["project"]


def pair_already_imported(pair: dict) -> bool:
    if not DB_PATH.exists():
        return False
    project_key = project_key_for_pair(pair)
    with sqlite3.connect(DB_PATH) as conn:
        old_exists = conn.execute(
            "select 1 from pricelist_versions where project_name=? and source_file=? limit 1",
            (project_key, pair["old_file"]),
        ).fetchone()
        new_exists = conn.execute(
            "select 1 from pricelist_versions where project_name=? and source_file=? limit 1",
            (project_key, pair["new_file"]),
        ).fetchone()
    return bool(old_exists and new_exists)


def main() -> int:
    args = parse_args()
    if not DRIVE_STATE_PATH.exists():
        print(f"[ERROR] Missing {DRIVE_STATE_PATH}")
        return 1
    state = json.loads(DRIVE_STATE_PATH.read_text(encoding="utf-8"))
    logs = read_recent_logs(args.hours)
    pairs, unmatched = build_pairs(logs, state)
    existing_keys = {
        (pair.get("project", ""), pair.get("new_file_id") or pair.get("new_file", ""), pair.get("old_file_id") or pair.get("old_file", ""))
        for pair in pairs
    }
    state_pairs, state_unmatched = build_state_pairs(state, args.hours, existing_keys)
    pairs.extend(state_pairs)
    unmatched.extend(state_unmatched)
    if args.limit:
        pairs = pairs[: args.limit]

    print(f"Recent logs: {len(logs)}")
    print(f"Matched new/old price-list pairs: {len(pairs)}")
    print(f"Unmatched uploaded price lists: {len(unmatched)}")
    for pair in pairs:
        print(f"[PAIR] {pair['project']} :: {pair['old_file']} -> {pair['new_file']}")
    if unmatched:
        print("\n[UNMATCHED]")
        for row in unmatched:
            print(f"- {row['project']} :: {row['file']} ({row['reason']})")

    if args.dry_run:
        return 0

    uk_module = load_uk_update_module()
    if args.reset_db:
        clear_database()
    if DOWNLOAD_DIR.exists():
        shutil.rmtree(DOWNLOAD_DIR)
    service = uk_module.auth()
    results = []
    for pair in pairs:
        if not args.reset_db and pair_already_imported(pair):
            results.append({**pair, "skipped": "already imported"})
            continue
        if not pair.get("new_file_id") or not pair.get("old_file_id"):
            results.append({**pair, "error": "missing Drive file id"})
            continue
        try:
            old_path, new_path = download_pair(service, pair)
            results.append(import_pair(pair, old_path, new_path))
        except Exception as exc:
            results.append({**pair, "error": str(exc)})

    report_path = SCRIPT_DIR / "unit_change_import_report.json"
    report_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nImport report: {report_path}")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
