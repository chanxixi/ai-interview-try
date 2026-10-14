package com.careerlens.jobservice.config.constants;

/**
 * 全链追踪常量（<b>spec.md §2.8 冻结</b>）。
 *
 * <p><b>为什么单独建这个类</b>：这两个值原先分别散落在 {@code web.TraceIdFilter} 与
 * {@code client.AnalyzerClient} 里各写一份（字面量重复）。一旦出现「某处改了 header 名、
 * 别处没改」，全链 traceId 会静默断裂且极难定位。这里收敛为<b>唯一来源</b>，
 * 其它地方只 import、不重新定义、不 re-export。
 *
 * <p><b>依赖方向</b>：{@code config.constants} 不依赖任何业务包 —— 它必须能被
 * exception / client / web 任意一层引用而不产生反向依赖。
 */
public final class TraceConstants {

    /** 全链追踪 header 名（spec.md §2.8 冻结，三服务必须逐字一致）。 */
    public static final String TRACE_ID_HEADER = "X-Trace-Id";

    /** MDC key —— 决定 logback JSON 里的字段名（见 logback-spring.xml）。 */
    public static final String MDC_KEY = "traceId";

    private TraceConstants() {
        // 常量类，禁止实例化
    }
}
