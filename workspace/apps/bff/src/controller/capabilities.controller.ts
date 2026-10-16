import type { Context } from 'koa';

import type { JobService } from '../service/job.service';

/**
 * 能力探测控制器（part3）。
 *
 * 承载 `GET /api/capabilities` —— 前端据此决定要不要放开「深度」分析。
 * 之所以单独一个控制器而不塞进 `JobController`：它不属于岗位域，
 * 走的是「job-service 这一跳的能力」而不是「岗位数据」。
 *
 * 控制层纪律（指南 §2.2）：取 `ctx.state.traceId` → 调 Service → 写 `ctx.body`。
 * 这里没有 `try/catch` —— 下游异常由 `errorHandler` 统一映射。
 */
export class CapabilitiesController {
  constructor(private readonly service: JobService) {}

  /** 用箭头函数属性，保证作为路由回调传递时 `this` 不丢 */
  capabilities = async (ctx: Context): Promise<void> => {
    ctx.state.log.info('capabilities probed');
    ctx.body = await this.service.capabilities(ctx.state.traceId);
  };
}
