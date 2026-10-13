import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from comment_crawler.collectors.xiaohongshu import XhsProgress, collect_xiaohongshu


class FakePlaywrightError(Exception):
    pass


class XiaohongshuResumeTests(unittest.TestCase):
    def test_legacy_completed_checkpoints_migrate_to_scanned_semantics(self):
        note_id = '0123456789abcdef01234567'
        task = {'queries': ['memomind'], 'target': ''}
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = Path(tmp) / 'progress.json'
            checkpoint.write_text(json.dumps({
                'version': 1,
                'task': task,
                'notes': {note_id: {'status': 'completed', 'title': '笔记', 'queries': ['memomind']}},
            }), encoding='utf-8')
            progress = XhsProgress(checkpoint, task)
            self.assertEqual(progress.notes[note_id]['status'], 'scanned')
            saved = json.loads(checkpoint.read_text(encoding='utf-8'))
            self.assertEqual(saved['version'], 2)

    def test_malformed_checkpoint_is_rejected_with_actionable_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = Path(tmp) / 'progress.json'
            task = {'queries': ['memomind'], 'target': ''}
            malformed = (
                '[]',
                json.dumps({'version': 1, 'task': task,
                            'notes': {'0123456789abcdef01234567': {'status': 'broken', 'queries': [], 'title': ''}}}),
                json.dumps({'version': [], 'task': task, 'notes': {}}),
                json.dumps({'version': 2, 'task': task,
                            'notes': {'0123456789abcdef01234567': {'status': [], 'queries': [], 'title': ''}}}),
            )
            for payload in malformed:
                with self.subTest(payload=payload):
                    checkpoint.write_text(payload, encoding='utf-8')
                    with self.assertRaisesRegex(ValueError, 'progress.json'):
                        XhsProgress(checkpoint, task)

    def test_rerun_with_only_scanned_notes_is_a_successful_noop(self):
        note_id = '0123456789abcdef01234567'
        task = {'queries': ['memomind'], 'target': ''}

        class FakePage:
            def __init__(self):
                self.url = 'about:blank'
                self.opened_notes = []

            def goto(self, url, **_kwargs):
                self.url = url
                if note_id in url:
                    self.opened_notes.append(note_id)
                return types.SimpleNamespace(status=200)

            def evaluate(self, script):
                if 'SEARCH_ROWS' in script:
                    return {'rows': [{'url': f'https://www.xiaohongshu.com/explore/{note_id}', 'title': '笔记'}]}
                return None

            def wait_for_timeout(self, _milliseconds):
                pass

        class FakeContext:
            def __init__(self, page):
                self.page = page
            def new_page(self):
                return self.page
            def close(self):
                pass

        class FakePlaywright:
            def __init__(self, page):
                self.chromium = types.SimpleNamespace(
                    launch_persistent_context=lambda *_args, **_kwargs: FakeContext(page)
                )
            def __enter__(self):
                return self
            def __exit__(self, *_args):
                pass

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'run'
            profile = Path(tmp) / 'profile'
            progress = XhsProgress(output / 'progress.json', task)
            progress.register_note(note_id, '笔记', 'memomind')
            progress.mark(note_id, 'scanned')
            page = FakePage()
            sync_api = types.ModuleType('playwright.sync_api')
            sync_api.sync_playwright = lambda: FakePlaywright(page)
            sync_api.Error = FakePlaywrightError
            playwright = types.ModuleType('playwright')
            playwright.sync_api = sync_api
            with patch.dict(sys.modules, {'playwright': playwright, 'playwright.sync_api': sync_api}):
                result = collect_xiaohongshu({
                    'profile': str(profile), 'queries': ['memomind'], 'output': str(output),
                }, 0.001)

        self.assertEqual(result.status, 'completed_visible', result.errors)
        self.assertNotIn('所有笔记都未能打开', '\n'.join(result.warnings))
        self.assertEqual(page.opened_notes, [])

    def test_missing_search_cards_do_not_turn_scanned_checkpoint_into_success(self):
        note_id = '0123456789abcdef01234567'
        task = {'queries': ['memomind'], 'target': ''}

        class FakePage:
            def __init__(self):
                self.url = 'about:blank'

            def goto(self, url, **_kwargs):
                self.url = url
                return types.SimpleNamespace(status=200)

            def evaluate(self, script):
                if 'SEARCH_ROWS' in script:
                    return {'rows': []}
                return None

            def wait_for_timeout(self, _milliseconds):
                pass

        class FakeContext:
            def __init__(self, page):
                self.page = page
            def new_page(self):
                return self.page
            def close(self):
                pass

        class FakePlaywright:
            def __init__(self, page):
                self.chromium = types.SimpleNamespace(
                    launch_persistent_context=lambda *_args, **_kwargs: FakeContext(page)
                )
            def __enter__(self):
                return self
            def __exit__(self, *_args):
                pass

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'run'
            profile = Path(tmp) / 'profile'
            progress = XhsProgress(output / 'progress.json', task)
            progress.register_note(note_id, '笔记', 'memomind')
            progress.mark(note_id, 'scanned')
            sync_api = types.ModuleType('playwright.sync_api')
            sync_api.sync_playwright = lambda: FakePlaywright(FakePage())
            sync_api.Error = FakePlaywrightError
            playwright = types.ModuleType('playwright')
            playwright.sync_api = sync_api
            with patch.dict(sys.modules, {'playwright': playwright, 'playwright.sync_api': sync_api}):
                result = collect_xiaohongshu({
                    'profile': str(profile), 'queries': ['memomind'], 'output': str(output),
                }, 0.001)

        self.assertEqual(result.status, 'backend_limited')

    def test_one_note_http_error_does_not_stop_later_notes(self):
        note_ids = [
            '0123456789abcdef01234567',
            '1123456789abcdef01234567',
            '2123456789abcdef01234567',
        ]

        class FakePlaywrightTimeout(FakePlaywrightError):
            pass

        class FakePage:
            def __init__(self):
                self.url = 'about:blank'
                self.opened_notes = []

            def goto(self, url, **_kwargs):
                self.url = url
                note_id = next((item for item in note_ids if item in url), None)
                if note_id:
                    self.opened_notes.append(note_id)
                    if note_id == note_ids[1]:
                        raise FakePlaywrightTimeout('network timeout')
                    return types.SimpleNamespace(status=404 if note_id == note_ids[0] else 200)
                return types.SimpleNamespace(status=200)

            def evaluate(self, script):
                if 'SEARCH_ROWS' in script:
                    if '/search_result_ai' in self.url:
                        return {'rows': [
                            {'url': f'https://www.xiaohongshu.com/explore/{item}', 'title': item}
                            for item in note_ids
                        ]}
                    return {'rows': []}
                if 'NOTE_DETAILS' in script:
                    return {'title': '帖子', 'body': '正文'}
                if 'COMMENT_ROWS' in script:
                    return {'rows': [{'id': 'comment-2', 'body': '评论'}]}
                return 0

            def wait_for_timeout(self, _milliseconds):
                pass

        class FakeContext:
            def __init__(self, page):
                self.page = page
            def new_page(self):
                return self.page
            def close(self):
                pass

        class FakePlaywright:
            def __init__(self, page):
                self.chromium = types.SimpleNamespace(
                    launch_persistent_context=lambda *_args, **_kwargs: FakeContext(page)
                )
            def __enter__(self):
                return self
            def __exit__(self, *_args):
                pass

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'run'
            profile = Path(tmp) / 'profile'
            page = FakePage()
            sync_api = types.ModuleType('playwright.sync_api')
            sync_api.sync_playwright = lambda: FakePlaywright(page)
            sync_api.Error = FakePlaywrightError
            playwright = types.ModuleType('playwright')
            playwright.sync_api = sync_api
            with patch.dict(sys.modules, {'playwright': playwright, 'playwright.sync_api': sync_api}):
                result = collect_xiaohongshu({
                    'profile': str(profile), 'queries': ['memomind'], 'output': str(output),
                }, 0.001)
            state = json.loads((output / 'progress.json').read_text(encoding='utf-8'))

        self.assertEqual(page.opened_notes, note_ids)
        self.assertEqual(state['notes'][note_ids[0]]['status'], 'pending')
        self.assertEqual(state['notes'][note_ids[1]]['status'], 'pending')
        self.assertEqual(state['notes'][note_ids[2]]['status'], 'scanned')
        self.assertTrue(any('HTTP 404' in warning for warning in result.warnings))
        self.assertTrue(any('FakePlaywrightTimeout' in warning for warning in result.warnings))
        self.assertTrue(any(record.content_type == 'comment' and record.body == '评论'
                            for record in result.records))

    def test_interrupted_run_resumes_unfinished_notes_without_signed_urls(self):
        note_ids = ['0123456789abcdef01234567', '1123456789abcdef01234567']

        class FakePage:
            def __init__(self, *, interrupt_second=False):
                self.url = 'about:blank'
                self.interrupt_second = interrupt_second
                self.interrupted = False
                self.opened_notes = []

            def goto(self, url, **kwargs):
                self.url = url
                note_id = next((item for item in note_ids if item in url), None)
                if note_id:
                    self.opened_notes.append(note_id)
                return types.SimpleNamespace(status=200)

            def evaluate(self, script):
                if 'SEARCH_ROWS' in script:
                    if '/search_result_ai' in self.url:
                        return {'rows': [
                            {'url': f'https://www.xiaohongshu.com/explore/{item}?xsec_token=secret-{item}', 'title': item}
                            for item in note_ids
                        ]}
                    return {'rows': []}
                if 'NOTE_DETAILS' in script:
                    return {'title': '帖子', 'body': '正文', 'likes': '1'}
                if 'COMMENT_ROWS' in script:
                    note_id = next(item for item in note_ids if item in self.url)
                    if self.interrupt_second and note_id == note_ids[1] and not self.interrupted:
                        self.interrupted = True
                        raise KeyboardInterrupt()
                    return {'rows': [{'id': f'comment-{note_id}', 'body': '评论', 'author_id': 'author'}]}
                if 'EXPAND_REPLIES' in script:
                    return 0
                return None

            def wait_for_timeout(self, _milliseconds):
                pass

        class FakeContext:
            def __init__(self, page):
                self.page = page
            def new_page(self):
                return self.page
            def close(self):
                pass

        class FakePlaywright:
            def __init__(self, page):
                self.chromium = types.SimpleNamespace(
                    launch_persistent_context=lambda *_args, **_kwargs: FakeContext(page)
                )
            def __enter__(self):
                return self
            def __exit__(self, *_args):
                pass

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'run'
            profile = Path(tmp) / 'profile'
            first_page = FakePage(interrupt_second=True)
            sync_api = types.ModuleType('playwright.sync_api')
            sync_api.sync_playwright = lambda: FakePlaywright(first_page)
            sync_api.Error = FakePlaywrightError
            playwright = types.ModuleType('playwright')
            playwright.sync_api = sync_api
            with patch.dict(sys.modules, {'playwright': playwright, 'playwright.sync_api': sync_api}):
                with self.assertRaises(KeyboardInterrupt):
                    collect_xiaohongshu({'profile': str(profile), 'queries': ['memomind'], 'output': str(output)}, 0.001)

                checkpoint = output / 'progress.json'
                state = json.loads(checkpoint.read_text())
                self.assertEqual(state['notes'][note_ids[0]]['status'], 'scanned')
                self.assertEqual(state['notes'][note_ids[1]]['status'], 'in_progress')
                self.assertNotIn('xsec_token', checkpoint.read_text())

                resumed_page = FakePage()
                sync_api.sync_playwright = lambda: FakePlaywright(resumed_page)
                collect_xiaohongshu({'profile': str(profile), 'queries': ['memomind'], 'output': str(output)}, 0.001)

            self.assertEqual(resumed_page.opened_notes, [note_ids[1]])
            finished = json.loads((output / 'progress.json').read_text())
            self.assertTrue(all(note['status'] == 'scanned' for note in finished['notes'].values()))

            refreshed_page = FakePage()
            sync_api.sync_playwright = lambda: FakePlaywright(refreshed_page)
            with patch.dict(sys.modules, {'playwright': playwright, 'playwright.sync_api': sync_api}):
                collect_xiaohongshu({'profile': str(profile), 'queries': ['memomind'],
                                      'output': str(output), 'refresh_completed': True}, 0.001)
            self.assertEqual(refreshed_page.opened_notes, note_ids)


if __name__ == '__main__':
    unittest.main()
