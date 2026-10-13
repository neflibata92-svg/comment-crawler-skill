"""小红书只读页面采集：关键词发现笔记，再读取可见评论与楼中楼。"""
from __future__ import annotations

from pathlib import Path
import re
from urllib.parse import urlparse

from ..core.schema import ReviewRecord, clean_text, hash_author, stable_hash
from ..core.utils import CollectionResult


NOTE_PATH = re.compile(r'^/(?:explore|search_result)/([0-9a-fA-F]{24})/?$')
HOME = 'https://www.xiaohongshu.com/explore'


def validate_note_url(url: str) -> str:
    parsed = urlparse(url)
    if (parsed.scheme != 'https' or parsed.hostname not in {'www.xiaohongshu.com', 'xiaohongshu.com'}
            or parsed.username or parsed.password or parsed.port not in (None, 443)
            or not NOTE_PATH.fullmatch(parsed.path)):
        raise ValueError('小红书目标应为 xiaohongshu.com 的 HTTPS 笔记链接')
    return url


def note_id_from_url(url: str) -> str:
    return NOTE_PATH.fullmatch(urlparse(validate_note_url(url)).path).group(1).lower()


def canonical_note_url(url: str) -> str:
    return f'https://www.xiaohongshu.com/explore/{note_id_from_url(url)}'


def xhs_record(raw: dict, url: str) -> ReviewRecord:
    canonical = canonical_note_url(url)
    author = hash_author('xiaohongshu', raw.get('author_id') or raw.get('author'))
    body = clean_text(raw.get('body'))
    published = clean_text(raw.get('time'))
    native_id = clean_text(raw.get('id'))
    external_id = native_id or 'synthetic:' + stable_hash(f'{canonical}|{author}|{published}|{body}')
    return ReviewRecord('xiaohongshu', 'comment', canonical, external_id, body=body,
                        parent_id=clean_text(raw.get('parent_id')), author_hash=author,
                        published_at=published,
                        metadata={'likes': clean_text(raw.get('likes')),
                                  'queries': list(raw.get('queries') or []),
                                  'id_kind': 'platform' if native_id else 'synthetic',
                                  'coverage': 'visible_dom'}).normalize()


SEARCH_ROWS_JS = r'''() => { // SEARCH_ROWS
  const rows = [];
  const sections = document.querySelectorAll('section.note-item, section:has(a[href*="/search_result/"]), section:has(a[href*="/explore/"])');
  for (const section of sections) {
    if (section.classList.contains('query-note-item')) continue;
    const link = section.querySelector('a[href*="/search_result/"], a[href*="/explore/"]');
    if (!link) continue;
    const url = new URL(link.getAttribute('href'), location.href);
    if (url.hostname !== 'www.xiaohongshu.com' && url.hostname !== 'xiaohongshu.com') continue;
    if (!/^\/(?:explore|search_result)\/[0-9a-f]{24}\/?$/i.test(url.pathname)) continue;
    const title = section.querySelector('.title, .note-title, a.title, .footer .title span')?.textContent
      || link.querySelector('span')?.textContent || '';
    rows.push({url: url.href, title: title.trim()});
  }
  return {rows};
}'''

SEARCH_SCROLL_JS = r'''() => {
  const scroller = document.querySelector('.search-layout-wrapper');
  if (scroller && scroller.scrollHeight > scroller.clientHeight) scroller.scrollTop = scroller.scrollHeight;
  else window.scrollTo(0, document.documentElement.scrollHeight);
}'''

COMMENT_ROWS_JS = r'''() => { // COMMENT_ROWS
  const clean = el => (el?.textContent || '').replace(/\s+/g, ' ').trim();
  const author = el => {
    const link = el.querySelector('a[href*="/user/profile/"]');
    const id = link?.getAttribute('href')?.match(/\/user\/profile\/([A-Za-z0-9]+)/)?.[1];
    return {id: id || '', name: clean(el.querySelector('.author-wrapper .name, .user-name, .name'))};
  };
  const id = el => el.getAttribute('data-comment-id') || el.getAttribute('data-id') || '';
  const rows = [];
  for (const root of document.querySelectorAll('.parent-comment')) {
    const item = root.querySelector('.comment-item');
    if (!item) continue;
    const text = clean(item.querySelector('.content, .note-text'));
    if (!text) continue;
    const a = author(item);
    const parentIndex = rows.length;
    rows.push({id: id(item) || id(root), body: text, author_id: a.id, author: a.name,
      time: clean(item.querySelector('.date, .time')), likes: clean(item.querySelector('.count'))});
    for (const reply of root.querySelectorAll('.reply-container .comment-item-sub, .sub-comment-list .comment-item')) {
      const replyText = clean(reply.querySelector('.content, .note-text'));
      if (!replyText) continue;
      const b = author(reply);
      rows.push({id: id(reply), parent_index: parentIndex, body: replyText,
        author_id: b.id, author: b.name, time: clean(reply.querySelector('.date, .time')),
        likes: clean(reply.querySelector('.count'))});
    }
  }
  return {rows};
}'''

EXPAND_REPLIES_JS = r'''() => { // EXPAND_REPLIES
  let clicked = 0;
  for (const root of document.querySelectorAll('.parent-comment')) {
    const buttons = root.querySelectorAll('button, [role="button"], .show-more');
    for (const button of buttons) {
      const label = (button.textContent || '').replace(/\s+/g, ' ').trim();
      if (label.length <= 30 && /展开|更多回复|全部回复|查看.*回复/.test(label)) {
        button.click(); clicked++; break;
      }
    }
  }
  return clicked;
}'''

COMMENT_SCROLL_JS = r'''() => {
  const scroller = document.querySelector('.note-scroller') || document.querySelector('.comments-container');
  if (scroller) scroller.scrollTop = scroller.scrollHeight;
  else window.scrollTo(0, document.documentElement.scrollHeight);
}'''


def check_access(page) -> None:
    parsed = urlparse(page.url)
    if parsed.scheme != 'https' or parsed.hostname not in {'www.xiaohongshu.com', 'xiaohongshu.com'}:
        raise ValueError('页面跳转到非预期域名，停止采集')
    if any(part in parsed.path.lower() for part in ('captcha', 'login', 'error')):
        raise ValueError('页面要求登录或验证，停止采集')


def discover_notes(page, delay: float, result: CollectionResult, *, stable_rounds: int = 6) -> list[dict]:
    notes: dict[str, dict] = {}
    stable = 0
    while True:
        check_access(page)
        snapshot = page.evaluate(SEARCH_ROWS_JS)
        if isinstance(snapshot, list):  # 方便独立测试旧式页面提取返回值。
            snapshot = {'rows': snapshot}
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get('rows'), list):
            raise ValueError('搜索结果页面结构发生变化')
        before = len(notes)
        for row in snapshot['rows']:
            try:
                key = note_id_from_url(row['url'])
            except (KeyError, ValueError, TypeError):
                continue
            notes.setdefault(key, {'url': row['url'], 'title': clean_text(row.get('title'))})
        if not notes and stable >= stable_rounds - 1:
            result.status = 'backend_limited'
            result.warnings.append('未找到笔记卡片；无法区分空结果、登录限制或页面结构变化')
            return []
        stable = stable + 1 if len(notes) == before else 0
        if stable >= stable_rounds:
            result.status = 'stalled'
            result.warnings.append('搜索结果连续多轮无新增；不证明关键词覆盖全部笔记')
            return list(notes.values())
        page.evaluate(SEARCH_SCROLL_JS)
        page.wait_for_timeout(max(1000, delay * 1000))


def collect_note_comments(page, url: str, result: CollectionResult, delay: float,
                          *, stable_rounds: int = 6, queries: list[str] | None = None) -> None:
    seen: dict[str, str] = {}
    stable = 0
    while True:
        check_access(page)
        snapshot = page.evaluate(COMMENT_ROWS_JS)
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get('rows'), list):
            raise ValueError('评论页面结构发生变化')
        raw_rows = snapshot['rows']
        parent_ids: dict[int, str] = {}
        changed = 0
        for index, raw in enumerate(raw_rows):
            if not isinstance(raw, dict) or not clean_text(raw.get('body')):
                continue
            if 'parent_index' in raw:
                parent_id = parent_ids.get(raw['parent_index'])
                if not parent_id:
                    continue
                raw = {**raw, 'parent_id': parent_id}
            record = xhs_record({**raw, 'queries': queries or []}, url)
            if 'parent_index' not in raw:
                parent_ids[index] = record.external_id
            if seen.get(record.record_key) != record.content_hash:
                result.add(record)
                seen[record.record_key] = record.content_hash
                changed += 1
        page.evaluate(EXPAND_REPLIES_JS)
        if not seen and stable >= stable_rounds - 1:
            result.status = 'backend_limited'
            result.warnings.append(f'{canonical_note_url(url)} 未找到评论结构；无法区分无评论、登录限制或页面变化')
            return
        # 展开按钮若始终留在 DOM 中，不能让重复点击造成无限循环。
        stable = stable + 1 if not changed else 0
        if stable >= stable_rounds:
            result.status = 'stalled'
            result.warnings.append(f'{canonical_note_url(url)} 评论连续多轮无新增；不证明评论全量')
            return
        page.evaluate(COMMENT_SCROLL_JS)
        page.wait_for_timeout(max(1000, delay * 1000))


def _open(page, url: str) -> None:
    response = page.goto(url, wait_until='domcontentloaded', timeout=60000)
    if response is None or response.status >= 400:
        raise ValueError(f'页面请求失败 HTTP {response.status if response else "unknown"}')
    check_access(page)


def collect_xiaohongshu(config: dict, delay: float, emit=None) -> CollectionResult:
    from playwright.sync_api import sync_playwright

    result = CollectionResult('xiaohongshu', emit=emit)
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(str(Path(config['profile']).expanduser().resolve()), headless=False)
        try:
            page = context.new_page()
            notes: dict[str, dict] = {}
            if config.get('target'):
                url = validate_note_url(config['target'])
                notes[note_id_from_url(url)] = {'url': url, 'title': '', 'queries': []}
            for query in config.get('queries', []):
                _open(page, HOME)
                search = page.locator('input#search-input, input[placeholder*="搜索"]').first
                search.fill(query)
                button = page.locator('.search-icon').first
                if button.count():
                    button.click()
                else:
                    search.press('Enter')
                page.wait_for_timeout(max(1000, delay * 1000))
                check_access(page)
                if urlparse(page.url).path not in ('/search_result', '/search_result_ai'):
                    raise ValueError('提交关键词后未进入搜索结果页，停止采集')
                for note in discover_notes(page, delay, result):
                    key = note_id_from_url(note['url'])
                    entry = notes.setdefault(key, {**note, 'queries': []})
                    if query not in entry['queries']:
                        entry['queries'].append(query)
            for note in notes.values():
                _open(page, note['url'])
                collect_note_comments(page, note['url'], result, delay, queries=note.get('queries'))
            result.warnings.append(f'本次发现或指定 {len(notes)} 篇笔记；仅覆盖页面可见搜索结果和评论')
        except Exception as exc:
            # Playwright 异常可能携带 xsec_token；只保留异常类型。
            result.errors.append(str(exc) if isinstance(exc, ValueError) else f'浏览器运行失败：{type(exc).__name__}')
            result.status = 'failed'
        finally:
            context.close()
    return result


def login_xiaohongshu(profile: str) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(str(Path(profile).expanduser().resolve()), headless=False)
        try:
            page = context.new_page()
            page.goto(HOME, timeout=60000)
            page.wait_for_timeout(2000)
            # 登录入口本身可以带 /login；只在平台拒绝或要求验证时提前退出。
            if any(part in urlparse(page.url).path.lower() for part in ('captcha', 'error')):
                raise ValueError('页面出现验证或安全限制，停止登录流程')
            input('请在浏览器完成自己的小红书登录，成功后回终端按回车保存会话：')
            check_access(page)
        finally:
            context.close()
    print('本地浏览器未显示登录或验证拦截；是否有搜索和评论权限仍需真实采集核对。')
