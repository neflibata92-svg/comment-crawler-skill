# MediaCrawler 五平台参考源码快照与 Neflibata 署名方案

## 目的

在本仓库保留抖音、B站、微博、知乎和贴吧的 MediaCrawler 平台源码，便于查看本项目适配所依赖的上游实现及修改方式。副本仅作参考；实际采集仍使用用户在仓库外单独安装的 MediaCrawler checkout。

用户已确认拥有公开再发布修改版的书面许可，并选择从官方上游重建。由于本机未找到用户优化后的外置 checkout，本方案不会把重建结果描述成该 checkout 或其优化的恢复版本。

## 拟纳入内容

新增 `references/mediacrawler-source/`，固定来源为 `NanmiCoder/MediaCrawler` 的 `main` 提交 `19c956c962726f5ba6de338a04f82e6c4716b054`（2026-10-15 核对）。保留五个平台目录中的顶层 Python 源文件、修改后的 `config/base_config.py`、上游 `LICENSE` 原文，以及说明来源和变更的本地 `README.md`、`NOTICE.md`。

不纳入运行数据、账号资料、Cookie、媒体、依赖环境、上游测试夹具和小红书目录。此目录缺少 MediaCrawler 公共模块，不是可安装或独立运行的完整 checkout。

## 本地修改

在快照的五个平台 `core.py` 中应用本仓库 `prepare-mediacrawler` 已有的改动：将 `ENABLE_CDP_MODE` 和 `CDP_CONNECT_EXISTING` 设为 `False`，移除已识别的反检测脚本注入。知乎另包含现有分页改动：由核心调用将评论数参数传入客户端，客户端分页按该参数停止。其他平台源文件保持指定上游提交内容。

调用侧传入的大整数用于取消本项目的普通数量截断；这不证明平台返回全量，也不解除上游许可证、平台规则或账号可见范围的限制。

## 署名与许可证

仓库文档和本地 `NOTICE.md` 将维护者／本地修改者署名为“Neflibata”。上游版权声明、许可证文本和上游项目来源完整保留，不改写成仓库维护者版权。仓库根目录 MIT 许可不覆盖这个上游快照。上游许可证载明非商业学习用途，并禁止大规模采集或干扰平台运行；快照及文档会清楚保留这些限制。

将仓库当前公开的全部 20 个提交的 Git author name/email 统一映射为“Neflibata”及该 GitHub 账号对应的 noreply 邮箱，保留 author date、提交说明和文件树；committer 字段不改。检查发现其中 13 个提交有 GPG 签名。改写 author 会改变签名所覆盖的提交内容，因此这些原签名无法继续有效；用户于 2026-10-15 明确接受签名失效。所有现有提交哈希会因此变化。改写 `main`、`feature/comment-analysis`、`feature/mediacrawler-platforms`、`feature/xiaohongshu-comments` 四个公开分支，再把参考快照提交到重写后的 `feature/mediacrawler-platforms`。远端当前没有标签或开放／关闭 PR。推送时对四个分支逐一使用带原始远端 SHA 的 `--force-with-lease`，避免覆盖核对后新出现的远端更新。其他已有克隆需要重新 fetch 并同步分支。

## 文档更新

- 在根 `README.md` 标明项目维护者为“Neflibata”，并说明参考源码目录和外置 checkout 的运行关系。
- 将 `pyproject.toml` 的项目作者元数据标为“Neflibata”；根 MIT 许可证和上游 MediaCrawler 许可证的版权声明分别保留。
- 更新 `PROVENANCE.md`，列出快照来源、精确提交、包含文件、修改边界和许可边界。
- 更新 `references/mediacrawler.md`，区分参考快照与采集运行时使用的外置 checkout。

## 不在本次范围

- 不恢复、推测或冒称用户缺失的 MediaCrawler 优化 checkout。
- 不让采集器改用仓库内参考快照，不提供自动安装或切换逻辑。
- 不复制整个上游仓库、测试数据、登录状态、Cookie 或历史采集数据。
- 不更改现有五平台采集功能或评论数量策略。
- 不更改历史提交的文件树、说明、日期或 committer 字段；统一 Git author name/email，并按用户确认接受 13 个旧 GPG 签名失效。
- 不进行真实平台采集。

## 验收

- 快照来源提交和许可证可核对；LICENSE 与该提交中的原文完全一致。
- 五个平台源码能通过 Python 语法解析，且预期的浏览器与知乎分页改动可在目标文件中定位。
- 来源说明明确指出这是上游重建的参考副本、不是用户缺失的外置优化版，也不是完整可运行 checkout。
- 改写前后历史提交的文件树、提交说明和日期一致；四个分支中每个提交的 author 均为“Neflibata”。
- `git diff --check` 无错误；最终改动仅涉及快照目录、项目作者元数据、上述三份项目文档及本方案／执行计划文档。

## 已知限制

快照只固定一个上游提交，未来不会自动跟随上游。平台页面、上游接口和可见数据范围会变化；静态语法与来源检查不等于真实平台采集验证。历史重写会改变所有提交哈希，并使 13 个旧 GPG 签名失效；旧链接及未同步的本地克隆可能继续指向旧提交。用户确认的公开再发布许可将作为发布依据，但不替代随快照保留的上游许可证条款。
