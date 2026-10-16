package com.careerlens.jobservice.config.rubric;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Component;
import org.yaml.snakeyaml.Yaml;

import java.io.InputStream;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;

/**
 * 维度权重装配（part3 N2.3 / ADR-209）。
 *
 * <p>为什么权重<b>经过 Java</b>：{@code abilityProfile.overall} 的权重「来自岗位侧」
 * （part3 spec §2.3），而<b>岗位数据只有 Java 有</b>（part1 §2.6：Python 不连库）。
 * 所以由本类把目标岗位对应的权重档装配到候选集上，随 {@code JobCandidateDto} 下发。
 *
 * <p><b>为什么读的是 analyzer 的文件</b>：权重表是<b>数据</b>，真源只有一份 ——
 * {@code apps/analyzer/app/data/rubric.yaml}（part3 spec §2.5.2 ②）。
 * {@code pom.xml} 已把它并入本模块的 classpath（{@code pom.xml} 的第二个
 * {@code <resource>}）。在 Java 里再抄一张权重表，就变成「两处副本」：
 * 改一处忘一处是<b>静默</b>的，只会让综合分悄悄地按旧权重算（DoD 12 明令禁止）。
 *
 * <p><b>拿不到权重时怎么办</b>：不阻塞启动，只记 WARN 并把该字段留 {@code null}。
 * Python 收到 {@code null} 会回退自己的 {@code rubric.yaml} —— 比「启动即炸」和
 * 「按一张空权重表算出 0 分」都更可接受（part3 plan §6.2）。
 */
@Component
public class RubricWeightsProvider {

    private static final Logger log = LoggerFactory.getLogger(RubricWeightsProvider.class);

    /** 与 analyzer 共用的维度真源（Maven 已并入 classpath，见 {@code pom.xml}）。 */
    static final String RESOURCE = "rubric.yaml";

    /** 六维 —— **冻结集合**，与 {@code rubric.yaml} / {@code core/constants.py} 同源。 */
    public static final List<String> DIMENSIONS = List.of(
            "tech_depth", "engineering", "business", "impact", "collaboration", "growth");

    /** 默认档：与 analyzer 的 {@code rubric.DEFAULT_WEIGHT_LEVEL} 一致（认不出级别时用中性档）。 */
    public static final String DEFAULT_WEIGHT_LEVEL = "mid";

    /**
     * 岗位 {@code level} → 权重档。**顺序即优先级**（{@code 校招} 必须先于 {@code mid} 判）。
     *
     * <p>⚠️ 这是全项目唯一一处「同一个映射写了两遍」：另一处是
     * {@code analyzer/app/service/rubric.py} 的 {@code _WEIGHT_LEVEL_HINTS}。
     * 没有把它塞进 {@code rubric.yaml}，是因为那会让一份「描述能力维度」的数据文件
     * 顺带描述「岗位级别怎么命名」，职责混杂；而它只有 3 档 × 几个词，同步成本可控。
     * <b>改这里必须同步改那边</b>（DoD 15 的同思路）。
     */
    private static final Map<String, List<String>> LEVEL_HINTS = new LinkedHashMap<>();

    static {
        LEVEL_HINTS.put("campus",
                List.of("校招", "应届", "实习", "campus", "graduate", "junior", "intern"));
        LEVEL_HINTS.put("senior",
                List.of("高级", "资深", "专家", "架构师", "senior", "expert", "lead", "principal"));
        LEVEL_HINTS.put("mid",
                List.of("社招", "中级", "mid", "middle", "regular"));
    }

    private final Map<String, Map<String, Double>> weightsByLevel;

    public RubricWeightsProvider() {
        this.weightsByLevel = load();
    }

    /** 岗位 {@code level} 字符串 → 权重档名（{@code campus} / {@code mid} / {@code senior}）。 */
    public String weightLevelFor(String jobLevel) {
        if (jobLevel == null || jobLevel.isBlank()) {
            return DEFAULT_WEIGHT_LEVEL;
        }
        String lowered = jobLevel.trim().toLowerCase(Locale.ROOT);
        for (Map.Entry<String, List<String>> entry : LEVEL_HINTS.entrySet()) {
            for (String hint : entry.getValue()) {
                if (lowered.contains(hint)) {
                    String name = entry.getKey();
                    return weightsByLevel.containsKey(name) ? name : DEFAULT_WEIGHT_LEVEL;
                }
            }
        }
        return DEFAULT_WEIGHT_LEVEL;
    }

    /**
     * 取某一档的六维权重。
     *
     * @return 权重表；**拿不到就返回 {@link Optional#empty()}**（而不是空 Map）——
     *         空 Map 会让 Python 侧看起来「有值但和为 0」，而空 Optional 语义明确：
     *         没装配上，请回退。
     */
    public Optional<Map<String, Double>> weightsFor(String jobLevel) {
        return Optional.ofNullable(weightsByLevel.get(weightLevelFor(jobLevel))).map(Map::copyOf);
    }

    /** 当前已加载的档位数（供健康检查 / 测试断言；0 表示 rubric 没读进来）。 */
    public int loadedLevelCount() {
        return weightsByLevel.size();
    }

    @SuppressWarnings("unchecked")
    private Map<String, Map<String, Double>> load() {
        try (InputStream in = new ClassPathResource(RESOURCE).getInputStream()) {
            Object root = new Yaml().load(in);
            if (!(root instanceof Map)) {
                log.warn("rubric.yaml top-level is not a mapping, dimension weights unavailable");
                return Map.of();
            }
            Object raw = ((Map<String, Object>) root).get("weights");
            if (!(raw instanceof Map)) {
                log.warn("rubric.yaml has no `weights` block, dimension weights unavailable");
                return Map.of();
            }

            Map<String, Map<String, Double>> parsed = new LinkedHashMap<>();
            for (Map.Entry<String, Object> entry : ((Map<String, Object>) raw).entrySet()) {
                if (!(entry.getValue() instanceof Map)) {
                    continue;
                }
                Map<String, Double> table = new LinkedHashMap<>();
                for (Map.Entry<String, Object> inner
                        : ((Map<String, Object>) entry.getValue()).entrySet()) {
                    Object value = inner.getValue();
                    if (value instanceof Number number) {
                        table.put(String.valueOf(inner.getKey()), number.doubleValue());
                    }
                }
                // 六维必须齐：缺一维的权重表会让 overall 的分母少一项，而**没人看得出来**。
                // 宁可整档丢弃（Python 会回退），也不要下发一张可疑的表。
                if (!table.keySet().equals(new java.util.LinkedHashSet<>(DIMENSIONS))) {
                    log.error("rubric weights level `{}` does not cover the six dimensions (keys={}), skipped",
                            entry.getKey(), table.keySet());
                    continue;
                }
                parsed.put(String.valueOf(entry.getKey()), table);
            }
            log.info("rubric dimension weights loaded: levels={}", parsed.keySet());
            return parsed;
        } catch (Exception ex) {
            // 不阻塞启动：拿不到权重 → DTO 字段为 null → Python 回退自己的 rubric.yaml。
            log.warn("rubric dimension weights unavailable, will be omitted (reason={})",
                    ex.getClass().getSimpleName());
            return Map.of();
        }
    }
}
