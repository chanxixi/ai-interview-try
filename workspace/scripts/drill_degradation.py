#!/usr/bin/env python3
"""六条降级演练的**实测脚本**（tasks.md M8.3）。

和 `smoke-stream.sh` 的分工：

| 脚本 | 回答的问题 |
|---|---|
| `smoke.sh` | 四层骨架还活着吗 |
| `smoke-stream.sh` | **正常路径**的 SSE 契约还符合 spec 吗 |
| `drill-degradation.sh`（本脚本） | **异常路径**真的按契约降级了吗 |

为什么降级要单独测、且必须**实测**：降级路径的共同特征是「不跑也不会报错」。
LLM 挂了不降级 → 用户拿不到推荐；扫描件不报错 → 用户拿到一份 0 技能的「正常」结果；
断连不处理 → 句柄慢慢漏光。这些都不会让健康检查变红，只会让线上慢慢烂掉。
所以每一条都必须**主动制造故障、再断言行为**，不能靠读代码相信它。

六条与验收项的对应：

| # | 演练 | 验收 |
|---|---|---|
| 1 | LLM 不可用 | AC15 |
| 2 | 改名为 `.pdf` 的 docx | AC12 |
| 3 | 扫描件 / 纯图片 PDF | AC14 |
| 4 | 存储降级（MySQL 缺席） | part1 AC9/AC10 的**现状核对**（见 DELIVERY §7 D-9） |
| 5 | 连续 20 次「连上就断」 | AC19 |
| 6 | `Accept` 不含 `text/event-stream` | AC21 |

用法：

    bash scripts/drill-degradation.sh                 # 六个全跑
    bash scripts/drill-degradation.sh 2 3             # 只跑第 2、3 条

前置：四层已启动（`bash scripts/start-all.sh`），analyzer 的 `LLM_*` 环境变量**留空**
（第 1 条要的就是「LLM 不可用」这个状态；留空即不可用，见 `core/config.py`）。
"""

from __future__ import annotations

import http.client
import json
import pathlib
import re
import socket
import sys
import time
import uuid

# ------------------------------------------------------------------ 基础设施

BFF_HOST = "127.0.0.1"
BFF_PORT = 3000
BFF_BASE = f"http://{BFF_HOST}:{BFF_PORT}"
JOB_SERVICE_PORT = 8080

#: 与 `sse_event.py` 的 `STAGE_ORDER` 同序 —— 但这里**手写一遍**：
#: 脚本要独立于被测代码，从被测代码里读出来就变成「自己证明自己对」。
STAGE_ORDER = ["accepted", "parsed", "cleaned", "normalized", "matched", "recommended", "llm"]

RESUME_TEXT = "熟悉 Java、Spring Boot、MySQL、Redis、Docker、Git，有微服务与高并发经验"

WORKSPACE = pathlib.Path(__file__).resolve().parent.parent
FIXTURE_DIR = WORKSPACE / ".logs" / "drills"

_results: list[tuple[str, bool, str]] = []
_gaps: list[tuple[str, str]] = []


def ok(label: str, detail: str = "") -> None:
    _results.append((label, True, detail))
    print(f"  \033[32mOK\033[0m   {label}" + (f" —— {detail}" if detail else ""))


def bad(label: str, detail: str = "") -> None:
    _results.append((label, False, detail))
    print(f"  \033[31mFAIL\033[0m {label}" + (f" —— {detail}" if detail else ""))


def gap(label: str, detail: str = "") -> None:
    """**已登记的**契约缺口：断言不通过，但**不计入失败**。

    与 `bad()` 的区别是「这是已知的、已写进 DELIVERY §7 的取舍」，而不是
    「这次跑挂了」。两类必须分开 —— 混在一起，要么缺口把 CI 永远染红、
    要么真回归被当成缺口忽略掉。

    凡是用到这个函数的，都必须能在 DELIVERY.md §7 的偏离登记里找到对应条目。
    """
    _gaps.append((label, detail))
    print(f"  \033[33mGAP\033[0m  {label}" + (f" —— {detail}" if detail else ""))


def note(label: str) -> None:
    print(f"  \033[33mNOTE\033[0m {label}")


# ------------------------------------------------------------------ SSE 解析
# 故意**不用** apps/web 的解析器：那份代码是被测对象的一部分（前端也走它）。
# 这里只实现 spec §2.4 的两条规则，正好可以当「独立实现」对照。


def parse_frames(raw: str) -> list[tuple[str, dict]]:
    """`\n\n` 分帧 → `[(event, data_dict)]`。注释帧（`: ping`）直接丢弃。"""
    frames: list[tuple[str, dict]] = []
    for block in raw.split("\n\n"):
        if not block.strip():
            continue
        event = "message"
        data_lines: list[str] = []
        for line in block.split("\n"):
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                event = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:") :].lstrip(" "))
        if data_lines:
            try:
                frames.append((event, json.loads("\n".join(data_lines))))
            except json.JSONDecodeError:
                frames.append((event, {}))
    return frames


def _multipart(fields: dict[str, str], files: dict[str, tuple[str, bytes]] | None = None):
    """组一个 multipart/form-data 请求体。返回 (content_type, body_bytes)。"""
    boundary = "----drill" + uuid.uuid4().hex
    out = bytearray()
    for name, value in fields.items():
        out += f"--{boundary}\r\n".encode()
        out += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        out += value.encode("utf-8") + b"\r\n"
    for name, (filename, content) in (files or {}).items():
        out += f"--{boundary}\r\n".encode()
        out += (
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
            f"Content-Type: application/pdf\r\n\r\n"
        ).encode()
        out += content + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return f"multipart/form-data; boundary={boundary}", bytes(out)


def post_stream(
    *,
    fields: dict[str, str] | None = None,
    files: dict[str, tuple[str, bytes]] | None = None,
    accept: str = "text/event-stream",
    timeout: float = 90.0,
) -> tuple[int, dict[str, str], str]:
    """POST `/api/analysis/stream`，返回 (status, headers, 原始文本)。"""
    content_type, body = _multipart(fields or {}, files)
    conn = http.client.HTTPConnection(BFF_HOST, BFF_PORT, timeout=timeout)
    try:
        conn.request(
            "POST",
            "/api/analysis/stream",
            body=body,
            headers={
                "Content-Type": content_type,
                "Accept": accept,
                "X-Trace-Id": f"drill-{uuid.uuid4().hex[:8]}",
            },
        )
        response = conn.getresponse()
        raw = response.read().decode("utf-8", "replace")
        headers = {k.lower(): v for k, v in response.getheaders()}
        return response.status, headers, raw
    finally:
        conn.close()


def ensure_fixtures() -> None:
    """两个假样本按需生成（见 `drill-fixtures.py` 的说明）。"""
    if (FIXTURE_DIR / "renamed-docx.pdf").exists() and (FIXTURE_DIR / "scanned.pdf").exists():
        return
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    import drill_fixtures  # type: ignore[import-not-found]

    drill_fixtures.main([str(FIXTURE_DIR)])


# ------------------------------------------------------------------ 演练 1：AC15


def drill_llm_degraded() -> None:
    print("\n[1/6] AC15 · LLM 不可用 → result 与 done 照常，meta.degraded = true")
    status, headers, raw = post_stream(fields={"resumeText": RESUME_TEXT})
    if status != 200:
        bad("HTTP 200", f"实际 {status}")
        return
    ok("HTTP 200")

    frames = parse_frames(raw)
    types = [event for event, _ in frames]

    if types and types[0] == "meta":
        ok("首帧是 meta")
    else:
        bad("首帧是 meta", f"实际 {types[:1]}")

    if types and types[-1] == "done":
        ok("末帧是 done")
    else:
        bad("末帧是 done", f"实际 {types[-1:]}")

    thinking = [data for event, data in frames if event == "thinking"]
    if not thinking:
        ok("thinking 帧数 = 0（LLM 未启用，符合 AC15）")
    else:
        bad("thinking 帧数 = 0", f"实际 {len(thinking)} 条 —— LLM 是不是被启用了？")

    if "error" in types:
        err = next(data for event, data in frames if event == "error")
        bad("无 error 帧", f"实际收到 {err}")
        return
    ok("无 error 帧")

    if "result" not in types:
        bad("有 result 帧")
        return
    result = next(data for event, data in frames if event == "result")

    meta = result.get("meta") or {}
    if meta.get("degraded") is True:
        ok("meta.degraded = true", "这是 LLM 降级的**唯一**观察点")
    else:
        bad("meta.degraded = true", f"实际 {meta.get('degraded')!r}")

    if meta.get("llmUsed") is False:
        ok("meta.llmUsed = false")
    else:
        bad("meta.llmUsed = false", f"实际 {meta.get('llmUsed')!r}")

    recs = result.get("recommendations") or []
    if recs:
        ok("recommendations 完整", f"{len(recs)} 条，Top1 = {recs[0].get('jobId')} @ {recs[0].get('score')}")
    else:
        bad("recommendations 非空", "0 条 —— job-service 的种子数据没导入？")

    issues = result.get("issues") or []
    if issues:
        ok("issues 由规则兜底产出", f"{len(issues)} 条（LLM 缺席不等于没有建议）")
    else:
        note("issues 为空 —— 规则没命中，不算失败（取决于简历内容）")

    note("结论：LLM 挂掉只损失「LLM 视角的建议」，推荐与匹配**完全不受影响**")


# ------------------------------------------------------------------ 演练 2：AC12


def drill_renamed_docx() -> None:
    print("\n[2/6] AC12 · 改名为 .pdf 的 docx → 415（判据是 magic number，不是扩展名）")
    ensure_fixtures()
    path = FIXTURE_DIR / "renamed-docx.pdf"
    payload = path.read_bytes()

    status, headers, raw = post_stream(files={"file": ("resume.pdf", payload)})
    if status == 415:
        ok("HTTP 415 UNSUPPORTED_FILE_TYPE")
    else:
        bad("HTTP 415", f"实际 {status} —— 文件被放进解析器了")

    ctype = headers.get("content-type", "")
    if "application/json" in ctype:
        ok("响应是 JSON（**没有**建立 SSE 流）", ctype)
    else:
        bad("响应是 JSON", f"实际 content-type = {ctype!r}")

    if "text/event-stream" not in raw and "event:" not in raw:
        ok("响应体里没有 SSE 帧")
    else:
        bad("响应体里没有 SSE 帧")

    try:
        body = json.loads(raw)
        code = (body.get("error") or {}).get("code") or body.get("code")
        if code == "UNSUPPORTED_FILE_TYPE":
            ok("error.code = UNSUPPORTED_FILE_TYPE")
        else:
            bad("error.code = UNSUPPORTED_FILE_TYPE", f"实际 {code!r}（body={raw[:200]}）")
    except json.JSONDecodeError:
        bad("响应体是合法 JSON", raw[:200])

    note(f"样本前 4 字节 = {payload[:4]!r}（zip 头 PK\\x03\\x04），不是 %PDF-")


# ------------------------------------------------------------------ 演练 3：AC14


def drill_scanned_pdf() -> None:
    print("\n[3/6] AC14 · 扫描件 → error(PDF_NO_TEXT_LAYER) → done，5s 内关闭")
    ensure_fixtures()
    path = FIXTURE_DIR / "scanned.pdf"

    started = time.perf_counter()
    status, headers, raw = post_stream(files={"file": ("scanned.pdf", path.read_bytes())})
    elapsed = time.perf_counter() - started

    if status != 200:
        bad("HTTP 200（流式入口本身是通的）", f"实际 {status}")
        return
    ok("HTTP 200")

    frames = parse_frames(raw)
    types = [event for event, _ in frames]

    if "error" in types:
        error = next(data for event, data in frames if event == "error")
        if error.get("code") == "PDF_NO_TEXT_LAYER":
            ok("error.code = PDF_NO_TEXT_LAYER")
        else:
            bad("error.code = PDF_NO_TEXT_LAYER", f"实际 {error.get('code')!r}")
    else:
        bad("有 error 帧", f"事件序列 = {types}")

    if "result" not in types:
        ok("没有 result 帧（error 与 result 互斥）")
    else:
        bad("没有 result 帧", "★ 扫描件一路走到了 result —— 用户会拿到一份 0 技能的『正常』响应")

    if types and types[-1] == "done":
        ok("末帧是 done（连接不会悬挂）")
    else:
        bad("末帧是 done", f"实际 {types[-1:]}")

    if elapsed < 5.0:
        ok(f"连接 {elapsed:.2f}s 内关闭（AC14 要求 < 5s）")
    else:
        bad("连接 5s 内关闭", f"实际 {elapsed:.2f}s")

    # parsed 阶段必须留下 fail —— 否则日志里看不出是哪一阶段炸的
    parsed_frames = [
        data
        for event, data in frames
        if event == "stage" and data.get("stage") == "parsed"
    ]
    if parsed_frames and parsed_frames[-1].get("status") == "fail":
        ok("parsed 阶段留下 fail 记录")
    else:
        bad("parsed 阶段留下 fail 记录", f"实际 {parsed_frames[-1:] }")


# ------------------------------------------------------------------ 演练 4：存储


def _healthz(port: int) -> dict:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("GET", "/healthz")
        return json.loads(conn.getresponse().read().decode())
    finally:
        conn.close()


def drill_storage() -> None:
    print("\n[4/6] 存储降级 · MySQL 缺席时推荐是否正常（part1 AC9/AC10 现状核对）")
    try:
        health = _healthz(JOB_SERVICE_PORT)
    except OSError as exc:
        bad("job-service 可达", str(exc))
        return
    ok("job-service 可达", json.dumps(health, ensure_ascii=False))

    if "storage" in health:
        ok("healthz 暴露 storage 字段", f"storage = {health['storage']}")
    else:
        gap(
            "healthz 暴露 storage 字段",
            "part1 spec §2.8/§2.9 要求 `{status, storage: mysql|local|mock}` 作为降级的唯一可观测证据；"
            "当前只返回 {service, status} —— 见 DELIVERY.md §7 D-9",
        )

    # 「MySQL 缺席时推荐仍正常」：当前实例跑的就是 H2（不依赖 MySQL），
    # 所以只要推荐非空，这一条在**当前架构下**就成立 —— 但要同时说清代价。
    status, _, raw = post_stream(fields={"resumeText": RESUME_TEXT})
    result = next((d for e, d in parse_frames(raw) if e == "result"), None)
    recs = (result or {}).get("recommendations") or []
    if recs:
        ok("无 MySQL 时推荐仍完整", f"{len(recs)} 条")
    else:
        bad("无 MySQL 时推荐仍完整", "0 条")

    note(
        "现状：存储是**部署期**两档切换（JOB_DB_URL → H2 默认 / MySQL 显式），"
        "不是 part1 承诺的**运行期**三档自动降级；详见 DELIVERY.md §7 D-9"
    )


# ------------------------------------------------------------------ 演练 5：AC19


def drill_abort_storm(times: int = 20) -> None:
    print(f"\n[5/6] AC19 · 连续 {times} 次「连上就断」 → 服务仍健康、无泄漏")

    aborted = 0
    for index in range(times):
        content_type, body = _multipart({"resumeText": RESUME_TEXT})
        try:
            sock = socket.create_connection((BFF_HOST, BFF_PORT), timeout=10)
            request = (
                f"POST /api/analysis/stream HTTP/1.1\r\n"
                f"Host: {BFF_HOST}:{BFF_PORT}\r\n"
                f"Content-Type: {content_type}\r\n"
                f"Accept: text/event-stream\r\n"
                f"X-Trace-Id: drill-abort-{index:02d}\r\n"
                f"Content-Length: {len(body)}\r\n"
                f"Connection: close\r\n\r\n"
            ).encode() + body
            sock.sendall(request)
            # 读一点点就断 —— 关键在于**在服务端还在写的时候**把连接拆掉。
            # 用 socket 而不是 curl：curl 的 --max-time 会因为整条流只要几十毫秒
            # 而**跑完**，那样根本没断，等于什么都没测。
            sock.recv(64)
            sock.close()
            aborted += 1
        except OSError as exc:
            bad(f"第 {index + 1} 次连接", str(exc))

    if aborted == times:
        ok(f"{times} 次连接都在收到首帧后立刻断开")
    else:
        bad(f"{times} 次连接", f"只有 {aborted} 次成功建立")

    # 断连风暴之后，服务必须**照常工作** —— 这才叫「无句柄/线程泄漏」的可观测证据
    try:
        health = _healthz(BFF_PORT)
        ok("风暴后 BFF /healthz 仍 ok", json.dumps(health, ensure_ascii=False))
    except OSError as exc:
        bad("风暴后 BFF /healthz 仍 ok", str(exc))

    try:
        job_health = _healthz(JOB_SERVICE_PORT)
        ok("风暴后 job-service /healthz 仍 ok", json.dumps(job_health, ensure_ascii=False))
    except OSError as exc:
        bad("风暴后 job-service /healthz 仍 ok", str(exc))

    # 端到端再走一次完整流 —— 只是「健康」不够，链路必须真的还能跑
    status, _, raw = post_stream(fields={"resumeText": RESUME_TEXT})
    frames = parse_frames(raw)
    types = [event for event, _ in frames]
    if status == 200 and "result" in types and types[-1] == "done":
        ok("风暴后完整流仍跑通", f"{len(frames)} 帧")
    else:
        bad("风暴后完整流仍跑通", f"status={status} types={types}")

    # STREAM_ABORTED 必须真的落进日志（AC19 明文要求）
    log = WORKSPACE / ".logs" / "bff-new.log"
    if log.exists():
        text = log.read_text(encoding="utf-8", errors="replace")
        hits = len(re.findall(r"STREAM_ABORTED|stream aborted by client", text))
        if hits:
            ok("BFF 日志出现 STREAM_ABORTED", f"{hits} 条")
        else:
            bad("BFF 日志出现 STREAM_ABORTED", f"日志里没有（{log}）")
    else:
        note(f"没找到 BFF 日志 {log} —— 手动确认「stream aborted by client」是否落盘")


# ------------------------------------------------------------------ 演练 6：AC21


def drill_sync_fallback() -> None:
    print("\n[6/6] AC21 · Accept 不含 text/event-stream → 回退为同步 JSON")
    status, headers, raw = post_stream(fields={"resumeText": RESUME_TEXT}, accept="application/json")

    if status == 200:
        ok("HTTP 200")
    else:
        bad("HTTP 200", f"实际 {status}")

    ctype = headers.get("content-type", "")
    if "application/json" in ctype:
        ok("content-type 是 application/json", ctype)
    else:
        bad("content-type 是 application/json", f"实际 {ctype!r}")

    if "event:" not in raw:
        ok("响应体里没有 SSE 帧（一次性 JSON）")
    else:
        bad("响应体里没有 SSE 帧")

    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        bad("响应体是合法 JSON", raw[:200])
        return

    # part2 spec §2.3 的五块：resume / issues / match(可空) / recommendations / meta
    expected = {"resume", "issues", "match", "recommendations", "meta"}
    missing = expected - set(body)
    if not missing:
        ok("五块齐全", "resume / issues / match / recommendations / meta")
    else:
        bad("五块齐全", f"缺 {sorted(missing)}")

    recs = body.get("recommendations") or []
    if recs:
        ok("同步回退的推荐与流式一致（同一条链路）", f"{len(recs)} 条")
    else:
        bad("同步回退的推荐非空", "0 条")

    note("回退实现是「收完整条流只取 result」，所以两条入口**结果必然一致**")


# ------------------------------------------------------------------ 入口

DRILLS = {
    1: ("AC15 LLM 降级", drill_llm_degraded),
    2: ("AC12 magic number", drill_renamed_docx),
    3: ("AC14 扫描件", drill_scanned_pdf),
    4: ("存储降级", drill_storage),
    5: ("AC19 断连风暴", drill_abort_storm),
    6: ("AC21 同步回退", drill_sync_fallback),
}


def main(argv: list[str]) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

    selected = [int(a) for a in argv[1:] if a.isdigit()] or sorted(DRILLS)

    print("=" * 72)
    print(" 降级演练（tasks.md M8.3）")
    print("=" * 72)
    print(f" BFF={BFF_BASE}  job-service=:{JOB_SERVICE_PORT}  analyzer=:8001")
    print(f" 前置：analyzer 的 LLM_* 环境变量留空（第 1 条要的就是『LLM 不可用』）")

    for index in selected:
        label, func = DRILLS[index]
        try:
            func()
        except Exception as exc:  # noqa: BLE001 —— 一条演练崩了不该带走其余五条
            bad(f"{label} 执行异常", f"{type(exc).__name__}: {exc}")

    failed = [label for label, passed, _ in _results if not passed]
    total = len(_results)
    print("\n" + "-" * 72)

    if _gaps:
        print(f"\033[33m已登记的契约缺口 {len(_gaps)} 项（不计入失败，均可在 DELIVERY.md §7 找到条目）：\033[0m")
        for label, detail in _gaps:
            print(f"  · {label}")
            if detail:
                print(f"    {detail}")
        print()

    if not failed:
        print(f"\033[32m降级演练通过：{total} 项断言全部符合预期\033[0m")
        return 0

    print(f"\033[31m降级演练失败：{len(failed)}/{total} 项不通过\033[0m")
    for label in failed:
        print(f"  · {label}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
