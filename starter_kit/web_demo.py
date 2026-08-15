#!/usr/bin/env python3
"""LoomQ 网页演示入口（L2 交互体验）。

本地起一个小服务，浏览器里输入一句话，就调用 agent_chat 生成/修复电路，
并在本地模拟器上跑出测量结果，画成条形图。零第三方依赖，只用标准库。

用法：
    先配置模型（三种方式任选其一）——
      1) 把 starter_kit/.env 写好（见 .env.example）
      2) 或先 export 三个 LOOMQ_LLM_* 环境变量
    然后：
      python3 starter_kit/web_demo.py [端口]
    浏览器打开 http://127.0.0.1:8000
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    import adapter
except Exception:  # noqa: BLE001
    print("找不到 adapter.py，请把本文件放到 starter_kit/ 目录里运行。", file=sys.stderr)
    sys.exit(1)


def load_dotenv() -> None:
    """读取 .env（KEY=VALUE 一行一条），已存在的环境变量优先。"""
    candidates = [Path(__file__).parent / ".env", Path.cwd() / ".env"]
    for path in candidates:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LoomQ · 说一句话，指挥量子计算</title>
<style>
  body { font-family: system-ui, "Microsoft YaHei", sans-serif; max-width: 720px; margin: 40px auto; padding: 0 20px; color: #1a1a1a; }
  h1 { font-size: 1.45em; }
  textarea { width: 100%; height: 72px; padding: 10px; font-size: 15px; border: 1px solid #ccc; border-radius: 6px; box-sizing: border-box; }
  button { margin-top: 10px; padding: 10px 22px; font-size: 15px; cursor: pointer; background: #2563eb; color: #fff; border: 0; border-radius: 6px; }
  #result { margin-top: 20px; }
  pre { background: #f6f8fa; padding: 12px; border-radius: 6px; overflow-x: auto; font-size: 13px; white-space: pre-wrap; }
  .bar-row { display: flex; align-items: center; margin: 4px 0; }
  .bar-key { width: 96px; font-family: monospace; }
  .bar-track { flex: 1; height: 20px; background: #eee; border-radius: 3px; overflow: hidden; }
  .bar-fill { height: 100%; background: #2563eb; }
  .bar-val { width: 110px; font-size: 13px; color: #555; margin-left: 8px; }
  .error { color: #b91c1c; }
  .hint { color: #777; font-size: 13px; }
</style>
</head>
<body>
  <h1>LoomQ · 说一句话，指挥量子计算</h1>
  <p class="hint">试试：生成一个 3 比特的 GHZ 纠缠态并全测量；或：15 比特零排队免费选哪个平台？</p>
  <textarea id="prompt" placeholder="在这里输入你想做的事……"></textarea>
  <br><button id="go">生成 / 运行</button>
  <div id="result"></div>
<script>
  document.getElementById('go').addEventListener('click', function () {
    var prompt = document.getElementById('prompt').value.trim();
    var result = document.getElementById('result');
    if (!prompt) { result.innerHTML = '<p class="error">请输入内容。</p>'; return; }
    result.innerHTML = '<p>正在生成……</p>';
    fetch('/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ prompt: prompt }) })
      .then(function (r) { return r.json(); })
      .then(function (data) { render(data); })
      .catch(function (e) { result.innerHTML = '<p class="error">请求失败：' + e + '</p>'; });
  });

  function render(data) {
    var el = document.getElementById('result');
    if (!data.ok) { el.innerHTML = '<p class="error">' + escapeHtml(data.error) + '</p>'; return; }
    if (data.kind === 'answer') {
      el.innerHTML = '<p>' + escapeHtml(data.answer) + '</p>';
      return;
    }
    var html = '<p class="hint">已生成电路（OpenQASM 2.0）：</p><pre>' + escapeHtml(data.qasm) + '</pre>';
    html += '<p class="hint">测量结果分布（shots=' + data.shots + '）：</p>';
    Object.keys(data.counts).forEach(function (k) {
      var v = data.counts[k];
      var pct = Math.round(100 * v / data.shots);
      html += '<div class="bar-row"><span class="bar-key">' + k + '</span><div class="bar-track"><div class="bar-fill" style="width:' + pct + '%"></div></div><span class="bar-val">' + v + ' (' + pct + '%)</span></div>';
    });
    el.innerHTML = html;
  }

  function escapeHtml(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
            prompt = (data.get("prompt") or "").strip()
            if not prompt:
                self._json({"ok": False, "error": "请输入一句想做的事。"})
                return
            reply = adapter.agent_chat(prompt)
            if "OPENQASM" in reply:
                result = adapter.run(reply, "braket", 1024)
                self._json(
                    {
                        "ok": True,
                        "kind": "qasm",
                        "qasm": reply,
                        "counts": result["counts"],
                        "shots": result["shots"],
                    }
                )
            else:
                self._json({"ok": True, "kind": "answer", "answer": reply})
        except Exception as exc:  # noqa: BLE001
            message = str(exc) or exc.__class__.__name__
            if "LOOMQ_LLM" in message or "environment variable" in message.lower():
                message = (
                    "缺少模型配置：请设置 LOOMQ_LLM_BASE_URL / LOOMQ_LLM_API_KEY / "
                    "LOOMQ_LLM_MODEL，或写进 starter_kit/.env（参考 .env.example）。"
                )
            self._json({"ok": False, "error": message})

    def _json(self, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        return


def main() -> None:
    load_dotenv()
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print("LoomQ 演示已启动：http://127.0.0.1:%d  （按 Ctrl+C 停止）" % port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

