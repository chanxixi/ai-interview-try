/**
 * 上传校验（tasks.md M6.2）—— 全项目唯一的文件校验点。
 *
 * 重点是 AC12 / AC13 两条：
 *   AC12：改名成 .pdf 的 docx → 415（靠 magic number，不靠扩展名、不靠 MIME）
 *   AC13：>10MB → 413，且**不建立 SSE 流**
 */

import { AppError } from '../../src/errors/appError';
import {
  MAX_UPLOAD_BYTES,
  extractUpload,
  mapMulterError,
  startsWithPdfMagic,
  validateFile,
  type UploadedFile,
} from '../../src/middleware/upload.middleware';

/** 捕获抛出的错误以便断言它的 status / code（toMatchObject 不能直接作用于函数）。 */
function catchAppError(fn: () => void): AppError {
  try {
    fn();
  } catch (error) {
    return error as AppError;
  }
  throw new Error('expected validateFile to throw, but it did not');
}

function fakeCtx(body: Record<string, unknown>, file?: unknown) {
  return {
    request: { body, file, files: undefined },
  } as never;
}

function fileOf(overrides: Partial<UploadedFile>): UploadedFile {
  return {
    buffer: Buffer.from('%PDF-1.4 fake'),
    filename: 'resume.pdf',
    mimetype: 'application/pdf',
    size: 15,
    ...overrides,
  };
}

describe('startsWithPdfMagic', () => {
  it('合法的 PDF 头', () => {
    expect(startsWithPdfMagic(Buffer.from('%PDF-1.4\n...'))).toBe(true);
  });

  it('docx 的 PK 头 → false（★ AC12 的核心判据）', () => {
    // docx / zip 的文件头是 PK\x03\x04
    expect(startsWithPdfMagic(Buffer.from([0x50, 0x4b, 0x03, 0x04, 0x00]))).toBe(false);
  });

  it('空文件 / 过短 → false', () => {
    expect(startsWithPdfMagic(Buffer.alloc(0))).toBe(false);
    expect(startsWithPdfMagic(Buffer.from('%PD'))).toBe(false);
  });
});

describe('validateFile', () => {
  it('合法 PDF 通过', () => {
    expect(() => validateFile(fileOf({}))).not.toThrow();
  });

  it('>10MB → 413 FILE_TOO_LARGE', () => {
    expect(catchAppError(() => validateFile(fileOf({ size: MAX_UPLOAD_BYTES + 1 })))).toMatchObject({
      status: 413,
      code: 'FILE_TOO_LARGE',
    });
  });

  it('MIME 不是 pdf → 415', () => {
    expect(catchAppError(() => validateFile(fileOf({ mimetype: 'image/png' })))).toMatchObject({
      status: 415,
      code: 'UNSUPPORTED_FILE_TYPE',
    });
  });

  it('MIME 是 pdf 但内容不是 → 415（只信字节，不信客户端声明）', () => {
    const error = catchAppError(() => validateFile(fileOf({ buffer: Buffer.from('PK\x03\x04') })));
    expect(error.status).toBe(415);
  });
});

describe('extractUpload', () => {
  it('无文件时返回 file: null，并把字段原样带出', () => {
    const payload = extractUpload(fakeCtx({ resumeText: '张三', jobId: 'job-a' }));
    expect(payload.file).toBeNull();
    expect(payload.fields).toEqual({ resumeText: '张三', jobId: 'job-a' });
  });

  it('非字符串字段被丢弃（防止 prototype 污染式输入）', () => {
    // ⚠️ 必须同时给一个合法的 resumeText：`extractUpload` 在收尾时会调
    // `ensureHasInput`，「既没文件也没 resumeText」是 400 INVALID_INPUT（有意为之）。
    // 少了它，这条用例测的就不是「非字符串被丢弃」，而是「空请求被拒」——
    // 两者混在一起，失败信息会指向完全无关的地方。
    const payload = extractUpload(fakeCtx({ a: '1', b: 2, c: null, resumeText: '张三' } as never));
    expect(payload.fields).toEqual({ a: '1', resumeText: '张三' });
  });

  it('有文件且合法 → 带出 buffer', () => {
    const payload = extractUpload(
      fakeCtx({}, { buffer: Buffer.from('%PDF-1.4 x'), originalname: 'a.pdf', mimetype: 'application/pdf' }),
    );
    expect(payload.file?.filename).toBe('a.pdf');
    expect(startsWithPdfMagic(payload.file!.buffer)).toBe(true);
  });
});

describe('mapMulterError', () => {
  it('LIMIT_FILE_SIZE → 413', () => {
    const error = Object.assign(new Error('too large'), { name: 'MulterError', code: 'LIMIT_FILE_SIZE' });
    expect(mapMulterError(error)).toMatchObject({ status: 413 });
  });

  it('其它 MulterError → 400', () => {
    const error = Object.assign(new Error('bad'), { name: 'MulterError', code: 'LIMIT_UNEXPECTED_FILE' });
    expect(mapMulterError(error)).toMatchObject({ status: 400 });
  });

  it('非 multer 错误返回 null —— 交给 mapUpstreamError 兜底', () => {
    expect(mapMulterError(new Error('nope'))).toBeNull();
  });
});
