package com.careerlens.jobservice.repository;

import com.careerlens.jobservice.entity.JobRequirementEntity;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.CrudRepository;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.Collection;
import java.util.List;

/**
 * 岗位技能要求读仓储（tasks.md M5.2）。
 *
 * <p>核心方法只有一个：{@code findByJobIdIn}。它用一次 {@code IN (...)} 拿全部候选岗位的
 * 要求，<b>避免 N+1</b> —— 逐个岗位查在 7 个岗位时只是 7 条 SQL，
 * 但岗位数是会增长的（spec §2.6 的 5–8 是本期规模，不是上限）。
 *
 * <p>{@code ORDER BY} 由调用方决定：本方法只负责「取回来」，
 * 而「按什么顺序」属于装配策略（见 {@code AnalysisOrchestrationService}）。
 */
@Repository
public interface JobRequirementRepository extends CrudRepository<JobRequirementEntity, Long> {

    @Query("SELECT r FROM JobRequirementEntity r WHERE r.jobId IN :jobIds")
    List<JobRequirementEntity> findByJobIdIn(@Param("jobIds") Collection<Long> jobIds);

    long countByJobId(Long jobId);
}
