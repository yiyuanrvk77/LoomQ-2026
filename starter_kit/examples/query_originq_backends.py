"""Read-only OriginQ backend discovery using pyQPanda3 QCloudService.

The token is read from LOOMQ_ORIGINQ_TOKEN and is never printed or stored.
"""

import json
import os
import sys


def main() -> int:
    token = os.environ.get("LOOMQ_ORIGINQ_TOKEN", "").strip()
    if not token:
        print("请先设置 LOOMQ_ORIGINQ_TOKEN，再运行本示例。", file=sys.stderr)
        return 2

    from pyqpanda3.qcloud import QCloudService

    service = QCloudService(api_key=token)
    availability = dict(service.backends())
    if not availability:
        print("当前账号没有可查询的 OriginQ 后端。")
        return 0
    for name, is_available in availability.items():
        backend = service.backend(name)
        info = backend.chip_info()
        print(json.dumps({
            "backend": name,
            "available": bool(is_available),
            "chip_id": info.chip_id(),
            "qubit_count": info.qubit_count(),
        }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
