/**
 * k6 冒烟测试 - smoke.js
 *
 * 目标: 验证所有核心接口在低并发下可正常工作
 * 规格: 1 VU, 30 秒
 *
 * 运行:
 *   k6 run smoke.js -e SKIP_CAPTCHA=1
 */

import http from 'k6/http';
import { check, group, sleep } from 'k6';
import * as api from './common.js';

export const options = {
  vus: 1,
  duration: '30s',
  thresholds: {
    errors: ['rate<0.01'],
    http_req_failed: ['rate<0.01'],
    'http_req_duration{expected_response:true}': ['p(95)<500'],
  },
};

export function setup() {
  console.log('=== 冒烟测试 Setup ===');
  console.log(`目标服务: ${api.BASE_URL}`);
  console.log(`SKIP_CAPTCHA: ${api.SKIP_CAPTCHA}`);

  const studentToken = api.login(api.TEST_ACCOUNTS.student);
  const adminToken = api.login(api.TEST_ACCOUNTS.admin, '/api/authserver/admin/login');

  if (!studentToken || !adminToken) {
    console.error('setup: 登录失败, 测试无法继续');
    return null;
  }

  return { studentToken, adminToken };
}

export default function(data) {
  if (!data || !data.studentToken || !data.adminToken) {
    console.warn('setup 失败, 跳过测试');
    return;
  }

  // ── 学生端 ──────────────────────────────────────────────────
  group('冒烟: 学生 - /api/authserver/me', () => {
    api.getMe(data.studentToken);
  });

  sleep(1);

  group('冒烟: 学生 - 申请列表', () => {
    api.studentListApplications(data.studentToken);
  });

  sleep(1);

  group('冒烟: 学生 - 申请详情', () => {
    // 先拿列表,再查第一条详情
    const res = api.studentListApplications(data.studentToken, null);
    if (res && res.status === 200) {
      try {
        const firstId = JSON.parse(res.body).data?.list?.[0]?.id;
        if (firstId) api.studentDetailApplication(data.studentToken, firstId);
      } catch (_) {}
    }
  });

  sleep(1);

  group('冒烟: 学生 - 成绩查询', () => {
    api.studentScore(data.studentToken);
  });

  sleep(1);

  group('冒烟: 学生 - 可申请模板', () => {
    api.studentTemplateList(data.studentToken);
  });

  sleep(1);

  // ── 审核端 ──────────────────────────────────────────────────
  group('冒烟: 审核员 - 待审核列表', () => {
    api.adminPendingList(data.adminToken);
  });

  sleep(1);

  group('冒烟: 审核员 - 我的待审核', () => {
    api.adminMyPending(data.adminToken);
  });

  sleep(1);

  group('冒烟: 审核员 - 我的已审核', () => {
    api.adminMyReviewed(data.adminToken);
  });

  sleep(1);

  group('冒烟: 审核员 - 审核历史', () => {
    api.adminHistory(data.adminToken);
  });

  sleep(1);

  group('冒烟: 审核员 - /api/authserver/me', () => {
    api.getMe(data.adminToken);
  });
}

export function teardown(data) {
  console.log('=== 冒烟测试完成 ===');
}
