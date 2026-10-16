package com.careerlens.jobservice.dto.response;

import com.fasterxml.jackson.annotation.JsonInclude;

/**
 * 能力探测响应（<b>出站 DTO</b>，非契约接口）。
 *
 * <p>把「本跳的可达性 + 下游 analyzer 的能力」合并成一个扁平结构，供 BFF 直接透传给前端。
 * 前端据此决定要不要放开 part3 的「深度」分析。
 *
 * <p><b>为什么失败也用 200 表达</b>：与 {@link PingResponse} 同理 —— 探针的语义是
 * <b>报告状态</b>，不是执行用户请求。analyzer 不可达是一种**正常回报**（
 * {@code analyzerReachable=false}），把它变成 5xx 会让前端既拿不到「为什么不能深度分析」，
 * 又要额外处理一次错误。
 *
 * <p><b>{@code llmEnabled} 在失败时为 false</b>：能力未知时按「不可用」处理是唯一安全的方向 ——
 * 猜成 true 会让前端放开一个必然只能规则兜底的功能。
 *
 * @param analyzerReachable analyzer 是否可达
 * @param llmEnabled        analyzer 的 LLM 是否启用（analyzer 不可达时为 false）
 * @param error             仅不可达时出现：下游异常的<b>类名</b>（不带堆栈，spec.md §3.3）
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record CapabilitiesResponse(
        String service,
        boolean analyzerReachable,
        boolean llmEnabled,
        String error) {
}
