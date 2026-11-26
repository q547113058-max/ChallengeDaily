# ChallengeWorker 主控交接文档

> 目标：让 `auto` 节点作为**主控节点**，通过云端 hub 接管并控制其他 worker 节点。

---

## 一、架构

```
你（我）──下发命令──→ 云端 hub (/api/worker/*) ──→ 各 worker 节点
                            ↑
                     auto 节点也能作为主控，
                     通过同样的 API 控制其他节点
```

- **云端 hub**：`http://193.112.246.85`，任务队列 + 节点注册表
- **worker 节点**：跑 `ChallengeWorker-v102.exe` 面板的机器
- **主控台**：`worker_controller.py`，可在任意节点/本机运行，通过 API 控制所有节点
- 节点**主动长轮询**取任务，无需公网 IP、无需端口映射

---

## 二、当前节点

| 节点 ID | 角色 | 状态 |
|---|---|---|
| `auto` | 主控节点（已装主控台）| ONLINE |
| `LAPTOP-5KNUOU5D-2c7ba06cf290` | 被控节点 | 按需上线 |
| `v102-test` | 历史测试节点 | 可忽略 |

节点 ID 在面板上可改，建议给每台机器设置有辨识度的名字。

---

## 三、我已经做了什么

1. 写好主控台 `worker_controller.py`（7KB，纯标准库）
2. 上传到云端：`http://193.112.246.85/updates/worker_controller.py`
3. 安装到 `auto` 节点的 `D:\ChallengeDaily\worker_controller.py`
4. 验证：auto 上运行主控台能列出所有节点、下发任务、收到结果

---

## 四、auto 节点怎么当主控

### 方式 A：直接命令（推荐）

让 auto 执行（通过我下发，或在该机器本地运行）：

```bat
set WORKER_TOKEN=<控制token>
"D:\ChallengeDaily\.venv312\Scripts\python.exe" "D:\ChallengeDaily\worker_controller.py" list
```

### 方式 B：交互主控台

```bat
set WORKER_TOKEN=<控制token>
"D:\ChallengeDaily\.venv312\Scripts\python.exe" "D:\ChallengeDaily\worker_controller.py" shell
```

进入后：

```
controller> list                          列出所有节点
controller> run LAPTOP-xxx whoami         下发到指定节点
controller> run '*' echo hello            广播到所有在线节点
controller> broadcast dir C:\             广播并等待结果
controller> wait <task_id> 60             等待任务结果
controller> result <task_id>              查结果
controller> exit                          退出
```

### 方式 C：从我这边（主控端）

我直接用控制工具：
- `worker_controller.py list` — 看节点
- `worker_controller.py run <target> <cmd>` — 下发
- `worker_controller.py broadcast <cmd>` — 广播

---

## 五、主控台完整命令

| 命令 | 说明 |
|---|---|
| `list` | 列出所有节点（含在线状态、IP、心跳时间）|
| `run <target> <cmd>` | 向指定节点下发命令（`target` = 节点 ID 或 `*` 广播）|
| `broadcast <cmd>` | 广播给所有在线节点并等待结果 |
| `wait <task_id> [秒]` | 等待某任务完成并打印结果 |
| `result <task_id>` | 立即查询某任务结果（JSON）|
| `shell` | 进入交互模式 |

---

## 六、API 参考（自己写客户端时用）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/worker/list` | 列出节点 + 任务（公开，无需 token）|
| POST | `/api/worker/register` | `{worker_id}` 节点注册 |
| GET | `/api/worker/poll?worker_id=` | 长轮询取任务（节点调用）|
| POST | `/api/worker/result` | `{task_id, worker_id, result, ok}` 回传 |
| **POST** | **`/api/worker/task`** | **下发任务，需 `X-Worker-Token` 头** |
| GET | `/api/worker/result?task_id=` | 查结果（公开）|

下发任务示例：

```python
POST http://193.112.246.85/api/worker/task
Header: X-Worker-Token: <控制token>
Body:   {"cmd": "whoami", "target": "节点ID 或 *"}
返回:   {"status":"ok", "task_id":"..."}
```

---

## 七、常见操作示例

### 让某节点执行一条命令

```
controller> run LAPTOP-5KNUOU5D-2c7ba06cf290 whoami
```

### 广播重启所有节点的客户端

```
controller> broadcast "taskkill /F /IM ChallengeDaily.exe"
```

### 收集所有节点的磁盘信息

```
controller> broadcast "wmic diskdrive get size,model"
```

### 查一个长任务的结果

```
controller> wait <task_id> 300
```

---

## 八、注意事项

1. **面板必须常驻**：节点上的 `ChallengeWorker.exe` 关掉后就无法接收命令。点面板「开机自启」可持久在线。
2. **token 配置**：主控台用 `WORKER_TOKEN` 环境变量，或同目录 `sync_agent.json` 里的 token。没有 token 无法下发任务（只能 list/查结果）。
3. **任务超时**：默认单任务 300 秒。长任务用 `run` 的 timeout 参数或分批执行。
4. **结果编码**：远程终端中文可能显示乱码（GBK/UTF-8 差异），但命令执行本身正常。
5. **安全性**：节点会执行任意命令，只对接信任的机器。控制 token 不要外泄。

---

## 九、关键文件位置

| 文件 | 位置 |
|---|---|
| 主控台（auto 节点）| `D:\ChallengeDaily\worker_controller.py` |
| 主控台（云端备份）| `http://193.112.246.85/updates/worker_controller.py` |
| 主控台（本地源码）| `D:\project\daily\ChallengeDaily\tools\worker_controller.py` |
| 节点面板 | `D:\ChallengeWorker.exe` / 更新包 `ChallengeWorker-v102.exe` |
| 云端 hub 数据 | `/opt/challengedaily/data/worker_hub.json` |
| 控制 token | 服务器 `/opt/challengedaily/data/.api_token`（或环境变量）|

---

## 十、交接检查清单

- [x] 主控台写好并测试通过（list / run / 收结果）
- [x] 主控台上传到云端
- [x] 主控台安装到 auto 节点
- [x] 验证 auto 能列节点、下发任务、收结果
- [ ] 新节点上线后，用 `run <新节点ID> whoami` 验证接管
- [ ] auto 节点开启面板「开机自启」，保证长期在线
