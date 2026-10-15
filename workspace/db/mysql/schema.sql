-- ============================================================================
-- CareerLens · part2 数据模型 —— MySQL 8.0 主路径建表（6 张本期表）
-- ----------------------------------------------------------------------------
-- 依据：sdd/part2/spec.md §2.9（表集 + D1–D3 冻结约束）、plan.md §4（字段设计）
-- 同构副本：db/h2/schema.sql（MODE=MySQL 降级路径）—— 改这里必须同步改那边
-- 生成物：db/seed.sql 由 scripts/gen-seed.sh 生成，**禁止手改**
--
-- 三条冻结约束（spec §2.9）
--   D1 分类是数据不是代码 → job_category 字典表（树形自关联），禁 Java enum
--   D2 岗位只软删         → status ∈ {draft,active,archived} + deleted_at，禁物理 DELETE
--   D3 技能要求必须归一化 → job_requirement.skill_id NOT NULL，未登录词先补 skills.yaml
--
-- 本文件只建「本期 6 张表」；扩展位两表（analysis_record / job_revision）只写注释
-- 不建表 —— 见文件末尾与 workspace/DELIVERY.md。
--
-- 全部 CREATE TABLE 都带 IF NOT EXISTS：Spring Boot 的 spring.sql.init 每次启动都会跑
-- 本脚本，没有 IF NOT EXISTS 第二次启动就直接报错（「幂等启动」的前提）。
-- ============================================================================


-- ---------------------------------------------------------------------------
-- 1/6 job_category —— 岗位分类字典（树形，parent_id 自关联）
-- ---------------------------------------------------------------------------
-- 为什么是表不是 enum（D1）：新增一类岗位（如「财务」）只需 INSERT 一行，
-- 不改表结构、不改 Java 代码、不重新发版。AC22 就按这条判定。
-- category 管「职能归属」（单选），与 job_tag 的「横切特征」（多选）不混。
CREATE TABLE IF NOT EXISTS job_category (
  id         BIGINT       NOT NULL AUTO_INCREMENT,
  code       VARCHAR(48)  NOT NULL COMMENT '稳定业务键：tech-backend',
  name       VARCHAR(64)  NOT NULL COMMENT '显示名：后端开发',
  parent_id  BIGINT       NULL     COMMENT '自关联；NULL = 根（大类）',
  level      TINYINT      NOT NULL DEFAULT 1 COMMENT '1=大类 2=子类',
  sort_order INT          NOT NULL DEFAULT 0 COMMENT '同层展示顺序',
  status     VARCHAR(16)  NOT NULL DEFAULT 'active' COMMENT 'active | archived',
  PRIMARY KEY (id),
  CONSTRAINT uk_category_code UNIQUE (code),
  KEY idx_category_parent (parent_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
  COMMENT='岗位分类字典（树形）· 新增分类 = 插一行';


-- ---------------------------------------------------------------------------
-- 2/6 skill —— 技能标准名
-- ---------------------------------------------------------------------------
-- 真源是仓库内 app/data/skills.yaml（C4），本表由 scripts/gen-seed.sh 生成。
-- canonical 必须与 skills.yaml 的 canonical 逐字一致，否则归一化率静默下降（DoD §8）。
CREATE TABLE IF NOT EXISTS skill (
  id        BIGINT      NOT NULL AUTO_INCREMENT,
  canonical VARCHAR(64) NOT NULL COMMENT '标准名：Spring Boot（写 "Vue" 不写 "Vue3"）',
  category  VARCHAR(32) NOT NULL COMMENT 'language|framework|db|middleware|frontend|devops|tool|ai',
  status    VARCHAR(16) NOT NULL DEFAULT 'active' COMMENT 'active | archived',
  PRIMARY KEY (id),
  CONSTRAINT uk_skill_canonical UNIQUE (canonical),
  KEY idx_skill_category (category)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
  COMMENT='技能标准名 · 由 skills.yaml 生成';


-- ---------------------------------------------------------------------------
-- 3/6 skill_alias —— 技能别名（归一化的第二跳）
-- ---------------------------------------------------------------------------
-- uk_alias 落在 alias 上而不是 (skill_id, alias)：一个别名只能指向一个标准名，
-- 否则「SpringBoot」同时指向 Spring Boot 与 Spring 时无法判定。
CREATE TABLE IF NOT EXISTS skill_alias (
  id       BIGINT      NOT NULL AUTO_INCREMENT,
  skill_id BIGINT      NOT NULL COMMENT 'FK skill.id',
  alias    VARCHAR(64) NOT NULL COMMENT 'SpringBoot / spring boot / SB',
  PRIMARY KEY (id),
  CONSTRAINT uk_alias UNIQUE (alias),
  KEY idx_skill_alias_skill (skill_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
  COMMENT='技能别名 · 由 skills.yaml 生成';


-- ---------------------------------------------------------------------------
-- 4/6 job —— 岗位主表（含 JD 原文）
-- ---------------------------------------------------------------------------
-- source / status / deleted_at / content_hash / attributes 这五个字段是专为
-- 「人工增删 + 可扩展」留的，逐条对应 plan §4.2 的表格：
--   source        重新导入 seed 时不覆盖人工录入（导入语句带 WHERE source='seed'）
--   status+deleted_at  软删（D2）：历史分析记录引用着岗位，硬删会悬空
--   content_hash  判断「JD 变了没」→ 决定要不要重抽技能 / 写 job_revision
--   attributes    JSON 扩展位，未来加「薪资/城市/学历」零 DDL
--
-- attributes 用 TEXT 而不是 MySQL 原生 JSON：要与 db/h2/schema.sql 保持同构
-- （H2 无等价类型），代价是失去 JSON 路径索引 —— 本期只做展示与预留，可接受。
CREATE TABLE IF NOT EXISTS job (
  id           BIGINT       NOT NULL AUTO_INCREMENT,
  code         VARCHAR(48)  NOT NULL COMMENT '稳定业务键：job-java-01 / manual-<uuid8>',
  title        VARCHAR(128) NOT NULL,
  company      VARCHAR(128) NULL,
  level        VARCHAR(32)  NULL COMMENT '校招 | 社招 | 实习',
  category_id  BIGINT       NULL COMMENT 'FK job_category.id（单选，D1）',
  jd_raw       MEDIUMTEXT   NOT NULL COMMENT 'JD 原文：兜底 / 展示 / 换算法不重爬',
  content_hash CHAR(64)     NOT NULL COMMENT 'sha256(company|title|jd_raw)，变更检测',
  attributes   TEXT         NULL COMMENT '扩展位 JSON：薪资/城市/经验年限/学历…',
  source       VARCHAR(16)  NOT NULL DEFAULT 'seed'   COMMENT 'seed | manual | import',
  status       VARCHAR(16)  NOT NULL DEFAULT 'active' COMMENT 'draft | active | archived',
  deleted_at   TIMESTAMP    NULL     COMMENT '软删时间戳；NULL = 未删（D2）',
  version      INT          NOT NULL DEFAULT 1,
  created_at   TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at   TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  CONSTRAINT uk_job_code UNIQUE (code),
  KEY idx_job_category (category_id),
  -- 推荐候选集的主查询：WHERE status='active' AND deleted_at IS NULL（AC23）
  KEY idx_job_status (status, deleted_at),
  KEY idx_job_source (source)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
  COMMENT='岗位主表 · 只软删（D2）';


-- ---------------------------------------------------------------------------
-- 5/6 job_requirement —— 岗位 → 技能要求（★ 算分依据）
-- ---------------------------------------------------------------------------
-- skill_id NOT NULL 是硬约束（D3）：离线抽取若遇到词典未登录的技能，必须先把词
-- 补进 skills.yaml → 重新生成 skill 表 → 再落 requirement。
-- 归一化因此发生在「离线固化时」，运行期只做纯集合运算 —— 与 plan §3
-- 「Python 收不到 JD 原文、只收结构化 requirements」是同一个设计意图。
--
-- skill_raw 保留原文写法（如 "C/C++"）供前端展示；skill_id 才是算分用的键。
CREATE TABLE IF NOT EXISTS job_requirement (
  id         BIGINT       NOT NULL AUTO_INCREMENT,
  job_id     BIGINT       NOT NULL COMMENT 'FK job.id',
  skill_id   BIGINT       NOT NULL COMMENT 'FK skill.id（离线阶段已归一化，D3）',
  skill_raw  VARCHAR(64)  NOT NULL COMMENT '原文写法（展示用）',
  importance VARCHAR(16)  NOT NULL COMMENT 'required | preferred（权重 1.0 / 0.5）',
  evidence   VARCHAR(512) NULL     COMMENT 'JD 原文依据（逐字复制，不许改写）',
  jd_offset  INT          NULL     COMMENT 'evidence 在 jd_raw 中的起始下标',
  PRIMARY KEY (id),
  CONSTRAINT uk_job_skill UNIQUE (job_id, skill_id),
  -- 按技能反查岗位（「哪些岗位要 Redis」）；job_id 前缀已被 uk_job_skill 覆盖，不重复建
  KEY idx_req_skill (skill_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
  COMMENT='岗位技能要求 · skill_id NOT NULL（D3）';


-- ---------------------------------------------------------------------------
-- 6/6 job_tag —— 岗位横切标签（多选）
-- ---------------------------------------------------------------------------
-- 标签先做自由文本（轻量）。将来若要「标签分类 / 同义标签」，再补一张 tag 字典表
-- —— 本期不做，但本表结构不阻碍（plan §4.5）。
CREATE TABLE IF NOT EXISTS job_tag (
  id     BIGINT      NOT NULL AUTO_INCREMENT,
  job_id BIGINT      NOT NULL COMMENT 'FK job.id',
  tag    VARCHAR(32) NOT NULL COMMENT '高并发 / 分布式 / 校招 / 直播',
  PRIMARY KEY (id),
  CONSTRAINT uk_job_tag UNIQUE (job_id, tag),
  KEY idx_job_tag_tag (tag)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
  COMMENT='岗位横切标签（多选）';


-- ============================================================================
-- 扩展位：两张「现在不建、结构已想好」的表（M1.5.6）
-- ----------------------------------------------------------------------------
-- 只写注释不建表。完整说明与「什么时候建、怎么建」见 workspace/DELIVERY.md
-- 的「扩展位」一节 —— 放在那里是因为它属于交付说明，不属于建表脚本。
--
-- 扩展位 1：analysis_record —— 分析历史（含岗位快照）
--   id BIGINT AI PK / trace_id CHAR(36) / resume_hash CHAR(64) / job_id BIGINT NULL /
--   job_snapshot TEXT（分析当时的岗位+技能要求快照 JSON）/ match_score INT /
--   result_json TEXT NOT NULL / created_at TIMESTAMP
--   UNIQUE uk_analysis_trace (trace_id)
--   ★ job_snapshot 是「软删」的另一半：岗位被改或被归档后，历史记录里的分数
--     仍能解释「当时为什么是 82 分」。没有它，软删只是把行留下，语义仍然悬空。
--
-- 扩展位 2：job_revision —— JD 变更历史（审计 / 回滚）
--   id BIGINT AI PK / job_id BIGINT / revision_no INT / content_hash CHAR(64) /
--   jd_raw MEDIUMTEXT / changed_by VARCHAR(64) NULL / changed_at TIMESTAMP
--   UNIQUE uk_job_rev (job_id, revision_no)
-- ============================================================================


-- ---------------------------------------------------------------------------
-- 关于「为什么没有 FOREIGN KEY 约束」
-- ---------------------------------------------------------------------------
-- plan §4 的 DDL 只声明了 uk_* 与索引，没有 FK 约束，本文件严格照抄。理由是：
--   ① 分类/技能是「可归档的字典」——加 FK 后归档（status='archived'）不影响，
--      但删一行字典就会被外键挡住，与「只插行不改结构」的演进方式不冲突却也无收益；
--   ② 幂等导入的顺序耦合已由 gen-seed.sh 的分节顺序（category → skill → job →
--      requirement → tag）保证；
--   ③ 完整性由 M3.5 的 seed 一致性校验脚本在 CI 里把关（比数据库报错更早、更准）。
-- 若将来要求强约束，加 FK 是一次纯增量 DDL，不影响已有数据。
-- ============================================================================
