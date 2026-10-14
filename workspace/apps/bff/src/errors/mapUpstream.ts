import { AppError, UpstreamStatusError, UpstreamTransportError } from './appError';

/**
 * 下游故障 → 对外错误码（plan.md §6.4 的映射表）。
 *
 * ⚠️ **"数据库不可用"不会出现在这里** —— 存储降级在 Java 层内部消化
 *    （spec.md §2.9：三档 `mysql → local → mock`），BFF 永远看不到库的故障。
 *
 * 唯一调用方：`middleware/errorHandler.middleware.ts`。
 * 想改"某个下游报错时前端看到什么"，改这里，不要改 controller。
 */
export function mapUpstreamError(error: unknown): AppError {
  if (error instanceof AppError) {
    return error;
  }

  if (error instanceof UpstreamTransportError) {
    return error.reason === 'timeout'
      ? AppError.upstreamTimeout(error.service)
      : AppError.serviceUnavailable(error.service);
  }

  if (error instanceof UpstreamStatusError) {
    // Java 404 → JOB_NOT_FOUND；analyzer 4xx → ANALYSIS_FAILED；其余（含双方 5xx）→ 503
    if (error.service === 'job-service' && error.status === 404) {
      return AppError.jobNotFound('(unknown)');
    }
    if (error.service === 'analyzer' && error.status >= 400 && error.status < 500) {
      return AppError.analysisFailed();
    }
    return AppError.serviceUnavailable(error.service);
  }

  return AppError.internal();
}
