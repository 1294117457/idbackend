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

## 准备测试账号

在部署的服务里创建两个测试账号:

```sql
-- 学生账号 (普通用户角色)
INSERT INTO users (username, password_hash, role, full_name, created_at, updated_at)
VALUES ('test_student', 'HASH_OF_Test123456', 'user', '测试学生', now(), now())
ON CONFLICT (username) DO NOTHING;

-- 审核员账号 (管理员角色)
INSERT INTO users (username, password_hash, role, full_name, created_at, updated_at)
VALUES ('test_admin', 'HASH_OF_Admin123456', 'admin', '测试管理员', now(), now())
ON CONFLICT (username) DO NOTHING;
```

> 如果你的密码是 bcrypt 哈希的,可以这样生成:
> `python3 -c "import bcrypt; print(bcrypt.hashpw(b'Test123456', bcrypt.gensalt()).decode())"`

## 运行测试

### 0. 修改服务地址

如果服务不在 `223.109.49.63:8000`,运行时覆盖:

```bash
export K6_BASE_URL=http://YOUR_SERVER:8000
```

### 1. 冒烟测试 (验证接口可用)

```bash
k6 run k6/smoke.js
```

### 2. 负载测试 (50 VUs, 2 分钟, 验证 pool=30/overflow=50)

```bash
k6 run k6/load.js --out json=load_result.json
```

### 3. 压力测试 (逐步加压到 200 VUs)

```bash
k6 run k6/stress.js --out json=stress_result.json
```

### 4. 峰值测试 (瞬时 300 VUs 冲击)

```bash
k6 run k6/spike.js --out json=spike_result.json
```

### 5. 浸泡测试 (10 分钟稳定性)

```bash
k6 run k6/soak.js --out json=soak_result.json
```

## 输出解读

### 关键指标

| 指标 | 含义 | 合格线 |
|---|---|---|
| `http_req_duration` P95 | 95% 请求耗时 | < 1s |
| `http_req_duration` P99 | 99% 请求耗时 | < 3s |
| `http_req_failed` rate | 请求失败率 | < 1% |
| `errors` rate | 业务错误率 | < 1% |
| `login_duration` P95 | 登录(含验证码)耗时 | < 2s |
| `list_applications_duration` P95 | 列表查询耗时 | < 500ms |
| `review_proof_duration` P95 | 审核操作耗时 | < 800ms |

### JSON 结果后处理

```bash
# 安装 k6 和 jq
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
|---|---|---|---|
| `smoke.js` | 1 | 30s | 接口可用性验证 |
| `load.js` | 50 | 2min | 正常业务峰值,验证 pool 扩容 |
| `stress.js` | 50→200 | 3min | 逐步加压找瓶颈 |
| `spike.js` | 20→300 | 2min | 突发流量冲击 |
| `soak.js` | 10 | 10min | 长时间稳定性/泄漏检测 |
