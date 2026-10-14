package com.careerlens.jobservice.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 应用配置。全部来自环境变量（见仓库根 .env.example），密钥绝不硬编码（spec.md §3.3）。
 *
 * @param analyzer 下游 analyzer 服务配置
 */
@ConfigurationProperties(prefix = "careerlens")
public record AppProperties(Analyzer analyzer) {

    /**
     * @param baseUrl    analyzer 基础地址，如 http://localhost:8000
     * @param timeoutMs  读超时，默认对齐 plan.md §6.1 的超时矩阵
     */
    public record Analyzer(String baseUrl, long timeoutMs) {
    }
}
