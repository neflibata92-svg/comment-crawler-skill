# Comment Crawler Skill

中文优先的多平台评论采集 Skill，也可作为独立 Python CLI 使用。覆盖淘宝／天猫、京东、Kickstarter、Reddit 和 YouTube；关键词由使用者指定，没有内置品牌过滤或本地总页数上限。评论逐条写入 SQLite，可导出 CSV、JSONL，并记录覆盖限制与失败原因。

**先选入口：** YouTube 使用 Data API Key；Reddit 推荐 OAuth，也可单独使用已登录 Chrome 中的 OpenCLI；淘宝／天猫和京东使用用户手动登录的专用浏览器档案；Kickstarter 从公开项目页进入。各入口的实际可见范围不同，不能把“程序没有设页数上限”理解为平台保证全量。

**v0.1.0 验证边界：** 原作者确认历史脚本曾完整采集目标信息；本发布版已重构为普通 Playwright 与通用 CLI，仅进行离线测试、安装和合成样例验证，尚未进行真实平台复测。接口、登录权限和页面结构可能变化。“分页结束”不表示平台所有评论均可见。

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

OpenCLI 由用户单独安装并连接浏览器扩展；工具不会安装扩展、接管日常浏览器档案或获取账户密码。适配依据为发布时本机 OpenCLI `reddit search/read` 命令；版本差异见 [Reddit](references/reddit.md)。

## 安装为 Skill

把完整仓库目录复制或克隆到 Codex 的个人技能目录，并将目录命名为 `comment-crawler`（例如 `~/.codex/skills/comment-crawler`）。已有同名目录时先检查，勿覆盖。保留 `scripts/`、`references/`、`agents/` 和根目录文件；只复制 `SKILL.md` 不可执行。

重新加载技能后，以 `$comment-crawler` 调用。其他兼容 Agent Skills 的工具可将本目录安装到其技能目录。Skill 无需独立 Agent 服务。

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
comment-crawler login jd --profile ./profiles/jd
comment-crawler collect jd --target 'https://item.jd.com/123456.html' --profile ./profiles/jd --output ./runs/product-jd --dry-run
```

检查目标后，去掉第二条命令的 `--dry-run` 即可开始。`profiles/` 含登录状态，请放在仓库外或自行保护；本仓库 `.gitignore` 会忽略该目录。Reddit 两种入口的差异及各平台命令见下表和对应指南。

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

逐平台操作：[YouTube](references/youtube.md) · [Reddit](references/reddit.md) · [淘宝／天猫](references/taobao.md) · [京东](references/jd.md) · [Kickstarter](references/kickstarter.md)

人工导入、媒体文章、发布评论、私密社区和自动绕过验证不属于本包功能。程序只读评论，不自动登录或代用户完成验证。

## 输出与恢复

每个 `--output` 目录包含：

- `records.sqlite3`：每条记录立即提交的主库。
- `records.csv`、`records.jsonl`：结束时的导出；可用 `export` 重新生成。
- `task.json`：来源及目标，防止误将不同任务混入同一目录。
- `last_run.json`：新增、更新、未变化、错误、覆盖限制和结束状态。

Ctrl+C 保留已提交记录；相同命令和输出目录会从头重新扫描并去重，**不是保存游标直接续传**。强制终止可能留下旧报告或不完整导出，SQLite 是恢复依据。未承诺检测平台删除的评论；本地旧记录不会自动删除。

一次运行只选一个平台后端。Reddit OAuth 的来源为 `reddit`，OpenCLI 为 `reddit_opencli`，且应分任务目录使用；不要把两路评论直接合计。旧项目数据库不自动迁移。

| 状态／退出码 | 含义 |
|---|---|
| `completed_visible` / 0 | 当前入口正常结束，仅限可见返回范围 |
| `backend_limited`、`stalled` / 2 | 后端或页面加载限制，不能宣称全量 |
| `failed` / 1 | 失败；已提交记录保留 |
| `interrupted` / 130 | 用户中断；可重新扫描恢复 |

[字段、去重与验收说明](references/data-and-quality.md)。作者标识使用来源隔离的哈希，这是去标识化而非不可逆匿名保证；正文仍可能包含个人信息。数据与账号档案只保留在任务所需的本地位置。

## 开发验证

```bash
python -m pip install .
python -m unittest discover -s tests -v
python scripts/crawl.py doctor
python scripts/crawl.py collect youtube --query 'fixture camera' --output ./runs/fixture --dry-run
```

测试使用合成响应，不读取真实评论或凭据，不启动平台采集。CI 检查 Python 3.11–3.14 的安装与离线行为；浏览器安装不等于登录和平台访问验证。

## 来源与许可

MIT 许可覆盖本仓库代码和文档，不授予平台数据或账户的访问权。来源、已知局限及重构差异见 [PROVENANCE.md](PROVENANCE.md)。平台规则和接口授权需在实际任务中核实。
