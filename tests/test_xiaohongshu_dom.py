import unittest

from comment_crawler.collectors.xiaohongshu import COMMENT_ROWS_JS, EXPAND_REPLIES_JS, SEARCH_ROWS_JS

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


@unittest.skipUnless(sync_playwright, '需要 browser extra')
class XiaohongshuDomTests(unittest.TestCase):
    def test_search_cards_and_nested_comments_from_rendered_dom(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.set_content('''
                  <section class="note-item"><a href="https://www.xiaohongshu.com/search_result/0123456789abcdef01234567?xsec_token=secret">
                    <span>相机体验</span></a><div class="title">相机体验</div></section>
                  <section class="query-note-item"><a href="https://www.xiaohongshu.com/explore/111111111111111111111111">推荐词</a></section>
                ''')
                rows = page.evaluate(SEARCH_ROWS_JS)['rows']
                self.assertEqual(len(rows), 1)
                self.assertIn('xsec_token=secret', rows[0]['url'])

                page.set_content('''
                  <div class="parent-comment" data-comment-id="c1">
                    <div class="comment-item"><a href="/user/profile/u1" class="user-name">甲</a>
                      <div class="content">一级评论</div><span class="date">2026-10-13</span></div>
                    <button onclick="this.insertAdjacentHTML('afterend', '<div class=&quot;reply-container&quot;><div class=&quot;comment-item-sub&quot; data-comment-id=&quot;c2&quot;><a href=&quot;/user/profile/u2&quot; class=&quot;user-name&quot;>乙</a><div class=&quot;content&quot;>二级回复</div></div></div>'); this.remove()">展开回复</button>
                  </div>
                ''')
                self.assertEqual(page.evaluate(EXPAND_REPLIES_JS), 1)
                comments = page.evaluate(COMMENT_ROWS_JS)['rows']
                self.assertEqual([row['body'] for row in comments], ['一级评论', '二级回复'])
                self.assertEqual(comments[0]['id'], 'c1')
                self.assertEqual(comments[1]['parent_index'], 0)
                page.set_content('<article>为什么页面显示暂无评论？</article>')
                self.assertEqual(page.evaluate(COMMENT_ROWS_JS), {'rows': []})
                page.set_content('<article>没有找到相关笔记是我写的标题</article>')
                self.assertEqual(page.evaluate(SEARCH_ROWS_JS), {'rows': []})
            finally:
                browser.close()


if __name__ == '__main__':
    unittest.main()
