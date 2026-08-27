#!/usr/bin/env python
"""
回放一个 trajectory.jsonl 用于调试。

用法：
    python scripts/replay_trajectory.py runs/run_xxx/trajectory.jsonl

输出：
    每一步的事件摘要，包括 step、tool、result 摘要。
"""
import json
import sys
from pathlib import Path


def replay(jsonl_path: Path) -> None:
    events = []
    with jsonl_path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))

    print(f"=== Trajectory replay: {jsonl_path} ===")
    print(f"Total events: {len(events)}")
    print()

    for event in events:
        step = event.get("step", "?")
        etype = event.get("type", "?")
        tool = event.get("tool", "")
        duration = event.get("duration", 0)
        tokens = event.get("tokens", 0)

        if etype == "tool_call":
            args_summary = json.dumps(event.get("args", {}), ensure_ascii=False)[:80]
            print(f"[Step {step}] TOOL_CALL {tool}({args_summary}) [{duration}s, {tokens}tok]")
        elif etype == "observation":
            content = event.get("result", "")
            if isinstance(content, str):
                summary = content[:80].replace("\n", " ")
            else:
                summary = str(content)[:80]
            print(f"  └─ OBSERVATION: {summary}{'...' if len(content) > 80 else ''}")
        elif etype == "model_call":
            print(f"[Step {step}] MODEL_CALL [{duration}s, {tokens}tok]")
        elif etype == "finish":
            summary = event.get("summary", "")
            validation = event.get("validation", "")
            print(f"[Step {step}] FINISH: {summary}")
            if validation:
                print(f"  └─ VALIDATION: {validation}")
        elif etype == "error":
            print(f"[Step {step}] ERROR: {event.get('error', '?')}")
        elif etype == "stop":
            print(f"[Step {step}] STOP: {event.get('reason', '?')}")
        else:
            print(f"[Step {step}] {etype}: {event.get('description', '')}")

    print()
    print("=== Summary ===")
    stop_events = [e for e in events if e.get("type") == "stop"]
    if stop_events:
        print(f"Stop reason: {stop_events[-1].get('reason')}")
    finish_events = [e for e in events if e.get("type") == "finish"]
    if finish_events:
        print(f"Finish summary: {finish_events[-1].get('summary')}")
    error_events = [e for e in events if e.get("type") == "error"]
    print(f"Errors: {len(error_events)}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/replay_trajectory.py <trajectory.jsonl>")
        sys.exit(1)
    replay(Path(sys.argv[1]))