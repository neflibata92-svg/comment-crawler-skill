import unittest
from comment_crawler.collectors.browser import jd_record, taobao_record, validate_target, collect_jd, navigate
from comment_crawler.core.utils import CollectionResult


class BrowserTests(unittest.TestCase):
    def test_taobao_append_updates_same_identity(self):
        raw = {'user': 'fixture', 'meta': '2026-01-01 已购：black', 'content': 'nice', 'append': ''}
        a = taobao_record(raw, 'https://item.taobao.com/item.htm?id=123')
        b = taobao_record({**raw, 'append': 'later feedback'}, a.url)
        self.assertEqual(a.record_key, b.record_key)
        self.assertNotEqual(a.content_hash, b.content_hash)
        self.assertNotIn('fixture', str(a.as_dict()))

    def test_platform_id_survives_content_edits(self):
        a = jd_record({'id': '123', 'content': 'old'}, 'https://item.jd.com/123.html')
        b = jd_record({'id': '123', 'content': 'new'}, a.url)
        self.assertEqual(a.record_key, b.record_key)
        self.assertNotEqual(a.content_hash, b.content_hash)

    def test_target_rejects_wrong_domain_and_scheme(self):
        for url in ['https://evil.example/?next=jd.com', 'file:///tmp/x', 'https://item.jd.com.evil.example/1.html']:
            with self.assertRaises(ValueError):
                validate_target('jd', url)
        self.assertEqual(validate_target('jd', '123'), 'https://item.jd.com/123.html')

    def test_jd_stops_duplicate_pages_after_saving(self):
        class Response:
            status = 200
        class Page:
            url = 'https://club.jd.com/comment/productPageComments.action'
            def goto(self, *a, **k): return Response()
            def inner_text(self, selector): return '{"comments":[{"id":"1","content":"body"}]}'
        result = CollectionResult('jd')
        with self.assertRaisesRegex(ValueError, '重复'):
            collect_jd(Page(), 'https://item.jd.com/123.html', result, 0)
        self.assertEqual(result.fetched, 1)

    def test_redirect_outside_expected_host_stops(self):
        class Page:
            url = 'https://unexpected.example/comments'
            def goto(self, *args, **kwargs):
                class Response:
                    status = 200
                return Response()
        with self.assertRaisesRegex(ValueError, '域名'):
            navigate(Page(), 'https://api.jd.com/v1/comments')
