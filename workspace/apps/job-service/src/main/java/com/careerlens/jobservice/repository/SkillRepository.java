package com.careerlens.jobservice.repository;

import com.careerlens.jobservice.entity.SkillEntity;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.CrudRepository;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.Collection;
import java.util.List;

/**
 * 技能标准名读仓储 —— <b>只做一次纯查表</b>。
 *
 * <p>存在意义：{@code job_requirement} 存 {@code skill_id}（D3：归一化后落库），
 * 而 Python 契约要 canonical。装配候选集时要把 id 换成名字 —— 一次 {@code IN} 查表，
 * 不参与任何算法。
 *
 * <p><b>为什么 Python 不自己查</b>：spec §2.7 禁止 Python 直连数据库，
 * 它的词典真源是仓库内 {@code skills.yaml}（C4）。本服务只是把库里的
 * {@code skill_id} 翻译成 canonical —— 两边数据同源（都由 skills.yaml 生成），
 * 所以翻译结果与 Python 自己的归一化一致。
 */
@Repository
public interface SkillRepository extends CrudRepository<SkillEntity, Long> {

    /**
     * 按 id 批量取 {@code [id, canonical]} 两列。
     *
     * <p>返回 {@code Object[]} 而不是 DTO 或 Map：这是一个纯查表，
     * 为两列建一个 DTO 类是过度设计；而 Spring Data 的 Map 投影需要
     * 额外的别名处理，不如 {@code Object[]} 直接。调用方在
     * {@code AnalysisOrchestrationService} 里一次转成 Map。
     */
    @Query("SELECT s.id, s.canonical FROM SkillEntity s WHERE s.id IN :ids")
    List<Object[]> findIdAndCanonicalByIdIn(@Param("ids") Collection<Long> ids);
}
