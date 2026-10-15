import type { Context, Next } from 'koa';

import { TRACE_ID_HEADER } from '../config/constants';
import { AppError } from '../errors/appError';
import { mapUpstreamError } from '../errors/mapUpstream';
import { mapMulterError } from './upload.middleware';
import { logger } from '../util/logger';
import { toErrorResponse } from '../util/response';

/**
 * 统一错误收口（spec.md §2.3）。
 *
 * - 下游故障 → 按 plan.md §6.4 映射为 503 / 504
 * - 未预期错误 → 500 INTERNAL_ERROR
 * - 响应体固定 `{ code, message, traceId }`，**不透传下游原始错误栈**（spec.md §3.3）
 *
 * 必须是最外层中间件，才能兜住后面所有中间件与路由抛出的异常。
 *
 * 溯源：想知道"某个下游报错时前端看到什么"，读 `errors/mapUpstream.ts`，不要读 controller。
 */
export async function errorHandlerMiddleware(ctx: Context, next: Next): Promise<void> {
  try {
    await next();
  } catch (error) {
    // 翻译顺序是有讲究的：
    //   ① 已经是 AppError（业务层明确判定的）→ 原样用
    //   ② multer 的错误（超大文件 / 解析失败）→ 契约里的 413 / 400（M6.1）
    //   ③ 其余（下游故障 / 未预期异常）→ mapUpstreamError 兜底
    const appError =
      error instanceof AppError ? error : (mapMulterError(error) ?? mapUpstreamError(error));
    // traceId 中间件若自身失败，ctx.state.traceId 可能尚未写入 —— 兜底生成，保证响应体可对齐
    const traceId = ctx.state.traceId ?? ctx.get(TRACE_ID_HEADER);

    const log = ctx.state.log ?? logger;
    if (appError.status >= 500) {
      log.error({ err: error, code: appError.code, status: appError.status }, 'request failed');
    } else {
      log.warn({ err: error, code: appError.code, status: appError.status }, 'request rejected');
    }

    ctx.status = appError.status;
    ctx.body = toErrorResponse(appError, traceId);
  }
}
