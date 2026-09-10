from __future__ import annotations

import json
import re
from pathlib import Path


DEFAULT_PATH = Path(__file__).resolve().parent / "phase_alias_overrides.json"
PROJECT_PHASE_SEPARATOR = " · "


def norm(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def split_project_phase(project_name: str) -> tuple[str, str]:
    parts = re.split(r"\s+[·路]\s+", project_name or "", maxsplit=1)
    return (parts[0].strip(), parts[1].strip() if len(parts) > 1 else "")


def load_phase_aliases(path: Path = DEFAULT_PATH) -> dict[tuple[str, str], str]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    aliases: dict[tuple[str, str], str] = {}
    for item in payload.get("overrides", []):
        project = norm(item.get("project"))
        alias = norm(item.get("alias"))
        canonical = norm(item.get("canonical"))
        if project and alias and canonical:
            aliases[(project, alias)] = canonical
    return aliases


def load_project_aliases(path: Path = DEFAULT_PATH) -> dict[str, str]:
    """Load presentation-level project identity corrections.

    Source rows keep their original project names for append-only history.  This
    mapping corrects the canonical identity used by current inventory views.
    """
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        norm(item.get("source")): str(item.get("canonical") or "").strip()
        for item in payload.get("project_overrides", [])
        if norm(item.get("source")) and str(item.get("canonical") or "").strip()
    }


def canonical_phase(project: str, phase: str, aliases: dict[tuple[str, str], str] | None = None) -> str:
    aliases = aliases if aliases is not None else load_phase_aliases()
    return aliases.get((norm(project), norm(phase)), norm(phase))


def canonical_project_name(project_name: str, aliases: dict[tuple[str, str], str] | None = None) -> str:
    project, phase = split_project_phase(project_name)
    project = load_project_aliases().get(norm(project), project)
    if not phase:
        return project
    canonical = canonical_phase(project, phase, aliases)
    if canonical == "main":
        return project
    return f"{project}{PROJECT_PHASE_SEPARATOR}{canonical}"
