package com.careerlens.jobservice.web;

import com.careerlens.jobservice.client.AnalyzerClient;
import com.careerlens.jobservice.dto.PingResponse;
import java.util.LinkedHashMap;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 内部接口 —— 统一 /internal 前缀，语义上标明「不对外」（plan.md §3.3）。
 *
 * <p>骨架阶段的连通性探针：job-service 是链路上的第三跳，
 * 负责把请求继续交给 analyzer，从而证明 Vue → BFF → job-service → analyzer 全链可达。
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
    public Map<String, Object> ping() {
        String traceId = MDC.get(TraceIdFilter.MDC_KEY);
        log.info("ping received");

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("service", serviceName);
        result.put("status", "ok");
        result.put("version", version);
        result.put("runtime", "java " + System.getProperty("java.version"));
        result.put("traceId", traceId);
        result.put("downstream", pingAnalyzer(traceId));
        return result;
    }

    /**
     * 探测下游 analyzer。下游不可用时不抛出，而是把状态标为 down ——
     * 这样链路诊断能定位到具体是哪一跳断了。
     */
    private Map<String, Object> pingAnalyzer(String traceId) {
        Map<String, Object> downstream = new LinkedHashMap<>();
        downstream.put("service", "analyzer");
        try {
            PingResponse response = analyzerClient.ping(traceId);
            downstream.put("status", "ok");
            downstream.put("version", response.version());
            downstream.put("runtime", response.runtime());
            downstream.put("traceId", response.traceId());
        } catch (Exception e) {
            log.warn("analyzer unreachable: {}", e.getMessage());
            downstream.put("status", "down");
            downstream.put("error", e.getClass().getSimpleName());
        }
        return downstream;
    }
}
