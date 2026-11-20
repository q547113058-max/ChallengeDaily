# deploy/sync_agent.py 修复记录（2026-11-20）

## 问题
系统代理 `127.0.0.1:3067` 失效（端口无监听），但 Windows 代理设置仍开启。
Python urllib 默认继承系统代理 → `WinError 10061 目标计算机积极拒绝`，
导致采集数据推不到云端，客户端「今日总览」空白。

## 修复
在 deploy/sync_agent.py 中强制直连：

```python
try:
    from urllib.request import Request, urlopen, build_opener, ProxyHandler
    from urllib.error import HTTPError, URLError
except ImportError:
    from urllib2 import Request, urlopen, build_opener, ProxyHandler, HTTPError, URLError

_opener = build_opener(ProxyHandler({}))   # 空代理 = 直连

def urlopen_noproxy(req, timeout=30):
    return _opener.open(req, timeout=timeout)
```

推送处 `urlopen(req, ...)` 改为 `urlopen_noproxy(req, ...)`。

## 同类问题（已修）
- Electron 客户端：`main.cjs` 加 `no-proxy-server` switch + `setProxy({mode:'direct'})`
- 这两处均源于同一个失效的系统代理设置。

## 备注
deploy/ 目录在 ChallengeDaily 仓库外（D:\project\daily\deploy），按项目约定不入库。
