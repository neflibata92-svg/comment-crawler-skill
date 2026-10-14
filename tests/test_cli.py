import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from comment_crawler.cli import main, parser
from comment_crawler.core.schema import ReviewRecord
from comment_crawler.core.storage import ReviewStore
from comment_crawler.core.utils import CollectionResult


class CliTests(unittest.TestCase):
    def test_mediacrawler_no_longer_exposes_a_post_count_cap(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                parser().parse_args(['collect', 'douyin', '--query', 'camera', '--max-posts', '15', '--output', './run'])

    def test_xiaohongshu_query_and_target_dry_run_require_profile(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['collect', 'xiaohongshu', '--query', '相机', '--profile', tmp,
                                   '--output', str(Path(tmp) / 'query'), '--dry-run']), 0)
            self.assertEqual(main(['collect', 'xiaohongshu', '--target',
                                   'https://www.xiaohongshu.com/explore/0123456789abcdef01234567?xsec_token=secret',
                                   '--profile', tmp, '--output', str(Path(tmp) / 'note'), '--dry-run']), 0)
            self.assertFalse((Path(tmp) / 'query').exists())
            self.assertEqual(main(['collect', 'xiaohongshu', '--query', '相机',
                                   '--output', str(Path(tmp) / 'missing'), '--dry-run']), 1)

    def test_refresh_completed_is_passed_to_xiaohongshu_collector(self):
        captured = {}
        def collect(source, config, output, emit):
            captured.update(config)
            return CollectionResult(source)
        with tempfile.TemporaryDirectory() as tmp, patch('comment_crawler.cli.dispatch', collect), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['collect', 'xiaohongshu', '--query', 'memomind', '--profile', tmp,
                                   '--output', str(Path(tmp) / 'run'), '--refresh-completed']), 0)
        self.assertTrue(captured['refresh_completed'])

    def test_xiaohongshu_task_manifest_does_not_store_signed_token(self):
        def collect(source, config, output, emit):
            return CollectionResult(source)
        with tempfile.TemporaryDirectory() as tmp, patch('comment_crawler.cli.dispatch', collect), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['collect', 'xiaohongshu', '--target',
                                   'https://www.xiaohongshu.com/explore/0123456789abcdef01234567?xsec_token=secret',
                                   '--profile', tmp, '--output', str(Path(tmp) / 'note')]), 0)
            self.assertNotIn('secret', (Path(tmp) / 'note' / 'task.json').read_text())

    def test_browser_profile_inside_repository_is_rejected_for_collect_and_login(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stderr(io.StringIO()):
            repository = Path(tmp) / 'checkout'
            (repository / '.git').mkdir(parents=True)
            profile = repository / 'profiles' / 'xiaohongshu'
            self.assertEqual(main(['collect', 'xiaohongshu', '--query', 'memomind', '--profile', str(profile),
                                   '--output', str(Path(tmp) / 'run'), '--dry-run']), 1)
            with patch('comment_crawler.collectors.xiaohongshu.login_xiaohongshu') as login:
                self.assertEqual(main(['login', 'xiaohongshu', '--profile', str(profile)]), 1)
                login.assert_not_called()

    def test_check_reports_content_types_quality_and_last_run_status(self):
        def collect(source, config, output, emit):
            emit(ReviewRecord('xiaohongshu', 'post', 'https://www.xiaohongshu.com/explore/0123456789abcdef01234567',
                              'note:0123456789abcdef01234567', title='标题',
                              metadata={'visible_engagement': {'likes': '12', 'shares': ''}}))
            emit(ReviewRecord('xiaohongshu', 'comment', 'https://www.xiaohongshu.com/explore/0123456789abcdef01234567',
                              'synthetic:comment', body='正文'))
            return CollectionResult(source)
        with tempfile.TemporaryDirectory() as tmp, patch('comment_crawler.cli.dispatch', collect), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['collect', 'xiaohongshu', '--query', 'memomind', '--profile', tmp,
                                   '--output', tmp]), 0)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(['check', '--output', tmp]), 0)
            report = json.loads(output.getvalue())
            self.assertEqual(report['last_run']['status'], 'completed_visible')
            self.assertEqual(report['by_content_type'], {'comment': 1, 'post': 1})
            self.assertEqual(report['quality']['post']['fields']['body']['missing'], 1)
            self.assertEqual(report['quality']['post']['visible_engagement']['shares']['missing'], 1)
            self.assertEqual(report['quality']['post']['ids']['platform'], 1)
            self.assertNotIn('title', report['quality']['comment']['fields'])

    def test_last_run_reports_content_types_and_synthetic_id_quality(self):
        def collect(source, config, output, emit):
            emit(ReviewRecord('xiaohongshu', 'comment', 'https://www.xiaohongshu.com/explore/0123456789abcdef01234567',
                              'synthetic:c1', body='评论', metadata={'id_kind': 'synthetic'}))
            return CollectionResult(source)
        with tempfile.TemporaryDirectory() as tmp, patch('comment_crawler.cli.dispatch', collect), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['collect', 'xiaohongshu', '--query', 'memomind', '--profile', tmp,
                                   '--output', tmp]), 0)
            report = json.loads((Path(tmp) / 'last_run.json').read_text())
            self.assertEqual(report['by_content_type'], {'comment': 1})
            self.assertEqual(report['field_coverage']['comment']['records'], 1)
            self.assertEqual(report['field_coverage']['comment']['ids']['synthetic'], 1)

    def test_dry_run_does_not_create_output_or_require_credentials(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            out = Path(tmp) / 'out'
            self.assertEqual(main(['collect', 'youtube', '--query', 'camera', '--output', str(out), '--dry-run']), 0)
            self.assertFalse(out.exists())

    def test_failed_run_preserves_rows_and_returns_failure(self):
        def collect(source, config, output, emit):
            emit(ReviewRecord('youtube', 'comment', 'https://example.org', 'a', body='saved'))
            result = CollectionResult('youtube')
            result.errors.append('fixture failure')
            return result
        with tempfile.TemporaryDirectory() as tmp, patch('comment_crawler.cli.dispatch', collect), contextlib.redirect_stdout(io.StringIO()):
            code = main(['collect', 'youtube', '--query', 'camera', '--output', tmp])
            self.assertEqual(code, 1)
            with ReviewStore(Path(tmp) / 'records.sqlite3') as store:
                self.assertEqual(store.count(), 1)
            self.assertEqual(json.loads((Path(tmp) / 'last_run.json').read_text())['status'], 'failed')

    def test_check_missing_database_does_not_create_it(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stderr(io.StringIO()):
            out = Path(tmp) / 'missing'
            self.assertEqual(main(['check', '--output', str(out)]), 1)
            self.assertFalse(out.exists())

    def test_interrupt_keeps_committed_rows_and_report(self):
        def collect(source, config, output, emit):
            emit(ReviewRecord('youtube', 'comment', 'https://example.org', 'a', body='saved'))
            raise KeyboardInterrupt()
        with tempfile.TemporaryDirectory() as tmp, patch('comment_crawler.cli.dispatch', collect), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['collect', 'youtube', '--query', 'camera', '--output', tmp]), 130)
            report = json.loads((Path(tmp) / 'last_run.json').read_text())
            self.assertEqual(report['status'], 'interrupted')
            self.assertEqual(report['inserted'], 1)

    def test_same_output_rejects_other_target_before_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with patch('comment_crawler.cli.dispatch', return_value=CollectionResult('youtube')):
                self.assertEqual(main(['collect', 'youtube', '--query', 'camera', '--output', tmp]), 0)
            with patch('comment_crawler.cli.dispatch') as dispatch:
                self.assertEqual(main(['collect', 'youtube', '--query', 'other', '--output', tmp]), 1)
                dispatch.assert_not_called()

    def test_invalid_delay_is_rejected_without_output(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stderr(io.StringIO()):
            out = Path(tmp) / 'out'
            self.assertEqual(main(['collect', 'youtube', '--query', 'camera', '--output', str(out), '--delay', 'nan']), 1)
            self.assertFalse(out.exists())

    def test_unowned_old_database_is_not_adopted(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with ReviewStore(Path(tmp) / 'records.sqlite3') as store:
                store.upsert(ReviewRecord('reddit', 'comment', 'https://example.org', 'old', body='old'))
            with patch('comment_crawler.cli.dispatch', return_value=CollectionResult('youtube')) as dispatch:
                self.assertEqual(main(['collect', 'youtube', '--query', 'camera', '--output', tmp]), 1)
                dispatch.assert_not_called()
            self.assertFalse((Path(tmp) / 'task.json').exists())
            with ReviewStore(Path(tmp) / 'records.sqlite3') as store:
                self.assertEqual(store.count(), 1)
