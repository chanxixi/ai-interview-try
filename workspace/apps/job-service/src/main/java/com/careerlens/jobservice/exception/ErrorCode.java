package com.careerlens.jobservice.exception;

import org.springframework.http.HttpStatus;

/**
 * 错误码表 —— 与 <b>spec.md §2.3（冻结）</b>逐条对应。
 *
 * <p><b>职责边界</b>：本枚举是「code → HTTP 状态码 → 默认文案」的<b>唯一来源</b>。
 * 改这里等于改契约，必须先走 spec.md 的《变更记录》并同步三份 OpenAPI 契约。
 *
 * <p><b>刻意不收录的码</b>：
 *
 * <ul>
 *   <li>「数据库不可用」——存储降级在 Java 层内部消化（spec.md §2.9 / ADR-003），
 *       上游永远看不到这个失败；降级状态通过 {@code GET /healthz} 的 {@code storage}
 *       字段对外暴露，不进错误码表。
 * </ul>
 *
 * <p><b>唯一调用方</b>：{@link BusinessException}（领域抛出）与
 * {@link GlobalExceptionHandler}（边界翻译成 HTTP）。
 */
public enum ErrorCode {

    /** 参数校验失败（@Valid 未通过）。 */
    INVALID_INPUT(HttpStatus.BAD_REQUEST, "请求参数校验失败"),

    /** 简历超过 20000 字符（spec.md §2.1）。 */
    RESUME_TOO_LONG(HttpStatus.BAD_REQUEST, "简历文本超过 20000 字符上限"),

    /** jobId 不存在（T4 起由岗位查询使用）。 */
    JOB_NOT_FOUND(HttpStatus.NOT_FOUND, "岗位不存在"),

    /** 下游 analyzer 返回 4xx，或返回体不符合契约。 */
    ANALYSIS_FAILED(HttpStatus.UNPROCESSABLE_ENTITY, "分析服务处理失败"),

    /** 触发限流（spec.md §1.4 本期未启用，预留）。 */
    RATE_LIMITED(HttpStatus.TOO_MANY_REQUESTS, "请求过于频繁"),

    /** 下游不可用（连接失败 / 5xx）。 */
    SERVICE_UNAVAILABLE(HttpStatus.SERVICE_UNAVAILABLE, "下游服务不可用"),

    /** 下游调用超时（超时矩阵见 plan.md §6.1）。 */
    UPSTREAM_TIMEOUT(HttpStatus.GATEWAY_TIMEOUT, "下游服务响应超时"),

    /** 未预期错误 —— 兜底，不透传原始错误栈（spec.md §3.3）。 */
    INTERNAL_ERROR(HttpStatus.INTERNAL_SERVER_ERROR, "服务内部错误");

    private final HttpStatus httpStatus;
    private final String defaultMessage;

    ErrorCode(HttpStatus httpStatus, String defaultMessage) {
        this.httpStatus = httpStatus;
        this.defaultMessage = defaultMessage;
    }

    public HttpStatus httpStatus() {
        return httpStatus;
    }

    public String defaultMessage() {
        return defaultMessage;
    }
}
