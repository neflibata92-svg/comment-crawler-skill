import csv
import json
import tempfile
import unittest
from pathlib import Path

from comment_crawler.analysis import run_analysis


class ExactTextDedupeTests(unittest.TestCase):
    def _read_csv(self, path):
        with path.open(encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))

    def test_merges_exact_text_only_within_source_post_and_parent_context(self):
        rows = [
            {"source": "youtube", "content_type": "comment", "external_id": "c1", "post_id": "v1",
             "body": "MemoMind 经常断连，无法使用", "author_hash": "anon-1"},
            {"source": "youtube", "content_type": "comment", "external_id": "c2", "post_id": "v1",
             "body": "MemoMind 经常断连，无法使用", "author_hash": "anon-2"},
            {"source": "youtube", "content_type": "comment", "external_id": "c3", "post_id": "v2",
             "body": "MemoMind 经常断连，无法使用", "author_hash": "anon-3"},
            {"source": "youtube", "content_type": "comment", "external_id": "c4", "post_id": "v1",
             "parent_id": "root-2", "body": "MemoMind 经常断连，无法使用", "author_hash": "anon-4"},
            {"source": "youtube", "content_type": "comment", "external_id": "c5", "post_id": "v1",
             "body": "MemoMind 经常断连，无法使用！", "author_hash": "anon-5"},
            {"source": "reddit", "content_type": "comment", "external_id": "c6", "post_id": "v1",
             "parent_id": "t3_v1", "body": "MemoMind 经常断连，无法使用", "author_hash": "anon-6"},
        ]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_dir = root / "input"
            input_dir.mkdir()
            input_file = input_dir / "comments.jsonl"
            input_file.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
            output = root / "analysis"

            summary = run_analysis([str(input_file)], str(output))

            cleaned = self._read_csv(output / "cleaned_comments.csv")
            merged = next(row for row in cleaned if row["duplicate_count"] == "2")
            self.assertEqual(summary["raw_record_count"], 6)
            self.assertEqual(summary["valid_deduplicated_comment_count"], 5)
            self.assertEqual(summary["exact_duplicate_rows_removed"], 1)
            self.assertEqual(json.loads(merged["duplicate_comment_ids_json"]), ["c1", "c2"])
            self.assertEqual(json.loads(merged["duplicate_author_ids_json"]), ["anon-1", "anon-2"])
            pain_rows = [row for row in self._read_csv(output / "pain_points.csv")
                         if row["source_scope"] == "全部来源" and row["label"] == "稳定性与质量"]
            top_level = next(row for row in pain_rows if row["content_group"] == "top_level")
            reply = next(row for row in pain_rows if row["content_group"] == "reply")
            self.assertEqual(top_level["mention_count"], "4")
            self.assertEqual(top_level["author_count"], "5")
            self.assertEqual(reply["mention_count"], "1")
            self.assertEqual(reply["author_count"], "1")
            evidence = self._read_csv(output / "evidence_index.csv")
            references = " ".join(row["comment_reference"] for row in evidence)
            self.assertIn("youtube:c1", references)
            self.assertIn("youtube:c2", references)

    def test_markdown_review_queue_does_not_truncate_rows(self):
        rows = [
            {"source": "youtube", "content_type": "comment", "external_id": f"c{index}",
             "post_id": f"v{index}", "body": f"Unclassified comment {index}"}
            for index in range(101)
        ]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_dir = root / "input"
            input_dir.mkdir()
            input_file = input_dir / "comments.jsonl"
            input_file.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            output = root / "analysis"

            run_analysis([str(input_file)], str(output))

            report = (output / "analysis_report.md").read_text(encoding="utf-8")
            self.assertIn("youtube:c100", report)


if __name__ == "__main__":
    unittest.main()
