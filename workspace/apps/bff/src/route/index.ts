import Router from '@koa/router';

import { API_PREFIX } from '../config/constants';
import type { AnalysisController } from '../controller/analysis.controller';
import type { CapabilitiesController } from '../controller/capabilities.controller';
import type { HealthController } from '../controller/health.controller';
import type { JobController } from '../controller/job.controller';
import { uploadGuard } from '../middleware/upload.middleware';

/**
 * 路由接线层：**只做「路径 → controller 方法」的映射**。
 *
 * 纪律（指南 §2.2）：
 *   ❌ 不出现业务判断（`if (score > 80)`）
 *   ❌ 不出现下游调用（`fetch(...)`）
 *   ✅ 中间件挂载点写在这里（例如 T3 的 `validateBody(analyzeRequestSchema)`）
 *
 * 想找「某个 URL 由谁处理」→ 读这一个文件即可（溯源入口）。
 */
export function createApiRouter(deps: {
  health: HealthController;
  job: JobController;
  capabilities: CapabilitiesController;
  analysis: AnalysisController;
}): Router {
  const router = new Router();

  router.get('/healthz', deps.health.health);
  router.get(`${API_PREFIX}/ping`, deps.job.ping);

  // part3：能力探测。前端据此决定要不要放开「深度」分析。
  // 放在 `/api/ping` 旁边是刻意的：两者同属探针族（一个答「通不通」，一个答「能做什么」）。
  router.get(`${API_PREFIX}/capabilities`, deps.capabilities.capabilities);

  // part2 M6：`POST /api/analysis/stream`
  // `uploadGuard` 是**唯一**文件校验点（大小 / MIME / magic number）。
  // 挂在路由上而不是写进 controller —— 「请求进来先过校验」在路由表里可见，
  // 也保证 controller 拿到的 `ctx.state.upload` 一定是校验过的。
  router.post(`${API_PREFIX}/analysis/stream`, uploadGuard, deps.analysis.stream);

  return router;
}
