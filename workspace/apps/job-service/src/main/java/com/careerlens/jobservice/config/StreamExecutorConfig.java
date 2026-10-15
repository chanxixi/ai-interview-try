package com.careerlens.jobservice.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.task.TaskExecutor;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;

/**
 * 流式转发的专用线程池（tasks.md M5.6「独立 TaskExecutor」）。
 *
 * <h2>为什么不能用默认的 Servlet 线程</h2>
 * 一条分析链路几十秒（瓶颈在 LLM）。若转发跑在 Tomcat 工作线程上，
 * 并发几个上传就把线程池占满，之后的请求全部排队 —— 表现为「服务卡住」，
 * 而 healthz 还是 200（它走的是另外的线程），极难排查。
 *
 * <h2>参数怎么定的</h2>
 * <ul>
 *   <li>{@code corePoolSize=4}：本地开发 + 答辩演示的并发量级。线程本身很轻，
 *       瓶颈在等下游 IO，所以少量线程足够。</li>
 *   <li>{@code maxPoolSize=8} + 有界队列（{@code queueCapacity=32}）：
 *       队列<b>必须有界</b>。无界队列在「下游挂了、请求持续进来」时会无限堆积，
 *       最后 OOM —— 而拒绝策略至少能让调用方看到一个错误。</li>
 *   <li>{@code CallerRunsPolicy}：队列满时在调用线程（Tomcat）里跑。
 *       这会让转发变慢，但不会丢请求，也不会把异常抛给一个已经写了头的响应。</li>
 * </ul>
 */
@Configuration
public class StreamExecutorConfig {

    public static final String STREAM_EXECUTOR = "streamExecutor";

    @Bean(name = STREAM_EXECUTOR)
    public TaskExecutor streamExecutor() {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setCorePoolSize(4);
        executor.setMaxPoolSize(8);
        executor.setQueueCapacity(32);
        executor.setThreadNamePrefix("stream-forward-");
        executor.setWaitForTasksToCompleteOnShutdown(true);
        // 关闭时最多等 30 秒让在途的转发收尾，避免「优雅停机」变成硬断。
        executor.setAwaitTerminationSeconds(30);
        executor.initialize();
        return executor;
    }
}
