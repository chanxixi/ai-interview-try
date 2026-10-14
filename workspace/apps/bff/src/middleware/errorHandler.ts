import type { Context, Next } from 'koa';

import { AppError } from '../errors/appError';
import { mapUpstreamError } from '../errors/mapUpstream';
import { logger } from '../logger';
import { TRACE_ID_HEADER } from './traceId';

/**
 * 统一错误收口（spec.md §2.3）。
 *
 * - 下游故障 → 按 plan.md §6.4 映射为 503 / 504
 * - 未预期错误 → 500 INTERNAL_ERROR
 * - 响应体固定 `{ code, message, traceId }`，**不透传下游原始错误栈**（spec.md §3.3）
 *
 * 必须是最外层中间件，才能兜住后面所有中间件与路由抛出的异常。
 */
export async function errorHandlerMiddleware(ctx: Context, next: Next): Promise<void> {
  try {
    await next();
  } catch (error) {
    const appError = error instanceof AppError ? error : mapUpstreamError(error);
    // traceId 中间件若自身失败，ctx.state.traceId 可能尚未写入 —— 兜底生成，保证响应体可对齐
    const traceId = ctx.state.traceId ?? ctx.get(TRACE_ID_HEADER);

    const log = ctx.state.log ?? logger;
    if (appError.status >= 500) {
      log.error({ err: error, code: appError.code, status: appError.status }, 'request failed');
    } else {
      log.warn({ err: error, code: appError.code, status: appError.status }, 'request rejected');
    }

    ctx.status = appError.status;
    ctx.body = {
      code: appError.code,
      message: appError.message,
      traceId,
    };
  }
}
