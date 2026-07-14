/**
 * k6 冒烟测试 - smoke.js
 *
 * 目标: 验证所有核心接口在低并发下可正常工作
 * 规格: 1 VU, 30 秒
 */

import http from 'k6/http';
import { check, group, sleep } from 'k6';
import * as api from './common.js';

export const options = {
  vus: 1,
  duration: '30s',
  thresholds: {
    // 错误率 < 1%
    errors: ['rate<0.01'],
    // HTTP 状态码非 200
    http_req_failed: ['rate<0.01'],
    // P95 < 500ms
    'http_req_duration{expected_response:true}': ['p(95)<500'],
  },
};

export function setup() {
  console.log('=== 冒烟测试 Setup ===');

  // 登录两个账号
  const studentToken = api.login(api.TEST_ACCOUNTS.student);
  const adminToken = api.login(api.TEST_ACCOUNTS.admin, '/api/authserver/admin/login');

  if (!studentToken || !adminToken) {
    console.error('setup: 登录失败,测试无法继续');
  }

  return { studentToken, adminToken };
}

export default function(data) {
  if (!data.studentToken || !data.adminToken) return;

  // ── 学生端 ──────────────────────────────────────────────────
  group('冒烟: 学生申请列表', () => {
    api.studentListApplications(data.studentToken);
  });

  sleep(1);

  group('冒烟: 学生详情', () => {
    // 先拿列表,再查第一条详情
    const listRes = http.get(`${api.BASE_URL}/api/applications?pageSize=1`, {
      headers: api.authHeaders(data.studentToken),
    });
    if (listRes.status === 200) {
      try {
        const body = JSON.parse(listRes.body);
        const firstId = body.data?.list?.[0]?.id;
        if (firstId) api.studentDetailApplication(data.studentToken, firstId);
      } catch (_) {}
    }
  });

  sleep(1);

  // ── 审核端 ──────────────────────────────────────────────────
  group('冒烟: 审核员待审核', () => {
    api.adminPendingList(data.adminToken);
  });

  sleep(1);

  group('冒烟: 审核员历史', () => {
    api.adminHistory(data.adminToken);
  });

  sleep(1);

  group('冒烟: 管理员me', () => {
    const res = http.get(`${api.BASE_URL}/api/authserver/me`, {
      headers: api.authHeaders(data.adminToken),
    });
    check(res, { 'admin me: 200': (r) => r.status === 200 });
  });

  sleep(1);
}

export function teardown(data) {
  console.log('=== 冒烟测试完成 ===');
}
