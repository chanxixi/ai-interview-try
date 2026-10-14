package com.careerlens.jobservice.client;

import com.careerlens.jobservice.dto.PingResponse;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

/**
 * analyzer 下游客户端。
 *
 * <p>链路位置：job-service → analyzer。本层只做调用与编排，不做文本算法（spec.md §2.6）。
 */
@Component
public class AnalyzerClient {

    private static final String TRACE_ID_HEADER = "X-Trace-Id";

    private final RestClient restClient;

    public AnalyzerClient(RestClient analyzerRestClient) {
        this.restClient = analyzerRestClient;
    }

    /** 连通性探针，透传 traceId 以验证全链贯穿。 */
    public PingResponse ping(String traceId) {
        return restClient.get()
                .uri("/internal/ping")
                .header(TRACE_ID_HEADER, traceId)
                .retrieve()
                .body(PingResponse.class);
    }
}
