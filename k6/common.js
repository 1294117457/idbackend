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
 *   1. 快速冒烟 (1 VU, 30s) - 验证接口可用
 *      k6 run smoke.js -e SKIP_CAPTCHA=1
 *
 *   2. 负载测试 (50 VUs, 2min) - 模拟正常使用
 *      k6 run load.js -e SKIP_CAPTCHA=1
 *
 *   3. 压力测试 (200 VUs, 3min) - 找上限
 *      k6 run stress.js -e SKIP_CAPTCHA=1
 *
 *   4. 峰值测试 (阶梯加压)
 *      k6 run spike.js -e SKIP_CAPTCHA=1
 *
 *   5. 浸泡测试 (10 VUs, 10min) - 长时间稳定性
 *      k6 run soak.js -e SKIP_CAPTCHA=1
 *
 * 输出格式 (推荐 JSON, 方便后处理):
 *      k6 run load.js -e SKIP_CAPTCHA=1 --out json=load_result.json
 *
 * 环境变量:
 *   K6_BASE_URL    服务地址, 默认 http://223.109.49.63:8000
 *   SKIP_CAPTCHA   设为 1 跳过图形验证码 (默认 0, 使用真实验证码)
 */

import http from 'k6/http';
import { check } from 'k6';

import { errorRate, loginTrend, listTrend, detailTrend, reviewTrend, passTrend } from './metrics.js';

export { errorRate, loginTrend, listTrend, detailTrend, reviewTrend, passTrend };

// ════════════════════════════════════════════════════════════════
// 配置
// ════════════════════════════════════════════════════════════════
export const BASE_URL = __ENV.K6_BASE_URL || 'http://223.109.49.63:8000';

export const SKIP_CAPTCHA = __ENV.SKIP_CAPTCHA === '1';

// 测试账号 (测试前确保这些账号存在且有对应角色)
// 学生账号: 有正常申请权限
// 管理员账号: 有审核权限
export const TEST_ACCOUNTS = {
  student: { username: '33120202201909@stu.xmu.edu.cn', password: 'zchzch22', role: 'student' },
  admin:   { username: '33120202201909@stu.xmu.edu.cn', password: 'zchzch22', role: 'admin' },
};

// ════════════════════════════════════════════════════════════════
// 公共工具函数
// ════════════════════════════════════════════════════════════════

/**
 * 获取图形验证码
 * 返回 { captchaId, base64 } | null
 */
export function getCaptcha() {
  const res = http.get(`${BASE_URL}/api/authserver/captcha/generate`);
  if (res.status !== 200) return null;
  try {
    const body = JSON.parse(res.body);
    return { captchaId: body.data.captchaId, base64: body.data.base64 };
  } catch {
    return null;
  }
}

/**
 * 构造带认证 header 的 common object
 */
export function authHeaders(token) {
  return {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${token}`,
  };
}

/**
 * 登录获取 token
 * @param {object} account { username, password, role }
 * @param {string} loginEndpoint '/api/authserver/login' | '/api/authserver/admin/login'
 * @returns {{ accessToken, refreshToken }} | null
 */
export function login(account, loginEndpoint = '/api/authserver/login') {
  if (SKIP_CAPTCHA) {
    // 万能验证码 '0000' 直接通过, captchaId 可以用任意字符串
    const res = http.post(`${BASE_URL}${loginEndpoint}`, JSON.stringify({
      username: account.username,
      password: account.password,
      captchaId: 'bypass-test',
      verifyCode: '0000',
    }), {
      headers: { 'Content-Type': 'application/json' },
    });

    loginTrend.add(res.timings.duration);

    if (res.status !== 200) {
      errorRate.add(1);
      console.error(`login 失败: HTTP ${res.status} ${res.body}`);
      return null;
    }

    try {
      const body = JSON.parse(res.body);
      if (body.code !== 200) {
        errorRate.add(1);
        console.error(`login 业务错误: code=${body.code} msg=${body.msg}`);
        return null;
      }
      errorRate.add(0);
      return {
        accessToken: body.data.accessToken,
        refreshToken: body.data.refreshToken,
      };
    } catch (e) {
      errorRate.add(1);
      console.error(`login 解析失败: ${e}`);
      return null;
    }
  }

  // 正常流程: 需要真实验证码
  const captcha = getCaptcha();
  if (!captcha) {
    console.error('login: 获取验证码失败');
    return null;
  }

  const verifyCode = '0000'; // NOTE: 真实测试需要 OCR 或手动输入
  console.warn('login: 使用 fallback verifyCode=0000，请用 OCR 或手动获取真实验证码');

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

  if (res.status !== 200) {
    errorRate.add(1);
    console.error(`login 失败: HTTP ${res.status} ${res.body}`);
    return null;
  }

  try {
    const body = JSON.parse(res.body);
    // 成功时 backend 返回 code: 200
    if (body.code !== 200) {
      errorRate.add(1);
      console.error(`login 业务错误: code=${body.code} msg=${body.msg}`);
      return null;
    }
    errorRate.add(0);
    return {
      accessToken: body.data.accessToken,
      refreshToken: body.data.refreshToken,
    };
  } catch (e) {
    errorRate.add(1);
    console.error(`login 解析失败: ${e}`);
    return null;
  }
}

/**
 * 获取当前用户信息
 */
export function getMe(token) {
  const res = http.get(`${BASE_URL}/api/authserver/me`, {
    headers: authHeaders(token),
  });
  const ok = check(res, { 'me: 状态码 200': (r) => r.status === 200 });
  if (!ok) errorRate.add(1);
  else errorRate.add(0);
  return res;
}

// ════════════════════════════════════════════════════════════════
// 场景: 学生申请流程
// ════════════════════════════════════════════════════════════════

/**
 * 学生申请列表
 */
export function studentListApplications(token, status = null) {
  const params = status ? `?status=${status}` : '';
  const res = http.get(`${BASE_URL}/api/applications${params}`, {
    headers: authHeaders(token),
  });
  const ok = check(res, { 'list: 状态码 200': (r) => r.status === 200 });
  listTrend.add(res.timings.duration);
  if (!ok) errorRate.add(1);
  else errorRate.add(0);
  return res;
}

/**
 * 学生申请详情
 */
export function studentDetailApplication(token, applicationId) {
  const res = http.get(`${BASE_URL}/api/applications/${applicationId}`, {
    headers: authHeaders(token),
  });
  const ok = check(res, { 'detail: 状态码 200': (r) => r.status === 200 });
  detailTrend.add(res.timings.duration);
  if (!ok) errorRate.add(1);
  else errorRate.add(0);
  return res;
}

/**
 * 学生成绩查询
 */
export function studentScore(token) {
  const res = http.get(`${BASE_URL}/api/score/me`, {
    headers: authHeaders(token),
  });
  const ok = check(res, { 'score: 状态码 200': (r) => r.status === 200 });
  if (!ok) errorRate.add(1);
  else errorRate.add(0);
  return res;
}

/**
 * 学生可申请的加分模板列表
 */
export function studentTemplateList(token) {
  const res = http.get(`${BASE_URL}/api/bonus-template/by-category`, {
    headers: authHeaders(token),
  });
  const ok = check(res, { 'template list: 状态码 200': (r) => r.status === 200 });
  if (!ok) errorRate.add(1);
  else errorRate.add(0);
  return res;
}

// ════════════════════════════════════════════════════════════════
// 场景: 审核员审核流程
// ════════════════════════════════════════════════════════════════

/**
 * 审核员 - 待审核列表 (所有 APPLYING)
 */
export function adminPendingList(token, pageNum = 1, pageSize = 20) {
  const res = http.get(
    `${BASE_URL}/api/admin/applications?pageNum=${pageNum}&pageSize=${pageSize}`,
    { headers: authHeaders(token) }
  );
  const ok = check(res, {
    'admin/pending: 状态码 200': (r) => r.status === 200,
  });
  if (!ok) errorRate.add(1);
  else errorRate.add(0);
  return res;
}

/**
 * 审核员 - 我的待审核 (含过滤)
 */
export function adminMyPending(token, filters = {}) {
  const params = new URLSearchParams({ pageNum: 1, pageSize: 20, ...filters }).toString();
  const res = http.get(`${BASE_URL}/api/admin/applications/my-pending?${params}`, {
    headers: authHeaders(token),
  });
  const ok = check(res, {
    'admin/my-pending: 状态码 200': (r) => r.status === 200,
  });
  if (!ok) errorRate.add(1);
  else errorRate.add(0);
  return res;
}

/**
 * 审核员 - 我的已审核列表
 */
export function adminMyReviewed(token, pageNum = 1) {
  const res = http.get(
    `${BASE_URL}/api/admin/applications/my-reviewed?pageNum=${pageNum}&pageSize=20`,
    { headers: authHeaders(token) }
  );
  const ok = check(res, {
    'admin/my-reviewed: 状态码 200': (r) => r.status === 200,
  });
  if (!ok) errorRate.add(1);
  else errorRate.add(0);
  return res;
}

/**
 * 审核员 - 审核历史
 */
export function adminHistory(token, pageNum = 1) {
  const res = http.get(
    `${BASE_URL}/api/admin/applications/history?pageNum=${pageNum}&pageSize=20`,
    { headers: authHeaders(token) }
  );
  const ok = check(res, {
    'admin/history: 状态码 200': (r) => r.status === 200,
  });
  if (!ok) errorRate.add(1);
  else errorRate.add(0);
  return res;
}

/**
 * 审核员 - review proof
 */
export function adminReviewProof(token, applicationId, proofId, action = 'APPROVED') {
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
  return res;
}

/**
 * 审核员 - 通过申请
 */
export function adminPassApplication(token, applicationId) {
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
  return res;
}

/**
 * 审核员 - 驳回申请
 */
export function adminRejectApplication(token, applicationId) {
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
  return res;
}
