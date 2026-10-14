# MediaCrawler 与 YouTube 修复实施计划

> **执行方式：** 由当前会话在已有 `feature/mediacrawler-platforms` 工作区内联实施；不提交、不推送。每项行为先写回归测试并观察其失败，再实现并验证。

**目标：** 移除本地帖子和评论总量截断；MediaCrawler 搜索结果还须在帖子标题或正文命中至少一个完整查询词；精确同文评论在相同来源、帖子和父评论上下文内合并并保留溯源；修正 Reddit 评论深度与页数处理；限制网页视频回退导航；补齐 YouTube API key 安全设置、生成与运行说明。

**实现路径：** 保持现有 `ReviewRecord`、SQLite 和 CLI 结构。各采集器不对记录总数做本地截断；API 页大小、可见范围、权限、配额及 OpenCLI 最多 5 轮回复展开等上游边界如实报告。MediaCrawler 搜索候选需在标题或正文命中一个完整查询词，大小写无关并归一空白；目标详情模式不做关键词过滤。分析阶段按来源、帖子/评价、父评论关系和逐字相同正文合并，保留原始评论 ID 与匿名作者 ID 并集。网页视频回退仅允许已支持的平台域名作为主文档和 iframe 导航目标。YouTube 凭据只从 `YOUTUBE_API_KEY` 环境变量读取。

**技术栈：** Python、unittest、MediaCrawler 外置 CLI、Playwright、YouTube Data API v3。

## 全局约束

- 不把 MediaCrawler 源码、浏览器档案、Cookie、API key 或采集数据提交到仓库。
- 不改写用户已有 `runs/` 数据；不连接平台实采，也不使用用户的 API key 做联网验证。
- 评论层级只导入一级评论和二级回复；平台分页、权限、配额和可见范围限制如实记录。
- 文本完全相同才合并；近似文本不自动合并。不同帖子、不同父评论上下文不互相合并。
- GitHub 发布继续等待用户单独批准。

## 重点验证输入

- MediaCrawler 返回超过 15 个不同帖子；全部符合“搜索结果 + 标题/正文命中词”规则时全部导入。
- 搜索结果有相关与无关帖子；无关帖子及其评论不进入统一数据库。
- 同一帖、同一父评论下评论 ID 不同但正文完全相同；分析后为一条记录，重复来源与匿名作者计数仍可追溯。
- 同文评论出现在不同帖子或不同父评论关系下；分别保留。
- OpenCLI 返回超过 500 条评论记录并包含一级评论、二级回复、三级后代；仅保存前两层，搜索请求不设本地固定结果数，并披露单次搜索与最多五轮展开的后端限制。
- 初始视频 URL 或主文档重定向目标为非支持平台域名；在加载该页面前拒绝。
- YouTube API key 不在代码、示例配置、命令参数和日志中；指南使用仅当前 shell 可用的隐藏输入环境变量方式。

## 任务

### 任务 1：MediaCrawler 不限帖子数并按相关性导入

文件：`scripts/comment_crawler/collectors/mediacrawler.py`、`scripts/comment_crawler/cli.py`、`tests/test_mediacrawler.py`、`README.md`、`references/mediacrawler.md`。

先测试上游帖子参数不再被 15 条限制，且导入层不截断；再测试平台搜索候选在标题或正文命中至少一个完整查询词后才纳入。移除 `--max-posts` 与本地 `max_posts` 截断，向上游传大整数计数值。按用户确认的规则导入符合条件的帖子及其评论。

### 任务 2：统一精确文本去重并保留溯源

文件：`scripts/comment_crawler/analysis.py`、`tests/test_analysis_review.py`、`comment-quant-analysis/SKILL.md`、`comment-quant-analysis/references/analysis-methodology.md`、相关 README／字段文档。

先测试相同来源、帖子、父关系和完全相同正文的不同评论记录被合并，输出仍可计算匿名作者数并回查所有原始评论 ID；再实现最小变更。保留近似重复簇，不自动删除；跨来源、跨帖与跨父关系不合并。

### 任务 3：Reddit OpenCLI 评论边界

文件：`scripts/comment_crawler/collectors/reddit_opencli.py`、`tests/test_pagination.py`、`references/reddit.md`、`README.md`。

先测试请求参数不设评论总数截断、只保存两层评论、Reddit OAuth 的全部 `more` 节点持续分批展开、OpenCLI 搜索不由本地固定数量截断。OpenCLI 的 5 轮展开是其 CLI 上游硬上限，保留明确覆盖说明。

### 任务 4：限制网页视频浏览器导航范围

文件：`scripts/comment_crawler/web_video_analysis.py`、`tests/test_video_web.py`。

先测试非支持域名、伪装后缀、用户名／密码 URL 和跨站主文档重定向会被拒绝；再增加精确域名校验与主文档导航拦截，平台媒体子资源不因其 CDN 域名而误拦。

### 任务 5：YouTube API 设置与成功状态说明

文件：`references/youtube.md`、`README.md`、`VALIDATION.md`（如记录本地实测）。

补齐 Google Cloud 项目/API 启用、API key 创建与限制、macOS zsh 隐藏输入、`doctor`、`--dry-run`、正式采集、`check` 和 `export` 命令、配额和常见错误处理。明确 key 只在当前 shell 环境变量中使用，不写入代码、配置、命令行参数或 Git。记录“已成功保存记录”与“任务是否完整结束”两个状态，不把中断误写成全量完成。

### 任务 6：验证与发布边界

运行新增目标测试和完整 unittest 套件；检查 `git diff --check`、密钥模式扫描、`git status` 和 `git diff --stat`。任何失败如实报告。保留所有改动在当前分支工作区，不提交、不推送。
