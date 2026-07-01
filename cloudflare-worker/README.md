# Cloudflare 云端截图 Worker

这个 Worker 每 5 分钟在 Cloudflare 云端打开 YouTube 页面，截取播放器画面，然后上传到 GitHub Pages 的 `gh-pages` 分支。

国内用户访问 GitHub Pages 时只加载 `latest.jpg` 和 `snapshots/*.jpg`，不会直接访问 YouTube。

## 部署

1. 复制配置文件：

```bash
cp wrangler.toml.example wrangler.toml
```

2. 登录 Cloudflare：

```bash
npx wrangler login
```

3. 设置 GitHub token：

```bash
npx wrangler secret put GITHUB_TOKEN
```

4. 可选：设置手动触发密钥：

```bash
npx wrangler secret put RUN_KEY
```

5. 部署：

```bash
npm install
npm run deploy
```

部署后，Cloudflare Cron 会每 5 分钟运行一次。也可以访问：

```text
https://你的-worker域名/run?key=RUN_KEY
```

手动触发一次截图。

## 重要说明

Cloudflare 仍然是云端浏览器。如果 YouTube 对 Cloudflare IP 弹出验证页，截图会失败。这个方案解决的是“国内用户不用访问 YouTube”，不保证 Cloudflare 一定能稳定打开 YouTube。
