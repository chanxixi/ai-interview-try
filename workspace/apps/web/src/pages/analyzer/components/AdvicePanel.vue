<script setup lang="ts">
import type { GrowthDirection, Improvement } from '../../../api/analysis';

/**
 * 建议面板（part3 N5.3）—— 优化点（怎么改简历）+ 提升方向（该补什么）。
 *
 * <h2>为什么这两块放在一起，却分成两栏</h2>
 * 它们回答的是**两个不同的问题**：
 * - `improvements` = 现有简历**怎么写更好**（今天就能改）
 * - `growthDirections` = 能力上**该补什么**（要花时间学）
 *
 * 混在一个列表里，用户会分不清「改文案」和「补能力」的优先级。
 *
 * <h2>「AI 判定，仅供参考」为什么必须显式写出来</h2>
 * part3 spec §1.2 的产品边界是「**不替代人**：系统给该看哪几处，改不改留给人」。
 * 这块内容是 LLM 生成的**建议**（不是确定性计算结果），不标注会让用户把它当成
 * 权威结论 —— 与 `meta.degraded` 必须提示降级是同一个道理。
 *
 * <h2>方向条数 ≤ 5、顺序由后端定</h2>
 * 后端已按 `priority` 升序排好（spec §2.7：排序是代码的职责），前端**不再排**，
 * 只按收到的顺序渲染 —— 再排一次就是第二个排序实现。
 */
const props = defineProps<{
  improvements?: Improvement[];
  directions?: GrowthDirection[];
}>();
</script>

<template>
  <section class="panel advice-panel">
    <h2 class="panel__title">
      改进建议
      <span class="verdict-panel__hint">AI 判定，仅供参考</span>
    </h2>

    <div class="advice-panel__grid">
      <!-- 左：优化点（怎么改简历） -->
      <div class="advice-column">
        <h3 class="advice-column__title">优化点 · 简历怎么改</h3>
        <el-empty
          v-if="!props.improvements || props.improvements.length === 0"
          description="暂时没有可执行的改法"
          :image-size="64"
        />
        <ul v-else class="advice-list">
          <li v-for="(item, index) in props.improvements" :key="index" class="advice">
            <header class="advice__head">
              <el-tag size="small" effect="plain">{{ item.area }}</el-tag>
              <el-tag
                v-for="target in item.targets"
                :key="target"
                size="small"
                type="info"
                effect="light"
              >
                {{ target }}
              </el-tag>
            </header>
            <p class="advice__action">{{ item.action }}</p>
            <blockquote v-if="item.evidence" class="advice__evidence">{{ item.evidence }}</blockquote>
          </li>
        </ul>
      </div>

      <!-- 右：提升方向（补什么能力） -->
      <div class="advice-column">
        <h3 class="advice-column__title">提升方向 · 该补什么</h3>
        <el-empty
          v-if="!props.directions || props.directions.length === 0"
          description="目标岗位暂无缺口方向"
          :image-size="64"
        />
        <ol v-else class="direction-list">
          <li v-for="item in props.directions" :key="item.direction" class="direction">
            <header class="direction__head">
              <!-- priority 由后端给；这里只显示，不参与排序 -->
              <span class="direction__rank">{{ item.priority }}</span>
              <span class="direction__name">{{ item.direction }}</span>
            </header>
            <p class="direction__why">{{ item.why }}</p>
            <p class="direction__step">第一步：{{ item.firstStep }}</p>
          </li>
        </ol>
      </div>
    </div>
  </section>
</template>
