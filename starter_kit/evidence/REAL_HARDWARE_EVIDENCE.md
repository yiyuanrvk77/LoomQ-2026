# 真机证据操作说明

真机属于 L1 额外加分，不是 L1 入门资格、L2 智能体或包容奖的强制条件。平台维护、
设备离线或权限窗口关闭时，使用本地模拟器完成基础链路即可。

## 取证步骤

1. 用平台自己的账号和凭证登录。凭证只放在当前机器的环境变量或平台 SDK 配置中，不能写入
   源码、网页、JSON、截图或 Git 历史。
2. 使用同一份白名单 OpenQASM 2.0 Bell 电路提交任务，并保存平台控制台的原始任务详情。
3. 保存平台返回的原始 JSON，不手工改写、不补齐缺失 shot、不把 counts 归一化后当成原始结果。
4. OriginQ 先通过 `QCloudService` 查询当前在线设备；`originq_wukong` 是逻辑能力标识，
   物理设备可以是平台实际返回的 `WK_C180_2` 或其他在线设备。SpinQ 也可以使用当前在线的
   `gemini_vp` 等真实后端。
5. 将原始导出和平台截图放入 `evidence/files/`，再创建一个符合下列 Schema 的归档结果。
   归档结果中的 `backend` 应写实际设备或平台后端标识，不能写 `local-*`。
6. 在 `starter_kit/` 目录运行：

   ```bash
   python3 evidence/validate_hardware_result.py evidence/files/<normalized-result>.json
   ```

7. 只有验证通过且 job ID 能在平台控制台重新打开时，才在 `evidence/README.md` 中申报该平台
   的真机加分。

## 归档 Schema

```json
{
  "backend": "spinq_gemini_vp",
  "job_id": "platform-job-id",
  "shots": 1024,
  "counts": {"00": 480, "11": 544},
  "bit_order": "little",
  "timestamp": "2026-08-20T03:00:00Z",
  "meta": {
    "is_hardware": true,
    "is_mock": false,
    "platform_device_id": "gemini_vp",
    "source_result": "raw-platform-result.json"
  }
}
```

`counts` 的整数合计必须与 `shots` 完全相等，不能用概率值替代 counts。`timestamp` 必须带
时区并落在 2026-07-31 16:00 UTC 至 2026-08-25 04:00 UTC 的赛程窗口内。平台若返回
1023 条 counts 而声明 1024 shots，应重新导出完整任务结果；不能补 1、删除 1 或重新采样。

## 当前仓库记录

`files/spinq_gemini_bell.json` 仍保留作原始留档，但它缺少 `backend`、`bit_order`、`timestamp`，
且 counts 合计为 1023、shots 声明为 1024。因此它当前不能申报真机加分，必须从平台重新导出
完整结果后再生成归档 Schema。
