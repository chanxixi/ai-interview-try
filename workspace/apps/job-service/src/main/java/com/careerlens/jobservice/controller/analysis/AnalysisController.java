package com.careerlens.jobservice.controller.analysis;

import com.careerlens.jobservice.config.StreamExecutorConfig;
import com.careerlens.jobservice.client.AnalyzerStreamClient;
import com.careerlens.jobservice.dto.JobCandidateDto;
import com.careerlens.jobservice.exception.BusinessException;
import com.careerlens.jobservice.exception.ErrorCode;
import com.careerlens.jobservice.service.AnalysisOrchestrationService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.servlet.mvc.method.annotation.ResponseBodyEmitter;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.util.List;

/**
 * 流式分析入口 —— {@code POST /api/analysis/stream}（tasks.md M5.6）。
 *
 * <h2>本类的职责边界（写死，防止它长胖）</h2>
 * <ul>
 *   <li><b>做</b>：接 multipart、做第二道大小校验、装配候选集、把 SSE 帧透传给前端</li>
 *   <li><b>不做</b>：解析 PDF（{@code AnalyzerStreamClient} 只搬字节）、
 *       打分 / 归一化（Python 的事）、判文件类型（BFF 是第一道，spec.md §2.5）</li>
 * </ul>
 *
 * <h2>为什么用 {@link ResponseBodyEmitter} 而不是 {@code SseEmitter}</h2>
 * {@code SseEmitter} 会把每次 {@code send} 包成它自己那套事件格式，
 * 而这里要的是<b>字节级透传</b> —— Python 发来的帧长什么样，前端就收到什么样。
 * 用 {@code ResponseBodyEmitter} + 手写 {@code text/event-stream}，
 * 中间不引入任何重新编码。（tasks.md M5.6 提到的 {@code SseEmitter(timeout=130_000)}
 * 超时语义由 {@code spring.mvc.async.request-timeout} 等价提供。）
 *
 * <h2>独立线程池</h2>
 * 转发跑在专用 {@link Executor} 上而不用 Servlet 线程 —— 否则一条分析（几十秒）
 * 会占满 Tomcat 的工作线程，其他请求全部排队。
 */
@RestController
@RequestMapping("/api/analysis")
public class AnalysisController {

    private static final Logger log = LoggerFactory.getLogger(AnalysisController.class);

    /** 与 BFF / analyzer 同一口径：10 MB（spec.md §2.5）。 */
    private static final long MAX_UPLOAD_BYTES = 10L * 1024 * 1024;

    /** multipart 字段名 —— 与 {@code bff-python.yaml} 的 {@code AnalyzeStreamRequest} 逐字一致。 */
    static final String FIELD_FILE = "file";
    static final String FIELD_RESUME_TEXT = "resumeText";
    static final String FIELD_JOB_ID = "jobId";
    static final String FIELD_JD_TEXT = "jdText";
    static final String FIELD_CANDIDATES = "jobCandidates";

    private final AnalysisOrchestrationService orchestrationService;
    private final AnalyzerStreamClient analyzerStreamClient;
    private final org.springframework.core.task.TaskExecutor streamExecutor;
    private final ObjectMapper objectMapper;

    public AnalysisController(AnalysisOrchestrationService orchestrationService,
                              AnalyzerStreamClient analyzerStreamClient,
                              @org.springframework.beans.factory.annotation.Qualifier(
                                      StreamExecutorConfig.STREAM_EXECUTOR)
                              org.springframework.core.task.TaskExecutor streamExecutor,
                              ObjectMapper objectMapper) {
        this.orchestrationService = orchestrationService;
        this.analyzerStreamClient = analyzerStreamClient;
        this.streamExecutor = streamExecutor;
        this.objectMapper = objectMapper;
    }

    /**
     * {@code produces = text/event-stream} 是<b>必须的</b>：{@code ResponseBodyEmitter}
     * 的 {@code send(..., MediaType)} 只设置单次写入的媒体类型，<b>不会</b>写到响应头。
     * 少了它，响应的 Content-Type 是空的 —— 前端拿 {@code content-type} 判断
     * 「走流式还是回退同步」（AC21）就失效了。
     */
    @PostMapping(
            value = "/stream",
            consumes = MediaType.MULTIPART_FORM_DATA_VALUE,
            produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public ResponseBodyEmitter stream(
            jakarta.servlet.http.HttpServletResponse servletResponse,
            @RequestParam(value = FIELD_FILE, required = false) MultipartFile file,
            @RequestParam(value = FIELD_RESUME_TEXT, required = false) String resumeText,
            @RequestParam(value = FIELD_JOB_ID, required = false) String jobId,
            @RequestParam(value = FIELD_JD_TEXT, required = false) String jdText,
            @RequestHeader(value = "X-Trace-Id", required = false) String traceId) throws IOException {

        // ---- 第二道校验（spec.md §2.5：建流前能判定的走同步 HTTP）----------------
        // 第一道在 BFF（大小 / MIME / magic number）。这里只兜底「被直接调用」的情况。
        byte[] fileBytes = null;
        String fileName = null;
        if (file != null && !file.isEmpty()) {
            if (file.getSize() > MAX_UPLOAD_BYTES) {
                throw new BusinessException(ErrorCode.FILE_TOO_LARGE);
            }
            fileBytes = file.getBytes();
            fileName = file.getOriginalFilename();
        }
        if (fileBytes == null && (resumeText == null || resumeText.isBlank())) {
            throw new BusinessException(ErrorCode.INVALID_INPUT, "file 与 resumeText 至少提供一个");
        }

        // ---- 候选集装配（全项目唯一给 Python 数据的地方）------------------------
        List<JobCandidateDto> candidates = orchestrationService.assembleCandidates();
        String candidatesJson = objectMapper.writeValueAsString(candidates);

        // 目标岗位的 JD 原文走顶层字段下发（契约 R2），不进候选集
        String targetJdText = jdText;
        if (jobId != null && jdText == null) {
            targetJdText = orchestrationService.findJdTextByJobId(jobId).orElse(null);
        }

        log.info("analysis stream accepted (candidates={}, jobId={}, hasFile={}, traceId={})",
                candidates.size(), jobId, fileBytes != null, traceId);

        // ---- 响应头（SSE 三件套，缺一不可）----------------------------------------
        // Content-Type 必须**显式设**：ResponseBodyEmitter 的 send(..., MediaType) 只管
        // 单次写入，produces 也不会落到响应头上（实测 curl -D 拿不到 Content-Type）。
        // 少了它，前端按 content-type 判断「走流式还是回退同步」（AC21）就失效了。
        servletResponse.setContentType(MediaType.TEXT_EVENT_STREAM_VALUE);
        servletResponse.setCharacterEncoding(StandardCharsets.UTF_8.name());
        // no-cache：代理层不能缓存整条流；X-Accel-Buffering=no：Nginx 默认会攒批 SSE。
        servletResponse.setHeader("Cache-Control", "no-cache");
        servletResponse.setHeader("X-Accel-Buffering", "no");

        // ---- 透传 ----------------------------------------------------------------
        ResponseBodyEmitter emitter = new ResponseBodyEmitter(0L);
        final byte[] payload = fileBytes;
        final String name = fileName;
        final String text = resumeText;
        final String jd = targetJdText;
        final String cands = candidatesJson;
        final String trace = traceId == null ? "-" : traceId;

        emitter.onCompletion(() -> log.debug("stream completed (traceId={})", trace));
        emitter.onTimeout(() -> log.warn("stream timeout (traceId={})", trace));
        emitter.onError(throwable -> log.warn("stream error (traceId={}, type={})",
                trace, throwable.getClass().getSimpleName()));

        streamExecutor.execute(() -> {
            try {
                int status = analyzerStreamClient.stream(
                        payload, name, text, jobId, jd, cands,
                        line -> {
                            try {
                                emitter.send(line, MediaType.TEXT_EVENT_STREAM);
                            } catch (IOException ex) {
                                // 前端已断开。记日志后让上游自然结束 —— 不往外抛，
                                // 抛出去会让 Spring 再尝试写一次响应（二次错误，plan §6.3）。
                                log.info("client gone, stop forwarding (traceId={})", trace);
                                throw new UncheckedIOException(ex);
                            }
                        });
                if (status != 200) {
                    // 上游没建成流：这里还来得及返回一个同步错误，而不是 200 + 空流
                    emitter.send("{\"code\":\"ANALYSIS_FAILED\",\"message\":\"分析服务返回 "
                            + status + "\"}", MediaType.APPLICATION_JSON);
                }
                emitter.complete();
            } catch (UncheckedIOException ex) {
                log.info("stream aborted by client (traceId={})", trace);
                emitter.complete();
            } catch (Exception ex) {
                log.error("stream forwarding failed (traceId={}, type={})",
                        trace, ex.getClass().getSimpleName(), ex);
                emitter.completeWithError(ex);
            }
        });

        return emitter;
    }
}
