# 来源与验证边界

本仓库从作者提供的本地评论采集项目提炼，经作者批准制作并公开发布。作者确认历史脚本曾完成目标信息采集；本次没有独立核验那些历史目标的全量性。

| 发布代码 | 方法来源 | 发布版变化 |
|---|---|---|
| browser.py / taobao_dom.py | taobao_reviews.py、jd_reviews.py、kickstarter_reviews.py、对应登录脚本 | 参数化、普通 Playwright、统一记录、逐条 SQLite、明确停止原因 |
| collectors/youtube.py | memomind_crawler/collectors/youtube.py | 去掉品牌过滤、完整分页、缺失回复补齐、旧视频更新、sink 写入 |
| collectors/reddit.py | memomind_crawler/collectors/reddit.py | 搜索分页、更多评论展开、sink 写入 |
| collectors/reddit_opencli.py | memomind_crawler/collectors/reddit_opencli.py | 独立 source、移除产品过滤、保留后端限制提示 |
| collectors/xiaohongshu.py | 本分支新写；参考 OpenCLI 的公开页面选择器和 xiaohongshu-mcp 的评论展开说明 | 普通 Playwright 页面读取、关键词和笔记链接、无固定本地总量上限；未复制第三方源码 |
| core | memomind_crawler/core | 去掉产品主题推断，保留字段、幂等 upsert 和导出 |
| Skill 文档 | 本地方法参考及本次源码核对 | 按平台分层、明确权限／覆盖／验证状态 |

没有复制依赖库的源代码、真实评论、账号档案或历史 Git 提交。依赖通过包管理安装，许可证分别适用；Playwright 使用 Apache-2.0，OpenCLI 为外部工具，使用者应检查实际安装版本及许可。MIT 仅覆盖本仓库代码与文档，不能替代平台访问授权或数据使用许可。

本版本不包含人工导入、媒体测评、历史产品数据或原环境配置。原始项目保留在作者本机，发布仓库独立历史。

本次验证：离线合成响应、SQLite 提交与恢复、CLI 预检、安装及技能场景检查。没有执行真实平台采集，也没有证明普通 Playwright 在当前平台登录／评论页可用。平台文档链接用于接口形状核对，不代表平台认可此工具。
