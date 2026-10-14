package com.careerlens.jobservice.dto.response;

import com.fasterxml.jackson.annotation.JsonInclude;

/**
 * 连通性探针响应（<b>出站 DTO</b>，非契约接口）。
 *
 * <p>用途：证明 job-service 可达，并带上下游 analyzer 的一跳结果，
 * 让「链路断在哪一跳」一眼可见（spec.md §2.8 全链可观测）。
 *
 * <p>字段顺序即 JSON 输出顺序，与重构前的 {@code LinkedHashMap} 逐字一致。
 *
 * @param downstream 下游 analyzer 的探测结果，见 {@link Downstream}
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record PingResponse(
        String service,
        String status,
        String version,
        String runtime,
        String traceId,
        Downstream downstream) {

    /**
     * 下游一跳的探测结果。
     *
     * <p><b>刻意做成「成功字段 + error 字段」共存的扁平结构</b>，而不是
     * 成功/失败两个子类型：探针响应是诊断用的，形状越稳定越好用；
     * 用 {@code @JsonInclude(NON_NULL)} 保证成功时不出现 {@code error}、
     * 失败时不出现半空的 {@code version/runtime/traceId}。
     *
     * @param status {@code ok} 或 {@code down}
     * @param error  仅失败时出现：下游异常的<b>类名</b>（不带堆栈，spec.md §3.3）
     */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record Downstream(
            String service,
            String status,
            String version,
            String runtime,
            String traceId,
            String error) {
    }
}
