/**
 * k6 负载测试 - load.js
 *
 * 目标: 模拟正常业务峰值, 验证 DB pool 扩容后性能
 * 规格: 50 VUs, 2 分钟, 渐变启动
 *
 * 运行:
 *   k6 run load.js -e SKIP_CAPTCHA=1
 *   k6 run load.js -e SKIP_CAPTCHA=1 --out json=load_result.json
 */

import http from 'k6/http';
import { check, group, sleep } from 'k6';
import * as api from './common.js';

export const options = {
  vus: 50,

  stages: [
    { duration: '20s', target: 50 },   // 0→50 VUs
    { duration: '80s', target: 50 },   // 50 VUs 保持
    { duration: '20s', target: 0 },    // 渐退
  ],

  thresholds: {
    errors: ['rate<0.01'],
    http_req_failed: ['rate<0.01'],
    'http_req_duration{expected_response:true}': ['p(95)<1000'],
    'login_duration': ['p(95)<2000'],
    'list_applications_duration': ['p(95)<500'],
    'detail_application_duration': ['p(95)<300'],
    'review_proof_duration': ['p(95)<800'],
    'pass_application_duration': ['p(95)<800'],
  },
};

export function setup() {
  console.log('=== 负载测试 Setup ===');
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

  // ── 场景 1-5: 学生读操作 (5/10 概率) ──────────────────────
  if (scenario < 5) {
    if (!data.studentToken) return;
    api.getMe(data.studentToken);
    sleep(Math.random() * 2 + 0.5);
    api.studentListApplications(data.studentToken);
    sleep(Math.random() * 2 + 0.5);

    // 偶尔查详情
    if (Math.random() < 0.3) {
      const res = api.studentListApplications(data.studentToken, null);
      if (res && res.status === 200) {
        try {
          const firstId = JSON.parse(res.body).data?.list?.[0]?.id;
          if (firstId) api.studentDetailApplication(data.studentToken, firstId);
        } catch (_) {}
      }
    }
    sleep(Math.random() * 2 + 1);
  }
  // ── 场景 6-8: 审核员读操作 (3/10 概率) ─────────────────────
  else if (scenario < 8) {
    if (!data.adminToken) return;
    const r = Math.random();
    if (r < 0.33) {
      api.adminPendingList(data.adminToken);
    } else if (r < 0.66) {
      api.adminMyPending(data.adminToken);
    } else {
      api.adminMyReviewed(data.adminToken);
    }
    sleep(Math.random() + 0.5);
  }
  // ── 场景 9-10: 审核员写操作 (2/10 概率) ────────────────────
  else {
    if (!data.adminToken) return;
    const res = api.adminPendingList(data.adminToken, 1, 10);
    if (res && res.status === 200) {
      try {
        const list = JSON.parse(res.body).data?.list || [];
        // 过滤出仍有 APPLYING 状态的申请,避免重复操作已终态的申请
        const applying = list.filter(app => app.status === 'APPLYING');
        if (applying.length > 0) {
          const app = applying[Math.floor(Math.random() * applying.length)];
          if (app.proofs && app.proofs.length > 0) {
            api.adminReviewProof(data.adminToken, app.id, app.proofs[0].id, 'APPROVED');
            sleep(0.5);
          }
          const action = Math.random() < 0.7 ? 'pass' : 'reject';
          if (action === 'pass') {
            api.adminPassApplication(data.adminToken, app.id);
          } else {
            api.adminRejectApplication(data.adminToken, app.id);
          }
        }
      } catch (_) {}
    }
  }
}

export function teardown(data) {
  console.log('=== 负载测试完成 ===');
}
