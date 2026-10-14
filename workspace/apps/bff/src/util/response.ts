import type { ErrorResponse } from '../dto/response/error.response';
import type { AppError } from '../errors/appError';

/**
 * 统一**错误**响应封装（spec.md §2.3）。
 *
 * 成功响应不走这里 —— 直接返回业务对象，不套壳（指南 §6.7）。
 *
 * 唯一调用方：`middleware/errorHandler.middleware.ts`。
 * 把「错误对象 → 响应体」的转换收在一个函数里，将来加字段（比如 `details`）只改这里。
 */
export function toErrorResponse(error: AppError, traceId: string): ErrorResponse {
  return { code: error.code, message: error.message, traceId };
}
