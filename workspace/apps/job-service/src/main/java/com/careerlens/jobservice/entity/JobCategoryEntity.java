package com.careerlens.jobservice.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/**
 * 岗位分类字典 {@code job_category} —— 树形自关联（db/mysql/schema.sql 1/6）。
 *
 * <p><b>D1：分类是数据不是代码</b>。新增一类岗位（如「财务」）= INSERT 一行，
 * 不改表结构、不改 Java 代码、不重新发版 —— AC22 就是按这条判定的。
 * 所以本服务里<b>没有任何 {@code enum JobCategory}</b>，也不会有（附录 C 的审核项）。
 *
 * <p>树形层级由 {@code parentId} + {@code level} 共同表达：{@code level} 是
 * <b>冗余的</b>（可由 parent 链推出），但它是故意留的 —— 「取所有大类」这条查询
 * 因此不需要自连接，而分类表是启动时读一次后就几乎不变的字典数据。
 */
@Entity
@Table(name = "job_category")
public class JobCategoryEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /** 稳定业务键：{@code tech-backend}。 */
    @Column(name = "code", nullable = false, unique = true, length = 48)
    private String code;

    @Column(name = "name", nullable = false, length = 64)
    private String name;

    /** 自关联；{@code NULL} = 根（大类）。 */
    @Column(name = "parent_id")
    private Long parentId;

    /**
     * 1 = 大类，2 = 子类。
     *
     * <p>{@code columnDefinition = "TINYINT"} 是必要的：MySQL 与 H2 两份 schema
     * 都把它建成 TINYINT（取值只有 1 / 2），而 Java 的 {@code int} 默认映射到
     * INTEGER —— {@code ddl-auto=validate} 会报类型不匹配。用 Java 侧显式声明对齐
     * 库结构，比把字段改成 {@code byte} 可读（后者会让调用方到处强转）。
     */
    @Column(name = "level", nullable = false, columnDefinition = "TINYINT")
    private int level;

    @Column(name = "sort_order", nullable = false)
    private int sortOrder;

    /** {@code active | archived}。 */
    @Column(name = "status", nullable = false, length = 16)
    private String status;

    public Long getId() {
        return id;
    }

    public String getCode() {
        return code;
    }

    public void setCode(String code) {
        this.code = code;
    }

    public String getName() {
        return name;
    }

    public void setName(String name) {
        this.name = name;
    }

    public Long getParentId() {
        return parentId;
    }

    public void setParentId(Long parentId) {
        this.parentId = parentId;
    }

    public int getLevel() {
        return level;
    }

    public void setLevel(int level) {
        this.level = level;
    }

    public int getSortOrder() {
        return sortOrder;
    }

    public void setSortOrder(int sortOrder) {
        this.sortOrder = sortOrder;
    }

    public String getStatus() {
        return status;
    }

    public void setStatus(String status) {
        this.status = status;
    }
}
