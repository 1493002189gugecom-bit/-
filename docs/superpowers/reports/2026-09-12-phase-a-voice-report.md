# 阶段 A 本地语音验证报告

日期：2026-09-12
状态：**自动化基础验证完成；人工语音/试听门槛未完成，因此阶段 A 暂未放行**

## 1. 环境

| 项目 | 实测 |
| --- | --- |
| 操作系统 | Windows 11 家庭中文版 |
| CPU / 内存 | Ryzen 9 7945HX，16C/32T；15.7 GiB RAM |
| GPU | RTX 4060 Laptop，8188 MiB VRAM；本阶段模型全部显式使用 CPU provider |
| Python | `.venv` Python 3.11.9 |
| 运行时 | sherpa-onnx 1.13.8 / sherpa-onnx-core 1.13.8 |
| 模型目录 | `D:\smart-home-models`（用户要求放 D 盘，可用 `SMART_HOME_MODELS_DIR` 覆盖） |
| 麦克风 | 按优先列表自动选择；当前插着耳机时选中 `耳机式麦克风 (HyperX Virtual Surround Sound)`，否则回退 `麦克风阵列 (Realtek(R) Audio)`；不使用默认的网易虚拟音频设备 |
| 扬声器 | 按同一优先列表选择；当前为 `头戴式耳机 (HyperX Virtual Surround Sound)` |

依赖完整版本见 `apps/voice-service/requirements.lock.txt`。`pip check` 输出 `No broken requirements found.`。

## 2. 模型与许可证

| 用途 | 模型 | 本机验证 | 许可证状态 |
| --- | --- | --- | --- |
| KWS | sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20 | 模型初始化及官方样例推理成功 | 包内无 LICENSE；本机开发可用，对外分发前必须向上游确认 |
| VAD | silero_vad.onnx | 语音→静音转换返回正常 | 独立 ONNX 无随附许可证文本；分发前确认 |
| ASR | SenseVoiceSmall int8 2024-07-17 | 官方中/英/日/韩/粤五条样例推理成功 | 包内链接到 FunASR；当前上游 LICENSE 为 MIT |
| TTS | Kokoro int8 multi-lang v1.1 | 20 条中文全部生成 | 包内 Apache-2.0 |

详细来源、文件大小与许可证证据见 `docs/superpowers/notes/2026-09-12-model-review.md`。D 盘模型目录（压缩包＋解压目录）约 801 MB。

## 3. 自动化验证结果

### 3.1 代码与配置

- `python -m compileall -q apps/voice-service/src tools/voice-check`：通过。
- `python -m pytest apps/voice-service/tests -q`：**27 passed**（含静音块持续到达时仍触发超时、回复播放结束后才启动完整等待窗口、播放抑制丢弃输入、ASR 数字等价写法、空语料不得通过等回归测试）。
- `loop.py --startup-check`：Realtek 输入/输出及 KWS、VAD、ASR、TTS 全部初始化成功。
- `loop.py --no-tts --run-seconds 3`：实时输入流运行 3 秒，`audio queue overflows: 0`。
- `loop.py --no-tts --run-seconds 1`：生成 JSONL 会话日志，含 ISO 8601 时间戳、状态、设备、超时参数和停止事件；真人运行时还会记录 wake、ASR 转写/耗时、TTS 开始/结束、首帧估算和异常。
- `.venv`、模型、WAV、日志均由 `.gitignore` 排除。

### 3.2 ASR 冒烟

使用 SenseVoice 包内五条官方 WAV：

| 语言 | 结果 |
| --- | --- |
| 英文 | 成功转写 |
| 日文 | 成功转写 |
| 韩文 | 成功转写 |
| 粤语 | 成功转写 |
| 中文 | `开饭时间早上9点至下午5点。` |

5/5 管线成功；单条推理约 0.22–0.44 秒。该结果只证明模型和脚本可运行，**不替代真实麦克风的 30 条中文验收**。

### 3.3 TTS 生成

- `tts-20.tsv` 共 20 条，**20/20 成功生成** 24 kHz PCM16 WAV。
- 自动检查 20 个文件均存在、时长大于 0、峰值大于 0、采样率为 24000 Hz。
- 生成耗时约 2.49–6.50 秒/条（句长不同）。
- **听感尚未判定**；必须用 `listen_tts.py` 逐条播放并评分。

### 3.4 KWS 与自触发冒烟

- 官方 KWS 测试音频可产生关键词结果，证明模型与 token 管线可运行。
- 用 Kokoro 合成两个候选作非门槛冒烟：`小屋小屋` 命中；`你好小屋` 未命中。
- 把 20 条生成的普通家居播报 WAV 直接输入 KWS：**0 次检测**（补充冒烟，不算声学回环）。
- `check_wake.py` 现会对每段真实回录**同时运行 KWS 与 ASR**，报告唤醒命中、完整转写及禁止指令词命中；回录目录为空或总时长不足时不会通过。
- 负例文件按真实音频时长求和，少于 1800 秒或空目录不会通过；误唤醒次数本身按设计只报告、不设硬阈值。
- 已用直接合成的固定回复“收到”验证双管线可运行：KWS 0 次、ASR 转写“收到。”、禁止词 0 次；这不是扬声器→空气→麦克风的声学回环，故**不能替代真实播放自触发门槛**。

### 3.5 延迟与资源（CPU，官方中文样例，5 次）

| 指标 | 结果 |
| --- | --- |
| KWS 初始化 | 0.890 s |
| VAD 初始化 | 0.007 s |
| ASR 初始化 | 1.340 s |
| TTS 初始化 | 1.747 s |
| ASR 首次 / 热启动中位数 | 0.176 s / 0.171 s |
| TTS 完整同步合成首次 / 热启动中位数 | 3.418 s / 3.460 s |
| 进程峰值工作集 | 797.5 MB |
| VAD 语音后回到静音 | 是 |
| GPU provider | 未使用（全部显式 `cpu`） |

上表 TTS 数值是**整句完整生成耗时，不是首次出声时间**。真人运行 `loop.py` 时，会在 `loop-session.log` 写入从合成开始到输出流提交首帧并叠加 PortAudio 延迟的 `tts_first_output_estimate`；实际听到首声仍需用户复现并确认。基准期间整机 `nvidia-smi` 显存占用约 1549/8188 MiB；WDDM 模式未提供逐进程显存数字，进程列表未出现该 Python 基准进程。完整机器可读结果在 `voice-benchmark.json`。

## 4. 麦克风诊断

- Windows 麦克风隐私权限 HKCU/HKLM 与“桌面应用”两级均为 `Allow`。
- 插入耳机后 Windows 默认输入变为 HyperX，因此输入设备改为**有序优先列表**（`HyperX, Realtek`，可用 `SMART_HOME_INPUT_DEVICE` 覆盖），避免写死设备名。
- 端点注册表实测：HyperX 耳机麦克风 `ACTIVE`、音量 84/100；板载麦克风阵列 `ACTIVE`、音量 76/100。软件侧没有静音或零音量。
- 但两路麦克风在 6 秒录音窗口内都只有噪声底（HyperX 约 −91 dBFS、板载约 −97 dBFS），**峰值仅 −64 / −84 dBFS，没有任何语音能量**；MME、DirectSound、WDM-KS 三种接口和两个通道结果一致。
- 结论：现象是“录制期间没有声音进入系统”，而不是采样率或设备选择错误。可能原因是耳机物理静音键、麦克风未插到底，或录制时未实际发声。需要用 `--check-level` 在正式录音前确认。
- 正式录制入口：`record_cases.py --check-level`（静音会直接退出并报警）、`diagnose_mic.py`（逐设备 dBFS 与可回放 WAV）、`inspect_endpoints.py`（只读端点状态）。

## 5. 门槛状态

| 门槛 | 当前 | 放行要求 |
| --- | --- | --- |
| ASR 真实录音 | **30/30 通过**（门槛 ≥27/30） | ✅ 已达标 |
| 录音质量 | 30 条 peak 中位 0.208，29 条 ≥0.1，1 条 0.095 | ✅ 合格 |
| 麦克风可用性 | 耳机麦克风 ACTIVE、音量 84/100，实测可录 | ✅ 已确认 |
| TTS 人工试听 | 0/20 已评分；20/20 已生成 | 待用户：20 条逐条试听并记录，清晰且关键读音正确 ≥18/20 |
| 两个唤醒词真人测试 | 各 0/20 | 待用户：各 ≥18/20，最终选定一个 |
| 30 分钟负例 | 未录制 | 待用户：录满 ≥1800 秒，误唤醒次数记录并报告 |
| 播放自触发声学回环 | 未录制 | 待用户：指令文字/触发次数必须为 0 |
| 20 秒连续会话真人操作 | 脚本与 3 秒流已验证，播放后计时与播放抑制均有回归测试 | 待用户：实际唤醒、连续说话、超时、退出均复现 |

## 6. 用户执行入口

```powershell
# 0) 查看还有哪些语料没录
.\.venv\Scripts\python.exe tools/voice-check/recording_status.py

# 1) 录 30 条 ASR（--check-level 会先测电平，静音直接报警退出）
.\.venv\Scripts\python.exe tools/voice-check/record_cases.py --cases tools/voice-check/cases/asr-30.tsv --seconds 4 --check-level

# 2) 跑 ASR 门槛
.\.venv\Scripts\python.exe tools/voice-check/check_asr.py --cases tools/voice-check/cases/asr-30.tsv --out docs/superpowers/reports/artifacts/asr-results.json

# 2b) 核查录音电平与时长
.\.venv\Scripts\python.exe tools/voice-check/check_recording_quality.py

# 3) 试听并逐条评分 TTS
.\.venv\Scripts\python.exe tools/voice-check/listen_tts.py

# 4) 录两个唤醒词各 20 次
.\.venv\Scripts\python.exe tools/voice-check/record_cases.py --phrases tools/voice-check/cases/wake-xiaowu-20.txt --out-dir tools/voice-check/cases/audio/wake/xiaowu-xiaowu --seconds 3
.\.venv\Scripts\python.exe tools/voice-check/record_cases.py --phrases tools/voice-check/cases/wake-nihao-20.txt --out-dir tools/voice-check/cases/audio/wake/nihao-xiaowu --seconds 3

# 5) 录制 30 分钟负例（本地分成 6 个 5 分钟 WAV；--yes 跳过确认）
.\.venv\Scripts\python.exe tools/voice-check/capture_negative.py --yes

# 6) 播放固定回复并用物理麦克风做声学回录（会发出声音）
.\.venv\Scripts\python.exe tools/voice-check/capture_self_trigger.py --count 3

# 7) 检查真人唤醒、负例时长/误唤醒、回录 KWS 与 ASR 禁止词
.\.venv\Scripts\python.exe tools/voice-check/check_wake.py --positives 20 --negatives-dir tools/voice-check/cases/noise-30min --self-trigger-out tools/voice-check/cases/self-trigger --out docs/superpowers/reports/artifacts/wake-results.json

# 8) 启动真实连续语音环（事件写入本地 loop-session.log）
.\.venv\Scripts\python.exe apps/voice-service/src/loop.py
```

**ASR 结果（2026-09-12 实测）：30/30 通过**，门槛 27/30。

- 单条识别耗时 0.11–0.22 秒；全部为 16 kHz 单声道 4 秒。
- 录音电平：peak 中位 0.208、最大 0.709、最小 0.095。
- 用例 `asr-06` 最初因“关掉”被写成只接受“关闭”而误判，已改为接受 `关闭|关掉` 两种同义说法后命中；这属于用例写法问题，不是识别错误。

## 7. 阶段结论

**仍不放行，但最大的一项门槛已经通过。**

- 已通过：真实中文语音 ASR **30/30**（门槛 27/30），录音电平合格，耳机麦克风确认可用。
- 待用户完成：TTS 20 条试听评分、两个唤醒词各 20 次、30 分钟负例、声学回环、连续会话三轮。
- 已完成的自动验证：四模型 CPU 初始化与推理（内存约 0.8 GiB）、ASR/TTS/KWS/VAD 管线、设备优先选择、连续环骨架与 27 项单元测试。

三项待办中最需要时间的是 30 分钟负例；唤醒词测试要在安静环境下做，且两个候选都要录满 20 次才能比较。
