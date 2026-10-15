import unittest

from comment_crawler.web_video_analysis import _source_reference_url


class WebVideoReferenceTests(unittest.TestCase):
    def test_youtube_watch_keeps_only_video_id(self):
        self.assertEqual(
            _source_reference_url("https://www.youtube.com/watch?v=ABCDEFGHIjk&t=33&token=secret#part"),
            "https://www.youtube.com/watch?v=ABCDEFGHIjk",
        )
