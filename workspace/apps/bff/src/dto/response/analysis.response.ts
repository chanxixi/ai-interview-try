/**
 * `POST /api/analysis` 响应契约 —— spec.md §2.2（冻结）。
 *
 * 字段名 / 层级 / 类型都不可改；这里只**声明形状**。
 * BFF 不做任何业务计算（ADR-005），所有值原样来自 analyzer。
 *
 * ⚠️ 成功响应**不套壳**：直接返回本结构，不包 `{ code: 0, data: ... }`（指南 §6.7）。
 */

/** 归一化后的技能项 */
export interface NormalizedSkill {
  /** 简历原文里的写法 */
  raw: string;
  /** 归一化后的标准名（来自技能词典） */
  canonical: string;
  category?: string | null;
}

/** 简历结构化视图 */
export interface ResumeView {
  sections: Record<'education' | 'experience' | 'projects' | 'skills', string[]>;
  skills: NormalizedSkill[];
}

/** 简历自身的问题（与 JD 无关） */
export interface Issue {
  type: string;
  severity: 'high' | 'medium' | 'low';
  /** 简历原文证据 */
  evidence: string;
  suggestion: string;
}

/** 命中项 —— 双向原文证据是可解释性的核心（ADR-002） */
export interface MatchedItem {
  skill: string;
  importance: 'required' | 'preferred';
  weight: number;
  jdEvidence: string;
  resumeEvidence: string;
  jdOffset?: number | null;
  resumeOffset?: number | null;
}

/** 能力缺口 */
export interface MissingItem {
  skill: string;
  importance: 'required' | 'preferred';
  suggestion: string;
}

export interface MatchResult {
  /** 加权覆盖率 × 100，取值 0–100（spec.md §2.4） */
  score: number;
  matched: MatchedItem[];
  missing: MissingItem[];
}

/** 元信息 —— 两条降级链的对外证据之一 */
export interface Meta {
  traceId: string;
  /** 是否真的调用了 LLM */
  llmUsed: boolean;
  /** LLM 是否降级到规则分支（ADR-004）。存储降级不看这里，看 Java 的 /healthz.storage */
  degraded: boolean;
  elapsedMs: number;
}

export interface AnalysisResponse {
  resume: ResumeView;
  issues: Issue[];
  match: MatchResult;
  meta: Meta;
}
