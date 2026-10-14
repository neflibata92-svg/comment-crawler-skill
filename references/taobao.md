# 淘宝／天猫

安装 browser extra 和 Chromium。用户在专用目录里自行登录，不使用日常 Chrome 默认档案。

```bash
comment-crawler login taobao --profile ./profiles/taobao
comment-crawler collect taobao --target 'https://detail.tmall.com/item.htm?id=123456' --profile ./profiles/taobao --output ./runs/product-taobao --dry-run
```

123456 为示例 ID，执行前替换真实目标。登录命令打开可见浏览器；用户扫码并确认后，终端回车关闭浏览器。它仅保存会话，不验证评论读取权限。登录和采集不要同时使用同一档案。

采集打开评论抽屉，滚动并提取正文、日期规格、追评、点赞和图片数，逐条提交。相同合成 ID 的追评变化会更新；缺少原生评论 ID，合成键依赖作者哈希、规格时间、正文，不能保证跨页面变更稳定。

当前表结构是扁平商品评价：每条评价作为一级记录，没有从淘宝／天猫页面提取到稳定的“某用户回复了哪条评价”关系。`append` 是评价卡片上的追评文本，保存在同一记录的 `metadata.append`，不是另一个用户的子评论，所以不会生成 `parent_id` 或回复树。若页面后续提供稳定的回复 ID、父评价 ID、作者和时间，再单独补充子记录映射；当前不能根据追评文本猜测用户回复关系。

连续 6 轮无新增或更新后返回 stalled，不宣称全量；DOM 结构变化、抽屉关闭、登录或验证码时停止。虚拟列表不因卡片数量不变直接视为结束。页面方法沿用历史选择器，发布版普通 Playwright 未真实复测。
