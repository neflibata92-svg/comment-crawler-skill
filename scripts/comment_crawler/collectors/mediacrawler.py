"""适配外部 MediaCrawler checkout；不在本仓库复制其源码。"""
from __future__ import annotations

import ast
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any, Callable, Iterator

from ..core.schema import ReviewRecord, clean_text, hash_author, stable_hash
from ..core.utils import CollectionResult
from ..media_ocr import process_media_assets


PLATFORMS = {
    "douyin": {
        "code": "dy", "post_id": "aweme_id", "post_url": "aweme_url",
        "comment_parent": "aweme_id", "post_time": ("create_time",),
        "post_title": ("title",), "post_body": ("desc",),
        "comment_time": ("create_time",), "comment_text": ("content",),
        "post_likes": ("liked_count",), "post_comments": ("comment_count",),
        "comment_likes": ("like_count",), "fallback_url": "https://www.douyin.com/video/{id}",
    },
    "bilibili": {
        "code": "bili", "post_id": "video_id", "post_url": "video_url",
        "comment_parent": "video_id", "post_time": ("create_time",),
        "post_title": ("title",), "post_body": ("desc",),
        "comment_time": ("create_time",), "comment_text": ("content",),
        "post_likes": ("liked_count",), "post_comments": ("video_comment",),
        "comment_likes": ("like_count",), "fallback_url": "https://www.bilibili.com/video/{id}",
    },
    "weibo": {
        "code": "wb", "post_id": "note_id", "post_url": "note_url",
        "comment_parent": "note_id", "post_time": ("create_date_time", "create_time"),
        "post_title": (), "post_body": ("content",),
        "comment_time": ("create_date_time", "create_time"), "comment_text": ("content",),
        "post_likes": ("liked_count",), "post_comments": ("comments_count",),
        "comment_likes": ("comment_like_count",), "fallback_url": "",
    },
    "zhihu": {
        "code": "zhihu", "post_id": "content_id", "post_url": "content_url",
        "comment_parent": "content_id", "post_time": ("created_time",),
        "post_title": ("title",), "post_body": ("content_text", "desc"),
        "comment_time": ("publish_time",), "comment_text": ("content",),
        "post_likes": ("voteup_count",), "post_comments": ("comment_count",),
        "comment_likes": ("like_count",), "fallback_url": "",
    },
    "tieba": {
        "code": "tieba", "post_id": "note_id", "post_url": "note_url",
        "comment_parent": "note_id", "post_time": ("publish_time",),
        "post_title": ("title",), "post_body": ("desc",),
        "comment_time": ("publish_time",), "comment_text": ("content",),
        "post_likes": (), "post_comments": ("total_replay_num",),
        "comment_likes": (), "fallback_url": "https://tieba.baidu.com/p/{id}",
    },
}

_CORE_FILES = tuple(
    f"media_platform/{name}/core.py"
    for name in ("douyin", "bilibili", "weibo", "zhihu", "tieba", "xhs")
)

# MediaCrawler's CLI accepts only an integer count. This large sentinel removes
# its ordinary count caps in practice; the local importer has no count cap.
UNBOUNDED_UPSTREAM_COUNT = 2**63 - 1
MEDIA_DOWNLOAD_ID_BATCH_SIZE = 100
MEDIA_DOWNLOAD_PLATFORMS = {"douyin", "bilibili", "weibo", "xiaohongshu"}


def _media_download_support(home: Path, source: str) -> tuple[bool, str]:
    if source not in MEDIA_DOWNLOAD_PLATFORMS:
        return False, "not_supported_by_adapter"
    args_path = home / "cmd_arg" / "arg.py"
    if not args_path.is_file() or "--get_media" not in args_path.read_text(encoding="utf-8"):
        return False, "upstream_option_unavailable"
    return True, "requested"


def download_media_for_posts(
    source: str,
    home: str | Path,
    post_ids: list[str],
    output: str | Path,
    delay_seconds: float,
    *,
    profile_directory: str | Path | None = None,
) -> dict[str, Any]:
    """Use MediaCrawler only for media on posts already collected by this repository."""
    root = Path(home).expanduser().resolve()
    _assert_prepared(root)
    include_media, status = _media_download_support(root, source)
    if not post_ids:
        return {"status": "no_posts", "download_requested": False, "return_code": None}
    if not include_media:
        return {"status": status, "download_requested": False, "return_code": None}

    code = "xhs" if source == "xiaohongshu" else PLATFORMS[source]["code"]
    data_root = Path(output).expanduser().resolve() / ".mediacrawler"
    data_root.mkdir(parents=True, exist_ok=True)
    unique_post_ids = list(dict.fromkeys(str(post_id) for post_id in post_ids if str(post_id)))
    if not unique_post_ids:
        return {"status": "no_posts", "download_requested": False, "return_code": None}
    failed_status = ""
    failure_code = None
    for offset in range(0, len(unique_post_ids), MEDIA_DOWNLOAD_ID_BATCH_SIZE):
        batch = unique_post_ids[offset:offset + MEDIA_DOWNLOAD_ID_BATCH_SIZE]
        args = [
            "--platform", code, "--type", "detail", "--keywords", "",
            "--get_comment", "false", "--get_sub_comment", "false",
            "--save_data_option", "jsonl", "--crawler_max_notes_count", str(len(batch)),
            "--max_comments_count_singlenotes", str(UNBOUNDED_UPSTREAM_COUNT),
            "--save_data_path", str(data_root), "--headless", "false", "--enable_ip_proxy", "false",
            "--get_media", "true", "--specified_id", ",".join(batch),
        ]
        try:
            completed = subprocess.run(
                _build_command(root, args, delay_seconds, profile_directory=profile_directory),
                cwd=root,
                check=False,
            )
        except OSError as exc:
            failed_status = failed_status or f"launch_failed:{type(exc).__name__}"
            continue
        if completed.returncode != 0:
            failed_status = failed_status or "upstream_failed"
            failure_code = failure_code if failure_code is not None else completed.returncode
    return {
        "status": failed_status or "completed",
        "download_requested": True,
        "return_code": failure_code if failed_status else 0,
    }


def _replace_bool_assignment(text: str, name: str) -> str:
    pattern = re.compile(rf"^(\s*{re.escape(name)}\s*=\s*)True(\s*(?:#.*)?)$", re.MULTILINE)
    updated, count = pattern.subn(r"\1False\2", text, count=1)
    if count:
        return updated
    if re.search(rf"^\s*{re.escape(name)}\s*=\s*False\b", text, re.MULTILINE):
        return text
    raise ValueError(f"无法识别上游配置项 {name}；请核对 MediaCrawler 版本")


def _remove_anti_detection(text: str, path: Path) -> tuple[str, bool]:
    lines = text.splitlines(keepends=True)
    remove: set[int] = set()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if "stealth.min.js" in line:
            if stripped.startswith("#") or "add_init_script" in line:
                remove.add(index)
            else:
                raise ValueError(f"{path} 含有无法安全自动处理的 stealth.min.js 用法")
        if "add_stealth_script(" in line:
            if stripped.startswith("#") or "await " in line:
                remove.add(index)
            else:
                raise ValueError(f"{path} 含有无法安全自动处理的 add_stealth_script 用法")

    tree = ast.parse(text, filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_inject_anti_detection_scripts":
            remove.update(range(node.lineno - 1, node.end_lineno))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "_inject_anti_detection_scripts":
            index = node.lineno - 1
            if index >= len(lines) or not re.fullmatch(r"\s*await self\._inject_anti_detection_scripts\(\)\s*(?:#.*)?(?:\r?\n)?", lines[index]):
                raise ValueError(f"{path} 含有无法安全自动处理的内联反检测调用")
            remove.add(index)
            if index > 0 and "anti-detection scripts" in lines[index - 1]:
                remove.add(index - 1)

    updated = "".join(line for index, line in enumerate(lines) if index not in remove)
    updated_tree = ast.parse(updated, filename=str(path))
    has_inline_helper = any(
        (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_inject_anti_detection_scripts")
        or (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "_inject_anti_detection_scripts")
        for node in ast.walk(updated_tree)
    )
    if any(marker in updated for marker in ("stealth.min.js", "add_stealth_script(", "add_init_script(", "navigator.webdriver")) or has_inline_helper:
        raise ValueError(f"{path} 仍包含反检测脚本调用；停止，不修改该文件")
    return updated, bool(remove)


def _patch_zhihu_comment_limit(core_text: str, client_text: str, core_path: Path, client_path: Path) -> tuple[str, str]:
    call_before = """callback=zhihu_store.batch_update_zhihu_note_comments,
            )"""
    call_after = """callback=zhihu_store.batch_update_zhihu_note_comments,
                max_count=config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES,
            )"""
    core_text, core_count = re.subn(re.escape(call_before), lambda _: call_after, core_text, count=1)
    if core_count != 1 and call_after not in core_text:
        raise ValueError(f"无法安全设置知乎评论分页参数：{core_path}")

    tree = ast.parse(client_text, filename=str(client_path))
    methods = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "get_note_all_comments"]
    if len(methods) != 1:
        raise ValueError(f"无法识别知乎评论分页函数：{client_path}")
    method = methods[0]
    lines = client_text.splitlines(keepends=True)
    method_text = "".join(lines[method.lineno - 1:method.end_lineno])
    if "max_count - len(result)" not in method_text:
        replacements = (
            ("callback: Optional[Callable] = None,", "callback: Optional[Callable] = None,\n        max_count: Optional[int] = None,"),
            ("while not is_end:", "while not is_end and (max_count is None or len(result) < max_count):"),
            ("limit: int = 10", "limit = min(10, max_count - len(result)) if max_count is not None else 10"),
            (
                'comments = self._extractor.extract_comments(content, root_comment_res.get("data"))',
                'comments = self._extractor.extract_comments(content, root_comment_res.get("data"))\n\n            if max_count is not None:\n                comments = comments[: max_count - len(result)]',
            ),
        )
        for before, after in replacements:
            if method_text.count(before) != 1:
                raise ValueError(f"无法安全设置知乎评论分页参数：{client_path}")
            method_text = method_text.replace(before, after, 1)
        lines[method.lineno - 1:method.end_lineno] = [method_text]
        client_text = "".join(lines)
        ast.parse(client_text, filename=str(client_path))

    if "max_count=config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES" not in core_text or "max_count - len(result)" not in client_text:
        raise ValueError("知乎评论分页补丁未通过静态检查")
    return core_text, client_text


def prepare_mediacrawler(home: str | Path) -> list[str]:
    """将外置 checkout 切到普通浏览器模式，并移除已识别的反检测注入。"""
    root = Path(home).expanduser().resolve()
    config_path = root / "config" / "base_config.py"
    if not (root / "main.py").is_file() or not config_path.is_file():
        raise ValueError("路径不是可识别的 MediaCrawler checkout（缺少 main.py 或 config/base_config.py）")

    planned: dict[Path, str] = {}
    config_text = config_path.read_text(encoding="utf-8")
    config_text = _replace_bool_assignment(config_text, "ENABLE_CDP_MODE")
    config_text = _replace_bool_assignment(config_text, "CDP_CONNECT_EXISTING")
    planned[config_path] = config_text

    for relative in _CORE_FILES:
        path = root / relative
        if not path.is_file():
            raise ValueError(f"上游缺少 {relative}；请核对 MediaCrawler 版本")
        updated, _ = _remove_anti_detection(path.read_text(encoding="utf-8"), path)
        planned[path] = updated

    zhihu_core_path = root / "media_platform" / "zhihu" / "core.py"
    zhihu_client_path = root / "media_platform" / "zhihu" / "client.py"
    if not zhihu_client_path.is_file():
        raise ValueError("上游缺少 media_platform/zhihu/client.py；请核对 MediaCrawler 版本")
    zhihu_core, zhihu_client = _patch_zhihu_comment_limit(
        planned[zhihu_core_path],
        zhihu_client_path.read_text(encoding="utf-8"),
        zhihu_core_path,
        zhihu_client_path,
    )
    planned[zhihu_core_path] = zhihu_core
    planned[zhihu_client_path] = zhihu_client

    changed: list[str] = []
    for path, updated in planned.items():
        original = path.read_text(encoding="utf-8")
        if original == updated:
            continue
        backup = path.with_name(path.name + ".comment-crawler.bak")
        if not backup.exists():
            shutil.copy2(path, backup)
        temporary = path.with_name(path.name + ".comment-crawler.tmp")
        temporary.write_text(updated, encoding="utf-8")
        temporary.replace(path)
        changed.append(str(path.relative_to(root)))
    return changed


def _assert_prepared(root: Path) -> None:
    config_path = root / "config" / "base_config.py"
    text = config_path.read_text(encoding="utf-8")
    for name in ("ENABLE_CDP_MODE", "CDP_CONNECT_EXISTING"):
        if not re.search(rf"^\s*{name}\s*=\s*False\b", text, re.MULTILINE):
            raise ValueError("MediaCrawler 尚未准备为普通浏览器模式；请先运行 prepare-mediacrawler")
    for relative in _CORE_FILES:
        path = root / relative
        if not path.is_file():
            raise ValueError(f"MediaCrawler 缺少 {relative}；请核对上游版本")
        text = path.read_text(encoding="utf-8")
        if any(marker in text for marker in ("stealth.min.js", "add_stealth_script(", "add_init_script(", "navigator.webdriver")):
            raise ValueError("MediaCrawler 仍包含反检测脚本；请先运行 prepare-mediacrawler")
        tree = ast.parse(text, filename=str(path))
        if any(
            (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_inject_anti_detection_scripts")
            or (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "_inject_anti_detection_scripts")
            for node in ast.walk(tree)
        ):
            raise ValueError("MediaCrawler 仍包含内联反检测方法；请先运行 prepare-mediacrawler")

    zhihu_core = (root / "media_platform" / "zhihu" / "core.py").read_text(encoding="utf-8")
    zhihu_client = (root / "media_platform" / "zhihu" / "client.py").read_text(encoding="utf-8")
    if "max_count=config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES" not in zhihu_core or "max_count - len(result)" not in zhihu_client:
        raise ValueError("知乎评论分页尚未准备；请先运行 prepare-mediacrawler")


def _iter_jsonl(path: Path, result: CollectionResult, *, report_invalid: bool = True) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                if report_invalid:
                    result.warnings.append(f"上游 JSONL 有无法读取的行：{path.name}:{line_number}")
                continue
            if isinstance(value, dict):
                yield value
            else:
                if report_invalid:
                    result.warnings.append(f"上游 JSONL 有非对象记录：{path.name}:{line_number}")


def _first(row: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return value
    return ""


def _search_text(value: Any) -> str:
    return re.sub(r"\s+", " ", clean_text(value)).strip().casefold()


def _matches_search_queries(row: dict[str, Any], spec: dict[str, Any], queries: list[str]) -> bool:
    if not queries:
        return True
    fields = tuple(_search_text(_first(row, spec[key])) for key in ("post_title", "post_body"))
    return any(
        normalized_query and any(normalized_query in field for field in fields)
        for normalized_query in (_search_text(query) for query in queries)
    )


def _count(value: Any) -> int | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        if isinstance(value, str):
            text = value.strip().replace(",", "")
            multiplier = 1
            if text.endswith("万"):
                multiplier, text = 10_000, text[:-1]
            elif text.endswith("亿"):
                multiplier, text = 100_000_000, text[:-1]
            return int(float(text) * multiplier)
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _post_url(source: str, spec: dict[str, Any], row: dict[str, Any], post_id: str) -> str:
    url = clean_text(row.get(spec["post_url"]))
    if url:
        return url
    fallback = spec["fallback_url"]
    if source == "zhihu":
        kind = clean_text(row.get("content_type")).lower()
        question_id = clean_text(row.get("question_id"))
        if kind == "answer" and question_id:
            return f"https://www.zhihu.com/question/{question_id}/answer/{post_id}"
        if kind == "article":
            return f"https://zhuanlan.zhihu.com/p/{post_id}"
        if kind == "question":
            return f"https://www.zhihu.com/question/{post_id}"
    return fallback.format(id=post_id) if fallback else ""


def _post_record(source: str, spec: dict[str, Any], row: dict[str, Any]) -> tuple[ReviewRecord | None, str]:
    raw_id = clean_text(row.get(spec["post_id"]))
    if not raw_id:
        return None, ""
    external_id = f"post:{raw_id}"
    score = _count(_first(row, spec["post_likes"]))
    reply_count = _count(_first(row, spec["post_comments"]))
    engagement = {"likes": score, "comments": reply_count}
    for name in ("share_count", "shared_count", "collected_count", "video_favorite_count", "video_play_count", "voteup_count", "total_replay_num"):
        value = _count(row.get(name))
        if value is not None:
            engagement[name] = value
    metadata = {
        "mediacrawler_platform": spec["code"],
        "platform_content_type": clean_text(row.get("content_type") or row.get("aweme_type") or row.get("video_type")),
        "source_keyword": clean_text(row.get("source_keyword")),
        "engagement": engagement,
    }
    if source == "tieba":
        metadata["tieba_name"] = clean_text(row.get("tieba_name"))
    return ReviewRecord(
        source=source, content_type="post", url=_post_url(source, spec, row, raw_id),
        external_id=external_id, title=clean_text(_first(row, spec["post_title"])),
        body=clean_text(_first(row, spec["post_body"])),
        author_hash=hash_author(source, row.get("creator_hash")),
        published_at=_first(row, spec["post_time"]), score=score, reply_count=reply_count,
        metadata=metadata,
    ).normalize(), raw_id


def _comment_record(source: str, spec: dict[str, Any], row: dict[str, Any], posts: dict[str, tuple[str, str]]) -> ReviewRecord | None:
    comment_id = clean_text(row.get("comment_id"))
    post_id = clean_text(row.get(spec["comment_parent"]))
    if not comment_id:
        comment_id = "synthetic:" + stable_hash(
            f"{source}|{post_id}|{row.get('parent_comment_id')}|{_first(row, spec['comment_time'])}|{_first(row, spec['comment_text'])}",
            32,
        )
        id_strategy = "synthetic_from_post_parent_time_text"
    else:
        id_strategy = "platform_comment_id"
    post_external_id = f"post:{post_id}" if post_id else ""
    post_url, post_title = posts.get(post_id, ("", ""))
    if not post_url:
        post_url = clean_text(row.get(spec["post_url"]))
    if not post_url and post_id:
        post_url = _post_url(source, spec, {spec["post_url"]: ""}, post_id)
    raw_parent = clean_text(row.get("parent_comment_id"))
    parent_id = f"comment:{raw_parent}" if raw_parent and raw_parent not in {"0", "null", "None"} else ""
    likes = _count(_first(row, spec["comment_likes"]))
    replies = _count(row.get("sub_comment_count"))
    metadata = {
        "mediacrawler_platform": spec["code"],
        "post_external_id": post_external_id,
        "platform_comment_id_strategy": id_strategy,
    }
    return ReviewRecord(
        source=source, content_type="comment", url=post_url, external_id=f"comment:{comment_id}",
        title=post_title, body=clean_text(_first(row, spec["comment_text"])), parent_id=parent_id,
        author_hash=hash_author(source, row.get("creator_hash")),
        published_at=_first(row, spec["comment_time"]), score=likes, reply_count=replies,
        metadata=metadata,
    ).normalize()


def _platform_exports(root: Path, platform_code: str, item_type: str) -> list[Path]:
    directory = root / platform_code / "jsonl"
    if not directory.is_dir():
        return []
    return sorted(directory.glob(f"**/*_{item_type}_*.jsonl"))


def _matching_post_ids(data_root: Path, spec: dict[str, Any], queries: list[str]) -> list[str]:
    post_ids: list[str] = []
    seen: set[str] = set()
    scratch_result = CollectionResult(source="mediacrawler")
    for path in _platform_exports(data_root, spec["code"], "contents"):
        for row in _iter_jsonl(path, scratch_result, report_invalid=False):
            post_id = clean_text(row.get(spec["post_id"]))
            if post_id and post_id not in seen and _matches_search_queries(row, spec, queries):
                seen.add(post_id)
                post_ids.append(post_id)
    return post_ids


def _remove_unmatched_media(
    data_root: Path,
    platform_code: str,
    candidate_post_ids: set[str],
    matched_post_ids: set[str],
    result: CollectionResult,
) -> None:
    platform_root = data_root / platform_code
    media_root = platform_root / "media"
    if any(path.is_symlink() for path in (data_root, platform_root, media_root)):
        result.warnings.append("检测到符号链接媒体根目录，跳过未命中媒体清理")
        return
    if not media_root.is_dir():
        return
    resolved_data_root = data_root.resolve()
    resolved_root = media_root.resolve()
    try:
        resolved_root.relative_to(resolved_data_root)
    except ValueError:
        result.warnings.append("媒体目录超出任务目录，跳过未命中媒体清理")
        return
    if resolved_root == resolved_data_root:
        result.warnings.append("媒体目录与任务目录相同，跳过未命中媒体清理")
        return
    for post_id in candidate_post_ids - matched_post_ids:
        if post_id in {".", ".."} or Path(post_id).name != post_id:
            result.warnings.append(f"未清理无效帖子 ID 对应的媒体路径：{post_id}")
            continue
        media_dir = media_root / post_id
        if media_dir.is_symlink():
            try:
                media_dir.unlink()
            except OSError:
                result.warnings.append(f"未能移除未命中帖子媒体链接：{post_id}")
        elif media_dir.is_dir() and media_dir.resolve().parent == resolved_root:
            try:
                shutil.rmtree(media_dir)
            except OSError:
                result.warnings.append(f"未能清理未命中帖子媒体目录：{post_id}")


def _import_exports(
    source: str,
    spec: dict[str, Any],
    data_root: Path,
    emit: Callable[[ReviewRecord], Any],
    result: CollectionResult,
    queries: list[str],
    media_request_status: str,
    web_video_session: Any,
    profile_directory: str | Path | None,
) -> tuple[int, int]:
    content_files = _platform_exports(data_root, spec["code"], "contents")
    comment_files = _platform_exports(data_root, spec["code"], "comments")
    posts: dict[str, tuple[str, str]] = {}
    seen_post_ids: set[str] = set()
    candidate_post_ids: set[str] = set()
    for path in content_files:
        for row in _iter_jsonl(path, result):
            candidate_id = clean_text(row.get(spec["post_id"]))
            if candidate_id:
                candidate_post_ids.add(candidate_id)
            record, raw_id = _post_record(source, spec, row)
            if record is None:
                result.warnings.append(f"上游帖子缺少平台 ID，已跳过：{path.name}")
                continue
            if raw_id in seen_post_ids:
                continue
            if not _matches_search_queries(row, spec, queries):
                continue
            seen_post_ids.add(raw_id)
            media_dir = data_root / spec["code"] / "media" / raw_id
            record.metadata["media_assets"] = process_media_assets(
                media_dir, data_root, f"{spec['code']}:{raw_id}",
                download_requested=media_request_status == "requested",
                request_status=media_request_status,
                video_url=record.url if source in MEDIA_DOWNLOAD_PLATFORMS else "",
                web_video_session=web_video_session,
                profile_directory=profile_directory,
            )
            if record.metadata["media_assets"]["image_ocr_status"] in {"unavailable", "partial"}:
                result.warnings.append(
                    f"帖子 {raw_id} 的图片 OCR 未全部完成；未成功提取的图片已保留，安装本机 OCR 依赖后可重试"
                )
            video_analysis = record.metadata["media_assets"]["video_analysis"]
            if video_analysis["status"] in {"unavailable", "partial"}:
                if video_analysis.get("mode") == "web_page":
                    reason = "没有可用视频文件，网页播放取帧 OCR 未完成；检查浏览器登录、Playwright、播放器和 OCR 依赖"
                else:
                    reason = "视频帧 OCR 未全部完成，源视频已保留；检查 FFmpeg、Tesseract 和 OCR 语言数据后可重试"
                result.warnings.append(f"帖子 {raw_id}：{reason}")
            posts[raw_id] = (record.url, record.title)
            emit(record)

    _remove_unmatched_media(data_root, spec["code"], candidate_post_ids, set(posts), result)

    imported_comments = 0
    seen_comments: dict[str, set[str]] = {}
    accepted_root_ids: dict[str, set[str]] = {}

    def comment_rows(*, report_invalid: bool = True):
        for path in comment_files:
            yield from _iter_jsonl(path, result, report_invalid=report_invalid)

    # Import every top-level comment first so replies are not lost when the
    # upstream JSONL happens to write a reply before its parent row.
    for row in comment_rows():
        post_id = clean_text(row.get(spec["comment_parent"]))
        if post_id not in posts:
            continue
        raw_parent = clean_text(row.get("parent_comment_id"))
        if raw_parent not in {"", "0", "null", "None"}:
            continue
        record = _comment_record(source, spec, row, posts)
        if record is None:
            continue
        record.metadata["comment_level"] = 1
        post_seen = seen_comments.setdefault(post_id, set())
        if record.external_id in post_seen:
            continue
        post_seen.add(record.external_id)
        comment_id = clean_text(row.get("comment_id"))
        if comment_id:
            accepted_root_ids.setdefault(post_id, set()).add(comment_id)
        accepted_root_ids.setdefault(post_id, set()).add(record.external_id.removeprefix("comment:"))
        emit(record)
        imported_comments += 1

    # The shared result model stores the first two comment levels. Deeper
    # descendants are not silently mislabeled as second-level replies.
    orphan_replies = 0
    for row in comment_rows(report_invalid=False):
        post_id = clean_text(row.get(spec["comment_parent"]))
        if post_id not in posts:
            continue
        raw_parent = clean_text(row.get("parent_comment_id"))
        if raw_parent in {"", "0", "null", "None"}:
            continue
        if raw_parent not in accepted_root_ids.get(post_id, set()):
            orphan_replies += 1
            continue
        record = _comment_record(source, spec, row, posts)
        if record is None:
            continue
        record.metadata["comment_level"] = 2
        post_seen = seen_comments.setdefault(post_id, set())
        if record.external_id in post_seen:
            continue
        post_seen.add(record.external_id)
        emit(record)
        imported_comments += 1

    if orphan_replies:
        result.warnings.append(
            f"{orphan_replies} 条回复的父评论不在本次纳入的一级评论中；未计入二级评论"
        )

    if not content_files and not comment_files:
        result.warnings.append("MediaCrawler 没有生成可导入的内容或评论 JSONL")
    elif not comment_files:
        result.warnings.append("MediaCrawler 没有生成评论 JSONL；本次没有导入评论记录")
    return len(posts), imported_comments


def _build_command(
    home: Path,
    args: list[str],
    delay_seconds: float,
    *,
    profile_directory: str | Path | None = None,
) -> list[str]:
    if profile_directory:
        # MediaCrawler formats USER_DATA_DIR with the platform name; consume that token without adding it to this exact profile path.
        profile_path = str(Path(profile_directory).expanduser().resolve()).replace("%", "%%")
        profile_pattern = f"%.0s{profile_path}"
    else:
        profile_pattern = str(Path.home() / ".comment-crawler" / "mediacrawler" / "%s_user_data_dir")
    code = (
        "import config; config.ENABLE_CDP_MODE=False; "
        "config.CDP_CONNECT_EXISTING=False; config.ENABLE_IP_PROXY=False; "
        "config.ENABLE_GET_SUB_COMMENTS=True; "
        f"config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES={UNBOUNDED_UPSTREAM_COUNT}; "
        f"config.USER_DATA_DIR={profile_pattern!r}; "
        f"config.CRAWLER_MAX_SLEEP_SEC={float(delay_seconds)!r}; "
        "import main; from tools.app_runner import run; "
        "run(main.main, main.async_cleanup, cleanup_timeout_seconds=15.0)"
    )
    candidates = (home / ".venv" / "bin" / "python", home / ".venv" / "Scripts" / "python.exe")
    for python in candidates:
        if python.is_file():
            return [str(python), "-c", code, *args]
    uv = shutil.which("uv")
    if uv:
        return [uv, "run", "--locked", "--no-sync", "--project", str(home), "python", "-c", code, *args]
    return [sys.executable, "-c", code, *args]


def collect_mediacrawler(source: str, config: dict[str, Any], output: str | Path, emit: Callable[[ReviewRecord], Any]) -> CollectionResult:
    result = CollectionResult(source=source)
    spec = PLATFORMS[source]
    home = Path(config["mediacrawler_home"]).expanduser().resolve()
    _assert_prepared(home)

    data_root = Path(output) / ".mediacrawler"
    data_root.mkdir(parents=True, exist_ok=True)
    target = clean_text(config.get("target"))
    queries = [clean_text(value) for value in config.get("queries", []) if clean_text(value)]
    crawler_type = "detail" if target else "search"
    upstream_args = [
        "--platform", spec["code"], "--type", crawler_type,
        "--keywords", ",".join(queries),
        "--get_comment", "true",
        "--get_sub_comment", "true",
        "--save_data_option", "jsonl",
        "--crawler_max_notes_count", str(UNBOUNDED_UPSTREAM_COUNT),
        "--max_comments_count_singlenotes", str(UNBOUNDED_UPSTREAM_COUNT),
        "--save_data_path", str(data_root),
        "--headless", "false", "--enable_ip_proxy", "false",
    ]
    include_media, media_request_status = _media_download_support(home, source)
    if include_media:
        upstream_args.extend(["--get_media", "true" if target else "false"])
        if not target:
            media_request_status = "not_requested_until_keyword_filter"
    if target:
        upstream_args.extend(["--specified_id", target])

    interrupted = False
    return_code = None
    try:
        completed = subprocess.run(
            _build_command(
                home, upstream_args, float(config.get("delay_seconds", 2)),
                profile_directory=config.get("profile"),
            ),
            cwd=home,
            check=False,
        )
        return_code = completed.returncode
    except KeyboardInterrupt:
        interrupted = True
    except OSError as exc:
        result.errors.append(f"MediaCrawler 启动失败：{type(exc).__name__}")

    if include_media and not target and not interrupted and return_code == 0:
        matching_ids = _matching_post_ids(data_root, spec, queries)
        try:
            media_run = download_media_for_posts(
                source, home, matching_ids, output, float(config.get("delay_seconds", 2)),
                profile_directory=config.get("profile"),
            )
            media_request_status = str(media_run.get("status", "not_downloaded"))
            if media_request_status not in {"completed", "no_posts"}:
                result.warnings.append(f"{source} 命中帖子媒体下载状态：{media_request_status}")
        except KeyboardInterrupt:
            interrupted = True
            media_request_status = "interrupted"
            result.warnings.append("媒体下载已中断；已导入搜索结果与已完成媒体批次生成的记录")

    from ..web_video_analysis import WebVideoSession
    profile_directory = config.get("profile") or (
        Path.home() / ".comment-crawler" / "mediacrawler" / f"{spec['code']}_user_data_dir"
    )
    with WebVideoSession(profile_directory) as web_video_session:
        posts_count, comments_count = _import_exports(
            source, spec, data_root, emit, result, queries,
            media_request_status, web_video_session, profile_directory,
        )
    result.warnings.append("帖子按平台搜索结果导入，并要求标题或正文命中至少一个完整搜索词；帖子和评论均无本地数量上限。已启用一级评论和二级回复。平台分页、可见范围和配额仍可能限制结果。")
    if not include_media:
        result.warnings.append(f"未请求 {source} 媒体文件下载（状态：{media_request_status}）；帖子和评论仍按可见范围导入。")
    if posts_count == 0 and comments_count == 0:
        result.warnings.append("没有可导入的平台记录；请确认登录、入口权限和上游运行状态")
    if interrupted:
        result.status = "interrupted"
        result.errors.append("用户中断；已导入上游 JSONL 中可读取的记录。重跑会从原入口开始并按稳定 ID 去重，不支持精确平台游标续跑。")
    elif return_code not in (None, 0):
        result.errors.append(f"MediaCrawler 退出码为 {return_code}；已先导入运行中写出的 JSONL")
    return result
