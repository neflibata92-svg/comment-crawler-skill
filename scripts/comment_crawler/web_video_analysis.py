"""通过普通网页播放截取视频画面；不读取或保存视频流文件。"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path
import shutil
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from .video_analysis import _ocr_frames, _write_contact_sheets, _write_json

_PLATFORM_DOMAINS = (
    "youtube.com", "youtu.be", "douyin.com", "bilibili.com", "b23.tv",
    "weibo.com", "weibo.cn", "xiaohongshu.com", "xhslink.com", "zhihu.com", "baidu.com",
)


def is_supported_platform_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except (TypeError, ValueError):
        return False
    if (parsed.scheme.casefold() != "https" or "@" in parsed.netloc or parsed.username or parsed.password
            or port not in (None, 443) or not parsed.hostname):
        return False
    host = parsed.hostname.casefold()
    return any(host == domain or host.endswith("." + domain) for domain in _PLATFORM_DOMAINS)


def _source_reference_url(url: str) -> str:
    parsed = urlsplit(url)
    query = ""
    if parsed.hostname and parsed.hostname.casefold() in {"youtube.com", "www.youtube.com", "m.youtube.com"} and parsed.path == "/watch":
        video_id = parse_qs(parsed.query).get("v", [""])[0]
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            query = urlencode({"v": video_id})
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, ""))


def _guard_document_navigation(route: Any) -> None:
    request = route.request
    if request.is_navigation_request() and not is_supported_platform_url(request.url):
        route.abort("blockedbyclient")
    else:
        route.continue_()


class WebVideoSession:
    """Reuse one Playwright browser context for videos whose media file is unavailable."""

    def __init__(self, profile_directory: str | Path | None = None, *, interval_seconds: float = 8.0):
        self.profile_directory = Path(profile_directory).expanduser().resolve() if profile_directory else None
        self.interval_seconds = interval_seconds
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None

    def _ensure_started(self) -> None:
        if self._context is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "网页视频回退需要浏览器依赖：python -m pip install '.[browser]'，然后运行 playwright install chromium"
            ) from exc
        self._playwright = sync_playwright().start()
        if self.profile_directory:
            self.profile_directory.mkdir(parents=True, exist_ok=True)
            self._context = self._playwright.chromium.launch_persistent_context(
                str(self.profile_directory), headless=False,
            )
        else:
            self._browser = self._playwright.chromium.launch(headless=True)
            self._context = self._browser.new_context()

    def analyze(self, url: str, output_dir: Path) -> dict[str, Any]:
        if not is_supported_platform_url(url):
            raise ValueError("网页视频回退仅接受已支持平台的 HTTPS 视频页面")
        if self.interval_seconds <= 0:
            raise ValueError("interval_seconds 必须大于 0")
        output_dir = output_dir.resolve()
        asset_dir = output_dir / "web-page-capture"
        manifest_path = asset_dir / "manifest.json"
        if manifest_path.is_file():
            try:
                previous = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                previous = {}
            try:
                previous_frame_count = int(previous.get("frame_count", 0)) if isinstance(previous, dict) else 0
            except (TypeError, ValueError):
                previous_frame_count = 0
            if (isinstance(previous, dict) and previous.get("status") == "completed"
                    and previous_frame_count > 0
                    and len(list((asset_dir / "frames").glob("frame_*"))) >= previous_frame_count
                    and (asset_dir / "frames_ocr.json").is_file()
                    and (asset_dir / "frames_ocr.txt").is_file()):
                return previous
        self._ensure_started()
        if asset_dir.exists():
            shutil.rmtree(asset_dir)
        frames_dir = asset_dir / "frames"
        frames_dir.mkdir(parents=True)
        page = self._context.new_page()
        try:
            page.route("**/*", _guard_document_navigation)
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            page.locator("video").first.wait_for(state="attached", timeout=25_000)
            videos = page.locator("video")
            candidates = []
            for index in range(videos.count()):
                locator = videos.nth(index)
                box = locator.bounding_box()
                if box and box["width"] >= 160 and box["height"] >= 90:
                    candidates.append((box["width"] * box["height"], locator, box))
            if not candidates:
                raise RuntimeError("网页已打开，但没有找到可见的视频播放器")
            _, video, box = max(candidates, key=lambda item: item[0])
            video.scroll_into_view_if_needed(timeout=10_000)
            video.evaluate("""async v => {
              if (v.readyState >= 2) return;
              await new Promise((resolve, reject) => {
                const timer = setTimeout(() => reject(new Error('video_ready_timeout')), 25000);
                const done = () => { clearTimeout(timer); resolve(); };
                v.addEventListener('loadeddata', done, {once: true});
                if (v.readyState >= 2) done();
              });
            }""")
            media = video.evaluate("""async v => {
              v.muted = true;
              v.playsInline = true;
              try { await v.play(); } catch (_) {}
              return {duration: Number(v.duration), width: v.videoWidth, height: v.videoHeight};
            }""")
            duration = float(media.get("duration", 0))
            if not duration or duration != duration or duration == float("inf"):
                raise RuntimeError("网页播放器没有提供有限的视频时长，无法安全确定取帧范围")

            frames = []
            timestamp = 0.0
            frame_index = 1
            while timestamp < duration:
                actual_time = video.evaluate("""async (v, target) => {
                  v.pause();
                  if (Math.abs(v.currentTime - target) > 0.25) {
                    await new Promise((resolve, reject) => {
                      const timer = setTimeout(() => reject(new Error('seek_timeout')), 20000);
                      const done = () => { clearTimeout(timer); resolve(); };
                      v.addEventListener('seeked', done, {once: true});
                      v.currentTime = target;
                    });
                  }
                  await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
                  return Number(v.currentTime);
                }""", timestamp)
                box = video.bounding_box()
                if not box:
                    raise RuntimeError("视频播放器在采样时变为不可见")
                filename = f"frame_{frame_index:06d}.png"
                page.screenshot(
                    path=str(frames_dir / filename),
                    clip={"x": box["x"], "y": box["y"], "width": box["width"], "height": box["height"]},
                    timeout=30_000,
                )
                frames.append({
                    "file": f"frames/{filename}",
                    "timestamp_seconds": round(float(actual_time), 3),
                })
                frame_index += 1
                timestamp += self.interval_seconds

            if not frames:
                raise RuntimeError("网页播放器没有产生可用视频帧")
            sheets = _write_contact_sheets(asset_dir, frames)
            frame_ocr = _ocr_frames(asset_dir, frames)
            with (asset_dir / "frames.csv").open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=("file", "timestamp_seconds"))
                writer.writeheader()
                writer.writerows(frames)
            manifest = {
                "status": "completed",
                "capture_method": "rendered_webpage_screenshot",
                "source_url": _source_reference_url(url),
                "media": {
                    "duration_seconds": duration,
                    "width": media.get("width"),
                    "height": media.get("height"),
                    "audio_transcription": "not_requested",
                },
                "frame_count": len(frames),
                "contact_sheets": sheets,
                "frame_ocr": frame_ocr,
                "source_video_saved": False,
            }
            _write_json(manifest_path, manifest)
            return manifest
        except BaseException:
            shutil.rmtree(asset_dir, ignore_errors=True)
            raise
        finally:
            page.close()

    def close(self) -> None:
        if self._context is not None:
            self._context.close()
            self._context = None
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None

    def __enter__(self) -> "WebVideoSession":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()
