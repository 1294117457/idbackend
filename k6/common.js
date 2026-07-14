/**
 * k6 性能测试脚本 - idbackend
 *
 * 安装:
 *   sudo gpg -k
 *   sudo gpg --no-default-keyring --keyring /usr/share/keyrings/k6-archive-keyring.gpg --keyserver hkp://keyserver.ubuntu.com:80 --recv-keys C5AD17C747E3415A3642D57D77C6C491D6AC1D69
 *   echo "deb [signed-by=/usr/share/keyrings/k6-archive-keyring.gpg] https://dl.k6.io/deb stable main" | sudo tee /etc/apt/sources.list.d/k6.list
 *   sudo apt-get update && sudo apt-get install k6
 *
 * 运行方式:
 *   1. 快速冒烟 (1VUs, 30s) - 验证接口可用
 *      k6 run smoke.js
 *
 *   2. 负载测试 (50VUs, 2min) - 模拟正常使用
 *      k6 run load.js
 *
 *   3. 压力测试 (200VUs, 3min) - 找上限
 *      k6 run stress.js
 *
 *   4. 峰值测试 (阶梯加压)
 *      k6 run spike.js
 *
 *   5. 浸泡测试 (10VUs, 10min) - 长时间稳定性
 *      k6 run soak.js
 *
 * 输出格式 (推荐 JSON,方便后处理):
 *      k6 run load.js --out json=load_result.json
 *
 * 环境变量 (在 .env 文件或运行时覆盖):
 *      K6_BASE_URL    服务地址,默认 http://223.109.49.63:8000
 *      K6_DURATION    测试持续时间,默认 2m
 *      K6_VUS         虚拟用户数,默认 50
 */

import http from 'k6/http';
import { check, sleep, group } from 'k6';

import { errorRate, loginTrend, listTrend, detailTrend, reviewTrend, passTrend } from './metrics.js';

export { errorRate, loginTrend, listTrend, detailTrend, reviewTrend, passTrend };

// ════════════════════════════════════════════════════════════════
// 配置
// ════════════════════════════════════════════════════════════════
const BASE_URL = __ENV.K6_BASE_URL || 'http://223.109.49.63:8000';

// 测试账号 (测试前确保这些账号存在且有对应角色)
// 学生账号: 有正常申请权限
// 审核员账号: 有审核权限
const TEST_ACCOUNTS = {
  student: { username: '33120202201909@stu.xmu.edu.cn', password: 'zchzch22', role: 'student' },
  admin:   { username: '33120202201909@stu.xmu.edu.cn', password: 'zchzch22', role: 'admin' },
};

// ════════════════════════════════════════════════════════════════
// 公共工具函数
// ════════════════════════════════════════════════════════════════

/**
 * 获取图形验证码
 * 返回 { captchaId, base64 }
 */
function getCaptcha() {
  const res = http.get(`${BASE_URL}/api/authserver/captcha/generate`);
  const ok = check(res, { 'captcha: 状态码 200': (r) => r.status === 200 });
  if (!ok) return null;
  try {
    const body = JSON.parse(res.body);
    return { captchaId: body.data.captchaId, base64: body.data.base64 };
  } catch {
    return null;
  }
}

/**
 * 登录获取 token
 * @param {object} account { username, password, role }
 * @param {string} loginEndpoint '/api/authserver/login' | '/api/authserver/admin/login'
 * @returns {{ accessToken, refreshToken, userId }} | null
 */
function login(account, loginEndpoint = '/api/authserver/login') {
  const captcha = getCaptcha();
  if (!captcha) {
    console.error('login: 获取验证码失败');
    return null;
  }

  const verifyCode = __ENV.SKIP_CAPTCHA === '1' ? '0000' : '1234';

  const payload = JSON.stringify({
    username: account.username,
    password: account.password,
    captchaId: captcha.captchaId,
    verifyCode: verifyCode,
  });

  const res = http.post(`${BASE_URL}${loginEndpoint}`, payload, {
    headers: { 'Content-Type': 'application/json' },
  });

  loginTrend.add(res.timings.duration);

  const ok = check(res, { [`login(${account.role}): 状态码 200`]: (r) => r.status === 200 });
  if (!ok) {
    errorRate.add(1);
    console.error(`login 失败: ${res.status} ${res.body}`);
    return null;
  }

  try {
    const body = JSON.parse(res.body);
    if (body.code !== 0) {
      errorRate.add(1);
      console.error(`login 业务错误: ${body.code} ${body.message}`);
      return null;
    }
    errorRate.add(0);
    return {
      accessToken: body.data.accessToken,
      refreshToken: body.data.refreshToken,
    };
  } catch {
    errorRate.add(1);
    return null;
  }
}

/**
 * 构造带认证 header 的 common object
 */
function authHeaders(token) {
  return {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${token}`,
  };
}

// ════════════════════════════════════════════════════════════════
// 场景: 学生申请流程
// ════════════════════════════════════════════════════════════════

/**
 * 登录 → 获取当前用户信息
 */
export function studentMe(token) {
  group('学生 - /api/authserver/me', () => {
    const res = http.get(`${BASE_URL}/api/authserver/me`, {
      headers: authHeaders(token),
    });
    const ok = check(res, { 'me: 状态码 200': (r) => r.status === 200 });
    if (!ok) errorRate.add(1);
    else errorRate.add(0);
  });
}

/**
 * 学生申请列表
 */
export function studentListApplications(token, status = null) {
  group('学生 - GET /api/applications', () => {
    const params = status ? `?status=${status}` : '';
    const res = http.get(`${BASE_URL}/api/applications${params}`, {
      headers: authHeaders(token),
    });
    const ok = check(res, { 'list: 状态码 200': (r) => r.status === 200 });
    listTrend.add(res.timings.duration);
    if (!ok) errorRate.add(1);
    else errorRate.add(0);
  });
}

/**
 * 学生申请详情
 */
export function studentDetailApplication(token, applicationId) {
  group('学生 - GET /api/applications/{id}', () => {
    const res = http.get(`${BASE_URL}/api/applications/${applicationId}`, {
      headers: authHeaders(token),
    });
    const ok = check(res, { 'detail: 状态码 200': (r) => r.status === 200 });
    detailTrend.add(res.timings.duration);
    if (!ok) errorRate.add(1);
    else errorRate.add(0);
  });
}

// ════════════════════════════════════════════════════════════════
// 场景: 审核员审核流程
// ════════════════════════════════════════════════════════════════

/**
 * 审核员 - 待审核列表
 */
export function adminPendingList(token, pageNum = 1, pageSize = 20) {
  group('审核员 - GET /api/admin/applications', () => {
    const res = http.get(
      `${BASE_URL}/api/admin/applications?pageNum=${pageNum}&pageSize=${pageSize}`,
      { headers: authHeaders(token) }
    );
    const ok = check(res, {
      'admin/pending: 状态码 200': (r) => r.status === 200,
    });
    if (!ok) errorRate.add(1);
    else errorRate.add(0);
    return ok ? JSON.parse(res.body) : null;
  });
}

/**
 * 审核员 - 我的待审核(含过滤)
 */
export function adminMyPending(token, filters = {}) {
  group('审核员 - GET /api/admin/applications/my-pending', () => {
    const qs = new URLSearchParams({ pageNum: 1, pageSize: 20, ...filters }).toString();
    const res = http.get(`${BASE_URL}/api/admin/applications/my-pending?${qs}`, {
      headers: authHeaders(token),
    });
    const ok = check(res, {
      'admin/my-pending: 状态码 200': (r) => r.status === 200,
    });
    if (!ok) errorRate.add(1);
    else errorRate.add(0);
  });
}

/**
 * 审核员 - 我的已审核列表
 */
export function adminMyReviewed(token, pageNum = 1) {
  group('审核员 - GET /api/admin/applications/my-reviewed', () => {
    const res = http.get(
      `${BASE_URL}/api/admin/applications/my-reviewed?pageNum=${pageNum}&pageSize=20`,
      { headers: authHeaders(token) }
    );
    const ok = check(res, {
      'admin/my-reviewed: 状态码 200': (r) => r.status === 200,
    });
    if (!ok) errorRate.add(1);
    else errorRate.add(0);
  });
}

/**
 * 审核员 - 审核历史
 */
export function adminHistory(token, pageNum = 1) {
  group('审核员 - GET /api/admin/applications/history', () => {
    const res = http.get(
      `${BASE_URL}/api/admin/applications/history?pageNum=${pageNum}&pageSize=20`,
      { headers: authHeaders(token) }
    );
    const ok = check(res, {
      'admin/history: 状态码 200': (r) => r.status === 200,
    });
    if (!ok) errorRate.add(1);
    else errorRate.add(0);
  });
}

/**
 * 审核员 - review proof
 */
export function adminReviewProof(token, applicationId, proofId, action = 'APPROVED') {
  group('审核员 - POST review proof', () => {
    const payload = JSON.stringify({ action, remark: 'k6性能测试' });
    const res = http.post(
      `${BASE_URL}/api/applications/${applicationId}/proofs/${proofId}/review`,
      payload,
      { headers: authHeaders(token) }
    );
    const ok = check(res, {
      'review-proof: 状态码 200': (r) => r.status === 200,
    });
    reviewTrend.add(res.timings.duration);
    if (!ok) errorRate.add(1);
    else errorRate.add(0);
  });
}

/**
 * 审核员 - 通过申请
 */
export function adminPassApplication(token, applicationId) {
  group('审核员 - POST /api/applications/{id}/pass', () => {
    const payload = JSON.stringify({ remark: 'k6性能测试通过' });
    const res = http.post(
      `${BASE_URL}/api/applications/${applicationId}/pass`,
      payload,
      { headers: authHeaders(token) }
    );
    const ok = check(res, {
      'pass: 状态码 200': (r) => r.status === 200,
    });
    passTrend.add(res.timings.duration);
    if (!ok) errorRate.add(1);
    else errorRate.add(0);
  });
}

/**
 * 审核员 - 驳回申请
 */
export function adminRejectApplication(token, applicationId) {
  group('审核员 - POST /api/applications/{id}/reject', () => {
    const payload = JSON.stringify({ remark: 'k6性能测试驳回' });
    const res = http.post(
      `${BASE_URL}/api/applications/${applicationId}/reject`,
      payload,
      { headers: authHeaders(token) }
    );
    const ok = check(res, {
      'reject: 状态码 200': (r) => r.status === 200,
    });
    if (!ok) errorRate.add(1);
    else errorRate.add(0);
  });
}
