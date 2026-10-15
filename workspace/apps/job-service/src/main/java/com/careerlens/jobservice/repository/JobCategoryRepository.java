package com.careerlens.jobservice.repository;

import com.careerlens.jobservice.entity.JobCategoryEntity;
import org.springframework.data.repository.ListCrudRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

/**
 * 岗位分类字典读仓储（D1：分类是数据不是代码）。
 *
 * <p>本期只读：Java 侧不提供分类维护接口（spec §2.9「人工增删」走文件路）。
 * 分类的写入由 {@code db/seed.sql} 的启动幂等导入完成。
 */
@Repository
public interface JobCategoryRepository extends ListCrudRepository<JobCategoryEntity, Long> {

    Optional<JobCategoryEntity> findByCode(String code);

    /** 取某一层的全部分类（按 sort_order 升序，保证展示顺序稳定）。 */
    List<JobCategoryEntity> findByLevelOrderBySortOrderAsc(int level);
}
