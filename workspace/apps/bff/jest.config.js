/**
 * Jest 配置（plan.md §2 选型：BFF 用 jest + supertest）。
 *
 * 被测对象是 Koa app 本身，不起真实端口 —— supertest 直接喂 app.callback()。
 * 下游 HTTP 调用一律在用例里替换成 stub，测试不依赖任何外部服务。
 *
 * @type {import('jest').Config}
 */
module.exports = {
  preset: 'ts-jest',
  testEnvironment: 'node',
  roots: ['<rootDir>/tests'],
  testMatch: ['**/*.test.ts'],
  setupFiles: ['<rootDir>/tests/setup.ts'],
  transform: {
    '^.+\\.ts$': ['ts-jest', { tsconfig: '<rootDir>/tsconfig.test.json' }],
  },
  clearMocks: true,
  collectCoverageFrom: ['src/**/*.ts'],
};
