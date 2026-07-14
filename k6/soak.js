/**
 * k6 浸泡测试 - soak.js
 *
 * 目标: 长时间运行,验证内存泄漏/连接池泄漏/限流是否正常
 * 规格: 10 VUs, 持续 10 分钟
 */

import * as api from './common.js';

export const options = {
  vus: 10,
  duration: '10m',

  stages: [
    { duration: '1m',  target: 10 },   // 渐增到 10
    { duration: '8m',  target: 10 },   // 稳住 10 分钟
    { duration: '1m',  target: 0  },   // 渐退
  ],

  thresholds: {
    // 长时间下要求更严格
    errors: ['rate<0.005'],
    http_req_failed: ['rate<0.005'],
    'http_req_duration{expected_response:true}': ['p(95)<800'],
  },
};

export function setup() {
  console.log('=== 浸泡测试 Setup (10 分钟) ===');
  const studentToken = api.login(api.TEST_ACCOUNTS.student);
  const adminToken = api.login(api.TEST_ACCOUNTS.admin, '/api/authserver/admin/login');
  return { studentToken, adminToken };
}

export default function(data) {
  const scenario = Math.floor(Math.random() * 10);

  if (scenario < 5 && data.studentToken) {
    api.studentListApplications(data.studentToken);
    api.studentMe(data.studentToken);
  } else if (scenario < 9 && data.adminToken) {
    api.adminMyPending(data.adminToken);
    api.adminHistory(data.adminToken);
  } else if (data.adminToken) {
    api.adminMyReviewed(data.adminToken);
  }
}

export function teardown(data) {
  console.log('=== 浸泡测试完成 ===');
}
