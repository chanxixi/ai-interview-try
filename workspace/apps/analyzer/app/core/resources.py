"""仓库内**只读数据资源**的统一入口（指南 §4.1）。

## 为什么单独一个文件

本项目有三种「看起来都像配置」的东西，但它们**变化的原因不同**：

| 东西 | 性质 | 归谁管 | 改它的后果 |
|---|---|---|---|
| `constants.py` | **契约常量**（长度上限 / 权重 / header 名） | `core/constants.py` | 要同步 `spec.md` + 三份 OpenAPI |
| `.env` / 环境变量 | **部署配置**（可被环境覆盖） | `core/config.py` | 只影响这一次部署 |
| `app/data/*.yaml` | **仓库数据**（随代码分发的只读资源） | **本文件** | 只影响数据本身 |

混在一起会导致「改一个词典条目要翻契约文件」这类误判 —— 所以分三处。

## 为什么按 `__file__` 定位，不按 CWD

与 `core/config.py` 的 `.env` **正好相反**：`.env` 是部署配置，跟着**进程工作目录**走；
数据资源是仓库产物，**跟着代码走**。否则从别的目录启动 uvicorn 时资源会加载失败 ——
而这里的失败是**静默**的（空词典 → 所有技能都是 `unknown` → 匹配度全是 0），
属于最难查的一类假故障。

## 分层约束（决定了本文件的边界）

本文件**只依赖标准库 + `yaml`**，**绝不 import `service`** ——
`core` 不得依赖 `service`（指南 §4.2）。

因此分工是：
- **读成 `dict`**（路径拼接 / 解析 / 顶层类型校验）→ 本文件；
- **解释成领域对象**（如 `SkillDictionary` 的别名歧义检查、`category` 闭集校验）→ 各自的 service。

同一条约束也决定了 `get_dictionary()` **不能**搬到这里 —— 它返回的是
`service.normalizer.SkillDictionary`，放进来就等于 `core` 依赖 `service`。
"""

from __future__ import annotations
from pathlib import Path
import yaml

#: `app/data/` 的绝对路径。**全项目唯一**拼接这个路径的地方。
DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def resource_path(name: str) -> Path:
    """返回 `app/data/<name>` 的绝对路径。

    **不在这里检查存在性**：调用方通常需要区分「路径算错了」与「文件真缺了」，
    两者该给不同的文案（前者是代码 bug，后者是漏提交）。
    """
    return DATA_DIR / name


def read_yaml(path: Path | str) -> dict:
    """读取一个 YAML 数据文件，并要求顶层是 mapping。

    **缺文件 / 解析失败 / 顶层不是 mapping，一律立刻抛**，绝不返回空 dict：
    空资源会让下游「看起来一切正常，结果全空」（空词典 → 技能全 `unknown` →
    匹配度全 0），比启动即炸难查得多。宁可炸在启动时。
    """
    target = Path(path)
    if not target.is_file():
        raise FileNotFoundError(f"数据资源不存在：{target}")

    raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"数据资源顶层必须是 mapping：{target}")
    return raw
