package com.careerlens.jobservice.dto.response;

import com.fasterxml.jackson.annotation.JsonInclude;

/**
 * analyzer 能力探测响应（<b>入站 DTO</b>：下游 {@code GET /internal/capabilities} 的返回形状）。
 *
 * <p><b>与 {@link AnalyzerPingResponse} 的区别</b>：那个回答「通不通」，本 record 回答
 * 「通了能做什么」。二者刻意分成两个类型而不是给 ping 加字段 —— 探测的是两件不同的事，
 * 混在一起会让「链路可达但功能不可用」这种状态无处安放。
 *
 * <p>非契约接口（{@code /internal/**} 不对外），字段可自由演进；但仍用 {@code record}
 * 保证不可变。
 *
 * <p><b>唯一消费方</b>：{@code service.InternalService}。
 *
 * @param llmEnabled analyzer 的 LLM 是否启用（三项配置齐全）—— part3「深度分析」的开关证据。
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record AnalyzerCapabilitiesResponse(String service, boolean llmEnabled) {
}
