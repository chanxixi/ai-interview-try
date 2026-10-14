import Router from '@koa/router';

import { API_PREFIX } from '../config/constants';
import type { HealthController } from '../controller/health.controller';
import type { JobController } from '../controller/job.controller';

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
export function createApiRouter(deps: { health: HealthController; job: JobController }): Router {
  const router = new Router();

  router.get('/healthz', deps.health.health);
  router.get(`${API_PREFIX}/ping`, deps.job.ping);

  // T3 起追加：
  //   router.get(`${API_PREFIX}/jobs`, deps.job.list);
  //   router.post(`${API_PREFIX}/analysis`, validateBody(analyzeRequestSchema), deps.analysis.analyze);

  return router;
}
