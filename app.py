from __future__ import annotations

import ast
import base64
import html
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from unit_change_engine import DB_PATH as UNIT_DB_PATH
from unit_change_engine import recent_events, version_summary


BASE_DIR = Path(__file__).resolve().parents[1]
WORK_PROJECTS_DIR = BASE_DIR.parent
LOG_DIR = WORK_PROJECTS_DIR / "迁移资料到Google Drive" / "logs"
UK_UPDATE_SCRIPT_CANDIDATES = [
    WORK_PROJECTS_DIR / "迁移资料到Google Drive" / "uk_update_pricelists.py",
    WORK_PROJECTS_DIR / "迁移资料到Google Drive" / "berkeley_update_pricelists.py",
    BASE_DIR / "uk_update_pricelists.py",
    BASE_DIR / "berkeley_update_pricelists.py",
]
UK_UPDATE_SCRIPT = next((path for path in UK_UPDATE_SCRIPT_CANDIDATES if path.exists()), UK_UPDATE_SCRIPT_CANDIDATES[0])
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
    "Hampshire": ["Hartland Village", "Hareshill"],
    "Hertfordshire": ["Hertford Locks"],
    "Kent": ["Foal Hurst Green", "Oakhill"],
    "Oxfordshire": ["Leighwood Fields", "Winterbrook Meadows"],
    "Reading": ["Reading Riverworks", "Bankside Gardens"],
    "Surrey": ["Eden Grove"],
    "Watford": ["The Exchange Watford"],
    "Maidenhead": ["Spring Hill"],
}

DEVELOPER_OVERRIDES = {
    "B1 - Imperial House": "Elevate Property Group",
    "B1 - Photographic Works": "Hatchbury",
    "B12 - The Pressworks": "Countrywide Developments PLC",
    "B4 - Glasswater Locks": "Berkeley Group",
    "B4 - Gunsmith House": "Elevate Property Group",
    "B4 - Snowhill Wharf": "St Joseph Homes (Berkeley Group)",
    "B91 - Warwick House, Solihull": "BPG",
    "BN1 - Edward Street Quarter, Brighton": "Socius + First Base + Patron Capital",
    "Bankside": "Renaker",
    "CM16 - Epping Forest": "GS8",
    "Canalside Quarter": "The Hill Group",
    "City Reach": "The Hill Group",
    "Contour": "Renaker",
    "DA15 - Urban Picturehouse - Completed": "Montreaux Homes",
    "E10 - Coronation Square": "Taylor Wimpey",
    "E14 - 25 Cuba Street": "Canary Wharf Group",
    "E14 - 8 Harbord Square - Off market": "Canary Wharf Group",
    "E14 - Aspen": "Far East Consortium",
    "E14 - Goodluck Hope": "Ballymore",
    "E14 - Landmark Pinnacle": "Chalegrove Properties",
    "E14 - One Park Drive &10 Park Drive- - Completed": "Canary Wharf Group",
    "E14 - One Thames Quay": "Chalegrove Properties",
    "E14 - Rivermark": "Barratt London",
    "E14 - South Quay Plaza": "Berkeley Group",
    "E16 - Cerulean Quarter - Completed": "English Cities Fund (Muse/LCR)",
    "E16 - Queens Cross": "Mount Anvil",
    "E16 - Riverscape": "Ballymore",
    "E3 - Heron Wharf": "Berkeley Group",
    "E3 - Hertford Mill": "Taylor Wimpey",
    "E3 - Oxbow": "EcoWorld London",
    "E5 - Parkhaus -Completed": "Union Developments",
    "E8 - Smokehaus": "Union Developments",
    "EC1 - The Arc - Est. Completion Q2 2023": "Berkeley Group",
    "EC1V - Angel Village - Est. complete from Q4 2026": "Bentry Capital",
    "EC2 - One Crown Place": "MTD Group",
    "EC2A - Principal Tower": "SHUI ON",
    "EC2A - The Stage": "Galliard Homes",
    "EC3 - One Bishopsgate Plaza - Completed": "UOL Group",
    "EC3 - The Haydon - Completed": "Berkeley Group",
    "EN4 - Trent Park": "Berkeley Group",
    "HA9 - Fulton & Fifth": "Berkeley Group",
    "HA9 - The Pages - Est Complete Sep 2026": "Wates Residential",
    "HP10 - Abbey Barn Park": "Berkeley Group",
    "Hartmere": "The Hill Group",
    "Highcroft": "Berkeley Group",
    "KT1 - County Hall Kingston (London Square)": "London Square",
    "Knights Park": "The Hill Group",
    "Liverpool - Abbey Row": "Bentry Capital",
    "Liverpool - The Forge": "Jarron Developments",
    "M1 - Vita Living": "Select Property",
    "M3 - Vista River Gardens": "Renaker",
    "M3 - Waterhouse Gardens": "Salboy",
    "M4 - Victoria Riverside": "L&Q (Laurus Homes)",
    "Marleigh Park": "The Hill Group",
    "N1 - Shoreditch Parkside - Est. Complete Q1 2026": "Hackney Council",
    "N10 - Alexandra Gate": "Berkeley Group (St William)",
    "N15 - Park North": "Kimbrook Property Developments",
    "N2 - Bishops Avenue Gardens - Est. Complete Q4 2026": "Valouran",
    "N8 - Hornsey Town Hall - Completed": "Far East Consortium (FEC)",
    "NW1 - Camden Goods Yard": "Berkeley Group",
    "NW1 - Piano Studios": "Ferdinand Holdings Limited",
    "NW2 - Brent Cross Town - Completed": "Related Argent",
    "NW3 - 100 Avenue Road": "Arada",
    "NW6 - The Clay Yard": "Berkeley Group",
    "NW7 - The Claves": "EcoWorld (EWL Living)",
    "NW8 - The Broadley - Est Complete Q2 2030": "Mount Anvil",
    "North Gate Park": "The Hill Group + Peabody",
    "OX10 - Winterbrook Meadows": "Berkeley Group",
    "One Waterside": "Berkeley Group",
    "RG7 3SY - Tower House Farm (T A Fisher)": "VIVID Homes",
    "RG9 4PS - Highlands Park, Henley": "Crest Nicholson",
    "RM9 - Dagenham Green": "The Hill Group",
    "RM9 - Eastbrook Village": "Berkeley Group",
    "Reading Riverworks": "Berkeley Group",
    "Reading-RG1 7YU - Brunswick Hill House": "未找到",
    "Regents Crescent": "Great Marlborough Estates",
    "SE1 - Bermondsey (London Square)": "London Square",
    "SE1 - Brigade Court": "Hadston Southwark Ltd",
    "SE1 - Opus": "Qatari Diar",
    "SE1 - Pinks Mews": "Sons and Co",
    "SE1 - SEVEN Southbank Place - Est Complete Jan 2026": "Qatari Diar",
    "SE1 - The Edit": "Mount Anvil",
    "SE1 - Triptych Bankside - Completion Q3 2023": "JTRE London",
    "SE1 - Westminster Tower (London Square)": "Berkeley Group",
    "SE10 - Greenwich Peninsula -Est. Completion Q3-Q4 2025": "Knight Dragon",
    "SE11 - Graphite Square": "Third.i",
    "SE11 - Oval Village": "Berkeley Group",
    "SE16 - The Founding, Canada Water - Est.completion mid 2025": "British Land",
    "SE17 - The Wilderly": "Lendlease",
    "SE18 - Woolwich (London Square)": "London Square",
    "SE26 - Dylon Riverside - Completed": "Weston Homes",
    "SE3 - Kidbrooke Village": "Berkeley Group",
    "SL5 - Heatherwood Royal": "Taylor Wimpey",
    "SL6 - Harvest Hill": "Taylor Wimpey",
    "SM1 - Sutton Garden Square": "Berkeley Group",
    "SW1 - 8 Eaton Lane-Est.completion: Q1 2026": "CIT",
    "SW1 - Ebury - Completed": "Loxley",
    "SW1 - The Broadway-Completed": "Canary Wharf Group",
    "SW1- OWO - Completed": "OHLA",
    "SW10 - Chelsea Finery": "Mount Anvil",
    "SW11 - Battersea Power Station": "Battersea Power Station Development Company",
    "SW11 - Embassy Gardens - The Capston": "Ballymore",
    "SW11 - One Clapham Junction - Completion  from Q1-Q3 2025": "Mount Anvil",
    "SW11 - Parkside Collection at Chelsea Bridge Wharf": "Berkeley Group",
    "SW11 - The HiLight - Est Completion Q2 2026": "Qatari Diar",
    "SW14 - Beverley Waterside": "Wimshurst Pelleriti",
    "SW17 - Wandsworth Common (London Square)": "London Square",
    "SW18 - King George's Gate": "Taylor Wimpey",
    "SW18-Riverside Quarter Development": "Frasers Property",
    "SW19 - Lombard Square": "Berkeley Group",
    "SW19 - Wimbledon Bridge House (London Square)": "London Square",
    "SW1E - No.1 Palace Street": "NorthAcre",
    "SW1P - Chimes": "PegasusLife",
    "SW1W - Chelsea Barracks -Price on application": "Qatari Diar",
    "SW1X - Belgravia Gate": "Wainbridge",
    "SW1X - Knightsbridge Gate - Completed-Price on application": "OHLA",
    "SW3 - The Lucan-completed": "Gulf Islamic Investments (GII)",
    "SW5 - One Cluny Mews": "Salboy",
    "SW6 - Chelsea Waterfront Tower East": "长江实业",
    "SW6 - Hurlingham Gardens": "Berkeley Group",
    "SW6 - Hurlingham Waterfront - Est. Completion Q3 2025": "Rockwell Property",
    "SW6 - Hurlingham Waterfront - Est. Completion Q3 2026": "Rockwell Property",
    "SW8 - Key Bridge": "Mount Anvil",
    "SW8 - Nine Elms (London Square)": "London Square",
    "SW8 - River Park Tower": "富力集团",
    "SW8 - The Newton": "Thornsett Group",
    "SW8 - Wilcox": "Turnqey International",
    "Sunningdale villas": "Consero London",
    "TW1 - Twickenham Square (London Square)": "London Square",
    "TW2 - Twickenham Green (London Square)": "London Square",
    "TW3 - Lampton Parkside": "The Hill Group",
    "TW8 - Kew Bridge Rise": "The Hill Group + L&Q",
    "TW8 - The Brentford Project": "Ballymore",
    "TW9 - Richmond Square": "RER London",
    "The ICON": "The Hill Group",
    "W1 - 60 Curzon, Mayfair- Completed-Price on application": "OHLA",
    "W1 - W1 Place-Completion Q1 2024": "Concord London",
    "W10 - Portobello Square - Completed": "Peabody",
    "W11 - The Pembridge": "Beauchamp Estates",
    "W12 - Television Centre - Est. Completion Q2 2027": "Stanhope + Mitsui Fudosan",
    "W14 - 100 Kensington - Est complete in Q1 2027": "SevenCapital",
    "W14 - 50 Brook Green (London Square)": "London Square",
    "W1H - The Bryanston-completed": "Almacantar",
    "W1J - 36 & 37 Hertfort Street": "CIT",
    "W1J - 6 Charles Street": "REDD",
    "W1J - One Carrington": "OHLA",
    "W1K - Three Kings Yard": "EcoWorld London",
    "W1S - Mandarin Oriental The Residences Mayfair London": "Clivedale",
    "W1T - Fitzroy Walk": "Middlesex Annexe LLP",
    "W1U - 100 George Street": "Native Land",
    "W1U - Marylebone Mansions": "Elliott House",
    "W1U - Marylebone Square - completed": "Concord London",
    "W1W - 19 Bolsover Street": "SATO Investments",
    "W1W - The Bolsover": "Stone/RE",
    "W2 - 18 Porchester Garden-Completed": "Taylor Wimpey Central London",
    "W2 - Park Modern-completed": "Fenton Whelan",
    "W2 - Vabel Townhouse": "Vabel",
    "W2 -The Whiteley-completed": "Voluran/Finchatton",
    "W4 - Chiswick Green": "Great Marlborough Estates",
    "W4 - Marlborough House, Chiswick High Road": "未找到",
    "W5 - The Warwick": "Kingmead Homes",
    "W6 - Artisi - Completed": "FABRICA (A2Dominion)",
    "W8 - Allen House-completed": "Topland Group",
    "W8 - Holland Park Gate - completed": "Lodha",
    "W8 - One Kensington Gardens": "De Vere Estates",
    "WC1A - Centre Point Residences": "Almacantar",
    "WC1X - Postmark, Farringdon": "Taylor Wimpey Central London",
    "WC2B - Chapter House": "Londonewcastle",
    "WC2R - Strand Chamber": "Seastar Developments",
    "West Gate": "Renaker"
}

COOPERATION_OVERRIDES = {
    "CR0 - Croydon (London Square)": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "London Square"
    },
    "E1 - London Dock": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "伯克利"
    },
    "E14 - 25 Cuba Street": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "Ballymore"
    },
    "E14 - 8 Harbord Square - Off market": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "莱坊"
    },
    "E14 - Aspen": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "莱坊"
    },
    "E14 - Goodluck Hope": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "Ballymore"
    },
    "E14 - Landmark Pinnacle": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "Chalegrove"
    },
    "E14 - One Park Drive &10 Park Drive- - Completed": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "莱坊"
    },
    "E14 - One Thames Quay": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "JLL"
    },
    "E16 - Riverscape": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "Ballymore"
    },
    "E2 - Regent's View": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "伯克利"
    },
    "E3 - Bow Green": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "伯克利"
    },
    "E3 - Twelvetrees Park": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "伯克利"
    },
    "EC1 - The Arc - Est. Completion Q2 2023": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "莱坊"
    },
    "EC1V - Angel Village - Est. complete from Q4 2026": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "CBRE"
    },
    "EC2A - Principal Tower": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "Concord"
    },
    "EC3 - One Bishopsgate Plaza - Completed": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "莱坊"
    },
    "EC3 - The Haydon - Completed": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "GAL"
    },
    "EN4 - Trent Park": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "伯克利"
    },
    "HA0 - Grand Union": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "伯克利"
    },
    "HA9 - Fulton & Fifth": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "GAL"
    },
    "N4 - Woodberry Down": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "伯克利"
    },
    "NW1 - Piano Studios": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "莱坊"
    },
    "NW6 - The Clay Yard": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "莱坊"
    },
    "NW7 - The Claves": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "Royal Dock"
    },
    "SE1 - Bermondsey Place": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "伯克利"
    },
    "SE1 - Opus": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "莱坊/JLL"
    },
    "SE1 - SEVEN Southbank Place - Est Complete Jan 2026": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "莱坊/JLL"
    },
    "SE1 - Triptych Bankside - Completion Q3 2023": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "JTRE"
    },
    "SE16 - The Founding, Canada Water - Est.completion mid 2025": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "莱坊/JLL"
    },
    "SE17 - The Wilderly": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "莱坊/JLL"
    },
    "SE18 - Royal Arsenal Riverside": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "伯克利"
    },
    "SW1 - 8 Eaton Lane-Est.completion: Q1 2026": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "CIT"
    },
    "SW1 - Ebury - Completed": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "JLL"
    },
    "SW1 - The Broadway-Completed": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "JLL"
    },
    "SW1- OWO - Completed": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "OHLA"
    },
    "SW10 - Chelsea Finery": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "Mount Anvil"
    },
    "SW11 - Battersea Power Station": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "Savills"
    },
    "SW11 - Embassy Gardens - The Capston": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "Ballymore"
    },
    "SW11 - Ransomes Wharf (London Square)": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "London Square"
    },
    "SW11 - The HiLight - Est Completion Q2 2026": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "莱坊/JLL"
    },
    "SW18 - Wandsworth Mills": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "伯克利"
    },
    "SW1E - No.1 Palace Street": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "NorthAcre"
    },
    "SW1W - Chelsea Barracks -Price on application": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "Qatari Diar"
    },
    "SW1X - Knightsbridge Gate - Completed-Price on application": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "Knight Frank 莱坊"
    },
    "SW6 - Chelsea Waterfront Tower East": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "长江实业"
    },
    "SW6 - King's Road Park": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "伯克利"
    },
    "SW8 - Key Bridge": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "Hamptons"
    },
    "SW8 - Nine Elms (London Square)": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "London Square"
    },
    "SW8 - River Park Tower": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "富力"
    },
    "SW8 - The Newton": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "CBRE"
    },
    "TW8 - The Brentford Project": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "Ballymore"
    },
    "UB1 - The Green Quarter": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "伯克利"
    },
    "W1 - 60 Curzon, Mayfair- Completed-Price on application": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "Brockton Everlast"
    },
    "W12 - Television Centre - Est. Completion Q2 2027": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "莱坊"
    },
    "W12 - White City Living": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "伯克利"
    },
    "W14 - 100 Kensington - Est complete in Q1 2027": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "JLL"
    },
    "W1H - The Bryanston-completed": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "Almacantar"
    },
    "W1J - 36 & 37 Hertfort Street": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "CIT"
    },
    "W1J - 6 Charles Street": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "DD"
    },
    "W1J - One Carrington": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "Knight Frank 莱坊"
    },
    "W1K - Three Kings Yard": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "CBRE"
    },
    "W1S - Mandarin Oriental The Residences Mayfair London": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "Clivedale"
    },
    "W1U - 100 George Street": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "Native Land"
    },
    "W1U - Marylebone Square - completed": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "Concord"
    },
    "W2 - 18 Porchester Garden-Completed": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "CIT"
    },
    "W2 - Trillium": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "伯克利"
    },
    "W2 - West End Gate": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "伯克利"
    },
    "W2 -The Whiteley-completed": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "Voluran/Finchatton"
    },
    "W6 - Artisi - Completed": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "莱坊"
    },
    "W6 - Fulham Reach": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "伯克利"
    },
    "W8 - Allen House-completed": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "Knight Frank 莱坊"
    },
    "W8 - Holland Park Gate - completed": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "Lodha"
    },
    "W8 - One Kensington Gardens": {
        "cooperation_level": "独代合作",
        "cooperation_partner": "Knight Frank 莱坊"
    },
    "WC1X - Postmark, Farringdon": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "Taylor Wimpey"
    },
    "WD17 - The Exchange Watford": {
        "cooperation_level": "开发商合作",
        "cooperation_partner": "伯克利"
    }
}


def load_projects() -> dict[str, str]:
    if not UK_UPDATE_SCRIPT.exists():
        return {}
    text = UK_UPDATE_SCRIPT.read_text(encoding="utf-8", errors="replace")
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
        if any(project == name or name.lower() in project.lower() for name in names):
            return city
    return "London"


def infer_city_from_drive_path(path: str) -> str:
    parts = [part.strip() for part in (path or "").split("/") if part.strip()]
    for index, part in enumerate(parts):
        if part.startswith("London"):
            return "London"
        if part.startswith("Manchester"):
            return "Manchester"
        if part.startswith("Birmingham"):
            return "Birmingham"
        if part.startswith("Others") and index + 1 < len(parts):
            return parts[index + 1].split()[0]
    return ""


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
    log_paths = [*LOG_DIR.glob("uk_update_*.json"), *LOG_DIR.glob("berkeley_update_*.json")]
    for path in sorted(log_paths):
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
        state_city = state.get("city", "")
        if state_city in {"未分类", "Unclassified", "Unknown", "未记录"}:
            state_city = ""
        path_city = infer_city_from_drive_path(state.get("path", ""))
        if path_city:
            state_city = path_city
        project["data_source"] = "Drive"
        project["city"] = state_city or project.get("city") or infer_city(project_name)
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
    "Buckinghamshire": "白金汉郡",
    "Cambridgeshire": "剑桥郡",
    "Reading / Berkshire": "雷丁 / 伯克郡",
    "Berkshire / Slough": "伯克郡 / 斯劳",
    "Hampshire": "汉普郡",
    "Hertfordshire": "赫特福德郡",
    "Kent": "肯特郡",
    "Oxfordshire": "牛津郡",
    "Surrey": "萨里郡",
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


def city_breakdown_badges(projects: list[dict], limit: int = 6) -> str:
    counts = Counter(display_label(row.get("city", "未分类")) for row in projects)
    if not counts:
        return '<div class="metric-breakdown muted">暂无城市数据</div>'
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    visible = ranked[:limit]
    remaining = sum(count for _, count in ranked[limit:])
    badges = "".join(
        f'<span>{e(city)} <strong>{count}</strong></span>'
        for city, count in visible
    )
    if remaining:
        badges += f'<span>其他 <strong>{remaining}</strong></span>'
    return f'<div class="metric-breakdown">{badges}</div>'


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


POSTCODE_PRIORITY = [
    "W1",
    "SW1",
    "W2",
    "W8",
    "SW3",
    "SW7",
    "WC1",
    "WC2",
    "EC1",
    "EC2",
    "EC3",
    "EC4",
    "SE1",
    "E1",
    "E14",
    "E16",
    "N1",
    "NW1",
]


def postcode_rank(name: str) -> int:
    district = postcode_district(postcode_prefix(name))
    if district in POSTCODE_PRIORITY:
        return POSTCODE_PRIORITY.index(district)
    return len(POSTCODE_PRIORITY)


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
        ("/projects", "价单搜索"),
        ("/unit-changes", "房源变化"),
        ("/updates", "更新记录"),
    ]
    nav_html = "".join(
        f'<a class="nav-{index} {"active" if active == href else ""}" href="{href}">{label}</a>'
        for index, (href, label) in enumerate(nav)
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
    nav {{ display: flex; gap: 8px; flex-wrap: wrap; }}
    nav a {{ color: #344054; text-decoration: none; padding: 8px 12px; border-radius: 6px; font-size: 14px; border: 1px solid transparent; font-weight: 600; }}
    nav a.nav-0 {{ background: #dff7f2; color: #065f56; }}
    nav a.nav-1 {{ background: #e7f0ff; color: #1d4ed8; }}
    nav a.nav-2 {{ background: #fef0f0; color: #b91c1c; }}
    nav a.nav-3 {{ background: #fff4d6; color: #92400e; }}
    nav a.active {{ border-color: currentColor; box-shadow: inset 0 0 0 1px currentColor; }}
    nav a:hover {{ filter: brightness(.97); text-decoration: none; }}
    main {{ padding: 24px 28px 40px; max-width: 1440px; margin: 0 auto; }}
    h1 {{ font-size: 26px; margin: 0 0 18px; }}
    h2 {{ font-size: 18px; margin: 24px 0 10px; }}
    .grid {{ display: grid; gap: 14px; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); }}
    .metric {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 16px; }}
    .metric.wide {{ grid-column: span 2; }}
    .metric .label {{ color: var(--muted); font-size: 13px; }}
    .metric .value {{ font-size: 28px; font-weight: 700; margin-top: 8px; }}
    .metric-breakdown {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; }}
    .metric-breakdown span {{ border: 1px solid var(--line); border-radius: 999px; padding: 4px 8px; color: #344054; background: #f8fafc; font-size: 12px; white-space: nowrap; }}
    .metric-breakdown strong {{ color: #111827; }}
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
    .tag.drop {{ background: #fee2e2; color: #991b1b; }}
    .tag.increase {{ background: #ffedd5; color: #9a3412; }}
    .tag.sold {{ background: #f1f5f9; color: #334155; }}
    .tag.release {{ background: #dbeafe; color: #1e40af; }}
    .split {{ display: grid; grid-template-columns: 1.1fr .9fr; gap: 16px; }}
    .panel {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 14px; }}
    .unit-highlight {{ border-color: #b7d7d2; background: #f5fffd; }}
    .unit-highlight h2 {{ margin-top: 0; }}
    .unit-highlight table {{ margin-top: 10px; }}
    .unit-cta {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin-top: 10px; }}
    .unit-focus-columns {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; margin-top: 12px; }}
    .unit-focus-column {{ background: #fff; border: 1px solid #3f70d8; border-radius: 8px; padding: 14px; }}
    .unit-focus-column h3 {{ margin: 0 0 12px; font-size: 22px; }}
    .unit-focus-column.drop h3 {{ color: #b91c1c; }}
    .unit-focus-column.new h3 {{ color: #059669; }}
    .unit-focus-column.sold h3 {{ color: #6b7280; }}
    .unit-city-group {{ margin-top: 14px; }}
    .unit-city-group:first-of-type {{ margin-top: 0; }}
    .unit-city-title {{ display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 8px; color: #344054; font-size: 13px; font-weight: 700; }}
    .unit-city-title span {{ border: 1px solid var(--line); border-radius: 999px; padding: 3px 8px; background: #f8fafc; color: #475569; font-weight: 600; font-size: 12px; }}
    .unit-project-card {{ background: #fff; border: 1px solid #3f70d8; border-radius: 8px; padding: 12px; margin-top: 12px; }}
    .unit-project-card:first-of-type {{ margin-top: 0; }}
    .unit-project-card h3 {{ margin: 0; font-size: 17px; }}
    .change-block {{ border-top: 1px solid #eef1f5; margin-top: 12px; padding-top: 10px; }}
    .change-block h4 {{ display: flex; align-items: center; gap: 8px; margin: 0 0 8px; font-size: 14px; color: #344054; }}
    .unit-list {{ list-style: none; padding: 0; margin: 0; display: grid; gap: 8px; }}
    .unit-list li {{ display: grid; grid-template-columns: minmax(90px, 1fr) minmax(90px, .8fr) minmax(150px, 1.2fr); gap: 8px; align-items: baseline; padding: 8px 0; border-top: 1px dashed #eef1f5; }}
    .unit-list li:first-child {{ border-top: 0; }}
    .unit-name {{ font-weight: 700; }}
    .unit-price {{ font-weight: 700; color: #111827; }}
    .unit-note {{ color: var(--muted); font-size: 12px; }}
    .unit-project-change-list {{ display: grid; gap: 12px; margin-top: 12px; }}
    .unit-change-card {{ background: #fff; border: 1px solid #9cc9c1; border-radius: 8px; padding: 14px; }}
    .unit-change-head {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 14px; flex-wrap: wrap; margin-bottom: 10px; }}
    .unit-change-head h3 {{ margin: 0; font-size: 18px; }}
    .unit-change-summary {{ display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }}
    .summary-pill {{ border: 1px solid var(--line); border-radius: 999px; padding: 4px 8px; background: #f8fafc; color: #344054; font-size: 12px; font-weight: 700; white-space: nowrap; }}
    .summary-pill.drop {{ background: #fee2e2; color: #991b1b; border-color: #fecaca; }}
    .summary-pill.new {{ background: #dbeafe; color: #1e40af; border-color: #bfdbfe; }}
    .summary-pill.sold {{ background: #f1f5f9; color: #334155; border-color: #cbd5e1; }}
    .summary-pill.other {{ background: #ffedd5; color: #9a3412; border-color: #fed7aa; }}
    .unit-change-card .unit-list {{ margin-top: 8px; }}
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
    @media (max-width: 1100px) {{ .priority-grid, .followup-grid, .market-grid, .updates-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} .unit-focus-columns {{ grid-template-columns: 1fr; }} }}
    @media (max-width: 900px) {{ .grid, .split, .priority-grid, .followup-grid, .market-grid, .updates-grid {{ grid-template-columns: 1fr; }} .metric.wide {{ grid-column: auto; }} header {{ align-items: flex-start; flex-direction: column; }} input {{ min-width: 100%; }} .section-head {{ display: block; }} .unit-list li {{ grid-template-columns: 1fr; gap: 3px; }} }}
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
    updated_project_rows = [project for project in projects if project.get("last_updated_at")]
    tracked_city_badges = city_breakdown_badges(projects)
    updated_city_badges = city_breakdown_badges(updated_project_rows)
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
        base_name = base_unit_project_name(name)
        if base_name in project_by_name:
            return f'<a href="/project/{quote(base_name)}">{e(name)}</a>'
        if name in project_by_name:
            return f'<a href="/project/{quote(name)}">{e(name)}</a>'
        return e(name)

    unit_file_lookup = build_unit_file_lookup(data)
    source_link = lambda row: unit_source_link(row, unit_file_lookup)
    all_unit_events = load_unit_events(2000)
    unit_focus_cards = render_unit_focus_columns(all_unit_events, project_link, source_link_func=source_link, project_lookup=project_by_name)

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
        <div class="metric wide"><div class="label">已追踪项目</div><div class="value">{len(projects)}</div>{tracked_city_badges}</div>
        <div class="metric wide"><div class="label">有更新项目</div><div class="value">{len(updated_project_rows)}</div>{updated_city_badges}</div>
        <div class="metric"><div class="label">本周房源变化</div><div class="value">{len(all_unit_events)}</div></div>
        <div class="metric"><div class="label">近24小时动态</div><div class="value">{len(today_updates)}</div></div>
        <div class="metric"><div class="label">最近同步时间</div><div class="value" style="font-size:18px">{fmt_time(drive_synced_at) or fmt_time(latest_run_time) or "暂无同步记录"}</div></div>
      </div>

      <section class="panel unit-highlight" style="margin-top:18px">
        <div class="unit-cta">
          <div>
            <h2>按楼盘分组的重点变化</h2>
            <div class="muted">优先看降价、售出/锁定/下架、新增或新低价机会；同一个楼盘的多套变化放在一起。</div>
          </div>
          <a href="/unit-changes">查看全部房源变化</a>
        </div>
        {unit_focus_cards}
      </section>

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
        <div class="muted">先看 Prime Central London，再看伦敦核心区、伦敦东区、其他伦敦板块和外地城市。每个区域只露出最近有动作的项目，完整清单可进价单搜索筛选。</div>
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
      <h1>价单搜索</h1>
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
    return layout("价单搜索", content, "/projects")


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
      <h1>价单搜索</h1>
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
    return layout("价单搜索", content, "/projects")


def drive_link(project: dict) -> str:
    if project.get("folder_url"):
        return f'<a href="{e(project["folder_url"])}" target="_blank" rel="noreferrer">打开网盘</a>'
    return '<span class="muted">缺失</span>'


def base_unit_project_name(name: str) -> str:
    return re.split(r"\s+[·路]\s+", name or "", maxsplit=1)[0].strip()


def build_unit_file_lookup(data: dict) -> dict[tuple[str, str], str]:
    lookup: dict[tuple[str, str], str] = {}
    by_file: dict[str, str] = {}
    drive_projects = data.get("drive_state", {}).get("projects", {})
    for record in drive_projects.values():
        project = record.get("project", "")
        for item in [*record.get("latest_files", []), *record.get("old_files", [])]:
            filename = item.get("file", "")
            url = item.get("file_url", "")
            if filename and url:
                lookup[(project, filename)] = url
                by_file.setdefault(filename, url)
    for project in data.get("projects", []):
        project_name = project.get("name", "")
        for item in [*project.get("files", []), *project.get("archived", [])]:
            filename = item.get("file", "")
            url = item.get("file_url", "")
            if filename and url:
                lookup[(project_name, filename)] = url
                by_file.setdefault(filename, url)
    lookup.update({("", filename): url for filename, url in by_file.items()})
    return lookup


def unit_source_link(row: dict, file_lookup: dict[tuple[str, str], str]) -> str:
    filename = row.get("new_file", "") or row.get("old_file", "")
    if not filename:
        return '<span class="muted">来源缺失</span>'
    project = base_unit_project_name(row.get("project_name", ""))
    url = file_lookup.get((project, filename)) or file_lookup.get(("", filename))
    if url:
        return f'<a href="{e(url)}" target="_blank" rel="noreferrer">来源价单</a>'
    return f'<span class="muted">{e(filename)}</span>'


def is_displayable_unit_event(row: dict) -> bool:
    unit = (row.get("unit") or "").strip()
    if not unit or not re.search(r"\d", unit):
        return False
    if unit.lower() in {"plot", "plot no.", "plot no", "unit area", "unit area sqft"}:
        return False
    return True


def load_unit_events(limit: int = 2000) -> list[dict]:
    if not UNIT_DB_PATH.exists():
        return []
    try:
        rows = [row for row in recent_events(limit * 3) if is_displayable_unit_event(row)]
        deduped = []
        seen = set()
        for row in rows:
            key = (
                row.get("project_name"),
                row.get("unit"),
                row.get("change_type"),
                row.get("old_price"),
                row.get("new_price"),
                row.get("old_status"),
                row.get("new_status"),
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(row)
        return deduped[:limit]
    except Exception:
        return []


def load_unit_version_summary() -> list[dict]:
    if not UNIT_DB_PATH.exists():
        return []
    try:
        return version_summary()
    except Exception:
        return []


def change_label(change_type: str) -> str:
    labels = {
        "PRICE_DROP": "价格下降",
        "PRICE_INCREASE": "价格上涨",
        "NEW_RELEASE": "新放出",
        "SOLD": "已售/下架",
        "RESERVED": "变为预订",
        "BACK_ON_MARKET": "回到市场",
        "STATUS_CHANGE": "状态变化",
    }
    return labels.get(change_type, change_type or "变化")


def change_tag(change_type: str) -> str:
    cls = {
        "PRICE_DROP": "drop",
        "PRICE_INCREASE": "increase",
        "SOLD": "sold",
        "NEW_RELEASE": "release",
        "BACK_ON_MARKET": "release",
    }.get(change_type, "")
    return f'<span class="tag {cls}">{e(change_label(change_type))}</span>'


def money_value(value: object) -> str:
    if value in (None, ""):
        return ""
    try:
        number = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return e(str(value))
    return f"£{number:,.0f}"


def money_delta(value: object) -> str:
    if value in (None, ""):
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return e(str(value))
    if number < 0:
        return f"-£{abs(number):,.0f}"
    sign = "+" if number > 0 else ""
    return f"{sign}£{number:,.0f}"


def unit_focus_category(row: dict) -> str:
    change_type = row.get("change_type", "")
    status_text = f"{row.get('new_status', '')} {row.get('new_price', '')}".lower()
    if any(token in status_text for token in ["reserved", "under offer", "on hold", "hold", "reservation"]):
        return "sold"
    if change_type == "PRICE_DROP":
        return "drop"
    if change_type == "SOLD":
        return "sold"
    if change_type in {"NEW_RELEASE", "BACK_ON_MARKET"}:
        return "new"
    return ""


def unit_focus_title(category: str) -> str:
    return {
        "drop": "降价",
        "sold": "售出 / 锁定 / 下架",
        "new": "新释出 / 新低价机会",
    }.get(category, "其他变化")


def unit_focus_tag(category: str) -> str:
    cls = {"drop": "drop", "sold": "sold", "new": "release"}.get(category, "")
    return f'<span class="tag {cls}">{e(unit_focus_title(category))}</span>'


def unit_change_bucket(row: dict) -> str:
    category = unit_focus_category(row)
    if category:
        return category
    return "other"


def unit_change_summary_label(category: str) -> str:
    return {
        "drop": "降价",
        "new": "新增",
        "sold": "售出",
        "other": "其他",
    }.get(category, "其他")


def unit_phase_text(project_name: str) -> str:
    parts = re.split(r"\s+[·路]\s+", project_name or "", maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def text_value(value: object) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).replace("\u00a0", " ")).strip()


def bedroom_text(value: object) -> str:
    text = text_value(value)
    if not text:
        return "居室缺失"
    match = re.search(r"\d+", text)
    if match:
        return f"{match.group(0)}房"
    if "studio" in text.lower():
        return "Studio"
    return f"居室: {text}"


def unit_price_text(row: dict) -> str:
    category = unit_focus_category(row)
    old_price = money_value(row.get("old_price"))
    new_price = money_value(row.get("new_price"))
    delta = money_delta(row.get("price_change"))
    if category == "drop":
        return f"{old_price} → {new_price} ({delta})"
    if category == "sold":
        if row.get("change_type") == "SOLD":
            return f"{old_price or row.get('old_status') or '旧价单有记录'} → 已消失"
        return row.get("new_status") or row.get("new_price") or "已锁定"
    if category == "new":
        return f"新价 {new_price or row.get('new_status') or '缺失'}"
    return new_price or old_price or delta


def unit_note_text(row: dict) -> str:
    bits = []
    floor = text_value(row.get("floor"))
    area = text_value(row.get("internal_area"))
    aspect = text_value(row.get("aspect"))
    status = text_value(row.get("new_status")) or text_value(row.get("old_status"))
    if floor and floor.lower() not in {"floor"}:
        bits.append(f"{floor}层")
    if area and area.lower() not in {"status", "balcony sqft", "balcony sq m"}:
        bits.append(area)
    if aspect and aspect.lower() not in {"aspect", "rental yield"}:
        bits.append(aspect)
    if status and status not in {"缺失"}:
        bits.append(status)
    return " · ".join(bits)


def render_unit_rows(rows: list[dict], source_link_func=None) -> str:
    source_link_func = source_link_func or (lambda row: "")
    return "".join(
        f"""<li>
          <div><span class="unit-name">{e(row.get('unit', ''))}</span><div class="unit-note">{bedroom_text(row.get('bedroom'))}</div></div>
          <div class="unit-price">{unit_price_text(row)}</div>
          <div class="unit-note">{e(unit_note_text(row))}<br>{fmt_time(row.get('created_at', ''))}<br>{source_link_func(row)}</div>
        </li>"""
        for row in rows
    )


def render_project_change_rows(rows: list[dict], source_link_func=None) -> str:
    source_link_func = source_link_func or (lambda row: "")
    category_order = {"drop": 0, "new": 1, "sold": 2, "other": 3}
    rows = sorted(
        rows,
        key=lambda row: (
            category_order.get(unit_change_bucket(row), 9),
            row.get("unit", ""),
            row.get("created_at", ""),
        ),
    )
    items = []
    for row in rows:
        category = unit_change_bucket(row)
        phase = unit_phase_text(row.get("project_name", ""))
        note_bits = [unit_note_text(row)]
        if phase:
            note_bits.append(phase)
        note = " · ".join(bit for bit in note_bits if bit)
        items.append(
            f"""<li>
              <div><span class="unit-name">{e(row.get('unit', ''))}</span><div class="unit-note">{bedroom_text(row.get('bedroom'))}</div></div>
              <div><div>{unit_focus_tag(category)}</div><div class="unit-price">{unit_price_text(row)}</div></div>
              <div class="unit-note">{e(note)}<br>{fmt_time(row.get('created_at', ''))}<br>{source_link_func(row)}</div>
            </li>"""
        )
    return "".join(items)


def render_unit_project_changes(events: list[dict], project_link_func, source_link_func=None, project_lookup: dict[str, dict] | None = None) -> str:
    project_lookup = project_lookup or {}
    rows = [row for row in events if is_displayable_unit_event(row)]
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[base_unit_project_name(row.get("project_name", ""))].append(row)

    def project_context(project: str) -> dict:
        return project_lookup.get(project) or {
            "name": project,
            "city": infer_city(project),
        }

    def sort_key(project: str) -> tuple:
        project_rows = grouped[project]
        latest = max((row.get("created_at", "") for row in project_rows), default="")
        latest_dt = parse_dt(latest)
        latest_sort = -(latest_dt.timestamp()) if latest_dt else 0
        return (
            group_rank(market_group(project_context(project))),
            postcode_rank(project),
            latest_sort,
            -len(project_rows),
            project,
        )

    cards = []
    for project in sorted(grouped, key=sort_key):
        project_rows = grouped[project]
        counts = Counter(unit_change_bucket(row) for row in project_rows)
        summary = [f'<span class="summary-pill">共 {len(project_rows)} 条变化</span>']
        for category in ("drop", "new", "sold", "other"):
            if counts.get(category):
                summary.append(
                    f'<span class="summary-pill {category}">{unit_change_summary_label(category)} {counts[category]}</span>'
                )
        cards.append(
            f"""<article class="unit-change-card">
              <div class="unit-change-head">
                <h3>{project_link_func(project)}</h3>
                <div class="unit-change-summary">{''.join(summary)}</div>
              </div>
              <ul class="unit-list">{render_project_change_rows(project_rows, source_link_func)}</ul>
            </article>"""
        )
    body = "".join(cards) or '<div class="empty">暂无房源变化。</div>'
    return f'<div class="unit-project-change-list">{body}</div>'


def render_unit_focus_columns(events: list[dict], project_link_func, limit_projects: int | None = None, source_link_func=None, project_lookup: dict[str, dict] | None = None) -> str:
    project_lookup = project_lookup or {}

    def project_context(project: str) -> dict:
        base_name = base_unit_project_name(project)
        return project_lookup.get(base_name) or project_lookup.get(project) or {
            "name": base_name or project,
            "city": infer_city(base_name or project),
        }

    def project_sort_key(project: str, rows: list[dict]) -> tuple:
        context = project_context(project)
        latest = max((row.get("created_at", "") for row in rows), default="")
        latest_dt = parse_dt(latest)
        latest_sort = -(latest_dt.timestamp()) if latest_dt else 0
        return (
            group_rank(market_group(context)),
            postcode_rank(context.get("name", project)),
            -len(rows),
            latest_sort,
            project,
        )

    focus_events = [row for row in events if unit_focus_category(row)]
    grouped: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for row in focus_events:
        grouped[base_unit_project_name(row.get("project_name", ""))][unit_focus_category(row)].append(row)
    columns = []
    for category in ("drop", "new", "sold"):
        projects = [
            project for project, by_category in grouped.items()
            if by_category.get(category)
        ]
        projects = sorted(projects, key=lambda project: project_sort_key(project, grouped[project][category]))
        if limit_projects:
            projects = projects[:limit_projects]
        projects_by_group: dict[str, list[str]] = defaultdict(list)
        for project in projects:
            projects_by_group[market_group(project_context(project))].append(project)
        group_blocks = []
        for group_name in sorted(projects_by_group, key=group_rank):
            cards = []
            group_projects = sorted(
                projects_by_group[group_name],
                key=lambda project: project_sort_key(project, grouped[project][category]),
            )
            for project in group_projects:
                rows = grouped[project][category]
                rows = sorted(rows, key=lambda row: row.get("created_at", ""), reverse=True)
                items = render_unit_rows(rows, source_link_func)
                cards.append(
                    f"""<article class="unit-project-card">
                      <h3>{project_link_func(project)}</h3>
                      <div class="small-meta">{len(rows)} 套</div>
                      <ul class="unit-list">{items}</ul>
                    </article>"""
                )
            group_blocks.append(
                f"""<section class="unit-city-group">
                  <div class="unit-city-title">{e(display_label(group_name))}<span>{sum(len(grouped[project][category]) for project in group_projects)} 套</span></div>
                  {''.join(cards)}
                </section>"""
            )
        body = "".join(group_blocks) or '<div class="empty">暂无</div>'
        columns.append(
            f"""<section class="unit-focus-column {category}">
              <h3>{unit_focus_title(category)}</h3>
              {body}
            </section>"""
        )
    return f'<div class="unit-focus-columns">{"".join(columns)}</div>'


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


def render_unit_changes(data: dict, query: dict[str, list[str]] | None = None) -> bytes:
    events = load_unit_events(2000)
    versions = load_unit_version_summary()
    project_by_name = {row["name"]: row for row in data["projects"]}
    query = query or {}
    selected_project = query.get("project", [""])[0]
    if selected_project:
        events = [row for row in events if row.get("project_name") == selected_project]
    project_by_name = {row["name"]: row for row in data["projects"]}

    def unit_project_link(name: str) -> str:
        base_name = base_unit_project_name(name)
        if base_name in project_by_name:
            return f'<a href="/project/{quote(base_name)}">{e(name)}</a>'
        return e(name)

    unit_file_lookup = build_unit_file_lookup(data)
    source_link = lambda row: unit_source_link(row, unit_file_lookup)
    projects = sorted({row.get("project_name", "") for row in events if row.get("project_name")})
    project_options = '<option value="">全部项目</option>' + "".join(
        f'<option value="{e(project)}" {"selected" if project == selected_project else ""}>{e(project)}</option>'
        for project in projects
    )
    counts = defaultdict(int)
    project_counts = defaultdict(int)
    for row in events:
        counts[row.get("change_type", "")] += 1
        project_counts[base_unit_project_name(row.get("project_name", ""))] += 1
    top_project_rows = "".join(
        f"""<tr>
          <td>{unit_project_link(project)}</td>
          <td>{count}</td>
        </tr>"""
        for project, count in sorted(project_counts.items(), key=lambda item: item[1], reverse=True)[:10]
    ) or '<tr><td colspan="2" class="muted">暂无房源变化数据。</td></tr>'
    event_rows = "".join(
        f"""<tr>
          <td>{fmt_time(row.get('created_at', ''))}</td>
          <td>{unit_project_link(row.get('project_name', ''))}</td>
          <td>{e(row.get('unit', ''))}</td>
          <td>{change_tag(row.get('change_type', ''))}</td>
          <td>{money_value(row.get('old_price'))}</td>
          <td>{money_value(row.get('new_price'))}</td>
          <td>{money_delta(row.get('price_change'))}</td>
          <td>{e(row.get('old_status', ''))}</td>
          <td>{e(row.get('new_status', ''))}</td>
          <td>{source_link(row)}</td>
        </tr>"""
        for row in events
    ) or '<tr><td colspan="10" class="muted">暂无房源变化数据。可以先运行 unit_change_engine.py seed-postmark-test 做测试，或导入新旧价单。</td></tr>'
    focus_cards = render_unit_focus_columns(events, unit_project_link, source_link_func=source_link, project_lookup=project_by_name)
    content = f"""
      <h1>房源变化</h1>
      <div class="grid">
        <div class="metric"><div class="label">变化事件</div><div class="value">{len(events)}</div></div>
        <div class="metric"><div class="label">价格下降</div><div class="value">{counts.get('PRICE_DROP', 0)}</div></div>
        <div class="metric"><div class="label">新放出</div><div class="value">{counts.get('NEW_RELEASE', 0)}</div></div>
        <div class="metric"><div class="label">已售/下架</div><div class="value">{counts.get('SOLD', 0)}</div></div>
      </div>
      <div class="panel" style="margin-top:16px">
        <strong>数据库：</strong> {e(str(UNIT_DB_PATH))}
        <span class="muted" style="margin-left:18px">已入库项目：{len(versions)}</span>
      </div>
      <form class="toolbar" method="get" action="/unit-changes" style="margin-top:16px">
        <select name="project">{project_options}</select>
        <button type="submit">筛选</button>
        <a href="/unit-changes">重置</a>
      </form>
      <section class="panel unit-highlight" style="margin-top:16px">
        <div class="unit-cta">
          <div>
            <h2>按楼盘分组的重点变化</h2>
            <div class="muted">优先看降价、售出/锁定/下架、新增或新低价机会；同一个楼盘的多套变化放在一起。</div>
          </div>
        </div>
        {focus_cards}
      </section>
      <div class="split">
        <section>
          <h2>房源变化明细</h2>
          <table>
            <thead><tr><th>时间</th><th>项目</th><th>房号</th><th>类型</th><th>原价 (£)</th><th>新价 (£)</th><th>变化 (£)</th><th>原状态</th><th>新状态</th><th>来源文件</th></tr></thead>
            <tbody>{event_rows}</tbody>
          </table>
        </section>
        <section>
          <h2>项目变化排行</h2>
          <table>
            <thead><tr><th>项目</th><th>变化数</th></tr></thead>
            <tbody>{top_project_rows}</tbody>
          </table>
        </section>
      </div>
    """
    return layout("房源变化", content, "/unit-changes")


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
    unit_events = [
        row for row in load_unit_events(2000)
        if base_unit_project_name(row.get("project_name", "")) == name
    ][:20]
    unit_file_lookup = build_unit_file_lookup(data)
    source_link = lambda row: unit_source_link(row, unit_file_lookup)
    unit_focus_cards = render_unit_focus_columns(unit_events, lambda project_name: e(project_name), source_link_func=source_link, project_lookup={name: project})
    unit_event_rows = "".join(
        f"""<tr>
          <td>{fmt_time(row.get('created_at', ''))}</td>
          <td>{e(row.get('unit', ''))}</td>
          <td>{change_tag(row.get('change_type', ''))}</td>
          <td>{money_value(row.get('old_price'))}</td>
          <td>{money_value(row.get('new_price'))}</td>
          <td>{money_delta(row.get('price_change'))}</td>
          <td>{e(row.get('old_status', ''))}</td>
          <td>{e(row.get('new_status', ''))}</td>
          <td>{source_link(row)}</td>
        </tr>"""
        for row in unit_events
    ) or '<tr><td colspan="9" class="muted">暂无房源级变化记录。</td></tr>'
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
      <h2>房源变化</h2>
      {unit_focus_cards}
      <table><thead><tr><th>时间</th><th>房号</th><th>变化类型</th><th>原价 (£)</th><th>新价 (£)</th><th>变化 (£)</th><th>原状态</th><th>新状态</th><th>来源</th></tr></thead><tbody>{unit_event_rows}</tbody></table>
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
        elif path == "/unit-changes":
            body = render_unit_changes(data, query)
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
