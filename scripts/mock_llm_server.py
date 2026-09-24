#!/usr/bin/env python3
"""最小 OpenAI 兼容假服务器，用于在本地端到端验证 swegemma 管线。

不调用任何真实模型：按调用次数回放一个固定的工具调用剧本，让 harness 完整走完
"编译提交 → 容器/子进程沙箱 → 工具调用 → 抽取 patch" 的流程。

用法:
    python3 scripts/mock_llm_server.py --port 8111 [--script create|existing]
"""
from __future__ import annotations

import argparse
import json
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STATE = {"n": 0}


def _tool_call(name: str, args: dict) -> dict:
    return {
        "id": f"call_{uuid.uuid4().hex[:12]}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


def script_for(mode: str) -> list[dict]:
    """返回一串 assistant 消息；最后一条是纯文本以终止会话。"""
    if mode == "existing":
        # 修改一个已存在的文件：swegemma 的 README 由 harness 写进 /workspace
        return [
            {"tool": ("run_command", {"command": "ls -a /workspace"})},
            {"tool": ("read_file", {"filepath": "pytest.ini"})},
            {"tool": ("run_command", {"command": "printf '\\n# mock-edit\\n' >> /workspace/pytest.ini"})},
            {"tool": ("submit_patch", {})},
            {"text": "Mock run finished: appended a comment to pytest.ini and submitted."},
        ]
    # create：新建一个源码文件再提交
    return [
        {"tool": ("run_command", {"command": "ls -a /workspace"})},
        {"tool": ("write_file", {"filepath": "mockfix/__init__.py", "content": '"""mock fix."""\n\nVALUE = 42\n'})},
        {"tool": ("run_command", {"command": "cd /workspace && git status --porcelain"})},
        {"tool": ("submit_patch", {})},
        {"text": "Mock run finished: created mockfix/__init__.py and submitted."},
    ]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # 静音
        pass

    def _send(self, obj: dict, code: int = 200) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # /v1/models、/health
        if self.path.rstrip("/").endswith("/models"):
            self._send({"object": "list", "data": [{"id": "mock-model", "object": "model"}]})
        else:
            self._send({"status": "ok"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            req = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            req = {}

        mode = self.server.mode  # type: ignore[attr-defined]
        steps = script_for(mode)
        idx = min(STATE["n"], len(steps) - 1)
        STATE["n"] += 1
        step = steps[idx]

        if "tool" in step:
            name, args = step["tool"]
            msg = {
                "role": "assistant",
                "content": None,
                "tool_calls": [_tool_call(name, args)],
            }
            finish = "tool_calls"
        else:
            msg = {"role": "assistant", "content": step["text"]}
            finish = "stop"

        self._send({
            "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": req.get("model", "mock-model"),
            "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        })


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8111)
    ap.add_argument("--script", choices=["create", "existing"], default="create")
    args = ap.parse_args()

    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    srv.mode = args.script  # type: ignore[attr-defined]
    print(f"mock LLM server on http://127.0.0.1:{args.port}/v1  (script={args.script})", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
