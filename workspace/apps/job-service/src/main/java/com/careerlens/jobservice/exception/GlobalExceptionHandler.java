package com.careerlens.jobservice.exception;

import com.careerlens.jobservice.config.constants.TraceConstants;
import com.careerlens.jobservice.dto.response.ApiErrorResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/**
 * 统一错误收口 —— 全服务**唯一**把异常翻译成 HTTP 的地方（spec.md §2.3）。
 *
 * <p><b>职责边界</b>：
 *
 * <ul>
 *   <li>只做「异常 → HTTP 状态码 + {@link ApiErrorResponse}」的翻译，不含业务判断
 *   <li>不透传原始错误栈（spec.md §3.3）；{@code message} 一律来自 {@link ErrorCode}
 *       的默认文案或 {@link BusinessException} 构造时传入的对外文案
 * </ul>
 *
 * <p><b>与 BFF 的分工</b>：本层输出的是「Java 层视角」的错误；BFF 会按 plan.md §6.4
 * 再映射一层（例如把本层 5xx 收敛为 503 SERVICE_UNAVAILABLE）。两层都收口，但语义不同。
 *
 * <p><b>唯一调用方</b>：Spring MVC 异常分发（{@code @RestControllerAdvice}）。
 *
 * @see ErrorCode 错误码唯一来源
 * @see BusinessException 业务层抛出的领域异常
 */
@RestControllerAdvice
public class GlobalExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    /** 领域异常 —— 业务层唯一允许抛出的异常类型。 */
    @ExceptionHandler(BusinessException.class)
    public ResponseEntity<ApiErrorResponse> handleBusiness(BusinessException ex) {
        ErrorCode code = ex.errorCode();
        // 4xx 是「调用方问题」，warn 即可；5xx 是「我方问题」，需要 error 级别 + 堆栈
        if (code.httpStatus().is5xxServerError()) {
            log.error("business failure: code={} message={}", code.name(), ex.getMessage(), ex);
        } else {
            log.warn("business rejected: code={} message={}", code.name(), ex.getMessage());
        }
        return build(code, ex.getMessage());
    }

    /** {@code @Valid} 校验失败 → 400 INVALID_INPUT（spec.md §2.3）。 */
    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<ApiErrorResponse> handleValidation(MethodArgumentNotValidException ex) {
        String detail = ex.getBindingResult().getFieldErrors().stream()
                .map(error -> error.getField() + ": " + error.getDefaultMessage())
                .reduce((a, b) -> a + "; " + b)
                .orElse(ErrorCode.INVALID_INPUT.defaultMessage());
        log.warn("validation failed: {}", detail);
        return build(ErrorCode.INVALID_INPUT, detail);
    }

    /**
     * 兜底 —— 未预期异常。
     *
     * <p>没有这一条时，未预期异常会走 Spring 默认错误体（{@code {timestamp,status,error,path}}），
     * 形状与 spec.md §2.3 不一致。这里统一收口为 {@link ErrorCode#INTERNAL_ERROR}，
     * 堆栈只进日志、不出网。
     */
    @ExceptionHandler(Exception.class)
    public ResponseEntity<ApiErrorResponse> handleUnexpected(Exception ex) {
        log.error("unexpected error", ex);
        return build(ErrorCode.INTERNAL_ERROR, ErrorCode.INTERNAL_ERROR.defaultMessage());
    }

    private ResponseEntity<ApiErrorResponse> build(ErrorCode code, String message) {
        ApiErrorResponse body = new ApiErrorResponse(
                code.name(),
                message,
                // TraceIdFilter 以 HIGHEST_PRECEDENCE 运行，正常路径下 MDC 必然已有值；
                // 若为 null（例如 filter 之外的调用），契约字段仍保留，避免响应形状漂移
                MDC.get(TraceConstants.MDC_KEY));
        return ResponseEntity.status(code.httpStatus()).body(body);
    }
}
