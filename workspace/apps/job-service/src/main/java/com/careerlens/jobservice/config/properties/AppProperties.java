package com.careerlens.jobservice.config.properties;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

/**
 * 应用配置（{@code careerlens.*}）。全部来自环境变量（见仓库根 .env.example），
 * 密钥绝不硬编码（spec.md §3.3）。
 *
 * <p><b>为什么单独一个 properties 子包</b>：{@code config/} 根下放「装配逻辑」
 * （{@code RestClientConfig}、T4 的 {@code StorageModeEnvironmentPostProcessor}），
 * 子包 {@code config/properties/} 放「配置数据本身」。两者变更频率与责任人不同：
 * 加一个配置项只动 properties，改装配方式才动 config 根。
 *
 * <p><b>为什么用 record 而不是 @Value 散落各处</b>：类型安全 + 启动即校验 +
 * Service 层构造器只接普通类型（原则 3：Service 不依赖框架类型）。
 *
 * @param version  服务版本号，探针接口回显用；{@code @DefaultValue} 保证 yml 缺省时也能装配
 * @param analyzer 下游 analyzer 服务配置
 */
@ConfigurationProperties(prefix = "careerlens")
public record AppProperties(
        @DefaultValue("0.1.0") String version,
        Analyzer analyzer) {

    /**
     * @param baseUrl   analyzer 基础地址，如 http://localhost:8000
     * @param timeoutMs 读超时（毫秒）；连接超时固定在
     *                  {@code RestClientConfig.CONNECT_TIMEOUT_MS}
     */
    public record Analyzer(String baseUrl, long timeoutMs) {
    }
}
