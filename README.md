# YouTube Live Snapshot

这个仓库用于把 YouTube 直播画面截图发布到 GitHub Pages。

推荐运行方式是：Cloudflare Worker 每 5 分钟在云端打开 YouTube，截取播放器画面，然后把 JPG 图片上传到 GitHub Pages。国内用户只加载 GitHub 上的图片，不直接访问 YouTube。

当前直播地址：

```text
https://www.youtube.com/watch?v=FS7IPxmfEms
```

## 文件说明

- `cloudflare-worker/`：Cloudflare 云端截图并上传 GitHub 的主方案。
- `.github/workflows/snapshot.yml`：手动备用截图流程。
- `scripts/live_room_daemon.py`：云服务器常驻直播间截图 worker，作为备用方案。
- `scripts/run_cloud_live_worker.sh`：云服务器备用启动脚本。
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

## Cloudflare 云端截图

进入 `cloudflare-worker/`，复制配置并部署：

```bash
cp wrangler.toml.example wrangler.toml
npm install
npx wrangler login
npx wrangler secret put GITHUB_TOKEN
npm run deploy
```

部署后，Cloudflare Cron 会每 5 分钟截图一次，并更新：

```text
latest.jpg
manifest.json
snapshots/*.jpg
```

页面会自动读取 `manifest.json`，显示最新截图和最多 5 张历史缩略图。

注意：Cloudflare 也是云端浏览器。如果 YouTube 对 Cloudflare IP 弹验证页，截图会失败；但只要 Cloudflare 能截图成功，国内用户就不需要 VPN。

## 修改配置

Cloudflare Worker 支持这些配置：

```toml
CAPTURE_URL = "https://www.youtube.com/embed/hWWFQd9aMvc?autoplay=1&mute=1&playsinline=1&rel=0&controls=0"
MAX_SNAPSHOTS = "5"
WAIT_MS = "55000"
```

`MAX_SNAPSHOTS` 控制最多保留几张历史截图。
