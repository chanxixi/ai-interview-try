package com.careerlens.jobservice.controller.health;

import com.careerlens.jobservice.dto.response.HealthResponse;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 健康检查 —— spec.md §2.8 要求每个服务暴露 {@code GET /healthz}。
 *
 * <p><b>职责边界</b>：只做「把 service 层的结论变成 HTTP 响应」。
 * 不写业务判断、不碰 Repository（指南 §3.2 反模式）。
 *
 * <p><b>为什么不叫 actuator</b>：题目要求所有服务统一暴露 {@code /healthz}
 * （BFF 与 Python 侧同样如此），用 Spring Actuator 会让三个服务的探针形状不一致，
 * 也会给 compose 的 healthcheck 引入额外依赖。
 *
 * <p><b>唯一调用方</b>：Spring MVC 路由分发。
 */
@RestController
public class HealthController {

    private final String serviceName;

    public HealthController(@Value("${spring.application.name}") String serviceName) {
        this.serviceName = serviceName;
    }

    @GetMapping("/healthz")
    public HealthResponse healthz() {
        return HealthResponse.ok(serviceName);
    }
}
