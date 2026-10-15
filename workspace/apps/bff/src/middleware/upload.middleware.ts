import multer from '@koa/multer';
import type { Context, Next } from 'koa';

import { AppError } from '../errors/appError';

/**
 * 上传文件校验 —— **全项目唯一的文件校验点**（plan.md §7「唯一职责文件」）。
 *
 * 三条判据，全部在**建流之前**完成（spec.md §2.5 的分界线：
 * 「建流前能判定的」走同步 HTTP，「必须读完文件才知道的」才走 SSE error）：
 *
 * | 判据 | 错误 | 为什么 |
 * |---|---|---|
 * | 大小 ≤ 10MB | 413 `FILE_TOO_LARGE` | 内存不落盘（ADR-110），10MB 是上限 |
 * | MIME 是 `application/pdf` | 415 `UNSUPPORTED_FILE_TYPE` | 第一道，便宜但不保险（客户端可伪造） |
 * | **magic number 是 `%PDF-`** | 415 `UNSUPPORTED_FILE_TYPE` | **真正的判据**：改名为 .pdf 的 docx 必须被拦下（AC12） |
 *
 * **为什么信 magic number 不信扩展名**：AC12 的验收是「把 docx 改名成 .pdf」——
 * 扩展名是客户端给的，MIME 也是客户端给的，只有文件头的 5 个字节是文件自己的属性。
 *
 * **为什么 `resumeText` 路径也要过这里**：两条入口对「有没有内容」的约束应该一致，
 * 分开写两份校验迟早会不一致（指南 §5.3 原则 8）。
 */

/** 与 Java / Python 同一口径：10 MB（spec.md §2.5）。 */
export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;

/** PDF 文件头的 magic number。 */
const PDF_MAGIC = Buffer.from('%PDF-', 'ascii');

/** PDF 的合法 MIME。 */
const PDF_MIME = 'application/pdf';

export interface UploadedFile {
  buffer: Buffer;
  filename: string;
  mimetype: string;
  size: number;
}

export interface UploadPayload {
  file: UploadedFile | null;
  fields: Record<string, string>;
}

/**
 * multipart 解析 —— **memoryStorage，绝不落盘**（spec.md §2.8 / ADR-110）。
 *
 * <h2>为什么是 memoryStorage 而不是磁盘</h2>
 * 简历是 PII。落盘就要回答「什么时候删」「删不干净怎么办」「容器重启残留谁负责」——
 * 三个问题都是纯粹的新增风险。10 MB 上限下的内存占用是可接受的，
 * 而「不落盘」把「上传物被写进仓库 / 被另一个请求读到」变成结构上不可能。
 *
 * <h2>limits 是防御，不是校验</h2>
 * - `fileSize`：超限直接拒，不让大文件吃光内存；
 * - `files: 1`：本期只收一个文件（多文件是 Out of Scope）；
 * - `fields: 10`：防止「发 10 万个字段」的放大攻击。
 *
 * 真正的准入判据在 {@link validateFile}，解析只负责把字节拿到手。
 */
export const uploadParser = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: MAX_UPLOAD_BYTES, files: 1, fields: 10 },
});

/**
 * Koa 中间件：解析 multipart → 校验 → 把结果放进 `ctx.state.upload`。
 *
 * 挂在路由上（`router.post(..., uploadGuard, controller.stream)`）而不是写进 controller ——
 * 「请求进来先过校验」因此在路由表里可见，controller 拿到的也一定是校验过的载荷。
 *
 * 校验失败抛 `AppError`，由统一 errorHandler 收口成 `{code, message, traceId}`。
 */
export async function uploadGuard(ctx: Context, next: Next): Promise<void> {
  // @koa/multer v4 的 .single() 返回的就是 Koa 中间件 (ctx, next)，不用手动适配
  await uploadParser.single('file')(ctx, () => Promise.resolve());

  ctx.state.upload = extractUpload(ctx);
  await next();
}

/**
 * 从 Koa ctx 里取出已解析的上传载荷。
 *
 * 返回**纯数据**而不是挂副作用：controller 显式接收 `UploadPayload`，
 * 「读了什么」在数据流上可见。
 */
export function extractUpload(ctx: Context): UploadPayload {
  const request = ctx.request as unknown as {
    body?: Record<string, unknown>;
    file?: unknown;
    files?: unknown;
  };

  const fields: Record<string, string> = {};
  if (request.body && typeof request.body === 'object') {
    for (const [key, value] of Object.entries(request.body)) {
      if (typeof value === 'string') {
        fields[key] = value;
      }
    }
  }

  const raw = request.file ?? pickFirstFile(request.files);
  if (!raw || typeof raw !== 'object') {
    ensureHasInput(null, fields);
    return { file: null, fields };
  }

  const file = normalizeFile(raw as Record<string, unknown>);
  validateFile(file);
  return { file, fields };
}

/**
 * 「file 与 resumeText 至少提供一个」—— **必须在建流之前**判定。
 *
 * 放在这里而不是 service 里，是因为 controller 会先 `ctx.status = 200` 并
 * `flushHeaders()`，一旦头发出去，抛 AppError 也改不了状态码 ——
 * 于是「什么都没传」会变成一个 200 + 空流，用户完全看不出哪里错了。
 */
export function ensureHasInput(file: UploadedFile | null, fields: Record<string, string>): void {
  if (!file && !String(fields.resumeText ?? '').trim()) {
    throw AppError.invalidInput('file 与 resumeText 至少提供一个');
  }
}

function pickFirstFile(files: unknown): unknown {
  if (Array.isArray(files)) {
    return files[0];
  }
  if (files && typeof files === 'object') {
    return Object.values(files as Record<string, unknown>)[0];
  }
  return null;
}

function normalizeFile(raw: Record<string, unknown>): UploadedFile {
  const buffer = Buffer.isBuffer(raw.buffer) ? raw.buffer : Buffer.alloc(0);
  return {
    buffer,
    filename: String(raw.originalname ?? raw.filename ?? 'resume.pdf'),
    mimetype: String(raw.mimetype ?? ''),
    size: typeof raw.size === 'number' ? raw.size : buffer.byteLength,
  };
}

/** 三条判据。顺序是「先便宜后昂贵」：大小 → MIME → 读字节。 */
export function validateFile(file: UploadedFile): void {
  if (file.size > MAX_UPLOAD_BYTES) {
    throw AppError.fileTooLarge(MAX_UPLOAD_BYTES / 1024 / 1024);
  }
  if (file.mimetype && file.mimetype !== PDF_MIME) {
    throw AppError.unsupportedFileType();
  }
  if (!startsWithPdfMagic(file.buffer)) {
    // ★ AC12：改名成 .pdf 的 docx 就栽在这里
    throw AppError.unsupportedFileType('文件内容不是 PDF（magic number 不匹配）');
  }
}

/** magic number 判定：前 5 个字节必须是 `%PDF-`。 */
export function startsWithPdfMagic(buffer: Buffer): boolean {
  if (buffer.length < PDF_MAGIC.length) {
    return false;
  }
  return buffer.subarray(0, PDF_MAGIC.length).equals(PDF_MAGIC);
}

/** multer 的错误 → 契约里的 AppError。413 由 fileSize limit 触发。 */
export function mapMulterError(error: unknown): AppError | null {
  if (!(error instanceof Error) || error.name !== 'MulterError') {
    return null;
  }
  const code = (error as unknown as { code?: string }).code;
  if (code === 'LIMIT_FILE_SIZE') {
    return AppError.fileTooLarge(MAX_UPLOAD_BYTES / 1024 / 1024);
  }
  return AppError.invalidInput('上传内容解析失败');
}
