"""小红书只读页面采集：发现笔记，保存可见帖文字段与评论楼层。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
from urllib.parse import quote, urlparse

from ..core.schema import ReviewRecord, clean_text, hash_author, stable_hash, utc_now
from ..core.utils import CollectionResult, validate_browser_profile_path


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


def page_note_id(page) -> str | None:
    """读取当前页面地址路径中的笔记 ID；不是笔记页（如 /404 拦截页）时返回 None。

    被平台拦截时笔记 ID 只出现在被 URL 编码的查询参数里，路径本身是 /404，
    因此只看路径即可区分「真的打开了这篇笔记」和「被重定向到拦截页」。
    """
    match = NOTE_PATH.fullmatch(urlparse(page.url).path)
    return match.group(1).lower() if match else None


def search_url(query: str) -> str:
    """关键词直接拼成 AI 搜索结果页地址。

    2026-10 页面上的搜索框组件处于隐藏状态（宽高为 0），「打开首页打字再点搜索」
    的流程会因元素不可见而超时；直接打开搜索结果页地址与人工搜索等效。
    2026-10-13 实测 search_result_ai 入口对已登录用户返回标准笔记卡片
    （section.note-item），与旧版 search_result 布局一致，可直接采集。
    """
    return f'https://www.xiaohongshu.com/search_result_ai?keyword={quote(query)}'


def normalize_xhs_time(value, captured_at: str | None = None) -> tuple[str, str, str]:
    """Return UTC ISO time, the original display text, and its precision label."""
    raw = clean_text(value)
    if not raw:
        return '', '', 'missing'
    local_zone = datetime.now().astimezone().tzinfo or timezone.utc
    now = datetime.now().astimezone()
    if captured_at:
        try:
            captured = datetime.fromisoformat(captured_at.replace('Z', '+00:00'))
            if captured.tzinfo is None:
                captured = captured.replace(tzinfo=timezone.utc)
            now = captured.astimezone(local_zone)
        except ValueError:
            pass

    display = re.sub(r'\s*IP属地[:：].*$', '', raw).strip()
    display = re.sub(r'^(?:发布于|编辑于)\s*', '', display)

    def as_utc(value: datetime, precision: str) -> tuple[str, str, str]:
        if value.tzinfo is None:
            value = value.replace(tzinfo=local_zone)
        normalized = value.astimezone(timezone.utc).replace(microsecond=0).isoformat()
        return normalized, raw, precision

    iso_text = display[:-1] + '+00:00' if display.endswith('Z') else display
    iso_text = iso_text.replace('/', '-')
    try:
        parsed = datetime.fromisoformat(iso_text)
    except ValueError:
        parsed = None
    if parsed is not None:
        precision = 'exact' if re.search(r'[T ]\d{1,2}:\d{2}', display) else 'day'
        return as_utc(parsed, precision)

    chinese_date = re.fullmatch(
        r'(\d{4})年(\d{1,2})月(\d{1,2})日(?:\s+(\d{1,2}):(\d{2}))?', display
    )
    if chinese_date:
        year, month, day, hour, minute = chinese_date.groups()
        parsed = datetime(int(year), int(month), int(day), int(hour or 0), int(minute or 0), tzinfo=local_zone)
        return as_utc(parsed, 'exact' if hour else 'day')

    relative = re.fullmatch(r'(\d+)\s*(分钟前|小时前|天前|周前)', display)
    if relative:
        amount = int(relative.group(1))
        unit = relative.group(2)
        delta = {'分钟前': timedelta(minutes=amount), '小时前': timedelta(hours=amount),
                 '天前': timedelta(days=amount), '周前': timedelta(weeks=amount)}[unit]
        return as_utc(now - delta, 'estimated_relative')
    if display in {'刚刚', '刚才'}:
        return as_utc(now, 'estimated_relative')

    day_delta = {'昨天': 1, '前天': 2, '今天': 0}
    relative_day = re.fullmatch(r'(昨天|前天|今天)(?:\s+(\d{1,2}):(\d{2}))?', display)
    if relative_day:
        label, hour, minute = relative_day.groups()
        date = (now - timedelta(days=day_delta[label])).date()
        parsed = datetime(date.year, date.month, date.day, int(hour or 0), int(minute or 0), tzinfo=local_zone)
        return as_utc(parsed, 'estimated_day' if hour else 'estimated_day')

    month_day = re.fullmatch(r'(\d{1,2})[-月](\d{1,2})(?:日)?(?:\s+(\d{1,2}):(\d{2}))?', display)
    if month_day:
        month, day, hour, minute = month_day.groups()
        year = now.year
        candidate = datetime(year, int(month), int(day), int(hour or 0), int(minute or 0), tzinfo=local_zone)
        if candidate > now + timedelta(days=1):
            candidate = candidate.replace(year=year - 1)
        return as_utc(candidate, 'estimated_year')
    return '', raw, 'unparsed'


def xhs_record(raw: dict, url: str) -> ReviewRecord:
    canonical = canonical_note_url(url)
    author = hash_author('xiaohongshu', raw.get('author_id') or raw.get('author'))
    body = clean_text(raw.get('body'))
    captured_at = clean_text(raw.get('captured_at')) or utc_now()
    published, published_raw, time_precision = normalize_xhs_time(raw.get('time'), captured_at)
    native_id = clean_text(raw.get('id'))
    parent_id = clean_text(raw.get('parent_id'))
    # Relative display times move between runs; content identity stays stable so a rescan updates one row.
    external_id = native_id or 'synthetic:' + stable_hash(f'{canonical}|{parent_id}|{body}')
    metadata = {'likes': clean_text(raw.get('likes')),
                'queries': list(raw.get('queries') or []),
                'id_kind': 'platform' if native_id else 'synthetic',
                'coverage': 'visible_dom',
                'published_at_raw': published_raw,
                'published_at_precision': time_precision}
    return ReviewRecord('xiaohongshu', 'comment', canonical, external_id, body=body,
                        parent_id=parent_id, author_hash=author,
                        published_at=published, captured_at=captured_at,
                        metadata=metadata).normalize()


def xhs_post_record(raw: dict, url: str) -> ReviewRecord:
    canonical = canonical_note_url(url)
    note_id = note_id_from_url(url)
    title = clean_text(raw.get('title'))
    body = clean_text(raw.get('body'))
    author = hash_author('xiaohongshu', raw.get('author_id') or raw.get('author'))
    visible_engagement = {
        key: clean_text(raw.get(key))
        for key in ('likes', 'saves', 'comments', 'shares')
    }
    completeness = 'full' if title and body else 'partial' if title or body else 'index_summary'
    captured_at = clean_text(raw.get('captured_at')) or utc_now()
    published, published_raw, time_precision = normalize_xhs_time(
        raw.get('published_at') or raw.get('time'), captured_at
    )
    return ReviewRecord(
        'xiaohongshu', 'post', canonical, f'note:{note_id}', title=title, body=body,
        content_completeness=completeness, author_hash=author,
        published_at=published, captured_at=captured_at,
        metadata={'queries': list(raw.get('queries') or []),
                  'visible_engagement': visible_engagement,
                  'id_kind': 'platform',
                  'coverage': 'visible_dom',
                  'published_at_raw': published_raw,
                  'published_at_precision': time_precision}).normalize()


SEARCH_ROWS_JS = r'''() => { // SEARCH_ROWS
  const rows = [];
  const sections = document.querySelectorAll('section.note-item, section:has(a[href*="/search_result/"]), section:has(a[href*="/explore/"])');
  for (const section of sections) {
    if (section.classList.contains('query-note-item')) continue;
    const link = section.querySelector('a[href*="/search_result/"]') || section.querySelector('a[href*="/explore/"]');
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

NOTE_DETAILS_JS = r'''() => { // NOTE_DETAILS
  const clean = el => (el?.textContent || '').replace(/\s+/g, ' ').trim();
  const noteRoot = document.querySelector('#noteContainer, .note-detail, .note-content') || document;
  const text = selectors => {
    for (const selector of selectors) {
      const value = clean(noteRoot.querySelector(selector) || document.querySelector(selector));
      if (value) return value;
    }
    return '';
  };
  const author = noteRoot.querySelector('.author-wrapper') || document.querySelector('.author-wrapper');
  const profile = author?.querySelector('a[href*="/user/profile/"]');
  const authorId = profile?.getAttribute('href')?.match(/\/user\/profile\/([A-Za-z0-9_-]+)/)?.[1] || '';
  const count = selector => clean(noteRoot.querySelector(selector));
  return {
    title: text(['#detail-title', '.note-content .title', '.note-detail .title']),
    body: text(['#detail-desc', '.note-content .desc', '.note-detail .desc']),
    author_id: authorId,
    author: clean(author?.querySelector('.name, .user-name, .nickname')),
    published_at: text(['.note-content .date', '.note-content .time', '.note-detail .date', '.note-detail .time']),
    likes: count('.like-wrapper .count'),
    saves: count('.collect-wrapper .count'),
    comments: count('.chat-wrapper .count, .comment-wrapper .count'),
    shares: count('.share-wrapper .count')
  };
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


def discover_notes(page, delay: float, result: CollectionResult, *, stable_rounds: int = 6,
                   on_note=None) -> list[dict]:
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
            if key not in notes:
                note = {'url': row['url'], 'title': clean_text(row.get('title'))}
                notes[key] = note
                if on_note:
                    on_note(note)
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
                          *, stable_rounds: int = 6, queries: list[str] | None = None) -> bool:
    seen: dict[str, str] = {}
    stable = 0
    while True:
        check_access(page)
        snapshot = page.evaluate(COMMENT_ROWS_JS)
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get('rows'), list):
            raise ValueError('评论页面结构发生变化')
        raw_rows = snapshot['rows']
        parent_ids: dict[int, str] = {}
        new_records = 0
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
            if record.metadata.get('id_kind') == 'synthetic' and record.record_key in seen:
                continue
            if seen.get(record.record_key) != record.content_hash:
                is_new = record.record_key not in seen
                result.add(record)
                seen[record.record_key] = record.content_hash
                new_records += int(is_new)
        page.evaluate(EXPAND_REPLIES_JS)
        if not seen and stable >= stable_rounds - 1:
            result.status = 'backend_limited'
            result.warnings.append(f'{canonical_note_url(url)} 未找到评论结构；无法区分无评论、登录限制或页面变化')
            return False
        # 展开按钮若始终留在 DOM 中，不能让重复点击造成无限循环。
        stable = stable + 1 if not new_records else 0
        if stable >= stable_rounds:
            result.status = 'stalled'
            result.warnings.append(f'{canonical_note_url(url)} 评论连续多轮无新增；不证明评论全量')
            return True
        page.evaluate(COMMENT_SCROLL_JS)
        page.wait_for_timeout(max(1000, delay * 1000))


def _open(page, url: str) -> None:
    response = page.goto(url, wait_until='domcontentloaded', timeout=60000)
    if response is None or response.status >= 400:
        raise ValueError(f'页面请求失败 HTTP {response.status if response else "unknown"}')
    check_access(page)


class XhsProgress:
    """Atomic per-note checkpoint; signed browser URLs and profile data are never persisted."""

    def __init__(self, path: Path, task: dict, existing_note_ids=()):
        self.path = path
        self.task = task
        self.notes: dict[str, dict] = {}
        if self.path.exists():
            try:
                payload = json.loads(self.path.read_text(encoding='utf-8'))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError('progress.json 无法读取；请检查任务目录') from exc
            if (not isinstance(payload, dict) or payload.get('version') not in {1, 2}
                    or payload.get('task') != self.task or not isinstance(payload.get('notes'), dict)):
                raise ValueError('progress.json 与当前任务不一致或格式错误；请检查任务目录')
            self.notes = payload['notes']
            version = payload['version']
            valid_statuses = {'pending', 'in_progress', 'scanned'}
            if version == 1:
                valid_statuses.add('completed')
            for note_id, note in self.notes.items():
                if (not re.fullmatch(r'[0-9a-f]{24}', note_id) or not isinstance(note, dict)
                        or note.get('status') not in valid_statuses
                        or not isinstance(note.get('title', ''), str)
                        or not isinstance(note.get('queries', []), list)
                        or any(not isinstance(query, str) for query in note.get('queries', []))):
                    raise ValueError('progress.json 中的笔记检查点格式错误；请检查任务目录')
                if version == 1 and note.get('status') == 'completed':
                    note['status'] = 'scanned'
        for note_id in existing_note_ids:
            if re.fullmatch(r'[0-9a-f]{24}', str(note_id)):
                self.register_note(str(note_id))
        self.save()

    def register_note(self, note_id: str, title: str = '', query: str = '') -> None:
        note = self.notes.setdefault(note_id, {'title': '', 'queries': [], 'status': 'pending'})
        if title:
            note['title'] = title
        if query and query not in note['queries']:
            note['queries'].append(query)

    def mark(self, note_id: str, status: str) -> None:
        if status not in {'pending', 'in_progress', 'scanned'}:
            raise ValueError('无效的小红书检查点状态')
        self.notes[note_id]['status'] = status
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {'version': 2, 'task': self.task, 'notes': self.notes}
        temp = self.path.with_suffix(self.path.suffix + '.tmp')
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        temp.replace(self.path)


def collect_xiaohongshu(config: dict, delay: float, emit=None) -> CollectionResult:
    from playwright.sync_api import sync_playwright

    result = CollectionResult('xiaohongshu', emit=emit)
    target = validate_note_url(config['target']) if config.get('target') else ''
    task = {'queries': list(config.get('queries', [])),
            'target': note_id_from_url(target) if target else ''}
    output_dir = config.get('output_dir') or config.get('output')
    progress = XhsProgress(Path(output_dir) / 'progress.json', task,
                           config.get('existing_post_ids', [])) if output_dir else None
    profile = validate_browser_profile_path(config['profile'])
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(profile, headless=False)
        try:
            page = context.new_page()
            notes: dict[str, dict] = {}
            if target:
                key = note_id_from_url(target)
                notes[key] = {'url': target, 'title': '', 'queries': []}
                if progress:
                    progress.register_note(key)
            for query in config.get('queries', []):
                # 搜索框组件隐藏导致打字流程超时，改为直接打开关键词结果页。
                _open(page, search_url(query))
                page.wait_for_timeout(max(1000, delay * 1000))
                check_access(page)
                if urlparse(page.url).path not in ('/search_result', '/search_result_ai'):
                    raise ValueError('提交关键词后未进入搜索结果页，停止采集')
                def register_discovered_note(note):
                    key = note_id_from_url(note['url'])
                    entry = notes.setdefault(key, {**note, 'queries': []})
                    entry['title'] = entry.get('title') or note.get('title', '')
                    if query not in entry['queries']:
                        entry['queries'].append(query)
                    if progress:
                        progress.register_note(key, note.get('title', ''), query)
                        progress.save()

                discover_notes(page, delay, result, on_note=register_discovered_note)

            if progress:
                for note_id, saved in progress.notes.items():
                    entry = notes.setdefault(note_id, {
                        'url': f'https://www.xiaohongshu.com/explore/{note_id}',
                        'title': saved.get('title', ''), 'queries': [],
                    })
                    entry['title'] = entry.get('title') or saved.get('title', '')
                    for query in saved.get('queries', []):
                        if query not in entry['queries']:
                            entry['queries'].append(query)
            blocked = 0
            opened = 0
            for note_id, note in notes.items():
                if (progress and not config.get('refresh_completed')
                        and progress.notes.get(note_id, {}).get('status') == 'scanned'):
                    continue
                if progress:
                    progress.mark(note_id, 'in_progress')
                _open(page, note['url'])
                if page_note_id(page) != note_id:
                    # 平台把当前地址重定向到 /404 等拦截页；跳过该笔记，不采拦截页内容。
                    blocked += 1
                    result.warnings.append(f'{canonical_note_url(note["url"])} 未能打开（平台拦截或令牌失效）；跳过')
                    if progress:
                        progress.mark(note_id, 'pending')
                    if blocked >= 3:
                        result.status = 'backend_limited'
                        result.warnings.append('连续多篇笔记被拦截；停止采集，报告原因而不继续硬试')
                        break
                    continue
                blocked = 0
                opened += 1
                page.wait_for_timeout(max(1000, delay * 1000))
                try:
                    post_data = page.evaluate(NOTE_DETAILS_JS)
                    if not isinstance(post_data, dict):
                        post_data = {}
                        result.warnings.append(f'{canonical_note_url(note["url"])} 帖文字段结构异常；仍继续读取评论')
                except Exception as exc:
                    post_data = {}
                    result.warnings.append(
                        f'{canonical_note_url(note["url"])} 帖文字段读取失败：{type(exc).__name__}；仍继续读取评论'
                    )
                post_data = {**post_data,
                             'title': clean_text(post_data.get('title') or note.get('title')),
                             'queries': note.get('queries', [])}
                result.add(xhs_post_record(post_data, note['url']))
                if not post_data.get('body'):
                    result.warnings.append(f'{canonical_note_url(note["url"])} 未读取到笔记正文；已保存可获得的字段')
                comments_complete = collect_note_comments(page, note['url'], result, delay, queries=note.get('queries'))
                if progress:
                    progress.mark(note_id, 'scanned' if comments_complete else 'pending')
            if notes and opened == 0 and result.status not in ('backend_limited', 'failed'):
                result.status = 'backend_limited'
                result.warnings.append('所有笔记都未能打开；本次没有可交付的评论数据')
            result.warnings.append(f'本次发现或指定 {len(notes)} 篇笔记；仅覆盖页面可见笔记字段、搜索结果和评论')
            if progress:
                if config.get('refresh_completed'):
                    result.warnings.append('已按要求重新扫描此前结束可见扫描的笔记；结果仍仅限页面可见内容')
                else:
                    result.warnings.append('已结束可见扫描的笔记下次默认跳过；可用 --refresh-completed 重新扫描')
                result.warnings.append('中断中的笔记会重新扫描评论并按记录键去重')
        except Exception as exc:
            # Playwright 异常可能携带 xsec_token；只保留异常类型。
            result.errors.append(str(exc) if isinstance(exc, ValueError) else f'浏览器运行失败：{type(exc).__name__}')
            result.status = 'failed'
        finally:
            context.close()
    return result


def login_xiaohongshu(profile: str) -> None:
    from playwright.sync_api import sync_playwright

    profile = validate_browser_profile_path(profile)
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(profile, headless=False)
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
