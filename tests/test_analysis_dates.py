import unittest
from datetime import date

from comment_crawler.analysis import _parse_absolute_date, _time_metrics


class AnalysisDateTests(unittest.TestCase):
    def test_only_complete_absolute_dates_enter_time_trends(self):
        self.assertEqual(_parse_absolute_date("2026-10-13T06:37:20+00:00"), date(2026, 10, 13))
        self.assertEqual(_parse_absolute_date("2026/10/13"), date(2026, 10, 13))
        for display_value in ("2025-10-18北京", "2025-10", "09-26上海", "昨天 23:35加拿大"):
            self.assertIsNone(_parse_absolute_date(display_value))

        rows = [
            {"is_included": "true", "content_group": "reply", "source": "xiaohongshu",
             "published_at": "2025-10-18北京", "pain_points": ["功能与性能"]},
            {"is_included": "true", "content_group": "reply", "source": "xiaohongshu",
             "published_at": "2026-10-13T06:37:20+00:00", "pain_points": ["功能与性能"]},
        ]
        self.assertEqual(_time_metrics(rows), [{
            "source": "xiaohongshu", "content_group": "reply", "month": "2026-10",
            "comment_count": 1, "pain_mentions": 1,
        }])


if __name__ == "__main__":
    unittest.main()
