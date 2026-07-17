# 认证语义重构方案（HTTP 状态码 + body.code 双轨）

> 本文讲一件事：**怎么彻底分清"未认证 / token 过期 / RBAC 无权限 / 账号被禁用"四种场景**，
> 让前端可以正确触发"自动 refresh → 重试原请求"，而不会被 RBAC 拒绝误当成 token 过期。

---

## 1. 背景与问题

### 1.1 当前代码的事实

| 场景 | 当前后端响应 | HTTP 状态 | body.code | 触发位置 |
|------|----------|----------|----------|---------|
| 没传 Authorization | `{"code":401,"msg":"请先登录"}` | 401 | 401 | `auth_middleware.py:55-56` |
| Bearer 头格式错 | 同上 | 401 | 401 | `auth_middleware.py:55-56` |
| access token 过期 | `{"code":401,"msg":"Token 无效"}` | 401 | 401 | `auth_middleware.py:62-64`（被 `JWTError("Token 已过期", 401)` 翻译） |
| token 签错 / 篡改 | 同上 | 401 | 401 | 同上 |
| **账号被禁用** | `{"code":403,"msg":"账号已被禁用..."}` | **403** ❌ | **403** ❌ | `permission_middleware.py:78` |
| RBAC 权限不足 | `{"code":403,"msg":"权限不足..."}` | 403 | 403 | `permission_middleware.py:104` |
| refresh token 过期 | `{"code":401,"msg":"Token 无效"}` | 401 | 401 | `auth_service.py:138-157`（被 `JWTError(...)` 翻译） |

**两大问题**：

1. **403 混入了"账号被禁用"**（应该属于"身份失效"语义，归 401）
2. **401 没区分** access 过期 vs refresh 过期 vs token 篡改，前端无法选择性触发自动 refresh

### 1.2 后果

管理端 http.ts:115-150 的"403 → 自动 refresh"逻辑**一直在误触发**——任何 RBAC 拒绝都会让前端去刷 token，刷完 RBAC 还是 403，结果 token 被清、用户被踢。

**根因**：401/403 的语义边界模糊，导致前端无法靠 HTTP 状态码正确分类。

---

## 2. 目标

### 2.1 设计原则

1. **HTTP 状态码保持 RFC 9110 标准**：
   - `401 Unauthorized` = 身份不可信（缺失、过期、篡改、禁用）
   - `403 Forbidden` = 身份有效但权限不足（仅 RBAC 使用）
2. **业务细分用 `body.code`**（10001/10002/10003 等）区分"过期类型"
3. **前端按 `body.code` 触发具体动作**（自动 refresh vs 跳登录）

### 2.2 目标矩阵（终态）

| 场景 | HTTP | body.code | msg | 前端动作 |
|------|------|----------|------|---------|
| 无 Authorization 头 | 401 | 401 | 请先登录 | clearTokens + 跳登录 |
| Bearer 头格式错 | 401 | 401 | 请先登录 | clearTokens + 跳登录 |
| **access token 过期** | 401 | **10001** | access_token 已过期 | **自动 refresh → 重试** |
| **refresh token 过期** | 401 | **10002** | refresh_token 已过期，请重新登录 | clearTokens + 跳登录 |
| **token 篡改 / 签错 / 类型错** | 401 | **10003** | Token 无效 | clearTokens + 跳登录 |
| **账号被禁用** | 401 | **10003** | 账号已被禁用，请联系管理员 | 弹禁用提示 + clearTokens + 跳登录 |
| **RBAC 权限不足** | **403** | 403 | 权限不足，需要: {permCode} | 弹 ElMessage.error |
| 登录时账号被禁用（POST /login） | 403 | 403 | 账户已被禁用 | 弹 ElMessage.error（保留现状） |

> 📐 **关于 10003 的合并语义**：token 篡改 / 签错 / 类型错 / **账号被禁用** 都共用 `body.code=10003`。
> 理由：
> 1. 这 4 种场景前端的"最终动作"都是 `clearTokens + 跳登录`，合并 code 不影响 UX；
> 2. 账号禁用是"身份不可信"的极端态，归到 10003（"身份失效通用桶"）比单独编号更合理；
> 3. msg 字段足够前端弹不同的提示（禁用时显示"账号已被禁用" vs token 篡改显示"Token 无效"）；
> 4. 节省编号资源（10004 / 10005 留给未来更细分的场景，如"设备指纹变更"等）。
>
> 前端区分靠 **msg 字段**（弹不同提示），不靠 body.code：
> - `msg="账号已被禁用，请联系管理员"` → 弹 ElMessage 禁用提示
> - `msg="Token 无效"` 或 `msg="access_token 已过期"` → 静默 / 跳登录

---

## 3. 架构调整：中间件职责重新划分

### 3.1 旧划分（混乱）

```
AuthMiddleware          → 解析 token → JWTError 一把梭（401）
PermissionMiddleware    → DB 加载 user_auth → 账号禁用（403） → RBAC 校验（403）
                         ↑ 这里把"身份失效"和"权限不足"混在一个中间件
```

### 3.2 新划分（清晰）

```
AuthMiddleware          → 解析 token → 校验 token 类型 → 校验账号状态
                          失败响应 {code:10001/10002/10003, msg}

PermissionMiddleware    → DB 加载角色/权限 → 查 RBAC 路径权限 → 鉴权判定
                          失败响应 {code:403, msg}（仅这一种可能）

UserService             → 提供 2 个原子方法：
                          - verify_account_active(user_id) → bool  ← AuthMiddleware 用
                          - load_user_rbac(user_id) → roles + permissions  ← PermissionMiddleware 用
```

**关键点**：
- **账号禁用下沉到 AuthMiddleware**（属于"身份失效"，归 401）
- **PermissionMiddleware 只看 RBAC**（不属于身份问题，归 403）
- **DB 查询从 UserService 拆 2 个方法**，中间件只做编排
- **所有 401 / 403 的响应体（HTTP 状态 + body.code）统一在 `response.py` 工厂里定义**，
  `jwt.py` / `auth_middleware.py` / `permission_middleware.py` 都 **直接调用工厂**，不再各自拼响应体

---

## 4. 详细改动设计

> 📐 **章节地图（按依赖层次排序）**：
> - 4.1 `src/app/response.py` — 401/403 响应工厂的**单一来源**（HTTP 状态码 + body.code + msg 在此定义）
> - 4.2 `src/infra/jwt.py` — **只抛异常，不构造响应体**（子异常携带 `body_code`，与 4.1 完全解耦）
> - 4.3 调用方映射表（jwt.py 抛什么 → response.py 哪个工厂）
> - 4.4 `src/app/schemas/errors.py` — `AccountDisabledError`（被 4.9 引用）
> - 4.5 `auth_middleware.py` — 接管账号状态校验，直接 return `response.py` 的工厂
> - 4.6 `permission_middleware.py` — 只做 RBAC，鉴权失败 return `forbidden_resp(...)`
> - 4.7 `user_service.py` — 拆 `verify_account_active` + `load_user_rbac` 2 个原子方法
> - 4.8 `context.py` — ContextVar 结构调整（结构不变，只改 docstring）
> - 4.9 `auth_service.py` — refresh 接口错误细分（用 4.2 的子异常 + 抛 `AccountDisabledError`）
> - 4.10 `exception_handler.py` — 适配 `BusinessError.body_code` 字段（兜底 4.4 类异常）
>
> **依赖图**：
> ```
>   response.py (4.1) ←──── jwt.py (4.2) ←──── auth_middleware.py (4.5)
>        ↑                       ↑                       │
>        │                       │                       ↓
>        │                  schemas/errors.py (4.4) ◄── auth_service.py (4.9) ──→ exception_handler.py (4.10)
>        │                       ↑
>        └── forbidden_resp      │
>            ↑                   │
>   permission_middleware.py (4.6) │
>                                    │
>                          user_service.py (4.7) 提供 verify_account_active / load_user_rbac
>                                    │
>                                    ↓
>                          auth_middleware (4.5) / permission_middleware (4.6) 调用
> ```
> 核心规则：**response.py 是响应体的唯一物理构造点**；jwt.py / errors.py 都不直接构造 JSONResponse。

### 4.1 `src/app/response.py` — 认证 / 鉴权响应工厂的**单一来源**

**原则**：所有"401 → body.code=10001/10002/10003"和"403 → body.code=403"的响应体
**统一在 `response.py` 工厂里定义**，HTTP 状态码 + body.code 一并构造好。
下游 `jwt.py` / `auth_middleware.py` / `permission_middleware.py` / `auth_service.py`
**直接调用工厂**，不再各自拼响应体。

> 🔀 **双 token 设计下，HTTP status_code 与 body.code 解耦是预期行为**：
> - 所有 401 场景（access 过期 / refresh 过期 / token 篡改 / 账号禁用）的 **HTTP status_code 都是 401**；
> - 区分场景靠 **`body.code`**（10001 / 10002 / 10003）和 **`msg`**；
> - 因此 `_resp(status, code, msg, data)` 工厂需要 **接受 HTTP status 与 body.code 两个独立参数**，
>   旧版 `_resp(code, msg)` 隐含"HTTP status = body.code"的约束需打破。

**工厂列表**：

```python
def _resp(status_code: int, code: int, msg: str, data: Any = None) -> JSONResponse:
    """构造统一响应体
    Args:
        status_code: HTTP 状态码（如 401）
        code: 业务码 body.code（如 10001）
        msg: 提示信息
        data: 响应数据
    Note:
        双 token 场景下 status_code 与 code 会不同（如 HTTP 401 + body.code 10001），
        这是 RFC 9110 标准允许的细分场景，前端按 body.code 路由具体动作。
    """
    return JSONResponse(
        status_code=status_code,
        content={"code": code, "msg": msg, "data": data},
    )


# ===== 4xx 客户端错误（与认证 / 鉴权语义相关的工厂） =====

def unauthorized_resp(msg: str = "请先登录") -> JSONResponse:
    """401 未登录 / Authorization 头缺失或格式错 → HTTP 401 + body.code=401
    前端动作：clearTokens + 跳登录"""
    return _resp(401, 401, msg)


def access_token_expired_resp() -> JSONResponse:
    """401 access_token 过期 → HTTP 401 + body.code=10001
    前端动作：自动 refresh + 重试原请求"""
    return _resp(401, 10001, "access_token 已过期")


def refresh_token_expired_resp() -> JSONResponse:
    """401 refresh_token 过期 → HTTP 401 + body.code=10002
    前端动作：clearTokens + 跳登录"""
    return _resp(401, 10002, "refresh_token 已过期，请重新登录")


def invalid_token_resp(msg: str = "Token 无效") -> JSONResponse:
    """401 token 篡改 / 签错 / 类型错 → HTTP 401 + body.code=10003
    前端动作：clearTokens + 跳登录"""
    return _resp(401, 10003, msg)


def account_disabled_resp() -> JSONResponse:
    """401 账号被禁用 → HTTP 401 + body.code=10003（与 invalid_token_resp 同号）
    前端动作：弹禁用提示 + clearTokens + 跳登录

    说明：与 invalid_token_resp 共享 body.code=10003，但 msg 不同：
        invalid_token_resp(msg="Token 无效")              → 弹 "Token 无效"
        account_disabled_resp()                            → 弹 "账号已被禁用"
    前端只认 msg 弹不同提示；不需要靠 body.code 区分。
    """
    return _resp(401, 10003, "账号已被禁用，请联系管理员")


def forbidden_resp(msg: str = "权限不足") -> JSONResponse:
    """403 已登录但 RBAC 无权限 → HTTP 403 + body.code=403
    前端动作：弹 ElMessage.error，不动 token"""
    return _resp(403, 403, msg)
```

**注意**：
- **401 工厂的 HTTP status_code 一律是 401**；区分场景通过 `body.code`（401 / 10001 / 10002 / 10003）。
- **403 工厂的 HTTP status_code 一律是 403**；`body.code` 也为 403（保持一致，业务层只有 1 种 403 语义）。
- 业务层 4xx（400 / 404 / 409 / 429 / 500 等）仍用 `_resp(http_code, http_code, msg)`，
  即 **HTTP status_code = body.code**（业务层不需要细分），如 `_resp(400, 400, "参数错误")`。
- 旧版 `__init__` 注释"设计原则：HTTP status_code 与 body.code 保持一致"要改为：
  > 双 token 场景下 HTTP status_code 与 body.code 解耦；
  > 业务层（4xx/5xx 不细分场景）保持一致；
  > 详见 §2.2 目标矩阵。
- **这些工厂是 HTTP 响应层的契约**，与 `BusinessError` 子类（`schemas/errors.py`）
  是两条并行链路——认证 / 鉴权的失败由中间件直接 `return xxx_resp()`，
  其他业务层失败仍由 `BusinessError → exception_handler` 兜底（见 4.10）。

---

### 4.2 `src/infra/jwt.py` — 只抛异常，不构造响应体

**原则**：`jwt.py` 只负责**抛异常**（携带着 `{http_code, body_code, msg}` 三元组），
**不构造 `JSONResponse`**，更不拼 `body.code`。响应体由 `response.py` 工厂或
`exception_handler` 统一构造。

**改动**：用子异常携带"过期类型 + 错误码语义"，由调用方映射到对应响应工厂。

```python
# 自定义异常（继承自现有 JWTError，向后兼容）
class TokenError(JWTError):
    """JWT 校验失败的基类，自带 http_code=401 + 默认 body.code=10003（"Token 无效"）"""
    http_code: int = 401
    body_code: int = 10003        # 默认 "Token 无效"
    msg: str = "Token 无效"

    def __init__(self, msg: str = None, body_code: int = None):
        super().__init__(msg or self.msg, self.http_code)
        if body_code is not None:
            self.body_code = body_code


class AccessTokenExpiredError(TokenError):
    """access_token 过期 → 由 AuthMiddleware 映射到 access_token_expired_resp()"""
    body_code = 10001
    msg = "access_token 已过期"


class RefreshTokenExpiredError(TokenError):
    """refresh_token 过期 → 由 AuthService.refresh / AuthMiddleware 映射"""
    body_code = 10002
    msg = "refresh_token 已过期"


def verify_token(token: str, expected_type: str = "access") -> dict:
    """校验 token 签名 + 类型 + 过期

    Args:
        token: JWT 字符串
        expected_type: "access" / "refresh"

    Raises:
        AccessTokenExpiredError: access 过期（仅 expected_type="access" 时）
        RefreshTokenExpiredError: refresh 过期（仅 expected_type="refresh" 时）
        TokenError: 签名错 / 类型错 / 篡改（body_code 默认 10003）

    注意：本方法只抛异常，不构造 JSONResponse，不拼 body.code。
    响应体由调用方的中间件 / 服务，按异常.body_code 映射到 response.py 工厂构造。
    """
    try:
        payload = jwt.decode(token, settings.JWT_SECRET,
                             algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        if expected_type == "access":
            raise AccessTokenExpiredError()
        else:
            raise RefreshTokenExpiredError()
    except JWTError as e:
        raise TokenError(f"Token 验证失败: {e}")

    if payload.get("type") != expected_type:
        raise TokenError(f"Token 类型错误，期望 {expected_type}")

    return payload
```

**向后兼容**：
- `TokenError` / `AccessTokenExpiredError` / `RefreshTokenExpiredError` 都继承自 `JWTError`，
  现有捕获 `JWTError` 的代码（auth_middleware 的 `except JWTError`）继续工作。
- `verify_token(token)` 不传 `expected_type` 时默认 `"access"`，行为可演进为传参。
- **本文件绝不导入 `fastapi.responses.JSONResponse`，绝不调用 `response.py` 的任何函数**，
  保持 jwt.py 是纯基础设施层（不依赖 HTTP 框架）。

---

### 4.3 调用方映射表（jwt.py 抛异常 → response.py 工厂）

| 抛异常的位置 | 抛出什么 | 响应工厂（调用方） | HTTP | body.code | msg 关键字 |
|------------|----------|------------------|------|-----------|-----------|
| `auth_middleware.py:dispatch` 未带 Authorization 头 | — | `unauthorized_resp("请先登录")` | 401 | 401 | 请先登录 |
| `auth_middleware.py:dispatch` Bearer 格式错 | — | `unauthorized_resp("请先登录")` | 401 | 401 | 请先登录 |
| `auth_middleware.py:dispatch` 捕获 `AccessTokenExpiredError` | AccessTokenExpiredError | `access_token_expired_resp()` | 401 | **10001** | access_token 已过期 |
| `auth_middleware.py:dispatch` 捕获 `RefreshTokenExpiredError` | RefreshTokenExpiredError | `refresh_token_expired_resp()` | 401 | **10002** | refresh_token 已过期 |
| `auth_middleware.py:dispatch` 捕获 `TokenError`（含签错 / 类型错） | TokenError | `invalid_token_resp()` | 401 | **10003** | Token 无效 |
| `auth_middleware.py:dispatch` 账号被禁用 | — | `account_disabled_resp()` | 401 | **10003** | 账号已被禁用 |
| `permission_middleware.py:dispatch` RBAC 不足 | — | `forbidden_resp("权限不足,需要: {permCode}")` | 403 | 403 | 权限不足 |
| `auth_service.refresh()` 捕获 `RefreshTokenExpiredError` | RefreshTokenExpiredError | 由 `exception_handler` 按 `body_code=10002` 兜底 | 401 | **10002** | refresh_token 已过期 |
| `auth_service.refresh()` 捕获 `TokenError` | TokenError | `exception_handler` 兜底（仍走 10003） | 401 | **10003** | Token 无效 |
| `auth_service.refresh()` 账号被禁用 | AccountDisabledError（见 4.4） | `exception_handler` 按 `body_code=10003` 兜底 | 401 | **10003** | 账号已被禁用 |

**关键结论**：
- `jwt.py` 不知道 401 / 10001 / 10002 / 10003 是什么，只抛异常；
- `response.py` 定义所有 401 / 403 响应体的**物理形态**（HTTP 状态码 + body.code + msg）；
- `exception_handler.py` 是 BusinessError 子类的统一映射层（处理 `body_code=10003` 等异常类型）；
- 前端按 **HTTP 状态码 + body.code** 二维路由：先判 HTTP=401，再按 body.code 分流（详见 §5.1）；
- **10003 是"身份失效通用桶"**，msg 区分不同失效原因（Token 无效 / 账号已被禁用）。

---

### 4.4 `src/app/schemas/errors.py` — `AccountDisabledError` 业务异常

**为什么单独一节**：账号禁用发生在 `auth_service.refresh()` 中（业务层），
需要抛出一个**业务异常**被 `exception_handler` 接管，**而不是中间件直接 return 响应**。
所以这条链路不走 `response.py` 工厂，走 `BusinessError` 子类 + `body_code` 字段。

```python
# src/app/schemas/errors.py
class AccountDisabledError(BusinessError):
    """账号被禁用 → HTTP 401, body.code=10003
    被 auth_service.refresh() 在用户中途被禁用时抛出
    被 exception_handler 按 body_code=10003 映射响应体

    设计决策：body_code=10003 而非单独的 10004，理由见 §2.2。
    """
    http_code = 401               # HTTP 状态码
    error_code = "ACCOUNT_DISABLED"  # 日志用（不要用于响应体）
    body_code = 10003             # 🆕 响应 body.code（与 invalid_token_resp 共享编号，msg 区分）
    default_message = "账号已被禁用，请联系管理员"
```

**设计取舍**：
- `http_code` 还是 401（身份失效）；
- `body_code` = **10003**（身份失效通用桶，与 token 篡改/签错共享）；
- 中间件路径的"账号被禁用"（登录后访问业务接口）走 `auth_middleware` → `account_disabled_resp()` 工厂（4.1）；
- 业务路径的"账号被禁用"（refresh 时发现）走 `auth_service.refresh()` → `AccountDisabledError` → `exception_handler`（4.10）；
- **两条路径都收敛到 body.code=10003**，前端 http.ts 只认 code 不用关心来源，靠 msg 区分提示文案。

---

### 4.5 `src/app/middleware/auth_middleware.py` — 接管账号状态校验

**职责调整**：
- ✅ 解析 Authorization 头
- ✅ 校验 token 签名 + 类型（必须是 access）
- ✅ **新增**：校验账号状态（调用 `UserService.verify_account_active`）
- ❌ 不再只返"请先登录"，改为细分 10001/10002/10003
- ❌ 不在本文件构造任何 `JSONResponse` 详情（HTTP 状态 + body.code 都来自 `response.py` 工厂）

**伪代码**：

```python
from src.app.response import (
    unauthorized_resp,         # 401, body.code=401
    access_token_expired_resp, # 401, body.code=10001
    refresh_token_expired_resp, # 401, body.code=10002
    invalid_token_resp,        # 401, body.code=10003
    account_disabled_resp,     # 401, body.code=10003（与 invalid_token_resp 同号，msg 区分）
)
from src.infra.jwt import (
    verify_token,
    AccessTokenExpiredError,  # body_code=10001
    RefreshTokenExpiredError, # body_code=10002
    TokenError,                # body_code=10003
)

class AuthMiddleware(BaseHTTPMiddleware):
    BYPASS_PATHS = [
        # ... 原有 7 个认证接口 + 3 个文档接口 ...
        # 🆕 refresh 和 logout 必须在白名单：
        "/api/authserver/refresh",  # 自己校验 refresh_token
        "/api/authserver/logout",   # 已登录即可（access 仍需校验）
    ]

    async def dispatch(self, request, call_next):
        path = request.url.path

        if request.method == "OPTIONS":
            return await call_next(request)

        if self._is_bypass_path(path):
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return unauthorized_resp("请先登录")  # ← response.py 工厂，HTTP=401, body.code=401

        token = auth_header[7:]
        try:
            payload = verify_token(token, expected_type="access")
        except AccessTokenExpiredError:
            return access_token_expired_resp()   # ← response.py 工厂，HTTP=401, body.code=10001
        except RefreshTokenExpiredError:
            return refresh_token_expired_resp()  # ← response.py 工厂，HTTP=401, body.code=10002
        except TokenError:
            return invalid_token_resp()          # ← response.py 工厂，HTTP=401, body.code=10003

        user_id = payload.get("userId")

        # 🆕 校验账号状态（DB 一次 SELECT）
        if not await UserService.verify_account_active(user_id):
            return account_disabled_resp()        # ← response.py 工厂，HTTP=401, body.code=10003

        # 🆕 只存身份信息（不存 roles/permissions）
        set_user({
            "user_id": user_id,
            "username": payload.get("username"),
        })

        try:
            return await call_next(request)
        finally:
            clear_user()
```

**重点变化**：
- BYPASS_PATHS 多了 `/api/authserver/refresh`（refresh 接口自己校验 refresh token）
- 多了一次 DB 查询（校验账号状态），**性能取舍**：每次请求 +1 次 `SELECT users.status WHERE id=?`
- ContextVar 只存 `{user_id, username}`，**不存 roles/permissions**（这些由 PermissionMiddleware 加载）
- **本文件不直接构造 JSONResponse，不写 `status_code=` 或 `body.code=`**，
  全部 `return` 一 个 `response.py` 工厂的返回值，确保所有 401 响应体在同一处定义

---

### 4.6 `src/app/middleware/permission_middleware.py` — 只做 RBAC

**职责调整**：
- ✅ DB 加载 user_auth（角色 + 权限）
- ✅ super_admin / SYSTEM_ACCOUNTS 短路
- ✅ 查 RBAC 路径权限码
- ❌ **移除**：账号禁用检测（已下沉到 AuthMiddleware）
- ❌ 不在本文件构造任何 `JSONResponse` 详情，**鉴权失败统一 return `forbidden_resp(...)`**

**伪代码**：

```python
class PermissionMiddleware(BaseHTTPMiddleware):
    PUBLIC_PATHS = { ... }  # 不变
    NO_PERMISSION_PATHS = { ... }  # 不变

    async def dispatch(self, request, call_next):
        path = request.url.path
        if request.method == "OPTIONS":
            return await call_next(request)
        if self._is_under(path, self.PUBLIC_PATHS):
            return await call_next(request)
        if self._is_under(path, self.NO_PERMISSION_PATHS):
            return await call_next(request)

        user_id = get_user_id()
        username = get_username()

        # 白名单超管（不变）
        if is_system_account(username):
            set_user({
                "user_id": user_id,
                "username": username,
                "is_admin": True,
                "roles": [{"roleCode": "super_admin", "roleName": "超级管理员"}],
                "permissions": ["*"],
            })
            return await call_next(request)

        # 加载 RBAC（不会返回 None —— AuthMiddleware 已保证账号 ACTIVE）
        user_auth = await UserService.load_user_rbac(user_id)
        if user_auth is None:
            # 防御性兜底：理论不会到这里（AuthMiddleware 已校验 status）
            return forbidden_resp("权限信息加载失败")

        set_user(user_auth)

        # super_admin 短路（不变）
        if any(r.get("roleCode") == "super_admin" for r in user_auth.get("roles", [])):
            user_auth["permissions"] = ["*"]
            set_user(user_auth)

        # 查路径权限码 + 鉴权判定（不变）
        required = await RbacService.get_path_permission(path)
        if not required:
            return await call_next(request)

        user_perms = get_user_permissions()
        if "*" in user_perms or required in user_perms:
            return await call_next(request)

        return forbidden_resp(f"权限不足，需要: {required}")
```

**重点变化**：
- 移除 `if user_auth is None: return forbidden_resp("账号已被禁用...")` 那段
- 调用 `UserService.load_user_rbac` 而不是 `load_user_auth_info`（语义更精确）

---

### 4.7 `src/services/user_service.py` — 拆分 load_user_auth_info

**改动**：把现有 `load_user_auth_info` 拆 2 个方法：

```python
@staticmethod
async def verify_account_active(user_id: int) -> bool:
    """仅校验账号是否 ACTIVE，专供 AuthMiddleware 调用。

    Returns:
        True  → 账号正常
        False → 用户不存在 / 账号被禁用

    性能：1 次 SELECT，仅查 status 字段（不会全表扫描）
    """
    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)
        return user is not None and user.status == UserStatus.ACTIVE.value

@staticmethod
async def load_user_rbac(user_id: int) -> Optional[Dict[str, Any]]:
    """加载用户角色 + 权限码，专供 PermissionMiddleware 调用。

    Returns:
        None  → 用户不存在（账号状态由 AuthMiddleware 保证，这里不重复检查）
        dict  → {user_id, username, roles, permissions}

    与原 load_user_auth_info 的区别：
    - 不再返回 None 表示"账号禁用"（那个职责下沉到 AuthMiddleware）
    - 不再返回"空角色字典"用于 user 不存在的兜底（PermissionMiddleware 之前是为了兼容 login）
    """
    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)
        if not user:
            return None

        result = await db.execute(
            select(Role.id, Role.role_code, Role.role_name, Permission.permission_code)
            .select_from(UserRole)
            .join(Role, UserRole.role_id == Role.id)
            .join(RolePermission, RolePermission.role_id == Role.id)
            .join(Permission, RolePermission.permission_id == Permission.id)
            .where(UserRole.user_id == user_id)
            .where(Role.status == True)
            .where(Permission.status == True)
        )
        rows = result.all()

        role_map: Dict[int, dict] = {}
        perm_set: set = set()
        for role_id, role_code, role_name, perm_code in rows:
            role_map[role_id] = {"roleCode": role_code, "roleName": role_name}
            perm_set.add(perm_code)

        return {
            "user_id": user.id,
            "username": user.username,
            "is_admin": False,
            "roles": list(role_map.values()),
            "permissions": sorted(perm_set),
        }
```

**是否删除原方法**：保留 `load_user_auth_info` 作为 deprecated 包装，内部转调 `verify_account_active + load_user_rbac`，1-2 个版本后删除。

---

### 4.8 `src/app/context.py` — ContextVar 结构调整

**改动**：`set_user` 接收的数据结构从「完整 auth」变为「两层独立写入」。

```python
# 当前用法（PermissionMiddleware 一把写完）：
set_user({user_id, username, is_admin, roles, permissions})

# 改后用法（两个中间件分别写）：
#  AuthMiddleware 写：
set_user({user_id, username})
#  PermissionMiddleware 覆盖写：
set_user({user_id, username, is_admin, roles, permissions})
```

**ContextVar 本身不需要改**（存的就是 `Optional[Dict[str, Any]]`），**用法上**：

```python
# get_user_id / get_username / get_user_roles / get_user_permissions 都不变
# 它们的实现是 u.get("xxx", default)，缺字段就给默认值，不会 KeyError
```

**唯一需要的改动**：移除 docstring 里"中间件写入：set_user({user_id, username, is_admin, roles, permissions})"这个误导性说明，改为：

```python
"""
使用方式：
  AuthMiddleware 写入身份（set_user({user_id, username})）
  PermissionMiddleware 覆盖写入 RBAC（set_user({user_id, username, roles, permissions})）
  业务代码读取：get_user_id() / get_username() / get_user_permissions() / ...
  请求结束清理：clear_user()
"""
```

---

### 4.9 `src/services/auth_service.py` — refresh 接口错误细分

**当前问题**：`refresh()` 方法里 5 处 `raise JWTError(...)` 全是同一个 401，前端无法区分"refresh 过期"和"用户被禁"。

**改动**：用自定义异常细分。

```python
@staticmethod
async def refresh(db: AsyncSession, refresh_token: str) -> tuple[str, str]:
    """刷新 token"""
    # 1. 解析 refresh token（校验类型 + 过期）
    try:
        payload = verify_token(refresh_token, expected_type="refresh")
    except RefreshTokenExpiredError:
        raise RefreshTokenExpiredError()  # 透传，前端 body.code=10002
    except TokenError:
        raise TokenError("refresh_token 无效", 401)  # body.code=10003

    # 2. 检查 jti
    jti = payload.get("jti")
    if not jti:
        raise TokenError("Refresh token 缺少 jti", 401)

    # 3. 检查是否已撤销
    redis = await get_redis()
    cache = RedisCache(redis)
    if await cache.is_refresh_token_revoked(jti):
        raise TokenError("Refresh token 已失效", 401)

    # 4. 检查用户是否仍然有效
    user_id = payload.get("userId")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise TokenError("用户不存在", 401)
    if user.status != UserStatus.ACTIVE.value:
        # 🆕 用户中途被禁用 → 撤销所有 refresh token
        await cache.revoke_all_user_refresh_tokens(user_id)
        raise AccountDisabledError()  # 🆕 新异常 → body.code=10003（与 invalid_token_resp 共享编号，msg 区分）

    # 5. 撤销旧 refresh token (rotation) + 签发新 token 对（不变）
    ...
```

**问题**：`BusinessError.http_code` 是 HTTP 状态码（401），`body_code` 是新字段（10003）。
两者语义不同：`http_code` 给浏览器/CDN/反代看，`body_code` 给前端 JS 看。
详细定义见 [§4.4](#44-srcappschemaserrorspy--accountdisablederror-业务异常)；本节只是使用方。

---

### 4.10 全局异常处理器 — exception_handler 适配

**当前**：所有 `BusinessError` → `{code: http_code, msg: message}`，一对一映射。

**新规则**：
- 如果 `BusinessError` 有 `body_code` 字段 → 用 `body_code` 作为 body.code
- 否则 → 沿用 `http_code`

```python
# src/app/middleware/exception_handlers.py
async def business_error_handler(request: Request, exc: BusinessError):
    body_code = getattr(exc, "body_code", exc.http_code)  # 🆕 优先用 body_code
    return JSONResponse(
        status_code=exc.http_code,
        content={"code": body_code, "msg": exc.message, "data": None},
    )
```

**好处**：
- 不破坏现有 5 类 BusinessError（NotFoundError / BadRequestError / ForbiddenError / ConflictError / UnauthorizedError）—— 它们没 `body_code`，行为不变
- AccountDisabledError 可以走 401 + body.code=10003（与 token 篡改共享，msg 区分）

---

## 5. 前端改动设计（先做管理端）

### 5.1 `idfrontend-admin/src/common/utils/http.ts`

**目标矩阵**：

| HTTP | body.code | 触发场景 | 前端动作 |
|------|-----------|---------|---------|
| **401** | **10001** | access_token 过期 | **静默 refresh + 重试原请求** |
| **401** | **10002** | refresh_token 过期 | clearTokens + 跳登录（"登录已过期"） |
| **401** | **10003** | token 篡改 / 签错 / 类型错 / **账号被禁用** | clearTokens + 跳登录（按 msg 弹不同提示） |
| **401** | **401** | 业务层 401（旧 `UnauthorizedError`） | clearTokens + 跳登录 |
| **403** | **403** | RBAC 拒绝 | 弹 ElMessage.error(权限不足)，不动 token |
| 200/201 | 200/0/201 | 成功 | 业务成功处理 |
| 其他 | * | 未知错误 | 弹 ElMessage.error(msg) |

**判断顺序规则（强制）**：
1. **先判 HTTP 状态码**（401 / 403 / 200 / 5xx）
2. **再判 body.code**（细分路由）
3. **不兼容旧的 `res.code === 401` 在成功响应里**（重构后业务层 401 一律走 error 拦截器）
4. **不写"10001 出现在成功响应"的防御性代码**（access 过期永远走 HTTP 401）

**重写后的核心逻辑**：

```typescript
import axios, { type AxiosInstance, type AxiosError, type InternalAxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'
import { STORAGE_KEYS } from '@common/constants/storage'
import { useLoadingStore } from '@/stores/loading'

const apiClient: AxiosInstance = axios.create({
  headers: { 'Content-Type': 'application/json' },
  timeout: 10000,
})

// ============ refresh 状态机 ============
let isRefreshing = false
let failedQueue: Array<{
  resolve: (value?: any) => void
  reject: (reason?: any) => void
  config: InternalAxiosRequestConfig
}> = []

const processQueue = (error: any = null) => {
  failedQueue.forEach(({ resolve, reject, config }) => {
    if (error) {
      reject(error)
    } else {
      resolve(apiClient(config))  // 用新的 access_token 重试
    }
  })
  failedQueue = []
}

const clearTokensAndRedirect = async (msg = '登录已过期，请重新登录') => {
  localStorage.removeItem(STORAGE_KEYS.ACCESS_TOKEN)
  localStorage.removeItem(STORAGE_KEYS.REFRESH_TOKEN)
  ElMessage.error(msg)
  const { default: router } = await import('@/router')
  router.push('/login')
}

const doRefreshToken = async (refreshToken: string) => {
  const response = await axios.post<{
    code: number
    msg: string
    data: { accessToken: string; refreshToken: string; expiresIn: number }
  }>(
    '/api/authserver/refresh',
    { refreshToken },
    { headers: { 'Content-Type': 'application/json' } },
  )

  if (response.data.code !== 200) {
    throw new Error(response.data.msg || '刷新失败')
  }

  return response.data.data
}

// ============ 请求拦截器：自动带 access_token ============
apiClient.interceptors.request.use(
  (config) => {
    useLoadingStore().add()
    const token = localStorage.getItem(STORAGE_KEYS.ACCESS_TOKEN)
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => {
    useLoadingStore().sub()
    return Promise.reject(error)
  },
)

// ============ 响应拦截器：先判 HTTP 状态码，再判 body.code ============
apiClient.interceptors.response.use(
  // ===== 成功响应（HTTP 200-299）=====
  (response) => {
    useLoadingStore().sub()
    const res = response.data

    // 业务成功判定：body.code 是 200 / 0 / 201
    const isSuccess = res.code === 200 || res.code === 0 || res.code === 201
    if (!isSuccess) {
      // 理论上重构后业务层 4xx 全部走 error 拦截器（HTTP 非 2xx）
      // 这里的非 200/0/201 视为业务失败（防御性兜底）
      ElMessage.error(res.msg || '请求失败')
      return Promise.reject(res)
    }

    const method = response.config.method?.toLowerCase()
    const silent = (response.config as any).silent === true
    if (method !== 'get' && res.msg && !silent) {
      ElMessage.success(res.msg)
    }

    return res
  },

  // ===== 错误响应（HTTP 非 2xx）：先判 HTTP 状态码 =====
  async (error: AxiosError) => {
    const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean }

    useLoadingStore().sub()

    const statusCode = error.response?.status
    const body = error.response?.data as any
    const bodyCode = body?.code

    // ========== 第一层：按 HTTP 状态码分流 ==========

    // case HTTP 401: 身份失效（细分看 body.code）
    if (statusCode === 401) {
      // ===== 第二层：401 下按 body.code 细分 =====

      // case 10001: access_token 过期 → 自动 refresh + 重试
      if (bodyCode === 10001 && originalRequest && !originalRequest._retry) {
        if (isRefreshing) {
          return new Promise((resolve, reject) => {
            failedQueue.push({ resolve, reject, config: originalRequest })
          })
        }

        originalRequest._retry = true
        isRefreshing = true

        try {
          const refreshTokenValue = localStorage.getItem(STORAGE_KEYS.REFRESH_TOKEN)
          if (!refreshTokenValue) {
            throw new Error('没有 refresh token')
          }

          const newTokens = await doRefreshToken(refreshTokenValue)

          localStorage.setItem(STORAGE_KEYS.ACCESS_TOKEN, newTokens.accessToken)
          localStorage.setItem(STORAGE_KEYS.REFRESH_TOKEN, newTokens.refreshToken)

          originalRequest.headers.Authorization = `Bearer ${newTokens.accessToken}`

          processQueue()
          isRefreshing = false

          return apiClient(originalRequest)
        } catch (refreshError) {
          processQueue(refreshError)
          isRefreshing = false
          clearTokensAndRedirect('登录已过期，请重新登录')
          return Promise.reject(refreshError)
        }
      }

      // case 10002: refresh_token 过期 → 跳登录
      if (bodyCode === 10002) {
        await clearTokensAndRedirect('登录已过期，请重新登录')
        return Promise.reject(error)
      }

      // case 10003: token 篡改 / 签错 / 类型错 / 账号被禁用 → 跳登录
      // 前端靠 msg 区分提示文案：
      //   msg 含"账号已被禁用" → 弹禁用提示
      //   msg 含"Token 无效"   → 弹 token 无效提示
      if (bodyCode === 10003) {
        const isAccountDisabled = body?.msg?.includes('账号已被禁用')
        await clearTokensAndRedirect(
          isAccountDisabled ? '账号已被禁用，请联系管理员' : 'Token 无效，请重新登录'
        )
        return Promise.reject(error)
      }

      // case body.code=401: 业务层 401（旧 UnauthorizedError）→ 跳登录
      if (bodyCode === 401) {
        await clearTokensAndRedirect(body?.msg || '请先登录')
        return Promise.reject(error)
      }

      // 兜底：HTTP 401 但 body.code 不在 10001/10002/10003/401 中（理论上不会出现）
      await clearTokensAndRedirect(body?.msg || '请先登录')
      return Promise.reject(error)
    }

    // case HTTP 403: RBAC 拒绝 → 不动 token，弹错
    if (statusCode === 403) {
      ElMessage.error(body?.msg || '权限不足')
      return Promise.reject(error)
    }

    // case HTTP 5xx: 服务器错误
    if (statusCode && statusCode >= 500) {
      ElMessage.error('服务器异常，请稍后重试')
      return Promise.reject(error)
    }

    // case HTTP 4xx 其他（400 / 404 / 409 / 429）: 业务错误，弹 msg
    if (statusCode && statusCode >= 400 && statusCode < 500) {
      ElMessage.error(body?.msg || '请求失败')
      return Promise.reject(error)
    }

    // 其他（网络断开 / 超时）: 弹通用提示
    ElMessage.error('网络异常，请稍后重试')
    return Promise.reject(error)
  },
)

export default apiClient
```

**关键变化对比原代码**：

| 旧逻辑 | 新逻辑 | 改进点 |
|--------|--------|--------|
| `if (isForbidden && ...)` 触发 refresh | `if (httpCode === 401 && bodyCode === 10001 && ...)` 触发 refresh | **不再误触发 RBAC 403 → refresh** |
| 先按 `bodyCode` 分类，再 `if (statusCode === 401)` 兜底 | **先按 `httpCode` 分类**（401 / 403 / 5xx / 4xx），再按 `bodyCode` 细分 | 判断顺序清晰，符合"HTTP 协议 → 业务码"两层语义 |
| `clearTokensAndRedirect()` 内部消息固定 | 按 body.code 选不同 msg（10002 登录过期 / 10003-token 篡改 / 10003-账号禁用） | UX 更明确 |
| 处理 success 响应里 `res.code === 401` | **删除**（重构后业务层 401 一律走 HTTP 401 → error 拦截器） | 简化成功响应逻辑 |
| `if (res.code === 10001)` 防御性注释 | **删除**（access 过期永远走 HTTP 401，不会出现在成功响应里） | 消除死代码 |
| 10004 账号禁用 | **合并到 10003**（靠 msg 区分提示文案） | 减少分支、节省编号 |

**为什么先判 HTTP 状态码**：
- **HTTP 状态码是协议层语义**（401=身份失效、403=权限不足、500=服务端错误），CDN/反代/浏览器都认；
- **body.code 是业务层语义**（10001/10002/10003 是业务子场景），只有自家前端认；
- 先判 HTTP 可以**优先按协议层语义分流**（401 整体走身份失效分支，403 走权限分支），避免把所有错误混在一个 if-else 链里；
- 双 token 场景下 HTTP=401+body.code=10001 是合法状态，先按 HTTP 分流再按 body.code 细分更符合"先粗后细"的判断逻辑。

---

### 5.2 学生端（暂不动，标记 TODO）

`idfrontend/src/common/utils/http.ts` 现有逻辑（line 76-87）：
- 401 → clearTokens（无论 body.code 是什么）
- 403 → 弹错

**符合新设计**（HTTP 401 一律跳登录），**但**：
- 缺少 10001 自动 refresh 能力
- 缺少 10002 区分提示（vs 10003 token 篡改）

**TODO**：管理端稳定运行 1 个迭代后，把相同的"先 HTTP 后 body.code"分层逻辑搬到学生端。届时同步这两份 http.ts。

---

## 6. 完整改动清单（待评审）

| # | 文件 | 改什么 | 影响 |
|---|------|--------|------|
| 1 | `idbackend/src/infra/jwt.py` | 新增 `TokenError`/`AccessTokenExpiredError`/`RefreshTokenExpiredError`；`verify_token` 加 `expected_type` 参数 + 区分过期类型 | 后端 |
| 2 | `idbackend/src/app/response.py` | 新增 `access_token_expired_resp`/`refresh_token_expired_resp`/`account_disabled_resp`/`invalid_token_resp` | 后端 |
| 3 | `idbackend/src/app/schemas/errors.py` | 新增 `AccountDisabledError`（http_code=401, body_code=10003） | 后端 |
| 4 | `idbackend/src/app/middleware/exception_handlers.py` | 适配 `body_code` 字段（兼容现有 5 类异常） | 后端 |
| 5 | `idbackend/src/app/middleware/auth_middleware.py` | BYPASS_PATHS 加 `/api/authserver/refresh`、`/api/authserver/logout`；校验 token 类型（expected_type="access"）；调 `UserService.verify_account_active` 校验账号状态；区分 10001/10002/10003 | 后端 |
| 6 | `idbackend/src/services/auth_service.py` | `refresh()` 方法用 `verify_token(expected_type="refresh")`；用 `RefreshTokenExpiredError` 透传；用户被禁用时撤销所有 refresh token；新增 `AccountDisabledError` 抛点 | 后端 |
| 7 | `idbackend/src/services/user_service.py` | 拆 `load_user_auth_info` 为 `verify_account_active` + `load_user_rbac`；原方法标记 deprecated 1-2 个版本 | 后端 |
| 8 | `idbackend/src/app/middleware/permission_middleware.py` | 移除账号禁用检测（line 76-78）；调用 `load_user_rbac` 替代 `load_user_auth_info` | 后端 |
| 9 | `idbackend/src/app/context.py` | 改 docstring（AuthMiddleware 写身份，PermissionMiddleware 覆盖写 RBAC）；ContextVar 本身不动 | 后端 |
| 10 | `idfrontend-admin/src/common/utils/http.ts` | 重写响应拦截器，**先判 httpCode 再判 bodyCode**（HTTP 401 → 按 10001/10002/10003 细分，HTTP 403 → 弹错）；合并 10003 通用桶（token 篡改/账号禁用），靠 msg 区分提示 | 前端（管理端） |
| 11 | `idfrontend/src/common/utils/http.ts` | 暂不改（仅 TODO 标记） | 前端（学生端） |

**总改动量**：后端 9 个文件、前端 1 个文件。

---

## 7. 兼容性矩阵

| 场景 | 旧行为 | 新行为 | 兼容性 |
|------|--------|--------|--------|
| access 过期时调用业务接口 | 401 + 跳登录（refresh token 浪费） | 401 + body.code=10001 + 自动 refresh + 重试 | ✅ 体验更好 |
| refresh 过期 | 401 + 跳登录 | 401 + body.code=10002 + 跳登录 | ✅ 体验等价 |
| RBAC 拒绝 | 403 + **错误地**触发 refresh → clearTokens + 跳登录 | 403 + body.code=403 + 弹错 | ✅ 修复 bug |
| 账号被禁用（登录后访问） | 403 + 跳登录（语义错） | 401 + body.code=10003 + 跳登录（弹禁用提示，msg 区分） | ✅ 语义正确 |
| 账号被禁用（登录时） | 403 + 弹错 | 403 + 弹错（不变） | ✅ 不变 |
| token 篡改 | 401 + 跳登录 | 401 + body.code=10003 + 跳登录 | ✅ 体验等价 |
| 无 Authorization 头 | 401 + 跳登录 | 401 + body.code=401 + 跳登录 | ✅ 不变 |

**破坏性变化**：**无**（对外协议兼容）。

---

## 8. 风险清单

| 风险 | 等级 | 防御 |
|------|------|------|
| AuthMiddleware 多 1 次 DB 查询 → 性能影响 | 🟡 中 | 高频接口未来可加 Redis 缓存 user.status；本期不优化 |
| refresh 接口暴露成白名单 → 可能被滥用 | 🟢 低 | refresh 接口校验 refresh_token 类型 + jti + revoked 状态 |
| `body.code` 和 `http_code` 不一致（401 + body.code=10001）→ 前端新人困惑 | 🟢 低 | 本文档 + 代码注释 |
| 10003 账号禁用时，前端需要触发 refresh 后才发现禁用 → 多一次无效 refresh | 🟡 中 | 优化方案：未来 AccountDisabledError 可在 refresh 前置（先 ping /api/authserver/me 探活）；本期不优化 |
| AccountDisabledError 撤销所有 refresh token 是新逻辑 → 可能影响其他活跃 session | 🟡 中 | 仅撤销 refresh token（access token 无状态不可撤销），用户最多在 access 过期前能继续访问（≤ 2 小时） |
| `load_user_auth_info` deprecated 包装 → 容易遗漏 | 🟢 低 | 1 个版本后强删，编译报错提醒 |

---

## 9. 测试 checklist（实施后必跑）

### 后端

- [ ] access 过期 → 401 + body.code=10001
- [ ] refresh 过期 → 401 + body.code=10002
- [ ] access 当 refresh 用（wrong type）→ 401 + body.code=10003
- [ ] refresh 当 access 用（wrong type）→ 401 + body.code=10003
- [ ] 篡改 token → 401 + body.code=10003
- [ ] 账号被禁用（login 后访问）→ 401 + body.code=10003（msg 含"账号已被禁用"）
- [ ] 账号被禁用（login 时）→ 403 + body.code=403
- [ ] RBAC 拒绝 → 403 + body.code=403
- [ ] super_admin 仍能通过短路
- [ ] SYSTEM_ACCOUNTS 白名单仍能登录
- [ ] refresh 接口成功 → 200 + 新的 access_token/refresh_token
- [ ] refresh 接口用户被禁用 → 撤销所有 refresh token + 401 + body.code=10003（msg 含"账号已被禁用"）

### 前端（管理端）

- [ ] access 过期 → 自动 refresh + 用户无感
- [ ] refresh 过期 → 弹"登录过期"+ 跳登录
- [ ] RBAC 拒绝 → 弹"权限不足: {permCode}"，**不再误触发 refresh**
- [ ] 账号禁用 → 弹"账号已被禁用"+ 跳登录
- [ ] 网络断开 → 弹"网络异常"，不动 token
- [ ] 多请求并发 + access 过期 → 只 refresh 1 次，其他请求排队等新 token

### 前端（学生端）

- [ ] 暂不改，**回归测试**现有 401/403 行为没退化

---

## 10. 评审 checklist

- [ ] body.code 10001/10002/10003 的语义是否清晰？10003 合并 token 篡改 + 账号禁用是否接受？
- [ ] AccountDisabledError 用 body_code=10003（与 invalid_token_resp 共享，msg 区分）+ http_code=401 是否合理？
- [ ] AuthMiddleware 多 1 次 DB 查询的性能取舍可接受？
- [ ] refresh 接口加 BYPASS_PATHS 是否安全？
- [ ] `load_user_auth_info` 拆分后是否还有遗漏的调用方？
- [ ] 前端 http.ts 的 10001 自动 refresh 是否覆盖了所有边界 case（并发、网络抖动）？
- [ ] 学生端 http.ts 暂不动的策略是否接受？
- [ ] 是否有遗漏的状态码语义（409 / 429 / 500 等）？

---

## 11. 不在本期范围

- ❌ 学生端 http.ts 接入自动 refresh（下个迭代）
- ❌ `load_user_auth_info` 强删（下下个迭代）
- ❌ AuthMiddleware 加 Redis 缓存 user.status（性能优化）
- ❌ 前置探活机制（refresh 前先 ping /me 检测账号禁用）
- ❌ 审计日志（谁 / 何时 / 哪个接口被拒绝）
- ❌ 撤销所有 access token 的能力（无状态 JWT 改有状态，工作量大）