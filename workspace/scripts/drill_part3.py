#!/usr/bin/env python3
"""part3 降级演练：四条（tasks.md N6.1 / AC29）。

## 为什么这四条必须实测

降级路径的共同特征是「**不跑也不会报错**」。深分析的四个块是 LLM 产出的，
而 LLM 会超时、会返回非法 JSON、rubric 可能读不到 —— 这些都不会让 `/healthz` 变红，
只会让用户在某个版本上突然看到一片空白（或者更糟：看到**编出来的分**）。

所以每条都**主动制造故障、再断言行为**。

## 与 part2 的 `drill-degradation.sh` 有什么不同

| | part2 六条 | 本脚本四条 |
|---|---|---|
| 打桩点 | **真实 HTTP**（连四层服务） | **进程内**（直接驱动 `stream_analysis`） |
| 为什么 | 要验的是「跨进程的协议行为」（415/SSE/断连） | 要验的是「**降级分支**」——非法 JSON、rubric 缺失这类条件**在真实服务上造不出来**（服务不会主动返回坏 JSON） |

两条互补：part2 那套守**线上协议**，这套守**分支覆盖**。而且本脚本**不依赖任何服务**，
所以 CI 里能跑（`drill-degradation.sh` 需要四层全开，CI 里跑不了）。

## 四条

| # | 故障 | 断言 |
|---|---|---|
| 1 | LLM 连不上（端口没人听） | `result`/`done` 照常 · `degraded=true` · 判定退化为集合级事实且**非空** |
| 2 | LLM 返回**非法 JSON** | 同上（走的是同一个降级出口） |
| 3 | `rubric` 缺失 / 某维算不出 | `abilityProfile=null` 或该维 `score=null` 且 `overall` 按已有维度归一 —— **不编分** |
| 4 | `standard`（缺省） | 响应**逐字节回到 part2 形状** · 不发 `reviewed` |
"""

from __future__ import annotations
import asyncio
import json
import socket
import sys
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# 脚本在 scripts/ 下，analyzer 在 ../apps/analyzer —— 与 drill_degradation.py 同一套路径处理：
# 用 __file__ 自算绝对路径（Git Bash 的 MSYS 路径 Python 不认）。
ANALYZER_ROOT = (Path(__file__).resolve().parent / ".." / "apps" / "analyzer").resolve()
sys.path.insert(0, str(ANALYZER_ROOT))

from app.llm.events import LlmClient
from app.llm.client import NullLlmClient, OpenAiCompatibleClient

from app.schema.response.sse_event import SseEventType, StageName, StageStatus  # noqa: E402
from app.service.orchestration.stream import StreamRequest, stream_analysis  # noqa: E402
from app.service.match.matcher import Requirement  # noqa: E402
from app.service.skill.normalizer import get_dictionary  # noqa: E402
from app.service.match.recommender import JobCandidate  # noqa: E402
from app.util.http.sse import parse_frames  # noqa: E402

RESUME = (
    "个人信息\n张三，电话 13800138000，邮箱 zhangsan@example.com\n\n"
    "教育背景\n2019.09-2023.06 某大学 计算机科学与技术\n\n"
    "专业技能\nJava、Spring Boot、MySQL、Redis、Vue\n\n"
    "项目经历\n负责订单系统重构，接口耗时从 800ms 降到 120ms\n\n"
    "工作经历\n2023.07-2024.06 某公司 后端开发工程师\n"
)

CANDIDATES = (
    JobCandidate(
        jobId="job-deep",
        title="Java 后端",
        level="校招",
        requirements=(
            Requirement(skill="Java", importance="required", evidence="熟悉 Java"),
            Requirement(skill="Kafka", importance="required", evidence="熟悉 Kafka"),
            Requirement(skill="Docker", importance="preferred", evidence="Docker 加分"),
        ),
        weight_level="campus",
        dimension_weights={
            "tech_depth": 0.30,
            "engineering": 0.25,
            "business": 0.10,
            "impact": 0.10,
            "collaboration": 0.10,
            "growth": 0.15,
        },
    ),
)

PART2_RESULT_KEYS = ["resume", "issues", "match", "recommendations", "meta"]
PART2_META_KEYS = [
    "traceId", "llmUsed", "degraded", "elapsedMs",
    "source", "truncated", "recommendationCount",
]
PART3_BLOCK_KEYS = ["verdicts", "improvements", "growthDirections", "abilityProfile"]
PART3_META_KEYS = ["analysisDepth", "verdictCount", "directionCount"]


# ---------------------------------------------------------------- 一个真的会返回坏 JSON 的 LLM 服务


class _BadJsonHandler(BaseHTTPRequestHandler):
    """返回 200 + 合法 SSE 帧，但 `delta.content` 拼起来**不是 JSON**。

    这正是「内容失败」那一层：传输成功、HTTP 200、SSE 帧也对，
    只有累积出来的文本没法解析。用真 HTTP 而不是替身，是为了让
    `OpenAiCompatibleClient` 的三层降级**真的被执行**，而不是被跳过。
    """

    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:  # noqa: N802 —— http.server 的约定名
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)  # 必须读完，否则 keep-alive 会错位
        payloads = [
            'data: {"choices":[{"delta":{"content":"这不是 JSON"}}]}\n\n',
            'data: {"choices":[{"delta":{"content":"，完全没有结构"}}]}\n\n',
            "data: [DONE]\n\n",
        ]
        body = "".join(payloads).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:  # 别把演练日志刷满
        return


def start_bad_json_server() -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _BadJsonHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[0], server.server_address[1]
    return server, f"http://{host}:{port}"


def closed_port_url() -> str:
    """拿一个「确定没人听」的端口：开一个 socket 再关掉，端口随即空出来。"""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return f"http://127.0.0.1:{port}"


# ---------------------------------------------------------------- 演练骨架


@dataclass
class Check:
    ok: bool
    label: str
    detail: str = ""


class Drill:
    def __init__(self, title: str) -> None:
        self.title = title
        self.checks: list[Check] = []

    def expect(self, ok: bool, label: str, detail: str = "") -> None:
        self.checks.append(Check(ok=bool(ok), label=label, detail=detail))

    def report(self) -> bool:
        passed = sum(1 for c in self.checks if c.ok)
        total = len(self.checks)
        status = "\033[32mPASS\033[0m" if passed == total else "\033[31mFAIL\033[0m"
        print(f"\n=== {self.title} === {status} ({passed}/{total})")
        for check in self.checks:
            mark = "\033[32m✓\033[0m" if check.ok else "\033[31m✗\033[0m"
            suffix = f"  {check.detail}" if check.detail else ""
            print(f"  {mark} {check.label}{suffix}")
        return passed == total


#: 与 `stream_analysis` 的 `_RUBRIC_UNSET` 同一个语义：「不传」≠「传 None」。
#: 演练 1/2/4 要的是「用仓库里那份 rubric」，只有演练 3a 才显式制造「没有 rubric」。
_RUBRIC_UNSET: object = object()


async def run_stream(
    llm: LlmClient, *, depth: str = "deep", rubric: object = _RUBRIC_UNSET
) -> list[tuple[str, dict]]:
    request = StreamRequest(
        resume_text=RESUME,
        job_id="job-deep",
        job_candidates=CANDIDATES,
        trace_id="drill",
        analysis_depth=depth,
    )
    extra = {} if rubric is _RUBRIC_UNSET else {"rubric": rubric}
    frames = [
        frame
        async for frame in stream_analysis(
            request, dictionary=get_dictionary(), llm=llm, **extra
        )
    ]
    return parse_frames("".join(frames))


def result_of(events: list[tuple[str, dict]]) -> dict:
    return next(data for event_type, data in events if event_type == SseEventType.RESULT.value)


def reviewed_stage(events: list[tuple[str, dict]]) -> dict:
    stages = [
        data
        for event_type, data in events
        if event_type == SseEventType.STAGE.value and data["stage"] == StageName.REVIEWED.value
    ]
    return stages[-1]


def assert_deep_degraded(drill: Drill, events: list[tuple[str, dict]], *, label: str) -> None:
    """四条里前两条共用的断言集：**结果照常 + 四块退化为规则兜底（非空）**。"""
    types = [event_type for event_type, _ in events]
    drill.expect(types[-1] == SseEventType.DONE.value, f"{label}：末帧是 done")
    drill.expect(
        SseEventType.RESULT.value in types, f"{label}：result 照常发出（降级不终止流）"
    )
    drill.expect(SseEventType.ERROR.value not in types, f"{label}：不发 error（reviewed 失败非致命）")

    result = result_of(events)
    drill.expect(result["meta"]["degraded"] is True, f"{label}：meta.degraded=true")
    drill.expect(reviewed_stage(events)["status"] == StageStatus.FAIL.value,
                 f"{label}：reviewed 阶段留 fail 记录（不是静默 ok）")

    # ★ 降级 ≠ 空数组：ADR-206 / AC29 的「退化为集合级事实」
    expected = len(result["match"]["matched"]) + len(result["match"]["missing"])
    drill.expect(
        len(result["verdicts"]) == expected,
        f"{label}：verdicts 条数 = match 条数",
        f"{len(result['verdicts'])} / {expected}",
    )
    drill.expect(all(item["reason"].strip() for item in result["verdicts"]),
                 f"{label}：每条判定都有 reason")
    drill.expect(bool(result["improvements"]), f"{label}：improvements 非空（规则模板）")
    drill.expect(bool(result["growthDirections"]), f"{label}：growthDirections 非空（规则模板）")

    profile = result["abilityProfile"]
    drill.expect(profile is not None and len(profile["dimensions"]) == 6,
                 f"{label}：六维齐全（其中两维纯代码可算）")
    with_score = [d for d in profile["dimensions"] if d["score"]]
    drill.expect(
        all(d["evidence"].strip() for d in with_score),
        f"{label}：凡有分的维度都带原文证据（AC27）",
    )


# ---------------------------------------------------------------- 四条演练


def drill_1_llm_unreachable() -> bool:
    drill = Drill("演练 1 · LLM 连不上")
    client = OpenAiCompatibleClient(
        base_url=closed_port_url(), api_key="k", model="m", timeout_seconds=2.0
    )
    events = asyncio.run(run_stream(client))
    assert_deep_degraded(drill, events, label="断 LLM")
    drill.expect(result_of(events)["meta"]["llmUsed"] is False, "断 LLM：meta.llmUsed=false")
    return drill.report()


def drill_2_llm_bad_json() -> bool:
    drill = Drill("演练 2 · LLM 返回非法 JSON")
    server, base_url = start_bad_json_server()
    try:
        client = OpenAiCompatibleClient(
            base_url=base_url, api_key="k", model="m", timeout_seconds=5.0
        )
        events = asyncio.run(run_stream(client))
    finally:
        server.shutdown()
        server.server_close()

    assert_deep_degraded(drill, events, label="非法 JSON")

    # 顺带把「解析器确实把垃圾判成不可用」单独钉一下 —— 否则「降级了」可能只是因为连接就失败了
    from app.llm.parsers import parse_advice, parse_review


    drill.expect(parse_review("不是 JSON", allowed_levels={}) is None, "解析器：垃圾输入 → None")
    drill.expect(parse_advice("不是 JSON", max_directions=5) is None, "文案解析器：垃圾输入 → None")
    return drill.report()


def drill_3_dimension_uncomputable() -> bool:
    drill = Drill("演练 3 · rubric 缺失 / 某维算不出")

    # ---- 3a：rubric 整个读不到 → abilityProfile = null，但主流程照常（plan §6.2）
    events = asyncio.run(run_stream(NullLlmClient(), rubric=None))
    types = [event_type for event_type, _ in events]
    result = result_of(events)
    drill.expect(types[-1] == SseEventType.DONE.value, "rubric 缺失：末帧是 done")
    drill.expect(result["abilityProfile"] is None, "rubric 缺失：abilityProfile = null（不阻塞主流程）")
    drill.expect(result["match"] is not None, "rubric 缺失：match 照常（part2 的价值不受影响）")

    # ---- 3b：某维档位算不出 → 该维 score=null、overall 按已有维度归一，**不编分**
    from app.service.profile.ability_profile import build_profile
    from app.service.profile.advisor_rules import DimensionGrade
    from app.service.profile.rubric import load_rubric

    rubric = load_rubric()
    profile = build_profile(
        [
            DimensionGrade(key="tech_depth", level_key="L2", evidence="有实现", reason="r"),
            DimensionGrade(key="engineering", level_key="NOT_A_LEVEL", evidence="x", reason="r"),
        ],
        rubric,
        job_level="社招",
    )
    by_key = {item.key: item for item in profile.dimensions}
    drill.expect(by_key["engineering"].score is None, "非法档位：该维 score = null")
    drill.expect(by_key["engineering"].evidence == "", "非法档位：该维 evidence = 空串（不留半截证据）")
    drill.expect(profile.overall == by_key["tech_depth"].score,
                 "缺维归一：overall 只按**已有维度**算（不是把缺失维当 0）",
                 f"overall={profile.overall}")
    return drill.report()


def drill_4_standard_fallback() -> bool:
    drill = Drill("演练 4 · standard（缺省）回到 part2 形状")
    events = asyncio.run(run_stream(NullLlmClient(), depth="standard"))
    types = [event_type for event_type, _ in events]
    stages = [data["stage"] for event_type, data in events
              if event_type == SseEventType.STAGE.value]

    result = result_of(events)
    drill.expect(types[0] == SseEventType.META.value, "standard：meta 首帧")
    drill.expect(types[-1] == SseEventType.DONE.value, "standard：done 尾帧")
    drill.expect(StageName.REVIEWED.value not in stages, "standard：**不发** reviewed 阶段")
    drill.expect(len(stages) == 14, "standard：7 个 stage × (start+ok)", f"{len(stages)} 帧")

    drill.expect(list(result.keys()) == PART2_RESULT_KEYS,
                 "standard：顶层键与 part2 **逐字同序**",
                 str(list(result.keys())))
    drill.expect(list(result["meta"].keys()) == PART2_META_KEYS,
                 "standard：meta 键与 part2 **逐字同序**",
                 str(list(result["meta"].keys())))
    leaked = [key for key in PART3_BLOCK_KEYS + PART3_META_KEYS
              if key in result or key in result["meta"]]
    drill.expect(not leaked, "standard：一个 part3 的键都不出现", str(leaked))
    return drill.report()


DRILLS = {
    "1": ("LLM 连不上", drill_1_llm_unreachable),
    "2": ("LLM 返回非法 JSON", drill_2_llm_bad_json),
    "3": ("rubric 缺失 / 某维算不出", drill_3_dimension_uncomputable),
    "4": ("standard 回到 part2 形状", drill_4_standard_fallback),
}


def main(argv: list[str]) -> int:
    selected = argv[1:] or list(DRILLS)
    unknown = [item for item in selected if item not in DRILLS]
    if unknown:
        print(f"未知的演练编号：{unknown}；可选 {list(DRILLS)}", file=sys.stderr)
        return 2

    print("part3 降级演练（四条 · tasks.md N6.1 / AC29）")
    print("打桩在进程内 —— 不需要任何服务在跑。")

    results = []
    for key in selected:
        title, fn = DRILLS[key]
        print(f"\n--- 演练 {key} · {title} ---")
        results.append(fn())

    total = len(results)
    passed = sum(1 for item in results if item)
    print(f"\n================ 合计 {passed}/{total} 条通过 ================")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
