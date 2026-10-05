# 计量校准换算服务 (Calibration Translation Service)

在不同仪器坐标系之间，依据有向标定关系 `y = a·x + b` 做**精确有理数**换算，
并保证互相矛盾的标定证据不会被浮点舍入或任选路径掩盖。

## 设计要点

- **全程精确有理运算**：使用 `fractions.Fraction`，整数或 `p/q` 形式直接精确解析，
  拒绝小数（`1.5`）等近似写法；系数与结果均以**最简分数**返回（分母为 1 时省略分母）。
- **可逆关系组合**：每条关系要求 `a ≠ 0`；无向边可沿任一方向行走，反向使用精确逆变换。
- **路径无关性校验**：将整组关系视为方程组，对全图做一致性检查——任意连接两端的路径
  必须导出同一个仿射变换。实现上取任意生成森林，逐条检验非树边是否闭合为恒等变换；
  结果与录入顺序、遍历顺序无关。
- **任一相关环路冲突即拒绝**：即使矛盾环与本次 source/target 无关，也返回
  `409 conflict` 并指出环路上涉及的仪器，**绝不返回看似可用的系数或读数**。
- **不可达识别错误**：source 与 target 不连通时返回 `404 unreachable`。

## API

### `GET /health`

健康检查，返回 `{"status": "ok"}`。

### `POST /api/calibrations/translate`

请求体：

| 字段 | 约束 |
| --- | --- |
| `instruments` | 2–50 个唯一仪器名 |
| `relations` | 1–100 条有向关系，每项含 `source`、`target`、`a`、`b`（整数或 `p/q`，`a ≠ 0`） |
| `source` / `target` | 必须在 `instruments` 中声明 |
| `readings` | 待换算读数（整数或 `p/q`），至少一个 |

成功响应（`200`）：

```json
{
  "source": "A",
  "target": "C",
  "coefficients": {"a": "6", "b": "7"},
  "readings": ["0", "1", "1/3"],
  "results": ["7", "13", "9"]
}
```

错误响应：

- `404` `{"error": "unreachable", "message": ..., "instruments": [source, target]}`
- `409` `{"error": "conflict", "message": ..., "instruments": [环路上的仪器...]}`
- `422` `{"error": "invalid_request", ...}`（非法有理数、零斜率、重复/未声明仪器等）

示例：

```bash
curl -s localhost:8000/api/calibrations/translate -H 'Content-Type: application/json' -d '{
  "instruments": ["A","B","C"],
  "relations": [
    {"source":"A","target":"B","a":"2","b":"1"},
    {"source":"B","target":"C","a":"3","b":"4"}
  ],
  "source":"A","target":"C","readings":["0","1","1/3"]
}'
```

## 运行（Docker Compose）

```bash
# 宿主机端口可配置（默认 8000）
API_HOST_PORT=9090 docker compose up -d api

# 一次性校验服务：等待 api 健康后运行
#   1) 构建健全性检查（编译 + 导入）
#   2) pytest 代码测试
#   3) 一致链 / 矛盾链 / 不可达 的接口冒烟
# 以退出码报告结果后自行退出（restart: "no"）
docker compose up verify
docker inspect --format '{{.State.ExitCode}}' $(docker compose ps -q verify)
```

## 本地开发

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
pytest -q
uvicorn app.main:app --port 8000
python scripts/verify.py   # 需先启动 API；可用 API_BASE_URL 覆盖地址
```

## 代码结构

- `app/rational.py` — 规范有理数的精确解析与最简分数格式化
- `app/graph.py` — 精确仿射变换、逆变换、全图环路一致性校验、连通性与路径组合
- `app/main.py` — FastAPI 路由、请求校验与错误码
- `tests/` — 有理数解析、图算法（含乱序不变性、无关环冲突）与接口测试
- `scripts/verify.py` — 一次性 verify 服务
