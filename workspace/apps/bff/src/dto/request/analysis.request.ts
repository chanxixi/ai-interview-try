import { z } from 'zod';

/**
 * `POST /api/analysis` 请求契约 —— spec.md §2.1（冻结）。
 *
 * 校验属于 BFF 职责（spec.md §2.6），所以 schema 落在 DTO 层，
 * **不写进 controller** —— controller 只取 `ctx.state.dto`（见 middleware/validate.middleware.ts）。
 *
 * 两个长度上限走不同错误码（spec.md §2.3），这是刻意的：
 *   - `jdText > 8000`      → 由本 schema 拦下 → 400 INVALID_INPUT
 *   - `resumeText > 20000` → 由 Service 拦下 → 400 RESUME_TOO_LONG
 *   原因：简历超长是独立的用户可见错误，需要专属提示文案，不能混进通用校验失败里。
 */

/** 简历文本上限，spec.md §2.1（冻结） */
export const RESUME_MAX_LENGTH = 20_000;

/** JD 文本上限，spec.md §2.1（冻结） */
export const JD_MAX_LENGTH = 8_000;

export const analyzeRequestSchema = z
  .object({
    resumeText: z.string().min(1, '简历文本不能为空'),
    jobId: z.string().min(1).optional(),
    jdText: z.string().min(1).max(JD_MAX_LENGTH, `JD 文本不能超过 ${JD_MAX_LENGTH} 字符`).optional(),
  })
  .superRefine((value, ctx) => {
    // 二选一：至少提供一个（spec.md §2.1）。同时提供时以 jobId 为准，见 service/analysis.service.ts
    if (!value.jobId && !value.jdText) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ['jobId'],
        message: 'jobId 与 jdText 至少提供一个',
      });
    }
  });

export type AnalyzeRequest = z.infer<typeof analyzeRequestSchema>;
