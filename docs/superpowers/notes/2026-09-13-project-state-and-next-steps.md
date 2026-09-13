# 项目现状与下一步交接说明

日期：2026-09-13
状态：**项目已迁移到 `E:\smart-home` 并验证通过。**

## 为什么有这份说明

项目目录已从 `E:\智能家居` 改名为 `E:\smart-home`。DSH 的工作区因此改变，
重开 DSH 时请选 `E:\smart-home`。这份说明记录迁移结果、踩过的坑和下一步。

## 迁移结果（已完成）

**原因**：仓库路径含中文字符。实测 `cv2.imwrite` 在中文路径下**静默失败**；
ONNX Runtime 加载模型、CUDA/DirectML、ffmpeg 这类 C++ 工具链在非 ASCII 路径下也不可靠。

**目录联接（junction）不能解决**：已实测 `Path.resolve()` 与 `os.path.realpath()`
会把联接解析回中文真实路径，而本项目代码正是用 `Path(__file__).resolve()` 定位文件。

**最终怎么搬成的**：根目录改名始终被拒（见下），于是**逐个搬子项**；卡住的
`.git` 与 `runtime` 改用 **`Copy-Item` 复制**——源目录只是被持有句柄而
**不能删改，但可以读**。现在 `E:\smart-home` 是完整仓库：

| 校验 | 结果 |
|---|---|
| `git log` | 提交历史完整 |
| `git ls-files` | 143 个跟踪文件 |
| 全量测试 | **376 passed** |
| HA 四实体 | 灯/空调/插座/温度全部在线 |
| 设备工具验收 | **9/9 通过**（含离线不误操作） |
| `start_agent.ps1 -CheckOnly` | 正常 |

**残留（可删）**：`E:\智能家居` 只剩旧的 `.git` 与 `runtime`（都是过时副本，
`runtime` 已在新区重新生成）。关闭 DSH 后可删：
`cmd /c rmdir /s /q "E:\智能家居"`。迁移辅助脚本 `E:\smart-home-rename\` 也可删。

### 改名为什么这么麻烦

| 持有者 | 症状 | 关键证据 |
|---|---|---|
| **DSH Desktop** | 「另一个进程正在使用」 | 它有 8 个进程，**不是每个命令行都带工作区路径**，按命令行检测会漏 |
| **Docker Desktop** | 「**访问被拒绝**」 | 文件共享给目录加了显式 ACE（`S-1-4-881271916-17797080`），并在共享根持有句柄 |

- **子目录能改、根目录不能改** → 持有者锁的是**目录本身**，不是内容。
- **Restart Manager 两个都查不出**（实测「none reported」）。
- **Move 被拒 ≠ 不能搬**：`Copy-Item` 只要读权限，绕开了「不能删」的限制。

### 迁移中修掉的两个真实缺陷

1. **`$PSScriptRoot` 在 `param()` 默认值里是空的**（PowerShell 5.1）。原先写
   `[string]$RepoRoot = (Join-Path $PSScriptRoot '..\..')`，直接点斜杠调用没事，
   但嵌套 `powershell -File` 就崩。已改为在脚本主体里解析，`prepare_stack.ps1`
   与 `start_agent.ps1` 都已修。
2. **编辑会剥掉 `.ps1` 的 UTF-8 BOM**，导致 PowerShell 5.1 按 ANSI 读中文、
   字符串终止符错乱。已扫描全部 17 个脚本并为含非 ASCII 的补回 BOM。
   **今后改含中文的 `.ps1` 后要复查 BOM。**

**注意**：`.venv` 里 pip/pytest 的入口 exe 仍烘焙旧绝对路径。始终用本项目既有写法
`.\.venv\Scripts\python.exe -m <工具>`；只有需要 pip 本身时才重建 venv。

## 已完成并验证

| 能力 | 状态 |
|---|---|
| Home Assistant 虚拟设备闭环 | 4 个实体、稳定 id、已归入区域（客厅/卧室） |
| 幂等状态机 | `accepted → submitted → confirmed/unconfirmed/rejected`，崩溃恢复按设备对账 |
| 设备控制 | 从 `/catalog` **自动派生**工具，加设备只改配置不改代码 |
| 语音 Agent | DeepSeek 工具调用，唤醒词「小屋小屋」「你好小屋」 |
| 场景 | 我出门了 / 我回来了 / 我要睡觉了，**部分失败如实播报** |
| 本地舒适策略 | 温度全部来自配置，模型不能发明数字 |
| 语义退出 | `end_conversation` 工具，模型判断告别意图 |

验证记录：`docs/superpowers/reports/2026-09-13-ha-closed-loop-report.md`
（真实栈 14/14；全量自动化 376 项）

启动：`.\tools\voice-check\start_agent.ps1`（加 `-Text` 为打字模式）

## 已确认的设计原则（用户明确要求）

1. **人没有表达 → 不动，也不代替他决定。** 传感器只用于回答查询和确认执行结果，
   绝不作为动作的触发源。因此「条件自动触发」被明确否决。
2. **数据不撒谎**：部分失败说部分失败；超时说未确认；工具结果覆盖模型措辞。
3. **不擅自扩大范围**：人脸/声纹识别不在已批准设计内（§2 明确排除），要做得先改设计。

## 下一步：本地视觉（已定方案 C）

用户已决定：**不用云端多模态，用本地 VLM**。

| 项 | 决定 |
|---|---|
| 视觉后端 | 本地 VLM，Qwen2.5-VL-3B |
| 运行方式 | **Ollama**（自动用 CUDA；接口与 DeepSeek 同为 OpenAI 兼容，同一套 `image_url` 格式） |
| 摄像头 | 用户想用手机当摄像头，**USB 方案**绕开校园网（DroidCam/Iriun USB，或 USB 网络共享 + IP Webcam） |
| 接入点 | 新增 `look(camera, question)` 工具；DeepSeek 决定何时看，视觉后端可切换 |

**已实测的现状**：
- 显卡 RTX 4060 Laptop，8188 MiB，空闲约 6.8 GB；驱动 566.36
- `onnxruntime` 是 **CPU 版**，`torch` 是 **CPU 版**，**显卡目前完全没用上**
- 未安装 ollama / llama.cpp
- 项目 venv 无 `opencv`、无 `onnxruntime`；系统 Python 3.13 有 `cv2 4.13`（但 torch 是 CPU 版）
- 摄像头：仅内置 `Integrated Camera`（640×480）
- **DeepSeek 已支持看图**：`deepseek-chat` 与 `deepseek-flash` 都能正确识别图片
  （实测 3/5/8/0 四张全对）；`deepseek-v4-pro` 不支持。用户认为其视觉质量不够，故选本地。

**关键建议顺序**：
1. 装 Ollama，`ollama pull qwen2.5vl:3b`（约 3.2GB）
2. **先用一张真实手部照片验证 3B 模型能不能认手势**，再决定是否建整套
   （渲染数字能认 ≠ 真实手势能认：手掌纹理、光照、角度、手指交叠都更难）
3. 认得准再装 `opencv-python` + `onnxruntime-directml` 到项目 venv，写采集与 `look` 工具

**隐私**：加视觉后画面会离开本机（本地方案则不上传），这改变了原设计 §8
「云端只接收转写和任务必要状态」的隐私姿态，用户已知悉。

## 已知的坑（别重复踩）

| 坑 | 说明 |
|---|---|
| `cv2.imwrite` 中文路径 | 静默失败，用 `cv2.imencode` + 写字节（改名后应消失，但仍建议如此） |
| PowerShell 5.1 + 原生 stderr | `$ErrorActionPreference='Stop'` 会把 Docker 的进度输出当致命错误；用 `Invoke-Native` 包装并显式查退出码 |
| PowerShell 5.1 读 .ps1 | 无 BOM 的 UTF-8 会被当 ANSI，中文乱码；脚本里的中文要么加 BOM，要么全用 ASCII |
| HA 忽略 `object_id` | MQTT Discovery 的 entity_id 由实体名 slug 决定，且**加 `device` 块会把设备名拼进 id** |
| HA 实体区域 | `area_id` 在**实体**注册表上，可用工具设置；不要为了区域引入 `device` 块 |
| 查询参数名 | home-service 用 `device`/`room`，不是 `device_id` |
