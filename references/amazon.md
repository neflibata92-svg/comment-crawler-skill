# Amazon 商品评价

首版仅开放 `amazon.com` 美国站适配。本地样本通过；指定商品在用户自行完成页面验证后完成一次真实试采，页面只返回 8 条可见评价并提供请求更多评价入口，采集器报告 `backend_limited`。可传 10 位 ASIN 或美国站 `/dp/ASIN`、`/gp/product/ASIN` 商品链接；链接会归一为 `https://www.amazon.com/dp/ASIN`。其他国家站点需要分别核对页面结构后才能启用；目前会拒绝。没有关键词发现入口。

```bash
comment-crawler login amazon --profile ~/Library/Application\ Support/comment-crawler/amazon
comment-crawler collect amazon --target B000000000 --profile ~/Library/Application\ Support/comment-crawler/amazon --output ./runs/amazon-product --dry-run
comment-crawler collect amazon --target B000000000 --profile ~/Library/Application\ Support/comment-crawler/amazon --output ./runs/amazon-product --delay 2
comment-crawler check --output ./runs/amazon-product
```

把示例 ASIN 换成目标商品。用户在独立浏览器窗口自行登录；浏览器档案应放在 Git 仓库外。需要安装 browser extra、Chromium；图片 OCR 需安装 ocr extra 与本机 Tesseract 英文语言数据。登录命令仅保存本机会话，不验证评价页访问能力。

采集器保存一条 `post` 商品记录及可见的 `comment` 评价。评价记录含评分、标题、正文、原始日期、可解析的 UTC 日期、匿名作者哈希、已验证购买标记、图片 OCR 文本及状态。图片由浏览器截取到内存处理，不建立图片临时文件；OCR 不可用时保留评价并标记状态。只有页面提供明确 `seller-response` 标记时才建立 `parent_id` 子记录；不推断其他回复。

分页按页面“下一页”链接继续，不设置本地数量上限。没有下一页但显示“请求更多评价”时报告 `backend_limited`，不自动提交请求。已有平台评价 ID 用于更新去重；缺失时按 ASIN、匿名作者、原始日期和正文生成合成键，可能误合并。中断后以同一输出目录重跑会从第一页重新扫描，已写入 SQLite 的记录保留；没有精确平台游标。登录、验证码、HTTP 拒绝、重复评价页及结构变化会终止任务并记录原因。结果仅反映本次入口返回的可见评价，不表示平台全量；以前保存而此轮未再出现的评价不会自动删除。
