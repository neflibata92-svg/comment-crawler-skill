import json
import tempfile
import unittest
import subprocess
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

from comment_crawler.collectors.mediacrawler import (
    MEDIA_DOWNLOAD_ID_BATCH_SIZE, PLATFORMS, UNBOUNDED_UPSTREAM_COUNT,
    _import_exports, _matching_post_ids, _remove_unmatched_media,
    collect_mediacrawler, download_media_for_posts,
)
from comment_crawler.core.utils import CollectionResult
from comment_crawler.media_ocr import process_media_assets


class MediaCrawlerImportTests(unittest.TestCase):
    def _write_jsonl(self, path, rows):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")

    def _import_rows(self, root, rows, queries, comments=()):
        directory = root / "dy" / "jsonl"
        path = directory / "run_contents_0.jsonl"
        self._write_jsonl(path, rows)
        if comments:
            self._write_jsonl(directory / "run_comments_0.jsonl", comments)
        records = []
        result = CollectionResult("douyin")
        with patch("comment_crawler.collectors.mediacrawler.process_media_assets", return_value={
            "image_ocr_status": "not_applicable", "video_analysis": {"status": "not_applicable"},
        }):
            counts = _import_exports(
                "douyin", PLATFORMS["douyin"], root, records.append, result,
                queries=queries, media_request_status="not_requested",
                web_video_session=None, profile_directory=None,
            )
        return counts, records, result

    def test_import_has_no_fifteen_post_cap(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rows = [{"aweme_id": str(index), "title": "MemoMind camera review"} for index in range(23)]
            comments = [
                {"aweme_id": "0", "comment_id": f"c{index}", "content": f"Comment {index}"}
                for index in range(601)
            ]

            (counts, records, result) = self._import_rows(root, rows, ["MemoMind"], comments)

            self.assertEqual(counts, (23, 601))
            self.assertEqual(len(records), 624)
            self.assertFalse(any("上限" in warning for warning in result.warnings))

    def test_later_comment_version_replaces_earlier_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rows = [{"aweme_id": "post1", "title": "MemoMind review"}]
            comments = [
                {"aweme_id": "post1", "comment_id": "c1", "content": "old text"},
                {"aweme_id": "post1", "comment_id": "c1", "content": "new text"},
                {"aweme_id": "post1", "comment_id": "r1", "parent_comment_id": "c1", "content": "old reply"},
                {"aweme_id": "post1", "comment_id": "r1", "parent_comment_id": "c1", "content": "new reply"},
            ]
            counts, records, _ = self._import_rows(root, rows, ["MemoMind"], comments)
            self.assertEqual(counts, (1, 2))
            self.assertEqual([record.body for record in records[1:]], ["new text", "new reply"])

    def test_media_symlink_is_skipped_without_processing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outside = root / "outside"
            outside.mkdir()
            media_root = root / "dy" / "media"
            media_root.mkdir(parents=True)
            (media_root / "post1").symlink_to(outside, target_is_directory=True)
            counts, records, result = self._import_rows(root, [{"aweme_id": "post1", "title": "MemoMind"}], ["MemoMind"])
            self.assertEqual(counts, (0, 0))
            self.assertEqual(records, [])
            self.assertTrue(any("符号链接" in warning for warning in result.warnings))

    def test_nested_media_symlink_is_rejected_before_ocr(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            media = root / "dy" / "media" / "post1"
            media.mkdir(parents=True)
            external = root.parent / "external-image.jpg"
            (media / "image.jpg").symlink_to(external)
            with self.assertRaisesRegex(ValueError, "符号链接"):
                process_media_assets(media, root, "dy:post1", download_requested=False, request_status="not_requested")

    def test_search_results_also_need_a_keyword_hit_in_title_or_body(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rows = [
                {"aweme_id": "title", "title": "MEMOMIND camera"},
                {"aweme_id": "body", "desc": "A review of MemoMind for meetings"},
                {"aweme_id": "normalized", "title": "A MEMO   MIND camera review"},
                {"aweme_id": "cross-field", "title": "A MEMO", "desc": "MIND camera review"},
                {"aweme_id": "unrelated", "title": "Camera review", "desc": "Nothing relevant here"},
            ]

            (_, records, _) = self._import_rows(root, rows, ["  memomind  ", "memo\t  mind"])

            self.assertEqual([record.external_id for record in records], ["post:title", "post:body", "post:normalized"])

    def test_target_mode_without_search_queries_keeps_target_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rows = [{"aweme_id": "target", "title": "Post opened by exact URL"}]

            (_, records, _) = self._import_rows(root, rows, [])

            self.assertEqual([record.external_id for record in records], ["post:target"])

    def test_unmatched_duplicate_post_does_not_hide_later_keyword_match(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rows = [
                {"aweme_id": "same-post", "title": "Unrelated result"},
                {"aweme_id": "same-post", "title": "MemoMind review"},
            ]

            (_, records, _) = self._import_rows(root, rows, ["MemoMind"])

            self.assertEqual([record.external_id for record in records], ["post:same-post"])

    def test_upstream_post_count_sentinel_is_large(self):
        self.assertGreater(UNBOUNDED_UPSTREAM_COUNT, 15)

    def test_collection_passes_unbounded_sentinels_to_both_upstream_count_options(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "mediacrawler"
            home.mkdir()
            command = ["fixture", "-c", "code"]
            completed = subprocess.CompletedProcess(command, 0)
            with (
                patch("comment_crawler.collectors.mediacrawler._assert_prepared"),
                patch("comment_crawler.collectors.mediacrawler._build_command", return_value=command) as build_command,
                patch("comment_crawler.collectors.mediacrawler.subprocess.run", return_value=completed),
                patch("comment_crawler.web_video_analysis.WebVideoSession", return_value=nullcontext(None)),
                patch("comment_crawler.collectors.mediacrawler._import_exports", return_value=(0, 0)),
            ):
                result = collect_mediacrawler(
                    "douyin", {"mediacrawler_home": str(home), "queries": ["MemoMind"]}, root / "run", lambda _: None,
                )

            self.assertFalse(result.errors)
            upstream_args = build_command.call_args.args[1]
            self.assertEqual(
                upstream_args[upstream_args.index("--crawler_max_notes_count") + 1],
                str(UNBOUNDED_UPSTREAM_COUNT),
            )
            self.assertEqual(
                upstream_args[upstream_args.index("--max_comments_count_singlenotes") + 1],
                str(UNBOUNDED_UPSTREAM_COUNT),
            )

    def test_media_download_ids_are_filtered_by_post_keyword(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write_jsonl(root / "dy" / "jsonl" / "run_contents_0.jsonl", [
                {"aweme_id": "match-title", "title": "MemoMind review"},
                {"aweme_id": "match-body", "desc": "Reviewing MemoMind today"},
                {"aweme_id": "unrelated", "title": "Camera review"},
            ])

            post_ids = _matching_post_ids(root, PLATFORMS["douyin"], ["MemoMind"])

            self.assertEqual(post_ids, ["match-title", "match-body"])

    def test_media_download_batches_all_posts_without_a_total_cap(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "mediacrawler"
            home.mkdir()
            post_ids = [f"post-{index}" for index in range(205)]
            commands = []

            def build_command(_home, args, _delay, *, profile_directory=None):
                commands.append(args)
                return ["fixture", *args]

            with (
                patch("comment_crawler.collectors.mediacrawler._assert_prepared"),
                patch("comment_crawler.collectors.mediacrawler._media_download_support", return_value=(True, "requested")),
                patch("comment_crawler.collectors.mediacrawler._build_command", side_effect=build_command),
                patch("comment_crawler.collectors.mediacrawler.subprocess.run", return_value=subprocess.CompletedProcess([], 0)),
            ):
                result = download_media_for_posts("douyin", home, post_ids, root / "run", 0)

            batches = [args[args.index("--specified_id") + 1].split(",") for args in commands]
            self.assertEqual([len(batch) for batch in batches], [MEDIA_DOWNLOAD_ID_BATCH_SIZE] * 2 + [5])
            self.assertEqual([post_id for batch in batches for post_id in batch], post_ids)
            self.assertEqual(result["status"], "completed")

    def test_search_defers_media_download_until_after_matching_post_ids_are_known(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "mediacrawler"
            output = root / "run"
            home.mkdir()
            self._write_jsonl(output / ".mediacrawler" / "dy" / "jsonl" / "run_contents_0.jsonl", [
                {"aweme_id": "match", "title": "MemoMind review"},
                {"aweme_id": "unrelated", "title": "Camera review"},
            ])
            command = ["fixture", "-c", "code"]
            completed = subprocess.CompletedProcess(command, 0)
            with (
                patch("comment_crawler.collectors.mediacrawler._assert_prepared"),
                patch("comment_crawler.collectors.mediacrawler._media_download_support", return_value=(True, "requested")),
                patch("comment_crawler.collectors.mediacrawler._build_command", return_value=command) as build_command,
                patch("comment_crawler.collectors.mediacrawler.subprocess.run", return_value=completed),
                patch("comment_crawler.collectors.mediacrawler.download_media_for_posts", return_value={
                    "status": "completed", "download_requested": True, "return_code": 0,
                }) as download,
                patch("comment_crawler.web_video_analysis.WebVideoSession", return_value=nullcontext(None)),
                patch("comment_crawler.collectors.mediacrawler._import_exports", return_value=(1, 0)),
            ):
                result = collect_mediacrawler(
                    "douyin", {"mediacrawler_home": str(home), "queries": ["MemoMind"]}, output, lambda _: None,
                )

            upstream_args = build_command.call_args.args[1]
            self.assertEqual(upstream_args[upstream_args.index("--get_media") + 1], "false")
            self.assertEqual(download.call_args.args[2], ["match"])
            self.assertFalse(result.errors)

    def test_unmatched_candidate_media_from_older_runs_is_removed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rows = [
                {"aweme_id": "match", "title": "MemoMind review"},
                {"aweme_id": "unrelated", "title": "Camera review"},
            ]
            unmatched_media = root / "dy" / "media" / "unrelated"
            matched_media = root / "dy" / "media" / "match"
            unmatched_media.mkdir(parents=True)
            matched_media.mkdir()
            (unmatched_media / "image.jpg").write_bytes(b"fixture")
            (matched_media / "image.jpg").write_bytes(b"fixture")

            self._import_rows(root, rows, ["MemoMind"])

            self.assertFalse(unmatched_media.exists())
            self.assertTrue(matched_media.exists())

    def test_unmatched_media_cleanup_does_not_follow_task_root_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "run"
            output.mkdir()
            data_root = output / ".mediacrawler"
            external_root = root / "external"
            external_media = external_root / "dy" / "media" / "unrelated"
            external_media.mkdir(parents=True)
            external_file = external_media / "keep.txt"
            external_file.write_text("outside task root", encoding="utf-8")
            data_root.symlink_to(external_root, target_is_directory=True)
            result = CollectionResult("douyin")

            _remove_unmatched_media(data_root, "dy", {"unrelated"}, set(), result)

            self.assertTrue(external_file.is_file())
            self.assertTrue(any("符号链接" in warning for warning in result.warnings))


if __name__ == "__main__":
    unittest.main()
