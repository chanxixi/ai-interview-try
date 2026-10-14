package com.careerlens.jobservice;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;

/**
 * CareerLens job-service —— 面向领域的稳定层。
 *
 * <p>职责（spec.md §2.6）：岗位 JD / 技能词典领域 API、DTO 契约、服务编排、持久化。
 * 禁止：文本算法、直接调用 LLM。
 */
@SpringBootApplication
@ConfigurationPropertiesScan
public class JobServiceApplication {

    public static void main(String[] args) {
        SpringApplication.run(JobServiceApplication.class, args);
    }
}
