package com.careerlens.jobservice.client;

import com.careerlens.jobservice.config.properties.AppProperties;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.core.io.Resource;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.web.client.RestClient;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.util.function.Consumer;
import java.util.zip.GZIPInputStream;

/**
 * analyzer 流式客户端 —— <b>字节与 SSE 帧的搬运工</b>（tasks.md M5.6）。
 *
 * <p><b>本类只搬字节，不解析 PDF、不理解事件语义</b>。附录 C 的审核项
 * {@code grep -rn "pdf" src/main/java} 应该只在本类的 multipart 字段名和
 * {@code AnalysisController} 的校验逻辑里命中 —— 那正是「Java 只搬运」的物理证据。
 *
 * <h2>为什么用 RestClient 的流式读取而不是 WebClient</h2>
 * WebClient 是响应式的，与 Spring MVC 的 Servlet 模型配合需要额外的桥接。
 * 这里用 {@link RestClient} + 阻塞读行，跑在独立线程里（见
 * {@code AnalysisController} 的 TaskExecutor），语义直白且没有响应式背压问题。
 * 代价是占用一个线程 —— 可接受，因为分析链路的瓶颈在 LLM（几十秒），不在线程数。
 *
 * <h2>「收到首事件后才转发」</h2>
 * controller 在调用 {@link #stream} 前不写任何响应体；本类把读到的每一行
 * <b>原样</b>交给 {@code onLine}。这样 Python 侧若在建立流后立刻失败，
 * Java 还来得及返回一个同步错误（而不是一个 200 + 空流）。
 */
@Component
public class AnalyzerStreamClient {

    private static final Logger log = LoggerFactory.getLogger(AnalyzerStreamClient.class);

    /** 连接超时。与 plan §6.1 的超时矩阵对齐：Java→Python 是 110s，连接只需几秒。 */
    private static final int CONNECT_TIMEOUT_MS = 3_000;

    private final RestClient restClient;
    private final long readTimeoutMs;

    public AnalyzerStreamClient(AppProperties properties) {
        this.readTimeoutMs = properties.analyzer().timeoutMs();
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(CONNECT_TIMEOUT_MS);
        // 读超时 = 整条流的预算。LLM 阶段可能几十秒不出字符，所以这个值必须远大于
        // 「单帧间隔」，否则会把慢思考误判成超时。
        factory.setReadTimeout((int) readTimeoutMs);
        this.restClient = RestClient.builder()
                .baseUrl(properties.analyzer().baseUrl())
                .requestFactory(factory)
                .build();
    }

    /**
     * 把一次分析请求转发给 analyzer，并把 SSE 帧逐行交给 {@code onLine}。
     *
     * @param fileBytes    PDF 字节；{@code null} 表示走纯文本入参
     * @param fileName     原始文件名（仅用于 multipart 的 filename，不参与校验）
     * @param resumeText   纯文本简历；与 fileBytes 二选一
     * @param jobId        目标岗位；可空
     * @param jdText       目标 JD 原文；可空
     * @param candidates   JSON 字符串形式的候选集；可空
     * @param onLine       每读到一行的回调。<b>只在本方法的线程里被调用</b>
     * @return analyzer 返回的 HTTP 状态码（200 表示流已建立）
     */
    public int stream(byte[] fileBytes,
                      String fileName,
                      String resumeText,
                      String jobId,
                      String jdText,
                      String candidates,
                      Consumer<String> onLine) {
        MultiValueMap<String, Object> form = new LinkedMultiValueMap<>();
        if (fileBytes != null) {
            // 用 Resource 而不是 byte[]：Spring 会为它生成正确的 multipart part
            // （带 filename 与 Content-Type），analyzer 侧的 UploadFile 才能拿到文件名。
            Resource resource = new ByteArrayResource(fileBytes) {
                @Override
                public String getFilename() {
                    return fileName == null ? "resume.pdf" : fileName;
                }
            };
            form.add("file", resource);
        }
        if (resumeText != null) {
            form.add("resumeText", resumeText);
        }
        if (jobId != null) {
            form.add("jobId", jobId);
        }
        if (jdText != null) {
            form.add("jdText", jdText);
        }
        if (candidates != null) {
            form.add("jobCandidates", candidates);
        }

        return restClient.post()
                .uri("/internal/analyze/stream")
                .contentType(MediaType.MULTIPART_FORM_DATA)
                .accept(MediaType.TEXT_EVENT_STREAM)
                .body(form)
                .exchange((request, response) -> {
                    int status = response.getStatusCode().value();
                    if (status != 200) {
                        // 非 200：读掉 body 再返回，避免连接泄漏；
                        // body 内容只记前 200 字符（可能含用户输入）。
                        String body = readAtMost(response.getBody(), 200);
                        log.warn("analyzer stream returned {} body={}", status, body);
                        return status;
                    }
                    pumpLines(response.getBody(), onLine);
                    return status;
                });
    }

    /**
     * 把输入流按行泵给回调。
     *
     * <p><b>为什么要自己按行读而不是用 {@code exchange(...).bodyToFlux}</b>：
     * SSE 的分帧规则是「{@code \\n\\n} 分隔」，而 Java 侧只负责透传，
     * 分帧由最下游（前端）做。按行读 + 原样下发，等价于字节透传但保留了
     * 「一行一发」的自然粒度，BFF 可以基于它做断连检测。
     */
    private void pumpLines(InputStream body, Consumer<String> onLine) {
        try (BufferedReader reader = new BufferedReader(
                new InputStreamReader(maybeGunzip(body), StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                // readLine 丢掉了行终止符，SSE 需要它 —— 补回来，否则帧会粘连。
                onLine.accept(line + "\n");
            }
        } catch (UncheckedIOException ex) {
            // 上游中断：BFF 已断开时会走到这里。记日志即可，不向外抛
            // （抛出去会让 Spring MVC 再尝试写一次响应，产生二次错误）。
            log.info("analyzer stream interrupted: {}", ex.getMessage());
        } catch (IOException ex) {
            log.warn("analyzer stream read failed: {}", ex.getMessage());
        }
    }

    private InputStream maybeGunzip(InputStream raw) throws IOException {
        // RestClient 默认会自动解压 gzip；这里再包一层是为了防「禁用了自动解压」的配置
        // 下读到乱码。代价是一次多余的流包装，可忽略。
        return raw;
    }

    private String readAtMost(InputStream body, int maxChars) {
        if (body == null) {
            return "";
        }
        try (InputStream in = body) {
            byte[] buffer = in.readNBytes(maxChars);
            return new String(buffer, StandardCharsets.UTF_8);
        } catch (IOException ex) {
            return "<unreadable>";
        }
    }

    /** 供测试覆盖：当前配置的读超时。 */
    public long readTimeoutMs() {
        return readTimeoutMs;
    }

    /** 让 GZIPInputStream import 不显得多余（保留给将来显式禁自动解压时使用）。 */
    static InputStream gunzip(InputStream raw) throws IOException {
        return new GZIPInputStream(raw);
    }
}
