# comment-crawler 数据字段映射

本参考对应同仓库的 `ReviewRecord` 结构及其 SQLite/CSV/JSONL 输出。读取时以当前文件为准；若字段版本不同，先报告实际字段并据实映射，不推测缺失值。

## 记录来源与格式

- 一个任务目录通常同时有 `records.sqlite3`、`records.csv`、`records.jsonl`。它们是同一批记录的不同表示，不是三份独立样本。优先从该任务的 SQLite 主库读取；若不可用，选一个导出文件并用 `task.json` 核对来源与目标。
- `task.json` 用于识别来源和任务目标；`last_run.json` 用于理解运行状态、警告、按内容类型计数和字段完整度。两者不是评论记录，不要加进评论条数。
- `progress.json` 是小红书扫描检查点，不是评论内容或平台覆盖率。
- 不同任务目录、时间快照及不同后端默认分开分析。用户明确要求合并时，保留任务来源；同一任务在 SQLite、CSV、JSONL 多种格式重复出现时只选一种输入。
- `last_run.json` 的状态和本地总库记录数不证明平台全量。结合其中的 warnings、失败项、扫描状态及 `content_completeness` 描述样本限制。

## 字段映射

| `ReviewRecord` 字段 | 分析字段/用途 | 限制 |
| --- | --- | --- |
| `source` | `source` | Reddit OAuth 与 OpenCLI 是不同 source 值，分别保留。 |
| `content_type` | `content_type` | 可见 `post`、`video`、`comment` 等类型；按数据实际值识别，不假设只包含评论。 |
| `external_id` | `comment_id`（评论）或内容 ID（帖子/视频） | 可能是平台 ID，也可能是合成 ID；必须结合 `metadata.id_kind`（如存在）识别，不能称合成 ID 为平台原生 ID。 |
| `parent_id` | `parent_id` | 对 `comment` 记录，非空表示采集器记录了父关系；空值只表示未提供/未记录，不能证明一定是顶层评论。不要推断完整楼层链。 |
| `metadata.comment_level` | `content_group` 的层级证据 | 统一口径为一级评论 `1`、回复 `2`；较深回复若来源保留则按 `reply` 汇总。缺失时结合平台父 ID 规则；仍不明确就标记 `unknown`。 |
| `body` | `text_original`（评论正文） | 采集器会压缩连续空白；这是采集器保存的原文，不等于网页字节级原文。 |
| `title` | 可选的 `title_original` 或帖子上下文 | 对帖子/视频与评论分开保存；不能把标题拼入评论正文后计数。 |
| `url` | `source_url` / 证据链接 | 可用于回溯；无法公开访问或 URL 为空时，改用文件位置键。 |
| `published_at` | `published_at` | 规范为 UTC；缺失或原始值解析失败时不得补齐。页面显示日期不一定具备时区精度。 |
| `captured_at` | `captured_at` | 抓取时间，不是评论发布时间。 |
| `author_hash` | `anonymous_author_id` | 这是按来源隔离的哈希；可用于单一来源内去重作者数，不可跨来源识别同一个人，也不代表匿名风险为零。 |
| `content_completeness` | 完整度/质检字段 | `full`、`partial`、`index_summary` 等值描述单条内容完整度，不是渠道覆盖率。片段或摘要不可直接当作完整评论。 |
| `score`、`rating`、`reply_count` | 保留为独立互动/评分字段 | 含义依平台而异，不要互相替换或跨平台直接比较。 |
| `metadata` | 来源特有字段 | 先检查每个平台真实键名与含义；如点赞等只在 metadata 中出现，保留原始字段与渠道口径。未知字段不自行解释。 |
| `is_official`、`language` | 原字段/分组辅助 | 不据此推测用户身份、赞助关系或购买状态。 |

## 目标产品复核与标注回写

- CLI 的 `--product`、`--brand` 是本次分析目标元数据，不覆盖原记录的 `product_or_brand`，也不代表该记录已经属于目标产品。
- `product_relevance` 是评论级判断，首轮默认为 `unknown`。必须根据评论文本和明确上下文人工标为 `related`、`unrelated` 或 `uncertain`；帖子标题或搜索关键词命中不能单独证明评论相关。
- `annotation_status` 区分 `rule_prelabel` 与 `manual_reviewed`。自动主题、痛点、体验状态、意图、情绪和障碍都是待复核线索；严重程度不做自动数值评分。
- 如果评论正文类型可以确认、但来源/父关系不足以区分顶层评论与回复，可在人工标注表中修正派生字段 `content_group`；允许值为 `top_level`、`reply`、`review` 或 `unknown`。不要仅凭空 `parent_id` 就认定为顶层评论。
- 首轮 `cleaned_comments.csv` 可作为标注表。保留 `analysis_record_key`，在同一份 CSV 中修正标签，设置复核状态和产品关联，再以同样原始输入通过 `--annotations` 导入。
- `--scope verified-target` 的统计分母只包括 `manual_reviewed + related + is_included=true` 的有效评论。未复核、不相关、不确定、排除或待复核内容不计入目标产品 N。
- 标注键绑定这批清洗记录；若改换输入文件、任务快照或去重结果，出现未知/重复键时应停止并重新匹配，不可强行复用。
- `evidence_index.csv` 将标签类型、标签、评论记录键、评论 ID/文件位置、来源链接、简短脱敏摘录和人工/规则状态逐条对应，正文引用被截短时以该文件回查全量证据。

## 去重与内容类型

- 当前采集器的逻辑记录键为 `source + content_type + external_id + parent_id`。SQLite 另存 `record_key` 和 `content_hash`；CSV/JSONL 通常不导出这两个数据库列。
- 有 `record_key` 时可用于识别仓库内同一逻辑记录；它不是平台评论 ID。跨导出合并时，不要把相同记录的多种文件格式当作多条评论。
- 同一个逻辑键在不同快照正文不一致时，保留版本/冲突信息并列入复核；只有分析“最新状态”时才按 `captured_at` 选取代表版本，并说明规则。
- 分析表会在逻辑 ID 去重后，按来源、内容类型、帖子/评价、父评论 ID 和逐字相同正文合并精确同文评论；`duplicate_comment_ids_json`、`duplicate_author_ids_json`、`source_locations_json` 与 `duplicate_count` 保留所有可追溯来源。作者数按匿名作者 ID 并集计算。不同来源、帖子或父评论关系不互相合并，标点、大小写不同的近似文本仍独立保留并可聚类。
- `content_type == comment` 同时可能包含顶层评论与回复。优先读取 `metadata.comment_level`，其次结合 `parent_id` 和来源规则分层；字段与关系都不足时标记 `unknown`，不擅自归类成顶层。
- `post`、`video` 等记录可作为内容上下文或来源覆盖单位，但不能计入评论 N。评论统计应明确是否包含回复，并分别给出分母。
- 小红书评论可能使用合成 ID；同一内容被重新采集时，检查 `metadata` 中的 ID 类型和父关系。不要把合成键的不稳定误读成用户新增评论或原生 ID。

## 采集结果解释

- 采集验收中的“新增/更新/未变化”是运行变化量，不等于最终唯一评论量。
- `check` 的历史总记录数可能含帖子/视频；按 `content_type` 过滤后再计算评论量。
- 受平台可见范围、分页/回复限制、权限、失败和中断影响的结果，只代表本次本地记录。把 `task.json`、`last_run.json` 与字段完整度作为覆盖说明，不作全量保证。
