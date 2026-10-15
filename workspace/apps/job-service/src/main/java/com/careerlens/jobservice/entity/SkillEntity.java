package com.careerlens.jobservice.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/**
 * 技能标准名 {@code skill}（db/mysql/schema.sql 2/6）。
 *
 * <p>真源是仓库内 {@code analyzer/app/data/skills.yaml}（契约变更 C4），
 * 本表由 {@code scripts/gen-seed.sh} 生成、<b>禁止手改</b>。
 * {@code canonical} 必须与 YAML 逐字一致，否则归一化率静默下降（DoD §8）。
 *
 * <p><b>Java 侧为什么只需要「按 id / canonical 查」**：Python 的归一化用的是
 * 仓库内 YAML，不查库（spec §2.7：Python 禁止直连数据库）。本服务只是把
 * {@code job_requirement.skill_id} 翻译成 canonical 发给 Python —— 一次纯查表，
 * 不参与任何算法。
 */
@Entity
@Table(name = "skill")
public class SkillEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /** 标准名：{@code Spring Boot}（写 "Vue" 不写 "Vue3"）。 */
    @Column(name = "canonical", nullable = false, unique = true, length = 64)
    private String canonical;

    /** {@code language|framework|db|middleware|frontend|devops|tool|ai}。 */
    @Column(name = "category", nullable = false, length = 32)
    private String category;

    /** {@code active | archived}。 */
    @Column(name = "status", nullable = false, length = 16)
    private String status;

    public Long getId() {
        return id;
    }

    public String getCanonical() {
        return canonical;
    }

    public void setCanonical(String canonical) {
        this.canonical = canonical;
    }

    public String getCategory() {
        return category;
    }

    public void setCategory(String category) {
        this.category = category;
    }

    public String getStatus() {
        return status;
    }

    public void setStatus(String status) {
        this.status = status;
    }
}
