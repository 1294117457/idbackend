/**
 * k6 压力测试 - stress_student.js (学生端视角)
 *
 * 目标: 逐步加压，找出学生端接口的瓶颈点
 * 场景: 登录 → 查看成绩 → 浏览模板 → 申请列表 → 申请详情
 *
 * 运行:
 *   k6 run stress_student.js -e SKIP_CAPTCHA=1
 */

import http from 'k6/http';
import { check, sleep } from 'k6';
import * as api from './common.js';

export const options = {
  stages: [
    { duration: '30s',  target: 30  },   // 阶段1: 30 VUs
    { duration: '30s',  target: 60  },   // 阶段2: 60 VUs
    { duration: '60s',  target: 100 },   // 阶段3: 100 VUs
    { duration: '60s',  target: 150 },   // 阶段4: 150 VUs
    { duration: '30s',  target: 0   },   // 渐退
  ],

  thresholds: {
    errors: ['rate<0.05'],
    http_req_failed: ['rate<0.05'],
    'http_req_duration{expected_response:true}': ['p(95)<5000', 'p(99)<20000'],
  },
};

export function setup() {
  console.log('=== 学生端压力测试 Setup ===');
  console.log(`目标服务: ${api.BASE_URL}`);

  const studentToken = api.login(api.TEST_ACCOUNTS.student)?.accessToken;
  if (!studentToken) {
    console.error('setup: 学生登录失败');
    return null;
  }

  // 获取申请列表中的第一个 ID
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
  console.log('=== 学生端压力测试完成 ===');
}
