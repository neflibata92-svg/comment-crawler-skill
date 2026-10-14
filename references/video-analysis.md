# 本地视频分析

平台采集器下载到的视频会自动进入本地帧 OCR 流程：FFmpeg 抽取关键帧，Tesseract 识别画面文字，结果保存后删除源视频。该自动流程需要本机 FFmpeg 与 OCR 依赖；处理失败时保留源视频并报告状态。完整说明见 [MediaCrawler 视频文件](mediacrawler.md#视频文件)。

下面的 `analyze-video` 命令用于处理用户另行提供或保留的本地视频文件，在本机提取关键帧、音轨和语音转写材料，供后续多模态分析使用。此命令默认保留输入文件，不代替平台评论采集，也不自动调用云端模型。

## 前置条件

- 安装 FFmpeg，并确认 `ffmpeg` 与 `ffprobe` 都能在终端运行。
- 在仓库环境安装视频 extra：

  ```bash
  python -m pip install '.[video]'
  ```

- `faster-whisper` 首次使用时需要取得对应模型文件；模型按 `--whisper-model` 指定，默认 `base`，可改成本地模型目录。处理过程使用 CPU 和 int8。

## 选择输入

优先使用采集器生成的视频处理结果。MediaCrawler 当前适配会为抖音、B站、微博请求视频文件；小红书在采集命令配置 `--mediacrawler-home` 或 `MEDIACRAWLER_HOME` 后也会请求已采集笔记的视频。下载文件位于任务目录 `.mediacrawler/<平台代码>/media/<帖子 ID>/`，会在帧 OCR 成功落盘后删除。YouTube Data API 不提供视频文件下载接口；在适用书面批准已确认时，采集器会改用普通网页播放器截帧 OCR，不保存完整视频。其他平台未提供本地视频文件时也会尝试网页截帧；该回退不转写音轨。

对目录递归发现 `.mp4`、`.m4v`、`.mov`、`.mkv`、`.webm`、`.flv` 和 `.avi` 文件。一条命令可处理多个文件：

```bash
comment-crawler analyze-video \
  --input ./runs/bilibili-test/.mediacrawler/bili/media \
  --output ./runs/bilibili-video-analysis \
  --whisper-model base \
  --language zh
```

不需要转写时加 `--no-transcribe`。`--scene-threshold` 调节场景变化抽帧敏感度（0–1，默认 0.35）；`--interval-seconds` 为静态画面额外抽帧间隔（默认 8 秒）。

## 输出

每个输入视频在输出目录下生成独立子目录，名称包含文件名和 SHA-256 前缀：

- `frames/`：按场景变化和定时间隔抽取的 JPG 帧。
- `contact-sheets/`：每 9 帧一张联系表，便于视觉检查。
- `frames.csv`：帧文件与时间戳对应表。
- `frames_ocr.json`、`frames_ocr.txt`：仅自动下载视频流程生成的采样帧文字识别结果；手动 `analyze-video` 命令当前不运行 OCR。
- `audio-16khz-mono.wav`：存在音轨且启用转写时提取的单声道音频。
- `transcript.json`、`transcript.txt`、`transcript.srt`：可用 Whisper 时生成的本地转写及时间戳。
- `analysis-brief.md`：视频分析提纲，要求区分画面事实、发布者陈述和推断并给出时间证据。
- `manifest.json`：视频文件名、SHA-256、时长、画面尺寸、编码、音轨状态、抽帧数量、转写状态和（自动采集流程中）源视频删除状态。

命令只在本机处理，不会上传完整视频、音轨、帧图或转写，也不会请求多模态模型。需要视觉模型进一步分析时，将 `contact-sheets/`、转写文件和 `analysis-brief.md` 交给用户选择的多模态工作流；分析结论应引用帧时间或字幕时间戳。转写状态为 `unavailable` 时检查 `faster-whisper` 安装和模型下载情况；无音轨时不会生成转写。

## 质量与边界

- 抽帧提供的是视频片段的采样视图，不保证覆盖每个动作或镜头细节。对关键演示应回看原视频对应时间段。
- Whisper 转写可能漏掉专有名词、重叠语音、音乐和低音量内容；应人工复核影响判断的字幕。
- 自动采集流程只对采样关键帧做 OCR，不保证读到帧间短暂文字，也不做物体识别、产品功能真伪核验或情绪推断；它保留抽取帧和 OCR 输出，OCR 与结果清单成功落盘后才删除视频源文件。独立 `analyze-video` 命令不对画面做 OCR，并保留输入视频。`analysis-brief.md` 是分析提示，不是已经完成的分析报告。
- 手动 `analyze-video` 命令保持输入视频不变；将分析输出保存在任务目录外或私有本地目录。视频和评论正文可能包含个人信息，勿把账号档案、Cookie 或无关个人文件放入输入目录。
