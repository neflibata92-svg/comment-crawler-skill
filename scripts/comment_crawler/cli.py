"""评论采集命令行：一项任务一个平台／后端，输出与安装目录分离。"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys

from .core.schema import utc_now
from .core.storage import ReviewStore
from .core.utils import CollectionResult, load_json

SOURCES = ('youtube', 'reddit', 'reddit_opencli', 'taobao', 'jd', 'kickstarter', 'xiaohongshu')


def dispatch(source, config, output, emit):
    crawl = {'delay_seconds': config.get('delay_seconds', 2), 'timeout_seconds': config.get('timeout_seconds', 60)}
    if source == 'youtube':
        from .collectors.youtube import YouTubeCollector
        return YouTubeCollector(config, crawl, emit=emit).collect()
    if source == 'reddit':
        from .collectors.reddit import RedditCollector
        return RedditCollector(config, crawl, emit=emit).collect()
    if source == 'reddit_opencli':
        from .collectors.reddit_opencli import OpenCLIRedditCollector
        return OpenCLIRedditCollector(config, crawl, emit=emit).collect()
    if source == 'xiaohongshu':
        from .collectors.xiaohongshu import collect_xiaohongshu
        return collect_xiaohongshu(config, crawl['delay_seconds'], emit)
    from .collectors.browser import browser_collect
    return browser_collect(source, config['target'], config.get('profile'), crawl['delay_seconds'], emit)


def parser():
    root = argparse.ArgumentParser(description='跨平台评论采集 Skill 工具（默认不截断总页数）')
    sub = root.add_subparsers(dest='command', required=True)
    sub.add_parser('doctor', help='离线检查依赖和凭据是否存在，不显示密钥')
    login = sub.add_parser('login', help='打开浏览器供用户自行登录')
    login.add_argument('source', choices=('taobao', 'jd', 'xiaohongshu'))
    login.add_argument('--profile', required=True)
    collect = sub.add_parser('collect', help='运行单一平台／后端')
    collect.add_argument('source', choices=SOURCES)
    collect.add_argument('--config', help='JSON 配置，可含平台同名节')
    collect.add_argument('--query', action='append', help='可重复传入关键词')
    collect.add_argument('--subreddit', action='append')
    collect.add_argument('--target', help='商品／项目／小红书笔记 URL；京东也接受数字 ID')
    collect.add_argument('--profile', help='用户专用的本地浏览器档案目录')
    collect.add_argument('--output', required=True, help='任务输出目录；恢复时用相同目录')
    collect.add_argument('--delay', type=float, help='请求间隔秒数，必须大于 0')
    collect.add_argument('--dry-run', action='store_true', help='只校验输入，不联网、不写输出')
    for name in ('export', 'check'):
        command = sub.add_parser(name)
        command.add_argument('--output', required=True)
    return root


def resolve_config(args):
    config = {}
    config_dir = Path.cwd()
    if args.config:
        payload, config_dir = load_json(args.config)
        section = payload.get(args.source, payload)
        if not isinstance(section, dict):
            raise ValueError('平台配置必须是 JSON 对象')
        config.update(section)
    for name, key in [('query', 'queries'), ('subreddit', 'subreddits'), ('target', 'target'), ('profile', 'profile'), ('delay', 'delay_seconds')]:
        value = getattr(args, name)
        if value is not None:
            config[key] = value
    for key in ('queries', 'subreddits'):
        values = config.get(key, [])
        if not isinstance(values, list) or any(not isinstance(v, str) or not v.strip() for v in values):
            raise ValueError(f'{key} 应为非空字符串数组')
    if args.source in ('youtube', 'reddit', 'reddit_opencli'):
        if not config.get('queries'):
            raise ValueError('请提供 --query 或配置 queries')
    elif args.source == 'xiaohongshu':
        from .collectors.xiaohongshu import validate_note_url
        if not config.get('queries') and not config.get('target'):
            raise ValueError('小红书需要 --query 或 --target')
        if config.get('target'):
            config['target'] = validate_note_url(str(config['target']))
        if not config.get('profile'):
            raise ValueError('小红书需要 --profile 指向自己的专用浏览器目录')
    else:
        from .collectors.browser import validate_target
        config['target'] = validate_target(args.source, str(config.get('target', '')))
        if args.source in ('taobao', 'jd') and not config.get('profile'):
            raise ValueError('需要 --profile 指向自己的专用浏览器目录')
    if config.get('profile'):
        profile = Path(config['profile']).expanduser()
        # 命令行路径相对 cwd；JSON 内路径相对配置所在目录。
        config['profile'] = str((profile if profile.is_absolute() else (Path.cwd() if args.profile else config_dir) / profile).resolve())
    delay = float(config.get('delay_seconds', 2))
    if not 0 < delay < float('inf'):
        raise ValueError('delay_seconds 必须是有限正数')
    config['delay_seconds'] = delay
    timeout = float(config.get('timeout_seconds', 60))
    if not 0 < timeout < float('inf'):
        raise ValueError('timeout_seconds 必须是有限正数')
    return config


def run_collect(args):
    config = resolve_config(args)
    output = Path(args.output).expanduser().resolve()
    if args.dry_run:
        print(json.dumps({'source': args.source, 'output': str(output), 'status': 'input_validated',
                          'note': '未验证凭据、登录、接口或真实采集'}, ensure_ascii=False))
        return 0
    output.mkdir(parents=True, exist_ok=True)
    # 任务目录只对应一个来源，双后端请分目录，防止下游统计误合并。
    manifest = output / 'task.json'
    target_identity = config.get('target', '')
    if args.source == 'xiaohongshu' and target_identity:
        from .collectors.xiaohongshu import canonical_note_url
        target_identity = canonical_note_url(target_identity)
    identity = {'source': args.source, 'queries': config.get('queries', []),
                'subreddits': config.get('subreddits', []), 'target': target_identity}
    if manifest.exists() and json.loads(manifest.read_text()) != identity:
        raise ValueError('输出目录属于不同任务；请使用新目录，或以原目标恢复')
    if not manifest.exists() and (output / 'records.sqlite3').exists():
        raise ValueError('目录中存在没有任务归属记录的旧数据库；请使用新目录，不会自动迁移或合并')
    if not manifest.exists():
        manifest.write_text(json.dumps(identity, ensure_ascii=False, indent=2) + '\n')
    counts = {'inserted': 0, 'updated': 0, 'unchanged': 0}
    result = CollectionResult(args.source)
    interrupted = False
    with ReviewStore(output / 'records.sqlite3') as store:
        def emit(record):
            counts[store.upsert(record)] += 1
        try:
            result = dispatch(args.source, config, output, emit)
        except KeyboardInterrupt:
            interrupted = True
            result.status = 'interrupted'
            result.errors.append('用户中断；此前已提交的记录保留。重新运行会从头扫描并去重。')
        except Exception as exc:
            result.errors.append(f'运行失败：{type(exc).__name__}')
        if result.errors and not interrupted:
            result.status = 'failed'
        report = {'source': args.source, 'status': result.status, 'finished_at': utc_now(), **counts,
                  'fetched': sum(counts.values()), 'total_saved': store.count(),
                  'warnings': result.warnings, 'errors': result.errors,
                  'coverage': '仅本次入口返回的可见记录，不等同于平台全量'}
        # 报告先落盘，即使导出被中断，SQLite 与运行状态仍保留。
        temp = output / 'last_run.json.tmp'
        temp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        temp.replace(output / 'last_run.json')
        store.export_jsonl(output / 'records.jsonl')
        store.export_csv(output / 'records.csv')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 130 if interrupted else 1 if result.errors else 2 if result.status in ('backend_limited', 'stalled') else 0


def doctor():
    print(json.dumps({'python': sys.version.split()[0], 'python_supported': sys.version_info >= (3, 11),
                      'playwright_installed': importlib.util.find_spec('playwright') is not None,
                      'opencli_on_path': shutil.which('opencli') is not None,
                      'credentials_present': {key: bool(os.environ.get(key, '').strip()) for key in
                                              ('YOUTUBE_API_KEY', 'REDDIT_CLIENT_ID', 'REDDIT_CLIENT_SECRET')},
                      'note': '离线检查；不验证 Chromium 安装、扩展连接、权限、登录或配额。'}, ensure_ascii=False, indent=2))
    return 0


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == 'doctor':
            return doctor()
        if args.command == 'login':
            if args.source == 'xiaohongshu':
                from .collectors.xiaohongshu import login_xiaohongshu
                login_xiaohongshu(args.profile)
            else:
                from .collectors.browser import login
                login(args.source, args.profile)
            return 0
        if args.command == 'collect':
            return run_collect(args)
        output = Path(args.output).expanduser().resolve()
        if not (output / 'records.sqlite3').is_file():
            raise ValueError('输出目录不存在 records.sqlite3')
        with ReviewStore(output / 'records.sqlite3') as store:
            if args.command == 'export':
                store.export_csv(output / 'records.csv')
                store.export_jsonl(output / 'records.jsonl')
            print(json.dumps({'total_saved': store.count(), 'by_source': store.summary_by_source()}, ensure_ascii=False))
        return 0
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except ImportError:
        print('缺少浏览器依赖：安装本包的 browser extra，并执行 playwright install chromium', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
