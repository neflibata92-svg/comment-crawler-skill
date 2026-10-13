#!/usr/bin/env python3
"""直接从 Skill 安装目录运行，无需依赖 cwd。"""
from comment_crawler.cli import main
if __name__ == '__main__':
    raise SystemExit(main())
