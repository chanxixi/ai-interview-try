package com.careerlens.jobservice.web;

import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.careerlens.jobservice.controller.internal.InternalController;
import com.careerlens.jobservice.dto.response.CapabilitiesResponse;
import com.careerlens.jobservice.dto.response.PingResponse;
import com.careerlens.jobservice.service.InternalService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.test.web.servlet.MockMvc;

/**
 * {@code /internal/ping} 的<b>HTTP 层契约快照</b>。
 *
 * <p>本类只回答一个问题：Service 给出的结论，有没有被原样序列化成前端期望的形状？
 * 因此打桩点在 {@link InternalService}（Controller 的上游），
 * 而<b>编排逻辑本身</b>由 {@code unit.service.InternalServiceTest} 覆盖。
 *
 * <p>两层的分工：这里测「序列化与路径」，那里测「容错与字段组装」。
 * 分开的好处是任何一边坏了都能立刻指出坏在哪一层。
 */
@WebMvcTest(InternalController.class)
class InternalControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @MockBean
    private InternalService internalService;

    @Test
    void pingSerializesDownstreamDetailWhenAnalyzerIsUp() throws Exception {
        when(internalService.ping()).thenReturn(new PingResponse(
                "job-service", "ok", "0.1.0", "java 17.0.2", "trace-up",
                new PingResponse.Downstream("analyzer", "ok", "0.1.0", "python 3.13.14", "trace-up", null)));

        mockMvc.perform(get("/internal/ping").header("X-Trace-Id", "trace-up"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.service").value("job-service"))
                .andExpect(jsonPath("$.status").value("ok"))
                .andExpect(jsonPath("$.downstream.service").value("analyzer"))
                .andExpect(jsonPath("$.downstream.status").value("ok"))
                .andExpect(jsonPath("$.downstream.runtime").value("python 3.13.14"))
                // 成功时不得出现 error 字段（NON_NULL 的语义保证）
                .andExpect(jsonPath("$.downstream.error").doesNotExist());
    }

    @Test
    void pingSerializesDownstreamFailureWithoutHalfEmptyFields() throws Exception {
        when(internalService.ping()).thenReturn(new PingResponse(
                "job-service", "ok", "0.1.0", "java 17.0.2", "trace-down",
                new PingResponse.Downstream("analyzer", "down", null, null, null, "ResourceAccessException")));

        mockMvc.perform(get("/internal/ping"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.downstream.status").value("down"))
                // 只暴露异常类名，不透传堆栈（spec.md §3.3）
                .andExpect(jsonPath("$.downstream.error").value("ResourceAccessException"))
                .andExpect(jsonPath("$.downstream.version").doesNotExist())
                .andExpect(jsonPath("$.downstream.runtime").doesNotExist());
    }

    @Test
    void capabilitiesSerializesAnalyzerCapabilityWhenUp() throws Exception {
        when(internalService.capabilities()).thenReturn(
                new CapabilitiesResponse("job-service", true, true, null));

        mockMvc.perform(get("/internal/capabilities"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.service").value("job-service"))
                .andExpect(jsonPath("$.analyzerReachable").value(true))
                .andExpect(jsonPath("$.llmEnabled").value(true))
                // 可达时不得出现 error 字段（NON_NULL 的语义保证）
                .andExpect(jsonPath("$.error").doesNotExist());
    }

    @Test
    void capabilitiesSerializesUnreachableWithoutLeakingStack() throws Exception {
        when(internalService.capabilities()).thenReturn(
                new CapabilitiesResponse("job-service", false, false, "ResourceAccessException"));

        mockMvc.perform(get("/internal/capabilities"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.analyzerReachable").value(false))
                // 未知能力一律按不可用回报，避免前端放开只能规则兜底的功能
                .andExpect(jsonPath("$.llmEnabled").value(false))
                .andExpect(jsonPath("$.error").value("ResourceAccessException"));
    }
}
