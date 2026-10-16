package com.careerlens.jobservice.service;

import com.careerlens.jobservice.client.AnalyzerClient;
import com.careerlens.jobservice.config.constants.TraceConstants;
import com.careerlens.jobservice.config.properties.AppProperties;
import com.careerlens.jobservice.dto.response.AnalyzerCapabilitiesResponse;
import com.careerlens.jobservice.dto.response.AnalyzerPingResponse;
import com.careerlens.jobservice.dto.response.CapabilitiesResponse;
import com.careerlens.jobservice.dto.response.PingResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

/**
 * 内部探针的业务编排。
 *
 * <p><b>职责边界</b>：组装「本跳信息 + 下游一跳结果」，并决定下游失败时怎么表达。
 * 不碰 HTTP（没有 {@code HttpServletRequest}、没有 {@code ResponseEntity}），
 * 因此换成 CLI 或队列消费者时本类可原样复用 —— 这正是判断「某段逻辑该不该在
 * Service」的判据（指南 §5.3 原则 2）。
 *
 * <p><b>为什么容错在这里而不在 client</b>：{@code AnalyzerClient} 只负责「把请求发出去」，
 * 它的契约是「失败就抛异常」；「失败要不要吞掉、以什么形状对外表达」是业务决策。
 * 放在 client 里会让适配器承担策略，放在 Controller 里会让 HTTP 层承担业务。
 *
 * <p><b>为什么不抽接口</b>：本类只有一个实现，且测试可直接 {@code new} 出来
 * （构造器参数全是普通类型）。接口的价值在于「多实现」或「跨模块解耦」，
 * 无差别给每个 Service 加接口只会增加一层样板。真正需要接口的是
 * {@code repository/}（ADR-007：mysql / local / mock 三选一）。
 *
 * <p><b>唯一调用方</b>：{@code controller.internal.InternalController}。
 */
@Service
public class InternalService {

    private static final Logger log = LoggerFactory.getLogger(InternalService.class);

    /** 下游服务名常量：只用于探针输出的展示字段，与真实服务名解耦。 */
    private static final String DOWNSTREAM_NAME = "analyzer";

    private final AnalyzerClient analyzerClient;
    private final AppProperties properties;
    private final String serviceName;

    public InternalService(AnalyzerClient analyzerClient,
                           AppProperties properties,
                           @Value("${spring.application.name}") String serviceName) {
        this.analyzerClient = analyzerClient;
        this.properties = properties;
        this.serviceName = serviceName;
    }

    /**
     * 本跳 + 下游一跳的探测结果。
     *
     * <p>无论下游是否可用，本方法都返回 200 与完整结构 —— 探针的语义是「报告链路状态」，
     * 不是「执行用户请求」，所以下游挂了也不该让探针本身失败。
     */
    public PingResponse ping() {
        String traceId = MDC.get(TraceConstants.MDC_KEY);
        log.info("ping received");

        return new PingResponse(
                serviceName,
                "ok",
                properties.version(),
                "java " + System.getProperty("java.version"),
                traceId,
                probeAnalyzer(traceId));
    }

    /**
     * 探测下游 analyzer。下游不可用时<b>不抛出</b>，而是把状态标为 {@code down} ——
     * 这样链路诊断能定位到具体是哪一跳断了（这是探针存在的意义）。
     */
    private PingResponse.Downstream probeAnalyzer(String traceId) {
        try {
            AnalyzerPingResponse response = analyzerClient.ping(traceId);
            return new PingResponse.Downstream(
                    DOWNSTREAM_NAME,
                    "ok",
                    response.version(),
                    response.runtime(),
                    response.traceId(),
                    null);
        } catch (Exception e) {
            log.warn("analyzer unreachable: {}", e.getMessage());
            // 只回传异常类名：探针响应会出现在前端自检面板上，不透传堆栈（spec.md §3.3）
            return new PingResponse.Downstream(
                    DOWNSTREAM_NAME,
                    "down",
                    null,
                    null,
                    null,
                    e.getClass().getSimpleName());
        }
    }

    /**
     * 能力探测：把 analyzer 的「能做什么」透传给上游，供前端决定是否放开 part3 的「深度」分析。
     *
     * <p><b>与 {@link #ping()} 同一容错取向</b>：analyzer 不可达时**不抛出**，
     * 而是回报 {@code analyzerReachable=false} 且 {@code llmEnabled=false}。
     * 能力未知时按「不可用」处理是唯一安全的方向 —— 猜成 available 会让前端
     * 放开一个必然只能规则兜底的功能（用户会把兜底结果误认为 AI 产出）。
     */
    public CapabilitiesResponse capabilities() {
        String traceId = MDC.get(TraceConstants.MDC_KEY);
        log.info("capabilities probed");

        try {
            AnalyzerCapabilitiesResponse response = analyzerClient.capabilities(traceId);
            return new CapabilitiesResponse(serviceName, true, response.llmEnabled(), null);
        } catch (Exception e) {
            log.warn("analyzer capabilities unreachable: {}", e.getMessage());
            return new CapabilitiesResponse(serviceName, false, false, e.getClass().getSimpleName());
        }
    }
}
