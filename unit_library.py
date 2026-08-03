from __future__ import annotations

import re
import sqlite3
from datetime import date, datetime
from pathlib import Path

from unit_change_engine import DB_PATH
from phase_aliases import canonical_project_name, load_phase_aliases


TEXT_FIELDS = (
    "project_name",
    "project_city",
    "project_location",
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


UNAVAILABLE_TOKENS = (
    "sold",
    "exchanged",
    "completed",
    "unavailable",
    "withdrawn",
)

RESERVED_TOKENS = (
    "reserved",
    "reservation",
    "under offer",
    "hold",
)


SOURCE_FIELD_OVERRIDES = Path(__file__).resolve().parent / "source_field_overrides.json"


def normalized_project(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def load_source_field_overrides(path: Path = SOURCE_FIELD_OVERRIDES) -> dict[str, set[str]]:
    if not path.exists():
        return {}
    import json
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        normalized_project(row.get("drive_project_name")): set(row.get("not_provided", []))
        for row in payload.get("overrides", [])
        if row.get("drive_project_name")
    }


MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}


def source_document_date(row: dict) -> date:
    extracted = str(row.get("extracted_at") or "")
    try:
        fallback = datetime.fromisoformat(extracted).date()
    except ValueError:
        fallback = date.min
    for value in (row.get("source_file"), row.get("version_label")):
        text = str(value or "").casefold()
        numeric = re.search(r"(?<!\d)(\d{1,2})[._/-](\d{1,2})[._/-](\d{2,4})(?!\d)", text)
        if numeric:
            day, month, year = (int(part) for part in numeric.groups())
            year = year + 2000 if year < 100 else year
            try:
                return date(year, month, day)
            except ValueError:
                pass
        named = re.search(
            r"(?:(\d{1,2})(?:st|nd|rd|th)?(?:\s+of)?\s+)?("
            + "|".join(MONTHS)
            + r")(?:[\s,._-]+(\d{2,4}))?",
            text,
        )
        if named:
            day = int(named.group(1) or 1)
            year = int(named.group(3)) if named.group(3) else fallback.year
            year = year + 2000 if year < 100 else year
            try:
                return date(year, MONTHS[named.group(2)], day)
            except ValueError:
                pass
    return fallback


def collapse_confirmed_phase_aliases(rows: list[dict]) -> list[dict]:
    aliases = load_phase_aliases()
    grouped: dict[tuple[str, str], list[dict]] = {}
    for source_row in rows:
        row = dict(source_row)
        row["source_project_name"] = row.get("project_name", "")
        row["project_name"] = canonical_project_name(row["source_project_name"], aliases)
        grouped.setdefault((row["project_name"], row.get("unit_key", "")), []).append(row)

    merge_fields = (
        "bedroom", "internal_area", "external_area", "aspect", "price", "floor",
        "tenure", "estimated_completion", "rent_estimate", "service_charge",
        "ground_rent", "parking", "incentives",
    )
    collapsed = []
    for candidates in grouped.values():
        candidates.sort(
            key=lambda row: (source_document_date(row), int(row.get("version_id") or 0)),
            reverse=True,
        )
        current = dict(candidates[0])
        for older in candidates[1:]:
            for field in merge_fields:
                if not str(current.get(field) or "").strip() and str(older.get(field) or "").strip():
                    current[field] = older[field]
        collapsed.append(current)
    return collapsed


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


def parse_area_sqft(value: object) -> float | None:
    text = str(value or "").replace("\u00a0", " ").strip().lower()
    if not text or any(token in text for token in ("internal", "area", "sq m", "sqm", "sqft")) and not re.search(r"\d", text):
        return None
    match = re.search(r"[\d,]+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        area = float(match.group(0).replace(",", ""))
    except ValueError:
        return None
    if area <= 0:
        return None
    if "sqm" in text or "sq m" in text or area < 250:
        return area * 10.7639
    return area


def is_displayable_unit(value: object) -> bool:
    text = str(value or "").strip()
    if not text or not re.search(r"\d", text):
        return False
    return text.lower() not in {
        "plot",
        "plot no.",
        "plot no",
        "unit",
        "unit no",
        "unit area",
        "unit area sqft",
        "apartment no.",
        "apart- ment no.",
    }


def normalize_status(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def normalize_bedrooms(value: object) -> int | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    if text in {"studio", "suite"}:
        return 0
    leading = re.match(r"^\s*([0-9]+)\s*(?:bed|beds|bedroom|bedrooms|b\b)", text)
    if leading:
        return int(leading.group(1))
    match = re.search(r"\b([0-9]+)\b", text)
    if match:
        return int(match.group(1))
    words = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
    }
    for word, number in words.items():
        if re.search(rf"\b{word}\b", text):
            return number
    return None


def load_manual_rent_benchmarks(conn: sqlite3.Connection) -> list[dict]:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='manual_rent_benchmarks'"
    ).fetchone()
    if not exists:
        return []
    query = """
        SELECT b.*
        FROM manual_rent_benchmarks b
        JOIN (
            SELECT project_match, bedroom, MAX(estimate_month) AS estimate_month
            FROM manual_rent_benchmarks
            GROUP BY project_match, bedroom
        ) latest
          ON latest.project_match = b.project_match
         AND latest.bedroom = b.bedroom
         AND latest.estimate_month = b.estimate_month
        ORDER BY LENGTH(b.project_match) DESC
    """
    return [dict(row) for row in conn.execute(query)]


def load_manual_unit_overrides(conn: sqlite3.Connection) -> list[dict]:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='manual_unit_overrides'"
    ).fetchone()
    if not exists:
        return []
    return [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM manual_unit_overrides ORDER BY LENGTH(project_match) DESC"
        )
    ]


def manual_override_for_unit(row: dict, overrides: list[dict]) -> dict | None:
    project_name = str(row.get("project_name") or "").casefold()
    unit = str(row.get("unit") or "").strip().casefold()
    for override in overrides:
        if (
            str(override["project_match"]).casefold() in project_name
            and str(override["unit_match"]).strip().casefold() == unit
        ):
            return override
    return None


def manual_rent_for_unit(row: dict, benchmarks: list[dict]) -> dict | None:
    project_name = str(row.get("project_name") or "").casefold()
    bedrooms = normalize_bedrooms(row.get("bedroom"))
    area_sqft = parse_area_sqft(row.get("internal_area"))
    if bedrooms is None:
        return None
    for benchmark in benchmarks:
        if not (
            str(benchmark["project_match"]).casefold() in project_name
            and int(benchmark["bedroom"]) == bedrooms
        ):
            continue
        if benchmark.get("min_area_sqft") is not None and (
            area_sqft is None or area_sqft < float(benchmark["min_area_sqft"])
        ):
            continue
        if benchmark.get("max_area_sqft") is not None and (
            area_sqft is None or area_sqft > float(benchmark["max_area_sqft"])
        ):
            continue
        return benchmark
    return None


def availability_bucket(status_value: object = "", unit_value: object = "", price_value: object = "") -> str:
    status = normalize_status(" ".join(str(value or "") for value in (status_value, unit_value, price_value)))
    if "unreleased" in status or "not released" in status:
        return "other"
    if any(token in status for token in UNAVAILABLE_TOKENS):
        return "sold"
    if any(token in status for token in RESERVED_TOKENS):
        return "reserved"
    if not status or any(token in status for token in ("available", "released", "for sale")):
        return "available"
    if parse_money(price_value) is not None:
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
              AND COALESCE(distribution_scope, 'STANDARD') = 'STANDARD'
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
            v.version_label,
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
        JOIN pricelist_versions event_version
          ON event_version.id = e.new_version_id
         AND COALESCE(event_version.distribution_scope, 'STANDARD') = 'STANDARD'
        JOIN (
            SELECT e2.project_name, e2.unit_key, MAX(e2.id) AS event_id
            FROM unit_change_events e2
            JOIN pricelist_versions v2
              ON v2.id = e2.new_version_id
             AND COALESCE(v2.distribution_scope, 'STANDARD') = 'STANDARD'
            GROUP BY e2.project_name, e2.unit_key
        ) latest ON latest.event_id = e.id
    """
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        units = collapse_confirmed_phase_aliases([dict(row) for row in conn.execute(query)])
        manual_rent_benchmarks = load_manual_rent_benchmarks(conn)
        manual_unit_overrides = load_manual_unit_overrides(conn)
        source_field_overrides = load_source_field_overrides()
        events = {
            (row["project_name"], row["unit_key"]): dict(row)
            for row in conn.execute(event_query)
        }
    for row in units:
        event = events.get((row.get("source_project_name"), row.get("unit_key")), {})
        unit_override = manual_override_for_unit(row, manual_unit_overrides)
        if unit_override:
            for field in ("bedroom", "floor", "internal_area"):
                if unit_override.get(field) is not None:
                    row[field] = unit_override[field]
        manual_rent = manual_rent_for_unit(row, manual_rent_benchmarks)
        base_project = re.split(r"\s+[·路]\s+", str(row.get("project_name") or ""), maxsplit=1)[0]
        not_provided = source_field_overrides.get(normalized_project(base_project), set())
        if "floor" in not_provided and not str(row.get("floor") or "").strip():
            row["floor"] = "N/A"
        row["rent_source"] = "PRICE_LIST" if str(row.get("rent_estimate") or "").strip() else ""
        row["rent_estimate_month"] = ""
        if (
            unit_override
            and unit_override.get("rent_amount") is not None
            and (
                not str(row.get("rent_estimate") or "").strip()
                or unit_override.get("source_type") == "PRICE_LIST_RECOGNIZED"
            )
        ):
            amount = float(unit_override["rent_amount"])
            amount_text = f"{amount:,.0f}" if amount.is_integer() else f"{amount:,.2f}"
            row["rent_estimate"] = f"£{amount_text} {unit_override['rent_period']}"
            row["rent_source"] = unit_override["source_type"]
            row["rent_estimate_month"] = unit_override.get("estimate_month") or ""
        if manual_rent and not str(row.get("rent_estimate") or "").strip():
            amount = float(manual_rent["rent_amount"])
            amount_text = f"{amount:,.0f}" if amount.is_integer() else f"{amount:,.2f}"
            row["rent_estimate"] = f"£{amount_text} {manual_rent['rent_period']}"
            row["rent_source"] = manual_rent["source_type"]
            row["rent_estimate_month"] = manual_rent["estimate_month"]
        row["price_number"] = parse_money(row.get("price"))
        row["availability"] = availability_bucket(row.get("status"), row.get("unit"), row.get("price"))
        row["rent_number"] = parse_money(row.get("rent_estimate"))
        row["area_sqft"] = parse_area_sqft(row.get("internal_area"))
        row["price_per_sqft"] = (
            row["price_number"] / row["area_sqft"]
            if row.get("price_number") is not None and row.get("area_sqft")
            else None
        )
        rent_period = str(row.get("rent_estimate") or "").lower()
        rent_multiplier = 52 if re.search(r"\bpw\b|per week|weekly", rent_period) else 1 if re.search(r"\bpa\b|per annum|annual", rent_period) else 12
        row["rental_yield"] = (
            row["rent_number"] * rent_multiplier / row["price_number"] * 100
            if row.get("rent_number") is not None and row.get("price_number")
            else None
        )
        row["is_displayable_unit"] = is_displayable_unit(row.get("unit"))
        row["latest_change_type"] = event.get("change_type", "")
        row["latest_price_change"] = event.get("price_change")
        row["latest_change_at"] = event.get("created_at", "")
        row["latest_change_reason"] = event.get("reason", "")
        row.pop("source_project_name", None)
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
        if filters.get("only_available") == "1" and row.get("availability") != "available":
            continue
        if filters.get("displayable_only") == "1" and not row.get("is_displayable_unit"):
            continue
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
