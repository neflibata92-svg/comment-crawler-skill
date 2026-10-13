# Comment Crawler Skill

中文优先的多平台评论采集 Skill，也可作为独立 Python CLI 使用。覆盖淘宝／天猫、京东、Kickstarter、Reddit、YouTube 和小红书；关键词由使用者指定，没有内置品牌过滤或本地总页数上限。笔记与评论逐条写入 SQLite，可导出 CSV、JSONL，并记录覆盖限制与失败原因。

**先选入口：** YouTube 使用 Data API Key；Reddit 推荐 OAuth，也可单独使用已登录 Chrome 中的 OpenCLI；淘宝／天猫、京东和小红书使用用户手动登录的专用浏览器档案；Kickstarter 从公开项目页进入。各入口的实际可见范围不同，不能把“程序没有设页数上限”理解为平台保证全量。

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

以 YouTube 为例：在本机安全环境中设置 `YOUTUBE_API_KEY`，不要把密钥填进聊天、配置或命令参数。先做不联网的输入检查：

```bash
comment-crawler collect youtube --query '你的产品名称 review' --output ./runs/product-youtube --dry-run
```

核对目标、用途及权限后，去掉 `--dry-run` 运行。程序不设本地总页数上限，运行时间和 API 配额消耗会随目标规模增长；`--delay 2` 控制请求间隔，不改变总量。

```bash
comment-crawler collect youtube --query '你的产品名称 review' --output ./runs/product-youtube --delay 2
comment-crawler check --output ./runs/product-youtube
comment-crawler export --output ./runs/product-youtube
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

API 也支持 `--config examples/config.json`；命令行参数覆盖同名配置。配置中的相对 profile 路径以配置目录为基准，命令行相对路径以当前目录为基准。凭据仅从环境变量读取。

## 支持范围

| 平台 | 所需登录／凭据 | 保存与覆盖边界 |
|---|---|---|
| YouTube | Data API v3 Key | 搜索、顶层评论及缺失回复分页；已存视频也刷新 |
| Reddit OAuth | 应用 Client ID／Secret | 搜索 after 分页、morechildren 迭代展开 |
| Reddit OpenCLI | 用户已登录 Chrome + 扩展 | 搜索仅单页、最多 5 轮展开；明确标记 `backend_limited` |
| 淘宝／天猫 | 专用档案中由用户登录 | 无固定滚动上限；6 轮无变化后标记 `stalled` |
| 京东 | 专用档案中由用户登录 | 无固定总页数；每次从首页扫描并去重／更新 |
| Kickstarter | 公开项目页 | 跟随下一页；保存返回的父 ID，未证明全部子回复覆盖 |
| 小红书 | 专用档案中由用户自行登录 | 关键词发现笔记或指定笔记，另存可见笔记字段及评论、楼中楼；连续无新增标记 `stalled`，不保证全量 |

逐平台操作：[YouTube](references/youtube.md) · [Reddit](references/reddit.md) · [淘宝／天猫](references/taobao.md) · [京东](references/jd.md) · [Kickstarter](references/kickstarter.md) · [小红书](references/xiaohongshu.md)

人工导入、媒体文章、发布评论、私密社区和自动绕过验证不属于本包功能。程序只读评论，不自动登录或代用户完成验证。

## 输出与恢复

每个 `--output` 目录包含：

- `records.sqlite3`：每条记录立即提交的主库。
- `records.csv`、`records.jsonl`：结束时的导出；可用 `export` 重新生成。
- `task.json`：来源及目标，防止误将不同任务混入同一目录。
- `last_run.json`：新增、更新、未变化、按内容类型统计、字段完整度、错误和结束状态。
- `progress.json`（小红书）：按笔记保存待处理／处理中／可见扫描结束状态，不含浏览器会话或签名链接。

Ctrl+C 会保留已提交记录。小红书按笔记写入检查点；搜索结果每次重新进入并扫描，因为页面没有可持久化的搜索游标，已发现的笔记会立即记入检查点。中断中的笔记从评论扫描起点重读，并按稳定记录键去重。默认跳过“可见扫描结束”的笔记；使用 `--refresh-completed` 可重新扫描这些笔记，获取可能新增的可见评论。全部已扫描笔记的重跑会作为成功的无操作运行结束。连续六轮无新增只表示当前页面扫描停滞，不证明平台全量。旧版任务若没有 `progress.json`，会先将数据库里已有笔记作为待扫描项重扫一次；旧检查点会自动迁移。重扫笔记时也会把该笔记旧版按作者和时间生成的合成评论 ID（含楼中楼父 ID）迁移到当前去重键。单篇笔记请求失败会保留待重试状态并继续后续笔记；401、403 或 429 会停止任务。其他平台仍可能从头扫描，依靠 SQLite 去重。强制终止可能留下旧报告或不完整导出，SQLite 是恢复依据；本地旧记录不会自动删除。

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
