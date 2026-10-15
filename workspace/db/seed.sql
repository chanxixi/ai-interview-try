-- ============================================================================
-- CareerLens · part2 种子数据（db/seed.sql）
-- ----------------------------------------------------------------------------
-- ⚠️ 本文件由 scripts/gen-seed.sh（内部 scripts/gen_seed.py）生成，**禁止手改**。
--    要改数据 → 改下面这些源 → 复跑脚本 → 重启（幂等导入）：
--      apps/analyzer/app/data/skills.yaml   技能词典真源（C4）
--      db/seed/categories.json              岗位分类树（D1：数据不是代码）
--      db/seed/jobs/*.json                  岗位源，一岗一文件
--
-- MySQL 8.0 与 H2（MODE=MySQL）**共用这一份**（spec §2.9）。
-- 幂等：字典/关联表走 ON DUPLICATE KEY UPDATE；job 表走「缺则插 + 变了才更」，
--       并带 source='seed' 守卫 —— 重复导入行数不变（AC23），且不覆盖人工录入。
-- 不删除任何行：岗位下架走 status='archived'（D2：只软删）。
--
-- 输入指纹 sha256: 433954e7bc11fa39db526ab2dbb5b908329d1c14b8cdcdf9295be834d51a7940
-- 规模: 分类 14 · 技能 83 · 别名 79 · 岗位 7 · 技能要求 66
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1/5 job_category —— 岗位分类树（父行在前，子行先插再单独 UPDATE 回填 parent_id）
--     新增一类岗位 = 在 categories.json 加一行 + 复跑本脚本，不改 Java 代码（D1）
--     ⚠️ parent_id 拆成两条语句是为了绕开 MySQL 的 ERROR 1093：
--        ON DUPLICATE KEY UPDATE 子句里不能引用目标表（派生表也拦），
--        INSERT 的 VALUES 子查询则必须套派生表 —— 详见 gen_seed.py 里的实测注释。
--     ⚠️ 更新语句**不写 status**：运营把某分类归档后，重复导入不该把它复活
--        （与 AC23「岗位置 archived 后行仍在、但不再进候选」同一条规则）
-- ----------------------------------------------------------------------------
INSERT INTO job_category (code, name, parent_id, level, sort_order, status) VALUES (
  'tech', '技术', NULL, 1, 10, 'active'
) ON DUPLICATE KEY UPDATE
  name = '技术', level = 1, sort_order = 10;
INSERT INTO job_category (code, name, parent_id, level, sort_order, status) VALUES (
  'product', '产品', NULL, 1, 20, 'active'
) ON DUPLICATE KEY UPDATE
  name = '产品', level = 1, sort_order = 20;
INSERT INTO job_category (code, name, parent_id, level, sort_order, status) VALUES (
  'operation', '运营', NULL, 1, 30, 'active'
) ON DUPLICATE KEY UPDATE
  name = '运营', level = 1, sort_order = 30;
INSERT INTO job_category (code, name, parent_id, level, sort_order, status) VALUES (
  'finance', '财务', NULL, 1, 40, 'active'
) ON DUPLICATE KEY UPDATE
  name = '财务', level = 1, sort_order = 40;
INSERT INTO job_category (code, name, parent_id, level, sort_order, status) VALUES (
  'marketing', '市场', NULL, 1, 50, 'active'
) ON DUPLICATE KEY UPDATE
  name = '市场', level = 1, sort_order = 50;
INSERT INTO job_category (code, name, parent_id, level, sort_order, status) VALUES (
  'design', '设计', NULL, 1, 60, 'active'
) ON DUPLICATE KEY UPDATE
  name = '设计', level = 1, sort_order = 60;
INSERT INTO job_category (code, name, parent_id, level, sort_order, status) VALUES (
  'tech-backend', '后端开发', (SELECT _p.id FROM (SELECT id FROM job_category WHERE code = 'tech') AS _p), 2, 10, 'active'
) ON DUPLICATE KEY UPDATE
  name = '后端开发', level = 2, sort_order = 10;
UPDATE job_category SET parent_id = (SELECT _p.id FROM (SELECT id FROM job_category WHERE code = 'tech') AS _p) WHERE code = 'tech-backend';
INSERT INTO job_category (code, name, parent_id, level, sort_order, status) VALUES (
  'tech-frontend', '前端开发', (SELECT _p.id FROM (SELECT id FROM job_category WHERE code = 'tech') AS _p), 2, 20, 'active'
) ON DUPLICATE KEY UPDATE
  name = '前端开发', level = 2, sort_order = 20;
UPDATE job_category SET parent_id = (SELECT _p.id FROM (SELECT id FROM job_category WHERE code = 'tech') AS _p) WHERE code = 'tech-frontend';
INSERT INTO job_category (code, name, parent_id, level, sort_order, status) VALUES (
  'tech-fullstack', '全栈开发', (SELECT _p.id FROM (SELECT id FROM job_category WHERE code = 'tech') AS _p), 2, 30, 'active'
) ON DUPLICATE KEY UPDATE
  name = '全栈开发', level = 2, sort_order = 30;
UPDATE job_category SET parent_id = (SELECT _p.id FROM (SELECT id FROM job_category WHERE code = 'tech') AS _p) WHERE code = 'tech-fullstack';
INSERT INTO job_category (code, name, parent_id, level, sort_order, status) VALUES (
  'tech-algorithm', '算法 / 数据', (SELECT _p.id FROM (SELECT id FROM job_category WHERE code = 'tech') AS _p), 2, 40, 'active'
) ON DUPLICATE KEY UPDATE
  name = '算法 / 数据', level = 2, sort_order = 40;
UPDATE job_category SET parent_id = (SELECT _p.id FROM (SELECT id FROM job_category WHERE code = 'tech') AS _p) WHERE code = 'tech-algorithm';
INSERT INTO job_category (code, name, parent_id, level, sort_order, status) VALUES (
  'tech-qa', '测试', (SELECT _p.id FROM (SELECT id FROM job_category WHERE code = 'tech') AS _p), 2, 50, 'active'
) ON DUPLICATE KEY UPDATE
  name = '测试', level = 2, sort_order = 50;
UPDATE job_category SET parent_id = (SELECT _p.id FROM (SELECT id FROM job_category WHERE code = 'tech') AS _p) WHERE code = 'tech-qa';
INSERT INTO job_category (code, name, parent_id, level, sort_order, status) VALUES (
  'tech-devops', '运维 / DevOps', (SELECT _p.id FROM (SELECT id FROM job_category WHERE code = 'tech') AS _p), 2, 60, 'active'
) ON DUPLICATE KEY UPDATE
  name = '运维 / DevOps', level = 2, sort_order = 60;
UPDATE job_category SET parent_id = (SELECT _p.id FROM (SELECT id FROM job_category WHERE code = 'tech') AS _p) WHERE code = 'tech-devops';
INSERT INTO job_category (code, name, parent_id, level, sort_order, status) VALUES (
  'tech-mobile', '客户端', (SELECT _p.id FROM (SELECT id FROM job_category WHERE code = 'tech') AS _p), 2, 70, 'active'
) ON DUPLICATE KEY UPDATE
  name = '客户端', level = 2, sort_order = 70;
UPDATE job_category SET parent_id = (SELECT _p.id FROM (SELECT id FROM job_category WHERE code = 'tech') AS _p) WHERE code = 'tech-mobile';
INSERT INTO job_category (code, name, parent_id, level, sort_order, status) VALUES (
  'tech-security', '安全 / 风控', (SELECT _p.id FROM (SELECT id FROM job_category WHERE code = 'tech') AS _p), 2, 80, 'active'
) ON DUPLICATE KEY UPDATE
  name = '安全 / 风控', level = 2, sort_order = 80;
UPDATE job_category SET parent_id = (SELECT _p.id FROM (SELECT id FROM job_category WHERE code = 'tech') AS _p) WHERE code = 'tech-security';

-- ----------------------------------------------------------------------------
-- 2/5 skill —— 技能标准名（真源：app/data/skills.yaml，C4）
-- ----------------------------------------------------------------------------
INSERT INTO skill (canonical, category, status) VALUES ('Java', 'language', 'active')
  ON DUPLICATE KEY UPDATE category = 'language';
INSERT INTO skill (canonical, category, status) VALUES ('JavaScript', 'language', 'active')
  ON DUPLICATE KEY UPDATE category = 'language';
INSERT INTO skill (canonical, category, status) VALUES ('TypeScript', 'language', 'active')
  ON DUPLICATE KEY UPDATE category = 'language';
INSERT INTO skill (canonical, category, status) VALUES ('Python', 'language', 'active')
  ON DUPLICATE KEY UPDATE category = 'language';
INSERT INTO skill (canonical, category, status) VALUES ('Go', 'language', 'active')
  ON DUPLICATE KEY UPDATE category = 'language';
INSERT INTO skill (canonical, category, status) VALUES ('C++', 'language', 'active')
  ON DUPLICATE KEY UPDATE category = 'language';
INSERT INTO skill (canonical, category, status) VALUES ('C', 'language', 'active')
  ON DUPLICATE KEY UPDATE category = 'language';
INSERT INTO skill (canonical, category, status) VALUES ('C#', 'language', 'active')
  ON DUPLICATE KEY UPDATE category = 'language';
INSERT INTO skill (canonical, category, status) VALUES ('Kotlin', 'language', 'active')
  ON DUPLICATE KEY UPDATE category = 'language';
INSERT INTO skill (canonical, category, status) VALUES ('Rust', 'language', 'active')
  ON DUPLICATE KEY UPDATE category = 'language';
INSERT INTO skill (canonical, category, status) VALUES ('Spring Boot', 'framework', 'active')
  ON DUPLICATE KEY UPDATE category = 'framework';
INSERT INTO skill (canonical, category, status) VALUES ('Spring Cloud', 'framework', 'active')
  ON DUPLICATE KEY UPDATE category = 'framework';
INSERT INTO skill (canonical, category, status) VALUES ('Spring MVC', 'framework', 'active')
  ON DUPLICATE KEY UPDATE category = 'framework';
INSERT INTO skill (canonical, category, status) VALUES ('Spring Security', 'framework', 'active')
  ON DUPLICATE KEY UPDATE category = 'framework';
INSERT INTO skill (canonical, category, status) VALUES ('MyBatis', 'framework', 'active')
  ON DUPLICATE KEY UPDATE category = 'framework';
INSERT INTO skill (canonical, category, status) VALUES ('MyBatis-Plus', 'framework', 'active')
  ON DUPLICATE KEY UPDATE category = 'framework';
INSERT INTO skill (canonical, category, status) VALUES ('Hibernate', 'framework', 'active')
  ON DUPLICATE KEY UPDATE category = 'framework';
INSERT INTO skill (canonical, category, status) VALUES ('Node.js', 'framework', 'active')
  ON DUPLICATE KEY UPDATE category = 'framework';
INSERT INTO skill (canonical, category, status) VALUES ('Koa', 'framework', 'active')
  ON DUPLICATE KEY UPDATE category = 'framework';
INSERT INTO skill (canonical, category, status) VALUES ('Express', 'framework', 'active')
  ON DUPLICATE KEY UPDATE category = 'framework';
INSERT INTO skill (canonical, category, status) VALUES ('NestJS', 'framework', 'active')
  ON DUPLICATE KEY UPDATE category = 'framework';
INSERT INTO skill (canonical, category, status) VALUES ('Django', 'framework', 'active')
  ON DUPLICATE KEY UPDATE category = 'framework';
INSERT INTO skill (canonical, category, status) VALUES ('Flask', 'framework', 'active')
  ON DUPLICATE KEY UPDATE category = 'framework';
INSERT INTO skill (canonical, category, status) VALUES ('FastAPI', 'framework', 'active')
  ON DUPLICATE KEY UPDATE category = 'framework';
INSERT INTO skill (canonical, category, status) VALUES ('Gin', 'framework', 'active')
  ON DUPLICATE KEY UPDATE category = 'framework';
INSERT INTO skill (canonical, category, status) VALUES ('MySQL', 'db', 'active')
  ON DUPLICATE KEY UPDATE category = 'db';
INSERT INTO skill (canonical, category, status) VALUES ('PostgreSQL', 'db', 'active')
  ON DUPLICATE KEY UPDATE category = 'db';
INSERT INTO skill (canonical, category, status) VALUES ('Oracle', 'db', 'active')
  ON DUPLICATE KEY UPDATE category = 'db';
INSERT INTO skill (canonical, category, status) VALUES ('SQL Server', 'db', 'active')
  ON DUPLICATE KEY UPDATE category = 'db';
INSERT INTO skill (canonical, category, status) VALUES ('MongoDB', 'db', 'active')
  ON DUPLICATE KEY UPDATE category = 'db';
INSERT INTO skill (canonical, category, status) VALUES ('Redis', 'db', 'active')
  ON DUPLICATE KEY UPDATE category = 'db';
INSERT INTO skill (canonical, category, status) VALUES ('Elasticsearch', 'db', 'active')
  ON DUPLICATE KEY UPDATE category = 'db';
INSERT INTO skill (canonical, category, status) VALUES ('SQLite', 'db', 'active')
  ON DUPLICATE KEY UPDATE category = 'db';
INSERT INTO skill (canonical, category, status) VALUES ('ClickHouse', 'db', 'active')
  ON DUPLICATE KEY UPDATE category = 'db';
INSERT INTO skill (canonical, category, status) VALUES ('HBase', 'db', 'active')
  ON DUPLICATE KEY UPDATE category = 'db';
INSERT INTO skill (canonical, category, status) VALUES ('Kafka', 'middleware', 'active')
  ON DUPLICATE KEY UPDATE category = 'middleware';
INSERT INTO skill (canonical, category, status) VALUES ('RabbitMQ', 'middleware', 'active')
  ON DUPLICATE KEY UPDATE category = 'middleware';
INSERT INTO skill (canonical, category, status) VALUES ('RocketMQ', 'middleware', 'active')
  ON DUPLICATE KEY UPDATE category = 'middleware';
INSERT INTO skill (canonical, category, status) VALUES ('Nginx', 'middleware', 'active')
  ON DUPLICATE KEY UPDATE category = 'middleware';
INSERT INTO skill (canonical, category, status) VALUES ('ZooKeeper', 'middleware', 'active')
  ON DUPLICATE KEY UPDATE category = 'middleware';
INSERT INTO skill (canonical, category, status) VALUES ('Netty', 'middleware', 'active')
  ON DUPLICATE KEY UPDATE category = 'middleware';
INSERT INTO skill (canonical, category, status) VALUES ('gRPC', 'middleware', 'active')
  ON DUPLICATE KEY UPDATE category = 'middleware';
INSERT INTO skill (canonical, category, status) VALUES ('Dubbo', 'middleware', 'active')
  ON DUPLICATE KEY UPDATE category = 'middleware';
INSERT INTO skill (canonical, category, status) VALUES ('TCP/IP', 'middleware', 'active')
  ON DUPLICATE KEY UPDATE category = 'middleware';
INSERT INTO skill (canonical, category, status) VALUES ('libevent', 'middleware', 'active')
  ON DUPLICATE KEY UPDATE category = 'middleware';
INSERT INTO skill (canonical, category, status) VALUES ('Vue', 'frontend', 'active')
  ON DUPLICATE KEY UPDATE category = 'frontend';
INSERT INTO skill (canonical, category, status) VALUES ('React', 'frontend', 'active')
  ON DUPLICATE KEY UPDATE category = 'frontend';
INSERT INTO skill (canonical, category, status) VALUES ('Angular', 'frontend', 'active')
  ON DUPLICATE KEY UPDATE category = 'frontend';
INSERT INTO skill (canonical, category, status) VALUES ('Element Plus', 'frontend', 'active')
  ON DUPLICATE KEY UPDATE category = 'frontend';
INSERT INTO skill (canonical, category, status) VALUES ('ECharts', 'frontend', 'active')
  ON DUPLICATE KEY UPDATE category = 'frontend';
INSERT INTO skill (canonical, category, status) VALUES ('Vite', 'frontend', 'active')
  ON DUPLICATE KEY UPDATE category = 'frontend';
INSERT INTO skill (canonical, category, status) VALUES ('Webpack', 'frontend', 'active')
  ON DUPLICATE KEY UPDATE category = 'frontend';
INSERT INTO skill (canonical, category, status) VALUES ('HTML', 'frontend', 'active')
  ON DUPLICATE KEY UPDATE category = 'frontend';
INSERT INTO skill (canonical, category, status) VALUES ('CSS', 'frontend', 'active')
  ON DUPLICATE KEY UPDATE category = 'frontend';
INSERT INTO skill (canonical, category, status) VALUES ('Sass', 'frontend', 'active')
  ON DUPLICATE KEY UPDATE category = 'frontend';
INSERT INTO skill (canonical, category, status) VALUES ('Tailwind CSS', 'frontend', 'active')
  ON DUPLICATE KEY UPDATE category = 'frontend';
INSERT INTO skill (canonical, category, status) VALUES ('Docker', 'devops', 'active')
  ON DUPLICATE KEY UPDATE category = 'devops';
INSERT INTO skill (canonical, category, status) VALUES ('Kubernetes', 'devops', 'active')
  ON DUPLICATE KEY UPDATE category = 'devops';
INSERT INTO skill (canonical, category, status) VALUES ('Jenkins', 'devops', 'active')
  ON DUPLICATE KEY UPDATE category = 'devops';
INSERT INTO skill (canonical, category, status) VALUES ('GitHub Actions', 'devops', 'active')
  ON DUPLICATE KEY UPDATE category = 'devops';
INSERT INTO skill (canonical, category, status) VALUES ('GitLab CI', 'devops', 'active')
  ON DUPLICATE KEY UPDATE category = 'devops';
INSERT INTO skill (canonical, category, status) VALUES ('Linux', 'devops', 'active')
  ON DUPLICATE KEY UPDATE category = 'devops';
INSERT INTO skill (canonical, category, status) VALUES ('Shell', 'devops', 'active')
  ON DUPLICATE KEY UPDATE category = 'devops';
INSERT INTO skill (canonical, category, status) VALUES ('Prometheus', 'devops', 'active')
  ON DUPLICATE KEY UPDATE category = 'devops';
INSERT INTO skill (canonical, category, status) VALUES ('Grafana', 'devops', 'active')
  ON DUPLICATE KEY UPDATE category = 'devops';
INSERT INTO skill (canonical, category, status) VALUES ('Ansible', 'devops', 'active')
  ON DUPLICATE KEY UPDATE category = 'devops';
INSERT INTO skill (canonical, category, status) VALUES ('Git', 'tool', 'active')
  ON DUPLICATE KEY UPDATE category = 'tool';
INSERT INTO skill (canonical, category, status) VALUES ('Maven', 'tool', 'active')
  ON DUPLICATE KEY UPDATE category = 'tool';
INSERT INTO skill (canonical, category, status) VALUES ('Gradle', 'tool', 'active')
  ON DUPLICATE KEY UPDATE category = 'tool';
INSERT INTO skill (canonical, category, status) VALUES ('npm', 'tool', 'active')
  ON DUPLICATE KEY UPDATE category = 'tool';
INSERT INTO skill (canonical, category, status) VALUES ('Postman', 'tool', 'active')
  ON DUPLICATE KEY UPDATE category = 'tool';
INSERT INTO skill (canonical, category, status) VALUES ('Jira', 'tool', 'active')
  ON DUPLICATE KEY UPDATE category = 'tool';
INSERT INTO skill (canonical, category, status) VALUES ('CMake', 'tool', 'active')
  ON DUPLICATE KEY UPDATE category = 'tool';
INSERT INTO skill (canonical, category, status) VALUES ('gtest', 'tool', 'active')
  ON DUPLICATE KEY UPDATE category = 'tool';
INSERT INTO skill (canonical, category, status) VALUES ('JUnit', 'tool', 'active')
  ON DUPLICATE KEY UPDATE category = 'tool';
INSERT INTO skill (canonical, category, status) VALUES ('pytest', 'tool', 'active')
  ON DUPLICATE KEY UPDATE category = 'tool';
INSERT INTO skill (canonical, category, status) VALUES ('Swagger', 'tool', 'active')
  ON DUPLICATE KEY UPDATE category = 'tool';
INSERT INTO skill (canonical, category, status) VALUES ('LLM', 'ai', 'active')
  ON DUPLICATE KEY UPDATE category = 'ai';
INSERT INTO skill (canonical, category, status) VALUES ('RAG', 'ai', 'active')
  ON DUPLICATE KEY UPDATE category = 'ai';
INSERT INTO skill (canonical, category, status) VALUES ('Prompt Engineering', 'ai', 'active')
  ON DUPLICATE KEY UPDATE category = 'ai';
INSERT INTO skill (canonical, category, status) VALUES ('LangChain', 'ai', 'active')
  ON DUPLICATE KEY UPDATE category = 'ai';
INSERT INTO skill (canonical, category, status) VALUES ('PyTorch', 'ai', 'active')
  ON DUPLICATE KEY UPDATE category = 'ai';
INSERT INTO skill (canonical, category, status) VALUES ('TensorFlow', 'ai', 'active')
  ON DUPLICATE KEY UPDATE category = 'ai';

-- ----------------------------------------------------------------------------
-- 3/5 skill_alias —— 别名（归一化的第二跳；alias 全局唯一，大小写不敏感）
-- ----------------------------------------------------------------------------
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'Java'), 'JDK')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'Java');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'Java'), 'J2EE')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'Java');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'Java'), 'JavaSE')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'Java');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'JavaScript'), 'ECMAScript')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'JavaScript');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'JavaScript'), 'ES6')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'JavaScript');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'Python'), 'python3')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'Python');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'Go'), 'Golang')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'Go');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'C++'), 'CPP')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'C++');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'C++'), 'C/C++')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'C++');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'C'), 'ANSI C')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'C');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'C#'), 'CSharp')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'C#');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'C#'), 'C Sharp')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'C#');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'Rust'), 'rust-lang')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'Rust');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'Spring Boot'), 'SpringBoot')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'Spring Boot');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'Spring Cloud'), 'SpringCloud')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'Spring Cloud');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'Spring MVC'), 'SpringMVC')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'Spring MVC');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'MyBatis'), 'ibatis')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'MyBatis');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'MyBatis-Plus'), 'MyBatisPlus')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'MyBatis-Plus');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'Hibernate'), 'JPA')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'Hibernate');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'Node.js'), 'NodeJS')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'Node.js');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'Koa'), 'Koa2')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'Koa');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'Koa'), 'koajs')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'Koa');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'Express'), 'expressjs')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'Express');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'NestJS'), 'nest.js')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'NestJS');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'Django'), 'DRF')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'Django');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'FastAPI'), 'fast-api')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'FastAPI');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'Gin'), 'gin-gonic')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'Gin');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'MySQL'), 'MariaDB')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'MySQL');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'PostgreSQL'), 'PG')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'PostgreSQL');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'PostgreSQL'), 'postgres')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'PostgreSQL');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'PostgreSQL'), 'pgsql')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'PostgreSQL');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'Oracle'), 'PL/SQL')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'Oracle');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'SQL Server'), 'MSSQL')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'SQL Server');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'SQL Server'), 'SQLServer')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'SQL Server');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'MongoDB'), 'mongo')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'MongoDB');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'Elasticsearch'), 'ES')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'Elasticsearch');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'SQLite'), 'sqlite3')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'SQLite');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'Kafka'), 'Apache Kafka')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'Kafka');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'RabbitMQ'), 'rabbit mq')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'RabbitMQ');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'RocketMQ'), 'Rocket MQ')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'RocketMQ');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'ZooKeeper'), 'ZK')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'ZooKeeper');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'gRPC'), 'Google RPC')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'gRPC');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'TCP/IP'), 'TCP')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'TCP/IP');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'TCP/IP'), 'tcpip')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'TCP/IP');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'Vue'), 'Vue.js')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'Vue');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'Vue'), 'vuejs')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'Vue');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'Vue'), 'vue3')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'Vue');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'Vue'), 'vue2')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'Vue');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'React'), 'React.js')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'React');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'React'), 'reactjs')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'React');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'Angular'), 'AngularJS')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'Angular');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'Element Plus'), 'ElementPlus')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'Element Plus');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'Element Plus'), 'element-ui')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'Element Plus');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'ECharts'), 'Apache ECharts')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'ECharts');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'Vite'), 'vitejs')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'Vite');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'Webpack'), 'webpack5')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'Webpack');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'HTML'), 'HTML5')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'HTML');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'CSS'), 'CSS3')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'CSS');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'Sass'), 'SCSS')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'Sass');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'Tailwind CSS'), 'tailwindcss')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'Tailwind CSS');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'Docker'), 'Docker Compose')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'Docker');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'Kubernetes'), 'K8s')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'Kubernetes');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'GitHub Actions'), 'github-actions')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'GitHub Actions');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'GitLab CI'), 'gitlab-ci')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'GitLab CI');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'Linux'), 'CentOS')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'Linux');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'Linux'), 'Ubuntu')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'Linux');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'Shell'), 'Bash')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'Shell');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'Maven'), 'MVN')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'Maven');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'npm'), 'pnpm')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'npm');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'npm'), 'yarn')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'npm');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'gtest'), 'Google Test')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'gtest');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'JUnit'), 'junit5')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'JUnit');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'Swagger'), 'OpenAPI')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'Swagger');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'Swagger'), 'springdoc')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'Swagger');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'LLM'), '大模型')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'LLM');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'LLM'), '大语言模型')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'LLM');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'RAG'), '检索增强生成')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'RAG');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'Prompt Engineering'), 'Prompt 工程')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'Prompt Engineering');
INSERT INTO skill_alias (skill_id, alias) VALUES ((SELECT id FROM skill WHERE canonical = 'Prompt Engineering'), '提示词工程')
  ON DUPLICATE KEY UPDATE skill_id = (SELECT id FROM skill WHERE canonical = 'Prompt Engineering');

-- ----------------------------------------------------------------------------
-- 4/5 job —— 岗位主表（含 JD 原文）
--     ① 缺则插：WHERE NOT EXISTS 保证重复导入不新增行（AC23）
--     ② 变了才更：UPDATE 的 WHERE 逐列比对「这行与源是否不一致」。
--        为什么不只比 content_hash：hash 是**由源算出来的**，入库后就不再变；
--        若有人在库里改了 title 却没动 hash，只比 hash 会认为「已同步」而漏掉这次漂移。
--        逐列比对把 level / category_id 这两个不在 hash 里的字段也覆盖到了。
--        好处：内容没变就一个字节都不写 → version 不涨、updated_at 不动，
--        不会出现「每次重启版本号自己涨一格」这种像 bug 的现象。
--     ③ source='seed' 守卫：绝不覆盖人工录入的行（spec §2.9）
--     ④ 更新语句**不写 status**：已归档的岗位重复导入不会被复活（AC23）
-- ----------------------------------------------------------------------------
-- job-algorithm-01 · 算法工程师（推荐 / 大模型方向） @ 某短视频公司 [tech-algorithm]
INSERT INTO job (code, title, company, level, category_id, jd_raw, content_hash,
                 attributes, source, status, version)
SELECT 'job-algorithm-01', '算法工程师（推荐 / 大模型方向）', '某短视频公司', '校招', (SELECT id FROM job_category WHERE code = 'tech-algorithm'),
       '岗位职责：
1、负责推荐与搜索场景的召回、排序算法设计与迭代；
2、参与大模型应用落地，包括 RAG 检索增强与效果评估；
3、与工程团队协作完成算法服务的上线与监控。

任职要求：
1、硕士及以上学历，计算机、数学或相关专业；
2、精通Python，熟悉常用数据结构与算法；
3、熟悉PyTorch，具备深度学习模型训练与调优经验；
4、熟悉RAG检索增强生成的技术链路，了解向量检索与重排；
5、熟悉LLM大模型应用开发，掌握 Prompt Engineering 与提示词设计方法；
6、熟悉Linux开发环境与Shell脚本。

加分项：
1、熟悉LangChain等大模型应用框架者优先；
2、有TensorFlow使用经验者优先；
3、有Kafka等流式数据处理经验者优先。',
       '9aa5f6465bc8f666ff4ac08ebf6c1a2628d179da3be9b33b33419aae4301ebb8', NULL, 'seed', 'active', 1
FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM job WHERE code = 'job-algorithm-01');
UPDATE job SET
  title = '算法工程师（推荐 / 大模型方向）', company = '某短视频公司', level = '校招', category_id = (SELECT id FROM job_category WHERE code = 'tech-algorithm'),
  jd_raw = '岗位职责：
1、负责推荐与搜索场景的召回、排序算法设计与迭代；
2、参与大模型应用落地，包括 RAG 检索增强与效果评估；
3、与工程团队协作完成算法服务的上线与监控。

任职要求：
1、硕士及以上学历，计算机、数学或相关专业；
2、精通Python，熟悉常用数据结构与算法；
3、熟悉PyTorch，具备深度学习模型训练与调优经验；
4、熟悉RAG检索增强生成的技术链路，了解向量检索与重排；
5、熟悉LLM大模型应用开发，掌握 Prompt Engineering 与提示词设计方法；
6、熟悉Linux开发环境与Shell脚本。

加分项：
1、熟悉LangChain等大模型应用框架者优先；
2、有TensorFlow使用经验者优先；
3、有Kafka等流式数据处理经验者优先。', content_hash = '9aa5f6465bc8f666ff4ac08ebf6c1a2628d179da3be9b33b33419aae4301ebb8',
  version = version + 1, updated_at = CURRENT_TIMESTAMP
WHERE code = 'job-algorithm-01' AND source = 'seed'
  AND (content_hash <> '9aa5f6465bc8f666ff4ac08ebf6c1a2628d179da3be9b33b33419aae4301ebb8' OR title <> '算法工程师（推荐 / 大模型方向）' OR company <> '某短视频公司' OR level <> '校招' OR category_id <> (SELECT id FROM job_category WHERE code = 'tech-algorithm'));

-- job-backend-01 · Java 后端开发工程师 @ 某电商科技 [tech-backend]
INSERT INTO job (code, title, company, level, category_id, jd_raw, content_hash,
                 attributes, source, status, version)
SELECT 'job-backend-01', 'Java 后端开发工程师', '某电商科技', '社招', (SELECT id FROM job_category WHERE code = 'tech-backend'),
       '岗位职责：
1、负责公司核心业务系统的后端设计与开发，保障服务稳定性；
2、参与微服务拆分与治理，持续优化接口性能与数据库访问效率；
3、编写单元测试与技术文档，参与代码评审。

任职要求：
1、本科及以上学历，计算机相关专业；
2、精通Java，熟悉JVM内存模型与垃圾回收机制；
3、熟练使用Spring Boot、MyBatis进行业务开发；
4、了解Spring Cloud微服务生态；
5、熟悉MySQL，具备索引设计与慢查询优化经验；
6、熟悉Redis，了解缓存穿透、击穿、雪崩的应对方案；
7、熟悉Kafka等消息中间件，理解异步解耦与削峰填谷；
8、熟悉Linux常用命令，能独立完成服务部署与问题排查；
9、熟悉Git协作流程与Maven构建。

加分项：
1、熟悉Docker与Kubernetes，有容器化部署经验者优先；
2、有高并发项目经验者优先。',
       '0bc564c96bfc659bf6776887b709f1f4e7f0297d93b64f48a951da5d13a1cc78', NULL, 'seed', 'active', 1
FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM job WHERE code = 'job-backend-01');
UPDATE job SET
  title = 'Java 后端开发工程师', company = '某电商科技', level = '社招', category_id = (SELECT id FROM job_category WHERE code = 'tech-backend'),
  jd_raw = '岗位职责：
1、负责公司核心业务系统的后端设计与开发，保障服务稳定性；
2、参与微服务拆分与治理，持续优化接口性能与数据库访问效率；
3、编写单元测试与技术文档，参与代码评审。

任职要求：
1、本科及以上学历，计算机相关专业；
2、精通Java，熟悉JVM内存模型与垃圾回收机制；
3、熟练使用Spring Boot、MyBatis进行业务开发；
4、了解Spring Cloud微服务生态；
5、熟悉MySQL，具备索引设计与慢查询优化经验；
6、熟悉Redis，了解缓存穿透、击穿、雪崩的应对方案；
7、熟悉Kafka等消息中间件，理解异步解耦与削峰填谷；
8、熟悉Linux常用命令，能独立完成服务部署与问题排查；
9、熟悉Git协作流程与Maven构建。

加分项：
1、熟悉Docker与Kubernetes，有容器化部署经验者优先；
2、有高并发项目经验者优先。', content_hash = '0bc564c96bfc659bf6776887b709f1f4e7f0297d93b64f48a951da5d13a1cc78',
  version = version + 1, updated_at = CURRENT_TIMESTAMP
WHERE code = 'job-backend-01' AND source = 'seed'
  AND (content_hash <> '0bc564c96bfc659bf6776887b709f1f4e7f0297d93b64f48a951da5d13a1cc78' OR title <> 'Java 后端开发工程师' OR company <> '某电商科技' OR level <> '社招' OR category_id <> (SELECT id FROM job_category WHERE code = 'tech-backend'));

-- job-devops-01 · DevOps / 运维开发工程师 @ 某云服务商 [tech-devops]
INSERT INTO job (code, title, company, level, category_id, jd_raw, content_hash,
                 attributes, source, status, version)
SELECT 'job-devops-01', 'DevOps / 运维开发工程师', '某云服务商', '社招', (SELECT id FROM job_category WHERE code = 'tech-devops'),
       '岗位职责：
1、负责公司业务的容器化部署与 CI/CD 流程建设；
2、负责线上服务的监控、告警与容量规划；
3、参与故障复盘，推动稳定性改进。

任职要求：
1、本科及以上学历，计算机相关专业；
2、熟悉Linux系统管理与性能调优；
3、熟练使用Docker进行应用打包与部署；
4、了解Kubernetes编排；
5、熟悉Jenkins流水线配置；
6、有GitHub Actions使用经验；
7、熟悉Nginx反向代理与负载均衡配置；
8、熟悉Shell脚本与Python自动化脚本开发；
9、熟悉Prometheus与Grafana监控体系。

加分项：
1、熟悉Ansible自动化配置管理者优先；
2、熟悉MySQL主从复制与备份恢复者优先。',
       '2977a58643eedec2e9eba11b3af0b1b28d70b33bda18fa11fe1d84e6510254d2', NULL, 'seed', 'active', 1
FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM job WHERE code = 'job-devops-01');
UPDATE job SET
  title = 'DevOps / 运维开发工程师', company = '某云服务商', level = '社招', category_id = (SELECT id FROM job_category WHERE code = 'tech-devops'),
  jd_raw = '岗位职责：
1、负责公司业务的容器化部署与 CI/CD 流程建设；
2、负责线上服务的监控、告警与容量规划；
3、参与故障复盘，推动稳定性改进。

任职要求：
1、本科及以上学历，计算机相关专业；
2、熟悉Linux系统管理与性能调优；
3、熟练使用Docker进行应用打包与部署；
4、了解Kubernetes编排；
5、熟悉Jenkins流水线配置；
6、有GitHub Actions使用经验；
7、熟悉Nginx反向代理与负载均衡配置；
8、熟悉Shell脚本与Python自动化脚本开发；
9、熟悉Prometheus与Grafana监控体系。

加分项：
1、熟悉Ansible自动化配置管理者优先；
2、熟悉MySQL主从复制与备份恢复者优先。', content_hash = '2977a58643eedec2e9eba11b3af0b1b28d70b33bda18fa11fe1d84e6510254d2',
  version = version + 1, updated_at = CURRENT_TIMESTAMP
WHERE code = 'job-devops-01' AND source = 'seed'
  AND (content_hash <> '2977a58643eedec2e9eba11b3af0b1b28d70b33bda18fa11fe1d84e6510254d2' OR title <> 'DevOps / 运维开发工程师' OR company <> '某云服务商' OR level <> '社招' OR category_id <> (SELECT id FROM job_category WHERE code = 'tech-devops'));

-- job-frontend-01 · 前端开发工程师（Vue 方向） @ 某 SaaS 服务商 [tech-frontend]
INSERT INTO job (code, title, company, level, category_id, jd_raw, content_hash,
                 attributes, source, status, version)
SELECT 'job-frontend-01', '前端开发工程师（Vue 方向）', '某 SaaS 服务商', '社招', (SELECT id FROM job_category WHERE code = 'tech-frontend'),
       '岗位职责：
1、负责公司 B 端产品的前端开发与体验优化；
2、参与组件库建设与前端工程化改造；
3、与后端协作完成接口联调与数据可视化。

任职要求：
1、本科及以上学历，2 年以上前端开发经验；
2、精通HTML、CSS、JavaScript，熟悉ES6+语法；
3、熟练使用Vue，理解响应式原理与组件化开发；
4、熟悉TypeScript，具备良好的类型设计习惯；
5、熟悉Vite构建工具与前端工程化流程；
6、熟悉ECharts，能独立完成数据可视化需求；
7、熟悉Git协作流程。

加分项：
1、熟悉Element Plus组件库者优先；
2、了解Sass等 CSS 预处理语言者优先；
3、有React项目经验者优先。',
       '7b356a2c870a47d85d675b55c23446750a4134f2cf532ed700233ca0b73a6c5a', NULL, 'seed', 'active', 1
FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM job WHERE code = 'job-frontend-01');
UPDATE job SET
  title = '前端开发工程师（Vue 方向）', company = '某 SaaS 服务商', level = '社招', category_id = (SELECT id FROM job_category WHERE code = 'tech-frontend'),
  jd_raw = '岗位职责：
1、负责公司 B 端产品的前端开发与体验优化；
2、参与组件库建设与前端工程化改造；
3、与后端协作完成接口联调与数据可视化。

任职要求：
1、本科及以上学历，2 年以上前端开发经验；
2、精通HTML、CSS、JavaScript，熟悉ES6+语法；
3、熟练使用Vue，理解响应式原理与组件化开发；
4、熟悉TypeScript，具备良好的类型设计习惯；
5、熟悉Vite构建工具与前端工程化流程；
6、熟悉ECharts，能独立完成数据可视化需求；
7、熟悉Git协作流程。

加分项：
1、熟悉Element Plus组件库者优先；
2、了解Sass等 CSS 预处理语言者优先；
3、有React项目经验者优先。', content_hash = '7b356a2c870a47d85d675b55c23446750a4134f2cf532ed700233ca0b73a6c5a',
  version = version + 1, updated_at = CURRENT_TIMESTAMP
WHERE code = 'job-frontend-01' AND source = 'seed'
  AND (content_hash <> '7b356a2c870a47d85d675b55c23446750a4134f2cf532ed700233ca0b73a6c5a' OR title <> '前端开发工程师（Vue 方向）' OR company <> '某 SaaS 服务商' OR level <> '社招' OR category_id <> (SELECT id FROM job_category WHERE code = 'tech-frontend'));

-- job-fullstack-01 · 全栈开发工程师（直播/视频方向） @ 某直播平台 [tech-fullstack]
INSERT INTO job (code, title, company, level, category_id, jd_raw, content_hash,
                 attributes, source, status, version)
SELECT 'job-fullstack-01', '全栈开发工程师（直播/视频方向）', '某直播平台', '校招', (SELECT id FROM job_category WHERE code = 'tech-fullstack'),
       '岗位职责：
1、负责直播、视频、广告等核心业务的服务端设计与开发；
2、参与高并发、低延迟场景下的系统架构设计与性能优化；
3、与产品、前端、算法团队协作，完成从需求到上线的全流程交付；
4、参与技术方案评审，沉淀通用组件与最佳实践。

任职要求：
1、本科及以上学历，计算机相关专业；
2、熟悉C/C++/Java开发语言，具备良好的编程习惯与代码质量意识；
3、熟悉Linux网络编程，理解进程、线程、内存与文件系统的基本原理；
4、熟悉TCP/IP协议，掌握 epoll 等IO模型，了解常见的网络性能瓶颈；
5、熟悉MySQL、Redis等存储系统，理解索引、事务与缓存的基本原理；
6、熟悉Git、CMake、gtest等工具，具备工程化协作能力；
7、具备良好的沟通能力与团队协作意识，能承受一定的工作压力。

加分项：
1、有libevent/muduo等网络库使用经验者优先；
2、具备LLM大语言模型知识，有 RAG 或 Agent 相关实践经验者优先；
3、具备AI Coding经验者优先。',
       '3754f6782590eed0acc9e5444419a826a61d3109236621e32458e817edb3427f', NULL, 'seed', 'active', 1
FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM job WHERE code = 'job-fullstack-01');
UPDATE job SET
  title = '全栈开发工程师（直播/视频方向）', company = '某直播平台', level = '校招', category_id = (SELECT id FROM job_category WHERE code = 'tech-fullstack'),
  jd_raw = '岗位职责：
1、负责直播、视频、广告等核心业务的服务端设计与开发；
2、参与高并发、低延迟场景下的系统架构设计与性能优化；
3、与产品、前端、算法团队协作，完成从需求到上线的全流程交付；
4、参与技术方案评审，沉淀通用组件与最佳实践。

任职要求：
1、本科及以上学历，计算机相关专业；
2、熟悉C/C++/Java开发语言，具备良好的编程习惯与代码质量意识；
3、熟悉Linux网络编程，理解进程、线程、内存与文件系统的基本原理；
4、熟悉TCP/IP协议，掌握 epoll 等IO模型，了解常见的网络性能瓶颈；
5、熟悉MySQL、Redis等存储系统，理解索引、事务与缓存的基本原理；
6、熟悉Git、CMake、gtest等工具，具备工程化协作能力；
7、具备良好的沟通能力与团队协作意识，能承受一定的工作压力。

加分项：
1、有libevent/muduo等网络库使用经验者优先；
2、具备LLM大语言模型知识，有 RAG 或 Agent 相关实践经验者优先；
3、具备AI Coding经验者优先。', content_hash = '3754f6782590eed0acc9e5444419a826a61d3109236621e32458e817edb3427f',
  version = version + 1, updated_at = CURRENT_TIMESTAMP
WHERE code = 'job-fullstack-01' AND source = 'seed'
  AND (content_hash <> '3754f6782590eed0acc9e5444419a826a61d3109236621e32458e817edb3427f' OR title <> '全栈开发工程师（直播/视频方向）' OR company <> '某直播平台' OR level <> '校招' OR category_id <> (SELECT id FROM job_category WHERE code = 'tech-fullstack'));

-- job-operation-01 · 用户运营（直播业务） @ 某内容平台 [operation]
INSERT INTO job (code, title, company, level, category_id, jd_raw, content_hash,
                 attributes, source, status, version)
SELECT 'job-operation-01', '用户运营（直播业务）', '某内容平台', '校招', (SELECT id FROM job_category WHERE code = 'operation'),
       '岗位职责：
1、负责直播业务用户增长与留存运营，制定并落地运营策略；
2、负责活动策划与执行，跟踪核心指标并输出复盘报告；
3、与产品、数据团队协作，推动运营需求落地。

任职要求：
1、本科及以上学历，专业不限；
2、具备良好的沟通能力与团队协作意识；
3、有较强的数据分析意识，能熟练使用 Excel 等办公软件；
4、对直播、短视频行业有热情。

加分项：
1、有校园社团或新媒体运营经验者优先。',
       '61468350635538ba81fe11ab6244ad8b9b3a7a81b78e4223f248c3ad189a64b2', NULL, 'seed', 'active', 1
FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM job WHERE code = 'job-operation-01');
UPDATE job SET
  title = '用户运营（直播业务）', company = '某内容平台', level = '校招', category_id = (SELECT id FROM job_category WHERE code = 'operation'),
  jd_raw = '岗位职责：
1、负责直播业务用户增长与留存运营，制定并落地运营策略；
2、负责活动策划与执行，跟踪核心指标并输出复盘报告；
3、与产品、数据团队协作，推动运营需求落地。

任职要求：
1、本科及以上学历，专业不限；
2、具备良好的沟通能力与团队协作意识；
3、有较强的数据分析意识，能熟练使用 Excel 等办公软件；
4、对直播、短视频行业有热情。

加分项：
1、有校园社团或新媒体运营经验者优先。', content_hash = '61468350635538ba81fe11ab6244ad8b9b3a7a81b78e4223f248c3ad189a64b2',
  version = version + 1, updated_at = CURRENT_TIMESTAMP
WHERE code = 'job-operation-01' AND source = 'seed'
  AND (content_hash <> '61468350635538ba81fe11ab6244ad8b9b3a7a81b78e4223f248c3ad189a64b2' OR title <> '用户运营（直播业务）' OR company <> '某内容平台' OR level <> '校招' OR category_id <> (SELECT id FROM job_category WHERE code = 'operation'));

-- job-qa-01 · 测试开发工程师 @ 某金融科技 [tech-qa]
INSERT INTO job (code, title, company, level, category_id, jd_raw, content_hash,
                 attributes, source, status, version)
SELECT 'job-qa-01', '测试开发工程师', '某金融科技', '社招', (SELECT id FROM job_category WHERE code = 'tech-qa'),
       '岗位职责：
1、负责核心业务的服务端测试方案设计与执行；
2、建设接口自动化测试与回归测试体系；
3、参与质量度量与缺陷分析，推动研发流程改进。

任职要求：
1、本科及以上学历，计算机相关专业；
2、熟悉Java或Python，能独立编写自动化测试脚本；
3、熟练使用JUnit或pytest编写单元测试与接口测试；
4、熟悉Postman进行接口调试与用例管理；
5、熟悉MySQL，能编写 SQL 进行数据校验；
6、熟悉Linux常用命令与Shell脚本；
7、熟悉Git与Jira等研发协作工具。

加分项：
1、熟悉Jenkins持续集成者优先；
2、熟悉Docker容器化测试环境者优先。',
       '8728f03e5aa5dfb46179382643f908e99a0eca0a20733e1174399a577c99e44f', NULL, 'seed', 'active', 1
FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM job WHERE code = 'job-qa-01');
UPDATE job SET
  title = '测试开发工程师', company = '某金融科技', level = '社招', category_id = (SELECT id FROM job_category WHERE code = 'tech-qa'),
  jd_raw = '岗位职责：
1、负责核心业务的服务端测试方案设计与执行；
2、建设接口自动化测试与回归测试体系；
3、参与质量度量与缺陷分析，推动研发流程改进。

任职要求：
1、本科及以上学历，计算机相关专业；
2、熟悉Java或Python，能独立编写自动化测试脚本；
3、熟练使用JUnit或pytest编写单元测试与接口测试；
4、熟悉Postman进行接口调试与用例管理；
5、熟悉MySQL，能编写 SQL 进行数据校验；
6、熟悉Linux常用命令与Shell脚本；
7、熟悉Git与Jira等研发协作工具。

加分项：
1、熟悉Jenkins持续集成者优先；
2、熟悉Docker容器化测试环境者优先。', content_hash = '8728f03e5aa5dfb46179382643f908e99a0eca0a20733e1174399a577c99e44f',
  version = version + 1, updated_at = CURRENT_TIMESTAMP
WHERE code = 'job-qa-01' AND source = 'seed'
  AND (content_hash <> '8728f03e5aa5dfb46179382643f908e99a0eca0a20733e1174399a577c99e44f' OR title <> '测试开发工程师' OR company <> '某金融科技' OR level <> '社招' OR category_id <> (SELECT id FROM job_category WHERE code = 'tech-qa'));

-- ----------------------------------------------------------------------------
-- 5/5 job_requirement + job_tag
--     skill_id 由 canonical 子查询解析 —— 脚本已保证每个 skill 都在词典里（D3），
--     所以这里永远不会插入 skill_id 为 NULL 的行。
--     jd_offset 是 evidence 在 jd_raw 中的字符下标，由脚本算，不手写。
-- ----------------------------------------------------------------------------
-- job-algorithm-01
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-algorithm-01'), (SELECT id FROM skill WHERE canonical = 'Python'), 'Python', 'required', '精通Python，熟悉常用数据结构与算法', 117)
  ON DUPLICATE KEY UPDATE skill_raw = 'Python', importance = 'required', evidence = '精通Python，熟悉常用数据结构与算法', jd_offset = 117;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-algorithm-01'), (SELECT id FROM skill WHERE canonical = 'PyTorch'), 'PyTorch', 'required', '熟悉PyTorch，具备深度学习模型训练与调优经验', 141)
  ON DUPLICATE KEY UPDATE skill_raw = 'PyTorch', importance = 'required', evidence = '熟悉PyTorch，具备深度学习模型训练与调优经验', jd_offset = 141;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-algorithm-01'), (SELECT id FROM skill WHERE canonical = 'RAG'), 'RAG', 'required', '熟悉RAG检索增强生成的技术链路', 170)
  ON DUPLICATE KEY UPDATE skill_raw = 'RAG', importance = 'required', evidence = '熟悉RAG检索增强生成的技术链路', jd_offset = 170;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-algorithm-01'), (SELECT id FROM skill WHERE canonical = 'LLM'), 'LLM', 'required', '熟悉LLM大模型应用开发', 200)
  ON DUPLICATE KEY UPDATE skill_raw = 'LLM', importance = 'required', evidence = '熟悉LLM大模型应用开发', jd_offset = 200;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-algorithm-01'), (SELECT id FROM skill WHERE canonical = 'Prompt Engineering'), 'Prompt Engineering', 'required', '掌握 Prompt Engineering 与提示词设计方法', 213)
  ON DUPLICATE KEY UPDATE skill_raw = 'Prompt Engineering', importance = 'required', evidence = '掌握 Prompt Engineering 与提示词设计方法', jd_offset = 213;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-algorithm-01'), (SELECT id FROM skill WHERE canonical = 'Linux'), 'Linux', 'required', '熟悉Linux开发环境与Shell脚本', 247)
  ON DUPLICATE KEY UPDATE skill_raw = 'Linux', importance = 'required', evidence = '熟悉Linux开发环境与Shell脚本', jd_offset = 247;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-algorithm-01'), (SELECT id FROM skill WHERE canonical = 'Shell'), 'Shell', 'required', '熟悉Linux开发环境与Shell脚本', 247)
  ON DUPLICATE KEY UPDATE skill_raw = 'Shell', importance = 'required', evidence = '熟悉Linux开发环境与Shell脚本', jd_offset = 247;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-algorithm-01'), (SELECT id FROM skill WHERE canonical = 'LangChain'), 'LangChain', 'preferred', '熟悉LangChain等大模型应用框架者优先', 276)
  ON DUPLICATE KEY UPDATE skill_raw = 'LangChain', importance = 'preferred', evidence = '熟悉LangChain等大模型应用框架者优先', jd_offset = 276;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-algorithm-01'), (SELECT id FROM skill WHERE canonical = 'TensorFlow'), 'TensorFlow', 'preferred', '有TensorFlow使用经验者优先', 302)
  ON DUPLICATE KEY UPDATE skill_raw = 'TensorFlow', importance = 'preferred', evidence = '有TensorFlow使用经验者优先', jd_offset = 302;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-algorithm-01'), (SELECT id FROM skill WHERE canonical = 'Kafka'), 'Kafka', 'preferred', '有Kafka等流式数据处理经验者优先', 324)
  ON DUPLICATE KEY UPDATE skill_raw = 'Kafka', importance = 'preferred', evidence = '有Kafka等流式数据处理经验者优先', jd_offset = 324;
INSERT INTO job_tag (job_id, tag) VALUES ((SELECT id FROM job WHERE code = 'job-algorithm-01'), '推荐系统')
  ON DUPLICATE KEY UPDATE tag = '推荐系统';
INSERT INTO job_tag (job_id, tag) VALUES ((SELECT id FROM job WHERE code = 'job-algorithm-01'), '大模型')
  ON DUPLICATE KEY UPDATE tag = '大模型';
INSERT INTO job_tag (job_id, tag) VALUES ((SELECT id FROM job WHERE code = 'job-algorithm-01'), '校招')
  ON DUPLICATE KEY UPDATE tag = '校招';

-- job-backend-01
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-backend-01'), (SELECT id FROM skill WHERE canonical = 'Java'), 'Java', 'required', '精通Java，熟悉JVM内存模型与垃圾回收机制', 117)
  ON DUPLICATE KEY UPDATE skill_raw = 'Java', importance = 'required', evidence = '精通Java，熟悉JVM内存模型与垃圾回收机制', jd_offset = 117;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-backend-01'), (SELECT id FROM skill WHERE canonical = 'Spring Boot'), 'Spring Boot', 'required', '熟练使用Spring Boot、MyBatis进行业务开发', 144)
  ON DUPLICATE KEY UPDATE skill_raw = 'Spring Boot', importance = 'required', evidence = '熟练使用Spring Boot、MyBatis进行业务开发', jd_offset = 144;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-backend-01'), (SELECT id FROM skill WHERE canonical = 'MyBatis'), 'MyBatis', 'required', '熟练使用Spring Boot、MyBatis进行业务开发', 144)
  ON DUPLICATE KEY UPDATE skill_raw = 'MyBatis', importance = 'required', evidence = '熟练使用Spring Boot、MyBatis进行业务开发', jd_offset = 144;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-backend-01'), (SELECT id FROM skill WHERE canonical = 'Spring Cloud'), 'Spring Cloud', 'preferred', '了解Spring Cloud微服务生态', 177)
  ON DUPLICATE KEY UPDATE skill_raw = 'Spring Cloud', importance = 'preferred', evidence = '了解Spring Cloud微服务生态', jd_offset = 177;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-backend-01'), (SELECT id FROM skill WHERE canonical = 'MySQL'), 'MySQL', 'required', '熟悉MySQL，具备索引设计与慢查询优化经验', 200)
  ON DUPLICATE KEY UPDATE skill_raw = 'MySQL', importance = 'required', evidence = '熟悉MySQL，具备索引设计与慢查询优化经验', jd_offset = 200;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-backend-01'), (SELECT id FROM skill WHERE canonical = 'Redis'), 'Redis', 'required', '熟悉Redis，了解缓存穿透、击穿、雪崩的应对方案', 226)
  ON DUPLICATE KEY UPDATE skill_raw = 'Redis', importance = 'required', evidence = '熟悉Redis，了解缓存穿透、击穿、雪崩的应对方案', jd_offset = 226;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-backend-01'), (SELECT id FROM skill WHERE canonical = 'Kafka'), 'Kafka', 'required', '熟悉Kafka等消息中间件', 255)
  ON DUPLICATE KEY UPDATE skill_raw = 'Kafka', importance = 'required', evidence = '熟悉Kafka等消息中间件', jd_offset = 255;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-backend-01'), (SELECT id FROM skill WHERE canonical = 'Linux'), 'Linux', 'required', '熟悉Linux常用命令', 284)
  ON DUPLICATE KEY UPDATE skill_raw = 'Linux', importance = 'required', evidence = '熟悉Linux常用命令', jd_offset = 284;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-backend-01'), (SELECT id FROM skill WHERE canonical = 'Git'), 'Git', 'required', '熟悉Git协作流程与Maven构建', 314)
  ON DUPLICATE KEY UPDATE skill_raw = 'Git', importance = 'required', evidence = '熟悉Git协作流程与Maven构建', jd_offset = 314;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-backend-01'), (SELECT id FROM skill WHERE canonical = 'Maven'), 'Maven', 'required', '熟悉Git协作流程与Maven构建', 314)
  ON DUPLICATE KEY UPDATE skill_raw = 'Maven', importance = 'required', evidence = '熟悉Git协作流程与Maven构建', jd_offset = 314;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-backend-01'), (SELECT id FROM skill WHERE canonical = 'Docker'), 'Docker', 'preferred', '熟悉Docker与Kubernetes，有容器化部署经验者优先', 341)
  ON DUPLICATE KEY UPDATE skill_raw = 'Docker', importance = 'preferred', evidence = '熟悉Docker与Kubernetes，有容器化部署经验者优先', jd_offset = 341;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-backend-01'), (SELECT id FROM skill WHERE canonical = 'Kubernetes'), 'Kubernetes', 'preferred', '熟悉Docker与Kubernetes，有容器化部署经验者优先', 341)
  ON DUPLICATE KEY UPDATE skill_raw = 'Kubernetes', importance = 'preferred', evidence = '熟悉Docker与Kubernetes，有容器化部署经验者优先', jd_offset = 341;
INSERT INTO job_tag (job_id, tag) VALUES ((SELECT id FROM job WHERE code = 'job-backend-01'), '高并发')
  ON DUPLICATE KEY UPDATE tag = '高并发';
INSERT INTO job_tag (job_id, tag) VALUES ((SELECT id FROM job WHERE code = 'job-backend-01'), '微服务')
  ON DUPLICATE KEY UPDATE tag = '微服务';
INSERT INTO job_tag (job_id, tag) VALUES ((SELECT id FROM job WHERE code = 'job-backend-01'), '分布式')
  ON DUPLICATE KEY UPDATE tag = '分布式';

-- job-devops-01
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-devops-01'), (SELECT id FROM skill WHERE canonical = 'Linux'), 'Linux', 'required', '熟悉Linux系统管理与性能调优', 101)
  ON DUPLICATE KEY UPDATE skill_raw = 'Linux', importance = 'required', evidence = '熟悉Linux系统管理与性能调优', jd_offset = 101;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-devops-01'), (SELECT id FROM skill WHERE canonical = 'Docker'), 'Docker', 'required', '熟练使用Docker进行应用打包与部署', 121)
  ON DUPLICATE KEY UPDATE skill_raw = 'Docker', importance = 'required', evidence = '熟练使用Docker进行应用打包与部署', jd_offset = 121;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-devops-01'), (SELECT id FROM skill WHERE canonical = 'Kubernetes'), 'Kubernetes', 'preferred', '了解Kubernetes编排', 144)
  ON DUPLICATE KEY UPDATE skill_raw = 'Kubernetes', importance = 'preferred', evidence = '了解Kubernetes编排', jd_offset = 144;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-devops-01'), (SELECT id FROM skill WHERE canonical = 'Jenkins'), 'Jenkins', 'required', '熟悉Jenkins流水线配置', 162)
  ON DUPLICATE KEY UPDATE skill_raw = 'Jenkins', importance = 'required', evidence = '熟悉Jenkins流水线配置', jd_offset = 162;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-devops-01'), (SELECT id FROM skill WHERE canonical = 'GitHub Actions'), 'GitHub Actions', 'required', '有GitHub Actions使用经验', 180)
  ON DUPLICATE KEY UPDATE skill_raw = 'GitHub Actions', importance = 'required', evidence = '有GitHub Actions使用经验', jd_offset = 180;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-devops-01'), (SELECT id FROM skill WHERE canonical = 'Nginx'), 'Nginx', 'required', '熟悉Nginx反向代理与负载均衡配置', 203)
  ON DUPLICATE KEY UPDATE skill_raw = 'Nginx', importance = 'required', evidence = '熟悉Nginx反向代理与负载均衡配置', jd_offset = 203;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-devops-01'), (SELECT id FROM skill WHERE canonical = 'Shell'), 'Shell', 'required', '熟悉Shell脚本与Python自动化脚本开发', 225)
  ON DUPLICATE KEY UPDATE skill_raw = 'Shell', importance = 'required', evidence = '熟悉Shell脚本与Python自动化脚本开发', jd_offset = 225;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-devops-01'), (SELECT id FROM skill WHERE canonical = 'Python'), 'Python', 'required', '熟悉Shell脚本与Python自动化脚本开发', 225)
  ON DUPLICATE KEY UPDATE skill_raw = 'Python', importance = 'required', evidence = '熟悉Shell脚本与Python自动化脚本开发', jd_offset = 225;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-devops-01'), (SELECT id FROM skill WHERE canonical = 'Prometheus'), 'Prometheus', 'required', '熟悉Prometheus与Grafana监控体系', 252)
  ON DUPLICATE KEY UPDATE skill_raw = 'Prometheus', importance = 'required', evidence = '熟悉Prometheus与Grafana监控体系', jd_offset = 252;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-devops-01'), (SELECT id FROM skill WHERE canonical = 'Grafana'), 'Grafana', 'required', '熟悉Prometheus与Grafana监控体系', 252)
  ON DUPLICATE KEY UPDATE skill_raw = 'Grafana', importance = 'required', evidence = '熟悉Prometheus与Grafana监控体系', jd_offset = 252;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-devops-01'), (SELECT id FROM skill WHERE canonical = 'Ansible'), 'Ansible', 'preferred', '熟悉Ansible自动化配置管理者优先', 286)
  ON DUPLICATE KEY UPDATE skill_raw = 'Ansible', importance = 'preferred', evidence = '熟悉Ansible自动化配置管理者优先', jd_offset = 286;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-devops-01'), (SELECT id FROM skill WHERE canonical = 'MySQL'), 'MySQL', 'preferred', '熟悉MySQL主从复制与备份恢复者优先', 309)
  ON DUPLICATE KEY UPDATE skill_raw = 'MySQL', importance = 'preferred', evidence = '熟悉MySQL主从复制与备份恢复者优先', jd_offset = 309;
INSERT INTO job_tag (job_id, tag) VALUES ((SELECT id FROM job WHERE code = 'job-devops-01'), 'CI/CD')
  ON DUPLICATE KEY UPDATE tag = 'CI/CD';
INSERT INTO job_tag (job_id, tag) VALUES ((SELECT id FROM job WHERE code = 'job-devops-01'), '容器化')
  ON DUPLICATE KEY UPDATE tag = '容器化';
INSERT INTO job_tag (job_id, tag) VALUES ((SELECT id FROM job WHERE code = 'job-devops-01'), '可观测')
  ON DUPLICATE KEY UPDATE tag = '可观测';

-- job-frontend-01
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-frontend-01'), (SELECT id FROM skill WHERE canonical = 'HTML'), 'HTML', 'required', '精通HTML、CSS、JavaScript', 102)
  ON DUPLICATE KEY UPDATE skill_raw = 'HTML', importance = 'required', evidence = '精通HTML、CSS、JavaScript', jd_offset = 102;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-frontend-01'), (SELECT id FROM skill WHERE canonical = 'CSS'), 'CSS', 'required', '精通HTML、CSS、JavaScript', 102)
  ON DUPLICATE KEY UPDATE skill_raw = 'CSS', importance = 'required', evidence = '精通HTML、CSS、JavaScript', jd_offset = 102;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-frontend-01'), (SELECT id FROM skill WHERE canonical = 'JavaScript'), 'JavaScript', 'required', '精通HTML、CSS、JavaScript', 102)
  ON DUPLICATE KEY UPDATE skill_raw = 'JavaScript', importance = 'required', evidence = '精通HTML、CSS、JavaScript', jd_offset = 102;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-frontend-01'), (SELECT id FROM skill WHERE canonical = 'Vue'), 'Vue', 'required', '熟练使用Vue，理解响应式原理与组件化开发', 136)
  ON DUPLICATE KEY UPDATE skill_raw = 'Vue', importance = 'required', evidence = '熟练使用Vue，理解响应式原理与组件化开发', jd_offset = 136;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-frontend-01'), (SELECT id FROM skill WHERE canonical = 'TypeScript'), 'TypeScript', 'required', '熟悉TypeScript，具备良好的类型设计习惯', 161)
  ON DUPLICATE KEY UPDATE skill_raw = 'TypeScript', importance = 'required', evidence = '熟悉TypeScript，具备良好的类型设计习惯', jd_offset = 161;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-frontend-01'), (SELECT id FROM skill WHERE canonical = 'Vite'), 'Vite', 'required', '熟悉Vite构建工具与前端工程化流程', 189)
  ON DUPLICATE KEY UPDATE skill_raw = 'Vite', importance = 'required', evidence = '熟悉Vite构建工具与前端工程化流程', jd_offset = 189;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-frontend-01'), (SELECT id FROM skill WHERE canonical = 'ECharts'), 'ECharts', 'required', '熟悉ECharts，能独立完成数据可视化需求', 211)
  ON DUPLICATE KEY UPDATE skill_raw = 'ECharts', importance = 'required', evidence = '熟悉ECharts，能独立完成数据可视化需求', jd_offset = 211;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-frontend-01'), (SELECT id FROM skill WHERE canonical = 'Git'), 'Git', 'required', '熟悉Git协作流程', 237)
  ON DUPLICATE KEY UPDATE skill_raw = 'Git', importance = 'required', evidence = '熟悉Git协作流程', jd_offset = 237;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-frontend-01'), (SELECT id FROM skill WHERE canonical = 'Element Plus'), 'Element Plus', 'preferred', '熟悉Element Plus组件库者优先', 256)
  ON DUPLICATE KEY UPDATE skill_raw = 'Element Plus', importance = 'preferred', evidence = '熟悉Element Plus组件库者优先', jd_offset = 256;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-frontend-01'), (SELECT id FROM skill WHERE canonical = 'Sass'), 'Sass', 'preferred', '了解Sass等 CSS 预处理语言者优先', 280)
  ON DUPLICATE KEY UPDATE skill_raw = 'Sass', importance = 'preferred', evidence = '了解Sass等 CSS 预处理语言者优先', jd_offset = 280;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-frontend-01'), (SELECT id FROM skill WHERE canonical = 'React'), 'React', 'preferred', '有React项目经验者优先', 304)
  ON DUPLICATE KEY UPDATE skill_raw = 'React', importance = 'preferred', evidence = '有React项目经验者优先', jd_offset = 304;
INSERT INTO job_tag (job_id, tag) VALUES ((SELECT id FROM job WHERE code = 'job-frontend-01'), '组件库')
  ON DUPLICATE KEY UPDATE tag = '组件库';
INSERT INTO job_tag (job_id, tag) VALUES ((SELECT id FROM job WHERE code = 'job-frontend-01'), '数据可视化')
  ON DUPLICATE KEY UPDATE tag = '数据可视化';
INSERT INTO job_tag (job_id, tag) VALUES ((SELECT id FROM job WHERE code = 'job-frontend-01'), 'B 端')
  ON DUPLICATE KEY UPDATE tag = 'B 端';

-- job-fullstack-01
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-fullstack-01'), (SELECT id FROM skill WHERE canonical = 'C++'), 'C++', 'required', '熟悉C/C++/Java开发语言', 146)
  ON DUPLICATE KEY UPDATE skill_raw = 'C++', importance = 'required', evidence = '熟悉C/C++/Java开发语言', jd_offset = 146;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-fullstack-01'), (SELECT id FROM skill WHERE canonical = 'Java'), 'Java', 'required', '熟悉C/C++/Java开发语言', 146)
  ON DUPLICATE KEY UPDATE skill_raw = 'Java', importance = 'required', evidence = '熟悉C/C++/Java开发语言', jd_offset = 146;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-fullstack-01'), (SELECT id FROM skill WHERE canonical = 'Linux'), 'Linux', 'required', '熟悉Linux网络编程', 183)
  ON DUPLICATE KEY UPDATE skill_raw = 'Linux', importance = 'required', evidence = '熟悉Linux网络编程', jd_offset = 183;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-fullstack-01'), (SELECT id FROM skill WHERE canonical = 'TCP/IP'), 'TCP/IP', 'required', '熟悉TCP/IP协议，掌握 epoll 等IO模型', 219)
  ON DUPLICATE KEY UPDATE skill_raw = 'TCP/IP', importance = 'required', evidence = '熟悉TCP/IP协议，掌握 epoll 等IO模型', jd_offset = 219;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-fullstack-01'), (SELECT id FROM skill WHERE canonical = 'MySQL'), 'MySQL', 'required', '熟悉MySQL、Redis等存储系统', 260)
  ON DUPLICATE KEY UPDATE skill_raw = 'MySQL', importance = 'required', evidence = '熟悉MySQL、Redis等存储系统', jd_offset = 260;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-fullstack-01'), (SELECT id FROM skill WHERE canonical = 'Redis'), 'Redis', 'required', '熟悉MySQL、Redis等存储系统', 260)
  ON DUPLICATE KEY UPDATE skill_raw = 'Redis', importance = 'required', evidence = '熟悉MySQL、Redis等存储系统', jd_offset = 260;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-fullstack-01'), (SELECT id FROM skill WHERE canonical = 'Git'), 'Git', 'required', '熟悉Git、CMake、gtest等工具', 298)
  ON DUPLICATE KEY UPDATE skill_raw = 'Git', importance = 'required', evidence = '熟悉Git、CMake、gtest等工具', jd_offset = 298;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-fullstack-01'), (SELECT id FROM skill WHERE canonical = 'LLM'), 'LLM', 'preferred', '具备LLM大语言模型知识', 399)
  ON DUPLICATE KEY UPDATE skill_raw = 'LLM', importance = 'preferred', evidence = '具备LLM大语言模型知识', jd_offset = 399;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-fullstack-01'), (SELECT id FROM skill WHERE canonical = 'libevent'), 'libevent', 'preferred', '有libevent/muduo等网络库使用经验者优先', 369)
  ON DUPLICATE KEY UPDATE skill_raw = 'libevent', importance = 'preferred', evidence = '有libevent/muduo等网络库使用经验者优先', jd_offset = 369;
INSERT INTO job_tag (job_id, tag) VALUES ((SELECT id FROM job WHERE code = 'job-fullstack-01'), '高并发')
  ON DUPLICATE KEY UPDATE tag = '高并发';
INSERT INTO job_tag (job_id, tag) VALUES ((SELECT id FROM job WHERE code = 'job-fullstack-01'), '分布式')
  ON DUPLICATE KEY UPDATE tag = '分布式';
INSERT INTO job_tag (job_id, tag) VALUES ((SELECT id FROM job WHERE code = 'job-fullstack-01'), '直播')
  ON DUPLICATE KEY UPDATE tag = '直播';
INSERT INTO job_tag (job_id, tag) VALUES ((SELECT id FROM job WHERE code = 'job-fullstack-01'), '校招')
  ON DUPLICATE KEY UPDATE tag = '校招';

-- job-operation-01
--   （无技术技能要求：非技术岗，M3.3「岗位 0 技能」边界的真实样本）
INSERT INTO job_tag (job_id, tag) VALUES ((SELECT id FROM job WHERE code = 'job-operation-01'), '直播')
  ON DUPLICATE KEY UPDATE tag = '直播';
INSERT INTO job_tag (job_id, tag) VALUES ((SELECT id FROM job WHERE code = 'job-operation-01'), '用户增长')
  ON DUPLICATE KEY UPDATE tag = '用户增长';
INSERT INTO job_tag (job_id, tag) VALUES ((SELECT id FROM job WHERE code = 'job-operation-01'), '校招')
  ON DUPLICATE KEY UPDATE tag = '校招';

-- job-qa-01
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-qa-01'), (SELECT id FROM skill WHERE canonical = 'Java'), 'Java', 'required', '熟悉Java或Python', 101)
  ON DUPLICATE KEY UPDATE skill_raw = 'Java', importance = 'required', evidence = '熟悉Java或Python', jd_offset = 101;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-qa-01'), (SELECT id FROM skill WHERE canonical = 'Python'), 'Python', 'required', '熟悉Java或Python', 101)
  ON DUPLICATE KEY UPDATE skill_raw = 'Python', importance = 'required', evidence = '熟悉Java或Python', jd_offset = 101;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-qa-01'), (SELECT id FROM skill WHERE canonical = 'JUnit'), 'JUnit', 'required', '熟练使用JUnit或pytest编写单元测试与接口测试', 131)
  ON DUPLICATE KEY UPDATE skill_raw = 'JUnit', importance = 'required', evidence = '熟练使用JUnit或pytest编写单元测试与接口测试', jd_offset = 131;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-qa-01'), (SELECT id FROM skill WHERE canonical = 'pytest'), 'pytest', 'required', '熟练使用JUnit或pytest编写单元测试与接口测试', 131)
  ON DUPLICATE KEY UPDATE skill_raw = 'pytest', importance = 'required', evidence = '熟练使用JUnit或pytest编写单元测试与接口测试', jd_offset = 131;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-qa-01'), (SELECT id FROM skill WHERE canonical = 'Postman'), 'Postman', 'required', '熟悉Postman进行接口调试与用例管理', 162)
  ON DUPLICATE KEY UPDATE skill_raw = 'Postman', importance = 'required', evidence = '熟悉Postman进行接口调试与用例管理', jd_offset = 162;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-qa-01'), (SELECT id FROM skill WHERE canonical = 'MySQL'), 'MySQL', 'required', '熟悉MySQL，能编写 SQL 进行数据校验', 186)
  ON DUPLICATE KEY UPDATE skill_raw = 'MySQL', importance = 'required', evidence = '熟悉MySQL，能编写 SQL 进行数据校验', jd_offset = 186;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-qa-01'), (SELECT id FROM skill WHERE canonical = 'Linux'), 'Linux', 'required', '熟悉Linux常用命令与Shell脚本', 212)
  ON DUPLICATE KEY UPDATE skill_raw = 'Linux', importance = 'required', evidence = '熟悉Linux常用命令与Shell脚本', jd_offset = 212;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-qa-01'), (SELECT id FROM skill WHERE canonical = 'Shell'), 'Shell', 'required', '熟悉Linux常用命令与Shell脚本', 212)
  ON DUPLICATE KEY UPDATE skill_raw = 'Shell', importance = 'required', evidence = '熟悉Linux常用命令与Shell脚本', jd_offset = 212;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-qa-01'), (SELECT id FROM skill WHERE canonical = 'Git'), 'Git', 'required', '熟悉Git与Jira等研发协作工具', 235)
  ON DUPLICATE KEY UPDATE skill_raw = 'Git', importance = 'required', evidence = '熟悉Git与Jira等研发协作工具', jd_offset = 235;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-qa-01'), (SELECT id FROM skill WHERE canonical = 'Jira'), 'Jira', 'required', '熟悉Git与Jira等研发协作工具', 235)
  ON DUPLICATE KEY UPDATE skill_raw = 'Jira', importance = 'required', evidence = '熟悉Git与Jira等研发协作工具', jd_offset = 235;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-qa-01'), (SELECT id FROM skill WHERE canonical = 'Jenkins'), 'Jenkins', 'preferred', '熟悉Jenkins持续集成者优先', 262)
  ON DUPLICATE KEY UPDATE skill_raw = 'Jenkins', importance = 'preferred', evidence = '熟悉Jenkins持续集成者优先', jd_offset = 262;
INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance, evidence, jd_offset)
  VALUES ((SELECT id FROM job WHERE code = 'job-qa-01'), (SELECT id FROM skill WHERE canonical = 'Docker'), 'Docker', 'preferred', '熟悉Docker容器化测试环境者优先', 282)
  ON DUPLICATE KEY UPDATE skill_raw = 'Docker', importance = 'preferred', evidence = '熟悉Docker容器化测试环境者优先', jd_offset = 282;
INSERT INTO job_tag (job_id, tag) VALUES ((SELECT id FROM job WHERE code = 'job-qa-01'), '自动化测试')
  ON DUPLICATE KEY UPDATE tag = '自动化测试';
INSERT INTO job_tag (job_id, tag) VALUES ((SELECT id FROM job WHERE code = 'job-qa-01'), '接口测试')
  ON DUPLICATE KEY UPDATE tag = '接口测试';
INSERT INTO job_tag (job_id, tag) VALUES ((SELECT id FROM job WHERE code = 'job-qa-01'), '质量保障')
  ON DUPLICATE KEY UPDATE tag = '质量保障';

-- ============================================================================
-- 导入完成。自检（AC23）：把本文件连续导入两次，各表行数必须一致：
--   SELECT COUNT(*) FROM job_category;  -- 14
--   SELECT COUNT(*) FROM skill;         -- 83
--   SELECT COUNT(*) FROM job;           -- 7
--   SELECT COUNT(*) FROM job_requirement WHERE skill_id IS NULL;  -- 必须 0（D3）
-- ============================================================================
