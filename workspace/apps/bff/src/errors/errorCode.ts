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
] as const;

export type ErrorCode = (typeof ERROR_CODES)[number];
