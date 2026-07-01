import puppeteer from "@cloudflare/puppeteer";

const DEFAULT_CAPTURE_URL =
  "https://www.youtube.com/embed/hWWFQd9aMvc?autoplay=1&mute=1&playsinline=1&rel=0&controls=0";

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname !== "/run") {
      return new Response("YouTube cloud snapshot worker is ready.\n", {
        headers: { "content-type": "text/plain; charset=utf-8" },
      });
    }

    if (env.RUN_KEY && url.searchParams.get("key") !== env.RUN_KEY) {
      return new Response("Forbidden\n", { status: 403 });
    }

    const result = await captureAndPublish(env);
    return Response.json(result);
  },

  async scheduled(_event, env, ctx) {
    ctx.waitUntil(captureAndPublish(env));
  },
};

async function captureAndPublish(env) {
  const captureUrl = env.CAPTURE_URL || DEFAULT_CAPTURE_URL;
  const maxSnapshots = numberEnv(env.MAX_SNAPSHOTS, 5);
  const waitMs = numberEnv(env.WAIT_MS, 55_000);
  const capturedAt = new Date().toISOString();
  const snapshotFile = `snapshots/${snapshotName(capturedAt)}`;

  const image = await captureYoutubeFrame(env, captureUrl, waitMs);
  const manifest = await loadManifest(env);
  const snapshots = [
    { file: snapshotFile, capturedAt },
    ...(manifest.snapshots || []).filter((item) => item.file !== snapshotFile),
  ].slice(0, maxSnapshots);

  await putGithubFile(env, snapshotFile, image, `Add live snapshot ${capturedAt}`);
  await putGithubFile(env, "latest.jpg", image, `Update latest live snapshot ${capturedAt}`);
  await putGithubText(
    env,
    "manifest.json",
    JSON.stringify(
      {
        sourceUrl: captureUrl,
        latest: { file: "latest.jpg", capturedAt },
        snapshots,
      },
      null,
      2,
    ) + "\n",
    `Update live snapshot manifest ${capturedAt}`,
  );
  await cleanupOldSnapshots(env, snapshots);

  return {
    ok: true,
    capturedAt,
    latest: "latest.jpg",
    snapshot: snapshotFile,
    kept: snapshots.length,
  };
}

async function captureYoutubeFrame(env, captureUrl, waitMs) {
  const browser = await puppeteer.launch(env.BROWSER);
  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1366, height: 768 });
    await page.setUserAgent(
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    );
    await page.goto(captureUrl, { waitUntil: "domcontentloaded", timeout: 60_000 });

    const deadline = Date.now() + waitMs;
    while (Date.now() < deadline) {
      await clickFirst(page, [
        "button.ytp-ad-skip-button-modern",
        ".ytp-ad-skip-button-modern",
        "button.ytp-ad-skip-button",
        ".ytp-ad-skip-button",
        ".ytp-skip-ad-button",
        "button:has-text('Skip')",
        "button:has-text('跳过')",
      ]);
      await page.evaluate(() => {
        const video = document.querySelector("video");
        if (!video) return;
        video.muted = true;
        video.play().catch(() => {});
      });
      await page.waitForTimeout(2_000);
    }

    const player =
      (await page.$("#movie_player")) ||
      (await page.$(".html5-video-player")) ||
      (await page.$("video"));
    if (player) {
      return await player.screenshot({ type: "jpeg", quality: 88 });
    }
    return await page.screenshot({ type: "jpeg", quality: 88, fullPage: false });
  } finally {
    await browser.close();
  }
}

async function clickFirst(page, selectors) {
  for (const selector of selectors) {
    try {
      const element = await page.$(selector);
      if (element) {
        await element.click();
        return true;
      }
    } catch (_error) {
      // Try the next selector.
    }
  }
  return false;
}

async function loadManifest(env) {
  const current = await getGithubFile(env, "manifest.json");
  if (!current) {
    return { sourceUrl: "", latest: null, snapshots: [] };
  }
  try {
    return JSON.parse(current.text);
  } catch (_error) {
    return { sourceUrl: "", latest: null, snapshots: [] };
  }
}

async function cleanupOldSnapshots(env, snapshots) {
  const keep = new Set(snapshots.map((item) => item.file));
  const files = await listGithubDirectory(env, "snapshots");
  await Promise.all(
    files
      .filter((file) => file.type === "file")
      .filter((file) => file.name.endsWith(".jpg"))
      .filter((file) => !keep.has(`snapshots/${file.name}`))
      .map((file) => deleteGithubFile(env, `snapshots/${file.name}`, file.sha)),
  );
}

async function githubRequest(env, path, init = {}) {
  const owner = requiredEnv(env, "GITHUB_OWNER");
  const repo = requiredEnv(env, "GITHUB_REPO");
  const token = requiredEnv(env, "GITHUB_TOKEN");
  const response = await fetch(`https://api.github.com/repos/${owner}/${repo}${path}`, {
    ...init,
    headers: {
      authorization: `Bearer ${token}`,
      accept: "application/vnd.github+json",
      "x-github-api-version": "2022-11-28",
      "user-agent": "cloudflare-youtube-snapshot",
      ...(init.headers || {}),
    },
  });

  if (response.status === 404) {
    return null;
  }
  if (!response.ok) {
    throw new Error(`GitHub API ${response.status}: ${await response.text()}`);
  }
  return response.json();
}

async function getGithubFile(env, path) {
  const branch = env.GITHUB_BRANCH || "gh-pages";
  const data = await githubRequest(env, `/contents/${encodePath(path)}?ref=${branch}`);
  if (!data) {
    return null;
  }
  return {
    sha: data.sha,
    text: decodeBase64Text(data.content || ""),
  };
}

async function listGithubDirectory(env, path) {
  const branch = env.GITHUB_BRANCH || "gh-pages";
  const data = await githubRequest(env, `/contents/${encodePath(path)}?ref=${branch}`);
  return Array.isArray(data) ? data : [];
}

async function putGithubFile(env, path, bytes, message) {
  const current = await getGithubFile(env, path);
  const body = {
    message,
    branch: env.GITHUB_BRANCH || "gh-pages",
    content: bytesToBase64(bytes),
  };
  if (current?.sha) {
    body.sha = current.sha;
  }
  await githubRequest(env, `/contents/${encodePath(path)}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

async function putGithubText(env, path, text, message) {
  await putGithubFile(env, path, new TextEncoder().encode(text), message);
}

async function deleteGithubFile(env, path, sha) {
  await githubRequest(env, `/contents/${encodePath(path)}`, {
    method: "DELETE",
    body: JSON.stringify({
      message: `Delete old live snapshot ${path}`,
      branch: env.GITHUB_BRANCH || "gh-pages",
      sha,
    }),
  });
}

function encodePath(path) {
  return path
    .split("/")
    .map((part) => encodeURIComponent(part))
    .join("/");
}

function snapshotName(isoString) {
  return isoString.replaceAll(":", "-").replaceAll(".", "-") + ".jpg";
}

function numberEnv(value, fallback) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function requiredEnv(env, name) {
  const value = env[name];
  if (!value) {
    throw new Error(`${name} is required`);
  }
  return value;
}

function bytesToBase64(bytes) {
  const array = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  let binary = "";
  const chunkSize = 0x8000;
  for (let index = 0; index < array.length; index += chunkSize) {
    binary += String.fromCharCode(...array.subarray(index, index + chunkSize));
  }
  return btoa(binary);
}

function decodeBase64Text(value) {
  const compact = value.replaceAll("\n", "");
  const binary = atob(compact);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return new TextDecoder().decode(bytes);
}
