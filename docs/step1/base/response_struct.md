然后我发现，除了正常情况比如标头200，body对应code也是200外
  有的时候标头状态码是200，但是body中的code可能是404之类
  有的时候标头头状态码是404，但是body还是有返回的内容
  有的时候标头标头状态码404，但是body显示无法加载数据，
为什么会有这么多种情况，以及会有标头的状态码和body的code不同步的情况

这种JSONResponse返回对应值就会直接操作这个请求以及对应标头状态码对吗，那这样还会操作对应的body吗，
  比如这里的{"code": 401, "msg": "Token无效"}还会在body中显示吗，
  还是说status_code=401这是修改了标头状态码，
  然后content={"code": 401, "msg": "Token无效"}这一整个是body呢
然后比如说没有api权限时，
  我可以设置status_code=403，
  然后content={"code":403,"msg"="无权限"}
  这么处理对吗，这样就不会显示body无法查看对吗


## 最终实现方案（已落地）

### `app/response.py` — 统一响应函数

设计原则：**HTTP `status_code` 与 body `code` 始终一致**，即 RESTful 流派。

```python
from typing import Any
from fastapi.responses import JSONResponse

def _resp(code: int, msg: str, data: Any = None) -> JSONResponse:
    return JSONResponse(
        status_code=code,
        content={"code": code, "msg": msg, "data": data},
    )

# 2xx 成功
def success_resp(data=None, msg="操作成功") -> JSONResponse: ...      # 200
def created_resp(data=None, msg="创建成功") -> JSONResponse: ...       # 201

# 4xx 客户端错误
def bad_request_resp(msg="请求参数错误", data=None) -> JSONResponse: ...  # 400
def unauthorized_resp(msg="请先登录") -> JSONResponse: ...                 # 401
def forbidden_resp(msg="权限不足") -> JSONResponse: ...                    # 403
def not_found_resp(msg="资源不存在") -> JSONResponse: ...                  # 404

# 5xx 服务端错误
def server_error_resp(msg="服务器内部错误") -> JSONResponse: ...           # 500
```

### 函数命名约定

| 函数 | HTTP 状态码 | 使用场景 |
|---|---|---|
| `success_resp()` | 200 | 查询、更新、删除成功 |
| `created_resp()` | 201 | 资源创建成功 |
| `bad_request_resp()` | 400 | 参数校验失败、业务规则违反 |
| `unauthorized_resp()` | 401 | 未登录、Token 无效/过期 |
| `forbidden_resp()` | 403 | 已登录但权限不足 |
| `not_found_resp()` | 404 | 目标资源不存在 |
| `server_error_resp()` | 500 | 未预期的服务端异常 |

### 路由层用法

```python
from src.app import response as R

# 查询
return R.success_resp(data=result)

# 创建
return R.created_resp(data=new_role)

# 资源不存在
if not role:
    return R.not_found_resp("角色不存在")

# 业务校验失败
if duplicate:
    return R.bad_request_resp("权限码已存在")
```

### 中间件用法

```python
from src.app.response import unauthorized_resp, forbidden_resp

return unauthorized_resp("Token无效")
return forbidden_resp(f"权限不足，需要: {required}")
```

### `main.py` 全局异常兜底

```python
from fastapi.exceptions import RequestValidationError

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    return JSONResponse(
        status_code=400,
        content={"code": 400, "msg": f"参数错误: {exc.errors()[0]['msg']}", "data": None}
    )

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={"code": 500, "msg": "服务器内部错误", "data": None}
    )
```

加了全局兜底后，路由里不再需要 `try/except Exception as e: return R.server_error(str(e))`，只在需要处理特定业务异常时才用 try/except。

### 前端 `http.ts` 对应调整

迁移到 RESTful 后，HTTP 4xx/5xx 走 Axios error 拦截器，success 拦截器简化：

```ts
// success 拦截器（HTTP 2xx）
(response) => {
  const res = response.data
  const method = response.config.method?.toLowerCase()
  if (method !== 'get' && res.msg) {
    ElMessage.success(res.msg)
  }
  return res
}

// error 拦截器（HTTP 4xx/5xx）
// 403 → 权限不足提示（已有）
// 401 → 尝试刷新 token（已有）
// 其他 → resData?.msg || '网络异常' （已有，能正确读到 body.msg）
```

### Body 结构约定

```json
{
  "code": 200,
  "msg": "操作成功",
  "data": { ... }
}
```

- `code`：与 HTTP 状态码一致
- `msg`：人类可读的提示文字，前端可直接用于 toast 展示
- `data`：业务数据，成功时为对象/数组，错误时为 `null`