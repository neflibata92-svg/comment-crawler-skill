"""通过 Reddit OAuth API 采集公开帖子与评论，不模拟用户登录。"""
from __future__ import annotations

import base64
from typing import Any, Iterator
from urllib.parse import urlencode

from ..core.schema import ReviewRecord, clean_text, hash_author
from ..core.utils import CollectionResult, RateLimiter, ConfigurationError, request_json, required_env, resolve_proxy


class RedditCollector:
    name = "reddit"

    def __init__(self, config: dict[str, Any], crawl_config: dict[str, Any], emit=None):
        self.emit = emit
        self.config = config
        self.timeout_seconds = int(crawl_config.get("timeout_seconds", 30))
        self.rate_limiter = RateLimiter(float(crawl_config.get("delay_seconds", 2)))
        self.proxy_url = resolve_proxy(crawl_config)
        self.user_agent = str(config.get("user_agent", "CommentCrawler/0.1"))
        self.official_authors = {str(item).lower() for item in config.get("official_authors", [])}

    def _token(self) -> str:
        client_id = required_env(str(self.config.get("client_id_env", "REDDIT_CLIENT_ID")))
        client_secret = required_env(str(self.config.get("client_secret_env", "REDDIT_CLIENT_SECRET")))
        basic = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
        self.rate_limiter.wait()
        response = request_json(
            "https://www.reddit.com/api/v1/access_token",
            headers={
                "Authorization": f"Basic {basic}",
                "User-Agent": self.user_agent,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data=urlencode({"grant_type": "client_credentials"}).encode("utf-8"),
            timeout=self.timeout_seconds,
            proxy_url=self.proxy_url,
        )
        if not isinstance(response, dict) or not response.get("access_token"):
            raise ConfigurationError("Reddit OAuth 未返回 access_token")
        return str(response["access_token"])

    def _api(self, path: str, token: str) -> dict[str, Any] | list[Any]:
        self.rate_limiter.wait()
        return request_json(
            f"https://oauth.reddit.com{path}",
            headers={"Authorization": f"Bearer {token}", "User-Agent": self.user_agent},
            timeout=self.timeout_seconds,
            proxy_url=self.proxy_url,
        )

    def _post_record(self, post: dict[str, Any]) -> ReviewRecord:
        author = clean_text(post.get("author"))
        permalink = clean_text(post.get("permalink"))
        return ReviewRecord(
            source=self.name,
            content_type="post",
            url=f"https://www.reddit.com{permalink}",
            external_id=clean_text(post.get("name")) or f"t3_{post.get('id', '')}",
            title=clean_text(post.get("title")),
            body=clean_text(post.get("selftext")),
            author_hash=hash_author(self.name, author),
            published_at=post.get("created_utc"),
            score=self._as_int(post.get("score")),
            reply_count=self._as_int(post.get("num_comments")),
            is_official=author.lower() in self.official_authors,
            metadata={
                "subreddit": clean_text(post.get("subreddit")),
                "permalink": permalink,
                "media_assets": {
                    "status": "not_downloaded_by_reddit_api" if post.get("is_video") else "not_applicable",
                    "download_requested": False,
                    "files": [],
                },
            },
        ).normalize()

    def _comment_records(self, node: Any, post_url: str, depth: int = 1) -> Iterator[ReviewRecord]:
        if not isinstance(node, dict):
            return
        if node.get("kind") != "t1":
            return
        data = node.get("data") or {}
        author = clean_text(data.get("author"))
        replies = data.get("replies")
        reply_children = (
            ((replies.get("data") or {}).get("children", []))
            if isinstance(replies, dict)
            else []
        )
        yield ReviewRecord(
            source=self.name,
            content_type="comment",
            url=post_url,
            external_id=clean_text(data.get("name")) or f"t1_{data.get('id', '')}",
            parent_id=clean_text(data.get("parent_id")),
            body=clean_text(data.get("body")),
            author_hash=hash_author(self.name, author),
            published_at=data.get("created_utc"),
            score=self._as_int(data.get("score")),
            reply_count=len(reply_children),
            is_official=author.lower() in self.official_authors,
            metadata={"subreddit": clean_text(data.get("subreddit")), "comment_level": depth},
        ).normalize()
        if isinstance(replies, dict):
            for child in reply_children:
                yield from self._comment_records(child, post_url, depth + 1)

    def _comments(self, post: dict[str, Any], token: str) -> Iterator[ReviewRecord]:
        post_id = clean_text(post.get("id"))
        if not post_id:
            return
        # Reddit's public API caps a listing response at 100; MoreComments nodes
        # below are expanded in successive requests until none remain.
        params = urlencode({"limit": 100, "sort": "new"})
        payload = self._api(f"/comments/{post_id}.json?{params}", token)
        if not isinstance(payload, list) or len(payload) < 2:
            raise ValueError("评论响应格式异常")
        children = (payload[1].get("data") or {}).get("children")
        if not isinstance(children, list):
            raise ValueError("评论响应缺少 children")
        post_url = f"https://www.reddit.com{clean_text(post.get('permalink'))}"
        pending = list(children)
        requested: set[str] = set()
        seen: set[str] = set()
        depth_by_comment_id: dict[str, int] = {}
        while pending:
            more_ids: list[str] = []
            while pending:
                node = pending.pop()
                data = node.get("data") or {}
                if node.get("kind") == "more":
                    parent_id = clean_text(data.get("parent_id"))
                    parent_depth = 0 if parent_id.startswith("t3_") else depth_by_comment_id.get(parent_id)
                    if parent_depth is not None and parent_depth >= 2:
                        continue
                    ids = data.get("children") or []
                    if not ids and data.get("count", 0):
                        raise ValueError("评论展开节点缺少 children，结果不完整")
                    for child_id in ids:
                        if child_id not in requested:
                            requested.add(child_id)
                            more_ids.append(child_id)
                    continue
                if node.get("kind") != "t1":
                    continue
                replies = data.get("replies")
                parent_id = clean_text(data.get("parent_id"))
                if parent_id.startswith("t3_"):
                    depth = 1
                elif parent_id in depth_by_comment_id:
                    depth = depth_by_comment_id[parent_id] + 1
                else:
                    continue
                if depth > 2:
                    continue
                if isinstance(replies, dict) and depth < 2:
                    pending.extend((replies.get("data") or {}).get("children") or [])
                # 迭代展开，避免 Python 递归深度成为评论层级上限。
                flat = {"kind": "t1", "data": {**data, "replies": ""}}
                for record in self._comment_records(flat, post_url, depth):
                    record.reply_count = None  # 展开返回不提供可靠的总回复数
                    depth_by_comment_id[record.external_id] = depth
                    if record.external_id not in seen:
                        seen.add(record.external_id)
                        yield record
            for offset in range(0, len(more_ids), 100):
                params = urlencode({"api_type": "json", "link_id": f"t3_{post_id}",
                                    "children": ",".join(more_ids[offset:offset + 100]), "sort": "new"})
                response = self._api(f"/api/morechildren?{params}", token)
                envelope = response.get("json", {})
                things = (envelope.get("data") or {}).get("things")
                if envelope.get("errors") or not isinstance(things, list):
                    raise ValueError("展开更多评论失败，结果不完整")
                pending.extend(things)
        missing = {f"t1_{child_id}" for child_id in requested} - seen
        if missing:
            raise ValueError(f"更多评论返回不完整：{len(missing)} 个请求的评论 ID 未返回")

    def collect(self) -> CollectionResult:
        result = CollectionResult(source=self.name, emit=self.emit)
        try:
            token = self._token()
            seen_posts: set[str] = set()
            queries = [str(q).strip() for q in self.config.get("queries", []) if str(q).strip()]
            subreddits = [str(s).strip() for s in self.config.get("subreddits", []) if str(s).strip()]
            for subreddit in subreddits or [""]:
                for query in queries:
                    after = ""
                    cursors: set[str] = set()
                    while True:
                        params = {"q": query, "restrict_sr": int(bool(subreddit)), "sort": "relevance", "limit": 100}
                        if after:
                            params["after"] = after
                        base = f"/r/{subreddit}" if subreddit else ""
                        payload = self._api(f"{base}/search.json?{urlencode(params)}", token)
                        data = payload.get("data") or {}
                        children = data.get("children")
                        if not isinstance(children, list):
                            raise ValueError("搜索响应缺少 children")
                        for child in children:
                            post = child.get("data") or {}
                            post_name = clean_text(post.get("name") or post.get("id"))
                            if not post_name or post_name in seen_posts:
                                continue
                            seen_posts.add(post_name)
                            result.add(self._post_record(post))
                            if self.config.get("read_comments", True):
                                result.extend(self._comments(post, token))
                        after = clean_text(data.get("after"))
                        if not after:
                            break
                        if after in cursors:
                            raise ValueError("Reddit 搜索分页游标重复")
                        cursors.add(after)
        except Exception as exc:
            result.errors.append(f"Reddit 采集中断：{type(exc).__name__}: {exc}")
        return result

    @staticmethod
    def _as_int(value: Any) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None
