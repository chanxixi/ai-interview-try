package com.careerlens.jobservice.controller.internal;

import com.careerlens.jobservice.client.AnalyzerClient;
import com.careerlens.jobservice.config.constants.TraceConstants;
import com.careerlens.jobservice.dto.response.AnalyzerPingResponse;
import com.careerlens.jobservice.dto.response.PingResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 内部探针 —— 统一 {@code /internal} 前缀，语义上标明「不对外」（plan.md §3.3）。
 *
 * <p>job-service 是链路上的第三跳，负责把请求继续交给 analyzer，
 * 从而证明 {@code Vue → BFF → job-service → analyzer} 全链可达。
 *
 * <p><b>职责边界</b>：只做 HTTP 接线 + 组装出站 DTO。
 * 「下游失败怎么处理」属于容错策略 —— P2-4 会把它移到 service 层
 * （当前仍内联在本类，属于本次重构的中间态）。
 *
 * <p><b>唯一调用方</b>：Spring MVC 路由分发。
 */
@RestController
@RequestMapping("/internal")
public class InternalController {

    private static final Logger log = LoggerFactory.getLogger(InternalController.class);

    private final AnalyzerClient analyzerClient;
    private final String serviceName;
    private final String version;

    public InternalController(AnalyzerClient analyzerClient,
                              @Value("${spring.application.name}") String serviceName,
                              @Value("${careerlens.version:0.1.0}") String version) {
        this.analyzerClient = analyzerClient;
        this.serviceName = serviceName;
        this.version = version;
    }

    @GetMapping("/ping")
    public PingResponse ping() {
        String traceId = MDC.get(TraceConstants.MDC_KEY);
        log.info("ping received");

        return new PingResponse(
                serviceName,
                "ok",
                version,
                "java " + System.getProperty("java.version"),
                traceId,
                pingAnalyzer(traceId));
    }

    /**
     * 探测下游 analyzer。下游不可用时不抛出，而是把状态标为 down ——
     * 这样链路诊断能定位到具体是哪一跳断了。
     */
    private PingResponse.Downstream pingAnalyzer(String traceId) {
        try {
            AnalyzerPingResponse response = analyzerClient.ping(traceId);
            return new PingResponse.Downstream(
                    "analyzer",
                    "ok",
                    response.version(),
                    response.runtime(),
                    response.traceId(),
                    null);
        } catch (Exception e) {
            log.warn("analyzer unreachable: {}", e.getMessage());
            // 只回传异常类名：探针响应可能出现在前端面板上，不透传堆栈（spec.md §3.3）
            return new PingResponse.Downstream(
                    "analyzer",
                    "down",
                    null,
                    null,
                    null,
                    e.getClass().getSimpleName());
        }
    }
}
