/**
 * 统一**错误**响应体 —— spec.md §2.3（冻结）。
 *
 * 只有错误走这个形状；成功响应直接返回业务对象（指南 §6.7）。
 * `message` 必须是**预置文案**，绝不能是 `err.message`（spec.md §3.3 禁止透传原始错误栈）。
 */
export interface ErrorResponse {
  code: string;
  message: string;
  traceId: string;
}
