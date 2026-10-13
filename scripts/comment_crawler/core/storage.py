"""SQLite 为主、CSV/JSONL 为辅的可续跑数据存储。"""
from __future__ import annotations

import csv
import json
from pathlib import Path
import sqlite3
from typing import Iterator

from .schema import ReviewRecord


CSV_COLUMNS = [
    "source", "content_type", "url", "external_id", "parent_id", "title", "body", "content_completeness",
    "author_hash", "published_at", "captured_at", "language", "score", "reply_count",
    "rating", "is_official", "metadata",
]


class ReviewStore:
    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.database_path)
        self.connection.row_factory = sqlite3.Row
        self._initialize()

    def _initialize(self) -> None:
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS records (
                record_key TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                content_type TEXT NOT NULL,
                external_id TEXT NOT NULL,
                url TEXT NOT NULL,
                published_at TEXT,
                captured_at TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_records_source ON records(source)")
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_records_published_at ON records(published_at)")
        self.connection.commit()

    def upsert(self, record: ReviewRecord) -> str:
        payload = record.as_dict()
        key = record.record_key
        content_hash = record.content_hash
        existing = self.connection.execute(
            "SELECT content_hash FROM records WHERE record_key = ?", (key,)
        ).fetchone()
        if existing and existing["content_hash"] == content_hash:
            return "unchanged"
        action = "updated" if existing else "inserted"
        self.connection.execute(
            """
            INSERT INTO records (
                record_key, source, content_type, external_id, url, published_at,
                captured_at, content_hash, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(record_key) DO UPDATE SET
                source=excluded.source,
                content_type=excluded.content_type,
                external_id=excluded.external_id,
                url=excluded.url,
                published_at=excluded.published_at,
                captured_at=excluded.captured_at,
                content_hash=excluded.content_hash,
                payload_json=excluded.payload_json
            """,
            (
                key, record.source, record.content_type, record.external_id, record.url,
                record.published_at, record.captured_at, content_hash,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
            ),
        )
        self.connection.commit()
        return action

    def iter_records(self) -> Iterator[ReviewRecord]:
        rows = self.connection.execute(
            "SELECT payload_json FROM records ORDER BY published_at DESC, captured_at DESC"
        )
        for row in rows:
            yield ReviewRecord.from_dict(json.loads(row["payload_json"]))

    def count(self) -> int:
        return int(self.connection.execute("SELECT COUNT(*) FROM records").fetchone()[0])

    def summary_by_source(self) -> dict[str, int]:
        rows = self.connection.execute(
            "SELECT source, COUNT(*) AS total FROM records GROUP BY source ORDER BY source"
        )
        return {row["source"]: int(row["total"]) for row in rows}

    def summary_by_content_type(self) -> dict[str, int]:
        rows = self.connection.execute(
            "SELECT content_type, COUNT(*) AS total FROM records GROUP BY content_type ORDER BY content_type"
        )
        return {row["content_type"]: int(row["total"]) for row in rows}

    def quality_summary(self) -> dict[str, dict]:
        summary = QualitySummary()
        for record in self.iter_records():
            summary.add(record)
        return summary.as_dict()

    def external_ids(self, source: str, content_type: str) -> set[str]:
        """返回已有记录的外部 ID，用于续跑时避免重复请求详情。"""
        rows = self.connection.execute(
            "SELECT external_id FROM records WHERE source = ? AND content_type = ?",
            (source, content_type),
        )
        return {str(row["external_id"]) for row in rows}

    def export_jsonl(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            for record in self.iter_records():
                handle.write(json.dumps(record.as_dict(), ensure_ascii=False) + "\n")
        return target

    def export_csv(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            for record in self.iter_records():
                row = record.as_dict()
                for field in ("metadata",):
                    row[field] = json.dumps(row[field], ensure_ascii=False)
                for field, value in row.items():
                    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
                        row[field] = "'" + value
                writer.writerow({column: row.get(column, "") for column in CSV_COLUMNS})
        return target

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "ReviewStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class QualitySummary:
    """Count populated fields by record type without retaining record contents."""

    FIELDS = {
        "post": ("title", "body", "author_hash", "published_at"),
        "comment": ("body", "author_hash", "published_at"),
        "default": ("title", "body", "author_hash", "published_at"),
    }
    ENGAGEMENT = ("likes", "saves", "comments", "shares")

    def __init__(self):
        self.groups: dict[str, dict] = {}

    def add(self, record: ReviewRecord) -> None:
        content_type = record.content_type or "unknown"
        group = self.groups.setdefault(content_type, {
            "records": 0,
            "fields": {name: {"present": 0, "missing": 0}
                       for name in self.FIELDS.get(content_type, self.FIELDS["default"])},
        })
        group["records"] += 1
        for name in self.FIELDS.get(content_type, self.FIELDS["default"]):
            group["fields"][name]["present" if bool(getattr(record, name, "")) else "missing"] += 1
        if record.source == "xiaohongshu":
            ids = group.setdefault("ids", {"platform": 0, "synthetic": 0, "unknown": 0})
            id_kind = record.metadata.get("id_kind") if isinstance(record.metadata, dict) else None
            if not id_kind and content_type == "post" and record.external_id.startswith("note:"):
                id_kind = "platform"
            ids[id_kind if id_kind in ("platform", "synthetic") else "unknown"] += 1
        if content_type == "post":
            engagement = record.metadata.get("visible_engagement", {}) if isinstance(record.metadata, dict) else {}
            counts = group.setdefault("visible_engagement", {
                name: {"present": 0, "missing": 0} for name in self.ENGAGEMENT
            })
            for name in self.ENGAGEMENT:
                value = engagement.get(name, "") if isinstance(engagement, dict) else ""
                counts[name]["present" if bool(str(value).strip()) else "missing"] += 1

    def as_dict(self) -> dict[str, dict]:
        return {content_type: values for content_type, values in sorted(self.groups.items())}
