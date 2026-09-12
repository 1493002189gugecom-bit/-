# 模型核验记录（阶段 A2/A3）

日期：2026-09-12
核验人：实施阶段自动核验，来源为官方文档与发行页
存储位置：`D:\smart-home-models\`（用户要求放 D 盘；可用环境变量 `SMART_HOME_MODELS_DIR` 覆盖）

## 运行时

| 项目 | 结果 |
| --- | --- |
| Python | 3.11.9（`.venv`） |
| sherpa-onnx | 1.13.8（含 `sherpa-onnx-core` 1.13.8，cp311 win_amd64 wheel） |
| 其他 | numpy 2.4.6、sounddevice 0.5.6、soundfile 0.14.0、click 8.5.0、sentencepiece 0.2.2、pypinyin 0.55.0；测试/监控：pytest 9.1.1、psutil 7.2.2 |
| API 可用性 | `KeywordSpotter`、`VadModel`（通过 `VadModel.create` 构造）、`OfflineRecognizer`、`OfflineTts` 均存在 |
| CLI | `sherpa-onnx-cli.exe text2token` 可用（缺 `click` 时无法运行，已补装） |

`pip check` 无冲突。

## 模型 1：唤醒（KWS）

- 名称：`sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20`
- 地址：https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20.tar.bz2
- 官方文档：https://k2-fsa.github.io/sherpa/onnx/kws/pretrained_models/index.html
- 语言：中文＋英文
- 官方列出的文件大小：encoder int8 4.4M、encoder fp32 12M、decoder 743K、joiner int8 85K、joiner fp32 331K、en.phone 3.2M、tokens 1.9K；整包约 38M
- 说明：`chunk-16` 延迟约 320ms，`chunk-8` 约 160ms（延迟低通常准确率低）。int8 encoder/joiner 可与 fp32 decoder 搭配。
- 唤醒词转换：`sherpa-onnx-cli text2token --tokens <tokens.txt> --tokens-type phone+ppinyin --lexicon <en.phone>`，关键词行需带 `@原词`（不能含空格，用 `_` 代替）。
- 备选：`sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01`（纯中文，整包约 18M），转换用 `--tokens-type ppinyin`。

## 模型 2：端点检测（VAD）

- 名称：Silero VAD（`silero_vad.onnx`）
- 地址：https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx
- 官方文档：https://k2-fsa.github.io/sherpa/onnx/vad/silero-vad.html
- 用途：麦克风持续采集时的语音活动检测，与 KWS 同一运行时

## 模型 3：识别（ASR）

- 名称：`sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17`
- 地址：https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2
- 官方文档：https://k2-fsa.github.io/sherpa/onnx/sense-voice/pretrained.html
- 语言：中文（普通话）、粤语、英语、日语、韩语
- 官方列出的大小：`model.int8.onnx` 228M、`tokens.txt` 308K；另含 `LICENSE`、`test_wavs/`
- 说明：该版本支持标点（`use_itn=1`）。等价 fp32 版本包内含 `model.onnx` 894M，本阶段用 int8。
- 备选：`sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09`（粤语增强，不支持标点）

## 模型 4：合成（TTS）

- 名称：`kokoro-multi-lang-v1_1`（中英，103 音色）
- 地址：https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/kokoro-multi-lang-v1_1.tar.bz2（另有 `kokoro-int8-multi-lang-v1_1.tar.bz2`）
- 官方文档：https://k2-fsa.github.io/sherpa/onnx/tts/pretrained_models/kokoro.html
- 上游模型：https://huggingface.co/hexgrad/Kokoro-82M （82M 参数）
- 说明：v1.0 包中 `model.onnx` 为 310M（文件大小）；采样率固定 24000 Hz。中文音色 ID 45–48（zf_xiaobei 等）、49–52（zm_yunjian 等）。
- 本阶段优先下载 **int8** 版本以降低内存占用；若中文听感不达标再评估非量化版本或 CosyVoice。

## 许可证结论（逐包核对，2026-09-12）

| 模型 | 包内许可证 | 结论 |
| --- | --- | --- |
| Kokoro int8 v1.1 | 包内 `LICENSE` = **Apache License 2.0** | 可用；需保留许可证与声明 |
| SenseVoiceSmall int8 | 包内 `LICENSE` 仅一行链接，指向 https://github.com/modelscope/FunASR#license；实测该仓库 `LICENSE` 为 **MIT License (c) 2025 FunASR** | 可用；保留版权声明 |
| KWS zipformer zh-en 3M | **包内没有 LICENSE 文件** | ⚠️ 未解决，见下 |
| Silero VAD | 单独 `.onnx` 文件，无随附许可证文本 | ⚠️ 未解决，见下 |

### 未解决事项（必须在正式使用/分发前处理）

**1. KWS 唤醒模型（中英 3M）**
- 下载包内无任何许可证文本，官方发行页也未标注许可证。
- 该系列模型的备选版本 `sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01` 训练于 **WenetSpeech** 数据集，而 WenetSpeech 官方仓库要求“read the license, and follow the instruction to apply for the PASSWORD”，属于**需申请、可能限学术用途**的数据集。
- 本阶段只做本机开发验证，不做分发；**若要商用或分发，必须先向 k2-fsa / 上游数据方确认授权**。
- 决策：先继续用中英 3M 版本做验证，把该风险写入阶段报告。若后续要发布，需替换为许可证明确的唤醒方案或自行训练。

**2. Silero VAD**
- 从 sherpa-onnx 发行页下载的 `silero_vad.onnx` 是转换后的模型文件，未随附许可证文本。
- 上游 Silero VAD 通常以 MIT 发布，但**本机包内无文本可证**，故同样标记为待确认。

**结论：ASR 与 TTS 的许可证已确认可用；唤醒与 VAD 的许可证文本缺失，已记录为待确认项，不阻塞本机开发验证，但阻塞对外分发。**

## 实际下载与占用（2026-09-12）

| 包 | 压缩包大小 | 说明 |
| --- | --- | --- |
| kokoro-int8-multi-lang-v1_1 | 140.2 MB | 解压后含 `model.int8.onnx` 109 MB、`voices.bin` 51.3 MB |
| sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20 | 31.4 MB | 含 chunk-8/16、fp32/int8 encoder |
| sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17 | 155.5 MB | `model.int8.onnx` 228.15 MB |
| silero_vad.onnx | 0.6 MB | 单文件 |

`D:\smart-home-models\` 解压后总计约 **801 MB**。

## 待办

1. ~~下载四个包到 `D:\smart-home-models\`，记录实际大小与总占用。~~ 已完成
2. ~~解压后读取每个包的 LICENSE/README 并补全本文件。~~ 已完成（唤醒/VAD 缺文本，已记录）
3. 用 `sherpa-onnx-cli text2token` 生成唤醒词文件（候选：小屋小屋、你好小屋）。
4. 解决唤醒与 VAD 的许可证确认（仅在对外分发前阻塞）。
