"""Amazon 商品页及可见评价页采集；仅启用已经适配的美国站。"""
from __future__ import annotations

from io import BytesIO
from datetime import datetime, timezone
import re
import time
from urllib.parse import urlparse

from ..core.schema import ReviewRecord, clean_text, hash_author, stable_hash
from ..core.utils import CollectionResult, validate_browser_profile_path


HOST = 'www.amazon.com'
ASIN = re.compile(r'[A-Z0-9]{10}', re.I)
PRODUCT_PATH = re.compile(r'/(?:[^/]+/)?(?:dp|gp/product)/([A-Z0-9]{10})(?:/|$)', re.I)


def validate_target(target: str) -> str:
    target = target.strip()
    if ASIN.fullmatch(target):
        return f'https://{HOST}/dp/{target.upper()}'
    parsed = urlparse(target)
    if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError('Amazon 目标必须是 HTTPS 商品链接或 10 位 ASIN')
    if parsed.hostname not in {HOST, 'amazon.com'}:
        raise ValueError('当前只验证了 amazon.com；其他国家站点需逐站适配')
    match = PRODUCT_PATH.match(parsed.path)
    if not match:
        raise ValueError('Amazon 商品链接需包含 /dp/ASIN 或 /gp/product/ASIN')
    return f'https://{HOST}/dp/{match.group(1).upper()}'


def _navigate(page, url: str) -> None:
    response = page.goto(url, wait_until='domcontentloaded', timeout=60000)
    if response is None or response.status >= 400:
        raise ValueError(f'Amazon 页面请求失败 HTTP {response.status if response else "unknown"}')
    parsed = urlparse(page.url)
    if parsed.scheme != 'https' or parsed.hostname not in {HOST, 'amazon.com'}:
        raise ValueError('Amazon 页面跳转到非预期域名')
    if '/ap/signin' in parsed.path or '/errors/validateCaptcha' in parsed.path:
        raise ValueError('Amazon 要求登录或验证，停止采集')
    if page.locator('form[action*="validateCaptcha"], input[name="captcha"], #captchacharacters').count():
        raise ValueError('Amazon 出现验证码，停止采集')


def _text(node, selector: str) -> str:
    found = node.locator(selector)
    return clean_text(found.first.inner_text()) if found.count() else ''


def _ocr_images(review) -> tuple[list[str], str]:
    images = review.locator('[data-hook="review-image-tile"] img, img[data-hook="review-image-tile"]')
    if not images.count():
        return [], 'none'
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return [], 'dependencies_missing'
    texts = []
    for image in images.all():
        try:
            # 截取已渲染的图片到内存；不创建图片临时文件。
            with Image.open(BytesIO(image.screenshot())) as bitmap:
                value = clean_text(pytesseract.image_to_string(bitmap, lang='eng'))
            if value:
                texts.append(value)
        except Exception:
            return texts, 'partial'
    return texts, 'completed'


def _rating(value: str) -> float | None:
    match = re.search(r'([0-5](?:[.,]\d+)?)', value)
    return float(match.group(1).replace(',', '.')) if match else None


def _review_date(value: str) -> str:
    match = re.search(r'\b([A-Za-z]+ \d{1,2}, \d{4})\b', value)
    if not match:
        return ''
    try:
        return datetime.strptime(match.group(1), '%B %d, %Y').replace(tzinfo=timezone.utc).isoformat()
    except ValueError:
        return ''


def review_record(raw: dict, product_url: str, asin: str) -> ReviewRecord:
    author = hash_author('amazon', raw.get('author'))
    body = clean_text(raw.get('body'))
    published = clean_text(raw.get('date'))
    review_id = clean_text(raw.get('id'))
    external_id = review_id or 'synthetic:' + stable_hash(f'{asin}|{author}|{published}|{body}')
    return ReviewRecord('amazon', 'comment', product_url, external_id,
                        title=raw.get('title', ''), body=body, author_hash=author,
                        published_at=_review_date(published), rating=_rating(raw.get('rating', '')),
                        metadata={'asin': asin, 'marketplace': HOST,
                                  'verified_purchase': bool(raw.get('verified_purchase')),
                                  'image_ocr_texts': raw.get('image_ocr_texts', []),
                                  'image_ocr_status': raw.get('image_ocr_status', 'none'),
                                  'review_date_raw': published,
                                  'id_kind': 'platform' if review_id else 'synthetic',
                                  'comment_level': 1, 'coverage': 'visible_review_page'}).normalize()


def collect_pages(page, product_url: str, delay: float, result: CollectionResult) -> None:
    asin = product_url.rsplit('/', 1)[-1]
    _navigate(page, product_url)
    title = _text(page, '#productTitle')
    if not title:
        raise ValueError('商品标题缺失，页面可能要求验证或结构已变化')
    result.add(ReviewRecord('amazon', 'post', product_url, f'product:{asin}', title=title,
                            metadata={'asin': asin, 'marketplace': HOST,
                                      'coverage': 'visible_product_page'}).normalize())
    next_url = f'https://{HOST}/product-reviews/{asin}/?reviewerType=all_reviews'
    seen_pages: set[str] = set()
    while next_url:
        _navigate(page, next_url)
        reviews = page.locator('[data-hook="review"]')
        if not reviews.count():
            if page.locator('[data-hook="no-reviews-message"]').count():
                return
            raise ValueError('评价页未返回可识别评价，不能视为全部采集完成')
        page_ids = []
        for review in reviews.all():
            raw = {
                'id': review.get_attribute('id') or '',
                'title': _text(review, '[data-hook="review-title"]'),
                'body': _text(review, '[data-hook="review-body"]'),
                'author': _text(review, '.a-profile-name'),
                'date': _text(review, '[data-hook="review-date"]'),
                'rating': _text(review, '[data-hook="review-star-rating"], [data-hook="cmps-review-star-rating"]'),
                'verified_purchase': bool(review.locator('[data-hook="avp-badge"]').count()),
            }
            if not raw['body'] and not raw['title']:
                raise ValueError('评价正文与标题均缺失，页面结构可能变化')
            raw['image_ocr_texts'], raw['image_ocr_status'] = _ocr_images(review)
            record = review_record(raw, product_url, asin)
            page_ids.append(record.external_id)
            result.add(record)
            # 仅当页面明确标示商家回复时才建立回复关系。
            replies = review.locator('[data-hook="seller-response"]')
            for index, reply in enumerate(replies.all(), 1):
                reply_body = clean_text(reply.inner_text())
                if reply_body:
                    result.add(ReviewRecord('amazon', 'comment', product_url,
                                            f'seller-response:{record.external_id}:{index}',
                                            body=reply_body, parent_id=record.external_id,
                                            is_official=True,
                                            metadata={'asin': asin, 'marketplace': HOST,
                                                      'comment_level': 2,
                                                      'coverage': 'visible_review_page'}).normalize())
        signature = stable_hash('|'.join(page_ids))
        if signature in seen_pages:
            raise ValueError('Amazon 返回重复评价页，停止分页')
        seen_pages.add(signature)
        next_link = page.locator('li.a-last:not(.a-disabled) a')
        if not next_link.count():
            return
        href = next_link.first.get_attribute('href') or ''
        parsed = urlparse(href)
        if parsed.scheme and parsed.scheme != 'https' or parsed.hostname and parsed.hostname not in {HOST, 'amazon.com'}:
            raise ValueError('Amazon 下一页链接不属于预期域名')
        if not href or not (parsed.path or '').startswith(f'/product-reviews/{asin}'):
            raise ValueError('Amazon 下一页链接结构发生变化')
        next_url = f'https://{HOST}{href}' if href.startswith('/') else href
        time.sleep(delay)


def collect_amazon(config: dict, delay: float, emit=None) -> CollectionResult:
    from playwright.sync_api import sync_playwright

    result = CollectionResult('amazon', emit=emit)
    with sync_playwright() as pw:
        context = None
        try:
            context = pw.chromium.launch_persistent_context(
                validate_browser_profile_path(config['profile']), headless=False)
            collect_pages(context.new_page(), config['target'], delay, result)
        except Exception as exc:
            result.status = 'failed'
            result.errors.append(str(exc) if isinstance(exc, ValueError) else f'浏览器运行失败：{type(exc).__name__}')
        finally:
            if context is not None:
                context.close()
    return result
