"""跨平台评论记录；不推断产品、主题或情感。"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any


def utc_now() -> str:
    """返回统一的 UTC ISO-8601 时间字符串。"""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def clean_text(value: Any) -> str:
    """压缩空白，避免 CSV/SQLite 中出现难以阅读的换行。"""
    return re.sub(r"\s+", " ", str(value or "")).strip()


def stable_hash(value: str, length: int = 20) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def hash_author(source: str, author: Any) -> str:
    """仅保留可去重的匿名作者标识，不把用户名写入数据集。"""
    author_text = clean_text(author)
    if not author_text or author_text.lower() in {"[deleted]", "deleted", "null"}:
        return ""
    return stable_hash(f"{source}:{author_text}", 24)


def to_iso8601(value: Any) -> str:
    """将常见 API 的 Unix 时间戳或 ISO 字符串标准化。"""
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).replace(microsecond=0).isoformat()
    text = clean_text(value)
    if not text:
        return ""
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def detect_language(text: str) -> str:
    """足够用于分流的中英检测，不把它当作语言识别的最终结论。"""
    text = clean_text(text)
    if not text:
        return ""
    han = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    if han and han >= latin / 4:
        return "zh"
    if latin:
        return "en"
    return "other"


@dataclass
class ReviewRecord:
    """一条帖子、评论、视频或媒体测评的规范化表示。"""

    source: str
    content_type: str
    url: str
    external_id: str
    title: str = ""
    body: str = ""
    content_completeness: str = "full"
    parent_id: str = ""
    author_hash: str = ""
    published_at: str = ""
    captured_at: str = field(default_factory=utc_now)
    language: str = ""
    score: int | None = None
    reply_count: int | None = None
    rating: float | None = None
    is_official: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def normalize(self) -> "ReviewRecord":
        self.source = clean_text(self.source).lower()
        self.content_type = clean_text(self.content_type).lower() or "review"
        self.url = clean_text(self.url)
        self.title = clean_text(self.title)
        self.body = clean_text(self.body)
        self.content_completeness = clean_text(self.content_completeness).lower() or "full"
        if self.content_completeness not in {"full", "partial", "index_summary"}:
            self.content_completeness = "full"
        self.parent_id = clean_text(self.parent_id)
        self.external_id = clean_text(self.external_id) or stable_hash(
            f"{self.source}|{self.content_type}|{self.url}|{self.parent_id}|{self.title}|{self.body}"
        )
        self.published_at = to_iso8601(self.published_at)
        self.captured_at = to_iso8601(self.captured_at) or utc_now()
        corpus = f"{self.title}\n{self.body}"
        self.language = self.language or detect_language(corpus)
        return self

    @property
    def record_key(self) -> str:
        return stable_hash(f"{self.source}|{self.content_type}|{self.external_id}|{self.parent_id}", 64)

    @property
    def content_hash(self) -> str:
        payload = self.as_dict()
        # 抓取时间每次都会变化，不能让它单独触发重复更新。
        payload.pop("captured_at", None)
        return stable_hash(json.dumps(payload, ensure_ascii=False, sort_keys=True), 64)

    def as_dict(self) -> dict[str, Any]:
        self.normalize()
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ReviewRecord":
        allowed = {field_name for field_name in cls.__dataclass_fields__}
        return cls(**{key: value for key, value in payload.items() if key in allowed}).normalize()
