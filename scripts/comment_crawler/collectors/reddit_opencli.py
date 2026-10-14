"""通过用户已授权的 OpenCLI/Chrome 会话读取公开 Reddit 帖子和评论。"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any

from ..core.schema import ReviewRecord, clean_text, hash_author, stable_hash
from ..core.utils import CollectionResult, ConfigurationError, RateLimiter

UNBOUNDED_VISIBLE_COUNT = 2**31 - 1


class OpenCLIRedditCollector:
    """只使用 OpenCLI 的 ``reddit search`` 和 ``reddit read`` 只读命令。"""

    name = "reddit_opencli"

    def __init__(self, config: dict[str, Any], crawl_config: dict[str, Any], emit=None):
        self.emit = emit
        self.config = config
        self.rate_limiter = RateLimiter(float(crawl_config.get("delay_seconds", 2)))
        self.timeout_seconds = int(crawl_config.get("timeout_seconds", 30))
        self.command = self._resolve_command(str(config.get("command", "opencli")))
        self.official_authors = {str(item).lower() for item in config.get("official_authors", [])}

    @staticmethod
    def _resolve_command(value: str) -> str:
        expanded = Path(value).expanduser()
        if expanded.is_absolute():
            if not expanded.is_file():
                raise ConfigurationError(f"未找到 OpenCLI：{expanded}")
            return str(expanded)
        return value

    def _run_json(self, arguments: list[str]) -> list[dict[str, Any]]:
        self.rate_limiter.wait()
        try:
            process = subprocess.run(
                [self.command, "reddit", *arguments, "-f", "json", "--window", "background"],
                capture_output=True,
                text=True,
                check=False,
                timeout=self.timeout_seconds,
            )
        except FileNotFoundError as exc:
            raise ConfigurationError("找不到 opencli；请先安装并连接 Chrome 扩展") from exc
        except subprocess.TimeoutExpired as exc:
            raise ConfigurationError(f"OpenCLI 超时（{self.timeout_seconds} 秒）") from exc
        if process.returncode:
            raise ConfigurationError(f"OpenCLI 命令失败（退出码 {process.returncode}）；请在本地检查扩展、权限和版本")
        try:
            payload = json.loads(process.stdout)
        except json.JSONDecodeError as exc:
            raise ConfigurationError("OpenCLI 未返回 JSON 数据") from exc
        if not isinstance(payload, list):
            raise ConfigurationError("OpenCLI 返回的数据结构不是列表")
        return [item for item in payload if isinstance(item, dict)]

    def _post_record(self, post: dict[str, Any], query: str) -> ReviewRecord:
        author = clean_text(post.get("author"))
        post_id = clean_text(post.get("id"))
        return ReviewRecord(
            source=self.name,
            content_type="post",
            url=clean_text(post.get("url")),
            external_id=f"t3_{post_id}" if post_id else stable_hash(clean_text(post.get("url"))),
            title=clean_text(post.get("title")),
            body=clean_text(post.get("selftext")),
            author_hash=hash_author(self.name, author),
            published_at=post.get("created_utc"),
            score=self._as_int(post.get("score")),
            reply_count=self._as_int(post.get("comments")),
            is_official=author.lower() in self.official_authors,
            metadata={
                "backend": "opencli",
                "subreddit": clean_text(post.get("subreddit")),
                "search_query": query,
                "post_hint": clean_text(post.get("post_hint")),
                "media_assets": {
                    "status": "not_downloaded_by_opencli"
                    if post.get("is_video") or "video" in clean_text(post.get("post_hint")).lower()
                    else "not_applicable",
                    "download_requested": False,
                    "files": [],
                },
            },
        ).normalize()

    def _comment_records(self, post: dict[str, Any]) -> list[ReviewRecord]:
        post_id = clean_text(post.get("id"))
        post_url = clean_text(post.get("url"))
        if not post_id or not post_url:
            return []
        comments = self._run_json([
            "read", post_id,
            "--sort", str(self.config.get("comment_sort", "top")),
            "--limit", str(UNBOUNDED_VISIBLE_COUNT),
            "--depth", "2",
            "--replies", str(UNBOUNDED_VISIBLE_COUNT),
            "--max-length", "2147483647",
            "--expand-more", "--expand-rounds", "5",
        ])
        records: list[ReviewRecord] = []
        parent_by_level: dict[int, str] = {}
        for index, item in enumerate(comments):
            comment_type = clean_text(item.get("type")).upper()
            if comment_type == "POST":
                continue
            body = clean_text(item.get("text"))
            if not body or body.startswith("[+"):
                continue
            level = int(comment_type[1:]) if comment_type.startswith("L") and comment_type[1:].isdigit() else 0
            if level > 1:
                continue
            parent_id = parent_by_level.get(level - 1, f"t3_{post_id}") if level else f"t3_{post_id}"
            external_id = f"opencli_{post_id}_{index}_{stable_hash(body, 12)}"
            parent_by_level[level] = external_id
            for deeper_level in list(parent_by_level):
                if deeper_level > level:
                    del parent_by_level[deeper_level]
            author = clean_text(item.get("author"))
            records.append(ReviewRecord(
                source=self.name,
                content_type="comment",
                url=post_url,
                external_id=external_id,
                parent_id=parent_id,
                body=body,
                author_hash=hash_author(self.name, author),
                score=self._as_int(item.get("score")),
                is_official=author.lower() in self.official_authors,
                metadata={
                    "backend": "opencli",
                    "subreddit": clean_text(post.get("subreddit")),
                    "comment_level": level + 1,
                    "coverage": "backend_limited",
                    "id_kind": "synthetic_order_dependent",
                },
            ).normalize())
        return records

    def collect(self) -> CollectionResult:
        result = CollectionResult(source="reddit_opencli", emit=self.emit)
        queries = [str(item).strip() for item in self.config.get("queries", []) if str(item).strip()]
        subreddits = [str(item).strip() for item in self.config.get("subreddits", []) if str(item).strip()]
        # 当前 OpenCLI 不暴露搜索 after 游标；不在请求侧设置有限结果数。
        result.status = "backend_limited"
        result.warnings.append("OpenCLI 搜索单次读取且不暴露分页游标；评论读取无本地数量上限，仅保存一级评论和二级回复。OpenCLI 的‘更多评论’展开最多 5 轮，且结果受页面可见范围限制。需要分页搜索时请使用 reddit OAuth 来源。评论 ID 为合成键，排序变化可能产生重复。")
        seen: set[str] = set()
        posts: list[dict[str, Any]] = []
        for subreddit in subreddits or [""]:
            for query in queries:
                arguments = ["search", query, "--sort", str(self.config.get("sort", "relevance")),
                             "--limit", str(UNBOUNDED_VISIBLE_COUNT)]
                if subreddit:
                    arguments.extend(["--subreddit", subreddit])
                try:
                    found = self._run_json(arguments)
                except Exception as exc:
                    scope = f"r/{subreddit} / " if subreddit else ""
                    result.errors.append(f"Reddit 搜索失败 {scope}{query}：{type(exc).__name__}: {exc}")
                    return result
                for post in found:
                    post_id = clean_text(post.get("id")) or clean_text(post.get("url"))
                    if (
                        not post_id
                        or post_id in seen
                    ):
                        result.skipped += 1
                        continue
                    seen.add(post_id)
                    posts.append(post)
                    result.add(self._post_record(post, query))
        if not bool(self.config.get("read_comments", True)):
            return result
        for post in posts:
            try:
                result.extend(self._comment_records(post))
            except Exception as exc:
                result.errors.append(f"Reddit 评论读取失败 {clean_text(post.get('id'))}：{type(exc).__name__}: {exc}")
                break
        return result

    @staticmethod
    def _as_int(value: Any) -> int | None:
        try:
            return int(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None
