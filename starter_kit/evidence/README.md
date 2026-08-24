# 人工评分证据包

> 只在你申报对应评分项时才需要填写。附件统一放入 `evidence/files/`。
> 截图不能替代可追溯的 job ID、原始结果或可运行代码。

## 1. L1 真机（最高 10 分，每个平台 +5，至多 2 个平台）

- [x] 平台：SpinQ Cloud（gemini_vp，2 比特核磁共振真机，机型 Gemini-pro-1）
- [x] job ID：G-260816-0001（可在量旋云控制台溯源）
- [x] 运行时间：2026-08-16 01:31:22 ~ 01:32:55（UTC+8，落在赛程窗口内）
- [x] 实际执行的 QASM：Bell 态（`h q[0]; cx q[0], q[1];`，云端自动全测量）
- [x] 原始结果路径：`evidence/files/spinq_gemini_bell.json`
- [x] 附件：任务页截图 `evidence/files/spinq_gemini_task.png` + 网页任务详情 `evidence/files/spinq_gemini_web_task.json`
- [x] Schema 整理：`reconcile_evidence.py` 把平台原始导出映射为官方 Schema 的
  `spinq_gemini_bell.official.json`（backend=spinq_cloud_qpu、bit_order=little、
  timestamp 取 created_time_utc、shots 取返回 counts 的实际合计 1023）。
  **注意**：平台导出声明 shots=1024 而 counts 合计 1023，已在 `meta.declared_shots /
  counts_total` 中如实记录；申报前必须到量旋云控制台复核实际 shot 数。原始导出文件
  `spinq_gemini_bell.json` 保持不变，仅作溯源
- [x] 凭证边界：`adapter.run()` 仅运行本地模拟器；若后续增加独立 QPU 取证脚本，Token 只能
  从 `.env` / 环境变量注入，不能进入源码、网页请求或 evidence JSON

## 2. L2 交互体验（最高 10 分）

- [x] 入口启动方法：`python starter_kit/web_demo.py`，浏览器打开 http://127.0.0.1:8000 进入 Quantum Cave；配置模型时走正式 Agent，无配置时明确标注为有限的离线教学预设，不把预设申报为 L2 Agent；完整工作台保留在 `/classic`
- [x] 自然语言闭环：正式 Agent 把开放表达转为结构化意图，再生成并校验 OpenQASM 2.0；Quantum Cave 的 GHZ / Bell / 叠加态 / Grover 教学预设让无 Key 用户也能体验 QASM → 本地模拟 → counts / 理想分布 / 噪声对比
- [x] 过程可见性：页面将一次请求拆成「意图 → 电路 → 质疑 → 模拟 → 观测」五个可见阶段；阶段节点表达交互流程，真实模型调用与本地模拟模式会在状态栏明确标注
- [x] 预测-验证交互：用户先选择相关性 / 均匀分布 / 不确定，再运行实验并看到预测是否命中主峰
- [x] 语法墙联觉交互：首屏没有具象洞口，而是一整面缓慢流动的 Python/API 语法；拖动鼠标或
  手指会让字符在触点附近偏移并留下光痕，继续交互后 Python 交叉淡入 QASM，真实芭蕾素材被
  实时提取为无矩形边界的灰蓝墙面剪影，银河作为更深一层状态空间显现；首次触碰直接启动内嵌
  低频环境声和位置音高，键盘按钮保留等价路径，并提供静音控制
- [x] 具象到抽象：Python 墙 → QASM 记谱 → 连续舞步/状态变化 → 单次影子/测量 → 重复分布/证据；
  青 / 金 / 蓝分别延续到结果区的理想 / 本地采样 / 噪声，不用重新学习颜色含义
- [x] 四个可操作实验：重复码支持直接点物理比特并动态更新 syndrome；Shor 码解释行内 / 区块校验；
  Steane 码提供隐藏错误、二进制地址和连击；二维表面码让用户连出错误串并看到端点异常格。所有
  SVG 节点 / 网格边都有键盘等价操作、焦点反馈和 `aria-live` 结果，390 px 手机宽度无横向溢出
- [x] 观测控制：观测频率改变洞内投影影子的密度，shots 改变本地采样稳定性；页面明确区分教学投影与末端 QASM 测量
- [x] 用户体验任务 1：输入「生成一个 3 比特的 GHZ 纠缠态并全测量」→ 得到电路图 + 测量结果条形图；贝尔态展示「理想 / 本地采样 / 噪声模拟」对比，只有 Schema 完整的真机记录才进入界面
- [x] 用户体验任务 2：配置 `LOOMQ_LLM_*` 后输入「15 比特、零排队、免费，选哪个平台？」→ 得到规范后端标识；模型不可用时会明确提示无法完成开放式选型
- [x] 用户体验任务 3：配置 `LOOMQ_LLM_*` 后粘贴报错的 QASM 并说「帮我修好，我要的是贝尔态」→ 得到修复后的电路；本地模板只承诺教学预设
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
- [x] 结果可视化位置：web_demo.py 的电路图 + 测量条形图 + 三平台翻译对比；`starter_kit/visualizations/` 里 4 个纠错可视化（`lab.html` 学习路径入口）
- [x] 错误恢复 / 无障碍引导位置：web_demo.py 缺 key 时进入有明确标签的离线教学预设；不支持的意图给出明确中文提示；Agent 节点、预设、滑杆、预测选项以及四个纠错游戏的图形节点均可键盘操作
- [ ] 真机附件待核验：`spinq_gemini_bell.official.json` 已满足官方 Schema 字段；
  仍须在量旋云控制台复核 `job_id=G-260816-0001` 与 counts 合计 1023 / 声明 1024 的差异
- [ ] 附件：对应截图
