import os
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
from comment_crawler.collectors.youtube import YouTubeCollector
from comment_crawler.collectors.reddit import RedditCollector
from comment_crawler.collectors.reddit_opencli import OpenCLIRedditCollector


class PaginationTests(unittest.TestCase):
    @patch.dict(os.environ, {'YOUTUBE_API_KEY': 'fixture'})
    def test_youtube_refreshes_other_products_and_search_pages(self):
        collector = YouTubeCollector({'queries': ['camera'], 'known_video_ids': ['video:a']}, {})
        def api(endpoint, params, key):
            if endpoint == 'search':
                return {'items': [{'id': {'videoId': 'b' if params.get('pageToken') else 'a'}}], **({} if params.get('pageToken') else {'nextPageToken': 'next'})}
            if endpoint == 'videos':
                return {'items': [{'id': params['id'], 'snippet': {'title': 'Camera review'}}]}
            return {'items': []}
        collector._api = api
        result = collector.collect()
        self.assertEqual(result.errors, [])
        self.assertEqual([r.external_id for r in result.records], ['video:a', 'video:b'])

    def test_youtube_all_comment_and_reply_pages(self):
        collector = YouTubeCollector({}, {})
        def api(endpoint, params, key):
            if endpoint == 'commentThreads':
                n = int(params.get('pageToken', '0'))
                return {'items': [{'snippet': {'topLevelComment': {'id': str(n), 'snippet': {'textOriginal': 'comment'}}, 'totalReplyCount': 2}}], **({'nextPageToken': str(n + 1)} if n < 2 else {})}
            suffix = params.get('pageToken', 'first')
            return {'items': [{'id': params['parentId'] + suffix, 'snippet': {'textOriginal': 'reply'}}], **({'nextPageToken': 'last'} if suffix == 'first' else {})}
        collector._api = api
        rows = list(collector._comments('v', 'key'))
        self.assertEqual(len(rows), 9)
        self.assertEqual(len({r.external_id for r in rows}), 9)
        self.assertEqual(rows[2].parent_id, 'comment:0')

    def test_youtube_repeated_cursor_stops(self):
        collector = YouTubeCollector({}, {})
        collector._api = lambda *args: {'items': [], 'nextPageToken': 'same'}
        with self.assertRaisesRegex(ValueError, '分页'):
            list(collector._comments('v', 'key'))

    def test_opencli_refreshes_non_memomind_post(self):
        collector = OpenCLIRedditCollector({'queries': ['camera'], 'known_post_ids': ['t3_a']}, {})
        collector._run_json = lambda args: ([{'id': 'a', 'title': 'Camera review', 'url': 'https://reddit.com/a'}] if args[0] == 'search' else [{'type': 'L0', 'text': 'New comment', 'author': 'a'}])
        result = collector.collect()
        self.assertEqual(len(result.records), 2)

    def test_reddit_search_pages_and_morechildren(self):
        collector = RedditCollector({'queries': ['camera'], 'subreddits': ['cameras']}, {})
        collector._token = lambda: 'fixture'
        def api(path, token):
            params = parse_qs(urlparse(path).query)
            if '/search' in path:
                pid = 'b' if 'after' in params else 'a'
                return {'data': {'children': [{'data': {'id': pid, 'name': 't3_' + pid, 'title': 'camera', 'permalink': '/comments/' + pid}}], 'after': None if pid == 'b' else 'cursor'}}
            if '/morechildren' in path:
                return {'json': {'errors': [], 'data': {'things': [{'kind': 't1', 'data': {'id': params['children'][0], 'name': 't1_' + params['children'][0], 'body': 'reply', 'parent_id': params['link_id'][0]}}]}}}
            pid = path.split('/')[2].split('.')[0]
            return [{}, {'data': {'children': [{'kind': 'more', 'data': {'children': [pid + 'reply'], 'count': 1}}]}}]
        collector._api = api
        result = collector.collect()
        self.assertEqual(result.errors, [])
        self.assertEqual({r.external_id for r in result.records}, {'t3_a', 't3_b', 't1_areply', 't1_breply'})
        self.assertTrue(all(r.reply_count is None for r in result.records if r.content_type == 'comment'))

    def test_youtube_keeps_partial_data_and_stops_on_error(self):
        collector = YouTubeCollector({'queries': ['camera', 'second-query']}, {})
        def api(endpoint, params, key):
            if endpoint == 'search':
                return {'items': [{'id': {'videoId': 'v'}}]}
            if endpoint == 'videos':
                return {'items': [{'id': 'v', 'snippet': {'title': 'camera'}}]}
            if params.get('pageToken'):
                raise RuntimeError('HTTP 403')
            return {'items': [{'snippet': {'topLevelComment': {'id': 'c', 'snippet': {'textOriginal': 'saved'}}}}], 'nextPageToken': 'next'}
        collector._api = api
        with patch.dict(os.environ, {'YOUTUBE_API_KEY': 'fixture'}):
            result = collector.collect()
        self.assertEqual([r.external_id for r in result.records], ['video:v', 'comment:c'])
        self.assertEqual(len(result.errors), 1)
        self.assertIn('403', result.errors[0])

    def test_opencli_no_twenty_post_cap_and_warns_backend_limit(self):
        collector = OpenCLIRedditCollector({'queries': ['camera'], 'read_comments': False}, {})
        collector._run_json = lambda args: [{'id': str(i), 'title': 'Camera', 'url': f'https://reddit.com/{i}'} for i in range(30)]
        result = collector.collect()
        self.assertEqual(len(result.records), 30)
        self.assertTrue(result.warnings)

    def test_reddit_missing_morechildren_is_reported(self):
        collector = RedditCollector({}, {})
        collector._api = lambda path, token: ({'json': {'errors': [], 'data': {'things': []}}} if 'morechildren' in path else [{}, {'data': {'children': [{'kind': 'more', 'data': {'children': ['missing'], 'count': 1}}]}}])
        with self.assertRaisesRegex(ValueError, '不完整'):
            list(collector._comments({'id': 'a', 'permalink': '/a'}, 'key'))
