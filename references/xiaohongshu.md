# 小红书：笔记与评论

只读使用普通 Playwright 浏览器访问用户有权查看的页面。关键词先搜索笔记，再打开笔记页保存页面可见的标题、正文、匿名作者标识、发布时间和互动数，并读取一级评论和楼中楼；评论记录在 `metadata.comment_level` 标记层级，回复通过 `parent_id` 关联父评论。也可以直接传入 `https://www.xiaohongshu.com/explore/24位笔记ID` 或搜索结果中的完整笔记链接。设置外置 MediaCrawler 后，可对成功打开的笔记请求完整视频文件；封面和图文图片先在本机 OCR 并保存文字，再删除图片。没有人工导入、发布或点赞操作。

笔记保存为 `content_type=post` 记录，评论保存为 `content_type=comment` 记录；两者通过规范化笔记链接关联。作者仅以来源隔离的哈希标识保存；互动数按页面原文放在 `metadata.visible_engagement` 中（点赞、收藏、评论、分享），不把“万”等显示值强转为整数。正文或其他字段不可见时会留空，质量报告会列出缺失字段。

`/search_result_ai?keyword=...` 是关键词结果页，不是单篇笔记。将其中的 `keyword` 值传给 `--query`；页面若采用新的 AI 搜索布局但未呈现可识别的笔记卡片，会标记 `backend_limited`，不能把搜索页可打开当作评论采集完成。

## 登录

安装 `.[browser]` 和 Chromium 后，在所有 Git 仓库之外准备专用档案目录，运行：

```bash
comment-crawler login xiaohongshu --profile ~/Library/Application\ Support/comment-crawler/xhs-profile
```

命令会打开浏览器。用户在小红书登录界面自行扫码、输入验证码或完成账户确认，完成后回终端按回车。程序不索取密码、Cookie 或验证码，也不读取日常 Chrome 档案。档案路径必须在所有 Git 仓库之外，`login` 和 `collect` 都会检查。登录命令只能检查当前页面是否显示登录／验证拦截，不能单独证明搜索和评论权限。

## 采集

```bash
comment-crawler collect xiaohongshu --query '相机体验' --profile ~/Library/Application\ Support/comment-crawler/xhs-profile --output ./runs/xhs-camera --dry-run
comment-crawler collect xiaohongshu --query '相机体验' --profile ~/Library/Application\ Support/comment-crawler/xhs-profile --output ./runs/xhs-camera --delay 2
# 同一任务增加媒体下载；复用专用小红书档案
comment-crawler collect xiaohongshu --query '相机体验' --profile ~/Library/Application\ Support/comment-crawler/xhs-profile --mediacrawler-home /path/to/MediaCrawler --output ./runs/xhs-camera-media --delay 2
# 重新扫描已结束可见扫描的笔记
comment-crawler collect xiaohongshu --query '相机体验' --profile ~/Library/Application\ Support/comment-crawler/xhs-profile --output ./runs/xhs-camera --refresh-completed --delay 2
comment-crawler check --output ./runs/xhs-camera
```

可重复使用 `--query`，或单独使用 `--target 'https://www.xiaohongshu.com/explore/笔记ID'`。同一输出目录的来源、关键词和笔记目标固定。签名查询参数仅供浏览器打开页面；数据库、任务标识及 `progress.json` 不保存 `xsec_token`。浏览器档案和任务数据不得提交到公开仓库。

搜索和评论都逐轮滚动，直到连续六轮没有新笔记／评论记录键；已有记录的互动数或时间更新不会重置停止计数。没有本地总笔记数或评论数上限。`stalled` 表示当前页面连续无新增，**不代表平台全量**。若始终没有提取到笔记或评论，标记 `backend_limited`：当前无法可靠区分空结果、登录限制与页面结构变化；没有识别到评论结构的笔记保持待处理，后续运行会重试。遇到验证或异常跳转时停止。

媒体下载依赖用户单独取得并运行 `prepare-mediacrawler` 处理过的 MediaCrawler checkout。可通过 `--mediacrawler-home` 或 `MEDIACRAWLER_HOME` 提供路径；没有配置时仍会正常采集帖子和评论，但不会请求媒体下载。下载步骤复用传入的专用 `--profile`，并只处理本次成功打开的笔记。图片 OCR 需要 `python -m pip install '.[ocr]'` 以及本机 Tesseract 的 `chi_sim`、`eng` 语言数据。OCR 文字先写入 `metadata.media_assets.image_ocr` 和 `.mediacrawler/image_ocr.json`，持久化后才删除图片；缺少依赖或失败的图片会保留并标记状态。

小红书任务会在输出目录写入 `progress.json`：搜索结果每次重新打开并扫描，因为页面没有可持久化的搜索游标；每发现一篇笔记就立即记入检查点。已结束可见扫描的笔记默认跳过；使用 `--refresh-completed` 可重新扫描这些笔记。若中断在一篇笔记中，该笔记的评论会从头重读，再用稳定记录键去重。若当前搜索结果中的笔记均已有结束扫描检查点，本次作为成功的无操作运行返回。检查点中的 `scanned` 表示这篇笔记本次可见评论扫描已停滞结束，不表示平台全量。签名链接只在内存中用于打开当前搜索结果，不写入检查点。检查点启用前的旧任务若没有该文件，会将已有笔记标为待扫描并重扫一次；旧版 `completed` 状态会自动迁移为 `scanned`。重扫时会先把该笔记数据库中旧版按作者和时间生成的合成评论 ID（含父评论引用）迁移到当前稳定键，避免重复插入。单篇笔记的 404 等请求失败会留待重试并继续后续笔记；401、403 或 429 会停止采集。评论缺少平台 ID 时使用合成 ID，以笔记、楼层／父评论和正文生成；同一笔记同一楼层的相同正文只保留一条，即使作者不同；单次扫描保留首次遇到的作者标识，后续刷新可能更新为当前页面首次返回的作者标识。不同楼层或不同笔记仍分别保存。重复扫描或相对时间变化不会重复插入。由于 ID 是合成值，正文变化仍可能形成新记录。

`last_run.json` 和 `check` 会显示帖子／评论数量、字段完整度、帖子互动数缺失情况，以及平台 ID／合成 ID 数量。`published_at` 是 UTC ISO-8601；原始页面显示文本保存在 `metadata.published_at_raw`，`published_at_precision` 标记 `exact`、`day`、`estimated_*`、`unparsed` 或 `missing`。无法可靠解析的文本不会冒充成日期；估算时间会明确标记精度。

## 验证状态与依据

笔记正文和互动数的页面选择器可能随小红书页面更新而失效；无法识别的字段会留空，不影响继续读取评论。实际任务应检查 `last_run.json` 和 `comment-crawler check` 中的状态与字段覆盖。

2026-10-13 用户在专用登录态以 `memomind` 搜索页可见结果做了真实试采，运行中由用户中断；统计和缺失字段详见[验收记录](../VALIDATION.md)。另一次未登录页面诊断被平台重定向到“安全限制”（300012）。遇到验证、异常跳转或访问限制时立即停止并检查平台允许的访问条件，不进行绕过。

方法参考：[小红书开放平台文档](https://open.xiaohongshu.com/document/developer/file/33)目前公开列举的权限以电商业务为主；[OpenCLI 小红书适配说明](https://github.com/jackwener/OpenCLI/blob/main/docs/adapters/browser/xiaohongshu.md)提供页面搜索和评论选择器线索；[xiaohongshu-mcp](https://github.com/xpzouying/xiaohongshu-mcp)提供评论展开行为参考。这些第三方实现不构成平台授权，也未作为本包运行依赖或复制源码。
