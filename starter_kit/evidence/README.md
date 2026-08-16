# 人工评分证据包

> 只在你申报对应评分项时才需要填写。附件统一放入 `evidence/files/`。
> 截图不能替代可追溯的 job ID、原始结果或可运行代码。

## 1. L1 真机（最高 10 分，每个平台 +5，至多 2 个平台）

- [x] 平台：SpinQ Cloud（gemini_vp，2 比特核磁共振真机，机型 Gemini-pro-1）
- [x] job ID：G-260816-0001（可在量旋云控制台溯源）
- [x] 运行时间：2026-08-16 01:31:22 ~ 01:32:55（UTC+8，落在赛程窗口内）
- [x] shots：1024
- [x] 实际执行的 QASM：Bell 态（`h q[0]; cx q[0], q[1];`，云端自动全测量）
- [x] 原始结果路径：`evidence/files/spinq_gemini_bell.json`
- [x] 附件：任务页截图 `evidence/files/spinq_gemini_task.png` + 网页任务详情 `evidence/files/spinq_gemini_web_task.json`

## 2. L2 交互体验（最高 10 分）

- [x] 入口启动方法：`python starter_kit/web_demo.py`，浏览器打开 http://127.0.0.1:8000
- [x] 用户体验任务 1：输入「生成一个 3 比特的 GHZ 纠缠态并全测量」→ 得到电路图 + 测量结果条形图；贝尔态额外展示「理想 / 实测 / 真机」三组噪声对比
- [x] 用户体验任务 2：输入「15 比特、零排队、免费，选哪个平台？」→ 得到规范后端标识
- [x] 用户体验任务 3：粘贴报错的 QASM 并说「帮我修好，我要的是贝尔态」→ 得到修复后的电路
- [ ] 附件：关键流程截图 / 演示视频（大视频用稳定只读链接）

## 3. 工程与产品复核（人工部分最高 5 分）

- [x] 构建与启动方法：`python starter_kit/evaluator.py --json-out report.json`（纯标准库，无需安装依赖）
- [x] 主要模块：见 ARCHITECTURE.md（qasm_parser / simulator / transpiler / backends / agent / hybrid 六层）
- [x] 目标用户：不懂量子、但有真实问题要解决的跨界创作者（产品 / 设计 / 内容 / 领域专家）
- [x] 完整使用流程：web_demo.py 输入自然语言 → agent 生成 QASM → transpile 转译 → 本地模拟出结果
- [x] 附件：ARCHITECTURE.md、README.md，以及 outputs/ 下的技术文档与可视化

## 4. 自定义量子 RISC-V 扩展指令（Bonus，最高 +8 分）

- [x] 指令编码规格文档：`starter_kit/RISCV_EXTENSION.md`
- [x] 模拟器扩展实现位置：`starter_kit/riscv_emulator.py`（新增 `quant` 指令）
- [x] 端到端测试命令：`python starter_kit/examples/riscv_extension_demo.py`
- 三项齐全且测试通过才计分，无需额外附件。

## 5. 新手引导与视觉叙事（Bonus，最高 +4 分）

- [x] 首次运行引导位置：web_demo.py 网页内提示语 + starter_kit/QUANTUM_101.md
- [x] 概念解释位置：QUANTUM_101.md（30 分钟速成）
- [x] 结果可视化位置：web_demo.py 的测量结果条形图 + outputs/可视化/ 下 4 个纠错可视化
- [x] 错误恢复 / 无障碍引导位置：web_demo.py 缺 key 时给出明确中文提示；agent 生成失败自动重试并说明原因
- [ ] 附件：对应截图
