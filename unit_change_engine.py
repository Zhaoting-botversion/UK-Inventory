from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET


SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "inventory_units.sqlite"

PRICE_FILE_EXTENSIONS = {".pdf", ".xlsx", ".xlsm", ".xls", ".csv"}
FIELD_SYNONYMS = {
    "unit": ["unit", "plot", "apartment", "apt", "apartment number", "property", "home", "home no", "房号"],
    "bedroom": ["bed", "beds", "bedroom", "bedrooms", "type", "unit type", "户型"],
    "internal_area": ["internal area", "internal", "net internal", "nia", "sq ft", "sqft", "area", "面积"],
    "external_area": ["external area", "external", "balcony", "terrace", "outside space", "室外"],
    "aspect": ["aspect", "orientation", "view", "views", "facing", "朝向", "景观"],
    "price": ["price", "asking price", "list price", "purchase price", "total price", "价格"],
    "floor": ["floor", "level", "storey", "楼层"],
    "status": ["status", "availability", "available", "reservation", "状态"],
    "tenure": ["tenure", "lease", "leasehold"],
    "estimated_completion": ["estimated completion", "completion", "build complete", "completion date", "交付"],
    "rent_estimate": ["rent estimate", "estimated rent", "rental estimate", "rent", "pcm", "pw", "租金"],
    "service_charge": ["service charge", "service charges", "物业费"],
    "ground_rent": ["ground rent", "地租"],
    "parking": ["parking", "car parking", "车位"],
    "incentives": ["incentive", "incentives", "discount", "furniture package", "furniture", "stamp duty", "优惠"],
}
OUTPUT_FIELDS = [
    "unit",
    "bedroom",
    "internal_area",
    "external_area",
    "aspect",
    "price",
    "floor",
    "status",
    "tenure",
    "estimated_completion",
    "rent_estimate",
    "service_charge",
    "ground_rent",
    "parking",
    "incentives",
]


def cell_text(value: object) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).replace("\u00a0", " ")).strip()


def header_key(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", cell_text(value).lower()).strip()


def header_to_field(value: str) -> str | None:
    key = header_key(value)
    if not key:
        return None
    if "unit area" in key or key in {"area", "sq ft", "sqft", "unit ea q", "u ar s m"}:
        return "internal_area"
    if "balcony" in key or "terrace" in key or "external" in key:
        return "external_area"
    if "asking price" in key or "list price" in key or "purchase price" in key or key == "price":
        return "price"
    if "est rental" in key or "rental per month" in key or key in {"rent", "rental"}:
        return "rent_estimate"
    if "rental yield" in key:
        return None
    if key in {"plot no", "plot", "unit", "apartment", "apart ment", "apartment number", "apt"}:
        return "unit"
    for field, synonyms in FIELD_SYNONYMS.items():
        for synonym in synonyms:
            syn = header_key(synonym)
            if key == syn or syn in key:
                return field
    return None


def parse_price(value: object) -> float | None:
    text = cell_text(value)
    if not text:
        return None
    if re.search(r"\bpoa\b|application|tbc|n/a", text, re.I):
        return None
    match = re.search(r"[\d,]+(?:\.\d+)?", text.replace("£", ""))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def normalize_record_value(field: str, value: object) -> str:
    text = cell_text(value)
    if field == "price":
        parsed = parse_price(text)
        if parsed is not None:
            return str(int(parsed)) if parsed.is_integer() else str(parsed)
    if field == "external_area":
        text = re.sub(r"\b(Terrace|Balcony)\s+(\d{2,5})\s+\d\b", r"\1 \2", text, flags=re.IGNORECASE)
    return text


def normalize_unit(value: object) -> str:
    key = re.sub(r"[^a-z0-9]+", "", cell_text(value).lower())
    if key.isdigit():
        return key.lstrip("0") or "0"
    return key


def bedroom_from_section(value: object) -> str:
    text = cell_text(value).lower()
    if len(text) > 60:
        return ""
    mapping = {
        "studio": "Studio",
        "one": "1",
        "two": "2",
        "three": "3",
        "four": "4",
        "five": "5",
        "six": "6",
    }
    if "bedroom" not in text and "bed" not in text and "studio" not in text:
        return ""
    if "studio" in text:
        return "Studio"
    digit = re.search(r"\b(\d+)\s*(?:bed|bedroom)", text)
    if digit:
        return digit.group(1)
    for word, number in mapping.items():
        if re.search(rf"\b{word}\s+bed(?:room)?", text):
            return number
    return ""


def status_norm(value: object) -> str:
    return cell_text(value).lower()


def is_sold_status(value: object) -> bool:
    text = status_norm(value)
    return any(token in text for token in ["sold", "exchanged", "completed", "unavailable", "withdrawn", "已售"])


def is_reserved_status(value: object) -> bool:
    text = status_norm(value)
    return any(token in text for token in ["reserved", "reservation", "under offer", "hold", "预订"])


def is_available_status(value: object) -> bool:
    text = status_norm(value)
    return not text or any(token in text for token in ["available", "released", "for sale", "可售"])


def is_display_only_status(value: object) -> bool:
    text = status_norm(value)
    return any(token in text for token in ["show apartment", "show home", "display apartment", "display home", "sample flat", "样板"])


def is_actionable_sale_record(record: dict) -> bool:
    if parse_price(record.get("price")) is not None:
        return True
    return bool(record.get("status")) and not is_display_only_status(record.get("status"))


def rows_to_records(rows: list[list[str]], source: str) -> list[dict]:
    records: list[dict] = []
    for index, row in enumerate(rows):
        fields = [header_to_field(cell) for cell in row]
        if "unit" not in fields or ("price" not in fields and "status" not in fields):
            continue
        mapping = {}
        for pos, field in enumerate(fields):
            if not field:
                continue
            key = header_key(row[pos]) if pos < len(row) else ""
            if field == "bedroom" and field in mapping:
                current_key = header_key(row[mapping[field]]) if mapping[field] < len(row) else ""
                if "bed" in key and "bed" not in current_key:
                    mapping[field] = pos
                continue
            if field == "unit" and field in mapping:
                current_key = header_key(row[mapping[field]]) if mapping[field] < len(row) else ""
                if ("unit" in key or "no" in key) and "unit" not in current_key:
                    mapping[field] = pos
                continue
            if field not in mapping:
                mapping[field] = pos
        current_bedroom = ""
        for data_row in rows[index + 1 :]:
            if not any(cell_text(cell) for cell in data_row):
                continue
            first_cell = cell_text(data_row[0]) if data_row else ""
            non_empty = [cell_text(cell) for cell in data_row if cell_text(cell)]
            section_bedroom = bedroom_from_section(first_cell)
            if section_bedroom and len(non_empty) <= 2:
                current_bedroom = section_bedroom
                continue
            record = {"source": source}
            for field in OUTPUT_FIELDS:
                pos = mapping.get(field)
                record[field] = normalize_record_value(field, data_row[pos]) if pos is not None and pos < len(data_row) else ""
            if current_bedroom and not record.get("bedroom"):
                record["bedroom"] = current_bedroom
            unit_key = normalize_unit(record["unit"])
            if unit_key in {"plotno", "unit", "unitno", "apartment", "apartmentnumber", "property"}:
                continue
            if record["unit"] and (record["price"] or record["status"]):
                records.append(record)
    deduped: dict[str, dict] = {}
    for record in records:
        key = normalize_unit(record["unit"])
        if key:
            deduped[key] = record
    return list(deduped.values())


def records_have_shifted_price_columns(records: list[dict]) -> bool:
    if not records:
        return False
    suspicious = 0
    for record in records:
        price = parse_price(record.get("price"))
        external = cell_text(record.get("external_area"))
        floor = cell_text(record.get("floor"))
        if (price is not None and price < 10000 and "£" in external) or re.search(r"\bbed\b", floor, re.I):
            suspicious += 1
    return suspicious >= max(1, len(records) // 3)


def join_words(words: list[dict]) -> str:
    return " ".join(word["text"] for word in sorted(words, key=lambda item: item["x0"])).strip()


def words_in_band(words: list[dict], x0: float, x1: float) -> str:
    return join_words([word for word in words if x0 <= word["x0"] < x1])


def extract_pdf_position_records(path: Path) -> list[dict]:
    try:
        import pdfplumber
    except ImportError:
        return []
    records: list[dict] = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            words = page.extract_words(x_tolerance=1, y_tolerance=3, keep_blank_chars=False)
            if not any(header_key(word["text"]) == "plot" for word in words):
                continue
            row_groups: dict[int, list[dict]] = defaultdict(list)
            for word in words:
                if word["top"] < 430:
                    continue
                row_groups[round(word["top"] / 3)].append(word)
            for row_words in row_groups.values():
                plot = words_in_band(row_words, 35, 85)
                if not re.fullmatch(r"\d+[A-Za-z]?", plot):
                    continue
                floor = words_in_band(row_words, 88, 125)
                bedroom = words_in_band(row_words, 125, 180)
                aspect = words_in_band(row_words, 180, 225)
                amenity = words_in_band(row_words, 225, 275)
                internal_area = words_in_band(row_words, 275, 320)
                external_area = words_in_band(row_words, 320, 365)
                price_or_status = words_in_band(row_words, 365, 415)
                rent_estimate = words_in_band(row_words, 415, 455)
                estimated_completion = words_in_band(row_words, 455, 520)
                price = price_or_status if parse_price(price_or_status) and parse_price(price_or_status) >= 10000 else ""
                status = "" if price else price_or_status
                record = {
                    "source": path.name,
                    "unit": plot,
                    "bedroom": bedroom,
                    "internal_area": internal_area,
                    "external_area": external_area,
                    "aspect": aspect,
                    "price": normalize_record_value("price", price),
                    "floor": floor,
                    "status": status,
                    "tenure": "",
                    "estimated_completion": estimated_completion,
                    "rent_estimate": rent_estimate,
                    "service_charge": "",
                    "ground_rent": "",
                    "parking": "",
                    "incentives": amenity,
                }
                if record["unit"] and (record["price"] or record["status"]):
                    records.append(record)
    deduped: dict[str, dict] = {}
    for record in records:
        key = normalize_unit(record["unit"])
        if key:
            deduped[key] = record
    return list(deduped.values())


def extract_single_column_pricelist_records(rows: list[list[str]], source: str) -> list[dict]:
    full_text = "\n".join(cell_text(row[0]) for row in rows if row)
    if "plot floor status" not in header_key(full_text):
        return []
    status_pattern = re.compile(r"\b(AVAILABLE|RESERVED|ON HOLD|SOLD|EXCHANGED|COMPLETED)\b", re.I)
    records: list[dict] = []
    for row in rows:
        cell = "\n".join(cell_text(part) for part in row if cell_text(part))
        if not cell or not status_pattern.search(cell):
            continue
        text = re.sub(r"\s+", " ", cell).strip()
        unit_matches = list(re.finditer(r"\b\d{1,2}\.\d{2}\b", text))
        status_match = status_pattern.search(text)
        if not unit_matches or not status_match:
            continue
        status = status_match.group(1).upper()
        prior_units = [match for match in unit_matches if match.start() < status_match.start()]
        unit_match = prior_units[0] if prior_units else unit_matches[-1]
        unit = unit_match.group(0)
        if unit_match.start() < status_match.start():
            between = text[unit_match.end():status_match.start()]
            floor_match = re.search(r"\b(\d{1,2})\b(?=\s*$)", between)
            if not floor_match:
                floor_match = re.search(r"\b(\d{1,2})\b", between)
        else:
            before_status = text[:status_match.start()]
            floor_match = re.search(r"\b(\d{1,2})\b\s*$", before_status)
        floor = floor_match.group(1) if floor_match else ""
        after_status = text[status_match.end():]
        price_matches = list(re.finditer(r"£\s*[\d,]+(?:\.\d+)?", after_status))
        price = price_matches[-1].group(0) if price_matches else ""
        area_match = re.search(r"\b(?P<area>\d[\d,]*(?:\.\d+)?)\s+(?P<beds>\d(?:\+\d)?(?:\s*Bed)?|Studio)\s+(?P<baths>\d(?:\.\d)?)\b", after_status, re.I)
        internal_area = area_match.group("area") if area_match else ""
        bedroom = area_match.group("beds") if area_match else ""
        if bedroom and "bed" not in bedroom.lower() and bedroom.lower() != "studio":
            bedroom = f"{bedroom} Bed"
        aspect = ""
        aspect_match = re.search(r"\b(North|South|East|West)(?:\s*&\s*(?:North|South|East|West))?\b", after_status, re.I)
        if aspect_match:
            aspect = aspect_match.group(0)
        records.append(
            {
                "source": source,
                "unit": unit,
                "bedroom": bedroom,
                "internal_area": internal_area,
                "external_area": "",
                "aspect": aspect,
                "price": normalize_record_value("price", price),
                "floor": floor,
                "status": status.title(),
                "tenure": "",
                "estimated_completion": "",
                "rent_estimate": "",
                "service_charge": "",
                "ground_rent": "",
                "parking": "",
                "incentives": "",
            }
        )
    deduped: dict[str, dict] = {}
    for record in records:
        key = normalize_unit(record["unit"])
        if key:
            deduped[key] = record
    return list(deduped.values())


def col_index(cell_ref: str) -> int:
    letters = re.match(r"[A-Z]+", cell_ref.upper())
    if not letters:
        return 0
    total = 0
    for char in letters.group(0):
        total = total * 26 + ord(char) - ord("A") + 1
    return total - 1


def read_xlsx_rows(path: Path) -> tuple[list[list[str]], str | None]:
    try:
        with zipfile.ZipFile(path) as zf:
            shared = []
            if "xl/sharedStrings.xml" in zf.namelist():
                root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
                ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                for si in root.findall("x:si", ns):
                    shared.append("".join(node.text or "" for node in si.findall(".//x:t", ns)))
            sheet_names = [name for name in zf.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", name)]
            rows = []
            ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            for sheet in sheet_names:
                root = ET.fromstring(zf.read(sheet))
                for row in root.findall(".//x:sheetData/x:row", ns):
                    values = []
                    for cell in row.findall("x:c", ns):
                        idx = col_index(cell.attrib.get("r", "A1"))
                        while len(values) <= idx:
                            values.append("")
                        inline_node = cell.find("x:is/x:t", ns)
                        value_node = cell.find("x:v", ns)
                        if inline_node is not None:
                            values[idx] = cell_text(inline_node.text)
                        elif value_node is not None:
                            raw = value_node.text or ""
                            values[idx] = shared[int(raw)] if cell.attrib.get("t") == "s" and raw.isdigit() and int(raw) < len(shared) else cell_text(raw)
                    if any(values):
                        rows.append(values)
        return rows, None
    except Exception as exc:
        return [], f"Excel parse failed: {exc}"


def extract_excel_records(path: Path) -> tuple[list[dict], str | None]:
    if path.suffix.lower() == ".xls":
        return [], "Legacy .xls parsing is not available; save as .xlsx first"
    rows, error = read_xlsx_rows(path)
    if error:
        return [], error
    records = rows_to_records(rows, path.name)
    return records, None if records else "No recognizable unit table found"


def extract_csv_records(path: Path) -> tuple[list[dict], str | None]:
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            with path.open("r", encoding=encoding, newline="") as fh:
                rows = [[cell_text(cell) for cell in row] for row in csv.reader(fh)]
            records = rows_to_records(rows, path.name)
            return records, None if records else "No recognizable unit table found"
        except UnicodeDecodeError:
            continue
        except Exception as exc:
            return [], f"CSV parse failed: {exc}"
    return [], "CSV encoding not recognized"


def extract_pdf_records(path: Path) -> tuple[list[dict], str | None]:
    try:
        import pdfplumber
    except Exception as exc:
        return [], f"pdfplumber unavailable: {exc}"
    rows = []
    try:
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                for table in page.extract_tables() or []:
                    rows.extend([[cell_text(cell) for cell in row] for row in table if row])
    except Exception as exc:
        return [], f"PDF parse failed: {exc}"
    records = rows_to_records(rows, path.name)
    if records_have_shifted_price_columns(records):
        positioned = extract_pdf_position_records(path)
        if len(positioned) >= len(records):
            records = positioned
    if not records:
        records = extract_single_column_pricelist_records(rows, path.name)
    return records, None if records else "No recognizable unit table found"


def extract_price_records(path: Path) -> tuple[list[dict], str | None]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return extract_pdf_records(path)
    if suffix in {".xlsx", ".xlsm", ".xls"}:
        return extract_excel_records(path)
    if suffix == ".csv":
        return extract_csv_records(path)
    return [], "Unsupported price file type"


def init_db(path: Path = DB_PATH) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS pricelist_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_name TEXT NOT NULL,
                source_file TEXT NOT NULL,
                source_path TEXT,
                version_label TEXT,
                extracted_at TEXT NOT NULL,
                unit_count INTEGER NOT NULL DEFAULT 0,
                parse_note TEXT
            );
            CREATE TABLE IF NOT EXISTS unit_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version_id INTEGER NOT NULL,
                project_name TEXT NOT NULL,
                unit_key TEXT NOT NULL,
                unit TEXT NOT NULL,
                bedroom TEXT,
                internal_area TEXT,
                external_area TEXT,
                aspect TEXT,
                price TEXT,
                floor TEXT,
                status TEXT,
                tenure TEXT,
                estimated_completion TEXT,
                rent_estimate TEXT,
                service_charge TEXT,
                ground_rent TEXT,
                parking TEXT,
                incentives TEXT,
                raw_json TEXT NOT NULL,
                FOREIGN KEY(version_id) REFERENCES pricelist_versions(id)
            );
            CREATE INDEX IF NOT EXISTS idx_unit_snapshots_project_unit ON unit_snapshots(project_name, unit_key);
            CREATE TABLE IF NOT EXISTS unit_change_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_name TEXT NOT NULL,
                unit_key TEXT NOT NULL,
                unit TEXT NOT NULL,
                change_type TEXT NOT NULL,
                old_version_id INTEGER,
                new_version_id INTEGER NOT NULL,
                old_file TEXT,
                new_file TEXT,
                old_price TEXT,
                new_price TEXT,
                price_change REAL,
                price_change_pct REAL,
                old_status TEXT,
                new_status TEXT,
                bedroom TEXT,
                internal_area TEXT,
                floor TEXT,
                aspect TEXT,
                reason TEXT,
                created_at TEXT NOT NULL,
                raw_json TEXT NOT NULL,
                FOREIGN KEY(old_version_id) REFERENCES pricelist_versions(id),
                FOREIGN KEY(new_version_id) REFERENCES pricelist_versions(id)
            );
            CREATE INDEX IF NOT EXISTS idx_unit_change_project_created ON unit_change_events(project_name, created_at);
            """
        )


def insert_version(project: str, source_file: str, source_path: str, version_label: str, records: list[dict], parse_note: str | None, path: Path = DB_PATH) -> int:
    init_db(path)
    now = datetime.now().isoformat(timespec="seconds")
    with sqlite3.connect(path) as conn:
        cur = conn.execute(
            """
            INSERT INTO pricelist_versions (project_name, source_file, source_path, version_label, extracted_at, unit_count, parse_note)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (project, source_file, source_path, version_label, now, len(records), parse_note or ""),
        )
        version_id = int(cur.lastrowid)
        for record in records:
            unit = cell_text(record.get("unit", ""))
            unit_key = normalize_unit(unit)
            conn.execute(
                """
                INSERT INTO unit_snapshots (
                    version_id, project_name, unit_key, unit, bedroom, internal_area, external_area, aspect,
                    price, floor, status, tenure, estimated_completion, rent_estimate, service_charge,
                    ground_rent, parking, incentives, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    version_id,
                    project,
                    unit_key,
                    unit,
                    record.get("bedroom", ""),
                    record.get("internal_area", ""),
                    record.get("external_area", ""),
                    record.get("aspect", ""),
                    record.get("price", ""),
                    record.get("floor", ""),
                    record.get("status", ""),
                    record.get("tenure", ""),
                    record.get("estimated_completion", ""),
                    record.get("rent_estimate", ""),
                    record.get("service_charge", ""),
                    record.get("ground_rent", ""),
                    record.get("parking", ""),
                    record.get("incentives", ""),
                    json.dumps(record, ensure_ascii=False),
                ),
            )
    return version_id


def latest_version(project: str, before_id: int | None = None, path: Path = DB_PATH) -> dict | None:
    init_db(path)
    query = "SELECT id, project_name, source_file, source_path, version_label, extracted_at, unit_count, parse_note FROM pricelist_versions WHERE project_name = ?"
    params: list[object] = [project]
    if before_id is not None:
        query += " AND id < ?"
        params.append(before_id)
    query += " ORDER BY id DESC LIMIT 1"
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(query, params).fetchone()
        return dict(row) if row else None


def snapshots_for_version(version_id: int, path: Path = DB_PATH) -> list[dict]:
    init_db(path)
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute("SELECT * FROM unit_snapshots WHERE version_id = ?", (version_id,))]


def event_type_for_status(old_status: str, new_status: str) -> str:
    if is_sold_status(new_status):
        return "SOLD"
    if is_reserved_status(new_status):
        return "RESERVED"
    if is_available_status(new_status) and not is_available_status(old_status):
        return "BACK_ON_MARKET"
    return "STATUS_CHANGE"


def compare_versions(project: str, old_version: dict | None, new_version: dict, path: Path = DB_PATH) -> list[dict]:
    new_records = snapshots_for_version(new_version["id"], path)
    old_records = snapshots_for_version(old_version["id"], path) if old_version else []
    old_by_unit = {row["unit_key"]: row for row in old_records if row.get("unit_key")}
    new_by_unit = {row["unit_key"]: row for row in new_records if row.get("unit_key")}
    events = []
    for unit_key, new in sorted(new_by_unit.items()):
        old = old_by_unit.get(unit_key)
        base = {
            "project_name": project,
            "unit_key": unit_key,
            "unit": new.get("unit", ""),
            "old_version_id": old_version["id"] if old_version else None,
            "new_version_id": new_version["id"],
            "old_file": old_version["source_file"] if old_version else "",
            "new_file": new_version["source_file"],
            "old_price": old.get("price", "") if old else "",
            "new_price": new.get("price", ""),
            "old_status": old.get("status", "") if old else "",
            "new_status": new.get("status", ""),
            "bedroom": new.get("bedroom", ""),
            "internal_area": new.get("internal_area", ""),
            "floor": new.get("floor", ""),
            "aspect": new.get("aspect", ""),
        }
        if not is_actionable_sale_record(new):
            continue
        if not old:
            events.append({**base, "change_type": "NEW_RELEASE", "price_change": None, "price_change_pct": None, "reason": "上一版未出现，本版新放出。"})
            continue
        old_price = parse_price(old.get("price"))
        new_price = parse_price(new.get("price"))
        if old_price is not None and new_price is not None and old_price != new_price:
            delta = new_price - old_price
            events.append(
                {
                    **base,
                    "change_type": "PRICE_DROP" if delta < 0 else "PRICE_INCREASE",
                    "price_change": delta,
                    "price_change_pct": delta / old_price if old_price else None,
                    "reason": "价格下降，适合优先复核和跟进。" if delta < 0 else "价格上调，需提醒销售使用新价格。",
                }
            )
        if status_norm(old.get("status")) != status_norm(new.get("status")):
            change_type = event_type_for_status(old.get("status", ""), new.get("status", ""))
            events.append({**base, "change_type": change_type, "price_change": None, "price_change_pct": None, "reason": "房源状态发生变化。"})
    for unit_key, old in sorted(old_by_unit.items()):
        if unit_key not in new_by_unit:
            events.append(
                {
                    "project_name": project,
                    "unit_key": unit_key,
                    "unit": old.get("unit", ""),
                    "change_type": "SOLD",
                    "old_version_id": old_version["id"] if old_version else None,
                    "new_version_id": new_version["id"],
                    "old_file": old_version["source_file"] if old_version else "",
                    "new_file": new_version["source_file"],
                    "old_price": old.get("price", ""),
                    "new_price": "",
                    "price_change": None,
                    "price_change_pct": None,
                    "old_status": old.get("status", ""),
                    "new_status": "缺失",
                    "bedroom": old.get("bedroom", ""),
                    "internal_area": old.get("internal_area", ""),
                    "floor": old.get("floor", ""),
                    "aspect": old.get("aspect", ""),
                    "reason": "上一版可见，本版消失；先标记为已售/下架，需以开发商确认为准。",
                }
            )
    return events


def store_events(events: list[dict], path: Path = DB_PATH) -> None:
    if not events:
        return
    now = datetime.now().isoformat(timespec="seconds")
    with sqlite3.connect(path) as conn:
        for event in events:
            conn.execute(
                """
                INSERT INTO unit_change_events (
                    project_name, unit_key, unit, change_type, old_version_id, new_version_id,
                    old_file, new_file, old_price, new_price, price_change, price_change_pct,
                    old_status, new_status, bedroom, internal_area, floor, aspect, reason,
                    created_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.get("project_name", ""),
                    event.get("unit_key", ""),
                    event.get("unit", ""),
                    event.get("change_type", ""),
                    event.get("old_version_id"),
                    event.get("new_version_id"),
                    event.get("old_file", ""),
                    event.get("new_file", ""),
                    event.get("old_price", ""),
                    event.get("new_price", ""),
                    event.get("price_change"),
                    event.get("price_change_pct"),
                    event.get("old_status", ""),
                    event.get("new_status", ""),
                    event.get("bedroom", ""),
                    event.get("internal_area", ""),
                    event.get("floor", ""),
                    event.get("aspect", ""),
                    event.get("reason", ""),
                    now,
                    json.dumps(event, ensure_ascii=False),
                ),
            )


def ingest_file(project: str, file_path: Path, version_label: str = "", db_path: Path = DB_PATH) -> tuple[int, list[dict], str | None]:
    records, parse_note = extract_price_records(file_path)
    version_id = insert_version(project, file_path.name, str(file_path), version_label or file_path.stem, records, parse_note, db_path)
    old_version = latest_version(project, before_id=version_id, path=db_path)
    new_version = latest_version(project, before_id=None, path=db_path)
    events = compare_versions(project, old_version, new_version, db_path) if new_version else []
    store_events(events, db_path)
    return version_id, events, parse_note


def recent_events(limit: int = 200, path: Path = DB_PATH) -> list[dict]:
    init_db(path)
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT e.*, v.extracted_at
                FROM unit_change_events e
                LEFT JOIN pricelist_versions v ON v.id = e.new_version_id
                ORDER BY e.created_at DESC, e.id DESC
                LIMIT ?
                """,
                (limit,),
            )
        ]


def version_summary(path: Path = DB_PATH) -> list[dict]:
    init_db(path)
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        return [
            dict(row)
            for row in conn.execute(
                """
                SELECT project_name, COUNT(*) AS versions, MAX(extracted_at) AS latest_extracted_at, SUM(unit_count) AS total_units
                FROM pricelist_versions
                GROUP BY project_name
                ORDER BY latest_extracted_at DESC
                """
            )
        ]


def seed_postmark_test(db_path: Path = DB_PATH) -> None:
    init_db(db_path)
    project = "WC1X - Postmark, Farringdon"
    old_records = [
        {"unit": "H1201", "bedroom": "1 Bed", "floor": "12", "internal_area": "548 sq ft", "price": "720000", "status": "Available", "aspect": "East"},
        {"unit": "H1302", "bedroom": "2 Bed", "floor": "13", "internal_area": "812 sq ft", "price": "1050000", "status": "Available", "aspect": "South"},
        {"unit": "H1503", "bedroom": "2 Bed", "floor": "15", "internal_area": "845 sq ft", "price": "1120000", "status": "Reserved", "aspect": "West"},
    ]
    new_records = [
        {"unit": "H1201", "bedroom": "1 Bed", "floor": "12", "internal_area": "548 sq ft", "price": "695000", "status": "Available", "aspect": "East"},
        {"unit": "H1302", "bedroom": "2 Bed", "floor": "13", "internal_area": "812 sq ft", "price": "1075000", "status": "Available", "aspect": "South"},
        {"unit": "H1605", "bedroom": "3 Bed", "floor": "16", "internal_area": "1012 sq ft", "price": "1450000", "status": "Available", "aspect": "South West"},
    ]
    old_id = insert_version(project, "20.06.26 - Monograph Square - Price List Block H.pdf", "", "test-old", old_records, "Seeded MVP test old version", db_path)
    new_id = insert_version(project, "04.07.26 - Monograph Square - Price List Block H.pdf", "", "test-new", new_records, "Seeded MVP test new version", db_path)
    old_version = latest_version(project, before_id=new_id, path=db_path)
    new_version = latest_version(project, path=db_path)
    if old_version and new_version:
        events = compare_versions(project, old_version, new_version, db_path)
        store_events(events, db_path)
        print(f"Seeded Postmark test: old_version={old_id}, new_version={new_id}, events={len(events)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Unit-level price list extraction and comparison engine.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db")
    ingest = sub.add_parser("ingest")
    ingest.add_argument("--project", required=True)
    ingest.add_argument("--file", required=True, type=Path)
    ingest.add_argument("--version-label", default="")
    seed = sub.add_parser("seed-postmark-test")
    seed.add_argument("--reset", action="store_true")
    recent = sub.add_parser("recent")
    recent.add_argument("--limit", type=int, default=20)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "init-db":
        init_db()
        print(DB_PATH)
        return 0
    if args.command == "seed-postmark-test":
        if args.reset and DB_PATH.exists():
            DB_PATH.unlink()
        seed_postmark_test()
        return 0
    if args.command == "ingest":
        version_id, events, parse_note = ingest_file(args.project, args.file, args.version_label)
        print(json.dumps({"version_id": version_id, "events": len(events), "parse_note": parse_note}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "recent":
        print(json.dumps(recent_events(args.limit), ensure_ascii=False, indent=2))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
