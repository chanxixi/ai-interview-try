package com.careerlens.jobservice.config.properties;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 应用配置（{@code careerlens.*}）。全部来自环境变量（见仓库根 .env.example），
 * 密钥绝不硬编码（spec.md §3.3）。
 *
 * <p><b>为什么单独一个 properties 子包</b>：{@code config/} 根下放「装配逻辑」
 * （{@code RestClientConfig}、T4 的 {@code StorageModeEnvironmentPostProcessor}），
 * 子包 {@code config/properties/} 放「配置数据本身」。两者变更频率与责任人不同：
 * 加一个配置项只动 properties，改装配方式才动 config 根。
 *
 * <p><b>超时</b>：{@code timeoutMs} 默认值对齐 plan.md §6.1 的超时矩阵；
 * 与 analyzer 侧、BFF 侧的超时是三条独立的线，不要混。
 *
 * @param analyzer 下游 analyzer 服务配置
 */
@ConfigurationProperties(prefix = "careerlens")
public record AppProperties(Analyzer analyzer) {

    /**
     * @param baseUrl   analyzer 基础地址，如 http://localhost:8000
     * @param timeoutMs 读超时（毫秒）；连接超时固定在
     *                  {@code RestClientConfig.CONNECT_TIMEOUT_MS}
     */
    public record Analyzer(String baseUrl, long timeoutMs) {
    }
}
