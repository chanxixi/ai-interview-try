package com.careerlens.jobservice.controller.internal;

import com.careerlens.jobservice.dto.response.PingResponse;
import com.careerlens.jobservice.service.InternalService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 内部探针 —— 统一 {@code /internal} 前缀，语义上标明「不对外」（plan.md §3.3）。
 *
 * <p>job-service 是链路上的第三跳，负责把请求继续交给 analyzer，
 * 从而证明 {@code Vue → BFF → job-service → analyzer} 全链可达。
 *
 * <p><b>职责边界</b>：只做 HTTP 接线。探什么、失败怎么表达，全在
 * {@link InternalService}。本类没有任何 {@code try/catch} 与 {@code if} ——
 * 一旦出现，说明有业务逻辑漏在了这一层（指南 §3.2）。
 *
 * <p><b>唯一调用方</b>：Spring MVC 路由分发。
 */
@RestController
@RequestMapping("/internal")
public class InternalController {

    private final InternalService internalService;

    public InternalController(InternalService internalService) {
        this.internalService = internalService;
    }

    @GetMapping("/ping")
    public PingResponse ping() {
        return internalService.ping();
    }
}
