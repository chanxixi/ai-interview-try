/**
 * 错误码与错误映射 —— spec.md §2.3（冻结）+ plan.md §6.4（下游表现 → 错误码）。
 *
 * 统一响应体：`{ "code": "...", "message": "...", "traceId": "..." }`
 * 禁止向前端透传下游原始错误栈（spec.md §3.3）—— 这里只暴露 code 与安全文案。
 */

export const ERROR_CODES = [
  'INVALID_INPUT',
  'RESUME_TOO_LONG',
  'JOB_NOT_FOUND',
  'ANALYSIS_FAILED',
  'RATE_LIMITED',
  'SERVICE_UNAVAILABLE',
  'UPSTREAM_TIMEOUT',
  'INTERNAL_ERROR',
] as const;

export type ErrorCode = (typeof ERROR_CODES)[number];

/** 面向客户端的业务错误。status + code 的组合必须在 spec.md §2.3 表内。 */
export class AppError extends Error {
  readonly status: number;
  readonly code: ErrorCode;

  constructor(status: number, code: ErrorCode, message: string) {
    super(message);
    this.name = 'AppError';
    this.status = status;
    this.code = code;
  }

  static invalidInput(message = '请求参数校验失败'): AppError {
    return new AppError(400, 'INVALID_INPUT', message);
  }

  static upstreamTimeout(service: string): AppError {
    return new AppError(504, 'UPSTREAM_TIMEOUT', `下游服务 ${service} 响应超时`);
  }

  static serviceUnavailable(service: string): AppError {
    return new AppError(503, 'SERVICE_UNAVAILABLE', `下游服务 ${service} 暂时不可用`);
  }

  static internal(): AppError {
    return new AppError(500, 'INTERNAL_ERROR', '服务内部错误');
  }
}

/** 下游返回了非 2xx 状态码。 */
export class UpstreamStatusError extends Error {
  constructor(
    readonly service: string,
    readonly status: number,
  ) {
    super(`upstream ${service} responded ${status}`);
    this.name = 'UpstreamStatusError';
  }
}

/** 下游连不上 / 超时 / 响应不可解析等传输层故障。 */
export class UpstreamTransportError extends Error {
  constructor(
    readonly service: string,
    readonly reason: 'timeout' | 'network' | 'malformed',
    cause?: unknown,
  ) {
    super(`upstream ${service} transport failure: ${reason}`, { cause });
    this.name = 'UpstreamTransportError';
  }
}

/**
 * 下游故障 → 对外错误码（plan.md §6.4 的映射表）。
 *
 * 骨架阶段只覆盖 ping 链路；T3 引入 `jobId` / `analysis` 路由后，
 * 路由层可在本函数之上追加 `404 JOB_NOT_FOUND`、`422 ANALYSIS_FAILED` 等细分映射。
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
    // Java 5xx / Python 5xx → 503；其余非 2xx 在骨架阶段同样按「下游不可用」处理
    return AppError.serviceUnavailable(error.service);
  }

  return AppError.internal();
}
