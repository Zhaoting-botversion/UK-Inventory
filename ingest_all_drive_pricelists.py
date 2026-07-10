from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sqlite3
import sys
from importlib.machinery import SourcelessFileLoader
from pathlib import Path

from unit_change_engine import DB_PATH, PRICE_FILE_EXTENSIONS, extract_price_records, insert_version


SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
WORK_PROJECTS_DIR = BASE_DIR.parent
DRIVE_STATE_PATH = SCRIPT_DIR / "drive_state.json"
UK_UPDATE_SCRIPT = WORK_PROJECTS_DIR / "迁移资料到Google Drive" / "uk_update_pricelists.py"
UK_UPDATE_PYC = WORK_PROJECTS_DIR / "迁移资料到Google Drive" / "__pycache__" / "uk_update_pricelists.cpython-312.pyc"
DOWNLOAD_DIR = Path(r"C:\tmp\UK_Inventory_All_Drive_Pricelists")
REPORT_PATH = SCRIPT_DIR / "all_drive_unit_inventory_audit.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit and ingest all Drive price lists into unit inventory.")
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit", help="Audit Drive price list coverage without downloading files.")
    audit.add_argument("--report", type=Path, default=REPORT_PATH)

    ingest = sub.add_parser("ingest", help="Download and ingest Drive price lists.")
    ingest.add_argument("--limit", type=int, default=0, help="Limit number of files to ingest.")
    ingest.add_argument("--project", default="", help="Only ingest projects containing this text.")
    ingest.add_argument("--reset-db", action="store_true", help="Delete inventory_units.sqlite before ingesting.")
    ingest.add_argument("--report", type=Path, default=REPORT_PATH)
    return parser.parse_args()


def load_uk_update_module():
    if UK_UPDATE_PYC.exists():
        loader = SourlessFileLoaderCompat("uk_update_cached", str(UK_UPDATE_PYC))
        module = loader.load_module()
    else:
        spec = importlib.util.spec_from_file_location("uk_update_pricelists", UK_UPDATE_SCRIPT)
        if not spec or not spec.loader:
            raise RuntimeError(f"Cannot load {UK_UPDATE_SCRIPT}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    module.SCRIPT_DIR = WORK_PROJECTS_DIR / "迁移资料到Google Drive"
    module.LOG_DIR = module.SCRIPT_DIR / "logs"
    module.PRICE_FOLDER = "价单 Price List"
    module.BROCHURE_FOLDER = "楼盘资料 Brochure, Factsheet & Floorplan"
    module.OLD_PRICE_NAMES = ["Old Pricelist旧价单", "Old Pricelist", "Old Pricelist 旧价单"]
    return module


class SourlessFileLoaderCompat(SourcelessFileLoader):
    """Keep cached uk_update_pricelists import isolated from the app module namespace."""


def normalize_phase(filename: str) -> str:
    value = Path(filename).stem.lower()
    value = re.sub(r"^(cn|en|zh|chinese|english)(?:\s*[-_]\s*|\s+)", " ", value)
    value = re.sub(r"\b(price\s*list|pricelist|prices|availability|customer|distribution)\b", " ", value)
    value = re.sub(r"\b\d{1,2}[._-]\d{1,2}[._-]\d{2,4}\b", " ", value)
    value = re.sub(r"\b\d{1,2}\s+[a-z]{3,9}\s+\d{2,4}\b", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value or Path(filename).stem.lower()


def base_project_name(name: str) -> str:
    return re.split(r"\s+[·]\s+", name or "", maxsplit=1)[0].strip()


def safe_part(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._ -]+", "_", value).strip(" ._") or "item"


def load_drive_state() -> dict:
    if not DRIVE_STATE_PATH.exists():
        raise FileNotFoundError(f"Missing {DRIVE_STATE_PATH}")
    return json.loads(DRIVE_STATE_PATH.read_text(encoding="utf-8"))


def price_file(row: dict) -> bool:
    return Path(row.get("file", "")).suffix.lower() in PRICE_FILE_EXTENSIONS


def latest_price_files(state: dict) -> list[dict]:
    rows = []
    for project_name, record in state.get("projects", {}).items():
        for item in record.get("latest_files", []):
            if not price_file(item):
                continue
            file_name = item.get("file", "")
            phase = normalize_phase(file_name)
            rows.append(
                {
                    "project": record.get("project", project_name),
                    "project_path": record.get("path", ""),
                    "price_folder_id": record.get("price_folder_id", ""),
                    "file": file_name,
                    "file_id": item.get("file_id", ""),
                    "file_url": item.get("file_url", ""),
                    "modified_at": item.get("modified_at", ""),
                    "price_date": item.get("price_date", ""),
                    "phase": phase,
                    "project_key": f"{record.get('project', project_name)} · {phase}",
                }
            )
    return rows


def db_coverage() -> dict:
    if not DB_PATH.exists():
        return {"project_keys": set(), "base_projects": set(), "versions": 0, "units": 0}
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT project_name, unit_count FROM pricelist_versions").fetchall()
    project_keys = {row[0] for row in rows}
    return {
        "project_keys": project_keys,
        "base_projects": {base_project_name(name) for name in project_keys},
        "versions": len(rows),
        "units": sum(int(row[1] or 0) for row in rows),
    }


def build_audit() -> dict:
    state = load_drive_state()
    files = latest_price_files(state)
    coverage = db_coverage()
    projects = state.get("projects", {})
    projects_with_price = {row["project"] for row in files}
    ingested_base = coverage["base_projects"]
    not_ingested_files = [row for row in files if row["project_key"] not in coverage["project_keys"]]
    not_ingested_projects = sorted({row["project"] for row in not_ingested_files})
    no_latest_price_projects = sorted(
        record.get("project", name)
        for name, record in projects.items()
        if not any(price_file(item) for item in record.get("latest_files", []))
    )
    return {
        "drive_projects": len(projects),
        "drive_projects_with_latest_price_files": len(projects_with_price),
        "drive_latest_price_files": len(files),
        "db_versions": coverage["versions"],
        "db_units_total_across_versions": coverage["units"],
        "db_project_keys": len(coverage["project_keys"]),
        "db_base_projects": len(ingested_base),
        "not_ingested_latest_price_files": len(not_ingested_files),
        "not_ingested_projects": len(not_ingested_projects),
        "projects_without_latest_price_files": len(no_latest_price_projects),
        "not_ingested_project_names": not_ingested_projects,
        "projects_without_latest_price_file_names": no_latest_price_projects,
        "not_ingested_files": not_ingested_files,
    }


def download_file(service, module, row: dict) -> Path:
    target = DOWNLOAD_DIR / safe_part(row["project"]) / safe_part(row["phase"])
    return module.download_drive_file_to(service, row["file_id"], row["file"], target)


def ingest_rows(rows: list[dict], reset_db: bool = False) -> list[dict]:
    if reset_db and DB_PATH.exists():
        DB_PATH.unlink()
    module = load_uk_update_module()
    service = module.auth()
    results = []
    for index, row in enumerate(rows, start=1):
        result = dict(row)
        try:
            local_path = download_file(service, module, row)
            records, parse_note = extract_price_records(local_path)
            version_id = insert_version(
                row["project_key"],
                row["file"],
                str(local_path),
                row.get("price_date") or Path(row["file"]).stem,
                records,
                parse_note,
            )
            result.update(
                {
                    "status": "ingested",
                    "version_id": version_id,
                    "unit_count": len(records),
                    "parse_note": parse_note,
                    "local_path": str(local_path),
                    "index": index,
                }
            )
        except Exception as exc:
            result.update({"status": "error", "error": str(exc), "index": index})
        results.append(result)
        print(json.dumps(result, ensure_ascii=False))
    return results


def main() -> int:
    args = parse_args()
    if args.command == "audit":
        audit = build_audit()
        args.report.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({k: v for k, v in audit.items() if not isinstance(v, list)}, ensure_ascii=False, indent=2))
        print(f"Report: {args.report}")
        return 0
    if args.command == "ingest":
        audit = build_audit()
        rows = audit["not_ingested_files"]
        if args.project:
            rows = [row for row in rows if args.project.lower() in row["project"].lower()]
        if args.limit:
            rows = rows[: args.limit]
        results = ingest_rows(rows, reset_db=args.reset_db)
        audit["ingest_results"] = results
        args.report.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
