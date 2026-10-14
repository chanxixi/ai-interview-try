package com.careerlens.jobservice.dto.response;

import com.fasterxml.jackson.annotation.JsonInclude;

/**
 * analyzer 连通性探针响应（<b>入站 DTO</b>：下游 {@code GET /internal/ping} 的返回形状）。
 *
 * <p><b>为什么放在 dto/response/ 而不留在 client/ 里</b>：响应形状属于契约，
 * 与「怎么调用」是两件事。混住在 client 里会导致适配器一改就要动契约类型
 * （指南 §3.2 反模式「DTO 与适配器混住」）。
 *
 * <p>非契约接口（{@code /internal/**} 不对外），字段可自由演进；
 * 但仍用 {@code record} 保证不可变。
 *
 * <p><b>唯一消费方</b>：{@code service.InternalService}。
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record AnalyzerPingResponse(
        String service,
        String status,
        String version,
        String runtime,
        String traceId) {
}
