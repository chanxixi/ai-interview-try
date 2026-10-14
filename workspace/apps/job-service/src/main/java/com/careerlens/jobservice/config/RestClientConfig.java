package com.careerlens.jobservice.config;

import com.careerlens.jobservice.config.properties.AppProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.RestClient;

/**
 * 下游调用配置。
 *
 * <p>所有外部调用必须有超时（spec.md §3.3 禁止无超时的外部调用）。
 */
@Configuration
public class RestClientConfig {

    private static final int CONNECT_TIMEOUT_MS = 2000;

    @Bean
    public RestClient analyzerRestClient(AppProperties properties) {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(CONNECT_TIMEOUT_MS);
        factory.setReadTimeout((int) properties.analyzer().timeoutMs());

        return RestClient.builder()
                .baseUrl(properties.analyzer().baseUrl())
                .requestFactory(factory)
                .build();
    }
}
