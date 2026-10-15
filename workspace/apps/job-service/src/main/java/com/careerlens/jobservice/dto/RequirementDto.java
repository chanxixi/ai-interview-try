package com.careerlens.jobservice.dto;

import com.fasterxml.jackson.annotation.JsonInclude;

/**
 * 岗位技能要求 DTO —— Java → Python 的契约形状（contracts/bff-java.yaml 的 {@code RequirementDto}）。
 *
 * <p>字段名与 plan §3 <b>逐字一致</b>，{@code additionalProperties: false}：
 * 多一个字段 Python 的 Pydantic 模型就会拒收（analyzer 侧按契约建模型）。
 *
 * <p><b>为什么不用 record 的紧凑构造</b>：{@code jdOffset} 在库里可空，
 * 而契约里是 {@code type: ['integer','null']}。用 record 就得在每个调用点判空，
 * 所以保留 setter —— 但本类只在 {@code service/} 装配时被写一次，
 * 之后按值传给 HTTP 客户端，不会被业务代码改。
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public class RequirementDto {

    /** 标准名（canonical），如 {@code C++} 而非 {@code C/C++}。 */
    private String skill;

    /** {@code required | preferred}。 */
    private String importance;

    /** JD 原文依据（逐字复制）。 */
    private String evidence;

    /** {@code evidence} 在 JD 原文中的起始下标。 */
    private Integer jdOffset;

    /** JD 里的原文写法（展示用）。 */
    private String skillRaw;

    public RequirementDto() {
    }

    public RequirementDto(String skill, String importance, String evidence,
                          Integer jdOffset, String skillRaw) {
        this.skill = skill;
        this.importance = importance;
        this.evidence = evidence;
        this.jdOffset = jdOffset;
        this.skillRaw = skillRaw;
    }

    public String getSkill() {
        return skill;
    }

    public void setSkill(String skill) {
        this.skill = skill;
    }

    public String getImportance() {
        return importance;
    }

    public void setImportance(String importance) {
        this.importance = importance;
    }

    public String getEvidence() {
        return evidence;
    }

    public void setEvidence(String evidence) {
        this.evidence = evidence;
    }

    public Integer getJdOffset() {
        return jdOffset;
    }

    public void setJdOffset(Integer jdOffset) {
        this.jdOffset = jdOffset;
    }

    public String getSkillRaw() {
        return skillRaw;
    }

    public void setSkillRaw(String skillRaw) {
        this.skillRaw = skillRaw;
    }
}
