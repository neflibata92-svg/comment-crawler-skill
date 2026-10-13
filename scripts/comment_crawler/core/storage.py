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
