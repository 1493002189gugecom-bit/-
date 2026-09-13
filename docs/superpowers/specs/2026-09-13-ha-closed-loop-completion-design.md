# Home Assistant 虚拟设备闭环完成设计

状态：用户已逐节批准；等待书面规格复核。

## 1. 目标与现状

本轮完成已启动但尚未闭合的 Home Assistant 虚拟设备底座，使四类虚拟设备能被 Home Assistant 发现，并能由 `home-service` 以可确认、可恢复、幂等且不误报成功的方式控制。

当前仓库已有已批准的总体设计、部分网关和测试草稿，但模拟器源码、完整 Compose 扩展、HA 控制服务和服务入口仍不完整；新增测试目前因缺少 `model` 与 `ha_service` 模块而无法收集。本设计只完成这条设备闭环，不接入云端 LLM，也不扩展 Unity 或空间模拟。

## 2. 已选方案

直接扩展现有 `D:/dac` Docker Compose，并复用其 Home Assistant。该环境全部服务于本项目，可按需要调整。新增 Mosquitto 与设备模拟器，MQTT 端口仅在容器网络开放。

未选择的方案：

- 仓库独立 Compose 再通过外部网络接入现有 HA：仓库更自包含，但跨 Compose 网络、启动顺序和凭据管理更复杂。
- 使用 Home Assistant Helper 模拟设备：演示更快，但不能验证 MQTT Discovery、availability、延迟、失败和重连语义。

## 3. 系统架构与边界

```text
Agent（后续）/ 文字验收
          |
          v
home-service 受限工具边界
- 参数、类型、范围、在线校验
- 持久化幂等状态机
- 状态确认与恢复对账
          |
          v
Home Assistant REST API
- 设备目录与对外权威状态
          |
          v
Mosquitto（仅容器网络）
          |
          v
device-simulator
- MQTT Discovery
- 模拟设备状态
- availability、延迟、失败注入
- 原子持久化与重启恢复
```

Home Assistant 是控制方读取设备状态的权威来源。模拟器拥有模拟设备的实际执行状态。`home-service` 不维护第二套长期设备真相，只持久化操作状态、安全规则和用于恢复的目标快照。

安全边界：

- `home-service` 独占 Home Assistant 长期访问令牌。
- 模拟器独占 MQTT 凭据。
- Agent 只能调用 `home-service` 暴露的受限工具，不能直接访问 HA 或 MQTT。
- 令牌和密码只放本地环境或秘密文件，不进入 Git、API 响应或日志。
- HA HTTP 客户端禁用系统代理和自动重定向，避免认证头被转发。
- MQTT 不向宿主机或局域网发布 1883 端口。

## 4. 组件设计

### 4.1 设备模拟器

模拟器拆成可独立测试的单一职责单元：

1. 纯状态模型：实现灯、空调、插座和温度传感器的合法状态转换，不执行 I/O。
2. MQTT 契约：生成 Discovery、状态、命令、availability 和故障事件主题与载荷。
3. 运行器：连接、订阅、重连、命令调度和状态发布。
4. 故障控制：切换离线、固定响应延迟和“下一条命令失败”。该接口只允许本地管理员使用，不暴露为 Agent 工具。
5. 持久化：采用同目录临时文件加原子替换；文件缺失时使用默认值，损坏或非法状态时明确失败而不是静默接受。

设备使用稳定 ID 和 `shv_` 实体前缀：

- `living_room_light`：开关、0–100% 亮度。
- `bedroom_ac`：`off`、`cool`、`fan_only`，目标温度 16–30℃。
- `desk_plug`：开关及模拟功率。
- `indoor_temperature`：模拟温度读数。

启动或重连后，模拟器重发带 retain 的 Discovery、availability 和当前状态；命令主题永不 retain。

### 4.2 Home Assistant 与 Mosquitto

现有 `D:/dac` Compose 是唯一运行底座。本仓库提供可审查的 Compose 扩展和无秘密默认配置，再以明确命令与现有 Compose 合并。Home Assistant 加载 MQTT 集成；Mosquitto 使用非默认凭据，只加入 Compose 内部网络；模拟器依赖 broker 健康后启动并采用自动重启策略。

所有新增实体均带稳定 `unique_id`、设备信息和 `shv_` 前缀。重启或重复发布 Discovery 不得生成重复实体。

### 4.3 home-service

`home-service` 保留 memory 后端用于现有回归测试，并新增显式 HA 后端。HA 后端由以下单元组成：

- HTTP gateway：只负责鉴权请求、响应解析和安全错误映射。
- 实体目录：把稳定设备 ID 映射到 HA `entity_id`、类型和房间元数据。
- 控制服务：执行本地校验、幂等状态机、服务调用和有限时间确认。
- 操作存储：以 SQLite 原子保存 operation ID、规范化参数、状态、时间和最终结果。
- 服务入口：通过明确环境变量选择 `memory` 或 `ha`；HA 配置不完整时拒绝启动，不自动回退到 memory。

空间查询和测试突变接口在 HA 模式下不得参与设备控制；不支持的接口返回明确错误。

## 5. 幂等状态机与确认语义

每个写操作采用以下持久化状态机：

```text
accepted -> submitted -> confirmed
    |           |
    |           +-------> unconfirmed
    +-------------------> rejected
```

- `accepted`：operation ID 与规范化参数已原子占位，尚未证明已提交。
- `submitted`：HA 服务请求已被发送；HTTP 成功只证明请求被接受，不证明设备已执行。
- `confirmed`：从 HA 观察到的当前状态达到目标。
- `unconfirmed`：请求可能已提交，但在确认窗口内没有观察到目标状态，或提交结果因连接中断而不确定。
- `rejected`：在可证明未提交时被本地校验或后端明确拒绝。

处理规则：

1. 首次请求先规范化参数，并以 operation ID 原子创建 `accepted` 记录。
2. 相同 ID 和相同规范化参数返回已有状态或最终结果，不重复下发。
3. 相同 ID 和不同参数返回 `operation_id_conflict`。
4. 调用 HA 前读取实体，检查存在性、类型、在线状态和是否已经达到目标。
5. 无需变更时直接记录 `confirmed`，并返回“已经处于目标状态”的诚实措辞。
6. 需要变更时进入 `submitted`，调用 HA 服务并限时轮询实体状态。
7. 只有观察到目标状态才进入 `confirmed`。超时进入 `unconfirmed`，对外错误为 `confirmation_timeout`，不得声称失败或成功。

### 5.1 崩溃恢复与显式重试

启动时扫描未终结操作：

- `accepted`：读取当前设备状态。若已达目标则记为 `confirmed`；否则可以安全下发一次，并按正常确认流程继续。
- `submitted`：禁止盲目重发。先对账；已达目标则记为 `confirmed`，否则保持 `unconfirmed`。
- `unconfirmed`：默认只对账，不自动重发。调用方必须使用新的 operation ID 发起显式重试；旧 ID 始终返回旧操作结果。

这一策略优先避免重复物理动作。它承认进程在网络调用临界区崩溃时无法仅凭本地记录区分“未送达”与“已送达”。

## 6. 数据流

以“将客厅灯调到 50%”为例：

1. 调用方发送稳定设备 ID、亮度和 operation ID。
2. 控制服务规范化参数并创建幂等记录。
3. 实体目录验证类型；控制服务验证亮度范围。
4. gateway 读取 HA 实体，拒绝不存在或 unavailable 的设备。
5. 若当前状态不同，控制服务把操作记为 `submitted` 并调用 HA light 服务。
6. HA 通过 MQTT 发出非 retain 命令。
7. 模拟器执行、原子保存状态并发布 retain 状态。
8. 控制服务轮询 HA，观察到开灯且亮度换算后达到 50%，记录 `confirmed`。
9. API 只根据该终态返回允许 Agent 复述的结果。

## 7. 错误与故障语义

| 情况 | API 错误/状态 | 是否下发 |
| --- | --- | --- |
| 参数、范围或类型非法 | `invalid_request` / `rejected` | 否 |
| 实体或映射不存在 | `not_found` / `rejected` | 否 |
| 实体 unavailable | `offline` / `rejected` | 否 |
| HA 连接失败且可证明未提交 | `backend_unavailable` / `rejected` | 否 |
| 提交阶段连接中断、结果未知 | `backend_unavailable` / `unconfirmed` | 可能已下发，禁止自动重试 |
| HA 在接受服务调用前明确拒绝 | `backend_rejected` / `rejected` | 否 |
| 已提交但未观察到目标 | `confirmation_timeout` / `unconfirmed` | 是 |
| ID 被不同参数复用 | `operation_id_conflict` | 否 |

模拟器的“下一条命令失败”保持原状态，并发布不含凭据的可追踪故障事件；延迟期间不提前发布目标状态；离线时 availability 为 offline 且不消费为成功。

## 8. 测试设计

### 8.1 单元测试

- 四类设备状态转换、非法载荷、数值类型与边界。
- Discovery、状态、命令和 availability 契约。
- 原子持久化、缺失文件与非法文件处理。
- 实体映射、亮度换算、空调模式和温度范围。
- `accepted/submitted/confirmed/unconfirmed/rejected` 的合法转移。
- 同 ID 同参数去重、不同参数冲突、无操作请求。
- `accepted` 与 `submitted` 的不同恢复策略。

### 8.2 伪后端集成测试

- 成功确认、实体离线、服务拒绝、连接失败、延迟和确认超时。
- 提交临界区连接中断不得误归为未执行。
- HA 模式不得自动回退 memory。
- 日志、异常和响应不得包含令牌、MQTT 密码或完整认证头。

### 8.3 真实环境验收

1. 合并现有 `D:/dac` Compose 与项目扩展后，HA、Mosquitto、模拟器健康。
2. HA 页面只出现一组稳定的四类虚拟设备。
3. 页面控制与 MQTT/HA 状态双向一致。
4. `home-service` 完成查询、灯光开关/亮度、空调模式/温度控制。
5. 模拟器与 broker 重启后自动重连、重发 Discovery 和恢复状态，不生成重复实体。
6. 逐项验证离线、下一条失败、延迟与确认超时，均不误报成功。
7. 制造未终结操作后重启 `home-service`，验证对账恢复且不盲目重发 submitted 操作。
8. 运行 simulator、home-service、voice-service 全套自动测试，无现有功能回归。

需要用户参与的节点仅有：创建或提供本机 Home Assistant 长期访问令牌，以及在 HA 页面确认实体和控制结果。秘密不会写入规格、Git 或聊天回显。

## 9. 完成标准

- 四类虚拟设备在现有 Home Assistant 中稳定可见并可控。
- `home-service` 的所有设备写入都经过持久化幂等状态机和实际状态确认。
- 崩溃恢复不盲目重发可能已经执行的命令。
- 离线、拒绝、失败、延迟和不确定结果都有明确且诚实的语义。
- MQTT 与 HA 凭据隔离且不泄露，MQTT 不暴露到局域网。
- 全套自动测试通过，真实环境验收结果被记录；任何未完成的人工作业明确标注为未验证。
