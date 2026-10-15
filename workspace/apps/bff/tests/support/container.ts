import type { JobServiceClient } from '../../src/client/jobService.client';
import { AnalysisController } from '../../src/controller/analysis.controller';
import { HealthController } from '../../src/controller/health.controller';
import { JobController } from '../../src/controller/job.controller';
import { createJobService } from '../../src/service/job.service';
import { createAnalysisDeps } from '../../src/service/analysis.stream.deps';

/**
 * 用 stub 的下游适配器拼一个容器（等价于 `container.ts` 的装配，只是换了最外层依赖）。
 *
 * 打桩点刻意选在**最外层**（下游适配器）：
 * Service 与 Controller 都跑真实实现，断言才能覆盖「BFF 信封字段」「错误映射」等真实行为。
 * 若直接在 Service 层打桩，这些行为就测不到了。
 *
 * 这里同时装配 `analysis` controller（part2 M6）—— 路由层要求它存在，
 * 所以凡是走 `createApiRouter` 的测试都会用到。
 */
export function containerWithJobServiceClient(jobServiceClient: JobServiceClient) {
  return {
    jobServiceClient,
    controllers: {
      health: new HealthController(),
      job: new JobController(createJobService({ jobService: jobServiceClient })),
      analysis: new AnalysisController(createAnalysisDeps()),
    },
  };
}
