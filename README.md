# YouTube Live Snapshot

这个仓库会每 5 分钟截取一次 YouTube 直播画面，并发布到 GitHub Pages。

当前直播地址：

```text
https://www.youtube.com/watch?v=FS7IPxmfEms
```

## 文件说明

- `.github/workflows/snapshot.yml`：定时截图并发布页面。
- `scripts/update_site.py`：更新 `latest.jpg`、历史截图和 `manifest.json`。
- `public/index.html`：GitHub Pages 页面。

## 使用步骤

1. 在 GitHub 新建一个公开仓库。
2. 把本目录里的所有文件上传到仓库默认分支，通常是 `main`。
3. 打开仓库的 `Settings` -> `Actions` -> `General`，确认 Workflow permissions 允许 `Read and write permissions`。
4. 打开 `Settings` -> `Pages`，在 Source 里选择 `Deploy from a branch`，Branch 选择 `gh-pages` 和 `/ (root)`。
5. 第一次可以到 `Actions` 里手动运行 `YouTube Live Snapshot`，之后会每 5 分钟自动运行。

页面地址通常是：

```text
https://你的GitHub用户名.github.io/仓库名/
```

## 修改配置

在 `.github/workflows/snapshot.yml` 里可以改：

```yaml
YOUTUBE_URL: "https://www.youtube.com/watch?v=FS7IPxmfEms"
MAX_SNAPSHOTS: "10"
SITE_TIMEZONE: "Asia/Shanghai"
```

`MAX_SNAPSHOTS` 控制最多保留几张历史截图。
