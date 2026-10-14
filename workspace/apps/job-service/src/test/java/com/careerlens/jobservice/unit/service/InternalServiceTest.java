package com.careerlens.jobservice.unit.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.careerlens.jobservice.client.AnalyzerClient;
import com.careerlens.jobservice.config.constants.TraceConstants;
import com.careerlens.jobservice.config.properties.AppProperties;
import com.careerlens.jobservice.dto.response.AnalyzerPingResponse;
import com.careerlens.jobservice.dto.response.PingResponse;
import com.careerlens.jobservice.service.InternalService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.slf4j.MDC;
import org.springframework.web.client.ResourceAccessException;

/**
 * {@link InternalService} 的单元测试 —— <b>不起 Spring 容器</b>。
 *
 * <p>这一点本身就是一条设计断言：如果 Service 里混进了 {@code HttpServletRequest}
 * 或 {@code ResponseEntity}，这个测试根本写不出来（指南 §5.3 原则 3）。
 * 构造器参数全是普通类型，所以直接 {@code new} 即可。
 *
 * <p>打桩点在 {@link AnalyzerClient}（最外层适配器），Service 跑真实实现。
 */
class InternalServiceTest {

    private static final AppProperties PROPERTIES = new AppProperties(
            "0.1.0", new AppProperties.Analyzer("http://localhost:8000", 45000));

    @AfterEach
    void clearMdc() {
        MDC.clear();
    }

    @Test
    void pingReportsDownstreamDetailWhenAnalyzerIsUp() {
        AnalyzerClient client = mock(AnalyzerClient.class);
        when(client.ping(any())).thenReturn(
                new AnalyzerPingResponse("analyzer", "ok", "0.1.0", "python 3.13.14", "trace-1"));

        PingResponse result = new InternalService(client, PROPERTIES, "job-service").ping();

        assertThat(result.service()).isEqualTo("job-service");
        assertThat(result.status()).isEqualTo("ok");
        assertThat(result.version()).isEqualTo("0.1.0");
        assertThat(result.downstream().status()).isEqualTo("ok");
        assertThat(result.downstream().runtime()).isEqualTo("python 3.13.14");
        assertThat(result.downstream().error()).isNull();
    }

    /**
     * 核心容错契约：<b>下游挂了，探针本身依然返回 ok</b>。
     *
     * <p>否则「链路断在第几跳」就无从判断 —— 探针的语义是报告状态，不是执行用户请求。
     */
    @Test
    void pingDegradesToDownStatusWhenAnalyzerThrows() {
        AnalyzerClient client = mock(AnalyzerClient.class);
        when(client.ping(any())).thenThrow(new ResourceAccessException("connection refused"));

        PingResponse result = new InternalService(client, PROPERTIES, "job-service").ping();

        assertThat(result.status()).isEqualTo("ok");
        assertThat(result.downstream().status()).isEqualTo("down");
        // 只暴露类名，不带 message/堆栈
        assertThat(result.downstream().error()).isEqualTo("ResourceAccessException");
        assertThat(result.downstream().version()).isNull();
        assertThat(result.downstream().runtime()).isNull();
    }

    /** traceId 必须透传给下游，否则全链日志无法按 traceId 串起来（spec.md §2.8）。 */
    @Test
    void pingPropagatesTraceIdFromMdcToDownstream() {
        MDC.put(TraceConstants.MDC_KEY, "trace-xyz");
        AnalyzerClient client = mock(AnalyzerClient.class);
        when(client.ping(any())).thenReturn(
                new AnalyzerPingResponse("analyzer", "ok", "0.1.0", "python 3.13.14", "trace-xyz"));

        PingResponse result = new InternalService(client, PROPERTIES, "job-service").ping();

        assertThat(result.traceId()).isEqualTo("trace-xyz");
        verify(client).ping("trace-xyz");
    }
}
