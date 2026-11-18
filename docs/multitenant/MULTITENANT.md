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

## 数据隔离验证
```bash
# 用租户 A 的 token 查
curl -H "X-API-Token: <tokenA>" http://193.112.246.85/api/activities
# 用租户 B 的 token 查（只会返回 B 自己的数据）
curl -H "X-API-Token: <tokenB>" http://193.112.246.85/api/activities
```

## 升级部署
1. 备份：`cp -a /opt/challengedaily /opt/challengedaily.bak-<date>`
2. 上传新文件：`server.py`、`data_api.py`、`tenant_store.py`
3. `python3 -m py_compile` 校验
4. `systemctl restart challengedaily.service`
5. 首次启动自动迁移旧数据为 `default` 租户并生成 `.admin_token`
6. 访问 `/admin` 验证
