/**
 * 分析相关的接口类型 —— 形状对齐 `workspace/contracts/frontend-bff.yaml` 的
 * `POST /api/analysis/stream`（part2 spec §2.3 / §2.4）。
 *
 * 前端只**描述**契约，不实现规则：分数怎么算、推荐怎么排全在 Python / Java 侧，
 * 这里只是「把收到的 JSON 摆到该有的形状上」（spec §2.7：Vue 禁止自行排序）。
 */

/** SSE 事件类型（part2 spec §2.4 冻结，6 类）。 */
export type SseEventType = 'meta' | 'stage' | 'thinking' | 'result' | 'error' | 'done';

/**
 * 8 个阶段（part2 spec §2.4 + part3 C5，按序）。
 *
 * **顺序是契约的一部分** —— 进度条要按它渲染，所以这里声明成 `as const` 元组，
 * 既能当运行时数组用（`v-for`），又能当类型用（`typeof STAGE_ORDER[number]`）。
 *
 * ⚠️ `reviewed` 是 part3 新增的，**只在 `deep` 模式发**。`standard` 模式下它一格都不会来，
 * 所以进度条绝不能无脑渲染这张表 —— 否则会出现「多一格却永远转不动」
 * （spec §2.4 明确禁止）。渲染时用 {@link stageOrderFor} 按本次请求的深度取。
 */
export const STAGE_ORDER = [
  'accepted',
  'parsed',
  'cleaned',
  'normalized',
  'matched',
  'recommended',
  'llm',
  'reviewed',
] as const;

export type StageName = (typeof STAGE_ORDER)[number];

/** `standard` 模式的阶段表（= part2 的 7 个，去掉 `reviewed`）。 */
export const STANDARD_STAGE_ORDER: readonly StageName[] = STAGE_ORDER.filter(
  (stage) => stage !== 'reviewed',
);

/**
 * 本次请求该渲染几格。
 *
 * 依据是**前端自己请求的深度**（`analysisDepth`），而不是「等后端发不发」——
 * 进度条必须在请求发出的那一刻就是最终形状，否则会先画出 8 格再抽掉一格。
 */
export function stageOrderFor(depth: AnalysisDepth): readonly StageName[] {
  return depth === 'deep' ? STAGE_ORDER : STANDARD_STAGE_ORDER;
}

/** 阶段的中文显示名。**只做展示**，不参与任何判断。 */
export const STAGE_LABEL: Record<StageName, string> = {
  accepted: '接收',
  parsed: '解析',
  cleaned: '清洗',
  normalized: '归一化',
  matched: '匹配',
  recommended: '推荐',
  llm: 'AI 评审',
  reviewed: '逐条判定',
};

export type StageStatus = 'start' | 'ok' | 'fail';

/** `stage` 事件载荷。`detail` 是事实（页数 / 文本长度 / 技能数…），可直接展示。 */
export interface StagePayload {
  stage: StageName;
  status: StageStatus;
  elapsedMs: number;
  detail: Record<string, unknown>;
}

/** `meta` 事件载荷 —— 建连后立刻收到，是**第一个**事件。 */
export interface MetaPayload {
  traceId: string;
  source: 'pdf' | 'text';
}

/** `error` 事件载荷 —— 致命阶段失败，终止序列（后面仍会来 `done`）。 */
export interface ErrorPayload {
  code: string;
  message: string;
  traceId: string;
}

/** `done` 事件载荷 —— 必为最后一个事件。 */
export interface DonePayload {
  elapsedMs: number;
}

// ---------------------------------------------------------------- result 主体

export type IssueType =
  | 'NO_QUANTIFY'
  | 'NO_STAR'
  | 'SKILL_STUFFING'
  | 'TIMELINE_GAP'
  | 'MISSING_CONTACT';

export type Severity = 'high' | 'medium' | 'low';
export type Importance = 'required' | 'preferred';

export const ISSUE_TYPE_LABEL: Record<IssueType, string> = {
  NO_QUANTIFY: '缺少量化',
  NO_STAR: '缺少 STAR 结构',
  SKILL_STUFFING: '技能堆砌',
  TIMELINE_GAP: '时间线断档',
  MISSING_CONTACT: '缺少联系方式',
};

export const SEVERITY_LABEL: Record<Severity, string> = {
  high: '高',
  medium: '中',
  low: '低',
};

export const IMPORTANCE_LABEL: Record<Importance, string> = {
  required: '必须',
  preferred: '加分',
};

export interface NormalizedSkill {
  raw: string;
  canonical: string;
  category?: string | null;
}

export interface ResumeSections {
  education: string[];
  experience: string[];
  projects: string[];
  skills: string[];
}

export interface ResumeView {
  sections: ResumeSections;
  skills: NormalizedSkill[];
}

export interface Issue {
  type: IssueType;
  severity: Severity;
  evidence: string;
  suggestion: string;
}

export interface MatchedItem {
  skill: string;
  importance: Importance;
  weight: number;
  jdEvidence: string;
  resumeEvidence: string;
  jdOffset?: number | null;
  resumeOffset?: number | null;
}

export interface MissingItem {
  skill: string;
  importance: Importance;
  suggestion: string;
}

/** 匹配结果。**part2 起可空** —— 未指定 `jobId` / `jdText` 时后端返回 `null`。 */
export interface MatchResult {
  score: number;
  matched: MatchedItem[];
  missing: MissingItem[];
}

export interface RecommendationMatchedItem {
  skill: string;
  importance: Importance;
}

export interface RecommendationMissingItem {
  skill: string;
  importance: Importance;
  suggestion: string;
}

export interface Recommendation {
  jobId: string;
  title: string;
  company?: string | null;
  level?: string | null;
  score: number;
  matched: RecommendationMatchedItem[];
  missing: RecommendationMissingItem[];
  reason: string;
}

export interface Meta {
  traceId: string;
  llmUsed: boolean;
  degraded: boolean;
  elapsedMs: number;
  source: 'pdf' | 'text';
  truncated: boolean;
  recommendationCount: number;
  // part3：**仅 deep 出现**。standard 模式下这三个键**不存在**（AC25），
  // 所以是可选而不是 `null` —— 用 `null` 会逼着调用方去区分「没有」和「是空」。
  analysisDepth?: AnalysisDepth;
  verdictCount?: number;
  directionCount?: number;
}

// ---------------------------------------------------------------- part3：LLM 深度匹配分析

/** 分析深度（part3 §2.2）。**缺省 `standard`** —— 老行为一字不变。 */
export type AnalysisDepth = 'standard' | 'deep';

export const ANALYSIS_DEPTH_LABEL: Record<AnalysisDepth, string> = {
  standard: '标准（匹配 + 推荐）',
  deep: '深度（+ 逐条判定与能力画像）',
};

/** 逐条判定档位（part3 §2.3 冻结三档）。 */
export type VerdictKind = 'satisfied' | 'partial' | 'missing';

export const VERDICT_LABEL: Record<VerdictKind, string> = {
  satisfied: '满足',
  partial: '部分满足',
  missing: '缺失',
};

/** 判定标签颜色。只影响展示，不参与判断。 */
export const VERDICT_TAG_TYPE: Record<VerdictKind, 'success' | 'warning' | 'danger'> = {
  satisfied: 'success',
  partial: 'warning',
  missing: 'danger',
};

/** 对**一条岗位要求**的判定。`jdEvidence` / `resumeEvidence` 是逐字原文，用于展开溯源。 */
export interface Verdict {
  skill: string;
  importance: Importance;
  verdict: VerdictKind;
  reason: string;
  jdEvidence?: string | null;
  resumeEvidence?: string | null;
}

/** 优化点 —— 怎么改简历。`targets` 是它服务于哪几条要求。 */
export interface Improvement {
  area: string;
  action: string;
  evidence: string;
  targets: string[];
}

/** 提升方向 —— 该补什么能力。`priority` 由**代码**排序（前端不再排）。 */
export interface GrowthDirection {
  direction: string;
  why: string;
  firstStep: string;
  priority: number;
}

/**
 * 一个能力维度的分数。
 *
 * ⚠️ `score === null` 表示**该维算不出**，前端必须显示「无依据」，
 * **不得画成 0 分**（spec §2.5.2 ①：软性维度没证据是常态，不是缺点）。
 */
export interface AbilityDimension {
  name: string;
  score: number | null;
  rubricRef: string;
  evidence: string;
}

export interface AbilityProfile {
  dimensions: AbilityDimension[];
  overall: number | null;
}

/** `result` 事件的 data = 完整响应体（part2 spec §2.3 + part3 §2.3）。 */
export interface AnalyzeResult {
  resume: ResumeView;
  issues: Issue[];
  match: MatchResult | null;
  recommendations: Recommendation[];
  /**
   * part3 的四个块**只在 `deep` 模式下存在**。
   *
   * 声明成可选（而不是 `null`）是刻意的：契约要求 `standard` 模式下这些键
   * **完全不出现**（AC25 的「与 part2 逐字节一致」）。写成 `| null` 会诱导调用方
   * 写 `v-if="result.verdicts !== null"`，而真实语义是「键不存在」。
   */
  verdicts?: Verdict[];
  improvements?: Improvement[];
  growthDirections?: GrowthDirection[];
  abilityProfile?: AbilityProfile | null;
  meta: Meta;
}

/** 提交给流式端点的入参（与 spec §2.2 + part3 §2.2 一致）。 */
export interface AnalysisInput {
  file?: File | null;
  resumeText?: string;
  jobId?: string;
  jdText?: string;
  /** part3：缺省 `standard`（老行为）。 */
  analysisDepth?: AnalysisDepth;
  /** part3：推荐条数上限 1..10；缺省由后端落回 3。 */
  topN?: number;
}

/** 建流**之前**的同步错误（413 / 415 / 400 / 5xx）—— 走这里，不是 SSE `error`。 */
export interface SyncErrorBody {
  code: string;
  message: string;
  traceId?: string;
}
