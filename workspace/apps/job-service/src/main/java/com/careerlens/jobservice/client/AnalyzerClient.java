package com.careerlens.jobservice.client;

import com.careerlens.jobservice.config.constants.TraceConstants;
import com.careerlens.jobservice.dto.response.AnalyzerCapabilitiesResponse;
import com.careerlens.jobservice.dto.response.AnalyzerPingResponse;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

/**
 * analyzer 下游客户端（<b>出站适配器</b>）。
 *
 * <p><b>职责边界</b>：只做「把请求发出去、把响应拿回来」。
 * 不做文本算法、不做降级决策、不做业务判断（spec.md §2.6）——
 * 降级与容错由 service 层决定（见 {@code service.InternalService}）。
 *
 * <p><b>超时</b>：由 {@code config.RestClientConfig} 在装配期统一设置
 * （spec.md §3.3 禁止无超时的外部调用）。
 *
 * <p><b>traceId</b>：必须透传，否则全链日志无法按 traceId 串起来（spec.md §2.8）。
 *
 * <p><b>唯一调用方</b>：{@code service} 层。
 */
@Component
public class AnalyzerClient {

    private final RestClient restClient;

    public AnalyzerClient(RestClient analyzerRestClient) {
        this.restClient = analyzerRestClient;
    }

    /** 连通性探针，透传 traceId 以验证全链贯穿。 */
    public AnalyzerPingResponse ping(String traceId) {
        return restClient.get()
                .uri("/internal/ping")
                .header(TraceConstants.TRACE_ID_HEADER, traceId)
                .retrieve()
                .body(AnalyzerPingResponse.class);
    }

    /** 能力探测：询问 analyzer「链路可达之后还能做什么」（part3：LLM 是否启用）。 */
    public AnalyzerCapabilitiesResponse capabilities(String traceId) {
        return restClient.get()
                .uri("/internal/capabilities")
                .header(TraceConstants.TRACE_ID_HEADER, traceId)
                .retrieve()
                .body(AnalyzerCapabilitiesResponse.class);
    }
}
