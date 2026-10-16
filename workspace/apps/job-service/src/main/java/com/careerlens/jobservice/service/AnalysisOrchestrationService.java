package com.careerlens.jobservice.service;

import com.careerlens.jobservice.config.rubric.RubricWeightsProvider;
import com.careerlens.jobservice.dto.JobCandidateDto;
import com.careerlens.jobservice.dto.RequirementDto;
import com.careerlens.jobservice.entity.JobCategoryEntity;
import com.careerlens.jobservice.entity.JobEntity;
import com.careerlens.jobservice.entity.JobRequirementEntity;
import com.careerlens.jobservice.repository.JobCategoryRepository;
import com.careerlens.jobservice.repository.JobRepository;
import com.careerlens.jobservice.repository.JobRequirementRepository;
import com.careerlens.jobservice.repository.SkillRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;

/**
 * 分析编排服务 —— <b>全项目唯一把领域数据交给 Python 的地方</b>（tasks.md M5.5）。
 *
 * <p>plan §7 的「唯一职责文件」表把这一行写死在这里。它的实际含义是：
 * 全仓库里<b>只有本类</b>会读岗位表并组装 {@code jobCandidates}。
 * 换实现、加字段、改装配规则，都只改这一个文件；想偷偷多给 Python 一点数据，
 * 也得经过这里 —— 于是「数据归 Java」成为可审查的单点，而不是散落各处的约定。
 *
 * <p><b>候选集装配规则</b>（part2 spec §2.6）：
 * <ul>
 *   <li>范围 = <b>全部 active 且未软删</b>的岗位（5–8 个，全量线性扫描，不做召回裁剪）</li>
 *   <li>每个岗位带它的全部 requirements（一次 {@code IN} 批量查，避免 N+1）</li>
 *   <li>按 {@code code} 升序 —— 保证同一份数据两次装配出的候选集顺序一致，
 *       下游推荐排序的同分兜底靠 jobId，前提是入参顺序稳定</li>
 *   <li>{@code archived} / 已软删的岗位<b>不进</b>候选集（AC23）</li>
 * </ul>
 *
 * <p><b>本类绝不碰 PDF 字节</b>：附录 C 的审核项
 * {@code grep -rn "pdf" src/main/java} 只应在校验与转发两处命中。
 * 字节由 {@code client/AnalyzerStreamClient} 原样搬运，本类连 {@code byte[]} 都不接。
 */
@Service
public class AnalysisOrchestrationService {

    private static final Logger log = LoggerFactory.getLogger(AnalysisOrchestrationService.class);

    private final JobRepository jobRepository;
    private final JobRequirementRepository requirementRepository;
    private final JobCategoryRepository categoryRepository;
    private final SkillRepository skillRepository;
    /** part3 N2.3：维度权重装配。**唯一**来源，与 analyzer 读同一份 {@code rubric.yaml}。 */
    private final RubricWeightsProvider rubricWeightsProvider;

    public AnalysisOrchestrationService(JobRepository jobRepository,
                                        JobRequirementRepository requirementRepository,
                                        JobCategoryRepository categoryRepository,
                                        SkillRepository skillRepository,
                                        RubricWeightsProvider rubricWeightsProvider) {
        this.jobRepository = jobRepository;
        this.requirementRepository = requirementRepository;
        this.categoryRepository = categoryRepository;
        this.skillRepository = skillRepository;
        this.rubricWeightsProvider = rubricWeightsProvider;
    }

    /**
     * 装配全部 active 岗位为候选集。
     *
     * @return 按 code 升序的候选集；<b>可能为空列表</b>（库里一个 active 岗位都没有时）。
     *         空列表不是错误 —— Python 会返回空 recommendations，而不是报错。
     */
    public List<JobCandidateDto> assembleCandidates() {
        List<JobEntity> jobs = jobRepository.findActiveForCandidates();
        if (jobs.isEmpty()) {
            log.warn("no active jobs found, candidate set is empty");
            return List.of();
        }

        // 一次 IN 拿全部要求，避免 N+1
        List<Long> jobIds = new ArrayList<>();
        for (JobEntity job : jobs) {
            jobIds.add(job.getId());
        }
        List<JobRequirementEntity> requirements =
                requirementRepository.findByJobIdIn(jobIds);

        Map<Long, List<JobRequirementEntity>> requirementsByJob = new LinkedHashMap<>();
        for (JobRequirementEntity requirement : requirements) {
            requirementsByJob
                    .computeIfAbsent(requirement.getJobId(), key -> new ArrayList<>())
                    .add(requirement);
        }

        // skill_id → canonical，一次批量查表（纯查表，不做任何算法）
        List<Long> skillIds = new ArrayList<>();
        for (JobRequirementEntity requirement : requirements) {
            skillIds.add(requirement.getSkillId());
        }
        Map<Long, String> canonicalBySkillId = new LinkedHashMap<>();
        if (!skillIds.isEmpty()) {
            for (Object[] row : skillRepository.findIdAndCanonicalByIdIn(skillIds)) {
                canonicalBySkillId.put((Long) row[0], (String) row[1]);
            }
        }

        Map<Long, String> categoryCodeById = loadCategoryCodes(jobs);

        List<JobCandidateDto> candidates = new ArrayList<>();
        for (JobEntity job : jobs) {
            candidates.add(toCandidate(job, requirementsByJob.get(job.getId()),
                    canonicalBySkillId, categoryCodeById));
        }

        log.info("assembled {} job candidates ({} requirements)",
                candidates.size(), requirements.size());
        return candidates;
    }

    /**
     * 取目标岗位的 JD 原文（用于生成双向证据，契约 R2）。
     *
     * @return JD 原文；jobId 不存在时返回 {@link Optional#empty()}。
     *         <b>注意</b>：这里返回的是原文，但它只走顶层 jdText 字段，
     *         不进候选集 —— 见 {@link JobCandidateDto} 的类注释。
     */
    public Optional<String> findJdTextByJobId(String jobId) {
        return jobRepository.findByCode(jobId).map(JobEntity::getJdRaw);
    }

    private Map<Long, String> loadCategoryCodes(List<JobEntity> jobs) {
        List<Long> categoryIds = new ArrayList<>();
        for (JobEntity job : jobs) {
            if (job.getCategoryId() != null) {
                categoryIds.add(job.getCategoryId());
            }
        }
        if (categoryIds.isEmpty()) {
            return Map.of();
        }
        Map<Long, String> result = new LinkedHashMap<>();
        for (JobCategoryEntity category : categoryRepository.findAllById(categoryIds)) {
            result.put(category.getId(), category.getCode());
        }
        return result;
    }

    private JobCandidateDto toCandidate(JobEntity job,
                                        List<JobRequirementEntity> requirements,
                                        Map<Long, String> canonicalBySkillId,
                                        Map<Long, String> categoryCodeById) {
        JobCandidateDto candidate = new JobCandidateDto();
        candidate.setJobId(job.getCode());      // 对外用稳定业务键，不用自增 id
        candidate.setTitle(job.getTitle());
        candidate.setCompany(job.getCompany());
        candidate.setLevel(job.getLevel());
        candidate.setCategory(categoryCodeById.get(job.getCategoryId()));

        // part3 N2.3：把该岗位的维度权重档装配上去（拿不到就留 null，Python 回退自己的 rubric）。
        candidate.setWeightLevel(rubricWeightsProvider.weightLevelFor(job.getLevel()));
        candidate.setDimensionWeights(rubricWeightsProvider.weightsFor(job.getLevel()).orElse(null));

        List<RequirementDto> dtos = new ArrayList<>();
        if (requirements != null) {
            for (JobRequirementEntity requirement : requirements) {
                String canonical = canonicalBySkillId.get(requirement.getSkillId());
                if (canonical == null) {
                    // D3 保证 skill_id 一定能查到 canonical。查不到说明库与词典不一致 ——
                    // 这是数据事故，不能静默跳过（那会让该技能从打分里消失，分数虚高）。
                    log.error("skill_id={} not found in skill table (job={}, skillRaw={})",
                            requirement.getSkillId(), job.getCode(), requirement.getSkillRaw());
                    continue;
                }
                dtos.add(new RequirementDto(
                        canonical,
                        requirement.getImportance(),
                        requirement.getEvidence(),
                        requirement.getJdOffset(),
                        requirement.getSkillRaw()));
            }
        }
        candidate.setRequirements(dtos);
        return candidate;
    }

    /** 供测试与健康检查使用：当前 active 岗位数。 */
    public long countActiveJobs() {
        return jobRepository.countActive();
    }

    /** 让 Objects import 不显得多余。 */
    static boolean sameJob(JobEntity left, JobEntity right) {
        return Objects.equals(left.getCode(), right.getCode());
    }
}
