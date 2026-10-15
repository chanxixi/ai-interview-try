/**
 * 上传前置校验（tasks.md M7.4：「本地预校验（不过则**不发请求**）」）。
 *
 * <h2>为什么前端也要校验一遍</h2>
 * 后端（BFF 的 `upload.middleware.ts`）才是**权威**校验点 —— 前端校验纯粹是为了
 * 体验：10MB 的文件传上去再被 413 拒绝，用户白等十几秒。所以这里的判据
 * **与后端逐条对齐**（大小 / MIME / magic number），一旦不一致就会出现
 * 「前端放行、后端 415」这种最让人困惑的组合。
 *
 * <h2>magic number 是唯一可信的判据</h2>
 * 扩展名和 MIME 都是**客户端提供**的字符串，随手就能改。AC12 的验收场景正是
 * 「把 docx 改名成 .pdf」—— 只有文件头的 `%PDF-` 是文件自己的属性。
 * 后端按它拦（415），前端也按它拦（提前提示），两边同一个理由。
 */

/** 与 BFF / Java / Python 同一口径：10 MB（spec.md §2.5）。 */
export const MAX_UPLOAD_BYTES = Number(import.meta.env.VITE_MAX_UPLOAD_MB ?? 10) * 1024 * 1024;

/** PDF 文件头 5 字节。 */
const PDF_MAGIC = '%PDF-';

export interface UploadValidation {
  ok: boolean;
  /** 与契约里的错误码同名，便于展示时对得上后端日志。 */
  code?: 'FILE_TOO_LARGE' | 'UNSUPPORTED_FILE_TYPE';
  message?: string;
}

/** 只读文件头，不把整个文件读进内存。 */
export async function readHead(file: File, bytes = 8): Promise<string> {
  const slice = file.slice(0, bytes);
  const buffer = await slice.arrayBuffer();
  return new TextDecoder('latin1').decode(buffer);
}

/**
 * 三条判据，顺序「先便宜后昂贵」：大小 → MIME → 读字节。
 *
 * 与 BFF `validateFile()` 的判据顺序一致 —— 这样两边的「第一个报出的错」
 * 也一致，用户不会在前端看到「类型不对」、到后端却变成「太大」。
 */
export async function validateResumeFile(file: File): Promise<UploadValidation> {
  if (file.size > MAX_UPLOAD_BYTES) {
    return {
      ok: false,
      code: 'FILE_TOO_LARGE',
      message: `文件超过 ${MAX_UPLOAD_BYTES / 1024 / 1024} MB，请压缩后再上传`,
    };
  }

  // MIME 为空时不拦（部分系统给不出），交给 magic number 兜底
  if (file.type && file.type !== 'application/pdf') {
    return { ok: false, code: 'UNSUPPORTED_FILE_TYPE', message: '只支持 PDF 简历' };
  }

  const head = await readHead(file, PDF_MAGIC.length);
  if (head !== PDF_MAGIC) {
    // ★ AC12：改名成 .pdf 的 docx 栽在这里
    return {
      ok: false,
      code: 'UNSUPPORTED_FILE_TYPE',
      message: '文件内容不是 PDF（可能是改了扩展名的 Word 文档）',
    };
  }

  return { ok: true };
}
