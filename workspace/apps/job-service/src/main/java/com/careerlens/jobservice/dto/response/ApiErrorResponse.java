package com.careerlens.jobservice.dto.response;

/**
 * 统一错误响应体 —— <b>spec.md §2.3（冻结）</b>。
 *
 * <p>字段固定为 {@code { code, message, traceId }}，<b>刻意不加 {@code @JsonInclude(NON_NULL)}</b>：
 * 契约要求三个字段恒定存在，省略字段会破坏下游（BFF）的解析与前端提示。
 *
 * <p>成功响应<b>不使用</b>本类型（本项目是「半个」统一响应，见指南 §6.7）——
 * 成功时直接返回业务 DTO，不套 {@code {code, data}} 外壳。
 *
 * <p><b>唯一构造方</b>：{@link com.careerlens.jobservice.exception.GlobalExceptionHandler}。
 */
public record ApiErrorResponse(String code, String message, String traceId) {
}
