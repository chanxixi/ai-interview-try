package com.careerlens.jobservice.web;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.careerlens.jobservice.client.AnalyzerClient;
import com.careerlens.jobservice.controller.internal.InternalController;
import com.careerlens.jobservice.dto.response.AnalyzerPingResponse;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.test.web.servlet.MockMvc;

/**
 * {@code /internal/ping} 的<b>响应形状快照</b>。
 *
 * <p>为什么单独测这个接口：它是前端「链路自检面板」的数据源，
 * 形状一变前端就白屏。本用例把「成功/失败两种形态各含哪些字段」
 * 写死成断言 —— 出站 DTO 改动导致形状漂移时，这里会先红。
 *
 * <p>打桩点选在最外层适配器 {@link AnalyzerClient}：Controller 跑真实实现，
 * 因此断言通过 = 真实响应形状正确（与 P1 同一套证明手段）。
 */
@WebMvcTest(InternalController.class)
class InternalControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @MockBean
    private AnalyzerClient analyzerClient;

    @Test
    void pingIncludesDownstreamDetailWhenAnalyzerIsUp() throws Exception {
        when(analyzerClient.ping(any())).thenReturn(
                new AnalyzerPingResponse("analyzer", "ok", "0.1.0", "python 3.13.14", "trace-up"));

        mockMvc.perform(get("/internal/ping").header("X-Trace-Id", "trace-up"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.service").value("job-service"))
                .andExpect(jsonPath("$.status").value("ok"))
                .andExpect(jsonPath("$.version").exists())
                .andExpect(jsonPath("$.runtime").exists())
                .andExpect(jsonPath("$.traceId").value("trace-up"))
                .andExpect(jsonPath("$.downstream.service").value("analyzer"))
                .andExpect(jsonPath("$.downstream.status").value("ok"))
                .andExpect(jsonPath("$.downstream.runtime").value("python 3.13.14"))
                .andExpect(jsonPath("$.downstream.traceId").value("trace-up"))
                // 成功时不得出现 error 字段（NON_NULL 的语义保证）
                .andExpect(jsonPath("$.downstream.error").doesNotExist());
    }

    @Test
    void pingMarksDownstreamDownAndHidesStackTraceWhenAnalyzerFails() throws Exception {
        when(analyzerClient.ping(any()))
                .thenThrow(new ResourceAccessException("connection refused"));

        mockMvc.perform(get("/internal/ping"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("ok"))
                .andExpect(jsonPath("$.downstream.status").value("down"))
                // 只暴露异常类名，不透传堆栈（spec.md §3.3）
                .andExpect(jsonPath("$.downstream.error").value("ResourceAccessException"))
                .andExpect(jsonPath("$.downstream.version").doesNotExist())
                .andExpect(jsonPath("$.downstream.runtime").doesNotExist());
    }
}
