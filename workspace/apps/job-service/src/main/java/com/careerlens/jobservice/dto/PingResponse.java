package com.careerlens.jobservice.dto;

import com.fasterxml.jackson.annotation.JsonInclude;

/** analyzer 连通性探针响应（对应 analyzer 的 GET /internal/ping）。 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record PingResponse(
        String service,
        String status,
        String version,
        String runtime,
        String traceId) {
}
