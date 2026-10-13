from pathlib import Path
import json
import tempfile
import unittest

from comment_crawler.collectors.xiaohongshu import (
    check_access, collect_note_comments, discover_notes, note_id_from_url, page_note_id,
    search_url, validate_note_url, xhs_post_record, xhs_record,
)
from comment_crawler.core.utils import CollectionResult
from comment_crawler.core.storage import ReviewStore


class XiaohongshuTests(unittest.TestCase):
    def test_page_note_id_reads_only_real_note_paths(self):
        # 被平台拦截时地址是 /404，笔记 ID 只出现在被编码的查询参数里；
        # 此时必须返回 None，防止把拦截页当成笔记页继续采。
        class Page:
            def __init__(self, url):
                self.url = url
        note = '0123456789abcdef01234567'
        self.assertEqual(page_note_id(Page(f'https://www.xiaohongshu.com/explore/{note}?xsec_token=secret')), note)
        self.assertEqual(page_note_id(Page(f'https://www.xiaohongshu.com/search_result/{note}')), note)
        blocked = ('https://www.xiaohongshu.com/404?source=/404/sec_x'
                   '&redirectPath=https%3A%2F%2Fwww.xiaohongshu.com%2Fexplore%2F' + note)
        self.assertIsNone(page_note_id(Page(blocked)))
        self.assertIsNone(page_note_id(Page('https://www.xiaohongshu.com/explore')))

    def test_search_url_builds_encoded_result_page(self):
        # 当前页面上的搜索框组件隐藏（宽高为 0），采集器改为直接打开结果页地址。
        self.assertEqual(search_url('memomind'),
                         'https://www.xiaohongshu.com/search_result_ai?keyword=memomind')
        self.assertEqual(search_url('户外相机'),
                         'https://www.xiaohongshu.com/search_result_ai?keyword=%E6%88%B7%E5%A4%96%E7%9B%B8%E6%9C%BA')

    def test_security_redirect_stops_before_collection(self):
        class Page:
            url = 'https://www.xiaohongshu.com/website-login/error?error_code=300012'
        with self.assertRaisesRegex(ValueError, '登录或验证'):
            check_access(Page())

    def test_note_url_validation_and_canonical_identity(self):
        signed = 'https://www.xiaohongshu.com/search_result/0123456789abcdef01234567?xsec_token=secret'
        self.assertEqual(validate_note_url(signed), signed)
        self.assertEqual(note_id_from_url(signed), '0123456789abcdef01234567')
        for url in ('https://www.xiaohongshu.com.evil.test/explore/0123456789abcdef01234567',
                    'http://www.xiaohongshu.com/explore/0123456789abcdef01234567',
                    'https://www.xiaohongshu.com/user/profile/0123456789abcdef01234567'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_note_url(url)

    def test_comment_record_uses_platform_id_and_thread_parent(self):
        url = 'https://www.xiaohongshu.com/explore/0123456789abcdef01234567?xsec_token=secret'
        parent = xhs_record({'id': 'c1', 'body': '原评论', 'author_id': 'u1'}, url)
        reply = xhs_record({'id': 'c2', 'parent_id': 'c1', 'body': '回复', 'author_id': 'u2'}, url)
        self.assertEqual(parent.url, 'https://www.xiaohongshu.com/explore/0123456789abcdef01234567')
        self.assertEqual(reply.parent_id, 'c1')
        self.assertNotEqual(parent.record_key, reply.record_key)
        self.assertNotIn('secret', str(reply.as_dict()))
        tagged = xhs_record({'id': 'c1', 'body': '原评论', 'queries': ['相机', '摄影']}, url)
        self.assertEqual(tagged.metadata['queries'], ['相机', '摄影'])

    def test_post_record_keeps_content_and_visible_metrics_but_hashes_author(self):
        url = 'https://www.xiaohongshu.com/explore/0123456789abcdef01234567?xsec_token=secret'
        record = xhs_post_record({
            'title': 'Memomind 使用体验', 'body': '笔记正文', 'author_id': 'user_1',
            'author': '公开昵称', 'published_at': '2天前', 'likes': '1.2万',
            'saves': '345', 'comments': '67', 'shares': '8', 'queries': ['memomind'],
        }, url)
        payload = record.as_dict()
        self.assertEqual(record.content_type, 'post')
        self.assertEqual(record.external_id, 'note:0123456789abcdef01234567')
        self.assertEqual(record.title, 'Memomind 使用体验')
        self.assertEqual(record.body, '笔记正文')
        self.assertTrue(record.published_at.endswith('+00:00'))
        self.assertEqual(record.metadata['published_at_raw'], '2天前')
        self.assertEqual(record.metadata['published_at_precision'], 'estimated_relative')
        self.assertTrue(record.author_hash)
        self.assertNotIn('公开昵称', str(payload))
        self.assertEqual(record.metadata['visible_engagement']['likes'], '1.2万')
        self.assertEqual(record.metadata['queries'], ['memomind'])
        self.assertNotIn('xsec_token', str(payload))

    def test_relative_post_time_is_iso_and_keeps_display_text(self):
        record = xhs_post_record({
            'title': '体验', 'published_at': '2天前',
            'captured_at': '2026-10-13T08:00:00+08:00',
        }, 'https://www.xiaohongshu.com/explore/0123456789abcdef01234567')
        self.assertEqual(record.published_at, '2026-10-11T00:00:00+00:00')
        self.assertEqual(record.metadata['published_at_raw'], '2天前')
        self.assertEqual(record.metadata['published_at_precision'], 'estimated_relative')

    def test_unrecognized_comment_time_is_not_misrepresented_as_iso(self):
        record = xhs_record({
            'id': 'c1', 'body': '评论', 'time': '来自未知组件',
            'captured_at': '2026-10-13T08:00:00+08:00',
        }, 'https://www.xiaohongshu.com/explore/0123456789abcdef01234567')
        self.assertEqual(record.published_at, '')
        self.assertEqual(record.metadata['published_at_raw'], '来自未知组件')
        self.assertEqual(record.metadata['published_at_precision'], 'unparsed')

    def test_synthetic_comment_identity_survives_relative_time_changes(self):
        url = 'https://www.xiaohongshu.com/explore/0123456789abcdef01234567'
        first = xhs_record({'body': '同一条评论', 'author_id': 'u1', 'time': '2天前'}, url)
        later = xhs_record({'body': '同一条评论', 'author_id': 'u1', 'time': '3天前'}, url)
        self.assertEqual(first.record_key, later.record_key)
        with tempfile.TemporaryDirectory() as tmp, ReviewStore(Path(tmp) / 'records.sqlite3') as store:
            self.assertEqual(store.upsert(first), 'inserted')
            self.assertEqual(store.upsert(later), 'updated')
            self.assertEqual(store.count(), 1)

    def test_synthetic_comment_identity_deduplicates_same_content_across_authors(self):
        url = 'https://www.xiaohongshu.com/explore/0123456789abcdef01234567'
        first = xhs_record({'body': '重复评论', 'author_id': 'u1'}, url)
        duplicate = xhs_record({'body': '重复评论', 'author_id': 'u2'}, url)
        self.assertEqual(first.record_key, duplicate.record_key)
        with tempfile.TemporaryDirectory() as tmp, ReviewStore(Path(tmp) / 'records.sqlite3') as store:
            store.upsert(first)
            store.upsert(duplicate)
            self.assertEqual(store.count(), 1)

    def test_comment_scan_keeps_first_synthetic_duplicate_without_counting_an_update(self):
        class Page:
            url = 'https://www.xiaohongshu.com/explore/0123456789abcdef01234567'
            rounds = 0
            def evaluate(self, script):
                if 'COMMENT_ROWS' in script:
                    self.rounds += 1
                    if self.rounds > 3:
                        raise AssertionError('duplicate rows kept the scan from reaching its stable stop')
                    return {'rows': [
                        {'body': '重复评论', 'author_id': 'u1'},
                        {'body': '重复评论', 'author_id': 'u2'},
                    ]}
                return 0
            def wait_for_timeout(self, _milliseconds):
                pass

        result = CollectionResult('xiaohongshu')
        collect_note_comments(Page(), Page.url, result, 0.001, stable_rounds=2)
        self.assertEqual(len(result.records), 1)
        first = xhs_record({'body': '重复评论', 'author_id': 'u1'}, Page.url)
        self.assertEqual(result.records[0].author_hash, first.author_hash)

    def test_comment_updates_do_not_reset_no_new_record_stop_counter(self):
        class Page:
            url = 'https://www.xiaohongshu.com/explore/0123456789abcdef01234567'
            rounds = 0
            def evaluate(self, script):
                if 'COMMENT_ROWS' in script:
                    self.rounds += 1
                    if self.rounds > 3:
                        raise AssertionError('updates kept the scan from reaching its stable stop')
                    return {'rows': [{'id': 'native-comment', 'body': '评论', 'likes': str(self.rounds)}]}
                return 0
            def wait_for_timeout(self, _milliseconds):
                pass

        page = Page()
        result = CollectionResult('xiaohongshu')
        collect_note_comments(page, page.url, result, 0.001, stable_rounds=2)
        self.assertEqual(page.rounds, 3)
        self.assertEqual(result.status, 'stalled')

    def test_search_scrolls_without_fixed_note_cap_and_deduplicates(self):
        class Page:
            url = 'https://www.xiaohongshu.com/search_result?keyword=camera'
            def __init__(self):
                self.round = 0
            def evaluate(self, script):
                if 'SEARCH_ROWS' in script:
                    ids = range(min(self.round, 2) * 30, min(self.round, 2) * 30 + 30)
                    return [{'url': f'https://www.xiaohongshu.com/explore/{i:024x}', 'title': str(i)} for i in ids]
                self.round += 1
                return None
            def wait_for_timeout(self, ms):
                pass
        result = CollectionResult('xiaohongshu')
        rows = discover_notes(Page(), 0.001, result, stable_rounds=2)
        self.assertGreater(len(rows), 50)
        self.assertEqual(result.status, 'stalled')

    def test_search_discovery_checkpoint_callback_runs_before_next_scroll(self):
        from comment_crawler.collectors.xiaohongshu import XhsProgress

        note_id = '0123456789abcdef01234567'
        task = {'queries': ['memomind'], 'target': ''}
        with tempfile.TemporaryDirectory() as tmp:
            progress = XhsProgress(Path(tmp) / 'progress.json', task)

            class Page:
                url = 'https://www.xiaohongshu.com/search_result_ai?keyword=memomind'
                def evaluate(self, script):
                    if 'SEARCH_ROWS' in script:
                        return {'rows': [{'url': f'https://www.xiaohongshu.com/explore/{note_id}', 'title': '测试笔记'}]}
                    return None
                def wait_for_timeout(self, _milliseconds):
                    raise KeyboardInterrupt()

            def checkpoint(note):
                progress.register_note(note_id, note['title'], 'memomind')
                progress.save()

            with self.assertRaises(KeyboardInterrupt):
                discover_notes(Page(), 0.001, CollectionResult('xiaohongshu'), on_note=checkpoint)
            saved = json.loads((Path(tmp) / 'progress.json').read_text())
            self.assertEqual(saved['notes'][note_id]['title'], '测试笔记')

    def test_comments_save_before_stall_and_preserve_replies(self):
        class Page:
            url = 'https://www.xiaohongshu.com/explore/0123456789abcdef01234567'
            def __init__(self):
                self.round = 0
            def evaluate(self, script):
                if 'COMMENT_ROWS' in script:
                    return {'rows': [{'id': 'c1', 'body': '一级'},
                                     {'id': 'c2', 'parent_id': 'c1', 'body': '二级'}], 'comments_disabled': False}
                if 'EXPAND_REPLIES' in script:
                    return 0
                self.round += 1
                return None
            def wait_for_timeout(self, ms):
                pass
        result = CollectionResult('xiaohongshu')
        collect_note_comments(Page(), 'https://www.xiaohongshu.com/explore/0123456789abcdef01234567',
                              result, 0.001, stable_rounds=2)
        self.assertEqual(len(result.records), 2)
        self.assertEqual(result.records[1].parent_id, 'c1')
        self.assertEqual(result.status, 'stalled')

    def test_missing_comment_dom_is_limited_not_completed(self):
        class Page:
            url = 'https://www.xiaohongshu.com/explore/0123456789abcdef01234567'
            def evaluate(self, script):
                if 'COMMENT_ROWS' in script:
                    return {'rows': []}
                return 0
            def wait_for_timeout(self, ms):
                pass
        result = CollectionResult('xiaohongshu')
        collect_note_comments(Page(), Page.url, result, 0.001, stable_rounds=2)
        self.assertEqual(result.status, 'backend_limited')
        self.assertEqual(result.records, [])


if __name__ == '__main__':
    unittest.main()
