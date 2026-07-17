/**
 * k6 自定义指标导出 (metrics.js)
 *
 * 这些指标在所有测试脚本间共享
 */
import { Rate, Trend } from 'k6/metrics';

export const errorRate = new Rate('errors');
export const loginTrend = new Trend('login_duration');
export const listTrend = new Trend('list_applications_duration');
export const detailTrend = new Trend('detail_application_duration');
export const reviewTrend = new Trend('review_proof_duration');
export const passTrend = new Trend('pass_application_duration');
