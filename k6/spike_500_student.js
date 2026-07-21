/**
 * k6 峰值测试 - spike_500_student.js
 *
 * 目标: 模拟 500 学生并发尖峰，验证 template + application 接口性能
 * 服务器: http://223.109.49.63:8000
 *
 * 运行:
 *   k6 run spike_500_student.js -e SKIP_CAPTCHA=1
 */

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';

const BASE_URL = 'http://223.109.49.63:8000';
const errors = new Rate('errors');

const listTrend = new Trend('list_templates');
const categoryTrend = new Trend('category_templates');
const templateDetailTrend = new Trend('template_detail');
const appListTrend = new Trend('app_list');
const appDetailTrend = new Trend('app_detail');
const saveDraftTrend = new Trend('save_draft');
const submitTrend = new Trend('submit');

function authHeaders(token) {
  return {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${token}`,
  };
}

export const options = {
  vus: 500,

  stages: [
    { duration: '30s', target: 50  },   // 预热
    { duration: '30s', target: 200 },   // 爬升
    { duration: '60s', target: 500 },   // 500人峰值
    { duration: '60s', target: 500 },   // 稳住观察稳定性
    { duration: '30s', target: 50  },   // 骤降
    { duration: '30s', target: 0   },   // 清场
  ],

  thresholds: {
    errors: ['rate<0.05'],
    http_req_failed: ['rate<0.05'],
    'http_req_duration{expected_response:true}': ['p(95)<5000', 'p(99)<15000'],
  },
};

export function setup() {
  console.log('=== spike_500 Setup ===');

  // 万能验证码登录
  const res = http.post(`${BASE_URL}/api/authserver/login`, JSON.stringify({
    username: '33120202201909@stu.xmu.edu.cn',
    password: 'zchzch22',
    captchaId: 'bypass-test',
    verifyCode: '0000',
  }), {
    headers: { 'Content-Type': 'application/json' },
  });

  if (res.status !== 200) {
    console.error(`setup 登录失败: ${res.status} ${res.body}`);
    return null;
  }

  let body;
  try { body = JSON.parse(res.body); } catch { return null; }

  const token = body?.data?.accessToken;
  if (!token) {
    console.error('setup: 未获取到 accessToken');
    return null;
  }

  // 预取数据: template_id 和 application_id (只查一次)
  let templateId = null;
  let appId = null;

  const tRes = http.get(`${BASE_URL}/api/bonus-template/list?pageNum=1&pageSize=1`, {
    headers: authHeaders(token),
  });
  if (tRes.status === 200) {
    try {
      const t = JSON.parse(tRes.body);
      templateId = t?.data?.list?.[0]?.id || null;
    } catch (_) {}
  }

  const aRes = http.get(`${BASE_URL}/api/applications?pageNum=1&pageSize=1`, {
    headers: authHeaders(token),
  });
  if (aRes.status === 200) {
    try {
      const a = JSON.parse(aRes.body);
      appId = a?.data?.list?.[0]?.id || null;
    } catch (_) {}
  }

  console.log(`登录成功, templateId=${templateId}, appId=${appId}`);
  return { token, templateId, appId };
}

export default function(data) {
  if (!data?.token) return;

  const token = data.token;
  const r = Math.random();

  // ── 70%: 读接口 ──────────────────────────────────────

  // 20%: 模板分页列表
  if (r < 0.20) {
    const res = http.get(`${BASE_URL}/api/bonus-template/list?pageNum=1&pageSize=20`, {
      headers: authHeaders(token),
    });
    const ok = check(res, { 'list: 200': (r) => r.status === 200 });
    if (!ok) errors.add(1); else errors.add(0);
    listTrend.add(res.timings.duration);
    sleep(Math.random() * 1.5 + 0.5);
    return;
  }

  // 20%: 按分类查模板
  if (r < 0.40) {
    const catId = Math.floor(Math.random() * 5) + 1;
    const res = http.get(`${BASE_URL}/api/bonus-template/by-category?categoryId=${catId}`, {
      headers: authHeaders(token),
    });
    const ok = check(res, { 'by-category: 200': (r) => r.status === 200 });
    if (!ok) errors.add(1); else errors.add(0);
    categoryTrend.add(res.timings.duration);
    sleep(Math.random() * 1.5 + 0.5);
    return;
  }

  // 15%: 我的申请列表
  if (r < 0.55) {
    const res = http.get(`${BASE_URL}/api/applications?pageNum=1&pageSize=20`, {
      headers: authHeaders(token),
    });
    const ok = check(res, { 'app-list: 200': (r) => r.status === 200 });
    if (!ok) errors.add(1); else errors.add(0);
    appListTrend.add(res.timings.duration);
    sleep(Math.random() * 1.5 + 0.5);
    return;
  }

  // 15%: 模板详情
  if (r < 0.70 && data.templateId) {
    const res = http.get(`${BASE_URL}/api/bonus-template/${data.templateId}`, {
      headers: authHeaders(token),
    });
    const ok = check(res, { 'template-detail: 200': (r) => r.status === 200 });
    if (!ok) errors.add(1); else errors.add(0);
    templateDetailTrend.add(res.timings.duration);
    sleep(Math.random() * 1.5 + 0.5);
    return;
  }

  // ── 20%: 写接口 ──────────────────────────────────────

  // 10%: 保存草稿
  if (r < 0.80) {
    const payload = JSON.stringify({
      templateId: data.templateId || 1,
      answers: [],
    });
    const res = http.post(`${BASE_URL}/api/applications/saveDraft`, payload, {
      headers: authHeaders(token),
    });
    const ok = check(res, { 'saveDraft: 201': (r) => r.status === 201 || r.status === 200 });
    if (!ok) errors.add(1); else errors.add(0);
    saveDraftTrend.add(res.timings.duration);
    sleep(Math.random() * 1.5 + 0.5);
    return;
  }

  // 10%: 提交申请
  if (r < 0.90) {
    const payload = JSON.stringify({
      templateId: data.templateId || 1,
      answers: [
        { ruleId: 1, value: 'k6-test' },
      ],
    });
    const res = http.post(`${BASE_URL}/api/applications/submit`, payload, {
      headers: authHeaders(token),
    });
    const ok = check(res, { 'submit: 201': (r) => r.status === 201 || r.status === 200 });
    if (!ok) errors.add(1); else errors.add(0);
    submitTrend.add(res.timings.duration);
    sleep(Math.random() * 1.5 + 0.5);
    return;
  }

  // ── 10%: 申请详情 ───────────────────────────────────

  // 10%: 申请详情
  if (data.appId) {
    const res = http.get(`${BASE_URL}/api/applications/${data.appId}`, {
      headers: authHeaders(token),
    });
    const ok = check(res, { 'app-detail: 200': (r) => r.status === 200 });
    if (!ok) errors.add(1); else errors.add(0);
    appDetailTrend.add(res.timings.duration);
    sleep(Math.random() * 1.5 + 0.5);
    return;
  }

  sleep(Math.random() * 1.5 + 0.5);
}

export function teardown(data) {
  console.log('=== spike_500 测试完成 ===');
}
