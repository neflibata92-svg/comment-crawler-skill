# Reddit：两个后端共存，单次任务选一个

优先选择具有当前访问权限的 OAuth API。若用户明确选择已有 Chrome 会话的 OpenCLI，可使用该后端，但必须说明其覆盖限制；OAuth 被拒绝后不可自动改走浏览器继续访问。

## OAuth

本机环境变量：`REDDIT_CLIENT_ID`、`REDDIT_CLIENT_SECRET`。配置 `user_agent` 使用自己的应用说明和用户名。当前代码采用 client_credentials，适用于应用获准访问的公开内容，不是用户账户授权或私密社区凭据。

```bash
comment-crawler collect reddit --query '产品名称' --subreddit photography --output ./runs/product-reddit --dry-run
```

不传 subreddit 时搜索全站公开返回结果。搜索跟随 after；评论展开 morechildren（每请求最多 100 个 ID），去重和循环检测；缺失请求的评论 ID 会报告不完整。API 本身的搜索窗口与访问范围不会因本地无上限而消失。

## OpenCLI

前提：已安装 OpenCLI、其扩展已连接 Chrome，用户已手动登录 Reddit。不能从“浏览器登录了”推断扩展连通。本包只调用 `reddit search/read`。

```bash
comment-crawler collect reddit_opencli --query '产品名称' --subreddit photography --output ./runs/product-reddit-browser --dry-run
```

适配命令：search 支持 query、--sort、--limit、--subreddit；read 支持 --sort、--limit、--depth、--replies、--max-length、--expand-more、--expand-rounds；两者支持 `-f json --window background`。先用本机 `opencli reddit search --help` 和 `opencli reddit read --help` 核对，缺少参数即停，不静默降低覆盖承诺。

当前适配版本 search 不返回 after，最多请求单页 100 条；read 最多展开 5 轮。显示数量按帖子公开评论计数设置，正文长度使用大值减少截断，这不等于无限能力。输出始终 backend_limited。评论缺少官方 ID，合成键包含位置和正文：排序变化可能重复、正文修改可能产生新记录，相同正文也可能碰撞。不要用它验证精确全量数。

OAuth 与 OpenCLI 来源标识不同，CLI 要求不同任务目录。对照时分别统计，不能直接累加。参考：[Reddit API](https://www.reddit.com/dev/api/)、[OpenCLI](https://github.com/jackwener/opencli)。
