/**
 * k6 压力测试 - stress.js
 *
 * 目标: 逐步加压, 找出系统瓶颈点
 * 规格: 200 VUs, 3 分钟, 分阶段加压
 *
 * 运行:
 *   k6 run stress.js -e SKIP_CAPTCHA=1
 */

import http from 'k6/http';
import { sleep } from 'k6';
import * as api from './common.js';

export const options = {
  stages: [
    { duration: '30s',  target: 50  },   // 阶段1: 50 VUs
    { duration: '30s',  target: 100 },   // 阶段2: 100 VUs
    { duration: '60s',  target: 150 },   // 阶段3: 150 VUs
    { duration: '60s',  target: 200 },   // 阶段4: 200 VUs (压测目标)
    { duration: '30s',  target: 0   },   // 渐退
  ],

  thresholds: {
    errors: ['rate<0.05'],
    http_req_failed: ['rate<0.05'],
    'http_req_duration{expected_response:true}': ['p(95)<5000', 'p(99)<30000'],
  },
};

export function setup() {
  console.log('=== 压力测试 Setup ===');
  console.log(`目标服务: ${api.BASE_URL}`);
  console.log(`SKIP_CAPTCHA: ${api.SKIP_CAPTCHA}`);

  const studentToken = api.login(api.TEST_ACCOUNTS.student)?.accessToken;
  const adminToken = api.login(api.TEST_ACCOUNTS.admin, '/api/authserver/admin/login')?.accessToken;

  if (!studentToken) console.error('setup: 学生登录失败');
  if (!adminToken) console.error('setup: 管理员登录失败');

  return { studentToken, adminToken };
}

export default function(data) {
  if (!data || (!data.studentToken && !data.adminToken)) return;

  const scenario = Math.floor(Math.random() * 10);

  if (scenario < 6) {
    // 60%: 学生读
    if (!data.studentToken) return;
    api.studentListApplications(data.studentToken);
    sleep(Math.random() * 1.5 + 0.2);
    api.getMe(data.studentToken);
  } else if (scenario < 9) {
    // 30%: 审核员读
    if (!data.adminToken) return;
    api.adminMyPending(data.adminToken);
    sleep(Math.random() * 1 + 0.2);
    api.adminPendingList(data.adminToken);
  } else {
    // 10%: 审核员写
    if (!data.adminToken) return;
    const res = api.adminPendingList(data.adminToken, 1, 5);
    if (res && res.status === 200) {
      try {
        const app = JSON.parse(res.body).data?.list?.[0];
        if (app?.proofs?.[0]) {
          api.adminReviewProof(data.adminToken, app.id, app.proofs[0].id, 'APPROVED');
        }
      } catch (_) {}
    }
  }

  sleep(Math.random() * 2 + 0.5);
}

export function teardown(data) {
  console.log('=== 压力测试完成 ===');
}
