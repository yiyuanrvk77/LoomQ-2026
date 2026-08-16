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


def _circuit_diagram(qasm: str) -> dict:
    """把 QASM 解析成前端可渲染的电路图数据。"""
    circuit = adapter.parse(qasm)
    gates = []
    for gate in circuit.gates:
        gates.append(
            {
                "name": gate.name,
                "qubits": list(gate.qubits),
                "params": [round(float(p), 4) for p in gate.params],
            }
        )
    for qubit, _clbit in circuit.measures:
        gates.append({"name": "measure", "qubits": [qubit]})
    return {"num_qubits": circuit.num_qubits, "gates": gates}


def _load_real_bell() -> dict | None:
    """读取真机 Bell 态实测结果（若无则返回 None），用于展示真实噪声。"""
    path = Path(__file__).parent / "evidence" / "files" / "spinq_gemini_bell.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    probs = data.get("probabilities") or data.get("counts")
    if not probs:
        return None
    # 归一化为概率（counts 是整数时除以总和）
    total = sum(probs.values())
    if total > 1.5:  # 是 counts
        return {k: v / total for k, v in probs.items()}
    return dict(probs)


def _circuit_summary(circuit) -> str:
    """根据电路结构给一句零基础用户能懂的大白话解读。"""
    names = [g.name for g in circuit.gates]
    n = circuit.num_qubits
    if n == 2 and sorted(names) == ["cx", "h"]:
        return "这是「贝尔态」：两个比特总是同时为 0、或同时为 1——这就是量子纠缠。真机因为噪声，会有约 10% 的偏差（看红色那组）。"
    if names and names[0] == "h" and len(names) >= 2 and all(x == "cx" for x in names[1:]):
        return "这是「GHZ 纠缠态」：所有比特的测量结果总是全同（要么全 0、要么全 1），是比贝尔态更「长」的纠缠链。"
    if n == 1 and names == ["h"]:
        return "这是「叠加态」：一个比特同时处于 0 和 1 两种状态，测量那一刻才随机坍缩成其中一个。"
    if not names:
        return "这个电路没有量子门，测量结果是确定态。"
    return "这是你生成的量子电路：每一根柱子代表某个测量结果出现的概率。"


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
  .guide { background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 8px; padding: 14px 16px; margin: 14px 0; font-size: 14px; line-height: 1.7; }
  .guide ol { margin: 8px 0 0; padding-left: 20px; }
  .guide a { color: #2563eb; }
  #quantum-field { width: 100%; height: 200px; display: block; background: radial-gradient(ellipse at center, #101b33 0%, #060a14 70%); border-radius: 10px; cursor: crosshair; }
  .field-label { position: relative; color: #7dd3fc; font-size: 12px; letter-spacing: 2px; margin-top: 6px; text-align: center; }
  .circuit { background: #fafafa; border: 1px solid #e5e7eb; border-radius: 6px; padding: 10px; overflow-x: auto; }
  .circuit-row { display: flex; align-items: center; height: 30px; white-space: nowrap; }
  .circuit-q { width: 34px; font-family: monospace; color: #666; flex: none; }
  .circuit-gate { display: inline-block; min-width: 24px; padding: 2px 5px; margin: 0 3px; text-align: center; border: 1px solid #334155; border-radius: 3px; background: #fff; font-family: monospace; font-size: 12px; }
  .circuit-space { display: inline-block; width: 24px; }
  .compare { margin-top: 8px; }
  .cmp-row { display: flex; align-items: center; margin: 3px 0; }
  .cmp-key { width: 60px; font-family: monospace; }
  .cmp-track { flex: 1; height: 8px; background: #eee; border-radius: 2px; margin: 0 6px; position: relative; }
  .cmp-fill { position: absolute; left: 0; top: 0; bottom: 0; border-radius: 2px; }
  .cmp-val { width: 76px; font-size: 12px; color: #555; }
  .legend { margin-top: 6px; font-size: 12px; color: #555; }
  .legend span { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 3px; vertical-align: middle; }
</style>
</head>
<body>
  <canvas id="quantum-field"></canvas>
  <p class="field-label">粒子 = 量子比特 · 连线 = 纠缠 · 鼠标靠近 = 测量扰动</p>
  <h1>LoomQ · 说一句话，指挥量子计算</h1>
  <p class="hint">试试：生成一个 3 比特的 GHZ 纠缠态并全测量；或：15 比特零排队免费选哪个平台？</p>
  <div class="guide">
    <b>三步玩懂量子计算（零基础也能玩）：</b>
    <ol>
      <li>点下面一个<b>算法按钮</b>（比如 GHZ-3），看电路怎么跑、结果长什么样</li>
      <li>在下方「问个概念」里输入「什么是纠缠」，看解释 + 能跑的电路</li>
      <li>打开 <a href="visualizations/index.html" target="_blank">纠错实验室</a>，亲手放一个错误看它被抓住</li>
    </ol>
  </div>
  <textarea id="prompt" placeholder="在这里输入你想做的事……"></textarea>
  <br><button id="go">生成 / 运行</button>
  <span class="hint" style="margin-left:10px;">快捷算法：</span>
  <button class="preset" data-name="ghz3" style="background:#475569;">GHZ-3</button>
  <button class="preset" data-name="grover3" style="background:#475569;">Grover-3</button>
  <button class="preset" data-name="qft4" style="background:#475569;">QFT-4</button>
  <div id="result"></div>
  <hr style="margin:28px 0;border:0;border-top:1px solid #e5e7eb;">
  <h2 style="font-size:1.2em;">问个概念 · 不懂就问我</h2>
  <p class="hint">试试：什么是贝尔态 / 什么是量子叠加 / 解释一下退相干</p>
  <textarea id="concept-input" placeholder="问一个量子概念……"></textarea>
  <br><button id="concept-btn">问概念</button>
  <div id="concept-result"></div>
  <hr style="margin:28px 0;border:0;border-top:1px solid #e5e7eb;">
  <h2 style="font-size:1.2em;">翻译官 · 同一电路的三家方言</h2>
  <p class="hint">展示 LoomQ 中间层如何把一份 OpenQASM 2.0 翻译成三家后端各自的格式。</p>
  <textarea id="qasm-input">OPENQASM 2.0;
include "qelib1.inc";
qreg q[2];
creg c[2];
h q[0];
cx q[0],q[1];
measure q[0] -> c[0];
measure q[1] -> c[1];
</textarea>
  <br><button id="transpile-btn">翻译成三家</button>
  <div id="transpile-result"></div>
  <hr style="margin:28px 0;border:0;border-top:1px solid #e5e7eb;">
  <h2 style="font-size:1.2em;">混合编译 · 量子 + 经典 → RISC-V</h2>
  <p class="hint">展示 L3 如何把 Hybrid-QASM 的经典块编译成 RISC-V 汇编。</p>
  <textarea id="hybrid-input">OPENQASM 2.0;
include "qelib1.inc";
qreg q[1];
creg c[1];
measure q[0] -> c[0];
classical { if (c[0] == 1) { r1 = 7; } else { r1 = 3; } }
</textarea>
  <br><button id="compile-btn">编译</button>
  <div id="compile-result"></div>
<script>
  (function () {
    var canvas = document.getElementById('quantum-field');
    var ctx = canvas.getContext('2d');
    var particles = [];
    var mouse = { x: -9999, y: -9999, active: false };
    var w = 0, h = 0, dpr = 1;
    var highlight = [];
    var highlightUntil = 0;

    function resize() {
      dpr = window.devicePixelRatio || 1;
      w = canvas.clientWidth;
      h = canvas.clientHeight;
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    function spawn() {
      particles = [];
      var count = Math.max(20, Math.min(44, Math.round(w * h / 4000)));
      for (var i = 0; i < count; i++) {
        particles.push({
          x: Math.random() * w,
          y: Math.random() * h,
          vx: (Math.random() - 0.5) * 0.35,
          vy: (Math.random() - 0.5) * 0.35,
          r: 1.2 + Math.random() * 2.1,
          phase: Math.random() * Math.PI * 2,
          glow: 0.45 + Math.random() * 0.55
        });
      }
    }

    function isHighlighted(i) {
      return highlight.indexOf(i) !== -1 && Date.now() < highlightUntil;
    }

    function draw() {
      ctx.clearRect(0, 0, w, h);
      var i, j, p, q, dx, dy, dist;

      for (i = 0; i < particles.length; i++) {
        p = particles[i];
        p.x += p.vx;
        p.y += p.vy;
        if (mouse.active) {
          dx = p.x - mouse.x;
          dy = p.y - mouse.y;
          dist = Math.sqrt(dx * dx + dy * dy);
          if (dist < 90 && dist > 0.001) {
            var force = (90 - dist) / 90;
            p.x += (dx / dist) * force * 3.2;
            p.y += (dy / dist) * force * 3.2;
          }
        }
        if (p.x < -24) p.x = w + 24; else if (p.x > w + 24) p.x = -24;
        if (p.y < -24) p.y = h + 24; else if (p.y > h + 24) p.y = -24;
        p.phase += 0.035;
      }

      ctx.lineWidth = 0.6;
      for (i = 0; i < particles.length; i++) {
        for (j = i + 1; j < particles.length; j++) {
          p = particles[i]; q = particles[j];
          dx = p.x - q.x; dy = p.y - q.y;
          dist = Math.sqrt(dx * dx + dy * dy);
          if (dist < 96) {
            var base = (1 - dist / 96) * 0.30;
            if (isHighlighted(i) && isHighlighted(j)) { base = (1 - dist / 96) * 0.75 + 0.15; }
            ctx.strokeStyle = 'rgba(125, 211, 252, ' + base.toFixed(3) + ')';
            ctx.beginPath();
            ctx.moveTo(p.x, p.y);
            ctx.lineTo(q.x, q.y);
            ctx.stroke();
          }
        }
      }

      for (i = 0; i < particles.length; i++) {
        p = particles[i];
        var pulse = 0.6 + 0.4 * Math.sin(p.phase);
        var on = isHighlighted(i);
        var color = on ? '103, 232, 249' : '125, 211, 252';
        var alpha = p.glow * pulse * (on ? 1.25 : 1);
        var halo = p.r * (on ? 5 : 4);
        var grad = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, halo);
        grad.addColorStop(0, 'rgba(' + color + ', ' + Math.min(1, alpha).toFixed(3) + ')');
        grad.addColorStop(1, 'rgba(' + color + ', 0)');
        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.arc(p.x, p.y, halo, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = 'rgba(224, 242, 254, ' + Math.min(1, alpha + 0.25).toFixed(3) + ')';
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fill();
      }

      requestAnimationFrame(draw);
    }

    canvas.addEventListener('mousemove', function (e) {
      var rect = canvas.getBoundingClientRect();
      mouse.x = e.clientX - rect.left;
      mouse.y = e.clientY - rect.top;
      mouse.active = true;
    });
    canvas.addEventListener('mouseleave', function () { mouse.active = false; });
    canvas.addEventListener('touchmove', function (e) {
      e.preventDefault();
      var rect = canvas.getBoundingClientRect();
      var t = e.touches[0];
      mouse.x = t.clientX - rect.left;
      mouse.y = t.clientY - rect.top;
      mouse.active = true;
    }, { passive: false });
    canvas.addEventListener('touchend', function () { mouse.active = false; });

    window.setQuantumField = function (n) {
      n = Math.max(1, Math.min(n || 1, particles.length));
      highlight = [];
      while (highlight.length < n) {
        var idx = Math.floor(Math.random() * particles.length);
        if (highlight.indexOf(idx) === -1) { highlight.push(idx); }
      }
      highlightUntil = Date.now() + 7000;
    };

    window.addEventListener('resize', function () { resize(); spawn(); });
    resize();
    spawn();
    draw();
  })();

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

  document.getElementById('transpile-btn').addEventListener('click', function () {
    var qasm = document.getElementById('qasm-input').value.trim();
    var el = document.getElementById('transpile-result');
    if (!qasm) { el.innerHTML = '<p class="error">请输入 QASM。</p>'; return; }
    el.innerHTML = '<p>正在翻译……</p>';
    fetch('/transpile', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ qasm: qasm }) })
      .then(function (r) { return r.json(); })
      .then(function (data) { renderTranspile(data); })
      .catch(function (e) { el.innerHTML = '<p class="error">翻译失败：' + e + '</p>'; });
  });

  document.querySelectorAll('.preset').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var name = btn.getAttribute('data-name');
      var result = document.getElementById('result');
      result.innerHTML = '<p>正在运行算法……</p>';
      fetch('/preset', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: name }) })
        .then(function (r) { return r.json(); })
        .then(function (data) { render(data); })
        .catch(function (e) { result.innerHTML = '<p class="error">请求失败：' + e + '</p>'; });
    });
  });

  document.getElementById('compile-btn').addEventListener('click', function () {
    var hybrid = document.getElementById('hybrid-input').value.trim();
    var el = document.getElementById('compile-result');
    if (!hybrid) { el.innerHTML = '<p class="error">请输入 Hybrid-QASM。</p>'; return; }
    el.innerHTML = '<p>正在编译……</p>';
    fetch('/compile', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ hybrid: hybrid }) })
      .then(function (r) { return r.json(); })
      .then(function (data) { renderCompile(data); })
      .catch(function (e) { el.innerHTML = '<p class="error">编译失败：' + e + '</p>'; });
  });

  document.getElementById('concept-btn').addEventListener('click', function () {
    var q = document.getElementById('concept-input').value.trim();
    var el = document.getElementById('concept-result');
    if (!q) { el.innerHTML = '<p class="error">请输入想了解的概念。</p>'; return; }
    el.innerHTML = '<p>正在查询……</p>';
    fetch('/concept', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ q: q }) })
      .then(function (r) { return r.json(); })
      .then(function (data) { renderConcept(data); })
      .catch(function (e) { el.innerHTML = '<p class="error">查询失败：' + e + '</p>'; });
  });

  function render(data) {
    var el = document.getElementById('result');
    if (!data.ok) { el.innerHTML = '<p class="error">' + escapeHtml(data.error) + '</p>'; return; }
    if (data.kind === 'answer') {
      el.innerHTML = '<p>' + escapeHtml(data.answer) + '</p>';
      return;
    }
    var html = '<p class="hint">电路图：</p>' + renderCircuit(data);
    if (data.summary) { html += '<div class="guide">' + escapeHtml(data.summary) + '</div>'; }
    html += '<p class="hint">已生成电路（OpenQASM 2.0）：</p><pre>' + escapeHtml(data.qasm) + '</pre>';
    html += renderCompare(data);
    el.innerHTML = html;
    if (window.setQuantumField) { window.setQuantumField(data.num_qubits); }
  }

  function gateLabel(g) {
    if (g.name === 'measure') { return 'M'; }
    var label = g.name.toUpperCase();
    if (g.params && g.params.length) { label += '(' + g.params.join(', ') + ')'; }
    return label;
  }

  function renderCircuit(data) {
    var rows = [];
    for (var i = 0; i < data.num_qubits; i++) { rows.push([]); }
    data.gates.forEach(function (g) {
      var qs = g.qubits;
      if (qs.length === 1) {
        rows[qs[0]].push(gateLabel(g));
      } else {
        qs.forEach(function (q, idx) {
          var mark = (g.name === 'cx' || g.name === 'ccx')
            ? (idx === qs.length - 1 ? '⊕' : '●')
            : gateLabel(g);
          rows[q].push(mark);
        });
      }
    });
    var html = '<div class="circuit">';
    rows.forEach(function (row, i) {
      html += '<div class="circuit-row"><span class="circuit-q">q' + i + '</span>';
      row.forEach(function (label) {
        html += '<span class="circuit-gate">' + escapeHtml(label) + '</span>';
      });
      html += '</div>';
    });
    html += '</div>';
    return html;
  }

  function renderCompare(data) {
    var keys = {};
    Object.keys(data.ideal || {}).forEach(function (k) { keys[k] = true; });
    Object.keys(data.counts || {}).forEach(function (k) { keys[k] = true; });
    Object.keys(data.noisy || {}).forEach(function (k) { keys[k] = true; });
    if (data.real) { Object.keys(data.real).forEach(function (k) { keys[k] = true; }); }
    var html = '<div class="compare"><p class="hint">概率对比（理想 / 实测 / 噪声模拟 / 真机）：</p>';
    Object.keys(keys).sort().forEach(function (key) {
      html += '<div class="cmp-row"><span class="cmp-key">' + key + '</span>';
      var iv = data.ideal ? (data.ideal[key] || 0) : 0;
      var cv = data.counts ? (data.counts[key] || 0) / data.shots : 0;
      var nv = data.noisy ? (data.noisy[key] || 0) : 0;
      var rv = data.real ? (data.real[key] || 0) : 0;
      html += cmpBar(iv, '#94a3b8') + cmpBar(cv, '#2563eb') + cmpBar(nv, '#f59e0b') + cmpBar(rv, '#dc2626');
      html += '</div>';
    });
    html += '<div class="legend"><span style="background:#94a3b8"></span>理想（无噪声） <span style="background:#2563eb"></span>实测采样 <span style="background:#f59e0b"></span>噪声模拟 <span style="background:#dc2626"></span>真机（SpinQ Gemini）</div>';
    html += '</div>';
    return html;
  }

  function cmpBar(prob, color) {
    var pct = Math.round(prob * 1000) / 10;
    return '<div class="cmp-track"><div class="cmp-fill" style="width:' + Math.min(100, pct) + '%;background:' + color + '"></div></div><span class="cmp-val">' + pct.toFixed(1) + '%</span>';
  }

  function renderTranspile(data) {
    var el = document.getElementById('transpile-result');
    if (!data.ok) { el.innerHTML = '<p class="error">' + escapeHtml(data.error) + '</p>'; return; }
    var html = '';
    Object.keys(data.results).forEach(function (t) {
      html += '<p class="hint">' + escapeHtml(data.labels[t]) + '：</p><pre>' + escapeHtml(data.results[t]) + '</pre>';
    });
    el.innerHTML = html;
  }

  function renderCompile(data) {
    var el = document.getElementById('compile-result');
    if (!data.ok) { el.innerHTML = '<p class="error">' + escapeHtml(data.error) + '</p>'; return; }
    var html = '<p class="hint">量子操作序列：</p><pre>' + escapeHtml(JSON.stringify(data.quantum_ops, null, 2)) + '</pre>';
    html += '<p class="hint">RISC-V 汇编：</p><pre>' + escapeHtml(data.assembly) + '</pre>';
    el.innerHTML = html;
  }

  function renderConcept(data) {
    var el = document.getElementById('concept-result');
    if (!data.ok) { el.innerHTML = '<p class="error">' + escapeHtml(data.error) + '</p>'; return; }
    var html = '<p><b>' + escapeHtml(data.name) + '</b>：' + escapeHtml(data.explain) + '</p>';
    html += '<p class="hint">可运行电路（复制到上面「生成」框即可跑）：</p><pre>' + escapeHtml(data.qasm) + '</pre>';
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
        # 静态文件：量子纠错可视化实验室（visualizations/*.html）
        if self.path.startswith("/visualizations/"):
            self._serve_visualization(self.path)
            return
        # 可视化页里「回 QUANTUM_101」等文档链接
        if self.path.startswith("/QUANTUM_101.md"):
            self._serve_doc("QUANTUM_101.md")
            return
        if self.path.startswith("/ARCHITECTURE.md"):
            self._serve_doc("ARCHITECTURE.md")
            return
        body = HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_visualization(self, url_path: str) -> None:
        filename = url_path[len("/visualizations/"):].split("?")[0].split("#")[0]
        # 只允许单个文件名，禁止子路径与路径穿越
        if not filename or "/" in filename or "\\" in filename or ".." in filename:
            self._send_plain(404, "Not Found")
            return
        file = Path(__file__).parent / "visualizations" / filename
        if not file.is_file():
            self._send_plain(404, "Not Found")
            return
        content_type = (
            "text/html; charset=utf-8"
            if file.suffix == ".html"
            else "text/plain; charset=utf-8"
        )
        self._send_bytes(200, content_type, file.read_bytes())

    def _serve_doc(self, filename: str) -> None:
        file = Path(__file__).parent / filename
        if not file.is_file():
            self._send_plain(404, "Not Found")
            return
        self._send_bytes(200, "text/plain; charset=utf-8", file.read_bytes())

    def _send_bytes(self, code: int, content_type: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_plain(self, code: int, text: str) -> None:
        self._send_bytes(code, "text/plain; charset=utf-8", text.encode("utf-8"))

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
            if self.path == "/transpile":
                self._handle_transpile(data)
                return
            if self.path == "/preset":
                self._handle_preset(data)
                return
            if self.path == "/compile":
                self._handle_compile(data)
                return
            if self.path == "/concept":
                self._handle_concept(data)
                return
            prompt = (data.get("prompt") or "").strip()
            if not prompt:
                self._json({"ok": False, "error": "请输入一句想做的事。"})
                return
            reply = adapter.agent_chat(prompt)
            if "OPENQASM" in reply:
                self._json(self._run_payload(reply))
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

    def _run_payload(self, qasm: str) -> dict:
        result = adapter.run(qasm, "braket", 1024)
        circuit = adapter.parse(qasm)
        ideal = adapter.probabilities(circuit)
        diagram = _circuit_diagram(qasm)
        is_bell = (
            diagram["num_qubits"] == 2
            and len(circuit.gates) == 2
            and sorted(g.name for g in circuit.gates) == ["cx", "h"]
        )
        real = _load_real_bell() if is_bell else None
        noisy_counts = adapter.simulate_with_noise(circuit, 1024, 0.03)
        return {
            "ok": True,
            "kind": "qasm",
            "qasm": qasm,
            "summary": _circuit_summary(circuit),
            "counts": result["counts"],
            "shots": result["shots"],
            "ideal": ideal,
            "noisy": {k: v / 1024 for k, v in noisy_counts.items()},
            "gates": diagram["gates"],
            "num_qubits": diagram["num_qubits"],
            "real": real,
        }

    def _handle_preset(self, data: dict) -> None:
        presets = {
            "ghz3": adapter.ghz(3),
            "grover3": adapter.grover_3(7),
            "qft4": adapter.qft(4),
        }
        name = (data.get("name") or "").strip()
        if name not in presets:
            self._json({"ok": False, "error": "未知算法"})
            return
        self._json(self._run_payload(presets[name]))

    def _handle_compile(self, data: dict) -> None:
        hybrid = (data.get("hybrid") or "").strip()
        if not hybrid:
            self._json({"ok": False, "error": "请输入 Hybrid-QASM。"})
            return
        quantum_ops, assembly = adapter.compile_hybrid(hybrid)
        self._json(
            {
                "ok": True,
                "kind": "compile",
                "quantum_ops": quantum_ops,
                "assembly": assembly,
            }
        )

    def _handle_concept(self, data: dict) -> None:
        q = (data.get("q") or "").strip()
        if not q:
            self._json({"ok": False, "error": "请输入想了解的概念。"})
            return
        concept = adapter.concept_answer(q)
        if not concept:
            self._json(
                {
                    "ok": False,
                    "error": "没找到这个概念。试试：贝尔态、GHZ、叠加、纠缠、测量、退相干。",
                }
            )
            return
        self._json({"ok": True, "kind": "concept", **concept})

    def _handle_transpile(self, data: dict) -> None:
        qasm = (data.get("qasm") or "").strip()
        if not qasm:
            self._json({"ok": False, "error": "请输入要翻译的 OpenQASM 2.0。"})
            return
        labels = {
            "spinq": "SpinQ（OpenQASM 2.0）",
            "braket": "Braket（OpenQASM 3.0）",
            "originq": "OriginQ（OriginIR）",
        }
        results = {}
        for target in labels:
            results[target] = adapter.transpile(qasm, target)
        self._json({"ok": True, "kind": "transpile", "labels": labels, "results": results})

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
