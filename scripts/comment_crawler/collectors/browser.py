"""普通 Playwright 浏览器采集；不伪装指纹，不在访问限制后重试。"""
from __future__ import annotations

import html
import json
from pathlib import Path
import re
import time
from urllib.parse import parse_qs, urlencode, urlparse

from ..core.schema import ReviewRecord, clean_text, hash_author, stable_hash
from ..core.utils import CollectionResult
from .taobao_dom import EXTRACT_JS, OPEN_DRAWER_JS, SCROLL_DRAWER_JS


def validate_target(source: str, target: str) -> str:
    if source == 'jd' and target.isdigit():
        target = f'https://item.jd.com/{target}.html'
    parsed = urlparse(target)
    allowed = {
        'jd': {'item.jd.com'},
        'taobao': {'item.taobao.com', 'detail.tmall.com'},
        'kickstarter': {'www.kickstarter.com', 'kickstarter.com'},
    }
    if parsed.scheme != 'https' or parsed.hostname not in allowed[source] or parsed.username or parsed.port not in (None, 443):
        raise ValueError('目标必须是对应平台的 HTTPS 商品或项目链接')
    if source == 'jd' and not re.fullmatch(r'/\d+\.html', parsed.path):
        raise ValueError('京东目标应为商品 ID 或 item.jd.com/数字.html')
    if source == 'taobao' and not (parse_qs(parsed.query).get('id', [''])[0]).isdigit():
        raise ValueError('淘宝或天猫商品链接缺少数字 id')
    if source == 'kickstarter' and not re.fullmatch(r'/projects/[^/]+/[^/]+/comments/?', parsed.path):
        raise ValueError('Kickstarter 目标应为项目的 /comments 页面')
    return target


def jd_record(item: dict, url: str) -> ReviewRecord:
    author = hash_author('jd', item.get('nickname'))
    body = clean_text(item.get('content'))
    sku = ' / '.join(str(v) for v in (item.get('productColor'), item.get('productSize')) if v)
    native_id = clean_text(item.get('id') or item.get('guid'))
    key = native_id or 'synthetic:' + stable_hash(f'{url}|{author}|{item.get("creationTime")}|{sku}|{body}')
    append = ''
    for name in ('afterUserReply', 'addFeedback', 'afterUserReplyStr'):
        value = item.get(name)
        if value:
            append = clean_text(value.get('content') if isinstance(value, dict) else value)
            break
    return ReviewRecord('jd', 'comment', url, key, body=body, author_hash=author,
                        published_at=item.get('creationTime', ''), score=item.get('usefulVoteCount'), rating=item.get('score'),
                        metadata={'sku': sku, 'append': append, 'images': len(item.get('images') or []),
                                  'id_kind': 'platform' if native_id else 'synthetic'}).normalize()


def taobao_record(raw: dict, url: str) -> ReviewRecord:
    meta = clean_text(raw.get('meta'))
    date = re.search(r'20\d{2}[-年]\d{1,2}[-月]\d{1,2}日?', meta)
    author = hash_author('taobao', raw.get('user'))
    body = clean_text(raw.get('content'))
    key = 'synthetic:' + stable_hash(f'{url}|{author}|{meta}|{body}')
    return ReviewRecord('taobao', 'comment', url, key, body=body, author_hash=author,
                        published_at=date.group(0) if date else '',
                        metadata={'product_meta': meta, 'append': clean_text(raw.get('append')),
                                  'likes': clean_text(raw.get('likes')), 'images': raw.get('imgs', 0),
                                  'id_kind': 'synthetic', 'coverage': 'visible_dom'}).normalize()


def kickstarter_record(item: dict, url: str) -> ReviewRecord:
    if item.get('id') is None:
        raise ValueError('Kickstarter 评论缺少 ID')
    parent = item.get('parent_id') or item.get('parent_comment_id')
    return ReviewRecord('kickstarter', 'comment', url, str(item['id']), body=clean_text(item.get('body')),
                        parent_id=str(parent) if parent else '',
                        author_hash=hash_author('kickstarter', (item.get('author') or {}).get('id') or (item.get('author') or {}).get('name')),
                        published_at=item.get('created_at', ''),
                        metadata={'reply_relationship': 'provided' if parent else 'not_provided',
                                  'coverage': 'returned_comments_only'}).normalize()


def navigate(page, url: str) -> None:
    response = page.goto(url, wait_until='domcontentloaded', timeout=60000)
    if response is None or response.status >= 400:
        raise ValueError(f'页面请求失败 HTTP {response.status if response else "unknown"}')
    expected = urlparse(url).hostname
    final = urlparse(page.url)
    allowed = {expected}
    if expected in ('kickstarter.com', 'www.kickstarter.com'):
        allowed = {'kickstarter.com', 'www.kickstarter.com'}
    if final.scheme != 'https' or final.hostname not in allowed:
        raise ValueError('页面跳转到非预期域名，停止采集')
    if any(part in page.url.lower() for part in ('login.', '/login', 'passport.', 'captcha', 'punish')):
        raise ValueError('页面要求登录或验证，停止采集')


def json_page(page, url: str) -> dict:
    navigate(page, url)
    text = page.inner_text('body')
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise ValueError('响应不是 JSON，可能需要验证或接口已经变化') from None
    if not isinstance(data, dict):
        raise ValueError('接口响应结构发生变化')
    return data


def collect_jd(page, url: str, result: CollectionResult, delay: float) -> None:
    product = re.search(r'/(\d+)\.html', url).group(1)
    seen_pages = set()
    page_no = 0
    while True:
        query = urlencode({'productId': product, 'score': 0, 'sortType': 5, 'page': page_no,
                           'pageSize': 10, 'isShadowSku': 0, 'fold': 1})
        payload = json_page(page, 'https://club.jd.com/comment/productPageComments.action?' + query)
        comments = payload.get('comments')
        if not isinstance(comments, list):
            raise ValueError('响应缺少 comments，不能视为采集结束')
        if not comments:
            return
        signature = stable_hash(json.dumps(comments, sort_keys=True))
        if signature in seen_pages:
            raise ValueError('重复评论页，停止以避免循环')
        seen_pages.add(signature)
        for item in comments:
            result.add(jd_record(item, url))
        page_no += 1
        time.sleep(delay)


def check_taobao(page) -> None:
    if page.evaluate("""() => !!document.querySelector('#baxia-dialog, .nc-container, iframe[src*="captcha"], iframe[src*="punish"]') || /滑动验证|安全检查/.test(document.body.innerText) || /login|punish/.test(location.href)"""):
        raise ValueError('出现验证或登录限制，停止采集')


def collect_taobao(page, url: str, result: CollectionResult, delay: float) -> None:
    navigate(page, url)
    page.wait_for_timeout(3000)
    check_taobao(page)
    page.mouse.wheel(0, 3000)
    page.wait_for_timeout(2000)
    if not page.evaluate(OPEN_DRAWER_JS):
        raise ValueError('未找到评论抽屉按钮；需核对页面选择器')
    page.wait_for_timeout(3000)
    seen = {}
    stable = 0
    while True:
        check_taobao(page)
        if not page.evaluate(SCROLL_DRAWER_JS):
            raise ValueError('评论抽屉未加载或已关闭')
        page.wait_for_timeout(max(1000, delay * 1000))
        changed = 0
        for raw in page.evaluate(EXTRACT_JS):
            record = taobao_record(raw, url)
            if seen.get(record.record_key) != record.content_hash:
                result.add(record)
                seen[record.record_key] = record.content_hash
                changed += 1
        stable = stable + 1 if not changed else 0
        if stable >= 6:
            result.status = 'stalled'
            result.warnings.append('连续 6 轮无新增或更新，仅表示当前页面停止加载，不证明平台全量')
            return


def collect_kickstarter(page, url: str, result: CollectionResult, delay: float) -> None:
    navigate(page, url)
    page.wait_for_timeout(3000)
    match = re.search(r'"comments":\s*"(https://api\.kickstarter\.com/v1/projects/\d+/comments\?[^"]+)"', html.unescape(page.content()))
    if not match:
        raise ValueError('留言页不再提供预期评论入口；需核对页面，不继续猜测接口')
    next_url = match.group(1)
    seen = set()
    result.status = 'backend_limited'
    result.warnings.append('保存接口返回的评论及其已有 parent_id；未证实接口覆盖全部子回复')
    while next_url:
        parsed = urlparse(next_url)
        if parsed.scheme != 'https' or parsed.hostname != 'api.kickstarter.com' or parsed.username or parsed.port not in (None, 443):
            raise ValueError('下一页地址不属于预期评论接口')
        if next_url in seen:
            raise ValueError('重复分页地址，停止采集')
        seen.add(next_url)
        data = json_page(page, next_url)
        comments = data.get('comments')
        if not isinstance(comments, list):
            raise ValueError('评论接口缺少 comments')
        for item in comments:
            if not item.get('deleted_at'):
                result.add(kickstarter_record(item, url))
        next_url = ((data.get('urls') or {}).get('api') or {}).get('more_comments', '')
        if next_url:
            time.sleep(delay)


def browser_collect(source: str, target: str, profile: str | None, delay: float, emit=None) -> CollectionResult:
    from playwright.sync_api import sync_playwright
    target = validate_target(source, target)
    result = CollectionResult(source, emit=emit)
    with sync_playwright() as pw:
        browser = None
        context = None
        try:
            if source in ('taobao', 'jd'):
                if not profile:
                    raise ValueError('此平台需要 --profile 指向已登录的专用本地浏览器目录')
                context = pw.chromium.launch_persistent_context(str(Path(profile).expanduser().resolve()), headless=False)
            else:
                browser = pw.chromium.launch(headless=True)
                context = browser.new_context()
            page = context.new_page()
            {'jd': collect_jd, 'taobao': collect_taobao, 'kickstarter': collect_kickstarter}[source](page, target, result, delay)
        except Exception as exc:
            # Playwright 错误可能包含带签名的 URL，避免写入公开日志。
            result.errors.append(str(exc) if isinstance(exc, ValueError) else f'浏览器运行失败：{type(exc).__name__}')
            result.status = 'failed'
        finally:
            if context is not None:
                context.close()
            if browser is not None:
                browser.close()
    return result


def login(source: str, profile: str) -> None:
    from playwright.sync_api import sync_playwright
    url = {'jd': 'https://passport.jd.com/new/login.aspx', 'taobao': 'https://login.taobao.com'}[source]
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(str(Path(profile).expanduser().resolve()), headless=False)
        try:
            context.new_page().goto(url, timeout=60000)
            input('请在浏览器完成自己的账户登录，成功后回终端按回车保存会话：')
        finally:
            context.close()
    print('会话已保存在本地；尚未验证商品评论访问权限。')
