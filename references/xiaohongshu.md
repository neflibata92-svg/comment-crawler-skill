# 小红书：关键词与笔记评论（开发分支）

首版只读，使用普通 Playwright 浏览器访问用户有权查看的页面。关键词先在小红书页面搜索笔记，再打开搜索结果中的笔记读取一级评论和楼中楼；也可以直接传入 `https://www.xiaohongshu.com/explore/24位笔记ID` 或搜索结果中的完整笔记链接。没有人工导入、发布或点赞操作。

`/search_result_ai?keyword=...` 是关键词结果页，不是单篇笔记。将其中的 `keyword` 值传给 `--query`；页面若采用新的 AI 搜索布局但未呈现可识别的笔记卡片，会标记 `backend_limited`，不能把搜索页可打开当作评论采集完成。

## 登录

安装 `.[browser]` 和 Chromium 后，在**仓库外**准备专用档案目录，运行：

```bash
comment-crawler login xiaohongshu --profile /本机私有目录/xhs-profile
```

命令会打开浏览器。用户在小红书登录界面自行扫码、输入验证码或完成账户确认，完成后回终端按回车。程序不索取密码、Cookie 或验证码，也不读取日常 Chrome 档案。登录命令只能检查当前页面是否显示登录／验证拦截，不能单独证明搜索和评论权限。

## 采集

```bash
comment-crawler collect xiaohongshu --query '相机体验' --profile /本机私有目录/xhs-profile --output ./runs/xhs-camera --dry-run
comment-crawler collect xiaohongshu --query '相机体验' --profile /本机私有目录/xhs-profile --output ./runs/xhs-camera --delay 2
comment-crawler check --output ./runs/xhs-camera
```

可重复使用 `--query`，或单独使用 `--target 'https://www.xiaohongshu.com/explore/笔记ID'`。同一输出目录的来源、关键词和笔记目标固定。签名查询参数仅供浏览器打开页面；数据库及任务标识只保留规范化笔记 URL，不保存 `xsec_token`。浏览器档案和任务数据不得提交到公开仓库。

搜索和评论都逐轮滚动并去重，没有本地总笔记数或评论数上限。连续六轮无新增标记 `stalled`，**这表示当前页面没有继续加载，不代表平台全量**。若始终没有提取到笔记或评论，标记 `backend_limited`：当前无法可靠区分真空结果、登录限制与页面结构变化。遇到验证或异常跳转时停止。评论没有稳定平台 ID 时使用合成 ID 并标记；这样的评论若正文或显示时间变化，可能被当作新记录。

## 验证状态与依据

本分支已进行离线合成 DOM 和 CLI 测试，尚未在真实小红书账户上验证关键词深翻、评论展开及登录状态。当前选择器可能随页面更新而失效；实际任务应先小范围试采，并在 `last_run.json` 中核对状态与覆盖提示。

2026-10-13 本机未登录页面诊断被平台重定向到“安全限制”（300012）。因此未运行真实登录或评论试采；若使用时遇到同类页面，立即停止并检查平台允许的访问条件，不进行绕过。

方法参考：[小红书开放平台文档](https://open.xiaohongshu.com/document/developer/file/33)目前公开列举的权限以电商业务为主；[OpenCLI 小红书适配说明](https://github.com/jackwener/OpenCLI/blob/main/docs/adapters/browser/xiaohongshu.md)提供页面搜索和评论选择器线索；[xiaohongshu-mcp](https://github.com/xpzouying/xiaohongshu-mcp)提供评论展开行为参考。这些第三方实现不构成平台授权，也未作为本包运行依赖或复制源码。
