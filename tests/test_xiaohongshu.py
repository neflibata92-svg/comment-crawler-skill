import unittest

from comment_crawler.collectors.xiaohongshu import (
    check_access, collect_note_comments, discover_notes, note_id_from_url, page_note_id,
    search_url, validate_note_url, xhs_record,
)
from comment_crawler.core.utils import CollectionResult


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
