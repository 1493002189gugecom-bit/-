# Unity 智能家庭语音 Agent — 实现计划

日期：2026-09-12（修订版 v2）
状态：待用户审阅。本计划是执行清单，不代表已开始实施。
对应设计：`docs/superpowers/specs/2026-09-12-smart-home-voice-agent-design.md`

## 修订说明（相对 v1）

v1 存在四个问题，本版逐条修正：

1. **验收循环依赖**：v1 在阶段 A（只有离线脚本）就要求验收“进入对话、播报自触发、设备误操作”，但对话状态机与设备链路尚未实现；阶段 C 又要求自然语言端到端找人通知，而 Agent 在阶段 D。本版把实时语音验证限定为“固定回复、不接家居状态”，设备误操作验收移到 B/C，自然语言端到端验收移到 D。
2. **缺少可执行细节**：v1 只有目录级描述。本版为阶段 A 写出文件清单、依赖锁定、逐条运行命令与证据格式。
3. **计划引用的路径被 Git 忽略**：实测 `tools/voice-check/`、`docs/superpowers/notes/`、`docs/superpowers/reports/` 全部被根目录允许列表忽略。本版加入精确放行步骤与验证命令。
4. **Unity 版本处理不当**：v1 说“不兼容就退回 2022.3 LTS”。跨大版本降级 Unity 工程有风险，本版改为先做兼容性验证再固定版本，禁止正式工程原地降级。

## 0. 执行原则

- 每个任务必须有“运行什么命令、看到什么算通过”；未验证不得声明完成。
- 前一阶段门槛未通过，不进入下一阶段。
- 失败如实记录到报告，不删用例、不降低门槛、不用演示代替测试。
- 密钥、模型权重、日志、录制的音视频不进入 Git。
- 涉及安装依赖与下载模型的任务，执行前需用户确认当前阶段。

## 1. 现状（只读检查，2026-09-12）

| 项目 | 结果 |
| --- | --- |
| 仓库 | `main` 跟踪 `origin/main`；`dd03a75` 设计、`1ac0619` 计划 v1；工作树干净 |
| 默认 Python | 3.13.2（`E:\py\python.exe`），已有 numpy、onnxruntime、sounddevice、funasr、torch、opencv 等 |
| 备用 Python | 3.11.9（`C:\Users\1\AppData\Local\Programs\Python\Python311\python.exe`），仅有 pip 24.0 |
| 音频 | PortAudio V19.7.0 可用；默认输入为「麦克风阵列（网易虚拟音频设备）」，默认输出为 Realtek 扬声器；Realtek 物理麦克风可选 |
| Unity | `2022.3.47f1c1` 与 `6000.0.23f1c1` 均在 `D:\unity\edition`，两者都有 `windowsstandalonesupport` |
| 其他 | FFmpeg 8.0.1、.NET SDK 9.0.305 已装；空闲内存约 5.4 GiB，空闲显存约 6.4 GiB |

尚未安装或运行任何候选模型，识别率、延迟、显存占用均未实测。

## 2. 阶段划分与依赖

| 阶段 | 目标 | 依赖 | 关键产物 |
| --- | --- | --- | --- |
| A | 本地语音验证（离线模型＋最小实时语音环） | 无 | 语音验证报告＋实测数据 |
| B | 家庭状态与受限工具服务（纯文字） | A 通过 | 可独立测试的本地服务＋测试报告 |
| C | 最小 Unity 小屋（测试面板驱动） | B 通过 | 可拖动人物、设备随指令变化 |
| D | 云端 Agent 与人物检测（自然语言端到端） | C 通过 | 完整语音—决策—执行链路 |
| E | 并行与故障验收 | D 通过 | 验收报告 |

**各阶段验收边界（避免提前验收未实现的功能）**

| 能力 | 最早可验收阶段 |
| --- | --- |
| 离线识别、离线合成、唤醒正负例 | A |
| 实时环路（固定回复、无家居状态） | A |
| 自触发防护（声学回环离线判定） | A |
| 设备误操作、离线设备、版本冲突 | B |
| 场景 1/3/4（经测试面板或文字指令） | C |
| 场景 2/5/6/8/9/10（自然语言端到端） | D |

## 3. 路径放行（先决任务，必须在阶段 A 编码前完成）

当前 `.gitignore` 采用根目录允许列表，计划所需目录会被忽略。实测证据：

```text
.gitignore:3:/*          tools/voice-check/check_audio.py
.gitignore:9:/docs/superpowers/*   docs/superpowers/notes/model-review.md
.gitignore:9:/docs/superpowers/*   docs/superpowers/reports/voice-report.md
```

### P1. 修改 `.gitignore`

在现有允许列表段落之后、敏感规则之前追加（敏感规则保持在后，确保仍然生效）：

```gitignore
!/docs/superpowers/notes/
!/docs/superpowers/reports/

# Project roots added for implementation (keep this list minimal and explicit).
!/tools/
/tools/*
!/tools/voice-check/

!/apps/
/apps/*
!/apps/voice-service/
/apps/voice-service/*
!/apps/voice-service/src/
!/apps/voice-service/requirements.lock.txt

!/apps/home-service/
/apps/home-service/*
!/apps/home-service/src/
!/apps/home-service/tests/
!/apps/home-service/requirements.lock.txt
```

注意：`/apps/voice-service/*` 这类规则会忽略目录内所有文件，因此需要在其后**再单独放行** `requirements.lock.txt`。

### P2. 验证命令与预期结果（用退出码判断）

`git check-ignore` 的退出码：`0` = 被忽略，`1` = 未被忽略。**不要用输出文本判断**，未忽略时它也会打印匹配到的否定规则（以 `!` 开头），容易看反。

```powershell
$expectIgnored = @('apps/voice-service/__pycache__/x.pyc','apps/voice-service/config.env','.env','models/x.onnx','recordings/a.wav')
foreach ($p in $expectIgnored) { git check-ignore -q -- $p; if ($LASTEXITCODE -eq 0) { "OK ignored: $p" } else { "FAIL: $p" } }

$expectAllowed = @('apps/voice-service/requirements.lock.txt','apps/voice-service/src/loop.py','apps/home-service/tests/test_state.py','tools/voice-check/cases/asr-30.tsv','docs/superpowers/notes/n.md','docs/superpowers/reports/artifacts/r.json')
foreach ($p in $expectAllowed) { git check-ignore -q -- $p; if ($LASTEXITCODE -eq 1) { "OK allowed: $p" } else { "FAIL: $p" } }
```

**通过门槛**：全部输出 `OK`；随后 `git add -A -- apps tools docs/superpowers` 后，`git diff --cached --name-only` 中不出现 `__pycache__`、`config.env`、`.env`、模型或音频文件。

### P3. 生成计划所需目录

```powershell
New-Item -ItemType Directory -Force -Path 'tools/voice-check/cases','apps/voice-service/src','apps/home-service/src','apps/home-service/tests','docs/superpowers/notes','docs/superpowers/reports/artifacts' | Out-Null
```

`docs/superpowers/reports/artifacts/` 已随本计划提交一个说明文件，保证目录存在于仓库中。

---

## 阶段 A：本地语音验证

阶段 A 只回答一个问题：**这台电脑上，本地唤醒、识别、合成能不能达到设计门槛。** 不接家居状态、不接云端、不做自然语言决策。

### A1. 独立环境

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
```

**通过门槛**：`.\.venv\Scripts\python.exe -V` 输出 `Python 3.11.9`；`.venv/` 未被 Git 跟踪。

### A2. 依赖安装与锁定

安装到 `.venv`，不触碰全局 3.13：

```powershell
.\.venv\Scripts\python.exe -m pip install sherpa-onnx sounddevice soundfile numpy
.\.venv\Scripts\python.exe -m pip freeze > apps/voice-service/requirements.lock.txt
```

`sherpa-onnx` 同时提供 KWS、VAD、ASR、TTS，首轮不需要 PyTorch/CUDA 依赖。

**通过门槛**：`pip check` 无冲突；`.\.venv\Scripts\python.exe -c "import sherpa_onnx, sounddevice, soundfile"` 无报错；锁定文件已生成。

### A3. 模型核验与下载（先核验，再下载）

| 用途 | 候选 | 默认唤醒词 |
| --- | --- | --- |
| 唤醒 | sherpa-onnx KWS zipformer 中文 3.3M | 待定，见 A6 |
| 端点检测 | Silero VAD | — |
| 识别 | SenseVoiceSmall int8 | — |
| 合成 | Kokoro 中英 v1.1（int8 优先） | — |

核验清单（每项都要有结论）：
1. 下载地址可访问，文件大小与官方文档一致。
2. 许可证名称、是否允许预期用途、是否要求署名。
3. Windows + Python 3.11 + sherpa-onnx 所需 API 存在（KWS 的 `text2token` 可用）。

核验结论写入 `docs/superpowers/notes/2026-09-12-model-review.md`，含来源链接与核验日期。模型文件放在 `models/`（已忽略）。

**通过门槛**：四个模型的地址、大小、许可证均有明确结论；许可证不清晰的不下载，并在报告中说明替代方案。

### A4. 离线识别验证（门槛项）

脚本：`tools/voice-check/check_asr.py`

- 输入：`tools/voice-check/cases/asr-30.tsv`（制表符分隔：`id`、`wav路径`、`期望关键信息`）。
- 行为：逐个 wav 调用 sherpa-onnx 识别，输出 `id`、实际转写、期望、关键信息是否命中。
- 输出：`docs/superpowers/reports/artifacts/asr-results.json` 与控制台表格。

用例至少 30 条，必须覆盖：否定（“不要开灯”）、人名（“叫爸爸吃饭”）、房间（“客厅”“卧室”）、数字（“二十六度”）、模糊意图（“有点热”）。

命令：

```powershell
.\.venv\Scripts\python.exe tools/voice-check/check_asr.py --cases tools/voice-check/cases/asr-30.tsv --out docs/superpowers/reports/artifacts/asr-results.json
```

**通过门槛**：关键信息命中 ≥ 27/30。未达标则先排查麦克风与设备、再换候选模型，仍不达标如实记录。

### A5. 离线合成验证（门槛项）

脚本：`tools/voice-check/check_tts.py`

- 输入：`tools/voice-check/cases/tts-20.tsv`。
- 行为：逐条合成到 `docs/superpowers/reports/artifacts/tts/`。
- 人工试听：确认人名、数字、多音字读音与可理解性，逐条记录通过/不通过及原因。

**通过门槛**：20 条中可理解且关键字段读音正确 ≥ 18 条；不通过项列出具体问题字词。

### A6. 最小实时语音环（固定回复）

脚本：`apps/voice-service/src/loop.py`

显式选择设备（不修改系统默认）：

```powershell
.\.venv\Scripts\python.exe apps/voice-service/src/loop.py --input-device "麦克风阵列 (Realtek(R) Audio)" --output-device "扬声器 (Realtek(R) Audio)"
```

行为（**不接家居状态、不接云端**）：
1. 待机：持续 KWS 唤醒检测。
2. 唤醒：播放提示音，进入听取。
3. 听取：VAD 分句 → 识别 → 打印转写 → 播放**固定测试回复**（如“收到”）。
4. 播报期间：丢弃麦克风输入，不喂给 KWS 与识别。
5. 退出：20 秒无新语音回到待机。
6. 日志：每条事件写入 `docs/superpowers/reports/artifacts/loop-session.log`，含时间戳、状态、转写、耗时。

**通过门槛**：唤醒 → 说一句 → 听到固定回复 → 20 秒后回到待机，可连续复现 3 轮；终端可见状态与转写。

### A7. 唤醒与自触发验证

1. **正例**：连续 20 次主动唤醒，记录成功次数。
2. **负例**：连续播放 30 分钟无意图音频（对话、视频），记录误唤醒次数。
3. **自触发（声学回环）**：正常音量播放固定回复，同时用麦克风录制；对录制文件离线运行 KWS 与识别，检查是否出现唤醒或指令文字。

命令示例：

```powershell
.\.venv\Scripts\python.exe tools/voice-check/check_wake.py --positives 20 --negatives-dir tools/voice-check/cases/noise-30min --out docs/superpowers/reports/artifacts/wake-results.json
```

**通过门槛**：20 次唤醒中 ≥ 18 次成功；负例 30 分钟误唤醒记录并报告数量；自触发录制中不出现指令文字。

### A8. 唤醒词选择

对候选唤醒词（例如“小屋小屋”“你好小屋”）各录 20 次正例，比较成功次数与误触发。选择一个固定在 `apps/voice-service/src/config.py`，并把对比数据写入报告。**唤醒词不是身份认证**，报告中要写明这一点。

### A9. 延迟与资源

在实时环路中记录：冷启动首次识别耗时、热启动识别耗时、TTS 首次出声时间、进程峰值内存、GPU 是否被占用。

**通过门槛**：不崩溃、不耗尽内存；数据完整记录（不设秒数门槛，数值交由用户判断是否可接受）。

### A10. 阶段 A 产出与放行

报告：`docs/superpowers/reports/2026-09-12-phase-a-voice-report.md`

必须包含：环境与依赖版本、四个模型核验结论、30 条转写逐条结果、20 条 TTS 试听结果、唤醒正负例与自触发结果、延迟与资源表、失败案例、明确的“通过/不通过”结论。

**未通过时不得进入阶段 B。**

---

## 阶段 B：家庭状态与受限工具服务

纯文字驱动，不接语音，不接 Unity。

1. 数据模型：房间、人物、设备、视觉观察、会话、操作（字段见设计文档第 5 节）。
2. 权威状态服务：快照、增量、版本号、重连接口。
3. 六个工具：查询房间、查询人物位置、查询设备状态、设置灯光、设置空调、房间播报。
4. 服务端校验：对象存在、参数范围、房间归属、在线状态、前置版本、操作 ID 去重。
5. 单元测试：目标解析、房间去重、范围校验、版本冲突、操作去重。
6. 集成测试：模拟设备离线、超时、部分成功、重复请求、服务重启。
7. 接口默认绑定 `127.0.0.1`，不开放局域网。
8. 代码放在 `apps/home-service/`（需按第 3 节模式加入允许列表）。

**通过门槛**：`pytest` 全绿且离线、冲突、去重路径均有对应用例；用文字请求脚本可复现“开灯”“调空调”“按人去重播报”。

---

## 阶段 C：最小 Unity 小屋（测试面板驱动）

1. **版本决策（先验证再固定）**：用目标版本建最小验证工程，确认 JSON/WebSocket 与目标 .NET 可用后固定版本。若 Unity 6 与所需包冲突，则**用 2022.3 重建工程**，禁止把已建工程原地跨大版本降级。
2. 三个房间、灯、空调、房间播报点；人物用圆点＋名字。
3. 连接状态服务：初始快照、增量同步、断线重连。
4. 拖动人物提交位置；模拟室温由测试面板修改。
5. 语音区、摄像头区、执行记录区界面骨架（摄像头先留空）。
6. 用单个扬声器按房间播报并高亮目标房间。
7. 本阶段通过**测试面板按钮与文字输入**验证场景，不要求自然语言。

**通过门槛**：设计文档「必须通过的场景」第 1、3、4 条可复现（含移动人物后使用新位置）；Unity 1080p ≥ 30 FPS。

---

## 阶段 D：云端 Agent 与人物检测（自然语言端到端）

1. 用户选定云端 LLM 厂商并开通 API；设置预算告警与应用侧限额。
2. 密钥写入 `.env`（已忽略），不进入 Unity 包与日志。
3. Agent 编排：工具选择、超时、工具轮数上限、澄清状态、操作 ID 复用。
4. 接入语音会话状态机：静音、待机、听取、处理、播报、20 秒退出。
5. 接入本地人物检测与手动身份绑定；轨迹丢失解除绑定；视觉不覆盖模拟位置。
6. 验证「必须通过的场景」第 2、5、6、8、9、10 条。

**通过门槛**：全部十条场景可复现，含失败与澄清路径。

---

## 阶段 E：并行与故障验收

1. Unity ＋ ASR ＋ TTS ＋ 检测并行运行 ≥ 30 分钟，记录 RAM/VRAM 峰值、帧率、各段延迟。
2. 云端延迟单独测量并报告；由用户确认是否可接受。
3. 汇总报告：`docs/superpowers/reports/2026-09-12-acceptance-report.md`。
4. 未通过项如实列出。

---

## 4. 证据与命名约定

| 类型 | 位置 | 说明 |
| --- | --- | --- |
| 测试用例 | `tools/voice-check/cases/` | `.tsv`，含期望关键信息 |
| 机器可读结果 | `docs/superpowers/reports/artifacts/*.json` | 脚本输出 |
| 合成音频 | `docs/superpowers/reports/artifacts/tts/` | 试听用 |
| 会话日志 | `docs/superpowers/reports/artifacts/*.log` | 时间戳、状态、耗时 |
| 阶段报告 | `docs/superpowers/reports/YYYY-MM-DD-*.md` | 结论与失败案例 |
| 模型核验 | `docs/superpowers/notes/YYYY-MM-DD-*.md` | 地址、大小、许可证 |

音频、模型、日志不入库；报告与 JSON 结果入库。

## 5. 风险与应对

| 风险 | 应对 |
| --- | --- |
| 16 GiB 内存不足 | 模型分批加载；先只跑 ASR＋TTS，再逐步加入检测 |
| 默认麦克风是虚拟设备 | 脚本显式选择 Realtek 物理麦克风；不改系统默认 |
| 唤醒误触发偏高 | 调整 boosting score 与触发阈值；仍不达标则如实报告 |
| 模型许可证不清 | 停止下载，先核验许可证再决定 |
| Unity 版本冲突 | 先建最小验证工程；冲突则用 2022.3 重建，禁止原地降级 |
| 云端账单超预期 | 厂商预算告警＋应用侧请求数与轮数上限 |
| 实时环路回声 | 播报期间丢弃输入；用 A7 离线回环验证 |

## 6. 待用户确认

1. 是否按 A → B → C → D → E 顺序执行。
2. 阶段 A 是否允许安装 Python 3.11 虚拟环境依赖并下载四个模型。
3. Unity 先用 `6000.0.23f1c1` 做兼容性验证吗（冲突则用 2022.3 重建）。
4. 唤醒词候选：“小屋小屋”与“你好小屋”对比后固定。
5. 云端 LLM 厂商留到阶段 D 再定。
