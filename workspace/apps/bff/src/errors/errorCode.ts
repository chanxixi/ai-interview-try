/**
 * 错误码表 —— spec.md §2.3（冻结）。
 *
 * ⚠️ 新增 / 修改错误码必须走 `spec.md` §6 变更记录，不得在代码里就地扩展。
 *
 * 溯源：这里定义的每个 code 都必须是「HTTP 状态码 + code」的合法组合；
 *      组合关系见 `appError.ts` 的静态工厂，映射来源见 `mapUpstream.ts`。
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
  // ---- part2 新增（part2 spec.md §2.5 / tasks.md M6.5）：上传准入的两个同步错误 ----
  // 它们只出现在**建流之前**：大小 / MIME / magic number 都是「读一下就知道」的判定；
  // 而损坏 / 加密 / 无文本层 / 页数必须等 Python 读完文件才知道，走 SSE error 事件。
  'FILE_TOO_LARGE',
  'UNSUPPORTED_FILE_TYPE',
  // 客户端提前断开。spec.md §2.5 明确它**仅日志**，不进响应体 ——
  // 收在这里只是为了让日志里的 code 与契约表对得上，避免各写各的。
  'STREAM_ABORTED',
] as const;

export type ErrorCode = (typeof ERROR_CODES)[number];
