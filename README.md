# Comment Crawler Skill

中文优先的多平台帖子与评论采集 Skill，也可作为独立 Python CLI 使用。覆盖淘宝／天猫、京东、Kickstarter、Reddit、YouTube、小红书，以及通过外置 MediaCrawler 接入的抖音、B站、微博、知乎和贴吧。关键词由使用者指定，没有内置品牌过滤；采集器不设置帖子或评论的本地总量截断。记录逐条写入 SQLite，可导出 CSV、JSONL，并报告覆盖限制与失败原因。

**先选入口：** YouTube 使用 Data API key；Reddit 推荐 OAuth，也可使用已登录 Chrome 中的 OpenCLI；淘宝／天猫、京东和小红书使用用户手动登录的专用浏览器档案；Kickstarter 从公开项目页进入；抖音、B站、微博、知乎和贴吧通过单独准备的 MediaCrawler checkout 运行。采集器不设帖子或评论总量上限，但平台分页、可见范围、权限、配额及个别上游入口能力仍会限制结果；分页结束不代表平台全量。

**快速导航：** [安装](#安装) · [快速开始](#快速开始) · [MediaCrawler 五平台](#抖音b站微博知乎和贴吧) · [支持范围](#支持范围) · [输出与恢复](#输出与恢复) · [评论分析](#分析已有采集结果) · [开发验证](#开发验证)

**v0.1.0 验证边界：** 2026-10-13 已在用户登录态用 `memomind` 做过一次小红书试采，用户中断了运行；结果与字段缺失见 [验收记录](VALIDATION.md)。这次试采不证明全量或后续页面结构仍然可用。其他平台的权限、配额和接口也需分别核实；“分页结束”不表示平台所有评论均可见。

## 安装

Python 3.11 或以上。API 与 OpenCLI 包装层没有必需的第三方 Python 依赖。

```bash
git clone https://github.com/neflibata92-svg/comment-crawler-skill.git
cd comment-crawler-skill
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
comment-crawler doctor
```

Windows 可用 `.venv\Scripts\activate` 激活。浏览器平台另装固定版本及对应 Chromium：

```bash
python -m pip install '.[browser]'
python -m playwright install chromium
```

若要输出多工作表分析工作簿，可选安装本地分析依赖：

```bash
python -m pip install '.[analysis]'
```

OpenCLI 由用户单独安装并连接浏览器扩展；工具不会安装扩展、接管日常浏览器档案或获取账户密码。适配依据为发布时本机 OpenCLI `reddit search/read` 命令；版本差异见 [Reddit](references/reddit.md)。

## 安装为 Skill

把完整仓库目录复制或克隆到 Codex 的个人技能目录，并将目录命名为 `comment-crawler`（例如 `~/.codex/skills/comment-crawler`）。已有同名目录时先检查，勿覆盖。保留 `scripts/`、`references/`、`agents/` 和根目录文件；只复制 `SKILL.md` 不可执行。

重新加载技能后，以 `$comment-crawler` 调用。其他兼容 Agent Skills 的工具可将本目录安装到其技能目录。Skill 无需独立 Agent 服务。

仓库还提供独立的评论分析 skill，位于 `comment-quant-analysis/`。如需直接使用 `$comment-quant-analysis`，将该子目录单独安装为 `~/.codex/skills/comment-quant-analysis`；也可以只安装主 skill，并在 `$comment-crawler` 任务中按需读取其配套分析 skill。两个 skill 可分别更新。

也可不安装命令行包，直接执行 `python /技能目录/scripts/crawl.py doctor`。采集数据写到单独任务目录，不写入技能安装目录。

## 快速开始

以 YouTube 为例：先按[操作指南](references/youtube.md)在 Google Cloud 启用 YouTube Data API v3、创建 API key，并将 key 限制为仅用于该 API。然后在 macOS zsh 当前终端中隐藏输入 key；它只在当前终端会话有效，不写入配置或源码：

```bash
printf '请输入 YouTube API key（输入不显示）: '
read -rs YOUTUBE_API_KEY
printf '\n'
export YOUTUBE_API_KEY

comment-crawler doctor
comment-crawler collect youtube --query '你的产品名称 review' --output ./runs/product-youtube --dry-run
```

`doctor` 只检查 key 是否已设置，不验证 key 是否有效或配额是否充足。先核对目标与输出目录，再去掉 `--dry-run` 正式采集。key 不要贴进聊天或截图，也不要放入命令参数、配置文件或 Git。程序不设本地总页数上限；运行时间和 API 配额消耗会随采集规模增长，`--delay 2` 只控制请求间隔。采集结束后可清除当前 shell 中的 key：

```bash
comment-crawler collect youtube --query '你的产品名称 review' --output ./runs/product-youtube --delay 2
comment-crawler check --output ./runs/product-youtube
comment-crawler export --output ./runs/product-youtube
unset YOUTUBE_API_KEY
```

淘宝／天猫和京东需要先打开**独立档案**，由用户在弹出的浏览器中自行登录，再用同一个档案采集。例如：

```bash
comment-crawler login jd --profile ~/Library/Application\ Support/comment-crawler/jd
comment-crawler collect jd --target 'https://item.jd.com/123456.html' --profile ~/Library/Application\ Support/comment-crawler/jd --output ./runs/product-jd --dry-run
```

检查目标后，去掉第二条命令的 `--dry-run` 即可开始。浏览器档案必须位于所有 Git 仓库之外；程序会拒绝仓库内路径。Reddit 两种入口的差异及各平台命令见下表和对应指南。

小红书支持关键词和笔记链接两种入口。采集器分别保存页面可见的笔记标题、正文、匿名作者标识、发布时间和互动数，以及评论和楼中楼。用户在专用浏览器中自行完成登录；登录命令只检查页面是否显示拦截，真实搜索及评论权限仍需采集试运行确认：

```bash
comment-crawler login xiaohongshu --profile ~/Library/Application\ Support/comment-crawler/xiaohongshu
comment-crawler collect xiaohongshu --query '相机体验' --profile ~/Library/Application\ Support/comment-crawler/xiaohongshu --output ./runs/xhs-camera --dry-run
comment-crawler collect xiaohongshu --query '相机体验' --profile ~/Library/Application\ Support/comment-crawler/xiaohongshu --output ./runs/xhs-camera --delay 2
# 重新扫描此前已结束可见扫描的笔记
comment-crawler collect xiaohongshu --query '相机体验' --profile ~/Library/Application\ Support/comment-crawler/xiaohongshu --output ./runs/xhs-camera --refresh-completed --delay 2
```

也可将 `--query` 改为 `--target 'https://www.xiaohongshu.com/explore/笔记ID'`。关键词可以重复传入；同一任务目录固定关键词和目标。完整登录步骤及采集边界见[小红书指南](references/xiaohongshu.md)。

## 抖音、B站、微博、知乎和贴吧

五个平台通过单独安装在仓库外的 MediaCrawler checkout 运行。本仓库不包含其源代码。请先按其说明安装依赖，并设置 `MEDIACRAWLER_HOME`；首次使用前运行准备命令，关闭上游默认的 CDP 和已识别的反检测脚本注入，并让知乎分页接收评论读取范围。准备命令也会为小红书的可选媒体下载准备上游核心文件。该命令会在外置 checkout 中备份并修改配置、六个平台核心文件及知乎评论客户端：

```bash
export MEDIACRAWLER_HOME=/path/to/MediaCrawler
comment-crawler prepare-mediacrawler --home "$MEDIACRAWLER_HOME"
comment-crawler collect douyin --query '产品关键词' --output ./runs/douyin-test
comment-crawler collect bilibili --target 'BV1xxxxxxxxx' --output ./runs/bilibili-test
comment-crawler collect weibo --query '产品关键词' --output ./runs/weibo-test
comment-crawler collect zhihu --query '产品关键词' --output ./runs/zhihu-test
comment-crawler collect tieba --query '产品关键词' --output ./runs/tieba-test
```

首次采集时由用户在可见浏览器中自行登录和处理正常登录流程。搜索模式只导入平台搜索结果中标题或正文命中至少一个完整搜索词的帖子及其评论，匹配时忽略大小写并归一空白；帖子和评论不设本地总量上限。默认读取一级评论和二级回复，更深层后代不进入统一评论表。平台分页、可见范围、账号权限和配额仍可能限制实际结果。遇到验证码、访问拒绝或限流时停止任务，不尝试绕过。使用 `--target` 进入指定内容详情模式；同一任务目录只能绑定相同来源和入口。MediaCrawler 采用独立的非商业学习许可，使用者须遵守其许可与平台规则；本仓库不会重新发布其代码。详细字段、准备及恢复说明见 [MediaCrawler 平台指南](references/mediacrawler.md)。

MediaCrawler 搜索模式先按标题和正文筛选，再为所有命中帖子的 ID 分批请求抖音、B站和微博媒体。分批只限制单次命令的 ID 数，不截断命中 ID 总数。小红书仍由本仓库采集评论；可通过 `--mediacrawler-home` 或 `MEDIACRAWLER_HOME` 让 MediaCrawler 为已采集笔记下载视频。

### 媒体与视频分析

视频保存在任务目录 `.mediacrawler/<平台代码>/media/<内容 ID>/`。本机使用 FFmpeg 抽取关键帧并运行 Tesseract OCR；抽帧图、联系表和文字保存在 `.mediacrawler/video-analysis/`，成功落盘后自动删除视频源文件。若未能下载视频，则尝试用普通网页播放器截取可见画面；页面需可访问、正常播放并支持定位，流程不保存完整视频流。YouTube Data API 不提供完整视频文件下载接口；网页截帧 OCR 仅在取得适用于该分析的 YouTube 书面批准后使用，也不会保存视频文件或缩略图。

封面和图文图片只在本机 OCR；文字先写入任务数据库和 `.mediacrawler/image_ocr.json`，成功后删除图片。缺少依赖或处理失败时保留可用源媒体并报告状态。启用媒体处理需安装 `python -m pip install '.[browser,ocr]'`、`python -m playwright install chromium`、本机 FFmpeg（`ffmpeg` 和 `ffprobe`）以及含 `chi_sim`、`eng` 语言数据的 Tesseract。

手动运行 `comment-crawler analyze-video --input <视频文件或目录> --output <新目录>` 可抽帧、生成联系表并转写音轨；该命令保留输入视频，不调用云端多模态 API。详见[视频分析指南](references/video-analysis.md)。

API 也支持 `--config examples/config.json`；命令行参数覆盖同名配置。配置中的相对 profile 路径以配置目录为基准，命令行相对路径以当前目录为基准。凭据仅从环境变量读取。

## 支持范围

| 平台 | 所需登录／凭据 | 评论层级与媒体边界 |
|---|---|---|
| YouTube | Data API v3 Key；网页取帧 OCR 需适用的 YouTube 书面批准 | 顶层评论和直接回复分页；视频用网页播放截帧 OCR，不保存完整视频文件或缩略图 |
| Reddit OAuth | 应用 Client ID／Secret | 分页搜索并展开可见评论树；不下载链接视频 |
| Reddit OpenCLI | 用户已登录 Chrome + 扩展 | 搜索仅单页，OpenCLI 最多 5 轮展开；明确标记 `backend_limited`，不下载视频 |
| 淘宝／天猫 | 专用档案中由用户登录 | 采集商品评价；当前适配无用户回复树，追评单独放在元数据；6 轮无变化后标记 `stalled` |
| 京东 | 专用档案中由用户登录 | 采集扁平商品评价；`afterUserReply` 等附加文本被合并进元数据，未建用户回复树；分页至空页并去重 |
| Kickstarter | 公开项目页 | 跟随下一页并保存返回的父 ID，未证明全部子回复覆盖；不下载视频文件 |
| 小红书 | 专用档案中由用户自行登录；媒体下载需配置 MediaCrawler | 保存可见笔记字段、一级评论和楼中楼；连续六轮无新增后停止；可下载视频并在 OCR 后删除，缺少视频文件时网页截帧 OCR |
| 抖音、B站、微博、知乎、贴吧 | 用户外置 MediaCrawler checkout；首次采集在可见浏览器中登录 | 帖子和评论均无本地总量截断；搜索结果需在帖子标题或正文命中搜索词。导入一级和二级评论。抖音、B站、微博请求媒体文件；视频帧和图片 OCR 完成后删除源媒体。重扫按 ID 去重，不保证精确游标续跑 |

逐平台操作：[YouTube](references/youtube.md) · [Reddit](references/reddit.md) · [淘宝／天猫](references/taobao.md) · [京东](references/jd.md) · [Kickstarter](references/kickstarter.md) · [小红书](references/xiaohongshu.md) · [MediaCrawler 五平台](references/mediacrawler.md)

人工导入、媒体文章、发布评论、私密社区和自动绕过验证不属于本包功能。程序只读评论，不自动登录或代用户完成验证。

## 输出与恢复

每个 `--output` 目录包含：

- `records.sqlite3`：每条记录立即提交的主库。
- `records.csv`、`records.jsonl`：结束时的导出；可用 `export` 重新生成。
- `task.json`：来源及目标，防止误将不同任务混入同一目录。
- `last_run.json`：新增、更新、未变化、按内容类型统计、字段完整度、错误和结束状态。
- `progress.json`（小红书）：按笔记保存待处理／处理中／可见扫描结束状态，不含浏览器会话或签名链接。
- `.mediacrawler/`：上游生成的原始 JSONL、OCR 文本清单，作为导入和恢复依据；保留在任务目录，本地数据不要提交到 Git。
- `.mediacrawler/<平台代码>/media/`：上游实际下载的媒体；视频完成抽帧与画面文字 OCR、图片完成 OCR 后自动删除源文件。`.mediacrawler/video-analysis/` 保存关键帧、联系表和文字结果；音轨转写仍需使用独立的本地 `analyze-video` 流程。

Ctrl+C 会保留已提交记录。小红书按笔记写入检查点；搜索结果每次重新进入并扫描，因为页面没有可持久化的搜索游标，已发现的笔记会立即记入检查点。中断中的笔记从评论扫描起点重读，并按稳定记录键去重。默认跳过“可见扫描结束”的笔记；使用 `--refresh-completed` 可重新扫描这些笔记，获取可能新增的可见评论。全部已扫描笔记的重跑会作为成功的无操作运行结束。连续六轮无新增只表示当前页面扫描停滞，不证明平台全量。旧版任务若没有 `progress.json`，会先将数据库里已有笔记作为待扫描项重扫一次；旧检查点会自动迁移。重扫笔记时也会把该笔记旧版按作者和时间生成的合成评论 ID（含楼中楼父 ID）迁移到当前去重键。单篇笔记请求失败会保留待重试状态并继续后续笔记；401、403 或 429 会停止任务。MediaCrawler 后端会把运行中生成的 JSONL 导入 SQLite；中断后再次运行会从原入口重扫并按稳定 ID 去重，不支持精确平台游标续跑。强制终止可能留下旧报告或不完整导出，SQLite 是恢复依据；本地旧记录不会自动删除。

一次运行只选一个平台后端。Reddit OAuth 的来源为 `reddit`，OpenCLI 为 `reddit_opencli`，且应分任务目录使用；不要把两路评论直接合计。旧项目数据库不自动迁移。

| 状态／退出码 | 含义 |
|---|---|
| `completed_visible` / 0 | 当前可见扫描按停止条件结束，或已发现笔记均已扫描而无需重开；仅限可见范围 |
| `backend_limited`、`stalled` / 2 | 后端或页面加载限制，不能宣称全量 |
| `failed` / 1 | 失败；已提交记录保留 |
| `interrupted` / 130 | 用户中断；可重新扫描恢复 |

[字段、去重与验收说明](references/data-and-quality.md)。作者标识使用来源隔离的哈希，这是去标识化而非不可逆匿名保证；正文仍可能包含个人信息。数据与账号档案只保留在任务所需的本地位置。

## 分析已有采集结果

安装配套分析 skill 后，可用 `$comment-quant-analysis` 对用户明确指定的任务数据做清洗、去重、痛点量化和证据整理。完整的分类、分母、严重程度和报告口径见 [`comment-quant-analysis/references/analysis-methodology.md`](comment-quant-analysis/references/analysis-methodology.md)；仓库记录字段的映射与限制见 [`comment-quant-analysis/references/crawler-data-map.md`](comment-quant-analysis/references/crawler-data-map.md)。

也可直接运行仓库 CLI 的本地分析器，无需重新采集或联网：

```bash
comment-crawler analyze \
  --input ./runs/xhs-memomind-test \
  --output ./runs/xhs-memomind-analysis \
  --product 'Memomind'
```

`--input` 支持任务目录、SQLite、CSV 或 JSONL；合并渠道时可重复指定。一个任务目录同时有 SQLite/CSV/JSONL 时只读 SQLite，不把导出文件重复计数；也会拒绝在同一命令中重复选入同一任务的多种格式。输出目录须为空且位于任务目录之外。必需输出包括清洗明细、量化摘要、Markdown 报告、痛点和机会表、完整 `evidence_index.csv` 及人工复核队列；安装 `.[analysis]` 后另有 XLSX。

`--product` 和 `--brand` 只记录分析目标，不会覆盖记录里的产品/品牌字段，也不会自动筛掉其他产品评论。首轮默认 `--scope all` 是探索性规则预标注；不要把它当作目标产品的正式结论。生成首轮结果后，逐条编辑 `cleaned_comments.csv`，保留 `analysis_record_key`，设置 `annotation_status=manual_reviewed`、`product_relevance=related/unrelated/uncertain`，必要时修正未知的 `content_group`，并复核主题、痛点、购买障碍和严重程度。再用相同原始输入及人工标注文件运行目标范围报告：

```bash
comment-crawler analyze \
  --input ./runs/xhs-memomind-test \
  --output ./runs/xhs-memomind-verified-analysis \
  --product 'Memomind' \
  --annotations ./runs/xhs-memomind-analysis/cleaned_comments.csv \
  --scope verified-target
```

`verified-target` 只统计人工确认与目标产品相关、且纳入分析的评论。评论意向“想买”不会自动计为购买障碍；严重度只汇总人工评估的 1–5 分。完整标签证据索引保存在 `evidence_index.csv`。规则预标注不能稳定识别反讽、上下文指代和隐含需求；单人复核也不等于标注者间信度。

一个任务目录中的 `records.sqlite3`、`records.csv`、`records.jsonl` 是同一批数据的不同格式，分析时只选一种作为记录输入，优先使用 SQLite 主库。`task.json` 和 `last_run.json` 用来说明采集来源、状态和覆盖限制，不是评论记录；不同任务目录或不同 Reddit 后端也不要默认合并。评论分析只基于用户指定文件，不自动联网补充或启动新的采集任务。

## 开发验证

```bash
python -m pip install .
python -m unittest discover -s tests -v
python scripts/crawl.py doctor
python scripts/crawl.py collect youtube --query 'fixture camera' --output ./runs/fixture --dry-run
```

测试使用合成响应，不读取真实评论或凭据，不启动平台采集。CI 检查 Python 3.11–3.14 的离线行为，并在独立 job 安装 Chromium 运行小红书 DOM 合成测试；这些测试不验证账户登录或真实平台访问。

## 来源与许可

MIT 许可覆盖本仓库代码和文档，不授予平台数据或账户的访问权。来源、已知局限及重构差异见 [PROVENANCE.md](PROVENANCE.md)。平台规则和接口授权需在实际任务中核实。
