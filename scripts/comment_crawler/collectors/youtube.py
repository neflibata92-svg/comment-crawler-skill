"""通过 YouTube Data API v3 采集公开视频元数据与公开评论。"""
from __future__ import annotations

from typing import Any, Iterator
from urllib.parse import urlencode

from ..core.schema import ReviewRecord, clean_text, hash_author
from ..core.utils import CollectionResult, RateLimiter, required_env, request_json, resolve_proxy


class YouTubeCollector:
    name = "youtube"
    API_ROOT = "https://www.googleapis.com/youtube/v3"

    def __init__(self, config: dict[str, Any], crawl_config: dict[str, Any], emit=None):
        self.emit = emit
        self.config = config
        self.timeout_seconds = int(crawl_config.get("timeout_seconds", 30))
        self.rate_limiter = RateLimiter(float(crawl_config.get("delay_seconds", 2)))
        self.proxy_url = resolve_proxy(crawl_config)
        self.official_channel_ids = {str(item) for item in config.get("official_channel_ids", [])}

    def _api(self, endpoint: str, params: dict[str, Any], api_key: str) -> dict[str, Any]:
        request_params = dict(params)
        request_params["key"] = api_key
        self.rate_limiter.wait()
        payload = request_json(
            f"{self.API_ROOT}/{endpoint}?{urlencode(request_params)}",
            timeout=self.timeout_seconds,
            proxy_url=self.proxy_url,
        )
        if not isinstance(payload, dict):
            raise RuntimeError("YouTube API 返回格式异常")
        return payload

    def _video_record(self, item: dict[str, Any]) -> ReviewRecord:
        video_id = clean_text(item.get("id"))
        snippet = item.get("snippet") or {}
        statistics = item.get("statistics") or {}
        channel_id = clean_text(snippet.get("channelId"))
        return ReviewRecord(
            source=self.name,
            content_type="video",
            url=f"https://www.youtube.com/watch?v={video_id}",
            external_id=f"video:{video_id}",
            title=clean_text(snippet.get("title")),
            body=clean_text(snippet.get("description")),
            author_hash=hash_author(self.name, channel_id),
            published_at=snippet.get("publishedAt"),
            score=self._as_int(statistics.get("likeCount")),
            reply_count=self._as_int(statistics.get("commentCount")),
            language=clean_text(snippet.get("defaultLanguage") or snippet.get("defaultAudioLanguage")),
            is_official=channel_id in self.official_channel_ids,
            metadata={"channel_id": channel_id, "channel_title": clean_text(snippet.get("channelTitle"))},
        ).normalize()

    def _comment_records(self, item: dict[str, Any], video_url: str, parent_id: str = "") -> Iterator[ReviewRecord]:
        snippet = item.get("snippet") or {}
        comment_id = clean_text(item.get("id"))
        author_id = ((snippet.get("authorChannelId") or {}).get("value"))
        yield ReviewRecord(
            source=self.name,
            content_type="comment",
            url=video_url,
            external_id=f"comment:{comment_id}",
            parent_id=parent_id,
            body=clean_text(snippet.get("textDisplay") or snippet.get("textOriginal")),
            author_hash=hash_author(self.name, author_id),
            published_at=snippet.get("publishedAt"),
            score=self._as_int(snippet.get("likeCount")),
            reply_count=self._as_int(snippet.get("totalReplyCount")),
            metadata={"video_url": video_url},
        ).normalize()

    def _pages(self, endpoint: str, params: dict[str, Any], api_key: str) -> Iterator[dict[str, Any]]:
        params = dict(params)
        seen_tokens: set[str] = set()
        while True:
            payload = self._api(endpoint, params, api_key)
            if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
                raise ValueError(f"{endpoint} 响应缺少 items，不能判定采集结束")
            yield payload
            token = clean_text(payload.get("nextPageToken"))
            if not token:
                return
            if token in seen_tokens:
                raise ValueError(f"{endpoint} 分页游标重复，停止以避免循环")
            seen_tokens.add(token)
            params["pageToken"] = token

    def _comments(self, video_id: str, api_key: str) -> Iterator[ReviewRecord]:
        if not self.config.get("read_comments", True):
            return
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        seen: set[str] = set()
        for payload in self._pages("commentThreads", {
            "part": "snippet,replies", "videoId": video_id,
            "maxResults": 100, "order": "time", "textFormat": "plainText",
        }, api_key):
            for thread in payload["items"]:
                snippet = thread.get("snippet") or {}
                top = snippet.get("topLevelComment")
                if not isinstance(top, dict) or not top.get("id"):
                    raise ValueError("评论线程缺少顶层评论 ID")
                parent_id = f"comment:{top['id']}"
                if parent_id in seen:
                    continue
                seen.add(parent_id)
                yield from self._comment_records(top, video_url)
                replies = (thread.get("replies") or {}).get("comments") or []
                if int(snippet.get("totalReplyCount", 0)) > len(replies):
                    # 单独分页补齐回复；不能只使用线程内附带的回复片段。
                    reply_pages = self._pages("comments", {
                        "part": "snippet", "parentId": top["id"],
                        "maxResults": 100, "textFormat": "plainText",
                    }, api_key)
                else:
                    reply_pages = iter([{"items": replies}])
                for reply_page in reply_pages:
                    for reply in reply_page["items"]:
                        reply_id = clean_text(reply.get("id"))
                        if not reply_id:
                            raise ValueError("回复缺少 ID")
                        if f"comment:{reply_id}" not in seen:
                            seen.add(f"comment:{reply_id}")
                            yield from self._comment_records(reply, video_url, parent_id=parent_id)

    def collect(self) -> CollectionResult:
        result = CollectionResult(source=self.name, emit=self.emit)
        try:
            api_key = required_env(str(self.config.get("api_key_env", "YOUTUBE_API_KEY")))
        except Exception as exc:
            result.errors.append(f"YouTube 未启动：{type(exc).__name__}: {exc}")
            return result
        seen_video_ids: set[str] = set()
        search_order = str(self.config.get("search_order", "relevance"))
        if search_order not in {"date", "rating", "relevance", "title", "videoCount", "viewCount"}:
            search_order = "relevance"
        queries = [str(query).strip() for query in self.config.get("queries", []) if str(query).strip()]
        for query in queries:
            try:
                for search in self._pages("search", {
                    "part": "snippet", "q": query, "type": "video",
                    "maxResults": 50, "order": search_order,
                }, api_key):
                    ids = []
                    for item in search["items"]:
                        video_id = clean_text((item.get("id") or {}).get("videoId"))
                        if video_id and video_id not in seen_video_ids:
                            ids.append(video_id)
                            seen_video_ids.add(video_id)
                    if not ids:
                        continue
                    details = self._api("videos", {"part": "snippet,statistics", "id": ",".join(ids)}, api_key)
                    for item in details.get("items", []):
                        video_id = clean_text(item.get("id"))
                        if not video_id:
                            continue
                        result.add(self._video_record(item))
                        # 已存视频仍刷新评论；SQLite 使用稳定 ID 去重。
                        result.extend(self._comments(video_id, api_key))
            except Exception as exc:
                result.errors.append(f"YouTube 采集中断 {query}：{type(exc).__name__}: {exc}")
                break
        return result

    @staticmethod
    def _as_int(value: Any) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None
