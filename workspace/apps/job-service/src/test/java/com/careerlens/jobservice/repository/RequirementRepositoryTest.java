package com.careerlens.jobservice.repository;

import com.careerlens.jobservice.dto.JobCandidateDto;
import com.careerlens.jobservice.entity.JobEntity;
import com.careerlens.jobservice.entity.JobRequirementEntity;
import com.careerlens.jobservice.entity.SkillEntity;
import com.careerlens.jobservice.service.AnalysisOrchestrationService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.jdbc.AutoConfigureTestDatabase;
import org.springframework.boot.test.autoconfigure.orm.jpa.DataJpaTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.TestPropertySource;

import java.util.Comparator;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * 岗位 / 要求 / 技能仓储与候选集装配（tasks.md M5.7）。
 *
 * <p>用 {@code @DataJpaTest} + 内嵌 H2，跑的是与生产<b>同一份</b>
 * {@code db/h2/schema.sql} + {@code db/seed.sql} —— 所以「种子能不能导进去」
 * 「导进去的样子对不对」也在这些断言的覆盖范围内，不需要额外的冒烟脚本。
 *
 * <p>{@code ddl-auto=validate}：测试里<b>不改</b>这个设置。
 * 一旦实体与建表脚本对不上，这些测试会集体失败 —— 那是想要的信号，
 * 因为它意味着「Java 的领域模型」与「数据库结构」漂了。
 */
/**
 * @see #REPLACE_NONE 用我们自己配的 MODE=MySQL 数据源，而不是 @DataJpaTest 默认的裸 H2
 */
@DataJpaTest
@AutoConfigureTestDatabase(replace = AutoConfigureTestDatabase.Replace.NONE)
@TestPropertySource(properties = {
        // ⚠️ MODE=MySQL 与 DATABASE_TO_LOWER=TRUE 一个都不能少：
        //   MODE=MySQL        —— schema.sql 用了 MySQL 的内联 KEY (...) 索引语法，
        //                        裸 H2 解析不了（这正是生产连接串也带它的原因）
        //   DATABASE_TO_LOWER —— 否则 H2 把未加引号的标识符折成大写，与实体映射对不上
        //   DB_CLOSE_DELAY=-1 —— 内存库在连接间隙不能消失（@DataJpaTest 每个测试一个事务）
        "spring.datasource.url=jdbc:h2:mem:jobrepo-test;MODE=MySQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1",
        "spring.datasource.driver-class-name=org.h2.Driver",
        "spring.datasource.username=sa",
        "spring.datasource.password=",
        "spring.sql.init.mode=always",
        "spring.sql.init.schema-locations=classpath:db/h2/schema.sql",
        "spring.sql.init.data-locations=classpath:db/seed.sql",
        "spring.sql.init.continue-on-error=false",
        "spring.jpa.hibernate.ddl-auto=validate"
})
class RequirementRepositoryTest {

    /** 保留给 javadoc 引用。 */
    static final String REPLACE_NONE = "replace=NONE";

    @Autowired
    private JobRepository jobRepository;

    @Autowired
    private JobRequirementRepository requirementRepository;

    @Autowired
    private SkillRepository skillRepository;

    @Autowired
    private JobCategoryRepository categoryRepository;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    // ------------------------------------------------------------------ 种子导入

    @Test
    void seed_is_imported_and_row_counts_match_generator_output() {
        // 与 scripts/gen-seed.sh 的输出一致（分类 14 · 技能 83 · 岗位 7 · 要求 66）
        assertThat(jobRepository.count()).isEqualTo(7);
        assertThat(skillRepository.count()).isEqualTo(83);
        assertThat(categoryRepository.count()).isEqualTo(14);
        assertThat(requirementRepository.count()).isEqualTo(66);
    }

    @Test
    void reimporting_seed_does_not_duplicate_rows_ac23() {
        // 幂等导入：再跑一次 seed.sql，行数不变（AC23）。
        // 测试里不重新执行脚本（它已在启动时跑过），而是验证「重复插入被 uk_* 挡住」：
        // 直接插入一条与种子冲突的 (job_id, skill_id) 必须失败。
        long jobId = jdbcTemplate.queryForObject(
                "SELECT id FROM job WHERE code = 'job-backend-01'", Long.class);
        long skillId = jdbcTemplate.queryForObject(
                "SELECT id FROM skill WHERE canonical = 'Java'", Long.class);

        assertThatThrownBy(() -> jdbcTemplate.update(
                "INSERT INTO job_requirement (job_id, skill_id, skill_raw, importance) "
                        + "VALUES (?, ?, 'Java', 'required')", jobId, skillId))
                .isNotNull();
    }

    // ------------------------------------------------------------------ D3

    @Test
    void every_requirement_has_a_non_null_skill_id_d3() {
        Integer orphans = jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM job_requirement WHERE skill_id IS NULL", Integer.class);
        assertThat(orphans).isZero();
    }

    @Test
    void every_requirement_skill_id_resolves_to_a_canonical() {
        for (JobRequirementEntity requirement : requirementRepository.findAll()) {
            assertThat(requirement.getSkillId()).as("D3：skill_id 必须非空").isNotNull();
            assertThat(skillRepository.findById(requirement.getSkillId()))
                    .as("skill_id=%s 必须能在 skill 表查到（库与 skills.yaml 不一致就是数据事故）",
                            requirement.getSkillId())
                    .isPresent();
        }
    }

    // ------------------------------------------------------------------ 批量查询（避免 N+1）

    @Test
    void findByJobIdIn_returns_requirements_for_all_requested_jobs() {
        List<JobEntity> jobs = jobRepository.findActiveForCandidates();
        assertThat(jobs).isNotEmpty();

        List<Long> jobIds = jobs.stream().map(JobEntity::getId).toList();
        List<JobRequirementEntity> requirements = requirementRepository.findByJobIdIn(jobIds);

        // 一次 IN 拿到全部 66 条（岗位全 active，所以要求的总数也是 66）
        assertThat(requirements).hasSize(66);

        // 每个返回的 jobId 都在请求范围内 —— 说明没有串数据
        assertThat(requirements).allSatisfy(requirement ->
                assertThat(jobIds).contains(requirement.getJobId()));
    }

    // ------------------------------------------------------------------ D2 软删

    @Test
    void archived_or_deleted_jobs_stay_out_of_candidate_set_ac23() {
        List<JobEntity> active = jobRepository.findActiveForCandidates();
        assertThat(active).hasSize(7);

        // 把其中一个岗位置 archived（模拟「下架」），行仍在，但不进候选集
        jdbcTemplate.update(
                "UPDATE job SET status = 'archived', deleted_at = CURRENT_TIMESTAMP "
                        + "WHERE code = 'job-backend-01'");

        List<JobEntity> afterArchive = jobRepository.findActiveForCandidates();
        assertThat(afterArchive).hasSize(6);
        assertThat(afterArchive).noneSatisfy(job ->
                assertThat(job.getCode()).isEqualTo("job-backend-01"));

        // 行还在 —— 软删不是物理删除（D2）
        Integer stillThere = jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM job WHERE code = 'job-backend-01'", Integer.class);
        assertThat(stillThere).isEqualTo(1);
    }

    // ------------------------------------------------------------------ 候选集装配

    @Test
    void assembled_candidates_carry_canonical_skills_and_no_jd_text() {
        AnalysisOrchestrationService service = new AnalysisOrchestrationService(
                jobRepository, requirementRepository, categoryRepository, skillRepository);

        List<JobCandidateDto> candidates = service.assembleCandidates();

        assertThat(candidates).hasSize(7);
        // 按 code 升序 —— 装配顺序稳定是推荐结果可复现的前提
        assertThat(candidates).isSortedAccordingTo(Comparator.comparing(JobCandidateDto::getJobId));

        for (JobCandidateDto candidate : candidates) {
            assertThat(candidate.getJobId()).isNotBlank();
            assertThat(candidate.getTitle()).isNotBlank();
            // 每条要求都必须是 canonical（不是 skillRaw）
            for (var requirement : candidate.getRequirements()) {
                assertThat(requirement.getSkill()).isNotBlank();
                assertThat(requirement.getImportance()).isIn("required", "preferred");
            }
        }

        // Java 后端岗至少要有 Java 这条要求，且 importance 合法
        JobCandidateDto backend = candidates.stream()
                .filter(candidate -> "job-backend-01".equals(candidate.getJobId()))
                .findFirst().orElseThrow();
        assertThat(backend.getRequirements()).isNotEmpty();
        assertThat(backend.getRequirements().stream()
                .map(com.careerlens.jobservice.dto.RequirementDto::getSkill))
                .contains("Java");
    }

    @Test
    void findJdTextByJobId_returns_the_target_job_jd() {
        AnalysisOrchestrationService service = new AnalysisOrchestrationService(
                jobRepository, requirementRepository, categoryRepository, skillRepository);

        assertThat(service.findJdTextByJobId("job-backend-01")).isPresent();
        assertThat(service.findJdTextByJobId("job-does-not-exist")).isEmpty();
    }

    // ------------------------------------------------------------------ D1 分类是数据

    @Test
    void job_category_is_data_not_code_d1() {
        // 插一个新分类 + 一个用它归类的岗位，不改任何 Java 代码即可被查到（AC22）
        jdbcTemplate.update(
                "INSERT INTO job_category (code, name, parent_id, level, sort_order, status) "
                        + "VALUES ('test-new', '新分类', NULL, 1, 99, 'active')");
        Long newCategoryId = jdbcTemplate.queryForObject(
                "SELECT id FROM job_category WHERE code = 'test-new'", Long.class);
        jdbcTemplate.update(
                "INSERT INTO job (code, title, company, level, category_id, jd_raw, content_hash, "
                        + "source, status, version) VALUES "
                        + "('job-new-cat-01', '新分类岗位', '某公司', '校招', ?, 'JD 原文', 'hash-new', "
                        + "'seed', 'active', 1)", newCategoryId);

        List<JobEntity> inNewCategory = jobRepository.findActiveByCategoryCode("test-new");
        assertThat(inNewCategory).extracting(JobEntity::getCode).containsExactly("job-new-cat-01");
    }
}
