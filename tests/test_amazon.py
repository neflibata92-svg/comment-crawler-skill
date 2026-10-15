import unittest
from unittest.mock import MagicMock, patch
import importlib.util

from comment_crawler.collectors.amazon import _ocr_images, collect_pages, review_record, validate_target
from comment_crawler.core.storage import ReviewStore
from comment_crawler.core.utils import CollectionResult


class AmazonTests(unittest.TestCase):
    def test_target_canonicalization_and_marketplace_boundary(self):
        expected = 'https://www.amazon.com/dp/B012345678'
        self.assertEqual(validate_target('b012345678'), expected)
        self.assertEqual(validate_target('https://amazon.com/gp/product/B012345678?tag=abc'), expected)
        for target in ('https://www.amazon.co.uk/dp/B012345678',
                       'https://amazon.com.evil.example/dp/B012345678',
                       'http://amazon.com/dp/B012345678',
                       'https://amazon.com/dp/not-an-asin'):
            with self.subTest(target=target), self.assertRaises(ValueError):
                validate_target(target)

    def test_review_mapping_and_stable_dedupe(self):
        url = 'https://www.amazon.com/dp/B012345678'
        raw = {'id': 'customer_review-1', 'author': 'Example User',
               'date': 'Reviewed in the United States on October 14, 2026',
               'title': 'Good', 'body': 'Works', 'rating': '4.0 out of 5 stars',
               'image_ocr_texts': ['HELLO'], 'image_ocr_status': 'completed'}
        first = review_record(raw, url, 'B012345678')
        changed = review_record({**raw, 'body': 'Works better'}, url, 'B012345678')
        self.assertEqual(first.record_key, changed.record_key)
        self.assertNotEqual(first.content_hash, changed.content_hash)
        self.assertEqual(first.published_at, '2026-10-14T00:00:00+00:00')
        self.assertEqual(first.rating, 4.0)
        self.assertEqual(first.metadata['image_ocr_texts'], ['HELLO'])
        self.assertNotIn('Example User', str(first.as_dict()))
        missing_id = review_record({**raw, 'id': ''}, url, 'B012345678')
        self.assertEqual(missing_id.metadata['id_kind'], 'synthetic')
        self.assertEqual(missing_id.record_key,
                         review_record({**raw, 'id': ''}, url, 'B012345678').record_key)

    def test_store_updates_same_review(self):
        from tempfile import TemporaryDirectory
        url = 'https://www.amazon.com/dp/B012345678'
        with TemporaryDirectory() as directory, ReviewStore(f'{directory}/records.sqlite3') as store:
            first = review_record({'id': 'r1', 'body': 'before'}, url, 'B012345678')
            second = review_record({'id': 'r1', 'body': 'after'}, url, 'B012345678')
            self.assertEqual(store.upsert(first), 'inserted')
            self.assertEqual(store.upsert(second), 'updated')
            self.assertEqual(store.count(), 1)

    def test_image_ocr_reports_missing_executable(self):
        review = MagicMock()
        review.locator.return_value.count.return_value = 1
        with patch('comment_crawler.collectors.amazon.shutil.which', return_value=None):
            texts, status = _ocr_images(review)
        self.assertEqual((texts, status), ([], 'ocr_unavailable'))
        review.locator.return_value.first.screenshot.assert_not_called()

    def test_two_visible_pages_then_no_next_link(self):
        class Page:
            def __init__(self):
                self.url = ''
                self.index = -1

            def goto(self, url, **_kwargs):
                self.url = url
                self.index += 1
                return MagicMock(status=200)

            def locator(self, selector):
                node = MagicMock()
                if selector == '#productTitle':
                    node.count.return_value = 1
                    node.first.inner_text.return_value = 'Example product'
                elif selector == '[data-hook="review"]':
                    node.count.return_value = 1
                    review = MagicMock()
                    review.get_attribute.return_value = f'customer_review-{self.index}'
                    review.locator.side_effect = lambda name: self._review_field(name)
                    node.all.return_value = [review]
                elif selector == 'li.a-last:not(.a-disabled) a':
                    node.count.return_value = 1 if self.index == 1 else 0
                    node.first.get_attribute.return_value = '/product-reviews/B012345678/?pageNumber=2'
                else:
                    node.count.return_value = 0
                return node

            @staticmethod
            def _review_field(selector):
                node = MagicMock()
                if selector == '[data-hook="review-body"]':
                    node.count.return_value = 1
                    node.first.inner_text.return_value = 'Visible review'
                else:
                    node.count.return_value = 0
                return node

        result = CollectionResult('amazon')
        with patch('comment_crawler.collectors.amazon.time.sleep'):
            collect_pages(Page(), 'https://www.amazon.com/dp/B012345678', 2, result)
        self.assertEqual([item.content_type for item in result.records], ['post', 'comment', 'comment'])
        self.assertEqual(result.records[1].external_id, 'customer_review-1')
        self.assertEqual(result.records[2].external_id, 'customer_review-2')

    @unittest.skipUnless(importlib.util.find_spec('playwright'), '需要 browser extra')
    def test_rendered_product_reviews_and_seller_response(self):
        from playwright.sync_api import sync_playwright

        product = '<span id="productTitle">Example camera</span>'
        first = '''<div data-hook="review" id="customer_review-r1">
          <span class="a-profile-name">Sample buyer</span>
          <a data-hook="review-title">Clear picture</a>
          <span data-hook="review-body">Works in daylight</span>
          <span data-hook="review-date">Reviewed in the United States on October 14, 2026</span>
          <i data-hook="review-star-rating">4.0 out of 5 stars</i>
          <div data-hook="seller-response">Response from the seller: Thank you</div>
          </div><ul><li class="a-last"><a href="/product-reviews/B012345678/?pageNumber=2">Next</a></li></ul>'''
        second = '''<div data-hook="review" id="customer_review-r2">
          <span data-hook="review-body">Works at night</span>
          </div><ul><li class="a-last a-disabled">Next</li></ul>'''

        def render(page, url):
            page.set_content(product if '/dp/' in url else second if 'pageNumber=2' in url else first)

        with sync_playwright() as pw, patch('comment_crawler.collectors.amazon._navigate', side_effect=render):
            browser = pw.chromium.launch(headless=True)
            try:
                result = CollectionResult('amazon')
                collect_pages(browser.new_page(), 'https://www.amazon.com/dp/B012345678', 0, result)
            finally:
                browser.close()
        self.assertEqual([r.content_type for r in result.records],
                         ['post', 'comment', 'comment', 'comment'])
        self.assertEqual(result.records[2].parent_id, 'customer_review-r1')
        self.assertTrue(result.records[2].is_official)

    @unittest.skipUnless(importlib.util.find_spec('playwright'), '需要 browser extra')
    def test_request_more_reviews_is_reported_as_limited(self):
        from playwright.sync_api import sync_playwright

        product = '<span id="productTitle">Example camera</span>'
        reviews = '''<div data-hook="review" id="customer_review-r1">
          <span data-hook="review-body">One visible review</span></div>
          <a href="/portal/customer-reviews/ajax/request-more-reviews/submit">Send a request</a>'''

        def render(page, url):
            page.set_content(product if '/dp/' in url else reviews)

        with sync_playwright() as pw, patch('comment_crawler.collectors.amazon._navigate', side_effect=render):
            browser = pw.chromium.launch(headless=True)
            try:
                result = CollectionResult('amazon')
                collect_pages(browser.new_page(), 'https://www.amazon.com/dp/B012345678', 0, result)
            finally:
                browser.close()
        self.assertEqual(result.status, 'backend_limited')
        self.assertEqual(len(result.records), 2)
        self.assertIn('请求更多评价', result.warnings[0])


if __name__ == '__main__':
    unittest.main()
