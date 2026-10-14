import unittest

from comment_crawler.web_video_analysis import _guard_document_navigation, is_supported_platform_url


class FakeRequest:
    def __init__(self, url, navigation):
        self.url = url
        self._navigation = navigation

    def is_navigation_request(self):
        return self._navigation


class FakeRoute:
    def __init__(self, url, navigation):
        self.request = FakeRequest(url, navigation)
        self.action = None

    def abort(self, reason):
        self.action = ("abort", reason)

    def continue_(self):
        self.action = ("continue", None)


class WebVideoURLTests(unittest.TestCase):
    def test_accepts_supported_platform_domains(self):
        for url in (
            "https://www.youtube.com/watch?v=abc",
            "https://youtu.be/abc",
            "https://www.douyin.com/video/123",
            "https://www.bilibili.com/video/BV123",
            "https://weibo.com/123",
            "https://www.xiaohongshu.com/explore/123",
            "https://www.zhihu.com/question/123",
            "https://tieba.baidu.com/p/123",
        ):
            with self.subTest(url=url):
                self.assertTrue(is_supported_platform_url(url))

    def test_rejects_untrusted_schemes_hosts_and_authority_tricks(self):
        for url in (
            "http://www.youtube.com/watch?v=abc",
            "https://youtube.com.evil.example/watch?v=abc",
            "https://evil-youtube.com/watch?v=abc",
            "https://user@youtube.com/watch?v=abc",
            "https://@youtube.com/watch?v=abc",
            "https://youtube.com:8443/watch?v=abc",
            "file:///tmp/video.mp4",
        ):
            with self.subTest(url=url):
                self.assertFalse(is_supported_platform_url(url))

    def test_navigation_guard_blocks_untrusted_documents_but_allows_media_subresources(self):
        external_document = FakeRoute("https://untrusted.example/player", True)
        trusted_document = FakeRoute("https://www.youtube.com/embed/abc", True)
        media_subresource = FakeRoute("https://cdn.example/video.m3u8", False)

        _guard_document_navigation(external_document)
        _guard_document_navigation(trusted_document)
        _guard_document_navigation(media_subresource)

        self.assertEqual(external_document.action, ("abort", "blockedbyclient"))
        self.assertEqual(trusted_document.action, ("continue", None))
        self.assertEqual(media_subresource.action, ("continue", None))


if __name__ == "__main__":
    unittest.main()
