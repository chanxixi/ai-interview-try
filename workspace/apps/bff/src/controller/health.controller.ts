import type { Context } from 'koa';

import { config } from '../config';
import type { HealthResponse } from '../dto/response/health.response';

/**
 * 健康检查 —— spec.md §2.8 要求每个服务暴露 `GET /healthz`。
 *
 * 控制层只做三件事：取值、调 Service、写 `ctx.body`。
 * 本控制器没有 Service（无业务），因此也不该有构造参数。
 *
 * ⚠️ BFF 的 `/healthz` 不返回 `storage` —— 那是 Java 层的字段（spec.md §2.9）。
 */
export class HealthController {
  /** 用箭头函数属性，保证作为路由回调传递时 `this` 不丢 */
  health = async (ctx: Context): Promise<void> => {
    const body: HealthResponse = { status: 'ok', service: config.serviceName };
    ctx.body = body;
  };
}
