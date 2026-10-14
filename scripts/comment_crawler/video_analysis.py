"""本地视频证据包：场景抽帧、音轨转写，并生成可供多模态分析的材料。"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


VIDEO_SUFFIXES = {".mp4", ".m4v", ".mov", ".mkv", ".webm", ".flv", ".avi"}
_PTS_RE = re.compile(r"pts_time:([0-9.]+)")


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=False)


def _require_tools() -> tuple[str, str]:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("缺少 ffmpeg 或 ffprobe；请先安装 FFmpeg 并确认两者都在 PATH 中")
    return ffmpeg, ffprobe


def _probe(path: Path, ffprobe: str) -> dict[str, Any]:
    result = _run([
        ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path),
    ])
    if result.returncode:
        raise RuntimeError(f"ffprobe 无法读取媒体文件：{path.name}")
    payload = json.loads(result.stdout)
    streams = payload.get("streams") or []
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    if video is None:
        raise ValueError(f"文件没有视频轨：{path.name}")
    fmt = payload.get("format") or {}
    try:
        duration = float(fmt.get("duration") or video.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    return {
        "duration_seconds": duration,
        "width": video.get("width"),
        "height": video.get("height"),
        "video_codec": video.get("codec_name", ""),
        "audio_present": audio is not None,
        "audio_codec": audio.get("codec_name", "") if audio else "",
    }


def _slug(path: Path) -> str:
    stem = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "-", path.stem).strip("-")[:64] or "video"
    digest = _sha256(path)[:10]
    return f"{stem}-{digest}"


def _extract_frames(path: Path, out_dir: Path, ffmpeg: str, threshold: float, interval: float) -> list[dict[str, Any]]:
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True)
    # Select scene changes plus a periodic floor so static scenes are represented.
    expression = (
        f"select='isnan(prev_selected_t)+gt(scene\\,{threshold:.4f})"
        f"+gte(t-prev_selected_t\\,{interval:.3f})',showinfo"
    )
    result = _run([
        ffmpeg, "-hide_banner", "-nostats", "-loglevel", "info", "-i", str(path),
        "-map", "0:v:0", "-vf", expression, "-fps_mode", "vfr", "-q:v", "2",
        str(frames_dir / "frame_%06d.jpg"),
    ])
    if result.returncode:
        raise RuntimeError(f"FFmpeg 抽帧失败：{path.name}")
    times = [float(value) for value in _PTS_RE.findall(result.stderr)]
    images = sorted(frames_dir.glob("frame_*.jpg"))
    return [
        {"file": f"frames/{image.name}", "timestamp_seconds": times[index] if index < len(times) else None}
        for index, image in enumerate(images)
    ]


def _write_contact_sheets(out_dir: Path, frames: list[dict[str, Any]]) -> list[str]:
    if not frames:
        return []
    try:
        from PIL import Image, ImageDraw, ImageOps
    except ImportError as exc:
        raise RuntimeError("缺少 Pillow；请安装本包的 video extra：python -m pip install '.[video]'") from exc
    sheet_dir = out_dir / "contact-sheets"
    sheet_dir.mkdir()
    sheet_files: list[str] = []
    cell_w, cell_h, label_h = 640, 380, 28
    for sheet_index, start in enumerate(range(0, len(frames), 9), start=1):
        canvas = Image.new("RGB", (cell_w * 3, (cell_h + label_h) * 3), "#151515")
        draw = ImageDraw.Draw(canvas)
        for slot, frame in enumerate(frames[start:start + 9]):
            image = Image.open(out_dir / frame["file"]).convert("RGB")
            image = ImageOps.contain(image, (cell_w, cell_h))
            x = (slot % 3) * cell_w + (cell_w - image.width) // 2
            y = (slot // 3) * (cell_h + label_h) + (cell_h - image.height) // 2
            canvas.paste(image, (x, y))
            stamp = frame.get("timestamp_seconds")
            label = f"{stamp:.2f}s" if isinstance(stamp, (int, float)) else "time unavailable"
            draw.text(((slot % 3) * cell_w + 8, (slot // 3) * (cell_h + label_h) + cell_h + 5), label, fill="white")
        name = f"sheet-{sheet_index:03d}.jpg"
        canvas.save(sheet_dir / name, quality=88, optimize=True)
        sheet_files.append(f"contact-sheets/{name}")
    return sheet_files


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _ocr_frames(out_dir: Path, frames: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        import pytesseract
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("缺少 pytesseract 或 Pillow；请安装本包 OCR 依赖：python -m pip install '.[ocr]'") from exc

    rows = []
    for frame in frames:
        try:
            with Image.open(out_dir / frame["file"]) as image:
                text = pytesseract.image_to_string(image, lang="chi_sim+eng").strip()
        except Exception as exc:
            if type(exc).__name__ == "TesseractNotFoundError":
                raise RuntimeError("未找到本机 Tesseract；安装 Tesseract 并加入 PATH 后可重试") from exc
            if "chi_sim" in str(exc) or "eng" in str(exc):
                raise RuntimeError("Tesseract 缺少 chi_sim 或 eng 语言数据") from exc
            raise RuntimeError(f"关键帧 OCR 失败：{frame['file']}") from exc
        rows.append({
            "file": frame["file"],
            "timestamp_seconds": frame.get("timestamp_seconds"),
            "text": text,
            "status": "text_found" if text else "no_text",
        })

    _write_json(out_dir / "frames_ocr.json", {"status": "completed", "frames": rows})
    (out_dir / "frames_ocr.txt").write_text(
        "\n\n".join(
            f"[{row['timestamp_seconds']:.2f}s] {row['text']}"
            if isinstance(row["timestamp_seconds"], (int, float))
            else row["text"]
            for row in rows if row["text"]
        ) + "\n",
        encoding="utf-8",
    )
    return {
        "status": "completed",
        "frame_count": len(rows),
        "frames_with_text": sum(bool(row["text"]) for row in rows),
        "files": ["frames_ocr.json", "frames_ocr.txt"],
    }


def _extract_audio(path: Path, out_dir: Path, ffmpeg: str) -> Path:
    audio_path = out_dir / "audio-16khz-mono.wav"
    result = _run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(path),
        "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(audio_path),
    ])
    if result.returncode:
        raise RuntimeError("FFmpeg 无法提取音轨")
    return audio_path


def _transcribe(audio_path: Path, out_dir: Path, model_name: str, language: str | None) -> dict[str, Any]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("缺少 faster-whisper；请安装本包的 video extra：python -m pip install '.[video]'") from exc
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, info = model.transcribe(str(audio_path), language=language, vad_filter=True)
    rows = []
    for segment in segments:
        rows.append({
            "start": round(float(segment.start), 3),
            "end": round(float(segment.end), 3),
            "text": str(segment.text).strip(),
        })
    (out_dir / "transcript.json").write_text(
        json.dumps({"language": info.language, "segments": rows}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (out_dir / "transcript.txt").write_text(
        "\n".join(f"[{row['start']:.2f}-{row['end']:.2f}] {row['text']}" for row in rows) + "\n",
        encoding="utf-8",
    )
    with (out_dir / "transcript.srt").open("w", encoding="utf-8") as stream:
        for index, row in enumerate(rows, start=1):
            def stamp(seconds: float) -> str:
                millis = round(seconds * 1000)
                hours, millis = divmod(millis, 3_600_000)
                minutes, millis = divmod(millis, 60_000)
                seconds, millis = divmod(millis, 1000)
                return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"
            stream.write(f"{index}\n{stamp(row['start'])} --> {stamp(row['end'])}\n{row['text']}\n\n")
    return {"status": "completed", "language": info.language, "segments": len(rows), "model": model_name}


def _analysis_brief(
    video_name: str, media: dict[str, Any], frames: list[dict[str, Any]],
    sheets: list[str], transcript_status: str, frame_ocr_status: str,
) -> str:
    lines = [
        f"# 多模态分析材料：{video_name}",
        "",
        "请只依据下列本地媒体证据撰写分析。把视频中直接出现的事实、发布者陈述和分析推断分开；每项结论附时间戳或字幕片段。",
        "",
        "## 媒体信息",
        f"- 时长（秒）：{media['duration_seconds']:.3f}",
        f"- 画面尺寸：{media['width']} × {media['height']}",
        f"- 音轨：{'有' if media['audio_present'] else '无'}",
        f"- 转写状态：{transcript_status}",
        f"- 画面文字 OCR 状态：{frame_ocr_status}",
        "",
        "## 关键帧",
        *[f"- {sheet}" for sheet in sheets],
        f"- 共抽取 {len(frames)} 帧；每帧时间点见 `frames.csv`。",
        "",
        "## 推荐分析项",
        "- 视频主题、展示对象和内容结构。",
        "- 明确演示的功能、操作步骤、环境与结果；没有展示的功能不推断为已实现。",
        "- 体验评价、营销话术与事实证据的区分。",
        "- 用户场景、需求和购买障碍线索；将发布者推测与观众评论分开。",
        "- 证据不足项、需要人工复核项和下一步验证建议。",
        "",
        "所有帧与转写都来自本机处理；本程序不会调用云端多模态 API。",
    ]
    if frame_ocr_status != "not_requested":
        lines.extend([
            "- 画面 OCR 结果见 `frames_ocr.json` 和 `frames_ocr.txt`；文本只覆盖已抽取关键帧。",
        ])
    return "\n".join(lines) + "\n"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_video_analysis(
    inputs: list[str], output: str, *, scene_threshold: float = 0.35,
    interval_seconds: float = 8.0, whisper_model: str = "base",
    language: str | None = None, transcribe: bool = True,
    ocr_frames: bool = False, delete_source_after_success: bool = False,
) -> dict[str, Any]:
    if not 0 <= scene_threshold <= 1 or interval_seconds <= 0:
        raise ValueError("scene_threshold 需在 0–1 之间，interval_seconds 必须大于 0")
    files: list[Path] = []
    for value in inputs:
        path = Path(value).expanduser().resolve()
        if path.is_file() and path.suffix.lower() in VIDEO_SUFFIXES:
            files.append(path)
        elif path.is_dir():
            files.extend(candidate for candidate in path.rglob("*")
                         if candidate.is_file() and candidate.suffix.lower() in VIDEO_SUFFIXES)
        else:
            raise ValueError(f"输入不是支持的视频文件或目录：{value}")
    files = sorted(set(files))
    if not files:
        raise ValueError("输入目录中没有支持的视频文件")
    ffmpeg, ffprobe = _require_tools()
    output_dir = Path(output).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for path in files:
        asset_dir = output_dir / _slug(path)
        if asset_dir.exists() and any(asset_dir.iterdir()):
            raise ValueError(f"分析结果目录已有内容，为避免混合数据已停止：{asset_dir.name}")
        asset_dir.mkdir(parents=True, exist_ok=True)
        try:
            source_hash = _sha256(path)
            media = _probe(path, ffprobe)
            frames = _extract_frames(path, asset_dir, ffmpeg, scene_threshold, interval_seconds)
            if not frames:
                raise RuntimeError(f"FFmpeg 没有抽取到关键帧：{path.name}")
            sheets = _write_contact_sheets(asset_dir, frames)
            frame_ocr = _ocr_frames(asset_dir, frames) if ocr_frames else {"status": "not_requested"}
            transcript = {"status": "not_requested"}
            if transcribe and media["audio_present"]:
                audio = _extract_audio(path, asset_dir, ffmpeg)
                try:
                    transcript = _transcribe(audio, asset_dir, whisper_model, language)
                except RuntimeError as exc:
                    transcript = {"status": "unavailable", "reason": str(exc)}
            elif transcribe:
                transcript = {"status": "no_audio_track"}
            with (asset_dir / "frames.csv").open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=("file", "timestamp_seconds"))
                writer.writeheader()
                writer.writerows(frames)
            (asset_dir / "analysis-brief.md").write_text(
                _analysis_brief(path.name, media, frames, sheets, transcript["status"], frame_ocr["status"]),
                encoding="utf-8",
            )
            manifest = {
                "source_file_name": path.name,
                "source_sha256": source_hash,
                "media": media,
                "frame_count": len(frames),
                "contact_sheets": sheets,
                "frame_ocr": frame_ocr,
                "transcription": transcript,
                "source_delete_status": "pending" if delete_source_after_success else "not_requested",
            }
            _write_json(asset_dir / "manifest.json", manifest)
        except BaseException:
            # If processing failed, discard only this attempt's derived output and keep the source video.
            shutil.rmtree(asset_dir, ignore_errors=True)
            raise
        if delete_source_after_success:
            try:
                path.unlink()
            except OSError:
                manifest["source_delete_status"] = "failed"
            else:
                manifest["source_delete_status"] = "deleted"
            try:
                _write_json(asset_dir / "manifest.json", manifest)
            except OSError:
                # The OCR output and pre-delete manifest are already durable; preserve them if the final status update fails.
                pass
        results.append({"directory": asset_dir.name, **manifest})
    return {"status": "completed_local_processing", "video_count": len(results), "videos": results}


def process_downloaded_videos(video_files: list[Path], output_dir: Path) -> dict[str, Any]:
    """OCR sampled frames from downloaded media; delete each source only after outputs are saved."""
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    if not video_files:
        for manifest_path in sorted(output_dir.glob("*/manifest.json")):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            frame_ocr = manifest.get("frame_ocr") if isinstance(manifest, dict) else None
            frames_dir = manifest_path.parent / "frames"
            try:
                frame_count = int(manifest.get("frame_count", 0)) if isinstance(manifest, dict) else 0
            except (TypeError, ValueError):
                frame_count = 0
            if (not isinstance(frame_ocr, dict) or frame_ocr.get("status") != "completed"
                    or manifest.get("source_delete_status") not in {"deleted", "failed", "pending"}
                    or frame_count < 1
                    or len(list(frames_dir.glob("frame_*"))) < frame_count
                    or not (manifest_path.parent / "frames_ocr.json").is_file()
                    or not (manifest_path.parent / "frames_ocr.txt").is_file()):
                continue
            results.append({
                "source_file_name": manifest.get("source_file_name", ""),
                "source_sha256": manifest.get("source_sha256", ""),
                "analysis_status": "completed",
                "source_delete_status": manifest["source_delete_status"],
                "source_deleted": manifest["source_delete_status"] == "deleted",
                "frame_count": manifest.get("frame_count", 0),
                "frames_with_text": frame_ocr.get("frames_with_text", 0),
                "analysis_directory": str(manifest_path.parent.relative_to(output_dir.parent.parent.parent)),
            })
    for path in video_files:
        try:
            existing_dir = output_dir / _slug(path)
            existing_manifest_path = existing_dir / "manifest.json"
            if existing_manifest_path.is_file():
                try:
                    existing = json.loads(existing_manifest_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    existing = {}
                frame_ocr = existing.get("frame_ocr") if isinstance(existing, dict) else None
                if (isinstance(frame_ocr, dict) and frame_ocr.get("status") == "completed"
                        and existing.get("source_sha256") == _sha256(path)
                        and int(existing.get("frame_count", 0)) > 0
                        and len(list((existing_dir / "frames").glob("frame_*"))) >= int(existing.get("frame_count", 0))
                        and (existing_dir / "frames_ocr.json").is_file()
                        and (existing_dir / "frames_ocr.txt").is_file()):
                    try:
                        path.unlink()
                    except OSError:
                        existing["source_delete_status"] = "failed"
                    else:
                        existing["source_delete_status"] = "deleted"
                    try:
                        _write_json(existing_manifest_path, existing)
                    except OSError:
                        pass
                    results.append({
                        "source_file_name": existing.get("source_file_name", path.name),
                        "source_sha256": existing.get("source_sha256", ""),
                        "analysis_status": "completed",
                        "source_delete_status": existing["source_delete_status"],
                        "source_deleted": existing["source_delete_status"] == "deleted",
                        "frame_count": existing.get("frame_count", 0),
                        "frames_with_text": frame_ocr.get("frames_with_text", 0),
                        "analysis_directory": str(existing_dir.relative_to(output_dir.parent.parent.parent)),
                    })
                    continue
            result = run_video_analysis(
                [str(path)], str(output_dir), transcribe=False, ocr_frames=True,
                delete_source_after_success=True,
            )
            video = result["videos"][0]
            results.append({
                "source_file_name": video["source_file_name"],
                "source_sha256": video["source_sha256"],
                "analysis_status": "completed",
                "source_delete_status": video["source_delete_status"],
                "source_deleted": video["source_delete_status"] == "deleted",
                "frame_count": video["frame_count"],
                "frames_with_text": video["frame_ocr"]["frames_with_text"],
                "analysis_directory": str((output_dir / video["directory"]).relative_to(output_dir.parent.parent.parent)),
            })
        except Exception as exc:
            results.append({
                "source_file_name": path.name,
                "analysis_status": "failed",
                "source_delete_status": "not_deleted",
                "source_deleted": False,
                "reason": str(exc),
            })

    if not results:
        status = "none"
    elif all(item["analysis_status"] == "completed" and item["source_deleted"] for item in results):
        status = "completed"
    elif all(item["analysis_status"] == "failed" for item in results):
        status = "unavailable"
    else:
        status = "partial"
    return {
        "status": status,
        "processed_count": sum(item["analysis_status"] == "completed" for item in results),
        "deleted_count": sum(item["source_deleted"] for item in results),
        "videos": results,
    }
