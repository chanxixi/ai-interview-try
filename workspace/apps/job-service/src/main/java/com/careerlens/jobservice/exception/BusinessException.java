package com.careerlens.jobservice.exception;

/**
 * 领域异常 —— <b>业务层只抛它</b>，绝不抛 HTTP 相关类型（指南 §3.2 反模式）。
 *
 * <p><b>为什么不让 Service 直接决定 HTTP 状态码</b>：那会把传输层语义渗进业务层，
 * 导致 ① 业务单测要造 Web 上下文；② 换传输方式（CLI / 队列消费者）就要改业务代码。
 * 正确做法是业务层只表达「哪一类错」，由 {@link GlobalExceptionHandler} 在边界翻译。
 *
 * <p><b>唯一调用方</b>：service 层；<b>唯一捕获方</b>：{@link GlobalExceptionHandler}。
 */
public class BusinessException extends RuntimeException {

    private final ErrorCode errorCode;

    /** 使用 {@link ErrorCode#defaultMessage()} 作为对外文案。 */
    public BusinessException(ErrorCode errorCode) {
        this(errorCode, errorCode.defaultMessage());
    }

    /**
     * @param errorCode 错误码（决定 HTTP 状态码，见 {@link ErrorCode}）
     * @param message   对外文案 —— <b>不得包含内部实现细节</b>（spec.md §3.3 禁止透传错误栈）
     */
    public BusinessException(ErrorCode errorCode, String message) {
        super(message);
        this.errorCode = errorCode;
    }

    public ErrorCode errorCode() {
        return errorCode;
    }
}
