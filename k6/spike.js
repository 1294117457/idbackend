/**
 * k6 峰值测试 - spike.js
 *
 * 目标: 模拟突发流量冲击,验证系统在瞬时高并发下的表现
 * 规格: 从低到极高,快速尖峰
 */

import * as api from './common.js';

export const options = {
  vus: 300,

  stages: [
    { duration: '10s', target: 5   },   // 预热
    { duration: '10s', target: 30  },   // 爬升
    { duration: '30s', target: 30  },   // 稳住
    { duration: '5s',  target: 50  },   // 尖峰: 模拟截止日峰值
    { duration: '30s', target: 50  },   // 高位持续
    { duration: '5s',  target: 5   },   // 骤降
    { duration: '10s', target: 0   },   // 清场
  ],

  thresholds: {
    // 峰值期间错误率允许稍高,但不应崩溃
    errors: ['rate<0.10'],
    http_req_failed: ['rate<0.10'],
    // 尖峰期间 P99 可能到 10s
    'http_req_duration{expected_response:true}': ['p(95)<10000'],
  },
};

export function setup() {
  const studentToken = api.login(api.TEST_ACCOUNTS.student)?.accessToken;
  const adminToken = api.login(api.TEST_ACCOUNTS.admin, '/api/authserver/admin/login')?.accessToken;
  return { studentToken, adminToken };
}

export default function(data) {
  const r = Math.random();
  if (r < 0.5 && data.studentToken) {
    api.studentListApplications(data.studentToken);
  } else if (r < 0.8 && data.adminToken) {
    api.adminPendingList(data.adminToken);
  } else if (data.adminToken) {
    api.adminMyReviewed(data.adminToken);
  }
}

export function teardown(data) {
  console.log('=== 峰值测试完成 ===');
}
