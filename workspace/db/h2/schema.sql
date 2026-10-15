-- ============================================================================
-- CareerLens · part2 数据模型 —— H2（MODE=MySQL）降级路径建表
-- ----------------------------------------------------------------------------
-- 依据：sdd/part2/spec.md §2.9、plan.md §4
-- 主路径副本：db/mysql/schema.sql —— **两份必须同构**：改一边必须同步改另一边
-- 生成物：db/seed.sql 由 scripts/gen-seed.sh 生成，**禁止手改**
--
-- 与 mysql/schema.sql 的差异（且**只有**这些差异，plan §4 约定）：
--   ① 去掉表级 ENGINE / DEFAULT CHARSET / COLLATE / COMMENT 子句（MySQL 专有）
--   ② 去掉列级 COMMENT '...'（H2 用 COMMENT ON COLUMN 语句，内联写法不通用）
--   ③ 其余**逐字保持**：表名 / 列名 / 类型 / uk_* 唯一键 / KEY 索引 / 默认值
--      —— 已实测 H2 2.2.224 在 MODE=MySQL 下支持 AUTO_INCREMENT、MEDIUMTEXT、
--         KEY (...) 内联索引、ON UPDATE CURRENT_TIMESTAMP，因此无需降级类型
--         （这正是「同构」而不是「另一套表结构」的关键）
--   ④ job.jd_raw / job.attributes 用 CLOB（2026-10-14 修）：
--      H2 2.3 在 MODE=MySQL 下把 TEXT 与 MEDIUMTEXT 都解析成 VARCHAR，
--      而 Hibernate 的 @Lob String 期望 CLOB —— ddl-auto=validate 会报
--      「found [varchar], expecting [clob]」，服务起不来。
--      MySQL 侧保持 MEDIUMTEXT / TEXT（都是 LOB，语义等价，不需要改）。
--      ★ 教训：validate 的价值正在这里 —— 它把「类型不匹配」在启动期变成硬失败，
--        而不是等到某条长文本写不进去才发现。
--
-- 连接串：jdbc:h2:mem:careerlens;MODE=MySQL;DATABASE_TO_LOWER=TRUE
--   DATABASE_TO_LOWER 必须开：否则 H2 把未加引号的标识符折成大写，
--   与 MySQL 的小写表名/列名不一致，Java 侧映射与手写 SQL 都会踩空。
--
-- 三条冻结约束（D1 / D2 / D3）与主路径完全一致，见 mysql/schema.sql 头部。
-- 全部 CREATE TABLE 带 IF NOT EXISTS：spring.sql.init 每次启动都会跑本脚本。
-- ============================================================================


-- ---------------------------------------------------------------------------
-- 1/6 job_category —— 岗位分类字典（树形，parent_id 自关联）
-- ---------------------------------------------------------------------------
-- D1：分类是数据不是代码。新增一类岗位只需 INSERT 一行，不改 Java 代码。
CREATE TABLE IF NOT EXISTS job_category (
  id         BIGINT       NOT NULL AUTO_INCREMENT,
  code       VARCHAR(48)  NOT NULL,
  name       VARCHAR(64)  NOT NULL,
  parent_id  BIGINT       NULL,
  level      TINYINT      NOT NULL DEFAULT 1,
  sort_order INT          NOT NULL DEFAULT 0,
  status     VARCHAR(16)  NOT NULL DEFAULT 'active',
  PRIMARY KEY (id),
  CONSTRAINT uk_category_code UNIQUE (code),
  KEY idx_category_parent (parent_id)
);


-- ---------------------------------------------------------------------------
-- 2/6 skill —— 技能标准名（由 app/data/skills.yaml 生成）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS skill (
  id        BIGINT      NOT NULL AUTO_INCREMENT,
  canonical VARCHAR(64) NOT NULL,
  category  VARCHAR(32) NOT NULL,
  status    VARCHAR(16) NOT NULL DEFAULT 'active',
  PRIMARY KEY (id),
  CONSTRAINT uk_skill_canonical UNIQUE (canonical),
  KEY idx_skill_category (category)
);


-- ---------------------------------------------------------------------------
-- 3/6 skill_alias —— 技能别名（归一化的第二跳）
-- ---------------------------------------------------------------------------
-- uk_alias 落在 alias 上：一个别名只能指向一个标准名。
CREATE TABLE IF NOT EXISTS skill_alias (
  id       BIGINT      NOT NULL AUTO_INCREMENT,
  skill_id BIGINT      NOT NULL,
  alias    VARCHAR(64) NOT NULL,
  PRIMARY KEY (id),
  CONSTRAINT uk_alias UNIQUE (alias),
  KEY idx_skill_alias_skill (skill_id)
);


-- ---------------------------------------------------------------------------
-- 4/6 job —— 岗位主表（含 JD 原文）
-- ---------------------------------------------------------------------------
-- D2：只软删。status ∈ {draft,active,archived} + deleted_at，无物理 DELETE。
-- attributes 用 CLOB（不是 JSON）：与 MySQL 版的 TEXT 同语义（都是大文本 LOB），
-- 代价是失去 JSON 路径索引。
-- ⚠️ jd_raw / attributes 都**不能**写成 MEDIUMTEXT / TEXT —— 见文件头差异 ④。
CREATE TABLE IF NOT EXISTS job (
  id           BIGINT       NOT NULL AUTO_INCREMENT,
  code         VARCHAR(48)  NOT NULL,
  title        VARCHAR(128) NOT NULL,
  company      VARCHAR(128) NULL,
  level        VARCHAR(32)  NULL,
  category_id  BIGINT       NULL,
  jd_raw       CLOB         NOT NULL,
  content_hash CHAR(64)     NOT NULL,
  attributes   CLOB         NULL,
  source       VARCHAR(16)  NOT NULL DEFAULT 'seed',
  status       VARCHAR(16)  NOT NULL DEFAULT 'active',
  deleted_at   TIMESTAMP    NULL,
  version      INT          NOT NULL DEFAULT 1,
  created_at   TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at   TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  CONSTRAINT uk_job_code UNIQUE (code),
  KEY idx_job_category (category_id),
  KEY idx_job_status (status, deleted_at),
  KEY idx_job_source (source)
);


-- ---------------------------------------------------------------------------
-- 5/6 job_requirement —— 岗位 → 技能要求（★ 算分依据）
-- ---------------------------------------------------------------------------
-- D3：skill_id NOT NULL。未登录词先补 skills.yaml 再落库，归一化发生在离线固化时。
CREATE TABLE IF NOT EXISTS job_requirement (
  id         BIGINT       NOT NULL AUTO_INCREMENT,
  job_id     BIGINT       NOT NULL,
  skill_id   BIGINT       NOT NULL,
  skill_raw  VARCHAR(64)  NOT NULL,
  importance VARCHAR(16)  NOT NULL,
  evidence   VARCHAR(512) NULL,
  jd_offset  INT          NULL,
  PRIMARY KEY (id),
  CONSTRAINT uk_job_skill UNIQUE (job_id, skill_id),
  KEY idx_req_skill (skill_id)
);


-- ---------------------------------------------------------------------------
-- 6/6 job_tag —— 岗位横切标签（多选）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS job_tag (
  id     BIGINT      NOT NULL AUTO_INCREMENT,
  job_id BIGINT      NOT NULL,
  tag    VARCHAR(32) NOT NULL,
  PRIMARY KEY (id),
  CONSTRAINT uk_job_tag UNIQUE (job_id, tag),
  KEY idx_job_tag_tag (tag)
);


-- ============================================================================
-- 扩展位：两张「现在不建、结构已想好」的表（M1.5.6）
-- ----------------------------------------------------------------------------
-- analysis_record（分析历史，含 job_snapshot）与 job_revision（JD 变更史）本期不建，
-- 完整字段与「什么时候建」见 workspace/DELIVERY.md「扩展位」一节。
-- ============================================================================


-- ---------------------------------------------------------------------------
-- 为什么没有 FOREIGN KEY 约束
-- ---------------------------------------------------------------------------
-- 与 mysql/schema.sql 一致：完整性由 gen-seed.sh 的分节顺序（category → skill →
-- job → requirement → tag）与 M3.5 的 seed 一致性校验脚本在 CI 里把关。
-- 若将来要加 FK，是一次纯增量 DDL。
-- ============================================================================
