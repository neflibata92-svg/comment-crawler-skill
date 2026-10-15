import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from comment_crawler.analysis import run_analysis


class AnalysisReviewTests(unittest.TestCase):
    def test_non_object_jsonl_fails_without_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "input").mkdir()
            source = root / "input" / "input.jsonl"
            source.write_text('{"source":"youtube","body":"valid"}\n[]\n', encoding="utf-8")
            output = root / "analysis"
            with self.assertRaisesRegex(ValueError, "第 2 行必须是对象"):
                run_analysis([str(source)], str(output))
            self.assertFalse(output.exists())

    def test_output_is_not_published_when_report_write_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "input").mkdir()
            source = root / "input" / "input.jsonl"
            self._write_jsonl(source, [{"source": "youtube", "content_type": "comment", "external_id": "c1", "body": "太贵"}])
            output = root / "analysis"
            with patch("comment_crawler.analysis._build_report", side_effect=RuntimeError("report failed")):
                with self.assertRaisesRegex(RuntimeError, "report failed"):
                    run_analysis([str(source)], str(output))
            self.assertFalse(output.exists())
            self.assertEqual(list(root.glob(".analysis.*")), [])

    def test_opportunity_review_requires_current_evidence_and_complete_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "input").mkdir()
            source = root / "input" / "input.jsonl"
            self._write_jsonl(source, [{"source": "youtube", "content_type": "comment", "external_id": "c1", "body": "价格太贵"}])
            first = root / "first"
            run_analysis([str(source)], str(first))
            review = first / "opportunities.csv"
            rows = self._read_csv(review)
            self.assertTrue(rows)
            for row in rows:
                row.update(product_opportunity="评估价格方案", product_implication="价格可能阻碍购买，待验证",
                           validation_method="访谈价格决策", suggested_metrics="购买放弃率")
            with review.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)
            final = root / "final"
            result = run_analysis([str(source)], str(final), opportunity_review_path=str(review))
            self.assertEqual(result["raw_record_count"], 1)
            self.assertEqual(self._read_summary(final / "analysis_summary.json")["manual_opportunity_rows_applied"], len(rows))

    def _write_jsonl(self, path, rows):
        path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")

    def _read_csv(self, path):
        with path.open(encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))

    def _read_summary(self, path):
        return json.loads(path.read_text(encoding="utf-8"))

    def test_target_arguments_do_not_overwrite_record_product(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_dir = root / "input"
            input_dir.mkdir()
            source = input_dir / "comments.jsonl"
            output = root / "analysis"
            self._write_jsonl(source, [{
                "source": "xiaohongshu",
                "content_type": "comment",
                "external_id": "c-1",
                "body": "这个产品不方便",
                "product_or_brand": "OtherBrand",
                "author_hash": "anon-1",
            }])

            run_analysis([str(source)], str(output), product="AI眼镜", brand="MemoMind")

            row = self._read_csv(output / "cleaned_comments.csv")[0]
            summary = self._read_summary(output / "analysis_summary.json")
            self.assertEqual(row["product_or_brand"], "OtherBrand")
            self.assertEqual(row["product_relevance"], "unknown")
            self.assertEqual(row["annotation_status"], "rule_prelabel")
            self.assertEqual(summary["analysis_target"], {"product": "AI眼镜", "brand": "MemoMind"})

    def test_verified_target_scope_uses_only_human_reviewed_relevant_rows(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_dir = root / "input"
            input_dir.mkdir()
            source = input_dir / "comments.jsonl"
            first_output = root / "first"
            annotations = first_output / "cleaned_comments.csv"
            final_output = root / "verified"
            self._write_jsonl(source, [
                {"source": "xiaohongshu", "content_type": "comment", "external_id": "c-1",
                 "body": "我用了这个产品，翻译经常失败，会议任务无法完成", "author_hash": "anon-1"},
                {"source": "xiaohongshu", "content_type": "comment", "external_id": "c-2",
                 "body": "我买了另一个品牌的眼镜", "author_hash": "anon-2"},
                {"source": "xiaohongshu", "content_type": "comment", "external_id": "c-3",
                 "body": "这条评论尚未人工复核", "author_hash": "anon-3"},
            ])
            run_analysis([str(source)], str(first_output), product="AI眼镜", brand="MemoMind")
            initial_rows = self._read_csv(first_output / "cleaned_comments.csv")
            with annotations.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=initial_rows[0].keys())
                writer.writeheader()
                for row, relevance in zip(initial_rows, ("related", "unrelated")):
                    row.update({
                        "annotation_status": "manual_reviewed", "product_relevance": relevance,
                        "is_included": "true", "comment_intent": "使用反馈", "experience_status": "实际使用",
                        "topics": '["功能与性能"]' if relevance == "related" else "[]",
                        "pain_points": '["功能与性能"]' if relevance == "related" else "[]",
                        "user_scenario": '["工作/办公"]' if relevance == "related" else "[]",
                        "purchase_barrier": "[]", "sentiment": "负面" if relevance == "related" else "中性",
                        "severity_by_pain_point": '{"功能与性能": 4}' if relevance == "related" else "{}",
                        "evidence_type": "用户直接表达", "confidence": "高", "evidence_note": "人工逐条复核",
                    })
                writer.writerows(initial_rows)

            result = run_analysis(
                [str(source)], str(final_output), product="AI眼镜", brand="MemoMind",
                annotations_path=str(annotations), analysis_scope="verified-target",
            )

            summary = self._read_summary(final_output / "analysis_summary.json")
            pain_rows = [row for row in self._read_csv(final_output / "pain_points.csv")
                         if row["source_scope"] == "全部来源"]
            self.assertEqual(result["analysis_denominator_count"], 1)
            self.assertEqual(summary["valid_deduplicated_comment_count"], 3)
            self.assertEqual(summary["analysis_denominator_count"], 1)
            self.assertEqual(summary["product_relevance_counts"], {"related": 1, "unrelated": 1, "unknown": 1})
            self.assertEqual(len(pain_rows), 1)
            self.assertEqual(pain_rows[0]["label"], "功能与性能")
            self.assertEqual(pain_rows[0]["denominator"], "1")
            self.assertEqual(pain_rows[0]["severity_median"], "4")
            self.assertEqual(pain_rows[0]["manual_reviewed_count"], "1")
            self.assertEqual(pain_rows[0]["rule_prelabel_count"], "0")
            self.assertEqual(summary["report_class"], "verified_target_human_reviewed")
            self.assertIn("人工复核目标产品报告", (final_output / "analysis_report.md").read_text(encoding="utf-8"))
            evidence = self._read_csv(final_output / "evidence_index.csv")
            self.assertTrue(evidence)
            self.assertTrue(all(item["analysis_record_key"] == initial_rows[0]["analysis_record_key"]
                                for item in evidence))

    def test_verified_target_scope_requires_annotations_and_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_dir = root / "input"
            input_dir.mkdir()
            source = input_dir / "comments.jsonl"
            self._write_jsonl(source, [{"source": "xiaohongshu", "content_type": "comment", "external_id": "c-1", "body": "comment"}])
            with self.assertRaisesRegex(ValueError, "--annotations"):
                run_analysis([str(source)], str(root / "no-annotations"), analysis_scope="verified-target")

    def test_verified_target_scope_requires_analysis_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_dir = root / "input"
            input_dir.mkdir()
            source = input_dir / "comments.jsonl"
            annotations = root / "annotations.csv"
            self._write_jsonl(source, [{"source": "xiaohongshu", "content_type": "comment", "external_id": "c-1", "body": "comment"}])
            annotations.write_text("analysis_record_key,annotation_status,product_relevance\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "--product 或 --brand"):
                run_analysis([str(source)], str(root / "no-target"), annotations_path=str(annotations),
                             analysis_scope="verified-target")

    def test_annotations_with_unmatched_key_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_dir = root / "input"
            input_dir.mkdir()
            source = input_dir / "comments.jsonl"
            first_output = root / "first"
            annotations = root / "annotations.csv"
            self._write_jsonl(source, [{"source": "xiaohongshu", "content_type": "comment", "external_id": "c-1", "body": "comment"}])
            run_analysis([str(source)], str(first_output))
            annotations.write_text(
                "analysis_record_key,annotation_status,product_relevance\nwrong-key,manual_reviewed,related\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "不属于当前输入"):
                run_analysis([str(source)], str(root / "final"), annotations_path=str(annotations))

    def test_context_only_input_has_no_comment_denominator(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_dir = root / "input"
            input_dir.mkdir()
            source = input_dir / "comments.jsonl"
            output = root / "analysis"
            self._write_jsonl(source, [{
                "source": "xiaohongshu", "content_type": "post", "external_id": "p-1", "body": "帖子正文",
            }])

            run_analysis([str(source)], str(output))

            summary = self._read_summary(output / "analysis_summary.json")
            report = (output / "analysis_report.md").read_text(encoding="utf-8")
            self.assertEqual(summary["analysis_denominator_count"], 0)
            self.assertIsNone(summary["manual_review_coverage_rate_pct"])
            self.assertNotIn("None%", report)
            self.assertEqual(self._read_csv(output / "evidence_index.csv"), [])

    def test_rule_prelabels_do_not_claim_a_numeric_severity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_dir = root / "input"
            input_dir.mkdir()
            source = input_dir / "comments.jsonl"
            output = root / "analysis"
            self._write_jsonl(source, [{
                "source": "xiaohongshu", "content_type": "comment", "external_id": "c-1",
                "body": "这个功能用起来不方便", "author_hash": "anon-1",
            }])

            run_analysis([str(source)], str(output))

            row = self._read_csv(output / "cleaned_comments.csv")[0]
            pain_rows = self._read_csv(output / "pain_points.csv")
            report = (output / "analysis_report.md").read_text(encoding="utf-8")
            severity_by_pain_point = json.loads(row["severity_by_pain_point"])
            self.assertIn("易用性", severity_by_pain_point)
            self.assertTrue(all(score == "无法判断" for score in severity_by_pain_point.values()))
            self.assertEqual(pain_rows[0]["severity_evaluable_count"], "0")
            self.assertEqual(pain_rows[0]["severity_median"], "不可计算")
            self.assertIn("探索性规则预标注报告", report)
            self.assertIn("规则筛查线索量化表", report)
            self.assertIn("evidence_index.csv", report)

    def test_purchase_intent_alone_is_not_a_purchase_barrier(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_dir = root / "input"
            input_dir.mkdir()
            source = input_dir / "comments.jsonl"
            output = root / "analysis"
            self._write_jsonl(source, [{
                "source": "xiaohongshu", "content_type": "comment", "external_id": "c-1",
                "body": "我想买这款", "author_hash": "anon-1",
            }])

            run_analysis([str(source)], str(output))

            row = self._read_csv(output / "cleaned_comments.csv")[0]
            self.assertEqual(row["comment_intent"], "购买意向")
            self.assertEqual(row["purchase_barrier"], "[]")


if __name__ == "__main__":
    unittest.main()
