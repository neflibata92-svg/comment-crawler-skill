import tempfile
import unittest
from pathlib import Path
from comment_crawler.core.schema import ReviewRecord
from comment_crawler.core.storage import ReviewStore
from comment_crawler.core.utils import CollectionResult
from comment_crawler.collectors.reddit_opencli import OpenCLIRedditCollector


class ReleaseTests(unittest.TestCase):
    def test_sink_commits_before_collector_finishes_and_does_not_buffer(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'records.sqlite3'
            with ReviewStore(path) as store:
                result = CollectionResult('youtube', emit=store.upsert)
                result.add(ReviewRecord('youtube', 'comment', 'https://example.org', 'c', body='first'))
                with ReviewStore(path) as reader:
                    self.assertEqual(reader.count(), 1)
                self.assertEqual(result.records, [])
                result.add(ReviewRecord('youtube', 'comment', 'https://example.org', 'c', body='edited'))
                self.assertEqual(store.count(), 1)
                self.assertEqual(next(store.iter_records()).body, 'edited')

    def test_no_product_inference(self):
        record = ReviewRecord('youtube', 'comment', 'https://example.org', 'c', body='camera').normalize()
        self.assertEqual(record.metadata, {})

    def test_reddit_backends_use_distinct_keys(self):
        collector = OpenCLIRedditCollector({}, {})
        browser = collector._post_record({'id': 'a', 'title': 'camera', 'url': 'https://reddit.com/a'}, 'camera')
        oauth = ReviewRecord('reddit', 'post', 'https://reddit.com/a', 't3_a')
        self.assertNotEqual(browser.record_key, oauth.record_key)

    def test_csv_does_not_execute_comment_as_formula(self):
        import csv
        with tempfile.TemporaryDirectory() as tmp:
            with ReviewStore(Path(tmp) / 'records.sqlite3') as store:
                store.upsert(ReviewRecord('youtube', 'comment', 'https://example.org', 'c', body='=1+1'))
                csv_path = store.export_csv(Path(tmp) / 'records.csv')
                with csv_path.open(encoding='utf-8-sig') as handle:
                    row = next(csv.DictReader(handle))
                self.assertEqual(row['body'], "'=1+1")
                self.assertEqual(next(store.iter_records()).body, '=1+1')
