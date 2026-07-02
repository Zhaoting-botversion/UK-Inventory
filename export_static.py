from __future__ import annotations

import shutil
from pathlib import Path
from urllib.parse import quote

import app


SITE_DIR = Path(__file__).resolve().parent / "site"
BASE_PATH = "/UK-Inventory"


def static_html(body: bytes) -> bytes:
    text = body.decode("utf-8")
    text = text.replace('href="/', f'href="{BASE_PATH}/')
    text = text.replace('action="/', f'action="{BASE_PATH}/')
    return text.encode("utf-8")


def write_page(relative_path: str, body: bytes) -> None:
    target = SITE_DIR / relative_path / "index.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(static_html(body))


def main() -> None:
    if SITE_DIR.exists():
        shutil.rmtree(SITE_DIR)
    SITE_DIR.mkdir(parents=True)

    data = app.build_data()
    write_page("", app.render_dashboard(data))
    write_page("projects", app.render_projects(data, {}))
    write_page("updates", app.render_updates(data))

    for project in data["projects"]:
        write_page(f"project/{quote(project['name'])}", app.render_project(data, project["name"]))

    (SITE_DIR / ".nojekyll").write_text("", encoding="utf-8")


if __name__ == "__main__":
    main()
