/**
 * k6 压力测试 - stress_student_heavy.js (学生端视角)
 *
 * 目标: 更高压力下的持续负载测试（300 VUs，2x 当前上限）
 * 场景: 登录 → 查看成绩 → 申请列表 → 申请详情 → 个人信息
 *
 * 运行:
 *   k6 run stress_student_heavy.js -e SKIP_CAPTCHA=1
 */

import http from 'k6/http';
import { check, sleep } from 'k6';
import * as api from './common.js';

export const options = {
  stages: [
    { duration: '30s',  target: 50  },   // 阶段1: 50 VUs
    { duration: '30s',  target: 100 },   // 阶段2: 100 VUs
    { duration: '60s',  target: 200 },   // 阶段3: 200 VUs
    { duration: '60s',  target: 300 },   // 阶段4: 300 VUs (极限)
    { duration: '60s',  target: 300 },   // 阶段5: 极限持续
    { duration: '30s',  target: 0   },   // 渐退
  ],

  thresholds: {
    errors: ['rate<0.05'],
    http_req_failed: ['rate<0.05'],
    'http_req_duration{expected_response:true}': ['p(95)<5000', 'p(99)<20000'],
  },
};

export function setup() {
  console.log('=== 学生端极限压力测试 Setup ===');
  console.log(`目标服务: ${api.BASE_URL}`);

  const studentToken = api.login(api.TEST_ACCOUNTS.student)?.accessToken;
  if (!studentToken) {
    console.error('setup: 学生登录失败');
    return null;
  }

  let appId = null;
  const res = http.get(`${api.BASE_URL}/api/applications?pageNum=1&pageSize=1`, {
    headers: api.authHeaders(studentToken),
  });
  if (res.status === 200) {
    try {
      const body = JSON.parse(res.body);
      appId = body.data?.list?.[0]?.id || null;
    } catch (_) {}
  }

  console.log(`学生登录成功, 找到 appId=${appId}`);
  return { studentToken, appId };
}

export default function(data) {
  if (!data || !data.studentToken) return;

  const token = data.studentToken;
  const scenario = Math.floor(Math.random() * 10);

  // 35%: 申请列表
  if (scenario < 3) {
    const res = http.get(`${api.BASE_URL}/api/applications?pageNum=1&pageSize=20`, {
      headers: api.authHeaders(token),
    });
    check(res, { 'list: 状态码 200': (r) => r.status === 200 });
    sleep(Math.random() * 0.5 + 0.1);
  }
  // 25%: 申请详情
  else if (scenario < 5 && data.appId) {
    const res = http.get(`${api.BASE_URL}/api/applications/${data.appId}`, {
      headers: api.authHeaders(token),
    });
    check(res, { 'detail: 状态码 200': (r) => r.status === 200 });
    sleep(Math.random() * 0.5 + 0.1);
  }
  // 20%: 我的成绩
  else if (scenario < 7) {
    const res = http.get(`${api.BASE_URL}/api/score/me`, {
      headers: api.authHeaders(token),
    });
    check(res, { 'score: 状态码 200': (r) => r.status === 200 });
    sleep(Math.random() * 0.5 + 0.1);
  }
  // 20%: 个人信息
  else if (scenario < 9) {
    const res = http.get(`${api.BASE_URL}/api/authserver/me`, {
      headers: api.authHeaders(token),
    });
    check(res, { 'me: 状态码 200': (r) => r.status === 200 });
    sleep(Math.random() * 0.5 + 0.1);
  }
  // 10%: 申请详情
  else {
    if (!data.appId) return;
    const res = http.get(`${api.BASE_URL}/api/applications/${data.appId}`, {
      headers: api.authHeaders(token),
    });
    check(res, { 'detail: 状态码 200': (r) => r.status === 200 });
    sleep(Math.random() * 0.5 + 0.1);
  }

  // 模拟用户思考时间
  sleep(Math.random() * 2 + 0.5);
}

export function teardown(data) {
  console.log('=== 学生端极限压力测试完成 ===');
}
