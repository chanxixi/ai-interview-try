/**
 * 能力探测 DTO —— 对齐 job-service 的 `GET /internal/capabilities`（BFF → Java 一跳）。
 *
 * 与 `ping.response.ts` 的分工：ping 回答「通不通」，本文件回答「通了能做什么」。
 * 二者刻意分成两个 DTO：混在一起会让「链路可达但功能不可用」这种状态无处安放。
 */

/** job-service 返回的形状（非契约内部接口，字段可演进）。 */
export interface UpstreamCapabilities {
  service: string;
  /** analyzer 是否可达 */
  analyzerReachable: boolean;
  /** analyzer 的 LLM 是否启用（不可达时为 false） */
  llmEnabled: boolean;
  /** 仅不可达时出现：下游异常的类名（不透传堆栈，spec.md §3.3） */
  error?: string;
}

/**
 * BFF `GET /api/capabilities` 的响应 —— 只暴露前端决策所需的**最小事实**。
 *
 * 前端据此决定要不要放开 part3 的「深度」分析。判据是**两个条件的合取**：
 * `llmEnabled && analyzerReachable` —— 深度需要 LLM，而 LLM 在 analyzer 上。
 */
export interface CapabilitiesResult {
  llmEnabled: boolean;
  analyzerReachable: boolean;
}
