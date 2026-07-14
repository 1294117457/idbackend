/**
 * k6 峰值测试 - spike.js (学生端视角)
 *
 * 目标: 模拟学生突发流量（如下课/截止日前）
 * 场景: 学生登录 → 查看成绩 → 浏览模板 → 查看申请列表 → 查看详情
 */

import http from 'k6/http';
import { check } from 'k6';
import * as api from './common.js';

export const options = {
  vus: 200,

  stages: [
    { duration: '10s', target: 10  },   // 预热
    { duration: '20s', target: 30  },   // 爬升
    { duration: '30s', target: 30  },   // 稳住
    { duration: '5s',  target: 60  },   // 尖峰: 模拟下课/截止日
    { duration: '30s', target: 60  },   // 高位持续
    { duration: '5s',  target: 10  },   // 骤降
    { duration: '10s', target: 0   },   // 清场
  ],

  thresholds: {
    errors: ['rate<0.10'],
    http_req_failed: ['rate<0.10'],
    'http_req_duration{expected_response:true}': ['p(95)<8000'],
  },
};

export function setup() {
  console.log('=== 学生端峰值测试 Setup ===');

  // 登录获取 token
  const studentToken = api.login(api.TEST_ACCOUNTS.student)?.accessToken;
  if (!studentToken) {
    console.error('setup: 学生登录失败');
    return null;
  }

  // 获取一个申请 ID 用于详情测试
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
  else if (r < 0.6) {
    const res = http.get(`${api.BASE_URL}/api/score/me`, {
      headers: api.authHeaders(token),
    });
    check(res, { 'score: 状态码 200': (r) => r.status === 200 });
  }
  // 20%: 个人信息
  else if (r < 0.8) {
    const res = http.get(`${api.BASE_URL}/api/authserver/me`, {
      headers: api.authHeaders(token),
    });
    check(res, { 'me: 状态码 200': (r) => r.status === 200 });
  }
  // 20%: 查看申请详情（如果有的话）
  else if (data.appId) {
    const res = http.get(`${api.BASE_URL}/api/applications/${data.appId}`, {
      headers: api.authHeaders(token),
    });
    check(res, { 'detail: 状态码 200': (r) => r.status === 200 });
  }
}

export function teardown(data) {
  console.log('=== 学生端峰值测试完成 ===');
}
