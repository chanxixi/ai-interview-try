package com.careerlens.jobservice.dto;

import com.fasterxml.jackson.annotation.JsonInclude;

import java.util.ArrayList;
import java.util.List;

/**
 * 候选岗位 DTO —— Java 装配后下发给 Python（contracts/bff-java.yaml 的 {@code JobCandidateDto}）。
 *
 * <p>⚠️ <b>不含 {@code jdText} 原文</b> —— 这是「数据归 Java、算法归 Python」的物理保证：
 * 候选集里没有任何一段 JD 原文，Python 的匹配就退化为纯集合运算，
 * 不可能偷读岗位数据自己重抽（spec §2.7 的禁止项变成结构上不可能）。
 *
 * <p>目标岗位的 JD 原文走<b>顶层</b> {@code jdText} 字段下发（契约 R2 的裁决），
 * 不塞进 {@code candidates[0]} —— 后者是「第一个候选就是目标」的隐式约定，
 * 读契约的人猜不出来，自定义 JD 场景也塞不进去。
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public class JobCandidateDto {

    private String jobId;
    private String title;
    private String company;
    private String level;
    /** 分类 code；仅作元数据回填，<b>不参与打分</b>（契约 R2 明确标注）。 */
    private String category;
    private List<RequirementDto> requirements = new ArrayList<>();

    public JobCandidateDto() {
    }

    public String getJobId() {
        return jobId;
    }

    public void setJobId(String jobId) {
        this.jobId = jobId;
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

    public String getCategory() {
        return category;
    }

    public void setCategory(String category) {
        this.category = category;
    }

    public List<RequirementDto> getRequirements() {
        return requirements;
    }

    public void setRequirements(List<RequirementDto> requirements) {
        this.requirements = requirements;
    }
}
