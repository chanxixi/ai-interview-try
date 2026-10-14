import type { Context } from 'koa';

import type { JobService } from '../service/job.service';

/**
 * 岗位域控制器。
 *
 * 当前只承载全链连通性探针 `GET /api/ping` —— 因为它走的就是 job-service 这条下游。
 * T3 起本控制器接管 `GET /api/jobs`（契约见 contracts/bff-java.yaml），
 * 探针届时迁到 `health.controller.ts`（探针 = 深度健康检查）。
 *
 * 控制层纪律（指南 §2.2）：
 *   ✅ 取 `ctx.state.dto` / `ctx.state.traceId` → 调 Service → 写 `ctx.body`
 *   ❌ 业务分支、try/catch、直接调下游、拼 SQL
 *   ❌ 状态码由 errorHandler 决定，这里不写 `ctx.status = 503`
 */
export class JobController {
  constructor(private readonly service: JobService) {}

  /** 用箭头函数属性，保证作为路由回调传递时 `this` 不丢 */
  ping = async (ctx: Context): Promise<void> => {
    ctx.state.log.info('ping received');
    ctx.body = await this.service.ping(ctx.state.traceId);
  };
}
