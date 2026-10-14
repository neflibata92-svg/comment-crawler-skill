"""本地评论清洗与量化分析；规则标签是预标注，不替代人工判断。"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
import statistics
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote


COMMENT_TYPES = {"comment", "reply", "review", "rating", "feedback", "user_review", "product_review"}
CONTEXT_TYPES = {"post", "video", "article", "note", "product", "thread"}
MAX_NEAR_COMPARISONS = 500_000

OUTPUT_FIELDS = [
    "source", "content_type", "content_group", "comment_id", "parent_id", "published_at", "captured_at", "title_original",
    "text_original", "is_included", "exclusion_reason", "duplicate_group_id", "duplicate_type",
    "duplicate_count", "duplicate_comment_ids_json", "duplicate_author_ids_json", "duplicate_author_missing_count",
    "product_or_brand", "product_relevance", "annotation_status", "comment_intent", "experience_status", "topics", "pain_points",
    "user_scenario", "purchase_barrier", "sentiment", "severity_by_pain_point", "evidence_type", "confidence",
    "evidence_note", "analysis_record_key", "anonymous_author_id", "source_url", "source_file", "source_row",
    "source_locations_json", "source_fields_json", "content_completeness", "id_kind", "score", "rating",
    "reply_count", "metadata_json", "review_status", "near_duplicate_similarity",
]

TOPIC_RULES = {
    "价格与价值": ("价格", "太贵", "贵了", "便宜", "性价比", "不值", "价格高", "price", "expensive", "cheap", "cost", "worth it", "value for money"),
    "功能与性能": ("功能", "性能", "识别", "翻译", "准确", "不准", "拍摄", "对焦", "卡顿", "反应慢", "feature", "function", "performance", "accuracy", "lag", "slow"),
    "稳定性与质量": ("故障", "质量", "死机", "损坏", "闪退", "断连", "不稳定", "耐用", "broken", "crash", "disconnect", "unstable", "reliable", "quality"),
    "易用性": ("难用", "好用", "操作", "设置", "复杂", "不方便", "麻烦", "学习成本", "easy to use", "hard to use", "setup", "confusing", "inconvenient"),
    "兼容性与连接": ("兼容", "蓝牙", "连接", "配对", "安卓", "苹果", "ios", "android", "bluetooth", "pairing", "compatible", "connect"),
    "续航与充电": ("续航", "电池", "电量", "充电", "发热", "battery", "charging", "battery life", "overheat"),
    "舒适度与设计": ("佩戴", "戴着", "重量", "舒服", "不舒服", "硌", "外观", "设计", "wear", "comfortable", "heavy", "design"),
    "服务与履约": ("客服", "售后", "退款", "退货", "维修", "物流", "发货", "保修", "customer support", "refund", "return", "repair", "delivery", "warranty"),
}

PAIN_CUES = (
    "问题", "不好", "不行", "不满意", "失望", "难用", "麻烦", "不方便", "不稳定", "无法", "不能", "没法",
    "故障", "坏了", "太贵", "有点贵", "价格偏高", "价格高", "买不起", "不划算", "不值", "卡顿", "慢",
    "不准", "缺少", "不够", "不足", "缺点", "缺陷", "不支持", "影响体验", "影响使用",
    "problem", "bad", "poor", "disappoint", "hard to use", "annoying", "inconvenient", "unreliable", "cannot",
    "can't", "doesn't work", "broken", "too expensive", "not worth", "missing", "unsupported", "slow",
)

POSITIVE_CUES = (
    "非常满意", "很满意", "满意", "喜欢", "好用", "不错", "值得", "推荐", "性价比高", "方便", "清晰", "准确", "稳定",
    "great", "excellent", "love", "recommend", "worth it", "easy to use", "works well", "reliable", "convenient",
)
NEGATIVE_CUES = (
    "不满意", "不好用", "不好", "很差", "差评", "失望", "难用", "太贵", "不值", "卡顿", "断连", "不能用", "无法使用",
    "不支持", "故障", "坏了", "退款", "麻烦", "不推荐", "bad", "poor", "disappoint", "hard to use", "expensive",
    "not worth", "doesn't work", "broken", "unreliable", "annoying", "failed", "refund",
)

INTENT_CUES = {
    "售后反馈": ("售后", "客服", "退款", "退货", "维修", "保修", "发货", "物流", "customer support", "refund", "return", "repair", "warranty", "delivery"),
    "产品比较": ("对比", "比较", "相比", "竞品", "vs", "versus", "compared to", "comparison"),
    "功能建议": ("建议", "希望增加", "希望可以", "能不能", "可不可以", "最好", "应该支持", "please add", "feature request", "would be nice"),
    "购买顾虑": ("担心", "犹豫", "不敢买", "值不值得买", "值得买吗", "要不要买", "买不买", "would buy if", "hesitant", "concerned about"),
    "购买意向": ("想买", "准备买", "考虑购买", "考虑入手", "打算购买", "thinking of buying", "considering buying", "planning to buy"),
    "咨询": ("多少钱", "怎么用", "如何使用", "是否支持", "有没有", "能否", "how much", "how to", "does it", "is it", "can it"),
    "使用反馈": ("用了", "用过", "买了", "入手", "收到", "使用", "体验", "used", "bought", "using", "tried", "works"),
}

PURCHASE_BARRIER_CUES = (
    "担心", "犹豫", "不敢买", "太贵", "有点贵", "价格偏高", "价格高", "买不起", "不划算", "不值",
    "concerned", "hesitant", "too expensive", "not worth",
)

ANNOTATION_FIELDS = (
    "annotation_status", "product_relevance", "is_included", "content_group", "exclusion_reason", "comment_intent",
    "experience_status", "topics", "pain_points", "user_scenario", "purchase_barrier", "sentiment",
    "severity_by_pain_point", "evidence_type", "confidence", "evidence_note",
)

EXPERIENCE_CUES = {
    "体验过但未购买": ("试用过但没买", "体验过但未购买", "试过还没买", "还没买但体验", "tried but haven't bought", "tested but did not buy"),
    "仅看过测评": ("看测评", "看了评测", "看到测评", "测评里", "only saw a review", "watched a review"),
    "潜在购买者": ("想买", "准备买", "考虑买", "考虑入手", "想入手", "打算购买", "值不值得买", "值得买吗", "要不要买", "thinking of buying", "considering buying", "planning to buy"),
    "实际使用": ("我用了", "用了一个", "用了几天", "买了", "已经入手", "收到后", "一直在用", "我在用", "i bought", "i have used", "i've used", "been using"),
}

SCENARIO_CUES = {
    "工作/办公": ("工作", "办公", "会议", "出差", "work", "office", "meeting", "business trip"),
    "学习/课堂": ("学习", "上课", "课堂", "作业", "study", "class", "lecture", "homework"),
    "通勤/出行": ("通勤", "地铁", "公交", "开车", "出行", "commute", "subway", "bus", "driving", "travel"),
    "运动/户外": ("运动", "跑步", "健身", "户外", "骑行", "exercise", "running", "outdoor", "cycling", "hiking"),
    "家庭/照护": ("孩子", "家人", "老人", "照护", "family", "child", "parent", "caregiving"),
}

AD_CUES = (
    "加我微信", "加微信领", "私信领取", "扫码领券", "扫码进群", "免费送名额", "招代理", "联系我拿优惠",
    "dm me for a discount", "use my promo code", "affiliate link",
)


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _first(record: dict[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        value = record.get(key)
        if value is not None and value != "":
            return value
    return default


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _stable(value: str, length: int = 24) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def _normalized(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"\s+", " ", value).strip()


def _json_string_list(value: Any) -> list[str]:
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except (TypeError, json.JSONDecodeError):
        parsed = []
    if not isinstance(parsed, list):
        return []
    return list(dict.fromkeys(_text(item) for item in parsed if _text(item)))


def _row_comment_ids(row: dict[str, Any]) -> list[str]:
    return _json_string_list(row.get("duplicate_comment_ids_json")) or ([row["comment_id"]] if row.get("comment_id") else [])


def _row_author_ids(row: dict[str, Any]) -> list[str]:
    return _json_string_list(row.get("duplicate_author_ids_json")) or (
        [row["anonymous_author_id"]] if row.get("anonymous_author_id") else []
    )


def _row_author_missing_count(row: dict[str, Any]) -> int:
    try:
        return max(0, int(row.get("duplicate_author_missing_count", 0)))
    except (TypeError, ValueError):
        return int(not row.get("anonymous_author_id"))


def _privacy_safe_fields(raw: dict[str, Any]) -> dict[str, Any]:
    """保留非身份来源字段；作者昵称、账号、主页等不复制到分析表。"""
    sensitive_tokens = ("username", "nickname", "profile", "userid", "authorname", "authorid", "authorhandle", "account", "avatar")

    def scrub(value: Any) -> Any:
        if isinstance(value, dict):
            safe = {}
            for key, nested in value.items():
                lowered = str(key).casefold()
                compact = re.sub(r"[^a-z0-9]", "", lowered)
                if lowered.startswith("_") or any(token in compact for token in sensitive_tokens) or compact == "author":
                    continue
                safe[key] = scrub(nested)
            return safe
        if isinstance(value, list):
            return [scrub(item) for item in value]
        return value

    return scrub(raw)


def _read_sqlite(path: Path) -> list[dict[str, Any]]:
    uri = f"file:{quote(str(path.resolve()), safe='/')}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        columns = {row[1] for row in connection.execute("PRAGMA table_info(records)")}
        if not {"payload_json", "record_key"}.issubset(columns):
            raise ValueError(f"SQLite 缺少预期的 records 表字段：{path}")
        output = []
        for index, row in enumerate(connection.execute("SELECT record_key, payload_json FROM records ORDER BY rowid"), 1):
            try:
                payload = json.loads(row["payload_json"])
            except json.JSONDecodeError as exc:
                raise ValueError(f"SQLite 第 {index} 条 payload_json 无效：{path}") from exc
            if not isinstance(payload, dict):
                continue
            payload["_db_record_key"] = row["record_key"]
            output.append({"raw": payload, "source_file": str(path), "source_row": index})
        connection.close()
        return output
    except sqlite3.Error as exc:
        raise ValueError(f"无法只读解析 SQLite 文件 {path}: {exc}") from exc


def _read_csv(path: Path) -> list[dict[str, Any]]:
    error = None
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                reader = csv.DictReader(handle)
                return [{"raw": dict(row), "source_file": str(path), "source_row": index}
                        for index, row in enumerate(reader, 2)]
        except UnicodeDecodeError as exc:
            error = exc
    raise ValueError(f"无法识别 CSV 编码：{path} ({error})")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    output = []
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            for index, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"JSONL 第 {index} 行不是合法 JSON：{path}") from exc
                if isinstance(raw, dict):
                    output.append({"raw": raw, "source_file": str(path), "source_row": index})
    except UnicodeDecodeError as exc:
        raise ValueError(f"无法读取 JSONL 编码：{path}") from exc
    return output


def _resolve_input(path_value: str) -> tuple[Path, str]:
    path = Path(path_value).expanduser().resolve()
    if not path.exists():
        raise ValueError(f"输入不存在：{path}")
    if path.is_dir():
        candidates = [path / "records.sqlite3", path / "records.csv", path / "records.jsonl"]
        selected = next((item for item in candidates if item.is_file()), None)
        if selected is None:
            raise ValueError(f"目录中未发现 records.sqlite3、records.csv 或 records.jsonl：{path}")
        alternatives = [item.name for item in candidates if item.is_file() and item != selected]
        note = f"目录输入选择 {selected.name}"
        if alternatives:
            note += f"；未重复导入其他导出格式：{', '.join(alternatives)}"
        return selected, note
    if path.suffix.lower() in {".sqlite", ".sqlite3", ".db"}:
        return path, "SQLite 只读输入"
    if path.suffix.lower() == ".csv":
        return path, "CSV 输入"
    if path.suffix.lower() in {".jsonl", ".ndjson"}:
        return path, "JSONL 输入"
    raise ValueError(f"只支持 SQLite、CSV、JSONL 文件或任务目录：{path}")


def _load_path(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() in {".sqlite", ".sqlite3", ".db"}:
        return _read_sqlite(path)
    if path.suffix.lower() == ".csv":
        return _read_csv(path)
    return _read_jsonl(path)


def _read_context(data_path: Path, input_label: str) -> dict[str, Any]:
    parent = data_path.parent
    context: dict[str, Any] = {"input_file": input_label}
    manifest = parent / "task.json"
    report = parent / "last_run.json"
    if manifest.is_file():
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                context["task"] = {key: payload.get(key) for key in ("source", "queries", "subreddits", "target") if key in payload}
        except (OSError, json.JSONDecodeError):
            context["task_manifest_warning"] = "task.json 无法解析"
    if report.is_file():
        try:
            payload = json.loads(report.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                context["last_run"] = {key: payload.get(key) for key in ("status", "warnings", "errors", "coverage", "finished_at") if key in payload}
        except (OSError, json.JSONDecodeError):
            context["last_run_warning"] = "last_run.json 无法解析"
    return context


def _relation(source: str, content_type: str, parent_id: str, raw: dict[str, Any], metadata: dict[str, Any]) -> str:
    if content_type in CONTEXT_TYPES:
        return "context"
    if content_type in {"review", "rating", "user_review", "product_review"} or source in {"jd", "taobao"}:
        return "review"
    if content_type not in COMMENT_TYPES and content_type != "comment":
        return "unknown"
    explicit = _text(_first(raw, "is_reply", "reply")).casefold()
    if explicit in {"true", "yes", "1", "reply"}:
        return "reply"
    if explicit in {"false", "no", "0", "top_level", "top-level"}:
        return "top_level"
    depth = _text(_first(raw, "depth")).casefold()
    try:
        if depth and float(depth) > 0:
            return "reply"
        if depth and float(depth) == 0:
            return "top_level"
    except ValueError:
        pass
    comment_level = _text(_first(raw, "comment_level")) or _text(metadata.get("comment_level"))
    try:
        level = int(comment_level)
        if level <= 1:
            return "top_level"
        return "reply"
    except ValueError:
        pass
    parent = parent_id.casefold()
    if source in {"reddit", "reddit_opencli"}:
        if parent.startswith("t3_"):
            return "top_level"
        if parent.startswith("t1_") or parent.startswith("opencli_"):
            return "reply"
        return "unknown"
    if source in {"youtube", "xiaohongshu", "xhs", "douyin", "bilibili", "weibo", "zhihu", "tieba"}:
        return "reply" if parent else "top_level"
    if source == "kickstarter":
        return "reply" if parent else "unknown"
    if parent:
        return "unknown"
    return "unknown"


def _normalize_record(item: dict[str, Any]) -> dict[str, Any]:
    raw = item["raw"]
    metadata = _json_object(raw.get("metadata"))
    source = _text(_first(raw, "source", "platform", "channel", default="未知")).casefold() or "未知"
    content_type = _text(_first(raw, "content_type", "record_type", "type")).casefold()
    if not content_type:
        if any(key in raw for key in ("comment_text", "review_text", "review", "comment")):
            content_type = "comment"
        else:
            content_type = "unknown"
    comment_id = _text(_first(raw, "external_id", "comment_id", "review_id", "id"))
    parent_id = _text(_first(raw, "parent_id", "parent_comment_id", "reply_to"))
    body = _text(_first(raw, "body", "text_original", "text", "comment_text", "review_text", "review_content", "review", "comment", "content", "message"))
    title = _text(_first(raw, "title", "post_title", "video_title"))
    source_url = _text(_first(raw, "url", "source_url", "link", "permalink"))
    target_id = _text(_first(raw, "post_id", "note_id", "video_id", "item_id", "target_id", "thread_id", "product_id")) or source_url
    author_hash = _text(_first(raw, "author_hash", "anonymous_author_id", "author_hash_anon"))
    content_group = _relation(source, content_type, parent_id, raw, metadata)
    product_or_brand = _text(_first(raw, "product_or_brand", "brand", "product_name", "product")) or "未知"
    key_material = "|".join((source, content_type, comment_id, parent_id))
    analysis_key = _text(raw.get("_db_record_key")) or _stable(key_material if comment_id else f"{item['source_file']}|{item['source_row']}|{body}")
    raw_safe = _privacy_safe_fields(raw)
    return {
        "source": source,
        "content_type": content_type,
        "content_group": content_group,
        "comment_id": comment_id,
        "parent_id": parent_id,
        "published_at": _text(_first(raw, "published_at", "created_at", "date", "timestamp")),
        "captured_at": _text(_first(raw, "captured_at", "collected_at")),
        "text_original": body,
        "title_original": title,
        "is_included": "not_applicable" if content_group == "context" else "review" if content_group == "unknown" else "true",
        "exclusion_reason": "非评论上下文记录" if content_group == "context" else
                            "内容类型无法识别，待人工判断" if content_group == "unknown" else "",
        "duplicate_group_id": "",
        "duplicate_type": "none",
        "duplicate_count": 1,
        "duplicate_comment_ids_json": json.dumps([comment_id] if comment_id else [], ensure_ascii=False),
        "duplicate_author_ids_json": json.dumps([author_hash] if author_hash else [], ensure_ascii=False),
        "duplicate_author_missing_count": int(not bool(author_hash)),
        "product_or_brand": product_or_brand,
        "product_relevance": "unknown",
        "annotation_status": "not_applicable" if content_group == "context" else "rule_prelabel",
        "comment_intent": "其他",
        "experience_status": "无法判断",
        "topics": [],
        "pain_points": [],
        "user_scenario": [],
        "purchase_barrier": [],
        "sentiment": "无法判断",
        "severity_by_pain_point": {},
        "evidence_type": "无法判断",
        "confidence": "低",
        "evidence_note": "尚未分类",
        "analysis_record_key": analysis_key,
        "anonymous_author_id": author_hash,
        "source_url": source_url,
        "source_file": item["source_file"],
        "source_row": item["source_row"],
        "source_locations_json": json.dumps([f"{item['source_file']}#row={item['source_row']}"], ensure_ascii=False),
        "source_fields_json": json.dumps(raw_safe, ensure_ascii=False, sort_keys=True, default=str),
        "content_completeness": _text(raw.get("content_completeness")),
        "id_kind": _text(metadata.get("id_kind")),
        "score": _text(raw.get("score")),
        "rating": _text(raw.get("rating")),
        "reply_count": _text(raw.get("reply_count")),
        "metadata_json": json.dumps(metadata, ensure_ascii=False, sort_keys=True, default=str),
        "review_status": "内容类型无法识别" if content_group == "unknown" else
                         "产品关联与规则标签待人工复核" if content_group != "context" else "",
        "near_duplicate_similarity": "",
        "_raw": raw,
        "_metadata": metadata,
        "_target": target_id,
        "_norm_text": _normalized(body),
    }


def _dedupe_key(row: dict[str, Any]) -> tuple[str, str]:
    prefix = f"{row['source']}|{row['content_type']}"
    if row["comment_id"] and row["id_kind"] not in {"synthetic", "synthetic_order_dependent"}:
        return "id", f"{prefix}|{row['comment_id']}"
    if row["comment_id"] and row["_target"]:
        # 合成 ID 只在其帖子/商品上下文内比较，避免跨内容碰撞。
        return "synthetic_id", f"{prefix}|{row['comment_id']}|{row['_target']}"
    if row["anonymous_author_id"] and row["_norm_text"]:
        values = (prefix, row["comment_id"], row["_norm_text"], row["anonymous_author_id"], row["parent_id"], row["published_at"], row["_target"])
        return "fallback", "|".join(values)
    # 身份字段不足时先避免基于模糊条件合并；后续精确文本轮按帖子与父关系补充去重。
    return "raw", row["source_fields_json"]


def _deduplicate(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int, int]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[_dedupe_key(row)].append(row)
    output: list[dict[str, Any]] = []
    exact_extra = 0
    conflicts = 0
    for (method, key), group in groups.items():
        if len(group) == 1:
            output.append(group[0])
            continue
        group_id = _stable(f"{method}|{key}")
        texts = {row["text_original"] for row in group}
        parents = {row["parent_id"] for row in group}
        targets = {row["_target"] for row in group}
        if method in {"id", "synthetic_id"} and (len(texts) > 1 or len(parents) > 1 or len(targets) > 1):
            conflicts += len(group)
            for row in group:
                row["analysis_record_key"] = _stable(
                    f"{row['analysis_record_key']}|{row['source_file']}|{row['source_row']}"
                )
                row["duplicate_group_id"] = group_id
                row["duplicate_type"] = "id_conflict"
                row["is_included"] = "review" if row["content_group"] != "context" else "not_applicable"
                row["exclusion_reason"] = "同一来源与评论 ID 对应不同正文或父关系，待复核"
                row["review_status"] = "同 ID 内容冲突"
                row["duplicate_count"] = len(group)
            output.extend(group)
            continue
        representative = _merge_duplicate_rows(
            group, group_id, "exact_id" if method in {"id", "synthetic_id"} else "exact_fallback"
        )
        exact_extra += representative["duplicate_count"] - 1
        output.append(representative)

    text_groups: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    untouched: list[dict[str, Any]] = []
    for row in output:
        if (row["content_type"] in COMMENT_TYPES and row["content_group"] != "context"
                and row["_target"] and row["text_original"]):
            text_groups[(row["source"], row["content_type"], row["_target"], row["parent_id"], row["text_original"])].append(row)
        else:
            untouched.append(row)
    for key, group in text_groups.items():
        if len(group) == 1:
            untouched.append(group[0])
            continue
        group_id = _stable("exact_text|" + "|".join(key))
        merged = _merge_duplicate_rows(group, group_id, "exact_text")
        exact_extra += merged["duplicate_count"] - 1
        untouched.append(merged)
    return untouched, exact_extra, conflicts


def _merge_duplicate_rows(group: list[dict[str, Any]], group_id: str, duplicate_type: str) -> dict[str, Any]:
    representative = max(group, key=lambda row: row["captured_at"])
    comment_ids = sorted({comment_id for row in group for comment_id in _row_comment_ids(row)})
    author_ids = sorted({author_id for row in group for author_id in _row_author_ids(row)})
    source_locations = sorted({location for row in group for location in _json_string_list(row["source_locations_json"])})
    representative["duplicate_group_id"] = group_id
    representative["duplicate_type"] = duplicate_type
    representative["duplicate_count"] = sum(int(row.get("duplicate_count", 1)) for row in group)
    representative["duplicate_comment_ids_json"] = json.dumps(comment_ids, ensure_ascii=False)
    representative["duplicate_author_ids_json"] = json.dumps(author_ids, ensure_ascii=False)
    representative["duplicate_author_missing_count"] = sum(_row_author_missing_count(row) for row in group)
    representative["source_locations_json"] = json.dumps(source_locations, ensure_ascii=False)
    return representative


def _contains(text: str, phrases: Iterable[str]) -> list[str]:
    return [phrase for phrase in phrases if phrase.casefold() in text]


def _classify(row: dict[str, Any]) -> None:
    text = row["_norm_text"]
    if row["content_group"] == "context":
        return
    if row["is_included"] == "review":
        return
    if not text:
        row["is_included"] = "false"
        row["exclusion_reason"] = "空评论正文"
        row["review_status"] = ""
        return
    ad_hits = _contains(text, AD_CUES)
    if ad_hits:
        row["is_included"] = "false"
        row["exclusion_reason"] = "明确广告或引流用语"
        row["evidence_note"] = "广告规则命中：" + ", ".join(ad_hits)
        return
    topic_hits = {name: _contains(text, phrases) for name, phrases in TOPIC_RULES.items()}
    topics = [name for name, hits in topic_hits.items() if hits]
    pain_signal = _contains(text, PAIN_CUES)
    pain_points = [name for name in topics if pain_signal]
    row["topics"] = topics
    row["pain_points"] = pain_points

    intent_hits = [(name, _contains(text, phrases)) for name, phrases in INTENT_CUES.items()]
    matched_intents = [(name, hits) for name, hits in intent_hits if hits]
    row["comment_intent"] = matched_intents[0][0] if matched_intents else "其他"

    experience = [(name, _contains(text, phrases)) for name, phrases in EXPERIENCE_CUES.items()]
    row["experience_status"] = next((name for name, hits in experience if hits), "无法判断")

    positive = _contains(text, POSITIVE_CUES)
    negative = _contains(text, NEGATIVE_CUES)
    if positive and negative:
        row["sentiment"] = "褒贬混合"
    elif positive:
        row["sentiment"] = "正面"
    elif negative:
        row["sentiment"] = "负面"
    elif len(text) >= 8:
        row["sentiment"] = "中性"
    else:
        row["sentiment"] = "无法判断"

    row["user_scenario"] = [name for name, phrases in SCENARIO_CUES.items() if _contains(text, phrases)]
    purchase_cues = _contains(text, INTENT_CUES["购买顾虑"])
    barrier_cues = _contains(text, PURCHASE_BARRIER_CUES)
    if barrier_cues:
        barrier_topics = [name for name in topics if name in {"价格与价值", "功能与性能", "易用性", "兼容性与连接", "续航与充电", "服务与履约"}]
        row["purchase_barrier"] = barrier_topics or ["购买顾虑（具体类别未识别）"]

    if pain_points:
        # 文本词典无法判断核心任务、频率和可替代方式，数值严重度必须经人工复核。
        row["severity_by_pain_point"] = {pain: "无法判断" for pain in pain_points}

    direct_hits = pain_signal + positive + negative + purchase_cues + barrier_cues + sum((hits for _, hits in matched_intents), [])
    row["evidence_type"] = "用户直接表达" if direct_hits else "合理推断" if topics or row["user_scenario"] else "无法判断"
    if direct_hits:
        # 词典命中能证明原文含有相关表达，但不能可靠判断反讽、指代和上下文。
        row["confidence"] = "中"
    elif topics or row["user_scenario"]:
        row["confidence"] = "中"
    else:
        row["confidence"] = "低"
    evidence_terms = list(dict.fromkeys(direct_hits + [hit for hits in topic_hits.values() for hit in hits]))
    row["evidence_note"] = "规则命中：" + (", ".join(evidence_terms[:12]) if evidence_terms else "未匹配到明确标签词")
    if row["confidence"] == "低" or row["content_group"] == "unknown":
        row["review_status"] = "语义或评论关系需人工复核"


def _annotation_value(value: str, field: str, key: str) -> Any:
    if field in {"topics", "pain_points", "user_scenario", "purchase_barrier"}:
        if not value.strip():
            return []
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"annotations 中 {key} 的 {field} 必须是 JSON 数组") from exc
        if not isinstance(parsed, list) or any(not isinstance(item, str) for item in parsed):
            raise ValueError(f"annotations 中 {key} 的 {field} 必须是字符串数组")
        return list(dict.fromkeys(parsed))
    if field == "severity_by_pain_point":
        if not value.strip():
            return {}
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"annotations 中 {key} 的严重度必须是 JSON 对象") from exc
        if not isinstance(parsed, dict):
            raise ValueError(f"annotations 中 {key} 的严重度必须是 JSON 对象")
        if any(not isinstance(label, str) or (score != "无法判断" and
                                               (isinstance(score, bool) or not isinstance(score, int) or not 1 <= score <= 5))
               for label, score in parsed.items()):
            raise ValueError(f"annotations 中 {key} 的严重度只接受 1–5 整数或“无法判断”")
        return parsed
    return value.strip()


def _apply_annotations(rows: list[dict[str, Any]], annotations_path: str | None) -> int:
    if not annotations_path:
        return 0
    path = Path(annotations_path).expanduser().resolve()
    by_key = {row["analysis_record_key"]: row for row in rows}
    if len(by_key) != len(rows):
        raise ValueError("分析记录键不唯一，无法安全匹配人工标注")
    seen: set[str] = set()
    reviewed_count = 0
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            required = {"analysis_record_key", "annotation_status"}
            if not reader.fieldnames or not required.issubset(reader.fieldnames):
                raise ValueError("--annotations CSV 必须包含 analysis_record_key 和 annotation_status 列")
            for source_row, annotation in enumerate(reader, 2):
                key = _text(annotation.get("analysis_record_key"))
                if not key:
                    raise ValueError(f"annotations 第 {source_row} 行缺少 analysis_record_key")
                if key in seen:
                    raise ValueError(f"annotations 存在重复 analysis_record_key：{key}")
                seen.add(key)
                if key not in by_key:
                    raise ValueError(f"annotations 中的记录键不属于当前输入：{key}")
                status = _text(annotation.get("annotation_status"))
                if status not in {"", "rule_prelabel", "unreviewed", "manual_reviewed"}:
                    raise ValueError(f"annotations 中 {key} 的 annotation_status 无效：{status}")
                if status != "manual_reviewed":
                    continue
                row = by_key[key]
                if row["content_group"] == "context":
                    raise ValueError(f"annotations 中 {key} 指向帖子/上下文记录，不能作为评论复核")
                relevance = _text(annotation.get("product_relevance"))
                if relevance not in {"related", "unrelated", "uncertain"}:
                    raise ValueError(f"annotations 中 {key} 的 product_relevance 必须为 related/unrelated/uncertain")
                for field in ANNOTATION_FIELDS:
                    if field not in (reader.fieldnames or ()) or annotation.get(field) is None:
                        continue
                    row[field] = _annotation_value(annotation.get(field, ""), field, key)
                row["annotation_status"] = "manual_reviewed"
                invalid_inclusion = row["is_included"] not in {"true", "false", "review", "not_applicable"}
                if invalid_inclusion:
                    raise ValueError(f"annotations 中 {key} 的 is_included 无效：{row['is_included']}")
                if row["confidence"] not in {"高", "中", "低", "无法判断", ""}:
                    raise ValueError(f"annotations 中 {key} 的 confidence 无效：{row['confidence']}")
                if not set(row["severity_by_pain_point"]).issubset(set(row["pain_points"])):
                    raise ValueError(f"annotations 中 {key} 的严重度标签必须对应 pain_points")
                if row["content_group"] not in {"top_level", "reply", "review", "unknown"}:
                    raise ValueError(f"annotations 中 {key} 的 content_group 无效：{row['content_group']}")
                if row["duplicate_type"] != "id_conflict":
                    row["review_status"] = ""
                reviewed_count += 1
    except OSError as exc:
        raise ValueError(f"无法读取 annotations 文件：{path} ({exc})") from exc
    return reviewed_count


def _ngrams(text: str, size: int = 3) -> set[str]:
    compact = re.sub(r"\s+", "", text)
    if len(compact) < size:
        return {compact} if compact else set()
    return {compact[index:index + size] for index in range(len(compact) - size + 1)}


def _near_duplicates(rows: list[dict[str, Any]], threshold: float) -> tuple[int, int, bool]:
    candidates = [index for index, row in enumerate(rows)
                  if row["is_included"] == "true" and row["content_group"] != "context"
                  and len(row["_norm_text"]) >= 12 and row["_target"]]
    buckets: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for index in candidates:
        row = rows[index]
        buckets[(row["source"], row["content_type"], row["_target"])].append(index)
    parent = {index: index for index in candidates}

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    comparisons = 0
    truncated = False
    for indices in buckets.values():
        if len(indices) < 2:
            continue
        for position, left in enumerate(indices):
            left_grams = _ngrams(rows[left]["_norm_text"])
            for right in indices[:position]:
                comparisons += 1
                if comparisons > MAX_NEAR_COMPARISONS:
                    truncated = True
                    break
                right_grams = _ngrams(rows[right]["_norm_text"])
                union_size = len(left_grams | right_grams)
                similarity = len(left_grams & right_grams) / union_size if union_size else 0.0
                if similarity >= threshold:
                    union(left, right)
                    for item in (rows[left], rows[right]):
                        current = float(item["near_duplicate_similarity"] or 0)
                        item["near_duplicate_similarity"] = f"{max(current, similarity):.3f}"
            if truncated:
                break
        if truncated:
            break

    clusters: dict[int, list[int]] = defaultdict(list)
    for index in candidates:
        clusters[find(index)].append(index)
    meaningful = [members for members in clusters.values() if len(members) > 1]
    for members in meaningful:
        cluster_id = _stable("near|" + "|".join(sorted(rows[index]["analysis_record_key"] for index in members)))
        for index in members:
            row = rows[index]
            row["duplicate_group_id"] = row["duplicate_group_id"] or cluster_id
            if row["duplicate_type"] == "none":
                row["duplicate_type"] = "near"
            row["review_status"] = "; ".join(filter(None, [row["review_status"], "高度相似评论簇，保留并建议复核"]))
    return len(meaningful), sum(len(members) for members in meaningful), truncated


def _reference(row: dict[str, Any]) -> str:
    return "; ".join(_references(row))


def _references(row: dict[str, Any]) -> list[str]:
    comment_ids = _row_comment_ids(row)
    if comment_ids:
        return [f"{row['source']}:{comment_id}" + (f" ({row['source_url']})" if row["source_url"] else "")
                for comment_id in comment_ids]
    return [f"{row['source_file']}#row={row['source_row']}"]


def _severity_level(median: float | None) -> str:
    if median is None:
        return "无法判断"
    if median < 1.8:
        return "低"
    if median < 2.6:
        return "中低"
    if median < 3.4:
        return "中"
    if median < 4.2:
        return "高"
    return "极高"


def _percent(numerator: int, denominator: int) -> float | None:
    return round(numerator * 100 / denominator, 1) if denominator else None


def _parse_absolute_date(value: Any) -> date | None:
    text = _text(value)
    match = re.fullmatch(
        r"(?P<date>\d{4}[-/]\d{1,2}[-/]\d{1,2})(?:(?:T| )(?P<time>\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:?\d{2})?))?",
        text,
    )
    if not match:
        return None
    normalized_date = match.group("date").replace("/", "-")
    try:
        parsed_date = date.fromisoformat(normalized_date)
        if match.group("time"):
            datetime.fromisoformat(f"{normalized_date}T{match.group('time').replace('Z', '+00:00')}")
    except ValueError:
        return None
    return parsed_date


def _valid_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if row["is_included"] == "true" and row["content_group"] != "context"]


def _scope_rows(rows: list[dict[str, Any]], analysis_scope: str) -> list[dict[str, Any]]:
    if analysis_scope == "all":
        return rows
    return [row for row in rows if row["annotation_status"] == "manual_reviewed"
            and row["product_relevance"] == "related"]


def _label_metrics(rows: list[dict[str, Any]], field: str, include_severity: bool = False) -> list[dict[str, Any]]:
    valid = _valid_rows(rows)
    sources = ["全部来源"] + sorted({row["source"] for row in valid})
    results = []
    for source_scope in sources:
        scoped = valid if source_scope == "全部来源" else [row for row in valid if row["source"] == source_scope]
        relations = sorted({row["content_group"] for row in scoped})
        for relation in relations:
            base = [row for row in scoped if row["content_group"] == relation]
            denominator = len(base)
            mentions: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in base:
                values = row[field] if isinstance(row[field], list) else []
                for label in set(values):
                    mentions[label].append(row)
            for label, matched in mentions.items():
                authors = {(row["source"], author_id) for row in matched for author_id in _row_author_ids(row)}
                target_values = {row["_target"] for row in matched if row["_target"]}
                detail = {
                    "source_scope": source_scope,
                    "content_group": relation,
                    "label": label,
                    "mention_count": len(matched),
                    "denominator": denominator,
                    "mention_rate_pct": _percent(len(matched), denominator),
                    "author_count": len(authors) if authors else None,
                    "author_id_missing_count": sum(_row_author_missing_count(row) for row in matched),
                    "source_coverage_count": len(target_values) if target_values else None,
                    "source_coverage_missing_count": sum(not row["_target"] for row in matched),
                    "evidence_ids": [reference for row in matched for reference in _references(row)],
                    "confidence_counts": dict(Counter(row["confidence"] for row in matched)),
                    "manual_confidence_counts": dict(Counter(row["confidence"] for row in matched
                                                              if row["annotation_status"] == "manual_reviewed")),
                    "manual_reviewed_count": sum(row["annotation_status"] == "manual_reviewed" for row in matched),
                    "rule_prelabel_count": sum(row["annotation_status"] != "manual_reviewed" for row in matched),
                }
                if include_severity:
                    scores = []
                    scenario_counts: Counter[str] = Counter()
                    for row in matched:
                        value = row["severity_by_pain_point"].get(label)
                        if isinstance(value, int):
                            scores.append(value)
                        scenario_counts.update(set(row["user_scenario"]))
                    high = sum(score >= 4 for score in scores)
                    detail.update({
                        "severity_median": statistics.median(scores) if scores else None,
                        "severity_level": _severity_level(statistics.median(scores) if scores else None),
                        "major_scenarios": [f"{name}（{count}条）" for name, count in scenario_counts.most_common(3)] or ["未识别"],
                        "product_implication": "待验证：回查证据确认该问题是否影响主要任务完成或效率。",
                        "severity_evaluable_count": len(scores),
                        "high_severity_count": high,
                        "high_severity_rate_pct": _percent(high, len(scores)),
                    })
                results.append(detail)
    return sorted(results, key=lambda row: (row["source_scope"] != "全部来源", row["source_scope"], -row["mention_count"], row["content_group"], row["label"]))


def _sentiment_metrics(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    valid = _valid_rows(rows)
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in valid:
        groups[(row["source"], row["content_group"])].append(row)
    output = []
    for (source, relation), group in sorted(groups.items()):
        counts = Counter(row["sentiment"] for row in group)
        for sentiment, count in sorted(counts.items()):
            output.append({"source": source, "content_group": relation, "sentiment": sentiment,
                           "count": count, "denominator": len(group), "rate_pct": _percent(count, len(group))})
    return output


def _experience_pain_metrics(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in _valid_rows(rows):
        groups[(row["source"], row["content_group"], row["experience_status"])].append(row)
    output = []
    for (source, relation, experience), group in sorted(groups.items()):
        mentions: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in group:
            for label in set(row["pain_points"]):
                mentions[label].append(row)
        for label, matched in mentions.items():
            scores = [row["severity_by_pain_point"][label] for row in matched
                      if isinstance(row["severity_by_pain_point"].get(label), int)]
            high = sum(score >= 4 for score in scores)
            authors = {author_id for row in matched for author_id in _row_author_ids(row)}
            output.append({
                "source": source,
                "content_group": relation,
                "experience_status": experience,
                "label": label,
                "mention_count": len(matched),
                "denominator": len(group),
                "mention_rate_pct": _percent(len(matched), len(group)),
                "author_count": len(authors) if authors else None,
                "severity_median": statistics.median(scores) if scores else None,
                "severity_level": _severity_level(statistics.median(scores) if scores else None),
                "severity_evaluable_count": len(scores),
                "high_severity_count": high,
                "high_severity_rate_pct": _percent(high, len(scores)),
                "evidence_ids": [reference for row in matched for reference in _references(row)],
                "manual_reviewed_count": sum(row["annotation_status"] == "manual_reviewed" for row in matched),
                "rule_prelabel_count": sum(row["annotation_status"] != "manual_reviewed" for row in matched),
            })
    return sorted(output, key=lambda row: (row["source"], row["content_group"], row["experience_status"],
                                           -row["mention_count"], row["label"]))


def _time_metrics(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    valid = _valid_rows(rows)
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in valid:
        parsed_date = _parse_absolute_date(row["published_at"])
        if parsed_date:
            groups[(row["source"], row["content_group"], parsed_date.strftime("%Y-%m"))].append(row)
    return [{"source": source, "content_group": relation, "month": month, "comment_count": len(group),
             "pain_mentions": sum(len(row["pain_points"]) for row in group)}
            for (source, relation, month), group in sorted(groups.items())]


def _coverage_summary(rows: list[dict[str, Any]], raw_count: int, raw_types: Counter[str], exact_duplicates: int, id_conflicts: int,
                      near_clusters: int, near_records: int, scan_truncated: bool, contexts: list[dict[str, Any]]) -> dict[str, Any]:
    valid = _valid_rows(rows)
    counts_by_relation = Counter(row["content_group"] for row in valid)
    source_counts = Counter(row["source"] for row in valid)
    exclusions = Counter(row["exclusion_reason"] for row in rows if row["is_included"] == "false")
    review_rows = [row for row in rows if row["is_included"] == "review" or bool(row["review_status"])]
    pending = len(review_rows)
    context_count = sum(row["content_group"] == "context" for row in rows)
    authors: dict[str, set[str]] = defaultdict(set)
    for row in valid:
        authors[row["source"]].update(_row_author_ids(row))
    time_ranges = {}
    for source in sorted(source_counts):
        source_rows = [row for row in valid if row["source"] == source]
        parsed_dates = [parsed for row in source_rows if (parsed := _parse_absolute_date(row["published_at"]))]
        time_ranges[source] = {
            "start": min(parsed_dates).isoformat() if parsed_dates else None,
            "end": max(parsed_dates).isoformat() if parsed_dates else None,
            "parsed_count": len(parsed_dates),
            "missing_count": sum(not row["published_at"] for row in source_rows),
            "unparsed_count": sum(bool(row["published_at"]) and _parse_absolute_date(row["published_at"]) is None
                                   for row in source_rows),
        }
    missing: dict[str, dict[str, int]] = {}
    parent_id_presence: dict[str, dict[str, int]] = {}
    for content_type in sorted(raw_types):
        group = [row for row in rows if row["content_type"] == content_type]
        fields = {"text_original": lambda row: bool(row["text_original"]),
                  "comment_id": lambda row: bool(row["comment_id"]),
                  "anonymous_author_id": lambda row: bool(row["anonymous_author_id"]),
                  "published_at": lambda row: bool(row["published_at"]),
                  "source_url": lambda row: bool(row["source_url"])}
        missing[content_type] = {name: sum(not predicate(row) for row in group) for name, predicate in fields.items()}
        if content_type in COMMENT_TYPES:
            parent_id_presence[content_type] = {
                "present": sum(bool(row["parent_id"]) for row in group),
                "empty": sum(not row["parent_id"] for row in group),
            }
    collection_status = [{
        "input_file": context.get("input_file"),
        "status": context.get("last_run", {}).get("status"),
        "coverage": context.get("last_run", {}).get("coverage"),
        "warnings": context.get("last_run", {}).get("warnings", []),
        "errors": context.get("last_run", {}).get("errors", []),
    } for context in contexts if context.get("last_run")]
    return {
        "raw_record_count": raw_count,
        "raw_record_count_by_content_type": dict(raw_types),
        "exact_duplicate_rows_removed": exact_duplicates,
        "same_id_conflict_records": id_conflicts,
        "near_duplicate_cluster_count": near_clusters,
        "near_duplicate_record_count": near_records,
        "near_duplicate_scan_truncated": scan_truncated,
        "excluded_comments_by_reason": dict(exclusions),
        "excluded_comment_count": sum(exclusions.values()),
        "pending_review_count": pending,
        "review_queue_included_in_N_count": sum(row["is_included"] == "true" for row in review_rows),
        "review_queue_not_included_in_N_count": sum(row["is_included"] != "true" for row in review_rows),
        "included_low_confidence_count": sum(row["confidence"] == "低" and row["is_included"] == "true" for row in rows),
        "same_id_conflict_not_included_count": sum(row["duplicate_type"] == "id_conflict" and row["is_included"] != "true"
                                                   for row in rows),
        "non_comment_context_records": context_count,
        "valid_deduplicated_comment_count": len(valid),
        "product_relevance_counts": dict(Counter(row["product_relevance"] for row in valid)),
        "manual_reviewed_valid_comment_count": sum(row["annotation_status"] == "manual_reviewed" for row in valid),
        "manual_review_coverage_rate_pct": _percent(sum(row["annotation_status"] == "manual_reviewed" for row in valid), len(valid)),
        "unreviewed_valid_comment_count": sum(row["annotation_status"] != "manual_reviewed" for row in valid),
        "N_by_content_group": dict(counts_by_relation),
        "valid_comments_by_source": dict(source_counts),
        "identifiable_authors_by_source": {source: len(values) for source, values in authors.items()},
        "time_range_by_source": time_ranges,
        "missing_fields_by_content_type": missing,
        "parent_id_presence_by_content_type": parent_id_presence,
        "collection_status_by_input": collection_status,
        "input_context": contexts,
        "analysis_engine": "local_rules_v1; no external model",
    }


def _escape_markdown(value: Any) -> str:
    if value is None:
        return "不可计算"
    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(_escape_markdown(value) for value in row) + " |")
    return "\n".join(lines)


def _quote_preview(value: str, limit: int = 64) -> str:
    value = re.sub(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", "[邮箱]", value, flags=re.I)
    value = re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", "[手机号]", value)
    value = re.sub(r"@[\w.-]{2,}", "[@用户]", value)
    value = re.sub(r"https?://\S+", "[链接]", value)
    return value[:limit]


def _opportunities(pain_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for item in pain_rows:
        if item["source_scope"] != "全部来源":
            continue
        severity = item.get("severity_median")
        if item.get("rule_prelabel_count", 0):
            evidence = f"含 {item['rule_prelabel_count']} 条规则预标注，需复核"
        else:
            confidence = item.get("manual_confidence_counts", {})
            evidence = "、".join(f"{level}{count}条" for level, count in sorted(confidence.items())) or "无法判断"
        output.append({
            "product_opportunity": f"验证{item['label']}问题的影响与可行改进方向",
            "user_problem": f"本数据集有 {item['mention_count']} 条{item['content_group']}评论提及该问题",
            "related_scenario": "、".join(item.get("major_scenarios", ["未识别，需人工复核"])),
            "product_implication": item.get("product_implication", "需人工结合证据确认"),
            "comment_count": item["mention_count"],
            "mention_rate_pct": item["mention_rate_pct"],
            "denominator": item["denominator"],
            "severity_median": severity,
            "severity_level": item.get("severity_level", "无法判断"),
            "evidence_confidence": evidence,
            "validation_method": "用情境访谈或任务测试验证问题是否复现及其对核心任务的影响",
            "suggested_metrics": "任务完成率、完成时长、问题复现率；按实际问题选择",
            "status": "规则候选，需人工复核" if item.get("rule_prelabel_count", 0) else "证据已复核，产品方向仍需验证",
            "evidence_ids": item["evidence_ids"],
        })
    return output


def _evidence_index(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    categories = (("pain_point", "pain_points"), ("topic", "topics"),
                  ("scenario", "user_scenario"), ("purchase_barrier", "purchase_barrier"))
    output = []
    for row in rows:
        for label_type, field in categories:
            labels = row[field] if isinstance(row[field], list) else []
            for label in sorted(set(labels)):
                output.append({
                    "label_type": label_type,
                    "label": label,
                    "source": row["source"],
                    "content_type": row["content_type"],
                    "content_group": row["content_group"],
                    "annotation_status": row["annotation_status"],
                    "product_relevance": row["product_relevance"],
                    "analysis_record_key": row["analysis_record_key"],
                    "comment_reference": _reference(row),
                    "evidence_preview": _quote_preview(row["text_original"], 120),
                    "source_url": row["source_url"],
                    "source_file": row["source_file"],
                    "source_row": row["source_row"],
                    "severity": row["severity_by_pain_point"].get(label, "") if label_type == "pain_point" else "",
                })
    return output


def _build_report(summary: dict[str, Any], pain_rows: list[dict[str, Any]], topic_rows: list[dict[str, Any]],
                  scenario_rows: list[dict[str, Any]], barrier_rows: list[dict[str, Any]], positive_rows: list[dict[str, Any]],
                  sentiment_rows: list[dict[str, Any]], time_rows: list[dict[str, Any]], experience_pain_rows: list[dict[str, Any]],
                  opportunities: list[dict[str, Any]],
                  review_rows: list[dict[str, Any]]) -> str:
    pain_overall = [row for row in pain_rows if row["source_scope"] == "全部来源"]
    ranked_signals = sorted(pain_overall, key=lambda row: (-row["mention_count"], row["label"]))[:5]
    if summary["analysis_scope"] == "verified-target":
        scope_note = "仅统计人工标记为 manual_reviewed 且 product_relevance=related 的评论。"
        report_class_label = "人工复核目标产品报告"
        label_note = "本报告纳入的分析标签来自人工复核；仍需结合样本覆盖限制解释。"
    else:
        scope_note = "统计全体有效去重评论，不按目标产品关联过滤；不能作为目标产品专属结论。规则标签只作探索性筛查。"
        report_class_label = ("探索性规则预标注报告" if summary["rule_prelabel_count_in_analysis_denominator"]
                              else "全体评论人工标注报告")
        label_note = "规则词典结果是预标注，不替代人工语境判断。"
    target = summary["analysis_target"]
    review_coverage = (f"{summary['manual_review_coverage_rate_pct']}%"
                       if summary["manual_review_coverage_rate_pct"] is not None else "不可计算")
    lines = ["# 评论清洗与量化分析报告", "", f"生成时间（本机）：{datetime.now().astimezone().isoformat(timespec='seconds')}",
             "", f"> 报告类型：{report_class_label}。分析目标：产品/品类 {target['product'] or '未指定'}；品牌 {target['brand'] or '未指定'}。{scope_note}",
             f"> {label_note} 提及率只描述本次输入数据。", "",
             "## 结论摘要", "",
             f"本次分析分母 N={summary['analysis_denominator_count']}；全体有效去重评论数为 {summary['valid_deduplicated_comment_count']}。",
             f"有效评论中的目标关联标记分布为 {json.dumps(summary['product_relevance_counts'], ensure_ascii=False)}；人工复核覆盖 {summary['manual_reviewed_valid_comment_count']}/{summary['valid_deduplicated_comment_count']} 条（{review_coverage}）。",
             "人工复核痛点（评论数靠前项）：" if summary["analysis_scope"] == "verified-target" else "规则筛查线索（非已验证痛点，评论数靠前项）："]
    if ranked_signals:
        lines.extend(["", _table(["标签", "评论数", "分母 N", "提及率", "人工复核/规则预标注数"], [
            [row["label"], row["mention_count"], row["denominator"], f"{row['mention_count']}/{row['denominator']} = {row['mention_rate_pct']}%",
             f"{row['manual_reviewed_count']} / {row['rule_prelabel_count']}"] for row in ranked_signals
        ])])
    if summary["analysis_scope"] == "all":
        lines.extend(["", "规则命中只用于定位复核对象；不能直接据此判断目标品牌用户的需求规模、严重程度或产品优先级。"])
    lines.extend(["", "## A. 数据清洗摘要", ""])
    lines.append(_table(["指标", "结果"], [
        ["分析目标", json.dumps(target, ensure_ascii=False)],
        ["分析范围/报告类型", f"{summary['analysis_scope']} / {report_class_label}"],
        ["原始记录数", summary["raw_record_count"]],
        ["精确重复冗余记录数", summary["exact_duplicate_rows_removed"]],
        ["相同 ID 冲突记录数", summary["same_id_conflict_records"]],
        ["近似重复簇/涉及记录", f"{summary['near_duplicate_cluster_count']} / {summary['near_duplicate_record_count']}"],
        ["原始记录类型分布", json.dumps(summary["raw_record_count_by_content_type"], ensure_ascii=False)],
        ["排除评论数（按原因）", json.dumps(summary["excluded_comments_by_reason"], ensure_ascii=False) or "0"],
        ["人工复核队列总数（计入 N / 未计入 N）", f"{summary['pending_review_count']}（{summary['review_queue_included_in_N_count']} / {summary['review_queue_not_included_in_N_count']}）"],
        ["低把握度且仍计入 N 的评论数", summary["included_low_confidence_count"]],
        ["同 ID 冲突且未计入 N 的记录数", summary["same_id_conflict_not_included_count"]],
        ["非评论上下文记录数", summary["non_comment_context_records"]],
        ["有效去重评论数", summary["valid_deduplicated_comment_count"]],
        ["本报告分析分母 N", summary["analysis_denominator_count"]],
        ["分析分母（按内容关系）", json.dumps(summary["analysis_denominator_by_content_group"], ensure_ascii=False)],
        ["目标产品关联标记分布", json.dumps(summary["product_relevance_counts"], ensure_ascii=False)],
        ["已应用人工标注行数", summary["manual_annotation_rows_applied"]],
        ["有效评论人工复核覆盖数/比例", f"{summary['manual_reviewed_valid_comment_count']}/{summary['valid_deduplicated_comment_count']} = {review_coverage}"],
        ["尚未人工复核的有效评论数", summary["unreviewed_valid_comment_count"]],
        ["分析分母中仍为规则预标注的评论数", summary["rule_prelabel_count_in_analysis_denominator"]],
        ["人工确认相关范围外的有效评论数", summary["verified_target_filtered_out_count"]],
        ["N（按内容关系）", json.dumps(summary["N_by_content_group"], ensure_ascii=False)],
        ["有效评论来源分布", json.dumps(summary["valid_comments_by_source"], ensure_ascii=False)],
        ["可识别作者数（按来源）", json.dumps(summary["identifiable_authors_by_source"], ensure_ascii=False)],
        ["来源/时间范围", json.dumps(summary["time_range_by_source"], ensure_ascii=False)],
        ["字段缺失数（按内容类型）", json.dumps(summary["missing_fields_by_content_type"], ensure_ascii=False)],
        ["评论 parent_id 有值/为空数", json.dumps(summary["parent_id_presence_by_content_type"], ensure_ascii=False)],
        ["采集状态与覆盖范围", json.dumps(summary["collection_status_by_input"], ensure_ascii=False)],
    ]))
    if summary["near_duplicate_scan_truncated"]:
        lines.extend(["", "近似重复比较达到本地安全上限，簇数量可能不完整。"])
    pain_heading = "## B. 人工复核痛点量化主表" if summary["analysis_scope"] == "verified-target" else "## B. 规则筛查线索量化表"
    lines.extend(["", pain_heading, ""])
    lines.append(_table(["内容关系", "痛点类型", "提及数", "提及率（分子/分母）", "作者数", "人工复核/规则预标注数", "严重程度中位数/等级", "4–5分/可评估数/占比", "来源覆盖数", "主要场景", "产品含义/验证方向", "证据 ID/位置（前8条）"], [
        [row["content_group"], row["label"], row["mention_count"], f"{row['mention_count']}/{row['denominator']} = {row['mention_rate_pct']}%",
         row["author_count"], f"{row['manual_reviewed_count']} / {row['rule_prelabel_count']}",
         f"{row.get('severity_median') if row.get('severity_median') is not None else '不可计算'} / {row.get('severity_level', '无法判断')}",
         f"{row.get('high_severity_count')}/{row.get('severity_evaluable_count')} = {row.get('high_severity_rate_pct')}%（可评估{row.get('severity_evaluable_count')}）" if row.get("severity_evaluable_count") else "不可计算",
         row["source_coverage_count"], ", ".join(row.get("major_scenarios", ["未识别"])), row.get("product_implication", "需人工结合证据确认"),
         ", ".join(row["evidence_ids"][:8])] for row in pain_overall
    ]))
    lines.extend(["", "严重程度只汇总人工给出的 1–5 分；规则预标注不自动打严重度分。报告表格展示每类最多 8 个引用；所有标签到评论的完整映射见 `evidence_index.csv`，痛点指标明细见 `pain_points.csv`。", "", "## C. 用户需求与场景", ""])
    lines.append("**主题规则命中（未复核项不等于真实需求）：**" if summary["analysis_scope"] == "all" else "**人工复核主题/需求：**")
    lines.append(_table(["来源范围", "内容关系", "主题", "评论数", "提及率", "作者数", "人工复核/规则预标注数", "证据 ID/位置（前8条）"], [
        [row["source_scope"], row["content_group"], row["label"], row["mention_count"],
         f"{row['mention_count']}/{row['denominator']} = {row['mention_rate_pct']}%", row["author_count"],
         f"{row['manual_reviewed_count']} / {row['rule_prelabel_count']}", ", ".join(row["evidence_ids"][:8])]
        for row in topic_rows if row["source_scope"] == "全部来源"
    ]))
    time_note = ("**时间口径：**仅使用可完整解析的绝对年月日；相对时间、无年份月日及带地区后缀的展示文本不推断。"
                 if time_rows else
                 "发布时间均无法解析为完整绝对日期；时间范围与月度趋势无法判断，不推断年份或具体日期。")
    lines.extend(["", "**场景（规则命中需复核）：**", _table(["内容关系", "场景", "评论数", "分母", "提及率", "作者数", "人工复核/规则预标注数"], [
        [row["content_group"], row["label"], row["mention_count"], row["denominator"], f"{row['mention_rate_pct']}%", row["author_count"],
         f"{row['manual_reviewed_count']} / {row['rule_prelabel_count']}"]
        for row in scenario_rows if row["source_scope"] == "全部来源"
    ]), "", "## D. 购买障碍与正向反馈", "", "**购买障碍（购买意向不自动计作障碍）：**", _table(["来源", "内容关系", "障碍", "评论数", "分母", "提及率", "人工复核/规则预标注数"], [
        [row["source_scope"], row["content_group"], row["label"], row["mention_count"], row["denominator"], f"{row['mention_rate_pct']}%",
         f"{row['manual_reviewed_count']} / {row['rule_prelabel_count']}"]
        for row in barrier_rows
    ]), "", "**正向反馈主题（占正面评论子集比例）：**", _table(["来源", "内容关系", "主题", "正向评论数", "分母", "占比", "人工复核/规则预标注数"], [
        [row["source_scope"], row["content_group"], row["label"], row["mention_count"], row["denominator"], f"{row['mention_rate_pct']}%",
         f"{row['manual_reviewed_count']} / {row['rule_prelabel_count']}"]
        for row in positive_rows
    ]), "", "## E. 趋势与分组比较", "", _table(["来源", "内容关系", "月份", "有效评论数", "痛点提及次数"], [
        [row["source"], row["content_group"], row["month"], row["comment_count"], row["pain_mentions"]] for row in time_rows
    ]), "", time_note, "", "**情绪分布（各来源内部）：**", _table(["来源", "内容关系", "倾向", "评论数", "分母", "占比"], [
        [row["source"], row["content_group"], row["sentiment"], row["count"], row["denominator"], f"{row['rate_pct']}%"] for row in sentiment_rows
    ]), "", "**按体验状态分组的痛点（标签复核状态见复核数）：**", _table(["来源", "内容关系", "体验状态", "痛点", "评论数", "分母", "提及率", "作者数", "人工复核/规则预标注数", "严重程度", "4–5分/可评估数", "证据 ID/位置（前8条）"], [
        [row["source"], row["content_group"], row["experience_status"], row["label"], row["mention_count"], row["denominator"],
         f"{row['mention_count']}/{row['denominator']} = {row['mention_rate_pct']}%", row["author_count"],
         f"{row['manual_reviewed_count']} / {row['rule_prelabel_count']}",
         f"{row['severity_median'] if row['severity_median'] is not None else '不可计算'} / {row['severity_level']}",
         f"{row['high_severity_count']}/{row['severity_evaluable_count']}" if row["severity_evaluable_count"] else "不可计算",
         ", ".join(row["evidence_ids"][:8])] for row in experience_pain_rows
    ]), "", "## F. 产品机会清单", "", _table(["产品机会", "数据中的问题", "关联场景", "待验证产品含义", "评论数/提及率", "严重程度", "证据把握度", "验证方式", "观察指标", "状态"], [
        [row["product_opportunity"], row["user_problem"], row["related_scenario"], row["product_implication"],
         f"{row['comment_count']}/{row['denominator']} = {row['mention_rate_pct']}%", f"{row['severity_median'] if row['severity_median'] is not None else '不可计算'} / {row['severity_level']}",
         row["evidence_confidence"], row["validation_method"], row["suggested_metrics"], row["status"]] for row in opportunities
    ]), "", "产品机会按评论提及数列出以便筛查，不代表最终优先级；最终排序需结合证据质量、核心任务和产品定位复核，不计算无依据的加权分数。", "", "## 需要人工复核", ""])
    lines.append(_table(["评论 ID/位置", "来源", "内容关系", "把握度", "复核原因", "匿名短摘录"], [
        [_reference(row), row["source"], row["content_group"], row["confidence"], row["review_status"] or row["exclusion_reason"], _quote_preview(row["text_original"])]
        for row in review_rows
    ]))
    lines.extend(["", f"复核队列共 {len(review_rows)} 条；完整清单见 `review_queue.csv`。", "", "## 限制", "",
                  "- 采集结果仅代表提供文件和本地可见记录，不代表平台全量或总体用户比例。",
                  "- 词典规则无法稳定识别反讽、上下文指代、隐含动机或复杂多主题表达；需复核低把握度和关键结论。",
                  "- 报告短摘录会遮盖常见邮箱、电话、@账号和链接；姓名等个人信息无法完全自动识别，分享前需人工检查。",
                  "- 作者数只在来源内按已有匿名标识计算；跨来源身份不关联。缺少发布时间、父关系或来源链接时，相关趋势/覆盖/分层不可计算。",
                  "- 顶层评论与回复分层沿用本仓库小红书 DOM 采集器的结构：根评论无 parent_id，嵌套回复保存父评论 ID；若数据来自不同采集实现，应复核该分层。",
                  "- 近似重复只在同来源、同内容类型和同帖子/商品范围内聚类；跨渠道转载可能漏检，疑似机器内容需要人工判断。",
                  "- 互动字段各平台含义不同，不作跨平台同尺度比较。", ""])
    return "\n".join(lines)


def _csv_safe(value: Any) -> Any:
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            output = {}
            for field in fields:
                value = row.get(field, "")
                if value is None:
                    value = "不可计算"
                if isinstance(value, (list, dict)):
                    value = json.dumps(value, ensure_ascii=False, sort_keys=True)
                output[field] = _csv_safe(value)
            writer.writerow(output)


def _write_workbook(path: Path, rows: list[dict[str, Any]], summary: dict[str, Any], pain_rows: list[dict[str, Any]],
                    review_rows: list[dict[str, Any]]) -> bool:
    try:
        from openpyxl import Workbook
    except ImportError:
        return False
    workbook = Workbook()

    def fill_sheet(name: str, headers: list[str], content: Iterable[Iterable[Any]]) -> None:
        sheet = workbook.create_sheet(name)
        sheet.append(headers)
        for values in content:
            sheet.append([_excel_safe(value) for value in values])
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions

    def _excel_safe(value: Any) -> Any:
        if value is None:
            return "不可计算"
        if isinstance(value, (list, dict)):
            value = json.dumps(value, ensure_ascii=False, sort_keys=True)
        if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
            return "'" + value
        return value

    detail = workbook.active
    detail.title = "清洗明细"
    detail.append(OUTPUT_FIELDS)
    for row in rows:
        detail.append([_excel_safe(row.get(field, "")) for field in OUTPUT_FIELDS])
    detail.freeze_panes = "A2"
    detail.auto_filter.ref = detail.dimensions
    fill_sheet("数据摘要", ["指标", "结果"], ((key, json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value)
                                                  for key, value in summary.items()))
    pain_fields = ["source_scope", "content_group", "label", "mention_count", "denominator", "mention_rate_pct",
                   "author_count", "source_coverage_count", "manual_reviewed_count", "rule_prelabel_count",
                   "severity_median", "severity_level", "severity_evaluable_count", "high_severity_count",
                   "high_severity_rate_pct", "major_scenarios", "product_implication", "evidence_ids"]
    fill_sheet("痛点统计", pain_fields, ([row.get(field) for field in pain_fields] for row in pain_rows))
    fill_sheet("待复核", ["analysis_record_key", "comment_id", "source", "content_group", "source_file", "source_row", "annotation_status", "product_relevance", "confidence", "review_status", "text_original"],
               ([row.get(field) for field in ("analysis_record_key", "comment_id", "source", "content_group", "source_file", "source_row", "annotation_status", "product_relevance", "confidence", "review_status", "text_original")]
                for row in review_rows))
    table_specs = [
        ("主题需求", "topics", ["source_scope", "content_group", "label", "mention_count", "denominator", "mention_rate_pct", "author_count", "manual_reviewed_count", "rule_prelabel_count", "evidence_ids"]),
        ("使用场景", "scenarios", ["source_scope", "content_group", "label", "mention_count", "denominator", "mention_rate_pct", "author_count", "manual_reviewed_count", "rule_prelabel_count", "evidence_ids"]),
        ("购买障碍", "purchase_barriers", ["source_scope", "content_group", "label", "mention_count", "denominator", "mention_rate_pct", "author_count", "manual_reviewed_count", "rule_prelabel_count", "evidence_ids"]),
        ("正向反馈", "positive_topics", ["source_scope", "content_group", "label", "mention_count", "denominator", "mention_rate_pct", "author_count", "manual_reviewed_count", "rule_prelabel_count", "evidence_ids"]),
        ("情绪分布", "sentiment", ["source", "content_group", "sentiment", "count", "denominator", "rate_pct"]),
        ("月度趋势", "monthly_trends", ["source", "content_group", "month", "comment_count", "pain_mentions"]),
        ("体验状态痛点", "pain_points_by_experience", ["source", "content_group", "experience_status", "label", "mention_count", "denominator", "mention_rate_pct", "author_count", "manual_reviewed_count", "rule_prelabel_count", "severity_median", "severity_level", "severity_evaluable_count", "high_severity_count", "high_severity_rate_pct", "evidence_ids"]),
        ("产品机会", "opportunities", ["product_opportunity", "user_problem", "related_scenario", "product_implication", "comment_count", "denominator", "mention_rate_pct", "severity_median", "severity_level", "evidence_confidence", "validation_method", "suggested_metrics", "status", "evidence_ids"]),
    ]
    for sheet_name, summary_key, fields in table_specs:
        records = summary.get(summary_key, [])
        fill_sheet(sheet_name, fields, ([record.get(field) for field in fields] for record in records))
    workbook.save(path)
    return True


def run_analysis(input_values: list[str], output_value: str, product: str = "", brand: str = "",
                 near_duplicate_threshold: float = 0.9, annotations_path: str | None = None,
                 analysis_scope: str = "all") -> dict[str, Any]:
    if not 0.5 <= near_duplicate_threshold <= 1:
        raise ValueError("近似重复阈值必须在 0.5 到 1 之间")
    if analysis_scope not in {"all", "verified-target"}:
        raise ValueError("分析范围必须是 all 或 verified-target")
    if analysis_scope == "verified-target":
        if not annotations_path:
            raise ValueError("verified-target 范围需要 --annotations 人工复核文件")
        if not product and not brand:
            raise ValueError("verified-target 范围需要 --product 或 --brand 作为分析目标")
    if not input_values:
        raise ValueError("至少指定一个 --input")
    resolved: list[tuple[Path, str]] = []
    seen_paths: set[Path] = set()
    seen_task_dirs: set[Path] = set()
    input_notes = []
    contexts = []
    for value in input_values:
        path, note = _resolve_input(value)
        if path in seen_paths:
            continue
        if path.name in {"records.sqlite3", "records.csv", "records.jsonl"} and path.parent in seen_task_dirs:
            raise ValueError(f"同一任务目录只能选择一种记录格式，避免重复导入：{path.parent.name}")
        seen_paths.add(path)
        if path.name in {"records.sqlite3", "records.csv", "records.jsonl"}:
            seen_task_dirs.add(path.parent)
        resolved.append((path, note))
        input_label = f"input-{len(resolved)}/{path.name}"
        input_notes.append(f"{input_label}: {note}")
        contexts.append(_read_context(path, input_label))
    output_dir = Path(output_value).expanduser().resolve()
    for input_path, _ in resolved:
        if output_dir == input_path.parent or input_path.parent in output_dir.parents:
            raise ValueError("分析输出目录必须位于输入文件目录之外，避免混入或覆盖原始任务数据")
    if output_dir.exists() and not output_dir.is_dir():
        raise ValueError("输出路径必须是目录，且不能是输入文件")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError("输出目录必须为空；请使用新的目录，不会覆盖旧结果")

    loaded = []
    for index, (path, _) in enumerate(resolved, 1):
        items = _load_path(path)
        for item in items:
            item["source_file"] = f"input-{index}/{path.name}"
        loaded.extend(items)
    raw_count = len(loaded)
    rows = [_normalize_record(item) for item in loaded]
    raw_types = Counter(row["content_type"] for row in rows)
    rows, exact_duplicates, id_conflicts = _deduplicate(rows)
    for row in rows:
        _classify(row)
    annotation_reviewed_count = _apply_annotations(rows, annotations_path)
    near_clusters, near_records, scan_truncated = _near_duplicates(rows, near_duplicate_threshold)

    analysis_rows = _scope_rows(rows, analysis_scope)
    analysis_valid = _valid_rows(analysis_rows)
    pain_rows = _label_metrics(analysis_rows, "pain_points", include_severity=True)
    topic_rows = _label_metrics(analysis_rows, "topics")
    scenario_rows = _label_metrics(analysis_rows, "user_scenario")
    barrier_rows = _label_metrics(analysis_rows, "purchase_barrier")
    positive_rows = _label_metrics([row for row in analysis_valid if row["sentiment"] == "正面"], "topics")
    sentiment_rows = _sentiment_metrics(analysis_rows)
    time_rows = _time_metrics(analysis_rows)
    opportunities = _opportunities(pain_rows)
    experience_pain_rows = _experience_pain_metrics(analysis_rows)
    review_rows = [row for row in rows if row["is_included"] == "review" or row["review_status"]]
    evidence_rows = _evidence_index(analysis_valid)
    summary = _coverage_summary(rows, raw_count, raw_types, exact_duplicates, id_conflicts, near_clusters, near_records,
                                scan_truncated, contexts)
    summary["input_selection_notes"] = input_notes
    summary["near_duplicate_threshold"] = near_duplicate_threshold
    summary["analysis_target"] = {"product": product, "brand": brand}
    summary["analysis_scope"] = analysis_scope
    summary["analysis_denominator_count"] = len(analysis_valid)
    summary["analysis_denominator_by_content_group"] = dict(Counter(row["content_group"] for row in analysis_valid))
    summary["manual_annotation_rows_applied"] = annotation_reviewed_count
    summary["verified_target_filtered_out_count"] = max(0, summary["valid_deduplicated_comment_count"] - len(analysis_valid))
    summary["rule_prelabel_count_in_analysis_denominator"] = sum(row["annotation_status"] != "manual_reviewed" for row in analysis_valid)
    summary["report_class"] = ("verified_target_human_reviewed" if analysis_scope == "verified-target" else
                               "exploratory_with_rule_prelabels" if summary["rule_prelabel_count_in_analysis_denominator"] else
                               "all_comments_with_manual_annotations")

    output_dir.mkdir(parents=True, exist_ok=True)
    cleaned_rows = [{field: row.get(field, "") for field in OUTPUT_FIELDS} for row in rows]
    _write_csv(output_dir / "cleaned_comments.csv", cleaned_rows, OUTPUT_FIELDS)
    with (output_dir / "cleaned_comments.jsonl").open("w", encoding="utf-8") as handle:
        for row in cleaned_rows:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    pain_fields = ["source_scope", "content_group", "label", "mention_count", "denominator", "mention_rate_pct",
                   "author_count", "author_id_missing_count", "source_coverage_count", "source_coverage_missing_count",
                   "severity_median", "severity_level", "severity_evaluable_count", "high_severity_count", "high_severity_rate_pct",
                   "manual_reviewed_count", "rule_prelabel_count", "major_scenarios", "evidence_ids"]
    _write_csv(output_dir / "pain_points.csv", pain_rows, pain_fields)
    opportunity_fields = ["product_opportunity", "user_problem", "related_scenario", "product_implication", "comment_count", "mention_rate_pct",
                          "denominator", "severity_median", "severity_level", "evidence_confidence", "validation_method", "suggested_metrics", "status", "evidence_ids"]
    _write_csv(output_dir / "opportunities.csv", opportunities, opportunity_fields)
    review_fields = ["analysis_record_key", "comment_id", "source", "content_group", "source_file", "source_row",
                     "annotation_status", "product_relevance", "confidence", "review_status", "is_included",
                     "exclusion_reason", "duplicate_group_id", "duplicate_type", "text_original", "evidence_note"]
    _write_csv(output_dir / "review_queue.csv", review_rows, review_fields)
    evidence_fields = ["label_type", "label", "source", "content_type", "content_group", "annotation_status",
                       "product_relevance", "analysis_record_key", "comment_reference", "evidence_preview",
                       "source_url", "source_file", "source_row", "severity"]
    _write_csv(output_dir / "evidence_index.csv", evidence_rows, evidence_fields)
    summary.update({"pain_points": pain_rows, "topics": topic_rows, "scenarios": scenario_rows,
                    "purchase_barriers": barrier_rows, "positive_topics": positive_rows,
                    "sentiment": sentiment_rows, "monthly_trends": time_rows,
                    "pain_points_by_experience": experience_pain_rows, "opportunities": opportunities})
    (output_dir / "analysis_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    report = _build_report(summary, pain_rows, topic_rows, scenario_rows, barrier_rows, positive_rows,
                           sentiment_rows, time_rows, experience_pain_rows, opportunities, review_rows)
    (output_dir / "analysis_report.md").write_text(report, encoding="utf-8")
    workbook_created = _write_workbook(output_dir / "analysis_report.xlsx", cleaned_rows, summary, pain_rows, review_rows)
    return {"output_dir": str(output_dir), "raw_record_count": raw_count,
            "valid_deduplicated_comment_count": summary["valid_deduplicated_comment_count"],
            "analysis_denominator_count": summary["analysis_denominator_count"],
            "exact_duplicate_rows_removed": exact_duplicates, "near_duplicate_cluster_count": near_clusters,
            "pending_review_count": summary["pending_review_count"], "workbook_created": workbook_created,
             "analysis_engine": summary["analysis_engine"], "analysis_scope": analysis_scope,
            "report_class": summary["report_class"]}


def build_parser() -> Any:
    import argparse
    parser = argparse.ArgumentParser(prog="comment-crawler analyze", description="本地清洗并量化分析用户指定的评论文件")
    parser.add_argument("--input", "-i", action="append", required=True, help="SQLite、CSV、JSONL 文件或包含 records.* 的单个任务目录；可重复指定")
    parser.add_argument("--output", "-o", required=True, help="新的分析结果目录，不可覆盖输入或旧分析文件")
    parser.add_argument("--product", default="", help="分析目标产品/品类；不覆盖记录字段，也不自动过滤评论")
    parser.add_argument("--brand", default="", help="分析目标品牌；不覆盖记录字段，也不自动过滤评论")
    parser.add_argument("--near-duplicate-threshold", type=float, default=0.9, help="近似重复文本 Jaccard 阈值，默认 0.9")
    parser.add_argument("--annotations", help="人工复核 CSV；可直接使用并编辑此前输出的 cleaned_comments.csv")
    parser.add_argument("--scope", choices=("all", "verified-target"), default="all",
                        help="all 为全体有效评论探索；verified-target 仅统计人工确认相关的评论")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run_analysis(args.input, args.output, args.product, args.brand, args.near_duplicate_threshold,
                              args.annotations, args.scope)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result["workbook_created"]:
            print("未生成 XLSX；如需工作簿，请安装 analysis extra：pip install '.[analysis]'", file=sys.stderr)
        return 0
    except (OSError, ValueError, csv.Error) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
