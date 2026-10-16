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

/**
 * `GET /api/capabilities` 响应（part3）。
 *
 * 前端据此决定要不要放开「深度」分析：判据是 **`llmEnabled && analyzerReachable`**。
 * 深度需要 LLM，而 LLM 在 analyzer 上 —— 两个条件缺一不可。
 */
export interface CapabilitiesResult {
  llmEnabled: boolean;
  analyzerReachable: boolean;
}

/**
 * 「深度」入口的**三态** —— `CapabilitiesResult` 的界面投影。
 *
 * 为什么不直接用布尔：**「能不能选」与「默认选哪个」是两个问题**，
 * 压成一个布尔必然有一边出错 ——
 *   - 默认 `deep`：探测失败时会白等两次 LLM 往返；
 *   - 默认 `standard`：违背「有 LLM 就用 LLM」。
 * 三态把「未知」单独拎出来，两者才能各自取到对的默认值。
 */
export type DeepCapability = 'available' | 'unknown' | 'unavailable';

/** `null`（探测未回来 / 探测失败）→ `unknown`：放行但**不预置 deep**（不猜）。 */
export function toDeepCapability(capabilities: CapabilitiesResult | null): DeepCapability {
  if (capabilities === null) return 'unknown';
  return capabilities.llmEnabled && capabilities.analyzerReachable ? 'available' : 'unavailable';
}
