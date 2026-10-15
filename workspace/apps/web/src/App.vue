<script setup lang="ts">
import zhCn from 'element-plus/es/locale/lang/zh-cn';
import { computed } from 'vue';
import { useRoute } from 'vue-router';

/**
 * 应用外壳 —— 只负责**顶栏 + 路由出口**。
 *
 * part1 的连通性自检已迁到 `pages/connectivity`，这里不再承载业务逻辑，
 * 页面各自的状态收在各自页面内（互不污染，也方便按页拆包）。
 *
 * `<el-config-provider :locale>` 是**按需引入模式下**注入语言包的正规做法
 * （`main.ts` 里不再 `app.use(ElementPlus)`，拿不到插件级的 locale 选项）。
 */
const route = useRoute();

const activePath = computed(() => route.path);
</script>

<template>
  <el-config-provider :locale="zhCn">
    <div class="app">
      <header class="app__bar">
        <div class="app__brand">
          <span class="app__logo" aria-hidden="true">CL</span>
          <div>
            <p class="app__name">CareerLens</p>
            <p class="app__sub">简历诊断 · 岗位匹配</p>
          </div>
        </div>

        <nav class="app__nav">
          <RouterLink
            class="app__link"
            :class="{ 'is-active': activePath.startsWith('/analyzer') }"
            to="/analyzer"
          >
            简历分析
          </RouterLink>
          <RouterLink
            class="app__link"
            :class="{ 'is-active': activePath.startsWith('/connectivity') }"
            to="/connectivity"
          >
            全链自检
          </RouterLink>
        </nav>
      </header>

      <RouterView />
    </div>
  </el-config-provider>
</template>
