# 英国销控看板 MVP

这是英国项目销控看板的本地 MVP，用来把 Google Drive 里 `UK 英国` 文件夹下已有的标准项目文件夹汇总成一个可搜索、可筛选的项目列表。

## 数据来源

- `drive_state.json`：Google Drive 当前快照，优先读取
- `../迁移资料到Google Drive/logs/uk_update_*.json`：英国项目价单自动更新日志，用于“更新记录”
- `../迁移资料到Google Drive/logs/berkeley_update_*.json`：历史日志，继续兼容读取
- `../迁移资料到Google Drive/uk_update_pricelists.py`：英国项目映射，用于识别开发商和项目文件夹

## 当前范围

同步脚本会扫描 Google Drive 的 `UK 英国` 根目录，并识别包含标准子文件夹的项目：

- `项目图 Photo`
- `视频 Video`
- `价单 Price List`
- `楼盘资料 Brochure, Factsheet & Floorplan`

只要项目在 Drive 里有类似结构，就会进入看板，不限于 Berkeley。

## 页面

- `http://127.0.0.1:8765/` 首页
- `http://127.0.0.1:8765/projects` 项目总览
- `http://127.0.0.1:8765/units` 房源库
- `http://127.0.0.1:8765/updates` 更新记录
- `http://127.0.0.1:8765/unit-changes` 房源变化

## 房源变化数据库

`unit_change_engine.py` 是独立的房源变化 MVP：

- 把 PDF、Excel、CSV 价单抽取为房源记录
- 记录每个项目的价单版本
- 对比上一版和最新版，识别降价、涨价、新放出、售出/下架、状态变化
- 写入 `inventory_units.sqlite`
- 在网站的“房源变化”页面展示，也会在单个项目页展示该项目最近的房源变化
- 在网站的“房源库”页面展示当前每个项目最新可解析价单中的房源，并支持项目、户型、价格、状态和变化类型筛选

测试样本：

```powershell
python unit_change_engine.py seed-postmark-test --reset
python unit_change_engine.py recent --limit 20
```

真实价单入库示例：

```powershell
python unit_change_engine.py ingest --project "WC1X - Postmark, Farringdon" --file "C:\path\to\new_price_list.pdf" --version-label "04.07.26"
```

## 启动

双击：

```text
启动英国销控MVP.cmd
```

或在当前文件夹运行：

```powershell
python app.py
```

## 发布线上网站

日常只需要双击：

```text
发布销控网站.cmd
```

这个脚本会让你选择：

- `1`：快速发布当前数据，默认选项
- `2`：重新扫描 Google Drive 后发布

如果 8 秒内不选择，会自动使用 `1` 模式。

## 什么时候选哪个

- 日常改了网页、开发商、合作信息、已有 `drive_state.json`：选 `1 快速发布当前数据`
- Google Drive 里新增、移动、重命名或归档了项目/价单：选 `2 重新扫描 Google Drive 后发布`

旧的拆分脚本已经移到 `高级工具_旧脚本`，日常不需要使用。

它会自动执行：

1. 重新扫描 Google Drive 的 `UK 英国`
2. 生成新的 `drive_state.json`
3. 复制到 GitHub Pages 部署仓库
4. 如果数据有变化，自动 commit 并 push 到 GitHub
5. GitHub Actions 自动重新部署页面

云端地址：

```text
https://zhaoting-botversion.github.io/UK-Inventory/
```

如果 Google Drive 没有变化，脚本会提示 `No Drive changes detected`，不会重复发布。

脚本比较变化时会忽略 `synced_at` 时间戳，所以只有项目、文件、价单链接等实际内容变化时才会推送到 GitHub。

全量扫描依赖 Google Drive API 和本地网络，可能会比较慢。扫描窗口现在会显示正在扫描的文件夹和正在收集的项目，方便判断进度。

## 注意

- 项目总览现在以 Google Drive 快照为准，避免旧 Berkeley 项目名和带邮编的新项目名重复显示。
- “更新记录”读取英国项目价单自动上传和旧价单归档日志，历史 Berkeley 日志继续兼容。
- 非 Berkeley 项目的开发商字段目前多为“未分类”，后续可以继续补充开发商识别规则。

## 云端部署

第一版建议部署为只读看板：云端读取 `drive_state.json`，老板可以通过网址远程查看；Google Drive 同步仍然在本地运行。

推荐部署文件夹：

```text
uk_inventory_mvp/
```

需要包含：

- `app.py`
- `drive_state.json`
- `requirements.txt`
- `Procfile`
- `runtime.txt`
- `render.yaml`

云平台启动命令：

```powershell
python app.py
```

环境变量：

```text
DASHBOARD_USER=自定义用户名
DASHBOARD_PASSWORD=自定义密码
```

如果不设置这两个环境变量，网站会直接公开访问。由于这里面有项目资料和价单入口，建议云端一定设置密码。

### Render 部署步骤

1. 把 `uk_inventory_mvp` 上传到一个 GitHub 仓库。
2. 打开 Render，选择 New Web Service。
3. 连接这个 GitHub 仓库。
4. Build Command 填：

```powershell
pip install -r requirements.txt
```

5. Start Command 填：

```powershell
python app.py
```

6. 在 Environment Variables 里设置 `DASHBOARD_USER` 和 `DASHBOARD_PASSWORD`。
7. 部署完成后，把 Render 生成的网址发给老板。

### 手动更新云端数据

当 Google Drive 里项目或价单变化后：

1. 本地双击 `同步GoogleDrive当前状态.cmd`
2. 确认新的 `drive_state.json` 已生成
3. 把新的 `drive_state.json` 提交并推送到 GitHub
4. 云端自动重新部署后，老板看到的就是最新数据
