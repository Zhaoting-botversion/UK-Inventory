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
    return "未分类"


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
    .empty {{ background: var(--panel); border: 1px dashed var(--line); border-radius: 8px; padding: 24px; color: var(--muted); }}
    @media (max-width: 900px) {{ .grid, .split {{ grid-template-columns: 1fr; }} header {{ align-items: flex-start; flex-direction: column; }} input {{ min-width: 100%; }} }}
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
    recent_projects = [row for row in projects if is_recent(row["last_updated_at"], 7)]
    latest_run = runs[0] if runs else {}
    latest_run_time = latest_run.get("finished_at") or latest_run.get("started_at") or latest_run.get("_mtime", "")
    drive_synced_at = data.get("drive_state", {}).get("synced_at", "")

    recent_rows = "".join(
        f"""<tr>
          <td><a href="/project/{quote(project['name'])}">{e(project['name'])}</a></td>
          <td>{e(project['city'])}</td>
          <td>{e(project['latest_file'])}</td>
          <td>{fmt_time(project['last_updated_at'])}</td>
        </tr>"""
        for project in recent_projects[:10]
    )
    update_rows = "".join(
        f"""<tr>
          <td>{'<span class="tag archived">已归档</span>' if row['type'] == 'archived' else '<span class="tag today">新上传</span>'}</td>
          <td><a href="/project/{quote(row['project'])}">{e(row['project'])}</a></td>
          <td>{file_link(row)}</td>
          <td>{fmt_time(row['run_time'])}</td>
        </tr>"""
        for row in updates[:12]
    )
    content = f"""
      <h1>英国销控看板</h1>
      <div class="grid">
        <div class="metric"><div class="label">已追踪项目</div><div class="value">{len(projects)}</div></div>
        <div class="metric"><div class="label">有更新项目</div><div class="value">{len(updated_projects)}</div></div>
        <div class="metric"><div class="label">近24小时动态</div><div class="value">{len(today_updates)}</div></div>
        <div class="metric"><div class="label">最近同步时间</div><div class="value" style="font-size:18px">{fmt_time(drive_synced_at) or fmt_time(latest_run_time) or "暂无同步记录"}</div></div>
      </div>
      <div class="split">
        <section>
          <h2>近期更新项目</h2>
          <table><thead><tr><th>项目</th><th>城市/区域</th><th>最新价单文件</th><th>更新时间</th></tr></thead><tbody>{recent_rows}</tbody></table>
        </section>
        <section>
          <h2>最新动态</h2>
          <table><thead><tr><th>类型</th><th>项目</th><th>文件</th><th>时间</th></tr></thead><tbody>{update_rows}</tbody></table>
        </section>
      </div>
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
    city_options = '<option value="">全部城市/区域</option>' + "".join(f'<option {"selected" if city == selected_city else ""}>{e(city)}</option>' for city in cities)
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
          <td>{e(project['city'])}</td>
          <td>{e(project['developer'])}</td>
          <td>{project_status(project)}</td>
          <td>{e(project['latest_date'])}</td>
          <td>{fmt_time(project['last_updated_at'])}</td>
          <td>{e(project['uploaded_count'])}</td>
          <td>{e(project.get('data_source', '日志'))}</td>
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
        <thead><tr><th>项目</th><th>城市/区域</th><th>开发商</th><th>状态</th><th>价单日期</th><th>最近更新</th><th>价单数量</th><th>数据来源</th><th>Google Drive</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    """
    return layout("项目总览", content, "/projects")


def drive_link(project: dict) -> str:
    if project.get("folder_url"):
        return f'<a href="{e(project["folder_url"])}" target="_blank" rel="noreferrer">打开 Drive</a>'
    return '<span class="muted">缺失</span>'


def render_updates(data: dict) -> bytes:
    rows = "".join(
        f"""<tr>
          <td>{fmt_time(row['run_time'])}</td>
          <td>{'<span class="tag archived">已归档</span>' if row['type'] == 'archived' else '<span class="tag today">新上传</span>'}</td>
          <td><a href="/project/{quote(row['project'])}">{e(row['project'])}</a></td>
          <td>{file_link(row)}</td>
          <td class="muted">{e(row['log'])}</td>
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
        f"""<tr><td>{file_link(row)}</td><td>{e(row['price_date'])}</td><td>{fmt_time(row['run_time'])}</td><td class="muted">{e(row['log'])}</td></tr>"""
        for row in files
    ) or '<tr><td colspan="4" class="muted">暂无价单上传记录。</td></tr>'
    archived_rows = "".join(
        f"""<tr><td>{e(row['file'])}</td><td>{e(row['old_folder'])}</td><td>{fmt_time(row['run_time'])}</td><td class="muted">{e(row['log'])}</td></tr>"""
        for row in archived
    ) or '<tr><td colspan="4" class="muted">暂无历史价单归档记录。</td></tr>'
    content = f"""
      <h1>{e(project['name'])}</h1>
      <div class="grid">
        <div class="metric"><div class="label">城市/区域</div><div class="value" style="font-size:20px">{e(project['city'])}</div></div>
        <div class="metric"><div class="label">开发商</div><div class="value" style="font-size:20px">{e(project['developer'])}</div></div>
        <div class="metric"><div class="label">已上传价单</div><div class="value">{e(project['uploaded_count'])}</div></div>
        <div class="metric"><div class="label">已归档旧价单</div><div class="value">{e(project['archived_count'])}</div></div>
      </div>
      <div class="panel" style="margin-top:16px">
        <strong>Google Drive：</strong> {drive_link(project)}
        <span class="muted" style="margin-left:18px">最近更新：{fmt_time(project['last_updated_at']) or "暂无记录"}</span>
      </div>
      {f'<div class="panel" style="margin-top:10px"><strong>Drive 路径：</strong>{e(project.get("path", ""))}</div>' if project.get("path") else ""}
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
