"""agent/ 能脱离界面单独跑，说明循环没和 UI 缠在一起。

    python cli.py "修复 workspace 里 mean 对空列表的处理"           # 有 Key 走 DeepSeek
    python cli.py --offline "修复 mean 对空列表的处理"              # 断网走离线 mock
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from agent.config import get_api_key, load_config              # noqa: E402
from agent.loop import AgentLoop                                # noqa: E402
from agent.providers import DeepSeekProvider, MockProvider      # noqa: E402
from agent.tools import BUILTIN_TOOLS                           # noqa: E402
from mcp.client import load_mcp_tools                           # noqa: E402

GREEN, RED, DIM, RESET = "\033[92m", "\033[91m", "\033[2m", "\033[0m"


def main() -> None:
    parser = argparse.ArgumentParser(description="桌面智能体的无界面入口")
    parser.add_argument("task", help="给智能体的任务")
    parser.add_argument("--workspace", default=str(Path(__file__).parent / "workspace"))
    parser.add_argument("--offline", action="store_true", help="强制离线 mock，不调模型")
    parser.add_argument("--steps", type=int, default=12)
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    tools = dict(BUILTIN_TOOLS)
    mcp, status = load_mcp_tools(Path(__file__).parent / "mcp.json", workspace)
    tools.update(mcp)
    for s in status:
        print(f"{DIM}[MCP] {s['server']}: {'ok' if s['ok'] else '不可用'} {s['tools']}{RESET}")

    if args.offline or not get_api_key():
        provider = MockProvider()
        print(f"{DIM}[provider] 离线 mock（未配置 Key）{RESET}")
    else:
        cfg = load_config()
        provider = DeepSeekProvider(get_api_key(), cfg["base_url"], cfg["model"])
        print(f"{DIM}[provider] {cfg['model']} @ {cfg['base_url']}{RESET}")

    loop = AgentLoop(provider, tools, workspace, max_steps=args.steps)
    names = ", ".join(s.name for s in loop.skills) or "（已关闭）"
    print(f"{DIM}[skills] {len(loop.skills)} 个：{names}{RESET}")
    print(f"{DIM}[hooks] {'on' if loop.hooks else 'off'}"
          f"  [reviewer] {'on' if loop.reviewer else 'off'}"
          f"  [agents.md] {'/'.join(loop.agents_md['layers']) or '无'}{RESET}")

    tool_calls = 0
    for ev in loop.run(args.task):
        if ev.type == "assistant_text":
            print(ev.data["delta"], end="", flush=True)
        elif ev.type == "tool_end":
            tool_calls += 1
            color = GREEN if ev.data["ok"] else RED
            print(f"\n{color}[{ev.data['tool']}] {'ok' if ev.data['ok'] else '失败'}"
                  f" ({ev.data['elapsed_ms']}ms){RESET}")
            print(ev.data["output"][:600])
        elif ev.type == "turn_usage":
            print(f"{DIM}[tokens] +{ev.data['prompt_tokens']}/{ev.data['completion_tokens']}{RESET}")
        elif ev.type == "final":
            print(f"\n=== 完成 ===\n{ev.data['text']}")
            print(f"{DIM}[总计] 工具调用 {tool_calls} 次{RESET}")
        elif ev.type == "stopped":
            print(f"\n=== 停止 === {ev.data['reason']}")
            print(f"{DIM}[总计] 工具调用 {tool_calls} 次{RESET}")
        elif ev.type == "error":
            print(f"\n{RED}=== 出错 === {ev.data['message']}{RESET}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
