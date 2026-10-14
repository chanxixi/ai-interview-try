/**
 * 配置层入口。
 *
 * 统一从 `../config` 引入，避免各处记住 `env` / `constants` 的物理路径。
 *   - 运行时配置（可被环境覆盖）→ `./env`
 *   - 编译期常量（代码里固定）  → `./constants`
 */
export { config, type Config } from './env';
export { API_PREFIX, BODY_LIMIT, TIMEOUT_MS, TRACE_ID_HEADER } from './constants';
