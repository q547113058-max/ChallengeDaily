# 云端深度画像实现（2026-11-25）

## 问题

客户端「深度画像」页的两个接口在云端是**返回空数据的硬编码占位**：

```python
"/api/deep-insight": (lambda q: ({"status":"ok","data_points":0,"frameworks":{},...}, None), True),
"/api/experience/profile": (lambda q: ({"ok":True,"profile":{...空...}}, None), True),
```

不是"没接云端"，而是云端当时为了不报 501 加的兜底空壳。

## 实现

在 `/opt/challengedaily/queries.py` 追加两个纯标准库函数，读租户 `synced.db` 真实活动数据：

- `deep_insight(q, target_date)`：
  - 计算 9 个学术框架指标（心流理论、刻意练习、布鲁姆分类、自我决定理论、超日节律、结构洞、最近发展区、习惯回路、心理资本）
  - 指标：flow_index、deliberate_ratio、cognitive_depth、rhythm_alignment、tool_diversity 等
  - 生成 summary.findings（真实统计结论）
- `experience_profile(q, days)`：
  - 按应用聚合 projects（含时长、最后使用时间）
  - 按分类聚合 skills（含等级、时长）
  - 协作工具识别、习惯推导

`/opt/challengedaily/server.py` 的 `DATA_ROUTES` 占位路由改为调用真实函数：
```python
"/api/deep-insight": (lambda q: _q("deep_insight")(q, (q.get("date") or [None])[0]), True),
"/api/experience/profile": (lambda q: _q("experience_profile")(q, (q.get("days") or ["90"])[0]), True),
```

## 关键修复

1. 函数内不能用路由传入的 `q`（那是 query dict，不是 DB 连接），改用 `data_api.connect()`（自动绑定当前请求线程的租户库）
2. `SELECT` 不要包含云端表没有的列（如 `ai_summary`），否则异常被吞掉返回空
3. 路由签名是 `fn(q)` 单参数，不能用三参数 lambda

## 验证

```
/api/deep-insight → status=ok, data_points=1327, 9 个框架有真实指标
/api/experience/profile?days=30 → projects=[DeepSeek Harness 2304min, chrome 1457min...], skills 有数据
```

## 注意

- 服务端文件在云端 `/opt/challengedaily/`，不在本仓库（本仓库是 Windows 采集端 + Electron 客户端）
- 云端 `server.py` 有备份 `server.py.bak-deepimg-*`，出问题可回滚
- 每次重启服务会重新加载 queries.py，改动即时生效
