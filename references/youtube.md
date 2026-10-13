# YouTube

前提：用户有权使用的 YouTube Data API v3 项目及环境变量 `YOUTUBE_API_KEY`。无需网页登录；`doctor` 只检查变量非空，不验证 Key。

```bash
comment-crawler collect youtube --query '产品名称 review' --output ./runs/product-youtube --dry-run
```

授权范围确定后去掉 dry-run。搜索跟随 nextPageToken；顶层评论使用 commentThreads，线程中回复不足时用 comments.list(parentId) 分页补齐。评论 ID 稳定，旧视频会重新刷新评论。`read_comments: false` 明确关闭评论；不再支持用旧 max_pages 参数截断。

搜索结果受平台索引和 API 可见性影响。评论关闭、配额或权限错误停止该来源并保存已提交记录，用户先处理原因，再明确恢复。不可把 HTTP 403 自动解释为“没有评论”。

参考：[搜索分页](https://developers.google.com/youtube/v3/docs/search/list)、[回复分页](https://developers.google.com/youtube/v3/docs/comments/list)。
