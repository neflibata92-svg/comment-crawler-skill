# Kickstarter

```bash
comment-crawler collect kickstarter --target 'https://www.kickstarter.com/projects/creator/project/comments' --output ./runs/project-kickstarter --dry-run
```

替换为真实项目留言页。需要 browser extra 和 Chromium；当前实现不要求登录，不支持私有或登录受限内容。

读取页面提供的评论 URL，再跟随 more_comments。链接可能带临时签名，不写入日志或输出；入口消失、请求失败、非预期域名或重复游标时停止，不猜测接口或绕过验证。

使用评论原生 ID 去重，保留响应中的 parent_id/parent_comment_id；缺少父 ID 时标记 not_provided，不能自动断言是顶层留言。不展开另一个未经验证的回复接口，始终报告 backend_limited：没有证明当前返回列表覆盖全部子回复。删除标记记录跳过；现有本地记录不会自动删除。
