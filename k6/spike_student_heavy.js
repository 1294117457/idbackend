/**
 * k6 峰值测试 - spike_student_heavy.js (学生端视角)
 *
 * 目标: 更高压力下的突发流量测试（500 VUs，2.5x 当前上限）
 * 场景: 学生登录 → 查看成绩 → 申请列表 → 查看详情
 */

import http from 'k6/http';
import { check } from 'k6';
import * as api from './common.js';

export const options = {
  stages: [
    { duration: '10s', target: 50  },   // 预热
    { duration: '20s', target: 100 },   // 爬升
    { duration: '30s', target: 200 },   // 稳住
    { duration: '10s', target: 350 },   // 尖峰: 350 VUs
    { duration: '30s', target: 500 },   // 极限位
    { duration: '30s', target: 500 },   // 极限持续
    { duration: '10s', target: 50  },   // 骤降
    { duration: '10s', target: 0   },   // 清场
  ],

  thresholds: {
    errors: ['rate<0.10'],
    http_req_failed: ['rate<0.10'],
    'http_req_duration{expected_response:true}': ['p(95)<10000'],
  },
};

export function setup() {
  console.log('=== 学生端极限峰值测试 Setup ===');

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

  console.log(`学生登录成功, appId=${appId || 'none'}`);
  return { studentToken, appId };
}

export default function(data) {
  if (!data || !data.studentToken) return;

  const token = data.studentToken;
  const r = Math.random();

  // 40%: 查看申请列表
  if (r < 0.4) {
    const res = http.get(`${api.BASE_URL}/api/applications?pageNum=1&pageSize=20`, {
      headers: api.authHeaders(token),
    });
    check(res, { 'list: 状态码 200': (r) => r.status === 200 });
  }
  // 30%: 我的成绩
  else if (r < 0.7) {
    const res = http.get(`${api.BASE_URL}/api/score/me`, {
      headers: api.authHeaders(token),
    });
    check(res, { 'score: 状态码 200': (r) => r.status === 200 });
  }
  // 20%: 个人信息
  else if (r < 0.9) {
    const res = http.get(`${api.BASE_URL}/api/authserver/me`, {
      headers: api.authHeaders(token),
    });
    check(res, { 'me: 状态码 200': (r) => r.status === 200 });
  }
  // 10%: 查看申请详情（如果有的话）
  else if (data.appId) {
    const res = http.get(`${api.BASE_URL}/api/applications/${data.appId}`, {
      headers: api.authHeaders(token),
    });
    check(res, { 'detail: 状态码 200': (r) => r.status === 200 });
  }
}

export function teardown(data) {
  console.log('=== 学生端极限峰值测试完成 ===');
}
