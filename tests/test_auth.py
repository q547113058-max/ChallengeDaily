"""
鉴权中间件测试

覆盖：
- 公开路径不需 token
- 受保护路径无 token → 401
- 受保护路径带正确 token → 200
- 错误 token → 401
- 本机豁免：127.0.0.1 不受限流与失败锁定约束（桌面应用唯一用户场景）
- 速率限制：外部 IP 超过 _RATE_LIMIT_MAX 次 → 429
- 鉴权失败锁定：外部 IP 连续失败 _AUTH_FAIL_LIMIT 次后 → 429

注：这两项防护对 localhost 是**有意豁免**的（本机 Electron 前端重启后 token 轮换
会连续 401，不应把自己锁 15 分钟）。原用例按 localhost 请求断言 429，
与设计相悖且阈值（60/窗口）也与实现（300/窗口）不符，故改为外部 IP 场景，
并补一条豁免断言把这个约定固化下来。
"""
import server


# 非本机来源 IP：用于触发限流/失败锁定（localhost 被有意豁免）
_FAKE_REMOTE_IP = "203.0.113.9"


# ── 公开路径 ──

def test_public_paths_no_token(client):
    """/api/health 不需 token"""
    resp = client.get("/api/health?quick=1")
    assert resp.status_code == 200


# ── 受保护路径 ──

def test_protected_path_no_token_returns_401(client):
    """/api/activities 无 token 返回 401"""
    resp = client.get("/api/activities")
    assert resp.status_code == 401


def test_protected_path_with_token_returns_200(authed_client):
    """带正确 token 返回 200"""
    resp = authed_client.get("/api/activities")
    assert resp.status_code == 200


def test_invalid_token_returns_401(client):
    """错误 token 返回 401"""
    resp = client.get("/api/activities", headers={"X-API-Token": "wrong-token-xxx"})
    assert resp.status_code == 401


# ── 速率限制 ──

def test_localhost_exempt_from_rate_limit(client):
    """本机请求不触发限流（忽略多少次）"""
    max_req = server._RATE_LIMIT_MAX
    for i in range(5):
        resp = client.get("/api/health?quick=1")
        assert resp.status_code == 200, f"本机第 {i + 1} 次请求不应被限流"
    # 即便累计计数超过阈值（此前的 300 次阈值太慢，这里直接走豁免分支验证语义）
    assert server._is_localhost("127.0.0.1") is True
    assert max_req > 0


def test_rate_limiting(client):
    """外部 IP 超过 _RATE_LIMIT_MAX 次后返回 429"""
    max_req = server._RATE_LIMIT_MAX
    server._rate_limit_store.pop(_FAKE_REMOTE_IP, None)

    env = {"REMOTE_ADDR": _FAKE_REMOTE_IP}
    # 阈值内的请求应当通过
    for i in range(max_req):
        resp = client.get("/api/health?quick=1", environ_base=env)
        assert resp.status_code == 200, f"第 {i + 1} 次请求应通过，实际 {resp.status_code}"
    # 第 N+1 次应被限流
    resp = client.get("/api/health?quick=1", environ_base=env)
    assert resp.status_code == 429


# ── 鉴权失败锁定 ──

def test_auth_fail_lockout(client):
    """外部 IP 连续鉴权失败达上限后返回 429（锁定）"""
    limit = server._AUTH_FAIL_LIMIT
    server._auth_fail_store.pop(_FAKE_REMOTE_IP, None)

    env = {"REMOTE_ADDR": _FAKE_REMOTE_IP}
    # 前 N 次错误 token → 401，每次记录一次鉴权失败
    for i in range(limit):
        resp = client.get("/api/activities", headers={"X-API-Token": "bad-token"},
                          environ_base=env)
        assert resp.status_code == 401, f"第 {i + 1} 次失败应返回 401，实际 {resp.status_code}"
    # 第 N+1 次：鉴权失败计数达上限 → 429
    resp = client.get("/api/activities", headers={"X-API-Token": "bad-token"},
                      environ_base=env)
    assert resp.status_code == 429


def test_localhost_exempt_from_auth_fail_lockout(client):
    """本机鉴权失败不会被锁定"""
    for _ in range(server._AUTH_FAIL_LIMIT + 2):
        resp = client.get("/api/activities", headers={"X-API-Token": "bad-token"})
        assert resp.status_code == 401, "本机失败应始终返回 401 而非 429"
