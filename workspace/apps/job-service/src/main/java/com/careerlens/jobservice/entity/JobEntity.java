package com.careerlens.jobservice.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Lob;
import jakarta.persistence.Table;

import java.time.Instant;

/**
 * 岗位主表 {@code job} —— 含 JD 原文（db/mysql/schema.sql 4/6）。
 *
 * <p><b>D2 软删</b>：没有物理删除方法。归档 = {@code status='archived'}，
 * 删除 = 写 {@code deletedAt}。查询候选集的两个条件 {@code status='active'}
 * 与 {@code deletedAt IS NULL} 由 {@code JobRepository} 的方法名表达，
 * 不写在调用方 —— 否则「某处忘加 deletedAt」会让已删岗位重新进入推荐（AC23）。
 *
 * <p><b>Entity 不出 Repository</b>（项目铁律）：本类只在 {@code repository/} 与
 * {@code entity/} 内出现，向外一律转成 {@code dto/JobCandidateDto}。
 * 直接返回 Entity 会把表结构绑死成 API 契约 —— 加一列就是一次破坏性变更。
 */
@Entity
@Table(name = "job")
public class JobEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /** 稳定业务键：{@code job-java-01} / {@code manual-<uuid8>}。对外一律用这个，不用自增 id。 */
    @Column(name = "code", nullable = false, unique = true, length = 48)
    private String code;

    @Column(name = "title", nullable = false, length = 128)
    private String title;

    @Column(name = "company", length = 128)
    private String company;

    @Column(name = "level", length = 32)
    private String level;

    /** FK {@code job_category.id}。可空：岗位允许暂时未分类（导入顺序不耦合）。 */
    @Column(name = "category_id")
    private Long categoryId;

    /**
     * JD 原文。<b>只在本服务内流转</b>，下发 Python 时走顶层 jdText，不进候选集（契约 R2）。
     *
     * <p>{@code @Lob} 必须加：JD 原文动辄几千字，不加会落到 VARCHAR 上限。
     *
     * <p>⚠️ {@code length} 也必须写，且必须与 db/mysql/schema.sql 的 {@code MEDIUMTEXT} 对齐。
     * 只写 {@code @Lob} 不写 length 时，Hibernate 6 在 <b>MySQL 方言</b>下会挑最小的 LOB 档位
     * （渲染成 {@code tinytext}，仅 255 字节），于是 {@code ddl-auto=validate} 直接报
     * 「found [text (Types#LONGVARCHAR)], but expecting [tinytext (Types#CLOB)]」而拒绝启动；
     * 更危险的是若关掉 validate，JD 原文会被静默截断到 255 字节。
     * H2 方言只有 CLOB 一个档位、不受 length 影响，所以这个坑只在真 MySQL 上暴露。
     * 16_777_215 = MEDIUMTEXT 上限，正好让 Hibernate 选到 mediumtext。
     */
    @Lob
    @Column(name = "jd_raw", nullable = false, length = 16_777_215)
    private String jdRaw;

    /**
     * {@code sha256(company|title|jdRaw)}，用于判断 JD 变了没 → 决定是否重抽技能。
     *
     * <p>{@code columnDefinition = "CHAR(64)"} 是<b>必要的</b>：库里建的就是 CHAR(64)
     * （MySQL 与 H2 两份 schema 一致，因为 sha256 十六进制恒为 64 字符，定长更贴切）。
     * 只写 {@code length = 64} 的话 Hibernate 期望 VARCHAR(64)，
     * 而 {@code ddl-auto=validate} 会在启动期报类型不匹配 —— 这正是 validate 的价值。
     */
    @Column(name = "content_hash", nullable = false, length = 64, columnDefinition = "CHAR(64)")
    private String contentHash;

    /**
     * 扩展位 JSON（薪资 / 城市 / 经验年限 / 学历…）。
     *
     * <p>@Lob + 数据库侧 MEDIUMTEXT / TEXT / CLOB，与 {@code jd_raw} 同一口径。
     * 用 TEXT 而不是原生 JSON 是因为要与 H2 版保持同构 —— 代价是失去 JSON 路径索引，
     * 本期只做展示与预留，可接受。
     *
     * <p>⚠️ {@code length} 与 {@code jd_raw} 同理必须写：65_535 = TEXT 上限，
     * 让 Hibernate 的 MySQL 方言选到 {@code text} 而不是 {@code tinytext}。
     */
    @Lob
    @Column(name = "attributes", length = 65_535)
    private String attributes;

    /** {@code seed | manual | import}。重新导入 seed 时只更新 seed 行，不覆盖人工录入。 */
    @Column(name = "source", nullable = false, length = 16)
    private String source;

    /** {@code draft | active | archived}。 */
    @Column(name = "status", nullable = false, length = 16)
    private String status;

    /** 软删时间戳；{@code NULL} = 未删（D2）。 */
    @Column(name = "deleted_at")
    private Instant deletedAt;

    @Column(name = "version", nullable = false)
    private int version;

    @Column(name = "created_at", nullable = false, insertable = false, updatable = false)
    private Instant createdAt;

    @Column(name = "updated_at", nullable = false, insertable = false, updatable = false)
    private Instant updatedAt;

    public Long getId() {
        return id;
    }

    public String getCode() {
        return code;
    }

    public void setCode(String code) {
        this.code = code;
    }

    public String getTitle() {
        return title;
    }

    public void setTitle(String title) {
        this.title = title;
    }

    public String getCompany() {
        return company;
    }

    public void setCompany(String company) {
        this.company = company;
    }

    public String getLevel() {
        return level;
    }

    public void setLevel(String level) {
        this.level = level;
    }

    public Long getCategoryId() {
        return categoryId;
    }

    public void setCategoryId(Long categoryId) {
        this.categoryId = categoryId;
    }

    public String getJdRaw() {
        return jdRaw;
    }

    public void setJdRaw(String jdRaw) {
        this.jdRaw = jdRaw;
    }

    public String getContentHash() {
        return contentHash;
    }

    public void setContentHash(String contentHash) {
        this.contentHash = contentHash;
    }

    public String getAttributes() {
        return attributes;
    }

    public void setAttributes(String attributes) {
        this.attributes = attributes;
    }

    public String getSource() {
        return source;
    }

    public void setSource(String source) {
        this.source = source;
    }

    public String getStatus() {
        return status;
    }

    public void setStatus(String status) {
        this.status = status;
    }

    public Instant getDeletedAt() {
        return deletedAt;
    }

    public void setDeletedAt(Instant deletedAt) {
        this.deletedAt = deletedAt;
    }

    public int getVersion() {
        return version;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public Instant getUpdatedAt() {
        return updatedAt;
    }
}
