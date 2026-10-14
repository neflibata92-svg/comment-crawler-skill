# YouTube：API key 申请、安全输入与采集

本采集器使用 YouTube Data API v3 读取公开搜索结果、视频元数据和可见评论。仅抓取公开数据时使用 API key，不需要登录 YouTube；需要读取私有或账户数据时应使用 OAuth，但本采集器不实现账户授权。API key 只从进程环境变量 `YOUTUBE_API_KEY` 读取，并通过 `x-goog-api-key` 请求头发送；不放进请求 URL、JSON 配置、源码或命令行参数，也不会写入任务文件。

## 1. 创建 API key

1. 登录 [Google Cloud Console](https://console.cloud.google.com/) 并创建或选择一个项目。
2. 在 API Library 搜索并启用 **YouTube Data API v3**。
3. 打开 **APIs & Services → Credentials → Create credentials → API key**。
4. 打开该 key 的限制设置，将 **API restrictions** 限制为 **YouTube Data API v3**。本机命令行采集不适合使用 HTTP referrer 限制；只有在出口 IP 固定时再设置 IP 地址限制。
5. 复制 key 到本机受信任的密码管理器。不要贴进聊天、截图、issue、JSON 配置、源码或 Git。若 key 已出现在公开仓库、聊天记录或截图中，应先在 Cloud Console 撤销并重新生成。

官方说明：[YouTube Data API 入门](https://developers.google.com/youtube/v3/getting-started)、[API 凭据指南](https://developers.google.com/youtube/registering_an_application)、[API key 限制](https://docs.cloud.google.com/api-keys/docs/add-restrictions-api-keys)、[API key 安全建议](https://docs.cloud.google.com/docs/authentication/api-keys-best-practices)。

## 2. 在 macOS zsh 中安全输入

在仓库根目录打开 Terminal。`read -rs` 会静默读取输入，不把 key 回显到终端；按提示粘贴 key 后按 Return：

```zsh
printf '请输入 YouTube API key（输入不显示）: '
read -rs YOUTUBE_API_KEY
printf '\n'
export YOUTUBE_API_KEY
```

这个环境变量仅在当前 shell 会话及其启动的子进程中可用。不要把 key 作为 `--api-key` 参数、写入 `config.json`、`.env` 或 Python 源码，也不要执行会打印环境变量的命令。采集器将 key 放在 HTTP header 中，不附加到请求 URL。任务结束后清除：

```zsh
unset YOUTUBE_API_KEY
```

`doctor` 仅输出环境变量是否存在的布尔值，不显示 key，也不验证 key 是否有效、API 是否启用或剩余配额。

## 3. 检查并运行

可使用已安装的 `comment-crawler` 命令，或在当前仓库直接使用 `python3 scripts/crawl.py`：

```zsh
python3 scripts/crawl.py doctor
python3 scripts/crawl.py collect youtube --query 'MemoMind review' --output ./runs/youtube-memomind-test --dry-run
```

确认目标与输出目录后，去掉 `--dry-run` 开始采集。`--query` 可以重复提供多个关键词：

```zsh
python3 scripts/crawl.py collect youtube \
  --query 'MemoMind' \
  --query 'MemoMind review' \
  --output ./runs/youtube-memomind-test
```

检查和导出已保存记录：

```zsh
python3 scripts/crawl.py check --output ./runs/youtube-memomind-test
python3 scripts/crawl.py export --output ./runs/youtube-memomind-test
```

数据逐条保存到 `records.sqlite3`，并由导出命令生成 `records.csv` 和 `records.jsonl`。`last_run.json` 记录本次状态、新增/更新/未变更数量、已保存总量、错误和覆盖范围。`status=completed_visible` 表示采集器已正常走完本次 API 返回的可见结果，不代表平台全量；若为 `interrupted`、`failed` 或 `backend_limited`，已保存记录仍可检查和分析，但本次采集不算正常完成。重复运行同一个任务目录会按来源与查询校验任务身份，并按稳定 ID 更新或去重记录。

## 4. API 调用与数量边界

采集流程依次使用 `search.list` 找公开搜索结果、`videos.list` 读取视频标题与统计字段、`commentThreads.list` 读取顶层评论和可见回复，并在回复尚未完整返回时使用 `comments.list` 按父评论继续分页。代码会跟随平台返回的 `nextPageToken`，没有额外设置本地总页数、视频数或评论数上限；每个 API 请求仍须遵守平台的页面大小、可见范围、评论关闭状态、权限和配额。

YouTube Data API 项目配额由 Cloud Console 显示，并可能调整。Google 文档当前说明默认每日包含 `search.list` 调用额度及其他端点的单位额度；无效请求也会消耗额度。采集规模越大，搜索关键词、视频页和评论页越多，耗时与配额消耗通常也越高。运行遇到 403、配额错误、评论关闭或权限拒绝时，程序会保存已写入记录并在报告中说明，不会把这些情况解释成“没有评论”或尝试绕过限制。查看[官方配额说明](https://developers.google.com/youtube/v3/getting-started)和[各请求成本表](https://developers.google.com/youtube/v3/determine_quota_cost)。

## 5. 网页视频分析

YouTube Data API 不提供完整视频文件下载接口。本仓库在媒体下载不可用时，只能按已确认的授权范围打开普通 YouTube 页面，对可见播放器按设置的间隔截帧并做本地 OCR；不会把网页截帧说成完整视频文件，也不会因此获取隐藏或不可见内容。需有适用于网页画面捕获和本地 OCR 的书面批准。视频页面、登录状态、地区或播放器限制导致失败时，会保留失败状态并继续报告评论结果，不绕过这些限制。
