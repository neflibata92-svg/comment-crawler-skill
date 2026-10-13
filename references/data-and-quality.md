# 数据与验收

主字段：source、content_type、url、external_id、parent_id、body、title、published_at、captured_at、author_hash、score、reply_count、rating、metadata。时间尽可能规范化为 UTC；无时区的历史页面日期仅为显示日期，不能据此推断真实 UTC 时刻。content_completeness 描述单条内容，不描述整个平台的覆盖率。

记录键使用 source + content_type + external_id + parent_id。更新时间不独立触发重复记录；正文、追评或互动变化更新。同任务重复运行可能同时出现 unchanged 和 updated，不必只接受 unchanged。合成 ID 的局限见对应平台参考；元数据缺失用未知表示，不推断官方、赞助或产品标签。

SQLite 每条提交，适合中断保护；记录 key 缓存在采集器内，超大任务仍可能消耗内存。导出失败不影响已提交主库。CSV 导出对以 =、+、-、@ 开头的文本增加单引号，降低表格公式执行风险；SQLite 与 JSONL 保留原文。

检查顺序：
1. task.json 来源、关键词或 URL 是否与任务一致。
2. last_run.json 状态、错误、warnings 与新增／更新／未变化数。
3. check 命令的总记录数是历史主库总数，不等于本次新增，也不等于评论数（可能包含帖子／视频）。
4. 区分 content_type，检查回复 parent_id 和缺失字段；人工抽查少量记录与原页面。
5. 记录采集时间、查询条件、平台窗口及剩余缺口；没有可核对基准时不声称全量。

恢复：相同目标和目录重新扫描；不保存易过期的签名游标。Ctrl+C 返回 130 并保存报告；kill -9 时报告可能是旧的，用 SQLite 和重新导出来核对。任务之间不共享文件夹，不同时运行两个进程写同一输出目录。
