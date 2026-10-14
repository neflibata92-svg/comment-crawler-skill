"""评论采集命令行：一项任务一个平台／后端，输出与安装目录分离。"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys

from .core.schema import utc_now
from .core.storage import QualitySummary, ReviewStore
from .core.utils import CollectionResult, load_json, validate_browser_profile_path

MEDIACRAWLER_SOURCES = ('douyin', 'bilibili', 'weibo', 'zhihu', 'tieba')
SOURCES = ('youtube', 'reddit', 'reddit_opencli', 'taobao', 'jd', 'kickstarter', 'xiaohongshu', *MEDIACRAWLER_SOURCES)


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
    if source in MEDIACRAWLER_SOURCES:
        from .collectors.mediacrawler import collect_mediacrawler
        return collect_mediacrawler(source, config, output, emit)
    from .collectors.browser import browser_collect
    return browser_collect(source, config['target'], config.get('profile'), crawl['delay_seconds'], emit)


def parser():
    root = argparse.ArgumentParser(description='跨平台帖子与评论采集 Skill 工具；按平台可见范围分页读取，不设本地数量上限')
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
    collect.add_argument('--target', help='商品／项目／帖子／视频 URL 或 ID；具体格式取决于平台')
    collect.add_argument('--profile', help='用户专用的本地浏览器档案目录')
    collect.add_argument('--mediacrawler-home', help='外置 MediaCrawler checkout 路径；也可设置 MEDIACRAWLER_HOME')
    collect.add_argument('--output', required=True, help='任务输出目录；恢复时用相同目录')
    collect.add_argument('--delay', type=float, help='请求间隔秒数，必须大于 0')
    collect.add_argument('--dry-run', action='store_true', help='只校验输入，不联网、不写输出')
    collect.add_argument('--refresh-completed', action='store_true',
                         help='小红书重新扫描已完成笔记，获取可能新增的可见评论')
    for name in ('export', 'check'):
        command = sub.add_parser(name)
        command.add_argument('--output', required=True)
    analyze = sub.add_parser('analyze', help='清洗并量化分析已有的评论文件；不联网、不修改输入')
    analyze.add_argument('--input', '-i', action='append', required=True,
                         help='SQLite、CSV、JSONL 文件或含 records.* 的任务目录；可重复指定不同来源')
    analyze.add_argument('--output', '-o', required=True, help='新的空分析结果目录')
    analyze.add_argument('--product', default='', help='分析目标产品／品类；不覆盖记录中的产品字段，也不自动过滤评论')
    analyze.add_argument('--brand', default='', help='分析目标品牌；不覆盖记录中的产品字段，也不自动过滤评论')
    analyze.add_argument('--near-duplicate-threshold', type=float, default=0.9,
                         help='近似重复聚类的字符三元组 Jaccard 阈值（0.5–1，默认 0.9）')
    analyze.add_argument('--annotations', help='人工复核 CSV；可编辑此前输出的 cleaned_comments.csv 后传入')
    analyze.add_argument('--scope', choices=('all', 'verified-target'), default='all',
                         help='all 为全体有效评论探索；verified-target 仅统计人工确认相关的评论')
    video = sub.add_parser('analyze-video', help='在本机抽取视频关键帧、转写音轨并生成多模态分析材料')
    video.add_argument('--input', '-i', action='append', required=True,
                       help='本机视频文件或目录；可重复指定')
    video.add_argument('--output', '-o', required=True, help='新的视频分析结果目录')
    video.add_argument('--scene-threshold', type=float, default=0.35, help='FFmpeg 场景变化阈值（0–1）')
    video.add_argument('--interval-seconds', type=float, default=8.0, help='静态场景定期间隔秒数')
    video.add_argument('--whisper-model', default='base', help='faster-whisper 本地模型名或模型目录')
    video.add_argument('--language', default=None, help='转写语言代码；不填时自动检测')
    video.add_argument('--no-transcribe', action='store_true', help='只抽帧，不提取音轨或运行 Whisper')
    prepare = sub.add_parser('prepare-mediacrawler', help='关闭 CDP/已识别反检测注入，并修正知乎评论分页边界')
    prepare.add_argument('--home', required=True, help='用户单独取得的 MediaCrawler checkout 路径')
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
    if args.refresh_completed:
        if args.source != 'xiaohongshu':
            raise ValueError('--refresh-completed 仅适用于小红书')
        config['refresh_completed'] = True
    for name, key in [('query', 'queries'), ('subreddit', 'subreddits'), ('target', 'target'), ('profile', 'profile'), ('delay', 'delay_seconds')]:
        value = getattr(args, name)
        if value is not None:
            config[key] = value
    for key in ('queries', 'subreddits'):
        values = config.get(key, [])
        if not isinstance(values, list) or any(not isinstance(v, str) or not v.strip() for v in values):
            raise ValueError(f'{key} 应为非空字符串数组')
    if args.source in MEDIACRAWLER_SOURCES:
        raw_home = args.mediacrawler_home or config.get('mediacrawler_home') or os.environ.get('MEDIACRAWLER_HOME', '')
        if not str(raw_home).strip():
            raise ValueError('MediaCrawler 平台需要 --mediacrawler-home 或 MEDIACRAWLER_HOME')
        home = Path(raw_home).expanduser()
        if not home.is_absolute():
            base = Path.cwd() if args.mediacrawler_home else config_dir
            home = base / home
        home = home.resolve()
        if not (home / 'main.py').is_file():
            raise ValueError(f'找不到 MediaCrawler main.py：{home}')
        from .collectors.mediacrawler import _assert_prepared
        _assert_prepared(home)
        config['mediacrawler_home'] = str(home)
        if not config.get('queries') and not config.get('target'):
            raise ValueError('MediaCrawler 平台需要 --query 或 --target')
        if config.get('queries') and config.get('target'):
            raise ValueError('MediaCrawler 任务不能同时指定 --query 和 --target')
    elif args.source == 'xiaohongshu':
        raw_home = args.mediacrawler_home or config.get('mediacrawler_home') or os.environ.get('MEDIACRAWLER_HOME', '')
        if str(raw_home).strip():
            home = Path(raw_home).expanduser()
            if not home.is_absolute():
                base = Path.cwd() if args.mediacrawler_home else config_dir
                home = base / home
            home = home.resolve()
            if not (home / 'main.py').is_file():
                raise ValueError(f'找不到 MediaCrawler main.py：{home}')
            from .collectors.mediacrawler import _assert_prepared
            _assert_prepared(home)
            config['mediacrawler_home'] = str(home)
    elif args.mediacrawler_home:
        raise ValueError('MediaCrawler 参数只适用于抖音、B站、微博、知乎、贴吧以及可选小红书媒体下载')
    config['read_comments'] = True
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
    elif args.source not in MEDIACRAWLER_SOURCES:
        from .collectors.browser import validate_target
        config['target'] = validate_target(args.source, str(config.get('target', '')))
        if args.source in ('taobao', 'jd') and not config.get('profile'):
            raise ValueError('需要 --profile 指向自己的专用浏览器目录')
    if config.get('profile'):
        profile = Path(config['profile']).expanduser()
        # 命令行路径相对 cwd；JSON 内路径相对配置所在目录。
        config['profile'] = validate_browser_profile_path(
            profile if profile.is_absolute() else (Path.cwd() if args.profile else config_dir) / profile
        )
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
    if args.source == 'youtube':
        config['output_dir'] = str(output)
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
    run_by_content_type = {}
    quality = QualitySummary()
    result = CollectionResult(args.source)
    interrupted = False
    with ReviewStore(output / 'records.sqlite3') as store:
        def emit(record):
            counts[store.upsert(record)] += 1
            run_by_content_type[record.content_type] = run_by_content_type.get(record.content_type, 0) + 1
            quality.add(record)

        if args.source == 'xiaohongshu':
            config['output_dir'] = str(output)
            config['existing_post_ids'] = {
                value.removeprefix('note:') for value in store.external_ids('xiaohongshu', 'post')
                if value.startswith('note:')
            }
            config['existing_post_records'] = {
                record.external_id.removeprefix('note:'): record
                for record in store.iter_records()
                if record.source == 'xiaohongshu' and record.content_type == 'post'
                and record.external_id.startswith('note:')
            }
        try:
            result = dispatch(args.source, config, output, emit)
            if result.status == 'interrupted':
                interrupted = True
        except KeyboardInterrupt:
            interrupted = True
            result.status = 'interrupted'
            if args.source == 'xiaohongshu':
                result.errors.append('用户中断；已提交记录保留。使用相同任务和输出目录重跑以按笔记检查点恢复。')
            elif args.source in MEDIACRAWLER_SOURCES or (args.source == 'xiaohongshu' and config.get('mediacrawler_home')):
                result.errors.append('用户中断；已提交记录保留。重新运行会从原入口开始并按稳定 ID 去重，不提供精确平台游标。')
            else:
                result.errors.append('用户中断；此前已提交的记录保留。重新运行会从头扫描并去重。')
        except Exception as exc:
            result.errors.append(f'运行失败：{type(exc).__name__}')
        if result.errors and not interrupted:
            result.status = 'failed'
        report = {'source': args.source, 'status': result.status, 'finished_at': utc_now(), **counts,
                  'fetched': sum(counts.values()), 'total_saved': store.count(),
                  'by_content_type': dict(sorted(run_by_content_type.items())),
                  'field_coverage': quality.as_dict(),
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
                      'ocr_python_dependencies_installed': all(importlib.util.find_spec(name) is not None
                                                               for name in ('pytesseract', 'PIL')),
                      'tesseract_installed': shutil.which('tesseract') is not None,
                      'ffmpeg_installed': shutil.which('ffmpeg') is not None,
                      'ffprobe_installed': shutil.which('ffprobe') is not None,
                      'opencli_on_path': shutil.which('opencli') is not None,
                      'credentials_present': {key: bool(os.environ.get(key, '').strip()) for key in
                                              ('YOUTUBE_API_KEY', 'REDDIT_CLIENT_ID', 'REDDIT_CLIENT_SECRET')},
                      'note': '离线检查；不验证 Chromium 安装、扩展连接、OCR 语言数据、网页可播放状态、登录、授权范围或配额。'}, ensure_ascii=False, indent=2))
    return 0


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == 'doctor':
            return doctor()
        if args.command == 'prepare-mediacrawler':
            from .collectors.mediacrawler import prepare_mediacrawler
            changed = prepare_mediacrawler(args.home)
            print(json.dumps({'prepared': True, 'changed_files': changed,
                              'note': '仅修改用户指定的外置 checkout；备份以 .comment-crawler.bak 结尾。'}, ensure_ascii=False, indent=2))
            return 0
        if args.command == 'login':
            profile = validate_browser_profile_path(args.profile)
            if args.source == 'xiaohongshu':
                from .collectors.xiaohongshu import login_xiaohongshu
                login_xiaohongshu(profile)
            else:
                from .collectors.browser import login
                login(args.source, profile)
            return 0
        if args.command == 'collect':
            return run_collect(args)
        if args.command == 'analyze':
            from .analysis import run_analysis
            result = run_analysis(args.input, args.output, args.product, args.brand,
                                  args.near_duplicate_threshold, args.annotations, args.scope)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            if not result['workbook_created']:
                print("未生成 XLSX；如需工作簿，请安装分析依赖：python -m pip install '.[analysis]'", file=sys.stderr)
            return 0
        if args.command == 'analyze-video':
            from .video_analysis import run_video_analysis
            result = run_video_analysis(
                args.input, args.output, scene_threshold=args.scene_threshold,
                interval_seconds=args.interval_seconds, whisper_model=args.whisper_model,
                language=args.language, transcribe=not args.no_transcribe,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        output = Path(args.output).expanduser().resolve()
        if not (output / 'records.sqlite3').is_file():
            raise ValueError('输出目录不存在 records.sqlite3')
        with ReviewStore(output / 'records.sqlite3') as store:
            if args.command == 'export':
                store.export_csv(output / 'records.csv')
                store.export_jsonl(output / 'records.jsonl')
            last_run_path = output / 'last_run.json'
            try:
                last_run = json.loads(last_run_path.read_text(encoding='utf-8')) if last_run_path.exists() else None
            except json.JSONDecodeError as exc:
                raise ValueError('last_run.json 不是合法 JSON；请先检查任务目录') from exc
            print(json.dumps({
                'total_saved': store.count(),
                'by_source': store.summary_by_source(),
                'by_content_type': store.summary_by_content_type(),
                'quality': store.quality_summary(),
                'last_run': last_run,
            }, ensure_ascii=False))
        return 0
    except (ValueError, OSError, csv.Error) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except ImportError:
        if args.command in ('analyze', 'analyze-video'):
            print('分析模块或可选依赖加载失败；请检查安装包及对应 extra', file=sys.stderr)
        else:
            print('缺少浏览器依赖：安装本包的 browser extra，并执行 playwright install chromium', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
