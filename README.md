# Smart Home Voice Agent

一个运行在 Windows 上的智能家庭语音 Agent：本地完成唤醒、VAD 与语音识别，使用 DeepSeek 进行受限工具调用，通过 Home Assistant 控制虚拟设备，并以语音如实反馈执行结果。

> 当前状态：语音 Agent、Home Assistant 虚拟设备闭环和多设备场景已经实现并通过自动化与真实栈验收；Unity 展示层以可安装 payload 形式保存在仓库中。本地视觉 VLM 尚未接入。

## 已实现能力

- 本地唤醒词「小屋小屋」「你好小屋」，唤醒后连续对话，空闲 20 秒退出。
- SenseVoiceSmall ONNX 本地 ASR；语音音频不上传云端。
- Edge neural TTS 播报；需要网络，失败时不会静默替换或谎报成功。
- DeepSeek OpenAI 兼容工具调用；设备和场景工具从 home-service catalog 自动派生。
- Home Assistant + MQTT 虚拟灯、空调、插座和温度传感器闭环。
- 写操作只有观察到真实目标状态后才报告 confirmed；离线、超时和部分失败均如实反馈。
- 场景：「我出门了」「我回来了」「我要睡觉了」。
- 空调舒适温度和调节步长来自本地配置，模型不能自行发明温度。
- Unity 2022.3 状态展示脚本：房间、设备、人物位置与播报高亮均由 home-service 状态驱动。

## 快速启动

模型默认存放在仓库外的 `D:\smart-home-models`，密钥和 Home Assistant 凭据存放在 Git 忽略的 `runtime/`。

```powershell
cd E:\smart-home

# 检查配置与运行环境
.\tools\voice-check\start_agent.ps1 -CheckOnly

# 打字模式：验证 Agent 与真实设备控制，不占用麦克风
.\tools\voice-check\start_agent.ps1 -Text

# 完整语音模式
.\tools\voice-check\start_agent.ps1
```

单独运行基础服务和测试的方法见：

- [Voice Service](apps/voice-service/README.md)
- [Home Service](apps/home-service/README.md)
- [Unity House payload](apps/unity-house-payload/README.md)

## 架构

```text
麦克风
  → 本地 KWS / VAD / SenseVoice ASR
  → DeepSeek 文本 Agent（受限工具）
  → home-service（127.0.0.1）
  → Home Assistant / MQTT 虚拟设备
  → Edge TTS + Unity 状态展示
```

home-service 是权威执行层。模型只能调用本地暴露的闭集工具，不能直接访问 Home Assistant、文件路径或任意网络接口。

## 验证记录

- [第一版完整设计与验收标准](docs/superpowers/specs/2026-09-12-smart-home-voice-agent-design.md)
- [语音 Agent 接入设计](docs/superpowers/specs/2026-09-13-voice-agent-integration-design.md)
- [Home Assistant 闭环验收报告](docs/superpowers/reports/2026-09-13-ha-closed-loop-report.md)
- [当前项目状态与下一步](docs/superpowers/notes/2026-09-13-project-state-and-next-steps.md)

## 隐私与仓库边界

- 原始音频默认不持久保存；云端只接收转写文本和完成任务所需的上下文。
- API 密钥、HA token、模型权重、音频、日志、数据库和运行时配置不进入 Git。
- Home Assistant 与 home-service 仅绑定本机 loopback；MQTT 不发布到宿主机端口。
- 本仓库尚未指定项目代码许可证；对外分发前还需完成第三方模型、唤醒词资源和素材的许可证核验。

仓库地址：<https://github.com/1493002189gugecom-bit/smart-home-voice-agent>
