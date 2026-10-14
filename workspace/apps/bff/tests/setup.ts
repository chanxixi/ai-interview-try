/**
 * 测试环境准备。
 *
 * 在加载任何业务模块之前把日志压到 silent，避免用例输出被结构化日志淹没。
 * （config.ts 会读 process.env，所以这里必须在 import 之前生效。）
 */
process.env.LOG_LEVEL = 'silent';
process.env.NODE_ENV = 'test';
