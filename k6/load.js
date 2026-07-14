/**
 * k6 负载测试 - load.js
 *
 * 目标: 模拟正常业务峰值,验证 DB pool 扩容后性能
 * 规格: 50 VUs, 2 分钟, 渐变启动
 */

import http from 'k6/http';
import { check, group, sleep } from 'k6';
import * as api from './common.js';

export const options = {
  // 50 并发用户,持续 2 分钟,20 秒渐变
  vus: 50,
  duration: '2m',

  // 启动/停止渐变
  stages: [
    { duration: '20s', target: 50 },   // 0→50 VUs
    { duration: '80s', target: 50 },   // 50 VUs 保持
    { duration: '20s', target: 0 },    // 渐退
  ],

  thresholds: {
    // 总错误率 < 1%
    errors: ['rate<0.01'],
    http_req_failed: ['rate<0.01'],
    // 端到端 P95 < 1s (注意: DB pool 扩容后才可能达标)
    'http_req_duration{expected_response:true}': ['p(95)<1000'],
    // 登录 P95 < 2s (含验证码)
    'login_duration': ['p(95)<2000'],
    // 列表查询 P95 < 500ms
    'list_applications_duration': ['p(95)<500'],
    // 详情 P95 < 300ms
    'detail_application_duration': ['p(95)<300'],
    // review 操作 P95 < 800ms
    'review_proof_duration': ['p(95)<800'],
    // 通过操作 P95 < 800ms
    'pass_application_duration': ['p(95)<800'],
  },
};

export function setup() {
  console.log('=== 负载测试 Setup ===');
  console.log(`目标服务: ${api.BASE_URL}`);
  console.log(`VU 数: 50, 持续: 2 分钟`);

  const studentToken = api.login(api.TEST_ACCOUNTS.student);
  const adminToken = api.login(api.TEST_ACCOUNTS.admin, '/api/authserver/admin/login');

  if (!studentToken) {
    console.error('setup: 学生登录失败');
  }
  if (!adminToken) {
    console.error('setup: 管理员登录失败');
  }

  return { studentToken, adminToken };
}

export default function(data) {
  // 每个 VU 独立 session,随机选场景
  const scenario = Math.floor(Math.random() * 10);

  // ── 场景 1-5: 学生读操作 (5/10 概率) ──────────────────────
  if (scenario < 5) {
    if (!data.studentToken) return;
    api.studentMe(data.studentToken);
    sleep(Math.random() * 2 + 0.5);
    api.studentListApplications(data.studentToken);
    sleep(Math.random() * 2 + 0.5);

    // 偶尔查详情
    if (Math.random() < 0.3) {
      const listRes = http.get(`${api.BASE_URL}/api/applications?pageSize=1`, {
        headers: api.authHeaders(data.studentToken),
      });
      if (listRes.status === 200) {
        try {
          const firstId = JSON.parse(listRes.body).data?.list?.[0]?.id;
          if (firstId) api.studentDetailApplication(data.studentToken, firstId);
        } catch (_) {}
      }
    }
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
    // 查待审核列表,取第一个做审核
    const listRes = http.get(
      `${api.BASE_URL}/api/admin/applications?pageNum=1&pageSize=10`,
      { headers: api.authHeaders(data.adminToken) }
    );
    if (listRes.status === 200) {
      try {
        const list = JSON.parse(listRes.body).data?.list || [];
        if (list.length > 0) {
          const app = list[0];
          if (app.proofs && app.proofs.length > 0) {
            const proof = app.proofs[0];
            api.adminReviewProof(data.adminToken, app.id, proof.id, 'APPROVED');
            sleep(0.5);
          }
          // 通过/驳回
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

  sleep(Math.random() * 3 + 1);
}

export function teardown(data) {
  console.log('=== 负载测试完成 ===');
}
