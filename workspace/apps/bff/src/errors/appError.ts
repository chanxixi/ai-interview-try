import type { ErrorCode } from './errorCode';

/**
 * 错误类型定义（spec.md §2.3）。
 *
 * 三个类各司其职，**不要合并**：
 *   - `AppError`              面向客户端的错误：已确定 status + code，可直接写进响应体
 *   - `UpstreamTransportError` 传输层故障（连不上 / 超时 / 响应不是 JSON）：还不知道该报什么 code
 *   - `UpstreamStatusError`    下游返回非 2xx：拿到状态码但还不知道业务语义
 *
 * 后两者由 `mapUpstream.ts` 翻译成 `AppError`，翻译发生在 errorHandler（唯一的收口点）。
 */

/** 面向客户端的业务错误。status + code 的组合必须在 spec.md §2.3 表内。 */
export class AppError extends Error {
  constructor(
    readonly status: number,
    readonly code: ErrorCode,
    message: string,
  ) {
    super(message);
    this.name = 'AppError';
  }

  static invalidInput(message = '请求参数校验失败'): AppError {
    return new AppError(400, 'INVALID_INPUT', message);
  }

  static resumeTooLong(max = 20000): AppError {
    return new AppError(400, 'RESUME_TOO_LONG', `简历文本不能超过 ${max} 字符`);
  }

  static jobNotFound(id: string): AppError {
    return new AppError(404, 'JOB_NOT_FOUND', `岗位不存在：${id}`);
  }

  static analysisFailed(): AppError {
    return new AppError(422, 'ANALYSIS_FAILED', '分析失败，请稍后重试');
  }

  static rateLimited(): AppError {
    return new AppError(429, 'RATE_LIMITED', '请求过于频繁，请稍后重试');
  }

  static upstreamTimeout(service: string): AppError {
    return new AppError(504, 'UPSTREAM_TIMEOUT', `下游服务 ${service} 响应超时`);
  }

  /**
   * part2：上传文件超过上限。HTTP 413（part2 spec.md §2.5）。
   *
   * **必须在建流之前抛出** —— 一旦 SSE 头已经写出去，就只能靠 error 事件，
   * 而 413 属于「客户端能直接修正」的错误，同步返回体验好得多（AC13）。
   */
  static fileTooLarge(maxMb = 10): AppError {
    return new AppError(413, 'FILE_TOO_LARGE', `上传文件超过 ${maxMb} MB 上限`);
  }

  /**
   * part2：文件类型不支持。HTTP 415（part2 spec.md §2.5）。
   *
   * 判据是 **magic number**（前 5 字节必须 `%PDF-`）而不是扩展名 ——
   * MIME 与扩展名都是客户端给的，可以伪造（AC12 就是把 docx 改名成 .pdf 传上来）。
   */
  static unsupportedFileType(reason = '仅接受 PDF 文件'): AppError {
    return new AppError(415, 'UNSUPPORTED_FILE_TYPE', reason);
  }

  static serviceUnavailable(service: string): AppError {
    return new AppError(503, 'SERVICE_UNAVAILABLE', `下游服务 ${service} 暂时不可用`);
  }

  static internal(): AppError {
    return new AppError(500, 'INTERNAL_ERROR', '服务内部错误');
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
