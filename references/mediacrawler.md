# MediaCrawler 五平台评论与四平台媒体接入指南

评论采集适用于抖音、B站、微博、知乎和贴吧；媒体下载适用于抖音、B站、微博和小红书。仓库只包含适配代码，不包含 MediaCrawler 源码；运行时需要用户单独取得的外置 checkout 和该项目依赖。

## 准备外置 checkout

先按上游说明准备 Python 环境。使用 `uv` 的示例：

```bash
git clone https://github.com/NanmiCoder/MediaCrawler.git /path/to/MediaCrawler
cd /path/to/MediaCrawler
uv sync
```

回到本仓库后设置路径，并显式准备普通浏览器模式：

```bash
export MEDIACRAWLER_HOME=/path/to/MediaCrawler
comment-crawler prepare-mediacrawler --home "$MEDIACRAWLER_HOME"
```

准备命令只修改用户指定 checkout 的 `config/base_config.py`、六个平台的 `core.py`（含小红书媒体支持）和知乎 `client.py`；关闭 CDP／既有浏览器连接，移除已识别的 stealth 与贴吧内联反检测脚本，并让知乎评论分页使用上游传入的数量参数。修改前会保留 `.comment-crawler.bak` 文件。新版本布局无法识别时命令会停止并要求人工核对，不会猜测补丁位置。采集器运行时也会再次检查这些设置。

## 采集入口和评论范围

关键词搜索：

```bash
comment-crawler collect douyin --query '产品关键词' --output ./runs/douyin-sample
comment-crawler collect bilibili --query '产品关键词' --output ./runs/bilibili-sample
comment-crawler collect weibo --query '产品关键词' --output ./runs/weibo-sample
comment-crawler collect zhihu --query '产品关键词' --output ./runs/zhihu-sample
comment-crawler collect tieba --query '产品关键词' --output ./runs/tieba-sample
```

指定帖子／视频：

```bash
comment-crawler collect bilibili --target 'https://www.bilibili.com/video/BV...' --output ./runs/bili-detail
```

`--query` 可重复输入多个词；`--target` 与 `--query` 不能同时使用。MediaCrawler 在可见浏览器里启动正常登录流程，用户自行登录。浏览器档案由适配器放在用户目录下的 `.comment-crawler/mediacrawler/`，与源码和任务数据分开；将其视为登录凭据，不要提交或共享。不要把 Cookie、账号档案或验证码写入配置文件、issue 或日志。

可选 `--profile /安全目录/浏览器档案` 可为 MediaCrawler 与网页视频回退指定同一个本地档案；需登录的平台应由用户先在该档案中自行登录。未指定时沿用 MediaCrawler 默认档案路径。页面未登录或视频无法播放时如实记录失败，不自动代登或规避限制。

搜索模式只把 MediaCrawler 平台搜索结果视为候选，并再要求帖子标题或正文命中至少一个完整搜索词。匹配时忽略大小写并将连续空白归一；不做语义相似度扩展。只有通过此条件的帖子及其评论会进入 SQLite。指定 `--target` 时按精确目标详情导入，不要求搜索词命中。

帖子、评论和回复都不设本地数量上限，也没有 `--max-posts` 参数。适配器向 MediaCrawler 上游传递大整数以解除其默认帖子／评论计数限制，再导入 JSONL 中所有符合条件的不同帖子与其可见评论。默认打开评论抓取，并将一级评论和它们的二级回复导入 SQLite；每条评论的 `metadata.comment_level` 为 `1` 或 `2`，回复 `parent_id` 指向一级评论。上游返回但找不到一级父评论的回复会跳过并在运行报告写警告；更深层后代不计入这两层。平台搜索分页、登录可见范围、请求配额、接口行为或 MediaCrawler 上游本身仍可能限制结果；不能据“无本地数量上限”宣称平台全量。

## 视频文件

抖音、B站和微博的搜索先完成帖子关键词筛选，再将所有命中帖子的 ID 分批传给外置 MediaCrawler detail 模式下载媒体；不会为未命中帖子的搜索候选请求媒体。指定 `--target` 时只为该目标请求媒体。若旧任务目录中留有未命中候选帖子的媒体目录，导入时会清理这些目录。小红书继续由原有 Playwright 适配器负责搜索和评论；若配置同一外置 checkout，会在当前笔记评论采集后调用 MediaCrawler 的 detail 模式，只为已成功打开的笔记下载媒体，并复用小红书专用浏览器档案。小红书可在 `collect xiaohongshu` 命令传 `--mediacrawler-home`，也可设置 `MEDIACRAWLER_HOME`。上游媒体开关可能同时下载封面、视频和图文图片。视频保存在任务目录：

```text
<任务目录>/.mediacrawler/<平台代码>/media/<平台内容 ID>/
```

`metadata.media_assets.files` 只列出仍保留的视频文件。下载的视频会在本机用 FFmpeg 按场景变化和定时间隔抽帧，再用 Tesseract 对关键帧做文字识别；抽取帧、联系表和 OCR 文本保存在 `.mediacrawler/video-analysis/`，随后自动删除源视频。若没有可用视频文件（包括未配置下载器、上游没有媒体文件或 YouTube API 来源），则尝试在普通网页播放器内定位播放进度、截取可见画面并做 OCR；该回退只保存画面截图与 OCR 结果，不读取或保存视频流文件，也不提取音轨。此回退需要页面可访问、已登录（如平台要求）并提供可定位的 `<video>` 播放器。帖子元数据记录帧数、含文字帧数、分析目录、捕获方式和删除状态。封面与图文图片也会用本地 Tesseract OCR，文字先持久化到帖子元数据和 `.mediacrawler/image_ocr.json`，随后删除图片。`image_ocr` 按原图片文件名保留识别文字和处理状态；完整 OCR 文本也能在任务的 SQLite／JSONL 导出中检索。视频与图片 OCR 都需要 `python -m pip install '.[browser,ocr]'`、`python -m playwright install chromium`、系统 FFmpeg（`ffmpeg` 与 `ffprobe`）和本机 Tesseract（含 `chi_sim`、`eng` 语言数据）。缺少依赖、语言包、抽帧／OCR 失败或无法写入结果时会保留已下载源媒体，并在运行报告中提示，可修复后重跑。

没有视频文件、上游版本不支持该选项或来源不在适配范围时，会保留对应状态，不会把标题、正文、字幕或缩略图标为视频文件。原始 JSONL 会保留平台搜索候选，因此可能比本地 SQLite 纳入的帖子更多；搜索媒体只按关键词命中的帖子 ID 分批下载，旧任务目录中与候选 ID 对应但未命中的媒体目录会在导入时清理。若外部进程在 JSONL 之外写入文件，请单独核对其位置和清理状态。

| `status` | 含义 |
|---|---|
| `available` | 找到至少一个仍保留的视频文件，`files` 列出相对路径 |
| `processed_and_deleted` | 关键帧 OCR 与结果保存完成，源视频已自动删除；输出见 `video_analysis` |
| `analysis_completed_source_retained` | 帧 OCR 已完成，但源视频删除失败，文件仍保留 |
| `analysis_completed_deletion_unconfirmed` | 已有完整 OCR 结果，但源视频未能确认删除；检查对应清单和媒体目录 |
| `processed_in_browser` | 没有可用源视频文件；网页播放器截帧 OCR 完成，未保存完整视频 |
| `web_fallback_failed` | 没有可用源视频文件，普通网页播放截帧未完成 |
| `requested_no_video_file` | 已请求上游下载，但该帖子目录没有发现支持的视频文件 |
| `upstream_option_unavailable` | 外置 checkout 未暴露 `--get_media`，因此没有请求下载 |
| `not_supported_by_adapter` | 当前平台适配器未实现媒体文件下载 |

图片处理状态另存于 `image_ocr_status`，与视频 `status` 分开。`completed` 表示找到的图片已成功 OCR 并删除；`partial` 或 `unavailable` 表示至少有图片仍保留。图片 OCR 结果和文件名保存在 `image_ocr`；视频帧 OCR 状态、识别帧数量、删除状态和结果目录保存在 `video_analysis`。只有抽帧、每帧 OCR 及清单落盘成功后才删除源视频；失败时源视频保留。帧识别只覆盖采样帧，不能代表视频每一帧，也不包含语音转写。

YouTube Data API 返回视频元数据和评论，但没有视频文件下载方法；如果用户已取得适用于该处理方式的 YouTube 书面批准，本适配器会对普通网页播放器截帧 OCR，不下载完整视频或缩略图。无批准时不要运行 YouTube 画面捕获。知乎、贴吧、Reddit、淘宝／天猫、京东及 Kickstarter 当前适配器不提供通用媒体文件下载；有公开视频 URL 时可尝试同样的网页截帧回退。

## 字段映射

| 平台 | 帖子 ID / URL | 帖子正文与时间 | 评论 ID / 父评论 | 互动字段 |
|---|---|---|---|---|
| 抖音 | `aweme_id` / `aweme_url` | `desc` / `create_time` | `comment_id` / `parent_comment_id` | 点赞、评论、分享 |
| B站 | `video_id` / `video_url` | `desc` / `create_time` | `comment_id` / `parent_comment_id` | 点赞、评论、播放、收藏、分享 |
| 微博 | `note_id` / `note_url` | `content` / `create_date_time` 或 `create_time` | `comment_id` / `parent_comment_id` | 点赞、评论、分享 |
| 知乎 | `content_id` / `content_url` | `content_text`、`title`、`desc` / `created_time` | `comment_id` / `parent_comment_id` | 赞同、评论、评论点赞 |
| 贴吧 | `note_id` / `note_url` | `title`、`desc` / `publish_time` | `comment_id` / `parent_comment_id` | 回复数 |

统一记录使用 `source` 区分平台，帖子为 `content_type=post`，评论为 `content_type=comment`；评论层级写入 `metadata.comment_level`，回复的 `parent_id` 指向一级评论。作者只保留来源隔离的哈希，不导入昵称。上游没有返回的平台 ID 时会用帖子、父 ID、时间和正文生成合成 ID，并在 `metadata.platform_comment_id_strategy` 标记；缺少 ID 的帖子会跳过并写入警告。互动数保存在统一字段及 `metadata.engagement`，未提供的值留空。

## 输出与中断恢复

- SQLite、CSV、JSONL 和 `last_run.json` 沿用本仓库的标准任务输出。
- MediaCrawler 的原始 JSONL 保存在任务目录的 `.mediacrawler/<平台代码>/jsonl/`，用于重跑时重新导入。
- 媒体文件保存在 `.mediacrawler/<平台代码>/media/`，可能较大；不要提交到 Git。
- SQLite 以来源、内容类型和平台 ID 幂等去重；上游 JSONL 可能包含多次扫描的重复行。
- Ctrl+C 后适配器尝试导入进程已写出的 JSONL。再次运行会重扫原关键词或指定内容，然后依靠稳定 ID 去重；当前不支持上游平台的精确检查点／游标续跑。强制杀进程可能留下不完整的最后一行，坏行会跳过并记录警告。
- `completed_visible` 只表示上游进程按当前入口返回并退出，不代表平台全量。

## 使用与许可

MediaCrawler 上游采用非商业学习许可，对商业用途和大规模采集有限制。使用者须遵守其当前许可证、目标平台规则和账号可见权限；获取源码的单独许可不自动代表可以把上游代码重新发布到本仓库。请在开始使用前阅读[上游许可证](https://github.com/NanmiCoder/MediaCrawler/blob/main/LICENSE)和[上游项目说明](https://github.com/NanmiCoder/MediaCrawler)。本仓库不提供绕过验证码、访问控制、限流或平台反自动化机制的功能。
