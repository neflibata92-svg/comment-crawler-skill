# 京东

```bash
comment-crawler login jd --profile ./profiles/jd
comment-crawler collect jd --target 123456 --profile ./profiles/jd --output ./runs/product-jd --dry-run
```

将示例 ID 替换为真实商品 ID，或传入 `https://item.jd.com/数字.html`。用户自行扫码；账户会话留在本机。需要 browser extra 和 Chromium。

现有方式使用登录浏览器访问商品评论分页入口，**旧脚本出现该接口不等于官方开放 API 授权**。实际运行前核对访问权限及适用条件。每次从第 0 页扫描；有 id/guid 优先使用，缺失时合成去重键并标记。追评和互动变化可以更新。不会删除平台已删除的旧评论。

空 comments 数组作为当前入口结束；字段缺失、非 JSON、HTTP 错误或重复页报错停止并保留已提交记录。取消固定总页数，保留请求间隔。接口可能只返回部分公开评论；普通 Playwright 版本尚未实测。
