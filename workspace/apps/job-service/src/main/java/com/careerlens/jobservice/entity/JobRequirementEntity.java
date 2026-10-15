package com.careerlens.jobservice.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/**
 * 岗位技能要求 {@code job_requirement} —— ★ 算分依据（db/mysql/schema.sql 5/6）。
 *
 * <p><b>D3：{@code skillId} 非空</b>。归一化发生在「离线固化时」：抽取遇到词典未登录的
 * 技能时，先把词补进 {@code skills.yaml} → 重新生成 skill 表 → 再落 requirement。
 * 所以运行期这里<b>不存在 {@code skillId IS NULL} 的行</b>，Python 拿到的
 * {@code skill} 一律是 canonical，匹配退化为纯集合运算。
 *
 * <p>{@code skillRaw} 保留 JD 里的原文写法（如 {@code "C/C++"}）供展示；
 * 算分与去重用的是 {@code skillId} 指向的 canonical。两者分开是因为
 * 「人看到的写法」和「机器比的键」本来就不该是同一个东西。
 */
@Entity
@Table(name = "job_requirement")
public class JobRequirementEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /** FK {@code job.id}。 */
    @Column(name = "job_id", nullable = false)
    private Long jobId;

    /** FK {@code skill.id}。<b>NOT NULL</b>（D3）。 */
    @Column(name = "skill_id", nullable = false)
    private Long skillId;

    /** JD 里的原文写法（展示用），如 {@code "C/C++"}。 */
    @Column(name = "skill_raw", nullable = false, length = 64)
    private String skillRaw;

    /** {@code required | preferred}（权重 1.0 / 0.5）。 */
    @Column(name = "importance", nullable = false, length = 16)
    private String importance;

    /** JD 原文依据（逐字复制，不许改写）。 */
    @Column(name = "evidence", length = 512)
    private String evidence;

    /** {@code evidence} 在 {@code jd_raw} 中的起始下标。 */
    @Column(name = "jd_offset")
    private Integer jdOffset;

    public Long getId() {
        return id;
    }

    public Long getJobId() {
        return jobId;
    }

    public void setJobId(Long jobId) {
        this.jobId = jobId;
    }

    public Long getSkillId() {
        return skillId;
    }

    public void setSkillId(Long skillId) {
        this.skillId = skillId;
    }

    public String getSkillRaw() {
        return skillRaw;
    }

    public void setSkillRaw(String skillRaw) {
        this.skillRaw = skillRaw;
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
}
