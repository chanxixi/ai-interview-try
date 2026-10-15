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
 * 7 个阶段（part2 spec §2.4 冻结，按序）。
 *
 * **顺序是契约的一部分** —— 进度条要按它渲染，所以这里声明成 `as const` 元组，
 * 既能当运行时数组用（`v-for`），又能当类型用（`typeof STAGE_ORDER[number]`）。
 */
export const STAGE_ORDER = [
  'accepted',
  'parsed',
  'cleaned',
  'normalized',
  'matched',
  'recommended',
  'llm',
] as const;

export type StageName = (typeof STAGE_ORDER)[number];

/** 阶段的中文显示名。**只做展示**，不参与任何判断。 */
export const STAGE_LABEL: Record<StageName, string> = {
  accepted: '接收',
  parsed: '解析',
  cleaned: '清洗',
  normalized: '归一化',
  matched: '匹配',
  recommended: '推荐',
  llm: 'AI 评审',
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
}

/** `result` 事件的 data = 完整响应体（part2 spec §2.3）。 */
export interface AnalyzeResult {
  resume: ResumeView;
  issues: Issue[];
  match: MatchResult | null;
  recommendations: Recommendation[];
  meta: Meta;
}

/** 提交给流式端点的入参（与 spec §2.2 一致）。 */
export interface AnalysisInput {
  file?: File | null;
  resumeText?: string;
  jobId?: string;
  jdText?: string;
}

/** 建流**之前**的同步错误（413 / 415 / 400 / 5xx）—— 走这里，不是 SSE `error`。 */
export interface SyncErrorBody {
  code: string;
  message: string;
  traceId?: string;
}
