package com.careerlens.jobservice.dto.response;

/**
 * 健康检查响应（<b>出站 DTO</b>）—— spec.md §2.8 要求每个服务暴露 {@code GET /healthz}。
 *
 * <p>用 {@code record} 而非 {@code Map.of(...)} 的原因：
 *
 * <ol>
 *   <li>{@code Map.of} 是无序的，字段顺序每次运行可能不同，日志与快照测试不稳定；
 *   <li>形状写死在代码里，改字段时编译期即可发现调用方，不用满仓库 grep 字面量 key。
 * </ol>
 *
 * <p><b>T4 会扩展本类型</b>：按 spec.md §2.9 / ADR-007，healthz 需要额外返回
 * {@code storage} 字段（{@code mysql | local | mock}），用于对外证明存储降级状态。
 * 本期（骨架）刻意不加 —— 存储层还不存在，凭空返回一个假字段比不返回更糟。
 *
 * <p><b>唯一构造方</b>：{@code controller.health.HealthController}（P2-4 起经 service 层）。
 */
public record HealthResponse(String status, String service) {

    /** 固定文案 "ok"，避免各处手写字符串拼错（探针类接口对字面量一致性敏感）。 */
    public static HealthResponse ok(String service) {
        return new HealthResponse("ok", service);
    }
}
