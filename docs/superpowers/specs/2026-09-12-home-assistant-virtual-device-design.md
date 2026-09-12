# Home Assistant 虚拟设备底座设计

状态：用户已批准并要求自动执行。

## 1. 目标

将当前项目从 Unity 三维家庭模拟转向可连接真实设备的智能家居控制闭环。第一版没有真实硬件，先用 Home Assistant、MQTT 和虚拟设备模拟器建立与真实设备一致的接入边界。

第一轮实施只完成设备底座与文字控制，不接云端大模型；已实现的本地 ASR/TTS 保留，待设备闭环稳定后再接回。

## 2. 范围

本轮包含：

- Docker Compose 启动 Home Assistant、Mosquitto 和虚拟设备模拟器。
- 四类虚拟设备：可调光灯、空调、智能插座、温度传感器。
- MQTT Discovery 自动注册、状态回报、可用性与重连。
- 离线、响应延迟和执行失败模拟。
- `home-service` 通过 Home Assistant API 查询和控制实体。
- 保留现有受限工具的校验、操作 ID 去重和明确失败语义。
- 自动测试和文字驱动验收。

本轮不包含：

- Unity、3D 建模、空间坐标和房间几何。
- 摄像头人物检测、人物位置与跨房间找人播报。
- 云端 LLM、自然语言工具选择和连续对话接入。
- Zigbee、Thread、Matter USB 硬件或任何真实家居设备。

房间名称只作为设备分组和稳定标识保留，不表示空间模拟。

## 3. 架构

```text
文字验收脚本 / 后续语音 Agent
              |
              v
      home-service 安全控制网关
      - 稳定 ID 与实体映射
      - 类型/范围/在线校验
      - 操作 ID 去重
      - 状态回执判定
              |
              v
       Home Assistant REST API
       - 设备目录与权威状态
       - 控制面板与服务调用
              |
              v
          Mosquitto MQTT
              |
              v
        device-simulator
        - 命令消费
        - 状态回报
        - 离线/延迟/失败注入
```

Home Assistant 是设备状态的权威来源。`home-service` 不再长期维护第二套设备真相，只保留 Agent 不应绕过的安全与业务规则。

## 4. 组件边界

### 4.1 Home Assistant

- 提供本地网页控制面板。
- 保存实体状态并通过 REST API 暴露查询和服务调用。
- 通过 MQTT Discovery 接收虚拟设备定义。
- 使用长期访问令牌供 `home-service` 调用；令牌只放本地 `.env`，不进入 Git 或日志。

### 4.2 Mosquitto

- 只在 Compose 内部网络提供 MQTT。
- 使用非默认账号密码；凭据通过本地秘密文件或环境变量注入。
- 不把 1883 端口暴露到局域网。

### 4.3 虚拟设备模拟器

模拟器使用稳定设备 ID，启动后发布带 retain 的 Discovery 与初始状态，并监听 Home Assistant 命令。实现：

| 设备 | 能力 |
| --- | --- |
| `living_room_light` | 开关、0–100% 亮度 |
| `bedroom_ac` | 开关、制冷/送风、16–30℃目标温度 |
| `desk_plug` | 开关、模拟功率 |
| `indoor_temperature` | 可调模拟温度 |

每个可控设备都发布 availability。模拟器控制接口可切换离线、固定响应延迟和下一次命令失败；失败时不得发布目标状态。

### 4.4 home-service

新增 Home Assistant 网关接口，生产实现调用 REST API，测试使用替身。稳定设备 ID 映射到 Home Assistant `entity_id`，映射由版本化配置管理。

现有六个工具的外部契约尽量保持不变。空间相关查询暂保留兼容状态，但不得成为设备控制前提；播报与人物位置工具不在本轮扩展。

## 5. 控制与回执

以“把客厅灯调到 50%”为例：

1. 调用 `set_light`，携带稳定设备 ID、目标状态和操作 ID。
2. `home-service` 校验设备类型、范围、在线状态和重复操作。
3. 网关调用 Home Assistant 的 light 服务。
4. Home Assistant 通过 MQTT 发送命令。
5. 模拟器执行并发布实际状态。
6. 网关轮询有限时间，直到状态达到目标或超时。
7. 只有目标状态得到确认才返回成功。

查询结果来自 Home Assistant 当前实体状态，而不是本地缓存的预期值。

## 6. 错误语义

- 实体不存在或映射错误：`not_found`，不发送控制。
- 实体 unavailable：`offline`，不声称执行成功。
- 参数越界或设备类型不符：本地拒绝。
- Home Assistant 不可连接：`backend_unavailable`。
- 服务调用被拒绝：`backend_rejected`。
- 命令已发出但状态未达到目标：`confirmation_timeout`，结果保持不确定而非成功。
- 相同操作 ID 重试：返回首次存储结果，不重复下发。
- 模拟失败：保持原状态并生成可追踪失败记录。

错误日志不得包含访问令牌、MQTT 密码或完整认证头。

## 7. 持久化与安全

- Compose 配置和无秘密的默认配置进入仓库。
- Home Assistant 运行状态、数据库、令牌、MQTT 密码和模拟器运行状态不进入 Git。
- Home Assistant Web 端口默认只绑定 `127.0.0.1:8123`。
- MQTT 不映射宿主机端口；仅 Compose 内部服务可访问。
- 容器使用健康检查和自动重启策略，但测试必须能显式停止故障组件。

## 8. 测试与验收

自动测试必须覆盖：

- Discovery 载荷与四类实体契约。
- 灯光亮度和空调温度范围。
- 状态回执成功、离线、延迟、失败和确认超时。
- Home Assistant 不可连接与错误响应。
- 操作 ID 去重，保证同一操作只下发一次。
- 凭据不会出现在日志或被 Git 跟踪。
- 现有 `home-service` 与 `voice-service` 测试无回归。

集成验收必须满足：

1. `docker compose up` 后 Home Assistant、Mosquitto、模拟器健康。
2. Home Assistant 页面可见四类虚拟设备。
3. 页面控制与 MQTT 状态双向一致。
4. 容器重启后设备自动重新注册。
5. `home-service` 能完成查询、开关、亮度和温度控制。
6. 离线、失败和超时均明确失败，不能误报成功。
7. 设备误操作次数为 0。

## 9. 实施分段

1. Compose 与安全配置。
2. MQTT 虚拟设备模拟器。
3. Home Assistant 实体注册与页面验证。
4. `home-service` 网关及实体映射。
5. 文字驱动端到端验收。
6. 后续独立阶段再接 ASR/TTS 与云端 Agent。

## 10. 未来真实设备迁移

真实设备接入 Home Assistant 后，为其配置对应的稳定 ID 映射即可替换虚拟实体。Agent 和受限工具契约不因 Zigbee、Matter、Wi-Fi 或厂商集成而改变。虚拟设备继续保留用于回归测试、故障注入和没有硬件时的演示。
