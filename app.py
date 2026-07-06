from __future__ import annotations

import ast
import base64
import html
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse


BASE_DIR = Path(__file__).resolve().parents[1]
LOG_DIR = BASE_DIR / "logs"
BERKELEY_SCRIPT = BASE_DIR / "berkeley_update_pricelists.py"
DRIVE_STATE_PATH = Path(__file__).resolve().parent / "drive_state.json"
APP_TITLE = "英国销控看板"
HOST = os.environ.get("HOST") or ("0.0.0.0" if "PORT" in os.environ else "127.0.0.1")
PORT = int(os.environ.get("PORT", "8765"))
DASHBOARD_USER = os.environ.get("DASHBOARD_USER", "")
DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")


CITY_HINTS = {
    "Birmingham": ["Glasswater Locks"],
    "Berkshire / Slough": ["Horlicks Quarter"],
    "Buckinghamshire": ["Abbey Barn Park", "Highcroft"],
    "Hampshire": ["Hartland Village"],
    "Hertfordshire": ["Hertford Locks"],
    "Kent": ["Foal Hurst Green", "Oakhill"],
    "Oxfordshire": ["Leighwood Fields", "Winterbrook Meadows"],
    "Reading": ["Reading Riverworks", "Bankside Gardens"],
    "Watford": ["The Exchange Watford"],
    "Maidenhead": ["Spring Hill"],
}

DEVELOPER_OVERRIDES = {
    "E3 - Oxbow": "EcoWorld London",
    "EC2 - One Crown Place": "MTD Group",
    "EC3 - One Bishopsgate Plaza - Completed": "UOL Group",
    "E14 - 25 Cuba Street": "Canary Wharf Group",
    "E14 - 8 Harbord Square - Off market": "Canary Wharf Group",
    "E14 - Aspen": "Far East Consortium",
    "E14 - Goodluck Hope": "Ballymore",
    "E14 - Landmark Pinnacle": "Chalegrove Properties",
    "E14 - One Park Drive &10 Park Drive- - Completed": "Canary Wharf Group",
    "E14 - One Thames Quay": "Chalegrove Properties",
    "E14 - Rivermark": "Barratt London",
    "E16 - Riverscape": "Ballymore",
    "SE1 - The Edit": "Mount Anvil",
    "SE1 - Pinks Mews": "Sons and Co",
    "SE1 - Triptych Bankside - Completion Q3 2023": "JTRE London",
    "SE10 - Greenwich Peninsula -Est. Completion Q3-Q4 2025": "Knight Dragon",
    "SE11 - Graphite Square": "Third.i",
    "SW1X - Belgravia Gate": "Wainbridge",
    "SW5 - One Cluny Mews": "Salboy",
    "SW6 - Hurlingham Waterfront - Est. Completion Q3 2025": "Rockwell Property",
    "SW6 - Hurlingham Waterfront - Est. Completion Q3 2026": "Rockwell Property",
    "SW8 - Key Bridge": "Mount Anvil",
    "SW11 - Battersea Power Station": "Battersea Power Station Development Company",
    "SW11 - Embassy Gardens - The Capston": "Ballymore",
    "SW11 - One Clapham Junction - Completion  from Q1-Q3 2025": "Mount Anvil",
    "TW8 - The Brentford Project": "Ballymore",
    "W1 - W1 Place-Completion Q1 2024": "Concord London",
    "W1H - The Bryanston-completed": "Almacantar",
    "W1U - 100 George Street": "Native Land",
    "W1U - Marylebone Square - completed": "Concord London",
    "W2 - 18 Porchester Garden-Completed": "Taylor Wimpey Central London",
    "W2 - Park Modern-completed": "Fenton Whelan",
    "W8 - Holland Park Gate - completed": "Lodha",
    "WC1A - Centre Point Residences": "Almacantar",
    "WC1X - Postmark, Farringdon": "Taylor Wimpey Central London",
}

COOPERATION_OVERRIDES = {
    "SW10 - Chelsea Finery": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "Mount Anvil"
    },
    "SW11 - Ransomes Wharf (London Square)": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "London Square"
    },
    "W14 - 100 Kensington - Est complete in Q1 2027": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "JLL"
    },
    "E14 - One Park Drive &10 Park Drive- - Completed": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "莱坊"
    },
    "E14 - 8 Harbord Square - Off market": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "莱坊"
    },
    "E14 - One Thames Quay": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "JLL"
    },
    "E14 - Landmark Pinnacle": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "Chalegrove"
    },
    "E14 - 25 Cuba Street": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "Ballymore"
    },
    "SE1 - Triptych Bankside - Completion Q3 2023": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "JTRE"
    },
    "W1 - 60 Curzon, Mayfair- Completed-Price on application": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "Brockton Everlast"
    },
    "W1J - One Carrington": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "Knight Frank 莱坊"
    },
    "W1K - Three Kings Yard": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "CBRE"
    },
    "W1J - 36 & 37 Hertfort Street": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "CIT"
    },
    "W1J - 6 Charles Street": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "DD"
    },
    "W1S - Mandarin Oriental The Residences Mayfair London": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "Clivedale"
    },
    "W1U - 100 George Street": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "Native Land"
    },
    "W1H - The Bryanston-completed": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "Almacantar"
    },
    "SW1- OWO - Completed": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "OHLA"
    },
    "SW1 - 8 Eaton Lane-Est.completion: Q1 2026": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "CIT"
    },
    "SW1W - Chelsea Barracks -Price on application": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "Qatari Diar"
    },
    "W2 - 18 Porchester Garden-Completed": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "CIT"
    },
    "W2 -The Whiteley-completed": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "Voluran/Finchatton"
    },
    "W8 - Holland Park Gate - completed": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "Lodha"
    },
    "W8 - Allen House-completed": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "Knight Frank 莱坊"
    },
    "W8 - One Kensington Gardens": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "Knight Frank 莱坊"
    },
    "SW1X - Knightsbridge Gate - Completed-Price on application": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "Knight Frank 莱坊"
    },
    "HA9 - Fulton & Fifth": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "GAL"
    },
    "EC3 - The Haydon - Completed": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "GAL"
    },
    "CR0 - Croydon (London Square)": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "London Square"
    },
    "SW8 - Nine Elms (London Square)": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "London Square"
    },
    "W12 - Television Centre - Est. Completion Q2 2027": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "莱坊"
    },
    "SE1 - Opus": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "莱坊/JLL"
    },
    "E3 - Bow Green": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "伯克利"
    },
    "SW1 - Ebury - Completed": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "JLL"
    },
    "W6 - Fulham Reach": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "伯克利"
    },
    "N4 - Woodberry Down": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "伯克利"
    },
    "EN4 - Trent Park": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "伯克利"
    },
    "SW1E - No.1 Palace Street": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "NorthAcre"
    },
    "SW8 - Key Bridge": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "Hamptons"
    },
    "W6 - Artisi - Completed": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "莱坊"
    },
    "SW6 - Chelsea Waterfront Tower East": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "长江实业"
    },
    "W12 - White City Living": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "伯克利"
    },
    "NW7 - The Claves": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "Royal Dock"
    },
    "EC1 - The Arc - Est. Completion Q2 2023": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "莱坊"
    },
    "SW11 - Embassy Gardens - The Capston": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "Ballymore"
    },
    "E14 - Aspen": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "莱坊"
    },
    "E3 - Twelvetrees Park": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "伯克利"
    },
    "UB1 - The Green Quarter": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "伯克利"
    },
    "EC3 - One Bishopsgate Plaza - Completed": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "莱坊"
    },
    "HA0 - Grand Union": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "伯克利"
    },
    "SW11 - Battersea Power Station": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "Savills"
    },
    "SW6 - King's Road Park": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "伯克利"
    },
    "E1 - London Dock": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "伯克利"
    },
    "EC2A - Principal Tower": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "Concord"
    },
    "WC1X - Postmark, Farringdon": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "Taylor Wimpey"
    },
    "SW8 - River Park Tower": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "富力"
    },
    "WD17 - The Exchange Watford": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "伯克利"
    },
    "W2 - West End Gate": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "伯克利"
    },
    "SE18 - Royal Arsenal Riverside": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "伯克利"
    },
    "SW1 - The Broadway-Completed": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "JLL"
    },
    "W2 - Trillium": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "伯克利"
    },
    "E2 - Regent's View": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "伯克利"
    },
    "SW18 - Wandsworth Mills": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "伯克利"
    },
    "SE1 - Bermondsey Place": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "伯克利"
    },
    "E16 - Riverscape": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "Ballymore"
    },
    "TW8 - The Brentford Project": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "Ballymore"
    },
    "E14 - Goodluck Hope": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "Ballymore"
    },
    "EC1V - Angel Village - Est. complete from Q4 2026": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "CBRE"
    },
    "NW6 - The Clay Yard": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "莱坊"
    },
    "SE1 - SEVEN Southbank Place - Est Complete Jan 2026": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "莱坊/JLL"
    },
    "SE16 - The Founding, Canada Water - Est.completion mid 2025": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "莱坊/JLL"
    },
    "SW11 - The HiLight - Est Completion Q2 2026": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "莱坊/JLL"
    },
    "SE17 - The Wilderly": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "莱坊/JLL"
    },
    "NW1 - Piano Studios": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "莱坊"
    },
    "SW8 - The Newton": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "CBRE"
    },
    "W1U - Marylebone Square - completed": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "Concord"
    }
}


def load_projects() -> dict[str, str]:
    if not BERKELEY_SCRIPT.exists():
        return {}
    text = BERKELEY_SCRIPT.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"PROJECTS\s*=\s*(\{.*?\})\n\nALIASES", text, re.S)
    if not match:
        return {}
    return ast.literal_eval(match.group(1))


def drive_folder_url(folder_id: str) -> str:
    return f"https://drive.google.com/drive/folders/{folder_id}"


def drive_file_url(file_id: str) -> str:
    return f"https://drive.google.com/file/d/{file_id}/view"


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def price_date_from_name(name: str) -> str:
    patterns = [
        r"(\d{1,2}[._-]\d{1,2}[._-]\d{2,4})",
        r"(\d{1,2}\.\d{1,2}\.\d{2,4})",
        r"(\d{1,2}\s+[A-Za-z]+\s+\d{4})",
        r"([A-Za-z]+\s+\d{4})",
    ]
    for pattern in patterns:
        match = re.search(pattern, name)
        if match:
            return match.group(1).replace("_", ".")
    return ""


def infer_city(project: str) -> str:
    for city, names in CITY_HINTS.items():
        if project in names:
            return city
    return "London"


def infer_developer(project: str) -> str:
    if project in DEVELOPER_OVERRIDES:
        return DEVELOPER_OVERRIDES[project]
    if "london square" in project.lower():
        return "London Square"
    return "未分类"


def infer_cooperation(project: str) -> dict[str, str]:
    return COOPERATION_OVERRIDES.get(project, {
        "cooperation_level": "未记录",
        "cooperation_partner": "未记录",
    })


def normalize_project_for_file(project: str, file_name: str) -> str:
    low = file_name.lower()
    if low.startswith("rv-ready") or low.startswith("rv-westwood") or low.startswith("rv-wright"):
        return "Regent's View"
    return project


def read_logs() -> list[dict]:
    runs = []
    if not LOG_DIR.exists():
        return runs
    for path in sorted(LOG_DIR.glob("berkeley_update_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        payload["_path"] = str(path)
        payload["_name"] = path.name
        payload["_mtime"] = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
        runs.append(payload)
    runs.sort(key=lambda row: row.get("finished_at") or row.get("started_at") or row.get("_mtime") or "", reverse=True)
    return runs


def read_drive_state() -> dict:
    if not DRIVE_STATE_PATH.exists():
        return {}
    try:
        return json.loads(DRIVE_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def build_data() -> dict:
    project_ids = load_projects()
    runs = read_logs()
    drive_state = read_drive_state()
    drive_projects = drive_state.get("projects", {})
    use_drive_snapshot = bool(drive_projects)
    projects: dict[str, dict] = {}
    updates = []

    for name, folder_id in project_ids.items():
        projects[name] = {
            "name": name,
            "city": infer_city(name),
            "developer": infer_developer(name),
            **infer_cooperation(name),
            "folder_id": folder_id,
            "folder_url": drive_folder_url(folder_id),
            "latest_file": "",
            "latest_file_url": "",
            "latest_date": "",
            "last_updated_at": "",
            "uploaded_count": 0,
            "archived_count": 0,
            "files": [],
            "archived": [],
            "data_source": "日志",
            "price_folder_url": "",
            "old_price_folder_url": "",
            "notes": [],
        }

    for run in runs:
        run_time = run.get("finished_at") or run.get("started_at") or run.get("_mtime")
        uploaded = run.get("uploaded", [])
        archived = run.get("archived", [])

        for row in uploaded:
            project = normalize_project_for_file(row.get("project", "Unknown"), row.get("file", ""))
            if project not in projects:
                projects[project] = {
                    "name": project,
                    "city": infer_city(project),
                    "developer": infer_developer(project),
                    **infer_cooperation(project),
                    "folder_id": "",
                    "folder_url": "",
                    "latest_file": "",
                    "latest_file_url": "",
                    "latest_date": "",
                    "last_updated_at": "",
                    "uploaded_count": 0,
                    "archived_count": 0,
                    "files": [],
                    "archived": [],
                    "data_source": "日志",
                    "price_folder_url": "",
                    "old_price_folder_url": "",
                    "notes": [],
                }
            file_id = row.get("id", "")
            file_name = row.get("file", "")
            file_info = {
                "file": file_name,
                "file_id": file_id,
                "file_url": drive_file_url(file_id) if file_id else "",
                "run_time": run_time,
                "price_date": price_date_from_name(file_name),
                "log": run.get("_name", ""),
            }
            projects[project]["files"].append(file_info)
            projects[project]["uploaded_count"] += 1
            if not projects[project]["last_updated_at"] or run_time > projects[project]["last_updated_at"]:
                projects[project]["last_updated_at"] = run_time
                projects[project]["latest_file"] = file_name
                projects[project]["latest_file_url"] = file_info["file_url"]
                projects[project]["latest_date"] = file_info["price_date"]

            updates.append({
                "type": "uploaded",
                "project": project,
                "file": file_name,
                "file_url": file_info["file_url"],
                "run_time": run_time,
                "log": run.get("_name", ""),
            })

        for row in archived:
            project = normalize_project_for_file(row.get("project", "Unknown"), row.get("file", ""))
            if project not in projects:
                continue
            item = {
                "file": row.get("file", ""),
                "old_folder": row.get("old_folder", ""),
                "run_time": run_time,
                "log": run.get("_name", ""),
            }
            projects[project]["archived"].append(item)
            projects[project]["archived_count"] += 1
            updates.append({
                "type": "archived",
                "project": project,
                "file": item["file"],
                "file_url": "",
                "run_time": run_time,
                "log": run.get("_name", ""),
            })

    if use_drive_snapshot:
        projects = {}

    for project_name, state in drive_projects.items():
        if project_name not in projects:
            projects[project_name] = {
                "name": project_name,
                "city": infer_city(project_name),
                "developer": infer_developer(project_name),
                **infer_cooperation(project_name),
                "folder_id": state.get("folder_id", ""),
                "folder_url": state.get("folder_url", ""),
                "latest_file": "",
                "latest_file_url": "",
                "latest_date": "",
                "last_updated_at": "",
                "uploaded_count": 0,
                "archived_count": 0,
                "files": [],
                "archived": [],
                "data_source": "Drive",
                "price_folder_url": "",
                "old_price_folder_url": "",
                "notes": [],
            }

        project = projects[project_name]
        latest_files = state.get("latest_files", [])
        old_files = state.get("old_files", [])
        project["data_source"] = "Drive"
        project["city"] = state.get("city") or project.get("city") or infer_city(project_name)
        project["developer"] = state.get("developer") or project.get("developer") or infer_developer(project_name)
        cooperation = infer_cooperation(project_name)
        project["cooperation_level"] = state.get("cooperation_level") or project.get("cooperation_level") or cooperation["cooperation_level"]
        project["cooperation_partner"] = state.get("cooperation_partner") or project.get("cooperation_partner") or cooperation["cooperation_partner"]
        project["path"] = state.get("path", "")
        project["folder_url"] = state.get("folder_url") or project.get("folder_url", "")
        project["price_folder_url"] = state.get("price_folder_url", "")
        project["old_price_folder_url"] = state.get("old_price_folder_url", "")
        project["notes"] = state.get("notes", [])
        project["files"] = [
            {
                "file": row.get("file", ""),
                "file_id": row.get("file_id", ""),
                "file_url": row.get("file_url", ""),
                "run_time": row.get("modified_at", ""),
                "price_date": row.get("price_date", ""),
                "log": "Google Drive 当前状态",
            }
            for row in latest_files
        ]
        project["archived"] = [
            {
                "file": row.get("file", ""),
                "old_folder": "Old Pricelist",
                "run_time": row.get("modified_at", ""),
                "log": "Google Drive 当前状态",
            }
            for row in old_files
        ]
        project["uploaded_count"] = len(project["files"])
        project["archived_count"] = len(project["archived"])
        if project["files"]:
            latest = project["files"][0]
            project["latest_file"] = latest["file"]
            project["latest_file_url"] = latest["file_url"]
            project["latest_date"] = latest["price_date"]
            project["last_updated_at"] = latest["run_time"]

    if use_drive_snapshot and not updates:
        for project in projects.values():
            for row in project["files"]:
                updates.append({
                    "type": "uploaded",
                    "project": project["name"],
                    "file": row.get("file", ""),
                    "file_url": row.get("file_url", ""),
                    "run_time": row.get("run_time", ""),
                    "log": "Google Drive 当前快照",
                })

    return {
        "projects": sorted(projects.values(), key=lambda row: (row["city"], row["name"])),
        "updates": sorted(updates, key=lambda row: row["run_time"] or "", reverse=True),
        "runs": runs,
        "drive_state": drive_state,
    }


def e(value: object) -> str:
    return html.escape(str(value or ""))


def fmt_time(value: str) -> str:
    dt = parse_dt(value)
    if not dt:
        return value or ""
    return dt.strftime("%Y-%m-%d %H:%M")


def is_recent(value: str, days: int) -> bool:
    dt = parse_dt(value)
    if not dt:
        return False
    now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
    return dt >= now - timedelta(days=days)


PRIME_CENTRAL_LONDON_DISTRICTS = {
    "W1",
    "W2",
    "W8",
    "SW1",
    "SW3",
    "SW7",
    "WC1",
    "WC2",
}

CENTRAL_LONDON_DISTRICTS = {
    "EC1",
    "EC2",
    "EC3",
    "EC4",
    "SE1",
    "NW1",
    "NW3",
    "NW8",
}

EAST_LONDON_DISTRICTS = {
    "E1",
    "E2",
    "E3",
    "E10",
    "E14",
    "E16",
    "SE8",
    "SE10",
    "SE18",
}

WEST_SOUTHWEST_LONDON_DISTRICTS = {
    "W3",
    "W4",
    "W5",
    "W6",
    "W10",
    "W11",
    "W12",
    "W14",
}

GREATER_LONDON_DISTRICTS = {
    "BR",
    "CR",
    "DA",
    "HA",
    "RM",
    "WD",
    "CM",
    "HP",
    "OX",
}

MARKET_ORDER = [
    "Prime Central London",
    "伦敦核心区",
    "伦敦东区 / 金丝雀码头 / Royal Docks",
    "伦敦西区 / 西南区",
    "伦敦北区 / 西北区",
    "大伦敦",
    "Manchester",
    "Birmingham",
    "Reading / Berkshire",
    "其他英国区域",
]

DISPLAY_LABELS = {
    "Manchester": "曼彻斯特",
    "Birmingham": "伯明翰",
    "Reading": "雷丁",
    "Berkshire": "伯克郡",
    "Reading / Berkshire": "雷丁 / 伯克郡",
    "Berkshire / Slough": "伯克郡 / 斯劳",
    "Others": "其他英国区域",
    "London": "伦敦",
    "Prime Central London": "Prime Central London 核心伦敦",
    "Google Drive": "网盘",
    "Drive": "网盘",
    "Google Drive 当前状态": "网盘当前状态",
    "Google Drive 当前快照": "网盘当前快照",
    "Old Pricelist": "历史价单",
}


def postcode_prefix(name: str) -> str:
    head = name.split(" - ", 1)[0].strip().upper()
    return head if re.match(r"^[A-Z]{1,2}\d", head) or head.startswith(("WC", "EC", "SW", "NW", "SE")) else ""


def postcode_district(prefix: str) -> str:
    match = re.match(r"^([A-Z]{1,2}\d{1,2})", prefix.upper())
    return match.group(1) if match else prefix.upper()


def display_label(value: str) -> str:
    return DISPLAY_LABELS.get(value, value)


def display_path(value: str) -> str:
    text = value or ""
    replacements = {
        "UK 英国": "英国",
        "London 伦敦": "伦敦",
        "Manchester 曼彻斯特": "曼彻斯特",
        "Birmingham 伯明翰": "伯明翰",
        "Others 其他": "其他英国区域",
        "Google Drive": "网盘",
        "Drive": "网盘",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text


def market_group(project: dict | str) -> str:
    if isinstance(project, dict):
        name = project.get("name", "")
        city = project.get("city", "")
    else:
        name = project
        city = ""

    prefix = postcode_prefix(name)
    district = postcode_district(prefix)
    area = re.match(r"^[A-Z]+", district)
    area_code = area.group(0) if area else district
    if city == "Manchester":
        return "Manchester"
    if city == "Birmingham":
        return "Birmingham"
    if city in {"Reading", "Berkshire / Slough"} or prefix.startswith(("RG", "SL")):
        return "Reading / Berkshire"
    if city and city not in {"London", "Others"}:
        return city

    if district in PRIME_CENTRAL_LONDON_DISTRICTS:
        return "Prime Central London"
    if district in CENTRAL_LONDON_DISTRICTS:
        return "伦敦核心区"
    if district in EAST_LONDON_DISTRICTS:
        return "伦敦东区 / 金丝雀码头 / Royal Docks"
    if district in WEST_SOUTHWEST_LONDON_DISTRICTS or area_code in {"SW", "TW"}:
        return "伦敦西区 / 西南区"
    if area_code in {"N", "NW"}:
        return "伦敦北区 / 西北区"
    if area_code in GREATER_LONDON_DISTRICTS:
        return "大伦敦"
    if city == "London":
        return "大伦敦"
    return "其他英国区域"


def group_rank(name: str) -> tuple[int, str]:
    if name in MARKET_ORDER:
        return (MARKET_ORDER.index(name), name)
    return (len(MARKET_ORDER), name)


def followup_signal(project: dict) -> dict:
    score = 0
    reasons = []
    group = market_group(project)
    latest_file = project.get("latest_file", "")
    text = " ".join([latest_file] + [row.get("file", "") for row in project.get("files", [])]).lower()

    if is_recent(project.get("last_updated_at", ""), 1):
        score += 35
        reasons.append("今天有价单或资料更新")
    elif is_recent(project.get("last_updated_at", ""), 3):
        score += 25
        reasons.append("近3天有更新")
    elif is_recent(project.get("last_updated_at", ""), 7):
        score += 15
        reasons.append("本周有更新")

    if project.get("archived_count", 0):
        score += 15
        reasons.append("有旧价单归档，说明价单版本发生变化")

    if group == "Prime Central London":
        score += 25
        reasons.append("Prime Central London 项目")
    elif group == "伦敦核心区":
        score += 18
        reasons.append("伦敦核心区项目")
    elif group in {"伦敦东区 / 金丝雀码头 / Royal Docks", "伦敦西区 / 西南区"}:
        score += 12
        reasons.append(display_label(group))
    elif group in {"Manchester", "Birmingham", "Reading / Berkshire"}:
        score += 6
        reasons.append(display_label(group))

    developer = project.get("developer", "")
    if developer in {"Berkeley Group", "London Square"}:
        score += 10
        reasons.append(f"{developer} 项目")

    file_count = project.get("uploaded_count", 0)
    if file_count >= 2:
        score += min(10, file_count * 2)
        reasons.append(f"当前识别到 {file_count} 个最新价单文件")

    keyword_rules = [
        (("discount", "reduced", "reduction", "incentive", "offer", "summer fete"), 14, "文件名出现优惠/活动信号"),
        (("ready", "move in", "completed", "completion"), 10, "文件名出现现房或准现房信号"),
        (("new", "release", "availability"), 8, "文件名出现新放出或可售清单信号"),
        (("penthouse", "private", "collection", "exclusive"), 8, "文件名出现稀缺产品信号"),
        (("price list", "pricelist", "prices"), 6, "识别到价单文件"),
    ]
    for keywords, points, reason in keyword_rules:
        if any(keyword in text for keyword in keywords):
            score += points
            reasons.append(reason)

    unique_reasons = []
    for reason in reasons:
        if reason not in unique_reasons:
            unique_reasons.append(reason)

    return {
        "score": min(score, 100),
        "reasons": unique_reasons[:4],
    }


def followup_projects(projects: list[dict]) -> list[dict]:
    rows = []
    for project in projects:
        signal = followup_signal(project)
        if signal["score"] < 35:
            continue
        row = dict(project)
        row["followup_score"] = signal["score"]
        row["followup_reasons"] = signal["reasons"]
        rows.append(row)
    rows.sort(key=lambda row: (row["followup_score"], row.get("last_updated_at", "")), reverse=True)
    return rows[:6]


def layout(title: str, content: str, active: str = "") -> bytes:
    nav = [
        ("/", "首页"),
        ("/projects", "项目总览"),
        ("/updates", "更新记录"),
    ]
    nav_html = "".join(
        f'<a class="{"active" if active == href else ""}" href="{href}">{label}</a>'
        for href, label in nav
    )
    body = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>{e(title)} · {APP_TITLE}</title>
  <style>
    :root {{
      --bg: #f6f7f9;
      --panel: #ffffff;
      --text: #17202a;
      --muted: #667085;
      --line: #d9dee7;
      --accent: #0f766e;
      --accent-soft: #d9f4ef;
      --warn: #b45309;
      --blue: #1d4ed8;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: Arial, Helvetica, sans-serif; background: var(--bg); color: var(--text); }}
    header {{ background: var(--panel); border-bottom: 1px solid var(--line); padding: 14px 28px; display: flex; justify-content: space-between; align-items: center; gap: 20px; position: sticky; top: 0; z-index: 10; }}
    .brand {{ font-size: 18px; font-weight: 700; white-space: nowrap; }}
    nav {{ display: flex; gap: 4px; }}
    nav a {{ color: var(--muted); text-decoration: none; padding: 8px 12px; border-radius: 6px; font-size: 14px; }}
    nav a.active, nav a:hover {{ color: var(--accent); background: var(--accent-soft); }}
    main {{ padding: 24px 28px 40px; max-width: 1440px; margin: 0 auto; }}
    h1 {{ font-size: 26px; margin: 0 0 18px; }}
    h2 {{ font-size: 18px; margin: 24px 0 10px; }}
    .grid {{ display: grid; gap: 14px; grid-template-columns: repeat(4, minmax(0, 1fr)); }}
    .metric {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 16px; }}
    .metric .label {{ color: var(--muted); font-size: 13px; }}
    .metric .value {{ font-size: 28px; font-weight: 700; margin-top: 8px; }}
    .toolbar {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 12px; display: flex; gap: 10px; align-items: center; margin-bottom: 14px; flex-wrap: wrap; }}
    input, select {{ border: 1px solid var(--line); border-radius: 6px; padding: 8px 10px; font-size: 14px; min-height: 36px; }}
    input {{ min-width: 260px; flex: 1; }}
    table {{ width: 100%; border-collapse: collapse; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 10px 12px; text-align: left; vertical-align: top; font-size: 14px; }}
    th {{ color: #344054; background: #eef1f5; font-weight: 700; }}
    tr:last-child td {{ border-bottom: 0; }}
    a {{ color: var(--blue); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .muted {{ color: var(--muted); }}
    .tag {{ display: inline-block; padding: 3px 8px; border-radius: 999px; background: #eef2ff; color: #3730a3; font-size: 12px; white-space: nowrap; }}
    .tag.today {{ background: #dcfce7; color: #166534; }}
    .tag.week {{ background: #fef3c7; color: var(--warn); }}
    .tag.archived {{ background: #f1f5f9; color: #475569; }}
    .split {{ display: grid; grid-template-columns: 1.1fr .9fr; gap: 16px; }}
    .panel {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 14px; }}
    .section-head {{ display: flex; justify-content: space-between; align-items: end; gap: 16px; margin: 26px 0 12px; }}
    .section-head h2 {{ margin: 0; }}
    .section-head .muted {{ max-width: 680px; line-height: 1.5; }}
    .priority-grid {{ display: grid; gap: 12px; grid-template-columns: repeat(3, minmax(0, 1fr)); }}
    .priority-card {{ background: var(--panel); border: 1px solid var(--line); border-left: 4px solid var(--accent); border-radius: 8px; padding: 14px; min-height: 132px; }}
    .priority-card .project-name {{ font-size: 16px; font-weight: 700; line-height: 1.35; }}
    .priority-card .file-name {{ margin-top: 10px; color: #344054; line-height: 1.35; overflow-wrap: anywhere; }}
    .priority-card .meta {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; color: var(--muted); font-size: 13px; }}
    .followup-grid {{ display: grid; gap: 12px; grid-template-columns: repeat(3, minmax(0, 1fr)); }}
    .followup-card {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 14px; min-height: 170px; }}
    .followup-card.high {{ border-color: #99d8cf; background: #f4fbf9; }}
    .followup-head {{ display: flex; justify-content: space-between; gap: 10px; align-items: flex-start; }}
    .score-badge {{ border-radius: 999px; background: var(--accent-soft); color: var(--accent); padding: 4px 9px; font-size: 12px; font-weight: 700; white-space: nowrap; }}
    .reason-list {{ margin: 10px 0 0; padding-left: 18px; color: #344054; line-height: 1.45; font-size: 13px; }}
    .market-grid {{ display: grid; gap: 12px; grid-template-columns: repeat(3, minmax(0, 1fr)); }}
    .market-card {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 14px; min-height: 180px; }}
    .market-card.featured {{ border-color: #99d8cf; background: #f4fbf9; }}
    .market-title {{ display: flex; justify-content: space-between; gap: 12px; align-items: baseline; }}
    .market-title strong {{ font-size: 16px; }}
    .count-pill {{ border: 1px solid var(--line); border-radius: 999px; padding: 2px 8px; color: #344054; font-size: 12px; background: #fff; white-space: nowrap; }}
    .project-list {{ list-style: none; margin: 12px 0 0; padding: 0; display: grid; gap: 8px; }}
    .project-list li {{ display: grid; gap: 3px; border-top: 1px solid #eef1f5; padding-top: 8px; }}
    .project-list li:first-child {{ border-top: 0; padding-top: 0; }}
    .small-meta {{ color: var(--muted); font-size: 12px; line-height: 1.35; }}
    .updates-grid {{ display: grid; gap: 12px; grid-template-columns: repeat(3, minmax(0, 1fr)); }}
    .update-group {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 14px; }}
    .update-row {{ display: grid; gap: 4px; border-top: 1px solid #eef1f5; padding-top: 10px; margin-top: 10px; }}
    .update-row:first-of-type {{ border-top: 0; padding-top: 0; margin-top: 12px; }}
    .empty {{ background: var(--panel); border: 1px dashed var(--line); border-radius: 8px; padding: 24px; color: var(--muted); }}
    @media (max-width: 1100px) {{ .priority-grid, .followup-grid, .market-grid, .updates-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} }}
    @media (max-width: 900px) {{ .grid, .split, .priority-grid, .followup-grid, .market-grid, .updates-grid {{ grid-template-columns: 1fr; }} header {{ align-items: flex-start; flex-direction: column; }} input {{ min-width: 100%; }} .section-head {{ display: block; }} }}
  </style>
</head>
<body>
  <header>
    <div class="brand">{APP_TITLE}</div>
    <nav>{nav_html}</nav>
  </header>
  <main>{content}</main>
</body>
</html>"""
    return body.encode("utf-8")


def filter_projects(projects: list[dict], query: dict[str, list[str]]) -> list[dict]:
    search = (query.get("q", [""])[0] or "").lower()
    city = query.get("city", [""])[0]
    developer = query.get("developer", [""])[0]
    status = query.get("status", [""])[0]
    rows = []
    for project in projects:
        haystack = f"{project['name']} {project['city']} {project['developer']}".lower()
        if search and search not in haystack:
            continue
        if city and project["city"] != city:
            continue
        if developer and project["developer"] != developer:
            continue
        if status == "today" and not is_recent(project["last_updated_at"], 1):
            continue
        if status == "week" and not is_recent(project["last_updated_at"], 7):
            continue
        if status == "updated" and not project["last_updated_at"]:
            continue
        rows.append(project)
    return rows


def project_status(project: dict) -> str:
    if is_recent(project["last_updated_at"], 1):
        return '<span class="tag today">今日更新</span>'
    if is_recent(project["last_updated_at"], 7):
        return '<span class="tag week">本周更新</span>'
    if project["last_updated_at"]:
        return '<span class="tag">有更新记录</span>'
    return '<span class="muted">暂无记录</span>'


def render_dashboard(data: dict) -> bytes:
    projects = data["projects"]
    updates = data["updates"]
    runs = data["runs"]
    updated_projects = {row["project"] for row in updates if row["type"] == "uploaded"}
    today_updates = [row for row in updates if is_recent(row["run_time"], 1)]
    recent_projects = sorted(
        [row for row in projects if is_recent(row["last_updated_at"], 7)],
        key=lambda row: row["last_updated_at"] or "",
        reverse=True,
    )
    latest_run = runs[0] if runs else {}
    latest_run_time = latest_run.get("finished_at") or latest_run.get("started_at") or latest_run.get("_mtime", "")
    drive_synced_at = data.get("drive_state", {}).get("synced_at", "")
    followups = followup_projects(projects)

    project_by_name = {row["name"]: row for row in projects}
    projects_by_group: dict[str, list[dict]] = defaultdict(list)
    updates_by_group: dict[str, list[dict]] = defaultdict(list)
    for project in projects:
        projects_by_group[market_group(project)].append(project)
    for row in updates:
        project = project_by_name.get(row["project"])
        updates_by_group[market_group(project or row["project"])].append(row)

    core_projects = projects_by_group.get("Prime Central London", [])
    core_recent = [row for row in recent_projects if market_group(row) == "Prime Central London"]
    priority_projects = (core_recent or sorted(core_projects, key=lambda row: row["last_updated_at"] or "", reverse=True))[:6]

    def project_link(name: str) -> str:
        if name in project_by_name:
            return f'<a href="/project/{quote(name)}">{e(name)}</a>'
        return e(name)

    priority_cards = "".join(
        f"""<article class="priority-card">
          <div class="project-name">{project_link(project['name'])}</div>
          <div class="file-name">{e(project['latest_file']) or '<span class="muted">暂无价单更新</span>'}</div>
          <div class="meta">
            <span>{e(display_label(market_group(project)))}</span>
            <span>{fmt_time(project['last_updated_at']) or "暂无更新时间"}</span>
            <span>{e(project['uploaded_count'])} 个价单</span>
          </div>
        </article>"""
        for project in priority_projects
    ) or '<div class="empty">暂无 Prime Central London 近期更新。</div>'

    followup_cards = "".join(
        f"""<article class="followup-card {'high' if project['followup_score'] >= 75 else ''}">
          <div class="followup-head">
            <div>
              <div class="project-name">{project_link(project['name'])}</div>
              <div class="small-meta">{e(display_label(market_group(project)))} · {fmt_time(project['last_updated_at']) or "暂无更新时间"}</div>
            </div>
            <span class="score-badge">建议查看</span>
          </div>
          <ul class="reason-list">{''.join(f'<li>{e(reason)}</li>' for reason in project['followup_reasons'])}</ul>
          <div class="file-name">{e(project['latest_file']) or '<span class="muted">暂无价单文件</span>'}</div>
        </article>"""
        for project in followups
    ) or '<div class="empty">暂无需要重点跟进的项目。</div>'

    market_cards = []
    for group_name in sorted(projects_by_group, key=group_rank):
        group_projects = sorted(projects_by_group[group_name], key=lambda row: row["last_updated_at"] or "", reverse=True)
        group_recent = [row for row in group_projects if row["last_updated_at"]][:5] or group_projects[:5]
        items = "".join(
            f"""<li>
              <div>{project_link(project['name'])}</div>
              <div class="small-meta">{fmt_time(project['last_updated_at']) or "暂无更新"} · {e(project['uploaded_count'])} 个价单</div>
            </li>"""
            for project in group_recent
        )
        market_cards.append(
            f"""<section class="market-card {'featured' if group_name == 'Prime Central London' else ''}">
              <div class="market-title"><strong>{e(display_label(group_name))}</strong><span class="count-pill">{len(group_projects)} 个项目</span></div>
              <ul class="project-list">{items}</ul>
            </section>"""
        )

    update_groups = []
    for group_name in sorted(updates_by_group, key=group_rank):
        group_updates = sorted(updates_by_group[group_name], key=lambda row: row["run_time"] or "", reverse=True)[:5]
        rows = "".join(
            f"""<div class="update-row">
              <div>{'<span class="tag archived">已归档</span>' if row['type'] == 'archived' else '<span class="tag today">新上传</span>'} {project_link(row['project'])}</div>
              <div>{file_link(row)}</div>
              <div class="small-meta">{fmt_time(row['run_time'])}</div>
            </div>"""
            for row in group_updates
        )
        update_groups.append(
            f"""<section class="update-group">
              <div class="market-title"><strong>{e(display_label(group_name))}</strong><span class="count-pill">{len(updates_by_group[group_name])} 条动态</span></div>
              {rows}
            </section>"""
        )

    content = f"""
      <h1>英国销控看板</h1>
      <div class="grid">
        <div class="metric"><div class="label">已追踪项目</div><div class="value">{len(projects)}</div></div>
        <div class="metric"><div class="label">有更新项目</div><div class="value">{len(updated_projects)}</div></div>
        <div class="metric"><div class="label">近24小时动态</div><div class="value">{len(today_updates)}</div></div>
        <div class="metric"><div class="label">最近同步时间</div><div class="value" style="font-size:18px">{fmt_time(drive_synced_at) or fmt_time(latest_run_time) or "暂无同步记录"}</div></div>
      </div>

      <div class="section-head">
        <h2>最新价单更新提醒</h2>
        <div class="muted">这里不是项目好坏评分，只是提示哪些项目近期价单或资料有变化，建议销售优先打开网盘确认。排序依据包括更新时间、是否有旧价单归档、开发商和文件名关键词等更新信号。</div>
      </div>
      <div class="followup-grid">{followup_cards}</div>

      <div class="section-head">
        <h2>Prime Central London 优先关注</h2>
        <div class="muted">优先显示 W1/W2/W8/SW1/SW3/WC1/WC2 等核心邮编项目。EC、SE1、NW 等仍保留在伦敦核心区，但不再和 PCL 混在同一组。</div>
      </div>
      <div class="priority-grid">{priority_cards}</div>

      <div class="section-head">
        <h2>按城市 / 区域查看楼盘</h2>
        <div class="muted">先看 Prime Central London，再看伦敦核心区、伦敦东区、其他伦敦板块和外地城市。每个区域只露出最近有动作的项目，完整清单可进项目总览筛选。</div>
      </div>
      <div class="market-grid">{''.join(market_cards)}</div>

      <div class="section-head">
        <h2>最新动态按区域归类</h2>
        <div class="muted">同一城市或板块的上传记录放在一起，避免最新动态变成一张难读的流水账。</div>
      </div>
      <div class="updates-grid">{''.join(update_groups)}</div>
    """
    return layout("首页", content, "/")


def file_link(row: dict) -> str:
    if row.get("file_url"):
        return f'<a href="{e(row["file_url"])}" target="_blank" rel="noreferrer">{e(row["file"])}</a>'
    return e(row.get("file", ""))


def render_projects(data: dict, query: dict[str, list[str]]) -> bytes:
    projects = filter_projects(data["projects"], query)
    all_projects = data["projects"]
    cities = sorted({row["city"] for row in all_projects})
    developers = sorted({row["developer"] for row in all_projects})
    selected_city = query.get("city", [""])[0]
    selected_developer = query.get("developer", [""])[0]
    selected_status = query.get("status", [""])[0]
    q = query.get("q", [""])[0]
    city_options = '<option value="">全部城市/区域</option>' + "".join(f'<option value="{e(city)}" {"selected" if city == selected_city else ""}>{e(display_label(city))}</option>' for city in cities)
    developer_options = '<option value="">全部开发商</option>' + "".join(f'<option {"selected" if item == selected_developer else ""}>{e(item)}</option>' for item in developers)
    status_options = "".join(
        f'<option value="{value}" {"selected" if selected_status == value else ""}>{label}</option>'
        for value, label in [
            ("", "全部状态"),
            ("today", "今日更新"),
            ("week", "本周更新"),
            ("updated", "有更新记录"),
        ]
    )
    rows = "".join(
        f"""<tr>
          <td><a href="/project/{quote(project['name'])}">{e(project['name'])}</a></td>
          <td>{e(display_label(project['city']))}</td>
          <td>{e(project['developer'])}</td>
          <td>{e(project.get('cooperation_level', '未记录'))}</td>
          <td>{e(project.get('cooperation_partner', '未记录'))}</td>
          <td>{project_status(project)}</td>
          <td>{e(project['latest_date'])}</td>
          <td>{fmt_time(project['last_updated_at'])}</td>
          <td>{e(project['uploaded_count'])}</td>
          <td>{e(display_label(project.get('data_source', '日志')))}</td>
          <td>{drive_link(project)}</td>
        </tr>"""
        for project in projects
    )
    content = f"""
      <h1>项目总览</h1>
      <form class="toolbar" method="get" action="/projects">
        <input name="q" value="{e(q)}" placeholder="搜索项目、城市、开发商">
        <select name="city">{city_options}</select>
        <select name="developer">{developer_options}</select>
        <select name="status">{status_options}</select>
        <button type="submit">筛选</button>
        <a href="/projects">重置</a>
      </form>
      <p class="muted">当前显示 {len(projects)} 个项目</p>
      <table>
        <thead><tr><th>项目</th><th>城市/区域</th><th>开发商</th><th>合作程度</th><th>合作方</th><th>状态</th><th>价单日期</th><th>最近更新</th><th>价单数量</th><th>数据来源</th><th>网盘</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    """
    return layout("项目总览", content, "/projects")


def render_projects(data: dict, query: dict[str, list[str]]) -> bytes:
    all_projects = data["projects"]
    cities = sorted({row["city"] for row in all_projects}, key=display_label)
    developers = sorted({row["developer"] for row in all_projects})
    selected_city = query.get("city", [""])[0]
    selected_developer = query.get("developer", [""])[0]
    selected_status = query.get("status", [""])[0]
    q = query.get("q", [""])[0]

    def filter_status(project: dict) -> str:
        if is_recent(project["last_updated_at"], 1):
            return "today"
        if is_recent(project["last_updated_at"], 7):
            return "week"
        if project["last_updated_at"]:
            return "updated"
        return ""

    city_options = '<option value="">全部城市/区域</option>' + "".join(
        f'<option value="{e(city)}" {"selected" if city == selected_city else ""}>{e(display_label(city))}</option>'
        for city in cities
    )
    developer_options = '<option value="">全部开发商</option>' + "".join(
        f'<option value="{e(item)}" {"selected" if item == selected_developer else ""}>{e(item)}</option>'
        for item in developers
    )
    status_options = "".join(
        f'<option value="{value}" {"selected" if selected_status == value else ""}>{label}</option>'
        for value, label in [
            ("", "全部状态"),
            ("today", "今日更新"),
            ("week", "本周更新"),
            ("updated", "有更新记录"),
        ]
    )

    rows = []
    for project in all_projects:
        city_label = display_label(project["city"])
        source_label = display_label(project.get("data_source", "日志"))
        group_label = display_label(market_group(project))
        search_text = " ".join(
            [
                project.get("name", ""),
                project.get("city", ""),
                city_label,
                group_label,
                project.get("developer", ""),
                project.get("cooperation_level", ""),
                project.get("cooperation_partner", ""),
                project.get("latest_file", ""),
                project.get("latest_date", ""),
                source_label,
            ]
        ).lower()
        rows.append(
            f"""<tr data-search="{e(search_text)}" data-city="{e(project['city'])}" data-developer="{e(project['developer'])}" data-status="{filter_status(project)}">
          <td><a href="/project/{quote(project['name'])}">{e(project['name'])}</a></td>
          <td>{e(city_label)}</td>
          <td>{e(project['developer'])}</td>
          <td>{e(project.get('cooperation_level', '未记录'))}</td>
          <td>{e(project.get('cooperation_partner', '未记录'))}</td>
          <td>{project_status(project)}</td>
          <td>{e(project['latest_date'])}</td>
          <td>{fmt_time(project['last_updated_at'])}</td>
          <td>{e(project['uploaded_count'])}</td>
          <td>{e(source_label)}</td>
          <td>{drive_link(project)}</td>
        </tr>"""
        )

    content = f"""
      <h1>项目总览</h1>
      <form class="toolbar" id="projectFilters" action="/projects">
        <input name="q" value="{e(q)}" placeholder="搜索项目、邮编、城市、开发商、合作方、价单文件" data-filter="q" autocomplete="off">
        <select name="city" data-filter="city">{city_options}</select>
        <select name="developer" data-filter="developer">{developer_options}</select>
        <select name="status" data-filter="status">{status_options}</select>
        <button type="button" id="resetProjectFilters">重置</button>
      </form>
      <p class="muted" id="projectCount">当前显示 {len(all_projects)} 个项目</p>
      <div id="noProjects" class="empty" style="display:none">没有找到匹配项目。</div>
      <table id="projectsTable">
        <thead><tr><th>项目</th><th>城市/区域</th><th>开发商</th><th>合作程度</th><th>合作方</th><th>状态</th><th>价单日期</th><th>最近更新</th><th>价单数量</th><th>数据来源</th><th>网盘</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
      <script>
      (() => {{
        const form = document.getElementById("projectFilters");
        const searchInput = form.querySelector('[data-filter="q"]');
        const citySelect = form.querySelector('[data-filter="city"]');
        const developerSelect = form.querySelector('[data-filter="developer"]');
        const statusSelect = form.querySelector('[data-filter="status"]');
        const rows = Array.from(document.querySelectorAll("#projectsTable tbody tr"));
        const table = document.getElementById("projectsTable");
        const countEl = document.getElementById("projectCount");
        const noProjects = document.getElementById("noProjects");
        const normalize = (value) => (value || "").toString().trim().toLowerCase();
        const statusMatches = (rowStatus, selected) => {{
          if (!selected) return true;
          if (selected === "week") return rowStatus === "today" || rowStatus === "week";
          if (selected === "updated") return rowStatus === "today" || rowStatus === "week" || rowStatus === "updated";
          return rowStatus === selected;
        }};
        const syncQuery = () => {{
          const params = new URLSearchParams();
          if (searchInput.value.trim()) params.set("q", searchInput.value.trim());
          if (citySelect.value) params.set("city", citySelect.value);
          if (developerSelect.value) params.set("developer", developerSelect.value);
          if (statusSelect.value) params.set("status", statusSelect.value);
          const query = params.toString();
          history.replaceState(null, "", query ? `${{location.pathname}}?${{query}}` : location.pathname);
        }};
        const applyFilters = () => {{
          const term = normalize(searchInput.value);
          const city = citySelect.value;
          const developer = developerSelect.value;
          const status = statusSelect.value;
          let visible = 0;
          rows.forEach((row) => {{
            const matched = (!term || row.dataset.search.includes(term))
              && (!city || row.dataset.city === city)
              && (!developer || row.dataset.developer === developer)
              && statusMatches(row.dataset.status, status);
            row.style.display = matched ? "" : "none";
            if (matched) visible += 1;
          }});
          countEl.textContent = `当前显示 ${{visible}} 个项目`;
          table.style.display = visible ? "" : "none";
          noProjects.style.display = visible ? "none" : "";
          syncQuery();
        }};
        const params = new URLSearchParams(location.search);
        if (params.has("q")) searchInput.value = params.get("q") || "";
        if (params.has("city")) citySelect.value = params.get("city") || "";
        if (params.has("developer")) developerSelect.value = params.get("developer") || "";
        if (params.has("status")) statusSelect.value = params.get("status") || "";
        form.addEventListener("submit", (event) => event.preventDefault());
        [searchInput, citySelect, developerSelect, statusSelect].forEach((el) => {{
          el.addEventListener("input", applyFilters);
          el.addEventListener("change", applyFilters);
        }});
        document.getElementById("resetProjectFilters").addEventListener("click", () => {{
          searchInput.value = "";
          citySelect.value = "";
          developerSelect.value = "";
          statusSelect.value = "";
          applyFilters();
        }});
        applyFilters();
      }})();
      </script>
    """
    return layout("项目总览", content, "/projects")


def drive_link(project: dict) -> str:
    if project.get("folder_url"):
        return f'<a href="{e(project["folder_url"])}" target="_blank" rel="noreferrer">打开网盘</a>'
    return '<span class="muted">缺失</span>'


def render_updates(data: dict) -> bytes:
    rows = "".join(
        f"""<tr>
          <td>{fmt_time(row['run_time'])}</td>
          <td>{'<span class="tag archived">已归档</span>' if row['type'] == 'archived' else '<span class="tag today">新上传</span>'}</td>
          <td><a href="/project/{quote(row['project'])}">{e(row['project'])}</a></td>
          <td>{file_link(row)}</td>
          <td class="muted">{e(display_label(row['log']))}</td>
        </tr>"""
        for row in data["updates"]
    )
    content = f"""
      <h1>更新记录</h1>
      <table>
        <thead><tr><th>时间</th><th>类型</th><th>项目</th><th>文件</th><th>日志</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    """
    return layout("更新记录", content, "/updates")


def render_project(data: dict, name: str) -> bytes:
    project = next((row for row in data["projects"] if row["name"] == name), None)
    if not project:
        return layout("未找到", '<div class="empty">未找到该项目。</div>')
    files = sorted(project["files"], key=lambda row: row["run_time"] or "", reverse=True)
    archived = sorted(project["archived"], key=lambda row: row["run_time"] or "", reverse=True)
    file_rows = "".join(
        f"""<tr><td>{file_link(row)}</td><td>{e(row['price_date'])}</td><td>{fmt_time(row['run_time'])}</td><td class="muted">{e(display_label(row['log']))}</td></tr>"""
        for row in files
    ) or '<tr><td colspan="4" class="muted">暂无价单上传记录。</td></tr>'
    archived_rows = "".join(
        f"""<tr><td>{e(row['file'])}</td><td>{e(display_label(row['old_folder']))}</td><td>{fmt_time(row['run_time'])}</td><td class="muted">{e(display_label(row['log']))}</td></tr>"""
        for row in archived
    ) or '<tr><td colspan="4" class="muted">暂无历史价单归档记录。</td></tr>'
    content = f"""
      <h1>{e(project['name'])}</h1>
      <div class="grid">
        <div class="metric"><div class="label">城市/区域</div><div class="value" style="font-size:20px">{e(display_label(project['city']))}</div></div>
        <div class="metric"><div class="label">开发商</div><div class="value" style="font-size:20px">{e(project['developer'])}</div></div>
        <div class="metric"><div class="label">合作程度</div><div class="value" style="font-size:20px">{e(project.get('cooperation_level', '未记录'))}</div></div>
        <div class="metric"><div class="label">合作方</div><div class="value" style="font-size:20px">{e(project.get('cooperation_partner', '未记录'))}</div></div>
        <div class="metric"><div class="label">已上传价单</div><div class="value">{e(project['uploaded_count'])}</div></div>
        <div class="metric"><div class="label">已归档旧价单</div><div class="value">{e(project['archived_count'])}</div></div>
      </div>
      <div class="panel" style="margin-top:16px">
        <strong>网盘：</strong> {drive_link(project)}
        <span class="muted" style="margin-left:18px">最近更新：{fmt_time(project['last_updated_at']) or "暂无记录"}</span>
      </div>
      {f'<div class="panel" style="margin-top:10px"><strong>网盘路径：</strong>{e(display_path(project.get("path", "")))}</div>' if project.get("path") else ""}
      <h2>最新价单文件</h2>
      <table><thead><tr><th>文件</th><th>识别到的价单日期</th><th>上传时间</th><th>日志</th></tr></thead><tbody>{file_rows}</tbody></table>
      <h2>历史价单归档</h2>
      <table><thead><tr><th>文件</th><th>归档文件夹</th><th>归档时间</th><th>日志</th></tr></thead><tbody>{archived_rows}</tbody></table>
    """
    return layout(project["name"], content)


class Handler(BaseHTTPRequestHandler):
    def is_authorized(self) -> bool:
        if not DASHBOARD_USER or not DASHBOARD_PASSWORD:
            return True
        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(header.removeprefix("Basic ").strip()).decode("utf-8")
        except Exception:
            return False
        return decoded == f"{DASHBOARD_USER}:{DASHBOARD_PASSWORD}"

    def request_auth(self) -> None:
        body = "需要登录后访问英国销控看板。".encode("utf-8")
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="UK Inventory Dashboard"')
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if not self.is_authorized():
            self.request_auth()
            return
        data = build_data()
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        path = parsed.path
        if path == "/":
            body = render_dashboard(data)
        elif path == "/projects":
            body = render_projects(data, query)
        elif path == "/updates":
            body = render_updates(data)
        elif path.startswith("/project/"):
            body = render_project(data, unquote(path.removeprefix("/project/")))
        else:
            body = layout("未找到", '<div class="empty">页面不存在。</div>')
            self.send_response(404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"英国销控看板已启动：http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
