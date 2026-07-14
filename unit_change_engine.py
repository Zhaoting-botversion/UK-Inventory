from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET


SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "inventory_units.sqlite"

PRICE_FILE_EXTENSIONS = {".pdf", ".xlsx", ".xlsm", ".xls", ".csv"}
FIELD_SYNONYMS = {
    "unit": ["unit", "plot", "apartment", "apt", "apartment number", "property", "home", "home no", "鎴垮彿"],
    "bedroom": ["bed", "beds", "bedroom", "bedrooms", "type", "unit type", "鎴峰瀷"],
    "internal_area": ["internal area", "internal", "net internal", "nia", "sq ft", "sqft", "area", "闈㈢Н"],
    "external_area": ["external area", "external", "balcony", "terrace", "outside space", "瀹ゅ"],
    "aspect": ["aspect", "orientation", "view", "views", "facing", "鏈濆悜", "鏅"],
    "price": ["price", "asking price", "list price", "purchase price", "total price", "浠锋牸"],
    "floor": ["floor", "level", "storey", "妤煎眰"],
    "status": ["status", "availability", "available", "reservation"],
    "tenure": ["tenure", "lease", "leasehold"],
    "estimated_completion": ["estimated completion", "completion", "build complete", "completion date", "浜や粯"],
    "rent_estimate": ["rent estimate", "estimated rent", "rental estimate", "rent", "pcm", "pw", "绉熼噾"],
    "service_charge": ["service charge", "service charges"],
    "ground_rent": ["ground rent", "鍦扮"],
    "parking": ["parking", "car parking", "杞︿綅"],
    "incentives": ["incentive", "incentives", "discount", "furniture package", "furniture", "stamp duty", "浼樻儬"],
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
    if key == "house type":
        return "aspect"
    if key in {"apart ment", "apartment ment"}:
        return "unit"
    if "unit area" in key or key in {"area", "sq ft", "sqft", "unit ea q", "u ar s m"}:
        return "internal_area"
    if "internal" in key and ("sqft" in key or "sq ft" in key or "size" in key):
        return "internal_area"
    if "net" in key and ("sqft" in key or "sq ft" in key or "sqm" in key):
        return "internal_area"
    if "balcony" in key or "terrace" in key or "external" in key:
        return "external_area"
    if "asking price" in key or "list price" in key or "purchase price" in key or key == "price":
        return "price"
    if "est rental" in key or "rental per month" in key or key in {"rent", "rental"}:
        return "rent_estimate"
    if "rental yield" in key:
        return None
    if key in {"plot no", "plot", "unit", "apartment", "apartment number", "apt", "apt no", "flat", "flat no", "residence no", "postal number", "name", "no", "number"}:
        return "unit"
    if key == "address":
        return "unit"
    for field, synonyms in FIELD_SYNONYMS.items():
        for synonym in synonyms:
            syn = header_key(synonym)
            if key == syn or syn in key:
                return field
    return None


def prefer_header_field(field: str, new_header: str, current_header: str) -> bool:
    new_key = header_key(new_header)
    current_key = header_key(current_header)
    if field == "internal_area":
        if ("sqft" in new_key or "sq ft" in new_key) and not ("sqft" in current_key or "sq ft" in current_key):
            return True
        if ("sqm" in current_key or "sq m" in current_key) and "sqm" not in new_key and "sq m" not in new_key:
            return True
    if field == "unit":
        preferred = ["postal number", "plot", "name", "apartment", "unit", "address"]

        def rank(key: str) -> int:
            for idx, token in enumerate(preferred):
                if token in key:
                    return idx
            return len(preferred)

        return rank(new_key) < rank(current_key)
    if field == "bedroom":
        return "bed" in new_key and "bed" not in current_key
    if field == "price":
        return "asking" in new_key and "asking" not in current_key
    return False


def finalize_record(record: dict) -> dict:
    price = cell_text(record.get("price", ""))
    status = cell_text(record.get("status", ""))
    if price in {"-"}:
        record["price"] = ""
    elif re.fullmatch(r"(reserved|sold|on hold|unavailable|exchanged)", price, flags=re.IGNORECASE):
        record["status"] = status or price
        record["price"] = ""
    elif price and parse_price(price) is None:
        record["price"] = ""
    elif parse_price(price) is not None and parse_price(price) < 50000:
        record["price"] = ""
    elif price and not status:
        record["status"] = "Available"
    if cell_text(record.get("bedroom", "")).lower() in {"available", "reserved", "sold", "on hold", "balcony", "terrace"}:
        record["bedroom"] = ""
    return record


def record_is_plausible(record: dict) -> bool:
    unit_key = normalize_unit(record.get("unit", ""))
    unit_text = cell_text(record.get("unit", ""))
    if unit_key in {
        "plotno",
        "unit",
        "unitno",
        "apartment",
        "apartmentnumber",
        "property",
        "homeno",
        "home",
        "flat",
        "aptno",
        "residenceno",
        "name",
    }:
        return False
    if len(unit_text) > 30 or "�" in unit_text:
        return False
    if not unit_key or not any(char.isdigit() for char in unit_key):
        return False
    if normalize_unit(record.get("status", "")) == unit_key:
        return False
    if cell_text(record.get("internal_area", "")).lower() in {"available", "reserved", "sold", "on hold"}:
        return False
    if not (cell_text(record.get("price", "")) or cell_text(record.get("status", ""))):
        return False
    return True


def header_mapping_from_rows(rows: list[list[str]], start: int, max_header_rows: int = 3) -> tuple[dict[str, int], int]:
    best_mapping: dict[str, int] = {}
    best_headers: dict[str, str] = {}
    best_rows_used = 1
    best_score = 0
    for rows_used in range(1, max_header_rows + 1):
        subset = rows[start : start + rows_used]
        if len(subset) < rows_used:
            continue
        width = max((len(row) for row in subset), default=0)
        mapping: dict[str, int] = {}
        headers: dict[str, str] = {}
        for pos in range(width):
            parts = []
            for row in subset:
                if pos < len(row):
                    text = cell_text(row[pos])
                    if text:
                        parts.append(text)
            header = " ".join(parts)
            field = header_to_field(header)
            if not field:
                continue
            if field not in mapping or prefer_header_field(field, header, headers.get(field, "")):
                mapping[field] = pos
                headers[field] = header
        score = len(mapping) + (2 if "unit" in mapping else 0) + (2 if "price" in mapping else 0)
        if "unit" in mapping and ("price" in mapping or "status" in mapping) and score > best_score:
            best_mapping = mapping
            best_headers = headers
            best_rows_used = rows_used
            best_score = score
    return best_mapping, best_rows_used


def row_looks_like_section(row: list[str]) -> bool:
    values = [cell_text(cell) for cell in row if cell_text(cell)]
    if not values:
        return True
    text = " ".join(values).lower()
    return len(values) <= 2 and any(token in text for token in ["bedroom", "apartments", "collection", "information", "price list"])


def value_from_row(data_row: list[str], pos: int | None, field: str) -> str:
    if pos is None:
        return ""
    candidates = [pos]
    if field in {"unit", "floor", "bedroom", "price", "internal_area"}:
        candidates.extend([pos - 1, pos + 1, pos + 2, pos - 2])
    for idx in candidates:
        if 0 <= idx < len(data_row):
            value = cell_text(data_row[idx])
            if value:
                return value
    return ""


def parse_price(value: object) -> float | None:
    text = cell_text(value)
    if not text:
        return None
    if re.search(r"\bpoa\b|application|tbc|n/a", text, re.I):
        return None
    cleaned = text.replace("拢", "").replace("£", "")
    cleaned = re.sub(r"(?<=\d)\s+(?=\d)", "", cleaned)
    match = re.search(r"[\d,]+(?:\.\d+)?", cleaned)
    if not match:
        return None
    try:
        value = float(match.group(0).replace(",", ""))
        if re.search(r"(?<=\d)\s*m\b|million", cleaned, re.IGNORECASE):
            value *= 1_000_000
        return value
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
    return re.sub(r"[^a-z0-9]+", "", cell_text(value).lower())


def status_norm(value: object) -> str:
    return cell_text(value).lower()


def is_sold_status(value: object) -> bool:
    text = status_norm(value)
    return any(token in text for token in ["sold", "exchanged", "completed", "unavailable", "withdrawn", "宸插敭"])


def is_reserved_status(value: object) -> bool:
    text = status_norm(value)
    return any(token in text for token in ["reserved", "reservation", "under offer", "hold", "棰勮"])


def is_available_status(value: object) -> bool:
    text = status_norm(value)
    return not text or any(token in text for token in ["available", "released", "for sale", "鍙敭"])


def rows_to_records(rows: list[list[str]], source: str) -> list[dict]:
    records: list[dict] = []
    for row in rows:
        joined = " ".join(cell_text(cell) for cell in row if cell_text(cell))
        record = parse_text_line_record(joined, source)
        if record and record_is_plausible(record):
            records.append(record)
    for index, row in enumerate(rows):
        mapping, header_rows = header_mapping_from_rows(rows, index)
        if "unit" not in mapping or ("price" not in mapping and "status" not in mapping):
            continue
        for data_row in rows[index + header_rows :]:
            if not any(cell_text(cell) for cell in data_row):
                continue
            if row_looks_like_section(data_row):
                continue
            record = {"source": source}
            for field in OUTPUT_FIELDS:
                pos = mapping.get(field)
                record[field] = normalize_record_value(field, value_from_row(data_row, pos, field))
            record = finalize_record(record)
            if record_is_plausible(record):
                records.append(record)
    deduped: dict[str, dict] = {}
    for record in records:
        key = normalize_unit(record["unit"])
        if key:
            deduped[key] = record
    return list(deduped.values())


def parse_text_line_record(line: str, source: str) -> dict | None:
    text = cell_text(line)
    if not text:
        return None
    money = r"(?:[£拢]\s?[\d,\s]+(?:\.\d+)?(?:m|M)?)"
    money_or_status = rf"(?:{money}|RESERVED|SOLD|ON HOLD|POA|TBC)"
    status = r"(?:Available|On Hold|Reserved|Sold|Exchanged|Unavailable)"
    match = re.match(
        rf"^(?:[•\-\u2022]\s*)?(?P<label>ONE|TWO|THREE|FOUR|FIVE|\d+)\s+BEDROOM(?:\s+APARTMENTS?)?\s+[-–]\s+"
        rf"(?P<note>PRICES?\s+FROM|PRICE\s+FROM|ASKING\s+PRICE)\s+(?P<price>{money})",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        groups = match.groupdict()
        label = (groups.get("label") or "").upper()
        bedroom_map = {"ONE": "1", "TWO": "2", "THREE": "3", "FOUR": "4", "FIVE": "5"}
        beds = bedroom_map.get(label, label)
        return finalize_record({
            "source": source,
            "unit": f"{beds} Bedroom Guide",
            "bedroom": beds,
            "internal_area": "",
            "external_area": "",
            "aspect": "",
            "price": normalize_record_value("price", groups.get("price") or ""),
            "floor": "",
            "status": "Price Guide",
            "tenure": "",
            "estimated_completion": "",
            "rent_estimate": "",
            "service_charge": "",
            "ground_rent": "",
            "parking": "",
            "incentives": "Project-level guide price; detailed unit pricing by one-to-one enquiry",
        })
    match = re.match(
        rf"^(?P<unit>[A-Za-z0-9][A-Za-z0-9.\-\/]*\*{{0,2}})\s+"
        rf"(?P<status>{status})\s+"
        rf"(?P<floor>[A-Za-z]|\d{{1,2}}|Ground|Lower Ground|LG|UG)\s+"
        rf"(?P<beds>\d+)\s+"
        rf"(?P<baths>\d+)\s+"
        rf"(?P<sqft>[\d,]+)\s+"
        rf"(?P<aspect>[A-Z]{{1,3}}(?:/[A-Z]{{1,3}})?)\s+"
        rf"(?P<price>{money_or_status})"
        rf"(?:\s+(?P<service>{money}))?"
        rf"(?:\s+(?P<rent>{money}))?$",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        groups = match.groupdict()
        price = groups.get("price") or ""
        row_status = groups.get("status") or ""
        if re.search(r"reserved|sold|on hold", price, re.I):
            row_status = price
            price = ""
        return finalize_record({
            "source": source,
            "unit": (groups.get("unit") or "").replace("*", ""),
            "bedroom": groups.get("beds") or "",
            "internal_area": groups.get("sqft") or "",
            "external_area": "",
            "aspect": groups.get("aspect") or "",
            "price": normalize_record_value("price", price),
            "floor": groups.get("floor") or "",
            "status": row_status,
            "tenure": "",
            "estimated_completion": "",
            "rent_estimate": normalize_record_value("rent_estimate", groups.get("rent") or ""),
            "service_charge": groups.get("service") or "",
            "ground_rent": "",
            "parking": "",
            "incentives": "",
        })
    match = re.match(
        rf"^(?P<unit>[A-Za-z0-9][A-Za-z0-9.\-\/]*\*{{0,2}})\s+"
        rf"(?P<status>{status})\s+"
        rf"(?P<floor>[A-Za-z]|\d{{1,2}}|Ground|Lower Ground)\s+"
        rf"(?P<beds>\d+)\s+"
        rf"(?P<baths>\d+)\s+"
        rf"(?P<sqft>[\d,]+)\s+"
        rf"(?P<price>{money_or_status})"
        rf"(?:\s+(?P<service>拢\s?[\d,]+))?"
        rf"(?:\s+(?P<rent>拢\s?[\d,]+))?$",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        groups = match.groupdict()
        price = groups.get("price") or ""
        row_status = groups.get("status") or ""
        if re.search(r"reserved|sold|on hold", price, re.I):
            row_status = price
            price = ""
        return finalize_record({
            "source": source,
            "unit": (groups.get("unit") or "").replace("*", ""),
            "bedroom": groups.get("beds") or "",
            "internal_area": groups.get("sqft") or "",
            "external_area": "",
            "aspect": "",
            "price": normalize_record_value("price", price),
            "floor": groups.get("floor") or "",
            "status": row_status,
            "tenure": "",
            "estimated_completion": "",
            "rent_estimate": normalize_record_value("rent_estimate", groups.get("rent") or ""),
            "service_charge": groups.get("service") or "",
            "ground_rent": "",
            "parking": "",
            "incentives": "",
        })
    match = re.match(
        rf"^(?P<unit>\d+[A-Za-z]?)\s+"
        rf"(?P<type>[A-Za-z][A-Za-z ]+?)\s+"
        rf"(?P<beds>\d+)\s+"
        rf"(?P<sqft>[\d,]+)\s+"
        rf"(?P<price>{money_or_status})"
        rf"(?:\s+(?P<rent>拢\s?[\d,]+))?"
        rf"(?:\s+(?P<yield>\d+(?:\.\d+)?%))?"
        rf"(?:\s+(?P<estate>拢\s?[\d,]+))?"
        rf"(?:\s+(?P<completion>.+))?$",
        text,
        flags=re.IGNORECASE,
    )
    if match and not re.search(r"\b(no|house type|price|rental|gross|collection)\b", text, re.I):
        groups = match.groupdict()
        price = groups.get("price") or ""
        row_status = "Available"
        if re.search(r"reserved|sold|on hold", price, re.I):
            row_status = price
            price = ""
        return finalize_record({
            "source": source,
            "unit": groups.get("unit") or "",
            "bedroom": groups.get("beds") or "",
            "internal_area": groups.get("sqft") or "",
            "external_area": "",
            "aspect": groups.get("type") or "",
            "price": normalize_record_value("price", price),
            "floor": "",
            "status": row_status,
            "tenure": "",
            "estimated_completion": groups.get("completion") or "",
            "rent_estimate": normalize_record_value("rent_estimate", groups.get("rent") or ""),
            "service_charge": groups.get("estate") or "",
            "ground_rent": "",
            "parking": "",
            "incentives": "",
        })
    match = re.match(
        rf"^(?P<unit>[A-Za-z]?\d+[A-Za-z]?(?:\.\d+)?)\s+"
        rf"(?P<floor>Ground|Lower Ground|Upper Ground|LG&G|UG|G|[A-Za-z]|\d{{1,2}}(?:st|nd|rd|th)?)\s+"
        rf"(?P<beds>\d+\s*(?:bed|penthouse)?|\d+Penthouse)\s+"
        rf"(?P<aspect>[A-Z]{{1,2}}(?:/[A-Z]{{1,2}})?)\s+"
        rf"(?P<area>[\d,]+)\s+"
        rf"(?P<sqm>[\d,]+)\s+"
        rf"(?P<balcony>[\d,\-]+)\s+"
        rf"(?P<parking>Yes|No|-)\s+"
        rf"(?P<price>{money_or_status}|U/O)$",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        groups = match.groupdict()
        price = groups.get("price") or ""
        row_status = "Available"
        if re.search(r"reserved|sold|on hold|u/o", price, re.I):
            row_status = "Under Offer" if re.search(r"u/o", price, re.I) else price
            price = ""
        return finalize_record({
            "source": source,
            "unit": groups.get("unit") or "",
            "bedroom": re.sub(r"\D+", "", groups.get("beds") or ""),
            "internal_area": groups.get("area") or "",
            "external_area": "" if groups.get("balcony") == "-" else groups.get("balcony") or "",
            "aspect": groups.get("aspect") or "",
            "price": normalize_record_value("price", price),
            "floor": groups.get("floor") or "",
            "status": row_status,
            "tenure": "",
            "estimated_completion": "",
            "rent_estimate": "",
            "service_charge": "",
            "ground_rent": "",
            "parking": groups.get("parking") or "",
            "incentives": "",
        })
    match = re.match(
        rf"^(?P<unit>\d{{1,2}}\.\d{{2}})\s+"
        rf"(?P<floor>[A-Z]|\d{{1,2}})\s+"
        rf"(?P<status>AVAILABLE|RESERVED|SOLD|ON HOLD)\s+"
        rf"(?P<middle>.+?)\s+"
        rf"(?P<sqft>[\d,]+)\s+"
        rf"(?P<beds>\d+(?:\.\d+)?)(?:\s*Bed)?\s+"
        rf"(?P<baths>\d+(?:\.\d+)?)\s+"
        rf"(?P<spec>[A-Za-z][A-Za-z ]+|-)\s+"
        rf"(?P<price>拢\s?[\d,]+|-)$",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        groups = match.groupdict()
        return finalize_record({
            "source": source,
            "unit": groups.get("unit") or "",
            "bedroom": groups.get("beds") or "",
            "internal_area": groups.get("sqft") or "",
            "external_area": "",
            "aspect": groups.get("middle") or "",
            "price": normalize_record_value("price", "" if groups.get("price") == "-" else groups.get("price")),
            "floor": groups.get("floor") or "",
            "status": groups.get("status") or "",
            "tenure": "",
            "estimated_completion": "",
            "rent_estimate": "",
            "service_charge": "",
            "ground_rent": "",
            "parking": "",
            "incentives": groups.get("spec") or "",
        })
    match = re.match(
        rf"^(?P<unit>[A-Z](?:\.[A-Z])?\.[A-Z]\.\d\.\d{{2}})\s+"
        rf"(?P<level>\d{{1,2}})\s+"
        rf"(?P<view>.+?)\s+"
        rf"(?P<sqft>[\d,]+)\s+"
        rf"(?P<outside>Balcony|Inset Terrace|Terrace|Winter Garden|N/A)\s+"
        rf"(?P<external>[\d,\-]+)\s+"
        rf"(?P<plan>Link|PDF|-)\s+"
        rf"(?P<price>{money_or_status})$",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        groups = match.groupdict()
        price = groups.get("price") or ""
        status_value = "Available"
        if re.search(r"reserved|sold|on hold", price, re.I):
            status_value = price
            price = ""
        return finalize_record({
            "source": source,
            "unit": groups.get("unit") or "",
            "bedroom": "",
            "internal_area": groups.get("sqft") or "",
            "external_area": f"{groups.get('outside') or ''} {groups.get('external') or ''}".strip(),
            "aspect": groups.get("view") or "",
            "price": normalize_record_value("price", price),
            "floor": groups.get("level") or "",
            "status": status_value,
            "tenure": "",
            "estimated_completion": "",
            "rent_estimate": "",
            "service_charge": "",
            "ground_rent": "",
            "parking": "",
            "incentives": groups.get("plan") or "",
        })
    match = re.match(
        rf"^(?P<unit>[EW]\d{{3}})\s+"
        rf"(?P<level>[A-Z]|\d{{1,2}})\s+"
        rf"(?P<beds>\d)\s+"
        rf"(?:(?P<amenity>Terrace|Balcony|Winter Garden)\s+)?"
        rf"(?P<sqft>[\d,]+)\s+"
        rf"(?P<price>{money_or_status})"
        rf"(?:\s+拢\s?[\d,]+)?$",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        groups = match.groupdict()
        price = groups.get("price") or ""
        status_value = "Available"
        if re.search(r"reserved|sold|on hold", price, re.I):
            status_value = price
            price = ""
        return finalize_record({
            "source": source,
            "unit": groups.get("unit") or "",
            "bedroom": groups.get("beds") or "",
            "internal_area": groups.get("sqft") or "",
            "external_area": groups.get("amenity") or "",
            "aspect": "",
            "price": normalize_record_value("price", price),
            "floor": groups.get("level") or "",
            "status": status_value,
            "tenure": "",
            "estimated_completion": "",
            "rent_estimate": "",
            "service_charge": "",
            "ground_rent": "",
            "parking": "",
            "incentives": "",
        })
    match = re.match(
        rf"^(?P<unit>\d+[a-z]?)\s+"
        rf"(?P<building>[IVX& ]+)\s+"
        rf"(?P<floor>LG&G|UG|G|[A-Za-z]|\d{{1,2}})\s+"
        rf"(?P<beds>\d)\s+"
        rf"(?P<internal>[\d,]+)\s+"
        rf"(?P<external>[\d,]+|n/a)\s+"
        rf"(?P<status>Available(?:\s*\\([^)]+\\))?|Reserved|Sold)\s+"
        rf"(?P<view>.+?)\s+拢\s?"
        rf"(?P<price>[\d,]+(?:\.\d+)?)",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        groups = match.groupdict()
        return finalize_record({
            "source": source,
            "unit": groups.get("unit") or "",
            "bedroom": groups.get("beds") or "",
            "internal_area": groups.get("internal") or "",
            "external_area": "" if (groups.get("external") or "").lower() == "n/a" else groups.get("external") or "",
            "aspect": groups.get("view") or "",
            "price": normalize_record_value("price", groups.get("price") or ""),
            "floor": groups.get("floor") or "",
            "status": groups.get("status") or "",
            "tenure": "",
            "estimated_completion": "",
            "rent_estimate": "",
            "service_charge": "",
            "ground_rent": "",
            "parking": "",
            "incentives": "",
        })
    match = re.match(
        rf"^(?P<unit>[A-Za-z]\d{{3,4}})\s+"
        rf"(?P<floor>\d{{1,2}})\s+"
        rf"(?P<aspect>[A-Z]{{1,3}}(?:/[A-Z]{{1,3}})?)\s+"
        rf"(?P<beds>\d+)\s+Bed\s+"
        rf"(?P<sqm>[\d,.]+)\s+"
        rf"(?P<sqft>[\d,]+)(?:\s+sq\s*ft)?\s+"
        rf"(?P<price>{money_or_status})",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        groups = match.groupdict()
        price = groups.get("price") or ""
        row_status = "Available"
        if re.search(r"reserved|sold|on hold", price, re.I):
            row_status = price
            price = ""
        return finalize_record({
            "source": source,
            "unit": groups.get("unit") or "",
            "bedroom": groups.get("beds") or "",
            "internal_area": groups.get("sqft") or "",
            "external_area": "",
            "aspect": groups.get("aspect") or "",
            "price": normalize_record_value("price", price),
            "floor": groups.get("floor") or "",
            "status": row_status,
            "tenure": "",
            "estimated_completion": "",
            "rent_estimate": "",
            "service_charge": "",
            "ground_rent": "",
            "parking": "",
            "incentives": "",
        })
    match = re.match(
        rf"^(?P<unit>[A-Za-z]?\d{{1,3}}(?:\.\d{{2}})?)\s+"
        rf"(?P<floor>Mezz|Ground|Lower Ground|Upper Ground|LG|UG|G|[A-Za-z]|\d{{1,2}}(?:st|nd|rd|th)?)\s+"
        rf"(?P<sqm>[\d,.]+)\s+"
        rf"(?P<sqft>[\d,]+)\s+"
        rf"(?P<beds>\d+)\s+"
        rf"(?P<aspect>[A-Za-z/ &-]+?)\s+"
        rf"(?P<price>{money_or_status})"
        rf"(?:\s+(?P<furniture>Yes|No))?"
        rf"(?:\s+(?P<rent>{money}))?"
        rf"(?:\s+(?P<yield>\d+(?:\.\d+)?%))?$",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        groups = match.groupdict()
        price = groups.get("price") or ""
        row_status = "Available"
        if re.search(r"reserved|sold|on hold", price, re.I):
            row_status = price
            price = ""
        return finalize_record({
            "source": source,
            "unit": groups.get("unit") or "",
            "bedroom": groups.get("beds") or "",
            "internal_area": groups.get("sqft") or "",
            "external_area": "",
            "aspect": groups.get("aspect") or "",
            "price": normalize_record_value("price", price),
            "floor": groups.get("floor") or "",
            "status": row_status,
            "tenure": "",
            "estimated_completion": "",
            "rent_estimate": normalize_record_value("rent_estimate", groups.get("rent") or ""),
            "service_charge": "",
            "ground_rent": "",
            "parking": "",
            "incentives": "Furniture pack included" if (groups.get("furniture") or "").lower() == "yes" else "",
        })
    match = re.match(
        rf"^(?P<unit>[A-Za-z]?\d+(?:\.\d+)?)\s+"
        rf"(?P<floor>\d{{1,2}})\s+"
        rf"(?P<aspect>[A-Z]{{1,3}}(?:/[A-Z]{{1,3}})?)\s+"
        rf"(?P<type>[A-Za-z0-9]+)\s+"
        rf"(?P<sqft>[\d,]+)\s+"
        rf"(?P<price>{money_or_status})"
        rf"(?:\s+{money})?$",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        groups = match.groupdict()
        price = groups.get("price") or ""
        status_value = "Available"
        if re.search(r"reserved|sold|on hold", price, re.I):
            status_value = price
            price = ""
        return finalize_record({
            "source": source,
            "unit": groups.get("unit") or "",
            "bedroom": "",
            "internal_area": groups.get("sqft") or "",
            "external_area": "",
            "aspect": groups.get("aspect") or "",
            "price": normalize_record_value("price", price),
            "floor": groups.get("floor") or "",
            "status": status_value,
            "tenure": "",
            "estimated_completion": "",
            "rent_estimate": "",
            "service_charge": "",
            "ground_rent": "",
            "parking": "",
            "incentives": groups.get("type") or "",
        })
    match = re.match(
        rf"^(?P<unit>[A-Z]?\d+)\s+"
        rf"(?P<building>[A-Za-z ]+?)\s+"
        rf"(?P<floor>Ground|Lower Ground|Upper Ground|LG|UG|G|[A-Za-z]|\d{{1,2}}(?:st|nd|rd|th)?)\s+"
        rf"(?P<area>[\d,]+)\s*/\s*(?P<sqm>[\d,.]+)\s+"
        rf"(?P<aspect>[A-Za-z/ &-]+?)\s+"
        rf"(?P<price>{money_or_status})$",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        groups = match.groupdict()
        price = groups.get("price") or ""
        status_value = "Available"
        if re.search(r"reserved|sold|on hold", price, re.I):
            status_value = price
            price = ""
        return finalize_record({
            "source": source,
            "unit": groups.get("unit") or "",
            "bedroom": "",
            "internal_area": groups.get("area") or "",
            "external_area": "",
            "aspect": groups.get("aspect") or "",
            "price": normalize_record_value("price", price),
            "floor": groups.get("floor") or "",
            "status": status_value,
            "tenure": "",
            "estimated_completion": "",
            "rent_estimate": "",
            "service_charge": "",
            "ground_rent": "",
            "parking": "",
            "incentives": groups.get("building") or "",
        })
    match = re.match(
        rf"^(?P<unit>[A-Z]\d+)\s+"
        rf"(?P<floor>[A-Z/]+|\d{{1,2}})\s+"
        rf"(?P<sqft>[\d,]+)\s+"
        rf"(?P<outside>Patio|Balcony|Terrace|Winter Garden|-)\s+"
        rf"(?P<price>{money_or_status})\s+"
        rf"(?P<rent>{money}|RESERVED|SOLD|ON HOLD)\s+"
        rf"(?P<status>{status})$",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        groups = match.groupdict()
        price = groups.get("price") or ""
        status_value = groups.get("status") or "Available"
        if re.search(r"reserved|sold|on hold", price, re.I):
            status_value = price
            price = ""
        return finalize_record({
            "source": source,
            "unit": groups.get("unit") or "",
            "bedroom": "",
            "internal_area": groups.get("sqft") or "",
            "external_area": "" if groups.get("outside") == "-" else groups.get("outside") or "",
            "aspect": "",
            "price": normalize_record_value("price", price),
            "floor": groups.get("floor") or "",
            "status": status_value,
            "tenure": "",
            "estimated_completion": "",
            "rent_estimate": normalize_record_value("rent_estimate", groups.get("rent") or ""),
            "service_charge": "",
            "ground_rent": "",
            "parking": "",
            "incentives": "",
        })
    match = re.match(
        rf"^(?P<unit>[A-Z]\d+(?:\.\d+)?)\s+"
        rf"(?P<floor>\d{{1,2}})\s+"
        rf"(?P<beds>Suite|\d+\s*Bed)\s+"
        rf"(?P<aspect>[A-Za-z &-]+?)\s+"
        rf"(?P<area>[\d,]+)\s*/\s*(?P<sqm>[\d,.]+)"
        rf"(?:\s+(?P<external_type>Balcony|Terrace|Winter Garden)\s+(?P<external>[\d,]+)\s*/\s*[\d,.]+)?\s+"
        rf"(?P<price>{money_or_status})$",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        groups = match.groupdict()
        price = groups.get("price") or ""
        status_value = "Available"
        if re.search(r"reserved|sold|on hold", price, re.I):
            status_value = price
            price = ""
        bed_text = groups.get("beds") or ""
        return finalize_record({
            "source": source,
            "unit": groups.get("unit") or "",
            "bedroom": "0" if bed_text.lower() == "suite" else re.sub(r"\D+", "", bed_text),
            "internal_area": groups.get("area") or "",
            "external_area": f"{groups.get('external_type') or ''} {groups.get('external') or ''}".strip(),
            "aspect": groups.get("aspect") or "",
            "price": normalize_record_value("price", price),
            "floor": groups.get("floor") or "",
            "status": status_value,
            "tenure": "",
            "estimated_completion": "",
            "rent_estimate": "",
            "service_charge": "",
            "ground_rent": "",
            "parking": "",
            "incentives": "",
        })
    match = re.match(
        rf"^(?P<unit>\d{{2}}-\d{{2}})\s+"
        rf"(?P<floor>-|\d{{1,2}})\s+"
        rf"(?P<area>[\d,]+)sqft/[\d,.]+sqm\s+"
        rf"(?P<external>[\d,]+)sqft/[\d,.]+sqm\s+"
        rf"(?P<aspect>[A-Za-z]+)\s+"
        rf"(?P<price>{money_or_status})\s+"
        rf"(?P<yield>\d+(?:\.\d+)?%)\s+"
        rf"(?P<rent>{money})\s+"
        rf"(?P<spec>[A-Za-z ]+)$",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        groups = match.groupdict()
        price = groups.get("price") or ""
        status_value = "Available"
        if re.search(r"reserved|sold|on hold", price, re.I):
            status_value = price
            price = ""
        return finalize_record({
            "source": source,
            "unit": groups.get("unit") or "",
            "bedroom": "",
            "internal_area": groups.get("area") or "",
            "external_area": groups.get("external") or "",
            "aspect": groups.get("aspect") or "",
            "price": normalize_record_value("price", price),
            "floor": "" if groups.get("floor") == "-" else groups.get("floor") or "",
            "status": status_value,
            "tenure": "",
            "estimated_completion": "",
            "rent_estimate": normalize_record_value("rent_estimate", groups.get("rent") or ""),
            "service_charge": "",
            "ground_rent": "",
            "parking": "",
            "incentives": f"{groups.get('yield') or ''} {groups.get('spec') or ''}".strip(),
        })
    match = re.match(
        rf"^(?P<unit>\d+[A-Za-z]?)\s+"
        rf"(?P<collection>[A-Za-z][A-Za-z ]+?)\s+"
        rf"(?P<type>Terrace|Apartment|House|Duplex|Flat)\s+"
        rf"(?P<beds>\d+)\s+"
        rf"(?P<baths>\d+)\s+"
        rf"(?P<sqft>[\d,]+)\s+"
        rf"(?P<aspect>[A-Za-z/ -]+?)\s+"
        rf"(?P<completion>Q\d\s+\d{{4}}|Ready|Complete|Completed)\s+"
        rf"(?P<price>{money_or_status})$",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        groups = match.groupdict()
        price = groups.get("price") or ""
        status_value = "Available"
        if re.search(r"reserved|sold|on hold", price, re.I):
            status_value = price
            price = ""
        return finalize_record({
            "source": source,
            "unit": groups.get("unit") or "",
            "bedroom": groups.get("beds") or "",
            "internal_area": groups.get("sqft") or "",
            "external_area": "",
            "aspect": groups.get("aspect") or "",
            "price": normalize_record_value("price", price),
            "floor": "",
            "status": status_value,
            "tenure": "",
            "estimated_completion": groups.get("completion") or "",
            "rent_estimate": "",
            "service_charge": "",
            "ground_rent": "",
            "parking": "",
            "incentives": f"{groups.get('collection') or ''} {groups.get('type') or ''}".strip(),
        })
    match = re.match(
        rf"^(?P<unit>[A-Z]\d(?:\.\d{{2}}){{2}})\s+"
        rf"(?P<type>\d{{3}})\s+"
        rf"(?P<floor>\d{{1,2}})\s+"
        rf"(?P<finish>[A-Za-z]+)\s+"
        rf"(?P<aspect>[NSEW](?:\s*/\s*[NSEW])*)\s+"
        rf"(?P<view>.+?)\s+"
        rf"(?P<rent>{money})\s+"
        rf"(?P<yield>\d+(?:\.\d+)?%)\s+"
        rf"(?P<price>{money_or_status})",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        groups = match.groupdict()
        price = groups.get("price") or ""
        status_value = "Available"
        if re.search(r"reserved|sold|on hold", price, re.I):
            status_value = price
            price = ""
        return finalize_record({
            "source": source,
            "unit": groups.get("unit") or "",
            "bedroom": "",
            "internal_area": "",
            "external_area": "",
            "aspect": f"{groups.get('aspect') or ''} {groups.get('view') or ''}".strip(),
            "price": normalize_record_value("price", price),
            "floor": groups.get("floor") or "",
            "status": status_value,
            "tenure": "",
            "estimated_completion": "",
            "rent_estimate": normalize_record_value("rent_estimate", groups.get("rent") or ""),
            "service_charge": "",
            "ground_rent": "",
            "parking": "",
            "incentives": groups.get("finish") or "",
        })
    match = re.match(
        rf"^(?:Apartment\s+)?(?P<unit>[A-Z]?\d+(?:\.\d+)?|M\.\d{{2}})\s+"
        rf"(?P<floor>Mezz|Ground|Lower Ground|Upper Ground|LG|UG|G|[A-Za-z]|\d{{1,2}})\s+"
        rf"(?P<sqm>[\d,.]+)\s+"
        rf"(?P<sqft>[\d,]+)\s+"
        rf"(?P<beds>\d+)\s+"
        rf"(?P<tail>.+)$",
        text,
        flags=re.IGNORECASE,
    )
    if match and "Apartment" in text:
        groups = match.groupdict()
        tail = groups.get("tail") or ""
        prices = re.findall(money, tail, flags=re.IGNORECASE)
        price = prices[-1] if prices else ""
        status_value = "Reserved" if re.search(r"\breserved\b", tail, re.I) and not price else "Available"
        return finalize_record({
            "source": source,
            "unit": groups.get("unit") or "",
            "bedroom": groups.get("beds") or "",
            "internal_area": groups.get("sqft") or "",
            "external_area": "",
            "aspect": re.sub(money_or_status, "", tail, flags=re.IGNORECASE).strip(),
            "price": normalize_record_value("price", price),
            "floor": groups.get("floor") or "",
            "status": status_value,
            "tenure": "",
            "estimated_completion": "",
            "rent_estimate": normalize_record_value("rent_estimate", prices[0] if len(prices) > 1 else ""),
            "service_charge": "",
            "ground_rent": "",
            "parking": "",
            "incentives": "",
        })
    match = re.match(
        rf"^(?P<unit>\d{{3,4}})\s+"
        rf"(?P<floor>\d{{1,2}})\s+"
        rf"(?P<type>Apartment|Penthouse)\s+"
        rf"(?P<beds>\d+)\s+"
        rf"(?P<sqm>[\d,.]+)\s+"
        rf"(?P<sqft>[\d,]+)\s+"
        rf"(?:(?P<outside>No|N/A)\s+N/A|(?P<outside_type>Balcony|Terrace|Winter Garden)\s+(?P<external_sqm>[\d,.]+)\s+(?P<external_sqft>[\d,]+))\s+"
        rf"(?P<aspect>.+?)\s+"
        rf"(?P<price>{money_or_status})$",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        groups = match.groupdict()
        price = groups.get("price") or ""
        status_value = "Available"
        if re.search(r"reserved|sold|on hold", price, re.I):
            status_value = price
            price = ""
        return finalize_record({
            "source": source,
            "unit": groups.get("unit") or "",
            "bedroom": groups.get("beds") or "",
            "internal_area": groups.get("sqft") or "",
            "external_area": f"{groups.get('outside_type') or ''} {groups.get('external_sqft') or ''}".strip(),
            "aspect": groups.get("aspect") or "",
            "price": normalize_record_value("price", price),
            "floor": groups.get("floor") or "",
            "status": status_value,
            "tenure": "",
            "estimated_completion": "",
            "rent_estimate": "",
            "service_charge": "",
            "ground_rent": "",
            "parking": "",
            "incentives": groups.get("type") or "",
        })
    match = re.match(
        rf"^(?P<unit>\d{{3,4}})\s+"
        rf"(?P<floor>[‘']?\d{{1,2}})\s+"
        rf"(?P<type>[A-Za-z0-9]+)\s+"
        rf"(?P<beds>Studio|\d+)\s+"
        rf"(?P<sqft>[\d,.]+)\s+"
        rf"(?P<sqm>[\d,.]+)\s+"
        rf"(?P<external>[\d,.]+)\s+"
        rf"(?P<price>{money_or_status})\s+"
        rf"(?P<aspect>.+)$",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        groups = match.groupdict()
        price = groups.get("price") or ""
        status_value = "Available"
        if re.search(r"reserved|sold|on hold", price, re.I):
            status_value = price
            price = ""
        beds = groups.get("beds") or ""
        return finalize_record({
            "source": source,
            "unit": groups.get("unit") or "",
            "bedroom": "0" if beds.lower() == "studio" else beds,
            "internal_area": groups.get("sqft") or "",
            "external_area": groups.get("external") or "",
            "aspect": groups.get("aspect") or "",
            "price": normalize_record_value("price", price),
            "floor": (groups.get("floor") or "").replace("‘", ""),
            "status": status_value,
            "tenure": "",
            "estimated_completion": "",
            "rent_estimate": "",
            "service_charge": "",
            "ground_rent": "",
            "parking": "",
            "incentives": groups.get("type") or "",
        })
    match = re.match(
        rf"^(?P<unit>[A-Z]?\d+[A-Z]?)\s+"
        rf"(?P<floor>Ground|Lower Ground|Upper Ground|LG|UG|G|[A-Za-z]|\d{{1,2}}(?:st|nd|rd|th)?)\s+"
        rf"(?P<beds>\d+)\s+"
        rf"(?P<internal>[\d,]+)\s+[\d,.]+\s+"
        rf"(?P<outside_type>Garden|Balcony|Terrace|Winter Garden)\s+"
        rf"(?P<external>[\d,]+)\s+[\d,.]+\s+"
        rf"(?P<view>.+?)\s+"
        rf"(?P<price>{money_or_status})$",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        groups = match.groupdict()
        return finalize_record({
            "source": source,
            "unit": groups.get("unit") or "",
            "bedroom": groups.get("beds") or "",
            "internal_area": groups.get("internal") or "",
            "external_area": f"{groups.get('outside_type') or ''} {groups.get('external') or ''}".strip(),
            "aspect": groups.get("view") or "",
            "price": normalize_record_value("price", groups.get("price") or ""),
            "floor": groups.get("floor") or "",
            "status": "Available",
            "tenure": "",
            "estimated_completion": "",
            "rent_estimate": "",
            "service_charge": "",
            "ground_rent": "",
            "parking": "",
            "incentives": "",
        })
    match = re.match(
        rf"^(?P<unit>[A-Z]\d+\.\d{{2}}|P\d+\.\d+\*?)\s+"
        rf"(?:(?P<type>[a-z]\.\d+(?:\.m)?)\s+)?"
        rf"(?P<spec>Classic|Prime)\s+"
        rf"(?P<floor>Ground|First|Second|Third|Fourth|Fifth|Sixth|Seventh|Eighth|Ninth|Tenth|[A-Za-z]|\d{{1,2}})\s+"
        rf"(?P<aspect>[A-Z]{{1,2}}(?:/[A-Z]{{1,2}})?|North|South|East|West)\s+"
        rf"(?P<view>.+?)\s+"
        rf"(?P<internal>[\d,]+)\s+"
        rf"(?P<external>NA|[\d,]+)\s+"
        rf"(?P<price>{money_or_status})"
        rf"(?:\s+(?P<rent>{money}))?"
        rf"(?:\s+(?P<yield>\d+(?:\.\d+)?%))?$",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        groups = match.groupdict()
        price = groups.get("price") or ""
        status_value = "Available"
        if re.search(r"reserved|sold|on hold", price, re.I):
            status_value = price
            price = ""
        return finalize_record({
            "source": source,
            "unit": (groups.get("unit") or "").replace("*", ""),
            "bedroom": "",
            "internal_area": groups.get("internal") or "",
            "external_area": "" if (groups.get("external") or "").upper() == "NA" else groups.get("external") or "",
            "aspect": f"{groups.get('aspect') or ''} {groups.get('view') or ''}".strip(),
            "price": normalize_record_value("price", price),
            "floor": groups.get("floor") or "",
            "status": status_value,
            "tenure": "",
            "estimated_completion": "",
            "rent_estimate": normalize_record_value("rent_estimate", groups.get("rent") or ""),
            "service_charge": "",
            "ground_rent": "",
            "parking": "",
            "incentives": groups.get("spec") or "",
        })
    match = re.match(
        rf"^(?P<unit>\d+[A-Za-z]?)\s+"
        rf"(?P<status>{status})\s+"
        rf"(?P<floor>\d{{1,2}})\s+"
        rf"(?P<beds>Studio|[A-Za-z0-9]+)\s+"
        rf"(?P<aspect>[A-Z]{{1,2}})\s+"
        rf"(?P<balcony>Y|N)\s+"
        rf"(?P<sqm>[\d,.]+)\s+"
        rf"(?P<sqft>[\d,]+)\s+"
        rf"(?P<price>{money})$",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        groups = match.groupdict()
        beds = groups.get("beds") or ""
        return finalize_record({
            "source": source,
            "unit": groups.get("unit") or "",
            "bedroom": "0" if beds.lower() == "studio" else re.sub(r"\D+", "", beds),
            "internal_area": groups.get("sqft") or "",
            "external_area": "Balcony" if (groups.get("balcony") or "").upper() == "Y" else "",
            "aspect": groups.get("aspect") or "",
            "price": normalize_record_value("price", groups.get("price") or ""),
            "floor": groups.get("floor") or "",
            "status": groups.get("status") or "",
            "tenure": "",
            "estimated_completion": "",
            "rent_estimate": "",
            "service_charge": "",
            "ground_rent": "",
            "parking": "",
            "incentives": "",
        })
    match = re.match(
        rf"^(?P<unit>\d+[A-Za-z]?)\s+"
        rf"(?P<core>[A-Za-z]+)\s+"
        rf"(?P<beds>\d+)\s+bedrooms?\s+"
        rf"(?P<sqft>[\d,]+)\s+sqft\s+"
        rf"(?P<price>{money})\s+"
        rf"(?P<status>{status})$",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        groups = match.groupdict()
        return finalize_record({
            "source": source,
            "unit": groups.get("unit") or "",
            "bedroom": groups.get("beds") or "",
            "internal_area": groups.get("sqft") or "",
            "external_area": "",
            "aspect": groups.get("core") or "",
            "price": normalize_record_value("price", groups.get("price") or ""),
            "floor": "",
            "status": groups.get("status") or "",
            "tenure": "",
            "estimated_completion": "",
            "rent_estimate": "",
            "service_charge": "",
            "ground_rent": "",
            "parking": "",
            "incentives": "",
        })
    match = re.match(
        rf"^(?P<unit>[A-Z]\.\d\.\d{{1,2}}\.\d)\s+"
        rf"(?P<floor>\d{{1,2}})\s+"
        rf"(?P<beds>-|\d+)\s+"
        rf"(?P<aspect>.+?)\s+"
        rf"(?P<terrace_sqft>[\d,]+)\s+"
        rf"(?P<terrace_sqm>[\d,.]+)\s+"
        rf"(?P<internal>[\d,]+)\s+"
        rf"(?P<internal_sqm>[\d,.]+)\s+"
        rf"(?P<price>{money})\s+"
        rf"(?P<status>{status})"
        rf"(?:\s+(?P<rent>{money}|-))?"
        rf"(?:\s+(?P<yield>\d+(?:\.\d+)?%|-))?$",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        groups = match.groupdict()
        return finalize_record({
            "source": source,
            "unit": groups.get("unit") or "",
            "bedroom": "" if groups.get("beds") == "-" else groups.get("beds") or "",
            "internal_area": groups.get("internal") or "",
            "external_area": groups.get("terrace_sqft") or "",
            "aspect": groups.get("aspect") or "",
            "price": normalize_record_value("price", groups.get("price") or ""),
            "floor": groups.get("floor") or "",
            "status": groups.get("status") or "",
            "tenure": "",
            "estimated_completion": "",
            "rent_estimate": normalize_record_value("rent_estimate", "" if groups.get("rent") == "-" else groups.get("rent") or ""),
            "service_charge": "",
            "ground_rent": "",
            "parking": "",
            "incentives": groups.get("yield") or "",
        })
    match = re.match(
        rf"^(?P<unit>[A-Z]?\d+[A-Z]?)\s+"
        rf"(?P<floor>Ground|Lower Ground|Upper Ground|LG|UG|G|[A-Za-z]|\d{{1,2}}(?:st|nd|rd|th)?)\s+"
        rf"(?P<beds>\d+)\s+"
        rf"(?P<internal>[\d,]+)\s+[\d,.]+\s+"
        rf"(?P<outside_type>Garden|Balcony|Terrace|Winter Garden)\s+"
        rf"(?P<external>[\d,]+)\s+[\d,.]+\s+"
        rf"(?P<price>{money_or_status})$",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        groups = match.groupdict()
        price = groups.get("price") or ""
        status_value = "Available"
        if re.search(r"reserved|sold|on hold", price, re.I):
            status_value = price
            price = ""
        return finalize_record({
            "source": source,
            "unit": groups.get("unit") or "",
            "bedroom": groups.get("beds") or "",
            "internal_area": groups.get("internal") or "",
            "external_area": f"{groups.get('outside_type') or ''} {groups.get('external') or ''}".strip(),
            "aspect": "",
            "price": normalize_record_value("price", price),
            "floor": groups.get("floor") or "",
            "status": status_value,
            "tenure": "",
            "estimated_completion": "",
            "rent_estimate": "",
            "service_charge": "",
            "ground_rent": "",
            "parking": "",
            "incentives": "",
        })
    match = re.match(
        rf"^(?P<unit>\d+[A-Za-z]?)\s+"
        rf"(?P<floor>House|G/LG|LG|UG|G|[A-Za-z]|\d{{1,2}})\s+"
        rf"(?P<beds>\d+)\s+"
        rf"(?P<outside>Garden/Roof Terrace|Garden/Patio|Balcony|Terrace|Winter Garden)\s+"
        rf"(?P<sqm>[\d,.]+)\s+"
        rf"(?P<sqft>[\d,]+)\s+"
        rf"(?P<price>{money}|[\d,]{{6,}})\s+"
        rf"(?:{money})?"
        rf"(?:\s+LINK)?\s*$",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        groups = match.groupdict()
        price = groups.get("price") or ""
        if not re.search(r"[£拢]", price):
            price = f"£{price}"
        return finalize_record({
            "source": source,
            "unit": groups.get("unit") or "",
            "bedroom": groups.get("beds") or "",
            "internal_area": groups.get("sqft") or "",
            "external_area": groups.get("outside") or "",
            "aspect": "",
            "price": normalize_record_value("price", price),
            "floor": groups.get("floor") or "",
            "status": "Available",
            "tenure": "",
            "estimated_completion": "",
            "rent_estimate": "",
            "service_charge": "",
            "ground_rent": "",
            "parking": "",
            "incentives": "",
        })
    match = re.match(
        rf"^(?P<unit>\d+\.\d{{2}}\*?)\s+"
        rf"(?P<primary>[A-Za-z ]+?)\s+"
        rf"(?P<secondary>-|[A-Za-z ]+?)\s+"
        rf"(?P<floor>\d{{1,2}}(?:-\d{{1,2}})?)\s+"
        rf"(?P<internal>[\d,]+)\s+"
        rf"(?P<sqm>[\d,]+)"
        rf"(?:\s+(?P<terrace>[\d,]+)\s+(?P<terrace_sqm>[\d,]+))?\s+"
        rf"(?P<price>{money_or_status})"
        rf"(?:\s+{money})?$",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        groups = match.groupdict()
        price = groups.get("price") or ""
        status_value = "Available"
        if re.search(r"poa|reserved|sold|on hold", price, re.I):
            status_value = price.upper() if re.search(r"poa", price, re.I) else price
            price = ""
        return finalize_record({
            "source": source,
            "unit": (groups.get("unit") or "").replace("*", ""),
            "bedroom": "",
            "internal_area": groups.get("internal") or "",
            "external_area": groups.get("terrace") or "",
            "aspect": f"{groups.get('primary') or ''} {groups.get('secondary') or ''}".strip(),
            "price": normalize_record_value("price", price),
            "floor": groups.get("floor") or "",
            "status": status_value,
            "tenure": "",
            "estimated_completion": "",
            "rent_estimate": "",
            "service_charge": "",
            "ground_rent": "",
            "parking": "",
            "incentives": "",
        })
    # The Broadway (JLL) customer list: apartment, building, floor,
    # accommodation, sqm, sqft, aspect, price/status.
    match = re.match(
        r"^(?P<unit>[A-Z]{2}\.\d{2}\.\d{2}\*{0,2})\s+"
        r"(?P<building>[A-Za-z]+\s+(?:East|West))\s+"
        r"(?P<floor>\d{1,2})\s+"
        r"(?P<beds>\d+)\s+bed\s*/\s*(?P<baths>\d+)\s+bath\s+"
        r"(?P<sqm>[\d,.]+)\s+(?P<sqft>[\d,]+)\s+"
        r"(?P<aspect>.+?)\s+(?P<price>£\s?[\d,]+|SOLD|RESERVED|ON HOLD)$",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        groups = match.groupdict()
        price = groups.get("price") or ""
        status_value = "Available"
        if re.search(r"sold|reserved|on hold", price, re.I):
            status_value = price
            price = ""
        return finalize_record({
            "source": source,
            "unit": (groups.get("unit") or "").replace("*", ""),
            "bedroom": groups.get("beds") or "",
            "internal_area": groups.get("sqft") or "",
            "external_area": "",
            "aspect": groups.get("aspect") or "",
            "price": normalize_record_value("price", price),
            "floor": groups.get("floor") or "",
            "status": status_value,
            "tenure": "",
            "estimated_completion": "",
            "rent_estimate": "",
            "service_charge": "",
            "ground_rent": "",
            "parking": "",
            "incentives": groups.get("building") or "",
        })
    return None


def text_lines_to_records(lines: list[str], source: str) -> list[dict]:
    records = []
    for line in lines:
        record = parse_text_line_record(line, source)
        if record and record_is_plausible(record):
            records.append(record)
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
    text_lines = []
    try:
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                try:
                    page_text = page.extract_text() or ""
                except Exception:
                    try:
                        page_text = page.extract_text_simple() or ""
                    except Exception:
                        page_text = ""
                text_lines.extend(page_text.splitlines())
                try:
                    page_tables = page.extract_tables() or []
                except Exception:
                    page_tables = []
                for table in page_tables:
                    rows.extend([[cell_text(cell) for cell in row] for row in table if row])
    except Exception as exc:
        return [], f"PDF parse failed: {exc}"
    records = rows_to_records(rows, path.name)
    text_records = text_lines_to_records(text_lines, path.name)
    for record in text_records:
        key = normalize_unit(record["unit"])
        existing = next((item for item in records if normalize_unit(item["unit"]) == key), None)
        if existing is None:
            records.append(record)
        elif not cell_text(existing.get("price")) and cell_text(record.get("price")):
            existing.update(record)
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
        if not old:
            events.append({**base, "change_type": "NEW_RELEASE", "price_change": None, "price_change_pct": None, "reason": "Appears in the new version but not in the previous version."})
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
                    "reason": "Price decreased; review as a priority." if delta < 0 else "Price increased; use updated pricing.",
                }
            )
        if status_norm(old.get("status")) != status_norm(new.get("status")):
            change_type = event_type_for_status(old.get("status", ""), new.get("status", ""))
            events.append({**base, "change_type": change_type, "price_change": None, "price_change_pct": None, "reason": "Unit status changed."})
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
                    "new_status": "Missing",
                    "bedroom": old.get("bedroom", ""),
                    "internal_area": old.get("internal_area", ""),
                    "floor": old.get("floor", ""),
                    "aspect": old.get("aspect", ""),
                    "reason": "Visible in the previous version but missing in the new version; marked as sold/withdrawn pending developer confirmation.",
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


def recent_events(limit: int = 200, path: Path = DB_PATH, days: int | None = None) -> list[dict]:
    init_db(path)
    query = """
        SELECT e.*, v.extracted_at
        FROM unit_change_events e
        LEFT JOIN pricelist_versions v ON v.id = e.new_version_id
    """
    params: list[object] = []
    if days is not None:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
        query += " WHERE e.created_at >= ?"
        params.append(cutoff)
    query += """
        ORDER BY e.created_at DESC, e.id DESC
        LIMIT ?
    """
    params.append(limit)
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        return [
            dict(row)
            for row in conn.execute(query, params)
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
