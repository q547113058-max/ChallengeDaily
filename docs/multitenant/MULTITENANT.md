# ChallengeDaily 多租户部署与使用

## 架构

- **每租户独立数据目录**：`/opt/challengedaily/data/tenants/<tenant_id>/`
  - `synced.db` —— 采集数据（独立 SQLite，物理隔离）
  - `client_state.json` —— 前端状态
- **token → 租户映射**：注册表 `data/tenants.json`，每个租户一个专属 API Token
- **管理员 token**：`data/.admin_token`，用于管理所有租户
- **向后兼容**：首次升级时，旧的 `.api_token` + `synced.db` 自动迁移为 `default` 租户，原客户端/同步代理无需改动即可继续工作

## 管理员操作

### 1. 获取管理员 token
```bash
cat /opt/challengedaily/data/.admin_token
```
（服务首次启动自动生成）

### 2. 打开管理后台
浏览器访问 `http://193.112.246.85/admin`，输入管理员 token。

后台功能：列出租户、创建租户、停用/启用、重置 token、删除租户。
所有操作也可直接调 API（请求头带 `X-API-Token: <管理员token>`）：

| 操作 | 方法 | 路径 | body |
|---|---|---|---|
| 列表 | GET | `/api/admin/tenants` | - |
| 创建 | POST | `/api/admin/tenants` | `{"tenant_id":"acme","name":"Acme公司"}` |
| 停用 | POST | `/api/admin/tenants/disable` | `{"tenant_id":"acme"}` |
| 启用 | POST | `/api/admin/tenants/enable` | `{"tenant_id":"acme"}` |
| 重置 token | POST | `/api/admin/tenants/rotate-token` | `{"tenant_id":"acme"}` |
| 删除 | POST | `/api/admin/tenants/delete` | `{"tenant_id":"acme"}` |

创建成功会返回该租户的专属 token，**妥善保存并交给对应租户**。

## 租户配置

### Windows 同步代理
编辑 `deploy/sync_agent.json`，把 `token` 改为该租户的专属 token：
```json
{
  "server": "http://193.112.246.85",
  "token": "<该租户专属 token>",
  "db": "D:\\project\\daily\\ChallengeDaily\\data\\xiaohei.db",
  "interval": 60
}
```
重启同步任务：
```powershell
Stop-ScheduledTask -TaskName ChallengeDailySync
Start-ScheduledTask -TaskName ChallengeDailySync
```

### 客户端（桌面版）
客户端的 token 通过 `X-API-Token` 传给云端。多租户下需要让客户端使用该租户 token：
- 桌面版：`%APPDATA%\challenge-daily\backend-config.json` 中 `token` 字段改为该租户 token
- 或浏览器外壳：访问 `http://193.112.246.85/?token=<该租户token>`，shim 会注入对应 token

## 客户端租户标识
桌面客户端侧栏顶部会显示当前租户名称（数据来自 `/api/tenant/me`）。鼠标悬停可看租户 ID、
token 提示、创建时间。旧版服务端无此接口时该标识自动隐藏，不影响使用。

租户自己可查询身份（普通 token 即可，返回信息已脱敏，不含完整 token）：
```bash
curl -H "X-API-Token: <租户token>" http://193.112.246.85/api/tenant/me
# {"tenant_id":"acme","name":"Acme","token_hint":"1288f4…14f5","role":"tenant",...}
```

## 数据隔离验证
```bash
# 用租户 A 的 token 查
curl -H "X-API-Token: <tokenA>" http://193.112.246.85/api/activities
# 用租户 B 的 token 查（只会返回 B 自己的数据）
curl -H "X-API-Token: <tokenB>" http://193.112.246.85/api/activities
```

## 完善项说明
- **token 唯一**：创建/重置 token 时自动校验，一个 token 只能属于一个租户
- **删除即清理**：后台删除租户会同时删除其数据目录（`tenants/<id>/`），不留垃圾
- **数据概况**：管理后台列表显示每租户的活动数与 DB 大小
- **脱敏**：`/api/tenant/me` 与租户列表均不返回完整 token，仅显示 token 提示

## 升级部署
1. 备份：`cp -a /opt/challengedaily /opt/challengedaily.bak-<date>`
2. 上传新文件：`server.py`、`data_api.py`、`tenant_store.py`
3. `python3 -m py_compile` 校验
4. `systemctl restart challengedaily.service`
5. 首次启动自动迁移旧数据为 `default` 租户并生成 `.admin_token`
6. 访问 `/admin` 验证
