# 来源与验证边界

本仓库从作者提供的本地评论采集项目提炼，经作者批准制作并公开发布。作者确认历史脚本曾完成目标信息采集；本次没有独立核验那些历史目标的全量性。

| 发布代码 | 方法来源 | 发布版变化 |
|---|---|---|
| browser.py / taobao_dom.py | taobao_reviews.py、jd_reviews.py、kickstarter_reviews.py、对应登录脚本 | 参数化、普通 Playwright、统一记录、逐条 SQLite、明确停止原因 |
| collectors/youtube.py | memomind_crawler/collectors/youtube.py | 去掉品牌过滤、完整分页、缺失回复补齐、旧视频更新、sink 写入 |
| collectors/reddit.py | memomind_crawler/collectors/reddit.py | 搜索分页、更多评论展开、sink 写入 |
| collectors/reddit_opencli.py | memomind_crawler/collectors/reddit_opencli.py | 独立 source、移除产品过滤、保留后端限制提示 |
| collectors/xiaohongshu.py | 本仓库新写；参考 OpenCLI 的公开页面选择器和 xiaohongshu-mcp 的评论展开说明 | 普通 Playwright 页面读取、关键词和笔记链接；按笔记检查点续跑、去重并报告字段质量；未复制第三方源码 |
| collectors/mediacrawler.py | MediaCrawler 外置 checkout 的命令行 JSONL 输出与字段模型 | 仅调用用户单独取得的源码；帖子与评论不设本地总量上限；搜索结果帖子需在标题或正文命中搜索词；导入一级和二级评论；在可用的平台请求媒体文件；不复制上游源码 |
| video_analysis.py | FFmpeg、Pillow 与可选 faster-whisper 本地处理 | 不联网调用模型；保留输入视频，生成关键帧、联系表、音频转写和分析提纲 |
| core | memomind_crawler/core | 去掉产品主题推断，保留字段、幂等 upsert 和导出 |
| Skill 文档 | 本地方法参考及本次源码核对 | 按平台分层、明确权限／覆盖／验证状态 |

没有复制 MediaCrawler 的源代码、真实评论、账号档案或历史 Git 提交。MediaCrawler 通过用户外置 checkout 和其自己的 Python 环境运行；`prepare-mediacrawler` 仅在用户指定目录修改浏览器配置、五个平台核心文件及知乎评论客户端，并为原文件建立 `.comment-crawler.bak` 备份。该外部项目的许可仍单独适用，见 [MediaCrawler LICENSE](https://github.com/NanmiCoder/MediaCrawler/blob/main/LICENSE)。MIT 仅覆盖本仓库代码与文档，不能替代平台访问授权或数据使用许可。

本版本不包含人工导入、媒体测评、历史产品数据或原环境配置。原始项目保留在作者本机，发布仓库独立历史。

本次原有本地验证包括离线合成响应、SQLite 提交与恢复、CLI 预检、字段质量统计和小红书合成 DOM。MediaCrawler 平台适配仅做源码字段映射和静态检查；未验证真实登录、平台授权、评论完整性、媒体文件下载或游标恢复。视频分析管线已加入本地 FFmpeg 抽帧和可选 Whisper 转写入口；未以真实视频运行验证。另有一次用户在登录态进行的 `memomind` 小红书实际试采，过程中被用户中断；数据质量和范围边界见 [验收记录](VALIDATION.md)。该试采发生在当前续跑与时间规范化实现之前，不证明当前版本在真实账户中的选择器、权限或全量性。平台文档链接用于接口形状核对，不代表平台认可此工具。
