import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from comment_crawler.collectors.xiaohongshu import XhsProgress, collect_xiaohongshu


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
            )
            for payload in malformed:
                with self.subTest(payload=payload):
                    checkpoint.write_text(payload, encoding='utf-8')
                    with self.assertRaisesRegex(ValueError, 'progress.json'):
                        XhsProgress(checkpoint, task)

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
