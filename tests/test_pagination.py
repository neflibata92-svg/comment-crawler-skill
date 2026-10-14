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

    def test_youtube_never_reads_api_key_from_config(self):
        collector = YouTubeCollector({'queries': ['camera'], 'api_key': 'must-not-be-used'}, {})
        with patch.dict(os.environ, {}, clear=True):
            result = collector.collect()
        self.assertEqual(result.records, [])
        self.assertTrue(any('YOUTUBE_API_KEY' in error for error in result.errors))

    def test_youtube_sends_api_key_in_header_not_url(self):
        collector = YouTubeCollector({}, {'delay_seconds': 0})
        with patch('comment_crawler.collectors.youtube.request_json', return_value={'items': []}) as request:
            collector._api('search', {'part': 'snippet', 'q': 'camera'}, 'fixture-key')
        url = request.call_args.args[0]
        options = request.call_args.kwargs
        self.assertNotIn('key=', url)
        self.assertNotIn('fixture-key', url)
        self.assertEqual(options['headers'], {'x-goog-api-key': 'fixture-key'})

    def test_opencli_refreshes_non_memomind_post(self):
        collector = OpenCLIRedditCollector({'queries': ['camera'], 'known_post_ids': ['t3_a']}, {})
        collector._run_json = lambda args: ([{'id': 'a', 'title': 'Camera review', 'url': 'https://reddit.com/a'}] if args[0] == 'search' else [{'type': 'L0', 'text': 'New comment', 'author': 'a'}])
        result = collector.collect()
        self.assertEqual(len(result.records), 2)

    def test_reddit_search_pages_and_morechildren(self):
        collector = RedditCollector({'queries': ['camera'], 'subreddits': ['cameras']}, {})
        collector._token = lambda: 'fixture'
        listing_limits = []
        def api(path, token):
            params = parse_qs(urlparse(path).query)
            if '/search' in path:
                pid = 'b' if 'after' in params else 'a'
                return {'data': {'children': [{'data': {'id': pid, 'name': 't3_' + pid, 'title': 'camera', 'permalink': '/comments/' + pid}}], 'after': None if pid == 'b' else 'cursor'}}
            if '/morechildren' in path:
                return {'json': {'errors': [], 'data': {'things': [{'kind': 't1', 'data': {'id': params['children'][0], 'name': 't1_' + params['children'][0], 'body': 'reply', 'parent_id': params['link_id'][0]}}]}}}
            listing_limits.extend(params.get('limit', []))
            pid = path.split('/')[2].split('.')[0]
            return [{}, {'data': {'children': [{'kind': 'more', 'data': {'children': [pid + 'reply'], 'count': 1}}]}}]
        collector._api = api
        result = collector.collect()
        self.assertEqual(result.errors, [])
        self.assertEqual({r.external_id for r in result.records}, {'t3_a', 't3_b', 't1_areply', 't1_breply'})
        self.assertTrue(all(r.reply_count is None for r in result.records if r.content_type == 'comment'))
        self.assertEqual(listing_limits, ['100', '100'])

    def test_reddit_expands_all_comment_ids_in_more_nodes_without_a_total_cap(self):
        collector = RedditCollector({}, {})
        collector._token = lambda: 'fixture'
        ids = [f'c{index}' for index in range(601)]
        requested_batches = []
        def api(path, token):
            params = parse_qs(urlparse(path).query)
            if '/comments/' in path:
                return [{}, {'data': {'children': [{'kind': 'more', 'data': {'children': ids, 'count': len(ids)}}]}}]
            batch = params['children'][0].split(',')
            requested_batches.append(batch)
            return {'json': {'errors': [], 'data': {'things': [
                {'kind': 't1', 'data': {'id': item, 'name': 't1_' + item, 'body': 'comment',
                                       'parent_id': params['link_id'][0]}}
                for item in batch
            ]}}}
        collector._api = api

        records = list(collector._comments({'id': 'post', 'permalink': '/comments/post'}, 'fixture'))

        self.assertEqual(len(records), 601)
        self.assertEqual(len(requested_batches), 7)
        self.assertTrue(all(len(batch) <= 100 for batch in requested_batches))

    def test_reddit_oauth_keeps_only_top_level_comments_and_direct_replies(self):
        collector = RedditCollector({}, {})
        deep_comment = {'kind': 't1', 'data': {
            'id': 'deep', 'name': 't1_deep', 'body': 'third-level reply', 'parent_id': 't1_reply',
        }}
        reply = {'kind': 't1', 'data': {
            'id': 'reply', 'name': 't1_reply', 'body': 'second-level reply', 'parent_id': 't1_root',
            'replies': {'data': {'children': [deep_comment]}},
        }}
        root_comment = {'kind': 't1', 'data': {
            'id': 'root', 'name': 't1_root', 'body': 'top-level comment', 'parent_id': 't3_post',
            'replies': {'data': {'children': [reply]}},
        }}
        collector._api = lambda *_: [{}, {'data': {'children': [root_comment]}}]

        records = list(collector._comments({'id': 'post', 'permalink': '/comments/post'}, 'fixture'))

        self.assertEqual([record.external_id for record in records], ['t1_root', 't1_reply'])
        self.assertEqual([record.metadata['comment_level'] for record in records], [1, 2])

    def test_youtube_keeps_collecting_other_videos_and_queries_after_comment_error(self):
        collector = YouTubeCollector({'queries': ['camera', 'second-query']}, {})
        def api(endpoint, params, key):
            if endpoint == 'search':
                return {'items': [{'id': {'videoId': 'v1' if params['q'] == 'camera' else 'v2'}}]}
            if endpoint == 'videos':
                return {'items': [{'id': params['id'], 'snippet': {'title': 'camera'}}]}
            if params['videoId'] == 'v1':
                raise RuntimeError('HTTP 403')
            return {'items': [{'snippet': {'topLevelComment': {'id': 'c2', 'snippet': {'textOriginal': 'saved'}}}}]}
        collector._api = api
        with patch.dict(os.environ, {'YOUTUBE_API_KEY': 'fixture'}):
            result = collector.collect()
        self.assertEqual([r.external_id for r in result.records], ['video:v1', 'video:v2', 'comment:c2'])
        self.assertEqual(len(result.errors), 1)
        self.assertIn('v1', result.errors[0])

    def test_opencli_no_twenty_post_cap_and_warns_backend_limit(self):
        collector = OpenCLIRedditCollector({'queries': ['camera'], 'read_comments': False}, {})
        called = []
        collector._run_json = lambda args: called.append(args) or [
            {'id': str(i), 'title': 'Camera', 'url': f'https://reddit.com/{i}'} for i in range(150)
        ]
        result = collector.collect()
        self.assertEqual(len(result.records), 150)
        self.assertTrue(result.warnings)
        requested_limit = called[0][called[0].index('--limit') + 1]
        self.assertGreater(int(requested_limit), 100)

    def test_opencli_reads_more_than_five_hundred_visible_comments_and_only_two_levels(self):
        collector = OpenCLIRedditCollector({}, {})
        called = []
        comments = [{'type': 'L0', 'text': f'Comment {index}', 'author': f'author-{index}'} for index in range(601)]
        comments.extend([
            {'type': 'L1', 'text': 'First-level reply', 'author': 'reply-author'},
            {'type': 'L2', 'text': 'Deeper reply should be omitted', 'author': 'deep-author'},
        ])
        collector._run_json = lambda args: called.append(args) or comments

        records = collector._comment_records({'id': 'post-1', 'url': 'https://reddit.com/post-1', 'comments': 1})

        self.assertEqual(len(records), 602)
        self.assertEqual({record.metadata['comment_level'] for record in records}, {1, 2})
        self.assertEqual(records[-1].metadata['comment_level'], 2)
        limit = called[0][called[0].index('--limit') + 1]
        depth = called[0][called[0].index('--depth') + 1]
        replies = called[0][called[0].index('--replies') + 1]
        self.assertGreater(int(limit), 500)
        self.assertEqual(depth, '2')
        self.assertGreater(int(replies), 500)

    def test_reddit_missing_morechildren_is_reported(self):
        collector = RedditCollector({}, {})
        collector._api = lambda path, token: ({'json': {'errors': [], 'data': {'things': []}}} if 'morechildren' in path else [{}, {'data': {'children': [{'kind': 'more', 'data': {'children': ['missing'], 'count': 1}}]}}])
        with self.assertRaisesRegex(ValueError, '不完整'):
            list(collector._comments({'id': 'a', 'permalink': '/a'}, 'key'))
