package com.careerlens.jobservice.repository;

import com.careerlens.jobservice.entity.JobEntity;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.CrudRepository;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

/**
 * 岗位读仓储（tasks.md M5.2）。
 *
 * <p><b>为什么 extends {@link CrudRepository} 而不是 {@code JpaRepository}</b>：
 * {@code JpaRepository} 自带 {@code save} / {@code delete} / {@code deleteAll}，
 * 而 spec §2.9 D2 <b>禁止物理删除岗位</b>。用窄接口意味着「想删也删不了」——
 * 真要删得先改这个签名，而那是一次显式的、会被 review 看见的动作。
 *
 * <p><b>软删条件写死在 @Query 里</b>而不是让调用方拼：漏一个
 * {@code deletedAt IS NULL} 就会让已删岗位重新进入推荐候选（AC23），
 * 而这种 bug 在功能测试里看不出来（接口照样返 200）。
 *
 * <p>存储两档（MySQL 主路径 / H2 降级）由 <b>datasource URL</b> 切换，
 * 不需要两套 Repository 实现 —— 见 README 的「存储两档」小节与 DELIVERY.md 的取舍说明。
 */
@Repository
public interface JobRepository extends CrudRepository<JobEntity, Long> {

    Optional<JobEntity> findByCode(String code);

    /** 推荐候选集的主查询：{@code status='active' AND deleted_at IS NULL}，按 code 升序（确定性）。 */
    @Query("""
            SELECT j FROM JobEntity j
            WHERE j.status = 'active' AND j.deletedAt IS NULL
            ORDER BY j.code ASC
            """)
    List<JobEntity> findActiveForCandidates();

    /** 按分类查 active 岗位（AC22：新增分类只插一行即可查，无需改 Java）。 */
    @Query("""
            SELECT j FROM JobEntity j
            WHERE j.status = 'active' AND j.deletedAt IS NULL
              AND j.categoryId IN (SELECT c.id FROM JobCategoryEntity c WHERE c.code = :categoryCode)
            ORDER BY j.code ASC
            """)
    List<JobEntity> findActiveByCategoryCode(@Param("categoryCode") String categoryCode);

    @Query("SELECT COUNT(j) FROM JobEntity j WHERE j.status = 'active' AND j.deletedAt IS NULL")
    long countActive();
}
