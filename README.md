# YouTube Live Snapshot

这个仓库用于把 YouTube 直播画面截图发布到 GitHub Pages。

最终运行方式是：在一台不会关机的云服务器上运行常驻 worker。worker 会打开一次直播间，跳过广告或等待广告结束，然后留在同一个播放器里每 5 分钟截图一次；只有直播断开或播放器失效时，才隔 5 分钟重连。

当前直播地址：

```text
https://www.youtube.com/watch?v=FS7IPxmfEms
```

## 文件说明

- `.github/workflows/snapshot.yml`：手动备用截图流程，不再定时反复打开 YouTube。
- `scripts/live_room_daemon.py`：云端常驻直播间截图 worker。
- `scripts/run_cloud_live_worker.sh`：云服务器启动脚本。
- `scripts/capture_youtube_page.py`：备用单次截图脚本，会解析真实直播源请求。
- `scripts/update_site.py`：更新 `latest.jpg`、历史截图和 `manifest.json`。
- `public/index.html`：GitHub Pages 页面。

## GitHub Pages

1. 在 GitHub 新建一个公开仓库。
2. 把本目录里的所有文件上传到仓库默认分支，通常是 `main`。
3. 打开仓库的 `Settings` -> `Actions` -> `General`，确认 Workflow permissions 允许 `Read and write permissions`。
4. 打开 `Settings` -> `Pages`，在 Source 里选择 `Deploy from a branch`，Branch 选择 `gh-pages` 和 `/ (root)`。

页面地址通常是：

```text
https://你的GitHub用户名.github.io/仓库名/
```

## 云端常驻 worker

在云服务器里设置这些环境变量：

```bash
export GITHUB_REPOSITORY="china-xxoo/chinaxxoo"
export GITHUB_TOKEN="你的 GitHub token"
export YOUTUBE_COOKIES_B64="你的 YouTube cookies base64"
export YOUTUBE_URL="https://www.youtube.com/watch?v=FS7IPxmfEms"
export MAX_SNAPSHOTS="5"
export CAPTURE_INTERVAL="300"
export RETRY_INTERVAL="300"
```

然后运行：

```bash
./scripts/run_cloud_live_worker.sh
```

长期运行时，可以把 `deploy/live-room-worker.service.example` 复制成 systemd 服务，并把环境变量放到服务器的 `/opt/chinaxxoo/.env`。这样云服务器重启后 worker 也会自动恢复。

## 修改配置

云端 worker 支持这些配置：

```bash
YOUTUBE_URL="https://www.youtube.com/watch?v=FS7IPxmfEms"
MAX_SNAPSHOTS="5"
SITE_TIMEZONE="Asia/Shanghai"
CAPTURE_INTERVAL="300"
RETRY_INTERVAL="300"
```

`MAX_SNAPSHOTS` 控制最多保留几张历史截图。
