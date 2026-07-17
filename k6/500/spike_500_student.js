/**
 * k6 尖峰测试 - spike_500_student.js
 *
 * 目标: 模拟突发尖峰，验证系统在 500 并发下的峰值表现
 * 策略: 快速爬升 → 持续稳压 → 骤降，观察系统在极限下的稳定性
 * 覆盖: 学生端高频接口（auth、score、template、application、file）
 *
 * 运行:
 *   k6 run k6/500/spike_500_student.js -e SKIP_CAPTCHA=1
 *   k6 run k6/500/spike_500_student.js -e SKIP_CAPTCHA=1 --out json=spike_500.json
 */

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';

const BASE_URL = __ENV.K6_BASE_URL || 'http://223.109.49.63:8000';
const errors = new Rate('errors');

// ── 接口耗时 Trend ────────────────────────────────────────────
const meTrend          = new Trend('me');
const scoreTrend       = new Trend('score_me');
const catListTrend     = new Trend('cat_list');
const byCatTrend       = new Trend('by_category');
const tmplDetailTrend  = new Trend('tmpl_detail');
const tmplListTrend    = new Trend('tmpl_list');
const appListTrend     = new Trend('app_list');
const appDetailTrend   = new Trend('app_detail');
const saveDraftTrend   = new Trend('save_draft');
const submitTrend      = new Trend('submit');
const fileSearchTrend  = new Trend('file_search');

function authHeaders(token) {
  return {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${token}`,
  };
}

function safeParse(body) {
  try { return JSON.parse(body); } catch { return null; }
}

export const options = {
  // 固定 500 VUs，快速爬升、稳压、再骤降
  vus: 500,

  stages: [
    { duration: '30s',  target: 500 },   // 快速爬升至 500
    { duration: '180s', target: 500 },   // 持续 3 分钟峰值压测
    { duration: '30s',  target: 100 },   // 骤降
    { duration: '30s',  target: 0   },   // 清场
  ],

  thresholds: {
    errors:           ['rate<0.05'],
    http_req_failed:   ['rate<0.05'],
    'http_req_duration{expected_response:true}': ['p(95)<5000', 'p(99)<15000'],
  },
};

export function setup() {
  console.log('=== spike_500 Setup ===');
  console.log(`目标服务: ${BASE_URL}`);

  // 万能验证码登录
  const res = http.post(`${BASE_URL}/api/authserver/login`, JSON.stringify({
    username: '33120202201909@stu.xmu.edu.cn',
    password: 'zchzch22',
    captchaId: 'bypass',
    verifyCode: '0000',
  }), { headers: { 'Content-Type': 'application/json' } });

  if (res.status !== 200) {
    console.error(`setup 登录失败: ${res.status} ${res.body}`);
    return null;
  }

  const body = safeParse(res.body);
  const token = body?.data?.accessToken;
  if (!token) {
    console.error('setup: 未获取到 accessToken');
    return null;
  }

  // 预取数据（只查一次）
  let templateId   = null;
  let categoryId    = null;
  let appId         = null;
  let templateName  = '机电换算';
  let applyScore    = 70;

  const cRes = http.get(`${BASE_URL}/api/template-category/list`, { headers: authHeaders(token) });
  if (cRes.status === 200) {
    const c = safeParse(cRes.body);
    categoryId = c?.data?.[0]?.id || null;
  }

  const tRes = http.get(`${BASE_URL}/api/bonus-template/list?pageNum=1&pageSize=1`, {
    headers: authHeaders(token),
  });
  if (tRes.status === 200) {
    const t = safeParse(tRes.body);
    const tmpl = t?.data?.list?.[0];
    if (tmpl) {
      templateId  = tmpl.id;
      templateName = tmpl.name || templateName;
      categoryId   = tmpl.categoryId || categoryId;
      applyScore   = tmpl.applyScore || applyScore;
    }
  }

  const aRes = http.get(`${BASE_URL}/api/applications?pageNum=1&pageSize=1`, {
    headers: authHeaders(token),
  });
  if (aRes.status === 200) {
    const a = safeParse(aRes.body);
    appId = a?.data?.list?.[0]?.id || null;
  }

  console.log(`登录成功, templateId=${templateId}, templateName=${templateName}, categoryId=${categoryId}, applyScore=${applyScore}, appId=${appId}`);
  return { token, templateId, categoryId, appId, templateName, applyScore };
}

export default function(data) {
  if (!data?.token) return;

  const token = data.token;
  const r = Math.random();

  // ════════════════════════════════════════════════════════════════
  // 高频读接口 (55%)
  // ════════════════════════════════════════════════════════════════

  // 18%: GET /api/authserver/me
  if (r < 0.18) {
    const res = http.get(`${BASE_URL}/api/authserver/me`, {
      headers: authHeaders(token),
    });
    const ok = check(res, { 'me: 200': (r) => r.status === 200 });
    if (!ok) errors.add(1); else errors.add(0);
    meTrend.add(res.timings.duration);
    sleep(Math.random() * 1.5 + 0.5);
    return;
  }

  // 14%: GET /api/score/me
  if (r < 0.32) {
    const res = http.get(`${BASE_URL}/api/score/me`, {
      headers: authHeaders(token),
    });
    const ok = check(res, { 'score: 200': (r) => r.status === 200 });
    if (!ok) errors.add(1); else errors.add(0);
    scoreTrend.add(res.timings.duration);
    sleep(Math.random() * 1.5 + 0.5);
    return;
  }

  // 10%: GET /api/template-category/list
  if (r < 0.42) {
    const res = http.get(`${BASE_URL}/api/template-category/list`, {
      headers: authHeaders(token),
    });
    const ok = check(res, { 'cat-list: 200': (r) => r.status === 200 });
    if (!ok) errors.add(1); else errors.add(0);
    catListTrend.add(res.timings.duration);
    sleep(Math.random() * 1.5 + 0.5);
    return;
  }

  // 13%: GET /api/bonus-template/by-category
  if (r < 0.55) {
    const catId = data.categoryId || 1;
    const res = http.get(`${BASE_URL}/api/bonus-template/by-category?categoryId=${catId}`, {
      headers: authHeaders(token),
    });
    const ok = check(res, { 'by-category: 200': (r) => r.status === 200 });
    if (!ok) errors.add(1); else errors.add(0);
    byCatTrend.add(res.timings.duration);
    sleep(Math.random() * 1.5 + 0.5);
    return;
  }

  // ════════════════════════════════════════════════════════════════
  // 中频读接口 (20%)
  // ════════════════════════════════════════════════════════════════

  // 7%: GET /api/bonus-template/list
  if (r < 0.62) {
    const res = http.get(`${BASE_URL}/api/bonus-template/list?pageNum=1&pageSize=20`, {
      headers: authHeaders(token),
    });
    const ok = check(res, { 'tmpl-list: 200': (r) => r.status === 200 });
    if (!ok) errors.add(1); else errors.add(0);
    tmplListTrend.add(res.timings.duration);
    sleep(Math.random() * 1.5 + 0.5);
    return;
  }

  // 5%: GET /api/bonus-template/{id}
  if (r < 0.67 && data.templateId) {
    const res = http.get(`${BASE_URL}/api/bonus-template/${data.templateId}`, {
      headers: authHeaders(token),
    });
    const ok = check(res, { 'tmpl-detail: 200': (r) => r.status === 200 });
    if (!ok) errors.add(1); else errors.add(0);
    tmplDetailTrend.add(res.timings.duration);
    sleep(Math.random() * 1.5 + 0.5);
    return;
  }

  // 5%: GET /api/applications
  if (r < 0.72) {
    const res = http.get(`${BASE_URL}/api/applications?pageNum=1&pageSize=20`, {
      headers: authHeaders(token),
    });
    const ok = check(res, { 'app-list: 200': (r) => r.status === 200 });
    if (!ok) errors.add(1); else errors.add(0);
    appListTrend.add(res.timings.duration);
    sleep(Math.random() * 1.5 + 0.5);
    return;
  }

  // 3%: GET /api/applications/{id}
  if (r < 0.75 && data.appId) {
    const res = http.get(`${BASE_URL}/api/applications/${data.appId}`, {
      headers: authHeaders(token),
    });
    const ok = check(res, { 'app-detail: 200': (r) => r.status === 200 });
    if (!ok) errors.add(1); else errors.add(0);
    appDetailTrend.add(res.timings.duration);
    sleep(Math.random() * 1.5 + 0.5);
    return;
  }

  // ════════════════════════════════════════════════════════════════
  // 写接口 (15%)
  // ════════════════════════════════════════════════════════════════

  // 9%: POST /api/applications/saveDraft
  if (r < 0.84) {
    const payload = JSON.stringify({
      applicationId: null,
      templateId:   data.templateId || 1,
      templateName: data.templateName || '机电换算',
      categoryId:   data.categoryId || 2,
      applyScore:   data.applyScore || 70,
      proofList:    [],
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

  // 6%: POST /api/applications/submit
  const submitPayload = JSON.stringify({
    applicationId: null,
    templateId:   data.templateId || 1,
    templateName: data.templateName || '机电换算',
    categoryId:   data.categoryId || 2,
    applyScore:   data.applyScore || 70,
    proofList: [{
      proofId:    null,
      fileId:     2,
      proofScore: data.applyScore || 70,
    }],
  });
  const subRes = http.post(`${BASE_URL}/api/applications/submit`, submitPayload, {
    headers: authHeaders(token),
  });
  const subOk = check(subRes, { 'submit: 201': (r) => r.status === 201 || r.status === 200 });
  if (!subOk) errors.add(1); else errors.add(0);
  submitTrend.add(subRes.timings.duration);
  sleep(Math.random() * 1.5 + 0.5);
  return;

  // ════════════════════════════════════════════════════════════════
  // 文件管理 (5%)
  // ════════════════════════════════════════════════════════════════

  // 5%: GET /api/file/search
  if (r < 0.90) {
    const res = http.get(
      `${BASE_URL}/api/file/search?fileCategory=POLICY&pageNum=1&pageSize=10` +
      `&fileName=2&fileExtension=.docx&startTime=2026-07-09&endTime=2026-08-11`,
      { headers: authHeaders(token) },
    );
    const ok = check(res, { 'file-search: 200': (r) => r.status === 200 });
    if (!ok) errors.add(1); else errors.add(0);
    fileSearchTrend.add(res.timings.duration);
    sleep(Math.random() * 1.5 + 0.5);
    return;
  }

  sleep(Math.random() * 1.5 + 0.5);
}

export function teardown(data) {
  console.log('=== spike_500 测试完成 ===');
}
