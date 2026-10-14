import { createJobServiceClient } from './client/jobService.client';
import { HealthController } from './controller/health.controller';
import { JobController } from './controller/job.controller';
import { createJobService } from './service/job.service';

/**
 * ★ **组合根（composition root）** —— 全项目**唯一** `new` 具体实现的地方。
 *
 * 为什么手写而不是引 inversify / tsyringe：ADR-006 定了"3 小时预算下熟悉度优先"，
 * Koa2 没有 DI 容器就是它的代价；补偿手段是**目录约定 + 单一组合根**（指南 §2.4）。
 *
 * 好处：
 *   1. 依赖方向从外向内手工装配，结构上**不可能成环**（指南 §6.5）
 *   2. 想知道"谁依赖谁"，读这一个文件就够 —— 不用追着 import 满仓库找
 *   3. 测试替换任意一层：`createApp(containerWithStubClient)`，见 tests/
 *
 * ⚠️ 除了本文件与 `app.ts`，其它文件都不应该 `new` 一个 Service / Controller。
 *    自检（指南 §A.1 第 4 条）：业务代码里出现 `new XxxServiceImpl()` 就是违规。
 */
export function buildContainer() {
  // ① 最外层：下游适配器
  const jobServiceClient = createJobServiceClient();

  // ② 业务层：只依赖适配器接口
  const jobService = createJobService({ jobService: jobServiceClient });

  // ③ 控制层：只依赖业务层
  return {
    jobServiceClient,
    controllers: {
      health: new HealthController(),
      job: new JobController(jobService),
    },
  };
}

/** 容器形状 —— 测试里可以用部分 stub 顶掉任意一层 */
export type Container = ReturnType<typeof buildContainer>;
