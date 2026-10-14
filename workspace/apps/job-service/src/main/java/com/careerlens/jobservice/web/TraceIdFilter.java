package com.careerlens.jobservice.web;

import com.careerlens.jobservice.config.constants.TraceConstants;
import jakarta.servlet.Filter;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.ServletRequest;
import jakarta.servlet.ServletResponse;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.UUID;
import org.slf4j.MDC;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;

/**
 * traceId 贯穿（spec.md §2.8）。
 *
 * <p>读取上游传入的 {@code X-Trace-Id}，缺失则自行生成，写入 MDC 供日志使用，
 * 并回写到响应头以便调用方核对。
 *
 * <p><b>为什么是 Filter 而不是 Interceptor</b>：Filter 在 Servlet 层，能覆盖到
 * 静态资源、错误转发等 Interceptor 触达不到的路径，且 {@code @Order(HIGHEST_PRECEDENCE)}
 * 保证它是第一个写 MDC 的组件 —— 后续任何日志（含异常收口）都带得上 traceId。
 *
 * <p><b>header 名与 MDC key 的唯一来源</b>：{@link TraceConstants}（此处不重复定义）。
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class TraceIdFilter implements Filter {

    @Override
    public void doFilter(ServletRequest request, ServletResponse response, FilterChain chain)
            throws IOException, ServletException {

        HttpServletRequest httpRequest = (HttpServletRequest) request;
        HttpServletResponse httpResponse = (HttpServletResponse) response;

        String traceId = httpRequest.getHeader(TraceConstants.TRACE_ID_HEADER);
        if (traceId == null || traceId.isBlank()) {
            traceId = UUID.randomUUID().toString();
        }

        MDC.put(TraceConstants.MDC_KEY, traceId);
        httpResponse.setHeader(TraceConstants.TRACE_ID_HEADER, traceId);

        try {
            chain.doFilter(request, response);
        } finally {
            // 线程池复用线程，必须清理，否则下一个请求会串上上一个请求的 traceId
            MDC.remove(TraceConstants.MDC_KEY);
        }
    }
}
