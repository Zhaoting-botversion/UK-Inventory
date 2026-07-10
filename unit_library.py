from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from unit_change_engine import DB_PATH


TEXT_FIELDS = (
    "project_name",
    "unit",
    "bedroom",
    "floor",
    "internal_area",
    "external_area",
    "aspect",
    "price",
    "status",
    "tenure",
    "estimated_completion",
    "rent_estimate",
    "service_charge",
    "ground_rent",
    "parking",
    "incentives",
    "source_file",
)


def parse_money(value: object) -> float | None:
    text = str(value or "")
    if not text or re.search(r"\bpoa\b|application|tbc|n/a", text, re.I):
        return None
    match = re.search(r"[\d,]+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def normalize_status(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def availability_bucket(value: object) -> str:
    status = normalize_status(value)
    if any(token in status for token in ("sold", "exchanged", "completed", "unavailable", "withdrawn")):
        return "sold"
    if any(token in status for token in ("reserved", "reservation", "under offer", "hold")):
        return "reserved"
    if not status or any(token in status for token in ("available", "released", "for sale")):
        return "available"
    return "other"


def current_units(path: Path = DB_PATH) -> list[dict]:
    if not path.exists():
        return []
    query = """
        WITH latest_versions AS (
            SELECT project_name, MAX(id) AS version_id
            FROM pricelist_versions
            WHERE unit_count > 0
            GROUP BY project_name
        )
        SELECT
            s.project_name,
            s.unit_key,
            s.unit,
            s.bedroom,
            s.internal_area,
            s.external_area,
            s.aspect,
            s.price,
            s.floor,
            s.status,
            s.tenure,
            s.estimated_completion,
            s.rent_estimate,
            s.service_charge,
            s.ground_rent,
            s.parking,
            s.incentives,
            v.id AS version_id,
            v.source_file,
            v.source_path,
            v.extracted_at,
            v.parse_note
        FROM latest_versions lv
        JOIN pricelist_versions v ON v.id = lv.version_id
        JOIN unit_snapshots s ON s.version_id = v.id
        ORDER BY s.project_name, s.unit
    """
    event_query = """
        SELECT e.*
        FROM unit_change_events e
        JOIN (
            SELECT project_name, unit_key, MAX(id) AS event_id
            FROM unit_change_events
            GROUP BY project_name, unit_key
        ) latest ON latest.event_id = e.id
    """
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        units = [dict(row) for row in conn.execute(query)]
        events = {
            (row["project_name"], row["unit_key"]): dict(row)
            for row in conn.execute(event_query)
        }
    for row in units:
        event = events.get((row.get("project_name"), row.get("unit_key")), {})
        row["availability"] = availability_bucket(row.get("status"))
        row["price_number"] = parse_money(row.get("price"))
        row["latest_change_type"] = event.get("change_type", "")
        row["latest_price_change"] = event.get("price_change")
        row["latest_change_at"] = event.get("created_at", "")
        row["latest_change_reason"] = event.get("reason", "")
    return units


def filter_units(units: list[dict], filters: dict[str, str]) -> list[dict]:
    search = (filters.get("q") or "").strip().lower()
    project = filters.get("project") or ""
    bedroom = filters.get("bedroom") or ""
    availability = filters.get("availability") or ""
    change_type = filters.get("change_type") or ""
    max_price = parse_money(filters.get("max_price"))
    min_price = parse_money(filters.get("min_price"))
    rows = []
    for row in units:
        haystack = " ".join(str(row.get(field, "")) for field in TEXT_FIELDS).lower()
        if search and search not in haystack:
            continue
        if project and row.get("project_name") != project:
            continue
        if bedroom and str(row.get("bedroom", "")).strip() != bedroom:
            continue
        if availability and row.get("availability") != availability:
            continue
        if change_type and row.get("latest_change_type") != change_type:
            continue
        price = row.get("price_number")
        if min_price is not None and (price is None or price < min_price):
            continue
        if max_price is not None and (price is None or price > max_price):
            continue
        rows.append(row)
    return rows


def inventory_summary(units: list[dict]) -> dict[str, int]:
    summary = {
        "units": len(units),
        "projects": len({row.get("project_name") for row in units if row.get("project_name")}),
        "available": 0,
        "reserved": 0,
        "sold": 0,
        "with_price": 0,
    }
    for row in units:
        if row.get("availability") in summary:
            summary[row["availability"]] += 1
        if row.get("price_number") is not None:
            summary["with_price"] += 1
    return summary
