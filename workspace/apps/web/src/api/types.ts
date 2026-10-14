/**
 * 与 BFF 的接口类型 —— 形状对齐 spec.md §2.8（traceId）与 BFF 的 `/api/ping` 响应。
 *
 * 前端不定义业务规则，只描述「客户端要什么形状」（plan.md §1.2）。
 */

/** 每一跳的探针结果；`downstream` 递归挂载自己的下游。 */
export interface PingResult {
  service: string;
  status: 'ok' | 'down';
  version?: string;
  runtime?: string;
  traceId?: string | null;
  error?: string;
  downstream?: PingResult;
}

/** 统一错误响应体（spec.md §2.3）。 */
export interface ApiErrorBody {
  code: string;
  message: string;
  traceId?: string;
}
