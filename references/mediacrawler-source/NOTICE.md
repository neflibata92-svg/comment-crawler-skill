# 来源与修改说明

本目录包含从 [NanmiCoder/MediaCrawler](https://github.com/NanmiCoder/MediaCrawler) 重建的五平台参考源码，固定上游提交为 `19c956c962726f5ba6de338a04f82e6c4716b054`，核对日期为 2026-10-15。项目维护者确认拥有公开再发布修改版的书面许可。

上游源码及原版权声明仍归其各自权利人所有。上游 `LICENSE` 随本目录原样保留。Neflibata 仅对本说明列明的适配变化署名，不主张上游代码的原始作者身份。

本地变化基于 `scripts/comment_crawler/collectors/mediacrawler.py` 的 `prepare_mediacrawler` 逻辑：

1. 将配置中的 `ENABLE_CDP_MODE` 和 `CDP_CONNECT_EXISTING` 设为 `False`。
2. 从抖音、B站、微博、知乎和贴吧的 `core.py` 移除适配器可识别的反检测脚本注入。
3. 调整知乎评论核心调用和客户端分页，让上游传入评论数量参数并按该参数结束读取。
4. 清理抖音 `core.py` 中一个空白行的尾随空格，以通过仓库空白检查。

本目录是局部、不可独立运行的参考副本，不包含上游公共模块、依赖或测试数据，不参与本仓库采集器运行。许可证边界和使用条件以本目录 `LICENSE` 为准；根目录 MIT 许可不覆盖这里的上游代码。
