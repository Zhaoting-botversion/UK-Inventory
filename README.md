# 英国销控看板 MVP

这是英国项目销控看板的本地 MVP，用来把 Google Drive 里 `UK 英国` 文件夹下已有的标准项目文件夹汇总成一个可搜索、可筛选的项目列表。

## 数据来源

- `drive_state.json`：Google Drive 当前快照，优先读取
- `../logs/berkeley_update_*.json`：Berkeley 自动更新日志，用于“更新记录”
- `../berkeley_update_pricelists.py`：Berkeley 项目映射，用于识别开发商

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
- `http://127.0.0.1:8765/updates` 更新记录

## 启动

双击：

```text
启动英国销控MVP.cmd
```

或在当前文件夹运行：

```powershell
python app.py
```

## 同步 Google Drive 当前状态

如果 Google Drive 里有人手动新增、移动、重命名或归档文件，先双击：

```text
同步GoogleDrive当前状态.cmd
```

它会重新扫描 `UK 英国`，生成 `drive_state.json`。网站会优先读取这个快照；如果没有快照，才回退读取本地更新日志。

## 注意

- 项目总览现在以 Google Drive 快照为准，避免旧 Berkeley 项目名和带邮编的新项目名重复显示。
- “更新记录”仍保留 Berkeley 自动上传和旧价单归档日志，方便追踪最近操作。
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

### 更新云端数据

当 Google Drive 里项目或价单变化后：

1. 本地双击 `同步GoogleDrive当前状态.cmd`
2. 确认新的 `drive_state.json` 已生成
3. 把新的 `drive_state.json` 提交并推送到 GitHub
4. 云端自动重新部署后，老板看到的就是最新数据
