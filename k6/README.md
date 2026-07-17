# k6 性能测试

## 安装

```bash
# Ubuntu/Debian
sudo gpg -k
sudo gpg --no-default-keyring --keyring /usr/share/keyrings/k6-archive-keyring.gpg \
  --keyserver hkp://keyserver.ubuntu.com:80 --recv-keys C5AD17C747E3415A3642D57D77C6C491D6AC1D69
echo "deb [signed-by=/usr/share/keyrings/k6-archive-keyring.gpg] https://dl.k6.io/deb stable main" \
  | sudo tee /etc/apt/sources.list.d/k6.list
sudo apt-get update && sudo apt-get install k6

# macOS
brew install k6

# 或直接下载二进制
# https://github.com/grafana/k6/releases
```

## 前置条件

### 1. 服务已部署并运行

确保后端服务已启动,默认地址 `http://223.109.49.63:8000`。

### 2. 测试账号存在

当前脚本使用以下账号(确保存在):

| 角色 | 用户名 | 密码 |
|------|--------|------|
| 学生 | `33120202201909@stu.xmu.edu.cn` | `zchzch22` |
| 管理员 | `33120202201909@stu.xmu.edu.cn` | `zchzch22` |

> 两个角色用同一个账号,登录时用不同端点即可:
> - 学生端: `POST /api/authserver/login`
> - 管理员端: `POST /api/authserver/admin/login`

### 3. 万能验证码 (可选)

后端直接硬编码 `'0000'` 通过验证码,无需配置。

## 运行测试

### 1. 冒烟测试 (1 VU, 30s)

验证所有核心接口在低并发下可正常工作:

```bash
k6 run k6/smoke.js -e SKIP_CAPTCHA=1
```

### 2. 负载测试 (50 VUs, 2 分钟)

模拟正常业务峰值,验证 DB pool 扩容后性能:

```bash
k6 run k6/load.js -e SKIP_CAPTCHA=1
```

### 3. 压力测试 (50→200 VUs, 3 分钟)

逐步加压,找出系统瓶颈点:

```bash
k6 run k6/stress.js -e SKIP_CAPTCHA=1
```

### 4. 峰值测试 (阶梯加压)

```bash
k6 run k6/spike.js -e SKIP_CAPTCHA=1
```

### 5. 浸泡测试 (10 VUs, 10 分钟)

长时间稳定性/内存泄漏检测:

```bash
k6 run k6/soak.js -e SKIP_CAPTCHA=1
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `K6_BASE_URL` | `http://223.109.49.63:8000` | 服务地址 |
| `SKIP_CAPTCHA` | `0` (关闭) | 设为 `1` 启用万能验证码 bypass |

示例:

```bash
# 指定服务地址 + 跳过验证码
k6 run k6/smoke.js -e SKIP_CAPTCHA=1 -e K6_BASE_URL=http://localhost:8000

# 输出 JSON 结果用于后续分析
k6 run k6/load.js -e SKIP_CAPTCHA=1 --out json=load_result.json
```

## 输出解读

### 关键指标

| 指标 | 含义 | 合格线 |
|------|------|--------|
| `http_req_duration` P95 | 95% 请求耗时 | < 1s |
| `http_req_duration` P99 | 99% 请求耗时 | < 3s |
| `http_req_failed` rate | 请求失败率 | < 1% |
| `errors` rate | 业务错误率 | < 1% |
| `login_duration` P95 | 登录耗时 | < 2s |
| `list_applications_duration` P95 | 列表查询耗时 | < 500ms |
| `detail_application_duration` P95 | 详情查询耗时 | < 300ms |
| `review_proof_duration` P95 | 审核操作耗时 | < 800ms |
| `pass_application_duration` P95 | 通过操作耗时 | < 800ms |

### JSON 结果后处理

```bash
# 分析负载测试关键指标
cat load_result.json | jq '
  .metrics | to_entries[] |
  select(.key | startswith("http_req_duration") or startswith("errors")) |
  { metric: .key, value: .value }
'

# 找出耗时 > 1s 的请求
cat load_result.json | jq -r '
  .metrics."http_req_duration{expected_response:true}".values | to_entries[] |
  select(.value > 1000) | "P\(index+1): \(.value)ms"
'
```

## 测试场景说明

| 脚本 | VUs | 时长 | 目标 |
|------|-----|------|------|
| `smoke.js` | 1 | 30s | 接口可用性验证 |
| `load.js` | 50 | 2min | 正常业务峰值, 验证 pool 扩容 |
| `stress.js` | 50→200 | 3min | 逐步加压找瓶颈 |
| `spike.js` | 20→300 | 2min | 突发流量冲击 |
| `soak.js` | 10 | 10min | 长时间稳定性/泄漏检测 |

## k6 Studio 使用

1. 打开 k6 Studio, 点击 **Import Test** 或 **New Test**
2. 选择脚本文件 (`smoke.js` 等)
3. 在 Environment 设置中添加:

   ```
   SKIP_CAPTCHA=1
   K6_BASE_URL=http://223.109.49.63:8000
   ```

4. 点击 **Run** 开始测试
