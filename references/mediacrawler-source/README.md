# MediaCrawler 五平台参考源码

此目录保留 MediaCrawler 抖音、B站、微博、知乎和贴吧适配器的参考源码，供审阅本仓库适配方式使用。它是基于官方上游重建的**局部参考快照**，不是缺失的外置优化 checkout，也不是完整、可安装或可运行的 MediaCrawler。

## 来源

- 上游项目：[NanmiCoder/MediaCrawler](https://github.com/NanmiCoder/MediaCrawler)
- 固定提交：`19c956c962726f5ba6de338a04f82e6c4716b054`
- 核对日期：2026-10-15
- 本地维护者与适配修改者：Neflibata

仅包含五个平台目录中的顶层 Python 文件、`config/base_config.py` 和上游 `LICENSE`。不包含小红书、测试夹具、媒体、采集数据、账号档案、Cookie、依赖环境或 MediaCrawler 公共模块。

## 本地适配变化

- `config/base_config.py` 将 `ENABLE_CDP_MODE` 与 `CDP_CONNECT_EXISTING` 设为 `False`。
- 五个平台的 `core.py` 移除本仓库适配器识别到的反检测脚本注入。
- 知乎 `core.py` 将评论读取范围传给客户端；知乎 `client.py` 按传入数量停止分页。
- 清理抖音 `core.py` 中一个空白行的尾随空格，以通过仓库空白检查。
- 其他平台文件保持上述固定上游提交内容。

## 运行边界

采集器不会导入或执行此参考目录。实际采集仍需要用户在仓库外单独安装的 MediaCrawler checkout，并通过 `MEDIACRAWLER_HOME` 指向该 checkout。采集运行前使用 `comment-crawler prepare-mediacrawler` 在用户指定的外置目录中准备文件。

## 许可证

此快照适用随附的上游 `LICENSE`。仓库根目录的 MIT 许可证不覆盖此目录。请在使用前阅读上游许可；它限定非商业学习用途，并禁止大规模采集或干扰平台运行。维护者确认已取得公开再发布修改版的书面许可；该许可不替代或扩大随附许可证载明的其他使用条件。

来源、变更和署名详情见 [`NOTICE.md`](NOTICE.md)。
