import { randomUUID } from 'node:crypto';

import type { Context, Next } from 'koa';

import { TRACE_ID_HEADER } from '../config/constants';
import { logger } from '../util/logger';

/**
 * traceId 贯穿（spec.md §2.8）。
 *
 * 读取上游传入的 `X-Trace-Id`，缺失则自行生成；写入 `ctx.state` 供业务使用，
 * 并回写响应头，让调用方（前端 / 上游）能核对同一请求的全链日志。
 *
 * 本中间件之后，`ctx.state.log` 已是绑定了 traceId 的子 logger ——
 * 业务代码一律用 `ctx.state.log`，不要直接 import 全局 logger。
 */
export async function traceIdMiddleware(ctx: Context, next: Next): Promise<void> {
  const incoming = ctx.get(TRACE_ID_HEADER).trim();
  const traceId = incoming === '' ? randomUUID() : incoming;

  ctx.state.traceId = traceId;
  ctx.state.log = logger.child({ traceId });
  ctx.set(TRACE_ID_HEADER, traceId);

  await next();
}
