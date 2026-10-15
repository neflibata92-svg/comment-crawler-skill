"""本地 OCR MediaCrawler 下载的封面和图文图片，并在持久化文字后删除图片。"""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any


IMAGE_SUFFIXES = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
VIDEO_SUFFIXES = {".avi", ".flv", ".m4v", ".mkv", ".mov", ".mp4", ".webm"}


def _load_manifest(path: Path) -> tuple[dict[str, Any], str]:
    if not path.exists():
        return {"version": 1, "posts": {}}, ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, "image_ocr_manifest_unreadable"
    if (not isinstance(payload, dict) or payload.get("version") != 1
            or not isinstance(payload.get("posts"), dict)
            or any(not isinstance(key, str) or not isinstance(entries, list)
                   or any(not isinstance(item, dict) or not isinstance(item.get("file"), str)
                          or not isinstance(item.get("text"), str) or not isinstance(item.get("status"), str)
                          for item in entries)
                   for key, entries in payload["posts"].items())):
        return {}, "image_ocr_manifest_unreadable"
    return payload, ""


def _save_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _video_output_dir(data_root: Path, post_key: str) -> Path:
    slug = re.sub(r"[^0-9A-Za-z_-]+", "-", post_key).strip("-")[:80] or "post"
    return data_root / "video-analysis" / slug


def process_media_assets(
    media_dir: Path,
    data_root: Path,
    post_key: str,
    *,
    download_requested: bool,
    request_status: str,
    video_url: str = "",
    web_video_session: Any = None,
    profile_directory: str | Path | None = None,
) -> dict[str, Any]:
    """Return video paths and OCR text; image files are removed only after text is persisted."""
    if media_dir.is_symlink():
        raise ValueError("媒体目录不得为符号链接")
    media_dir = media_dir.resolve()
    data_root = data_root.resolve()
    if media_dir == data_root or not media_dir.is_relative_to(data_root):
        raise ValueError("媒体目录超出任务目录")
    if media_dir.is_dir() and any(path.is_symlink() for path in media_dir.rglob("*")):
        raise ValueError("媒体目录包含符号链接文件")
    video_files = sorted(
        path for path in media_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in VIDEO_SUFFIXES
    ) if media_dir.is_dir() else []
    image_files = sorted(
        path for path in media_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    ) if media_dir.is_dir() else []

    manifest_path = data_root / "image_ocr.json"
    manifest, manifest_error = _load_manifest(manifest_path)
    previous = manifest.get("posts", {}).get(post_key, []) if not manifest_error else []
    previous_by_file = {
        item.get("file"): item for item in previous
        if isinstance(item, dict) and isinstance(item.get("file"), str)
    }
    image_results: dict[str, dict[str, str]] = dict(previous_by_file)
    deleted = 0
    engine_error = manifest_error

    if image_files and not engine_error:
        try:
            import pytesseract
            from PIL import Image
        except ImportError:
            engine_error = "ocr_dependencies_missing"
        else:
            for image_path in image_files:
                relative = image_path.relative_to(media_dir).as_posix()
                try:
                    with Image.open(image_path) as image:
                        text = pytesseract.image_to_string(image, lang="chi_sim+eng").strip()
                except Exception as exc:
                    status = "ocr_unavailable" if type(exc).__name__ == "TesseractNotFoundError" else "ocr_failed"
                    previous_text = previous_by_file.get(relative, {}).get("text", "")
                    image_results[relative] = {"file": relative, "text": previous_text, "status": status}
                    continue

                entry = {"file": relative, "text": text, "status": "ocr_pending_delete" if text else "no_text_pending_delete"}
                image_results[relative] = entry
                manifest["posts"][post_key] = list(image_results.values())
                try:
                    _save_manifest(manifest_path, manifest)
                except OSError:
                    entry["status"] = "ocr_manifest_write_failed"
                    continue

                try:
                    image_path.unlink()
                except OSError:
                    entry["status"] = "ocr_complete_delete_failed" if text else "no_text_delete_failed"
                else:
                    deleted += 1
                    entry["status"] = "deleted_after_ocr" if text else "no_text_deleted"
                    manifest["posts"][post_key] = list(image_results.values())
                    try:
                        _save_manifest(manifest_path, manifest)
                    except OSError:
                        # Text was already persisted before deletion; keep the pending state for audit.
                        entry["status"] = "ocr_manifest_update_failed"

    if engine_error:
        for image_path in image_files:
            relative = image_path.relative_to(media_dir).as_posix()
            previous_text = previous_by_file.get(relative, {}).get("text", "")
            image_results[relative] = {"file": relative, "text": previous_text, "status": engine_error}

    if image_files and not engine_error and image_results:
        manifest["posts"][post_key] = list(image_results.values())
        try:
            _save_manifest(manifest_path, manifest)
        except OSError:
            pass

    if not image_files:
        image_status = "unavailable" if manifest_error else ("none" if not previous else "restored_from_manifest")
    elif engine_error:
        image_status = "unavailable"
    else:
        statuses = {item.get("status") for item in image_results.values() if item.get("file") in {
            path.relative_to(media_dir).as_posix() for path in image_files
        }}
        image_status = "completed" if statuses and statuses <= {"deleted_after_ocr", "no_text_deleted"} else "partial"

    video_analysis: dict[str, Any]
    video_output_dir = _video_output_dir(data_root, post_key)
    try:
        from .video_analysis import process_downloaded_videos
        video_analysis = process_downloaded_videos(video_files, video_output_dir)
    except Exception as exc:
        video_analysis = {
            "status": "unavailable" if video_files else "none",
            "processed_count": 0,
            "deleted_count": 0,
            "videos": [{
                "source_file_name": path.name,
                "analysis_status": "failed",
                "source_delete_status": "not_deleted",
                "source_deleted": False,
                "reason": str(exc),
            } for path in video_files],
        }
    if not video_files and video_url and video_analysis["status"] == "none":
        session = web_video_session
        owns_session = session is None
        try:
            if owns_session:
                from .web_video_analysis import WebVideoSession
                session = WebVideoSession(profile_directory)
            webpage_manifest = session.analyze(video_url, video_output_dir)
            relative_directory = str((video_output_dir / "web-page-capture").relative_to(data_root.parent))
            video_analysis = {
                "status": "completed",
                "mode": "web_page",
                "processed_count": 1,
                "deleted_count": 0,
                "videos": [{
                    "source_file_name": post_key.rsplit(":", 1)[-1],
                    "analysis_status": "completed",
                    "source_delete_status": "not_applicable",
                    "source_deleted": False,
                    "frame_count": webpage_manifest["frame_count"],
                    "frames_with_text": webpage_manifest["frame_ocr"]["frames_with_text"],
                    "analysis_directory": relative_directory,
                    "capture_method": "rendered_webpage_screenshot",
                    "source_video_saved": False,
                }],
            }
        except Exception as exc:
            safe_reason = str(exc) if type(exc) in {RuntimeError, ValueError} else f"browser_error:{type(exc).__name__}"
            video_analysis = {
                "status": "unavailable",
                "mode": "web_page",
                "processed_count": 0,
                "deleted_count": 0,
                "videos": [{
                    "source_file_name": post_key.rsplit(":", 1)[-1],
                    "analysis_status": "failed",
                    "source_delete_status": "not_applicable",
                    "source_deleted": False,
                    "capture_method": "rendered_webpage_screenshot",
                    "reason": safe_reason,
                }],
            }
        finally:
            if owns_session and session is not None:
                session.close()

    remaining_videos = [path for path in video_files if path.is_file()]
    try:
        video_paths = [str(path.relative_to(data_root.parent)) for path in remaining_videos]
    except ValueError:
        video_paths = [str(path) for path in remaining_videos]
    if remaining_videos:
        source_retained_after_analysis = any(
            item.get("analysis_status") == "completed" and item.get("source_delete_status") == "failed"
            for item in video_analysis.get("videos", [])
        )
        video_status = "analysis_completed_source_retained" if source_retained_after_analysis else "available"
    elif video_analysis.get("mode") == "web_page" and video_analysis["status"] == "completed":
        video_status = "processed_in_browser"
    elif video_analysis.get("mode") == "web_page":
        video_status = "web_fallback_failed"
    elif video_analysis["status"] == "completed":
        video_status = "processed_and_deleted"
    elif video_analysis["processed_count"]:
        video_status = "analysis_completed_deletion_unconfirmed"
    else:
        video_status = "requested_no_video_file" if download_requested else request_status
    return {
        "status": video_status,
        "download_requested": download_requested,
        "files": video_paths,
        "video_analysis": video_analysis,
        "image_count": len(image_files),
        "images_deleted": deleted,
        "image_ocr_status": image_status,
        "image_ocr": list(image_results.values()),
    }
