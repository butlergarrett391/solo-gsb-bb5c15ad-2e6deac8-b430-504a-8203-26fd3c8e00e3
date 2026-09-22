# 实验测量单位校验 Web 应用

使用 **FastAPI + SQLite + 原生 JavaScript** 构建的实验测量计算与单位校验工具。
支持括号、乘除、幂运算、SI 前缀解析，按量纲自动换算，并以**一阶误差传播
（GUM，各输入相互独立）**计算结果不确定度；对量纲不兼容、零除、非法指数等
错误返回字段级提示。

## 一键启动（Docker Compose）

```bash
docker compose up --build -d
```

启动后在浏览器访问：

> **http://localhost:8000**

停止：

```bash
docker compose down
```

数据保存在 Docker 卷 `measurement-data`（容器内 `/app/data/entries.db`），
重建容器后已保存的计算条目不会丢失。

> 端口 8000 被占用时，修改 `docker-compose.yml` 中的 `"8000:8000"` 左侧端口即可。

## 本地直接运行（可选，无需 Docker）

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

访问 http://localhost:8000 。

## 功能

- **表达式解析**：括号 `()`、`+ - * /`（以及 `× ÷ ·`）、幂 `^` / `**`
- **SI 单位与前缀**：m, g, kg, s, A, K, mol, cd, Hz, N, Pa, J, W, V, Ohm/Ω,
  C, F, L, eV 等；前缀 `k M G T … m μ n p f` 等（如 `km`、`mV`、`μs`、`GHz`）
- **复合单位**：`m/s^2`、`kg·m/s^2`、`m s^-1`
- **不确定度输入**：
  - 显式：`9.81 ± 0.02 m/s^2`
  - 末位简记（GUM 写法）：`1.23(4) m` 表示 1.23 ± 0.04
- **量纲检查与换算**：不同前缀/派生单位自动折算到 SI 基本单位再运算；
  加减法量纲不一致会报错
- **一阶误差传播**：
  - 加减 `u = √(u₁² + u₂²)`
  - 乘除 `u/|f| = √((u₁/x₁)² + (u₂/x₂)²)`
  - 幂 `u/|f| = |n|·u/x`
- **字段级错误**：量纲不兼容、零除、非法指数、未知单位、括号不匹配等，
  均定位到 `expression` 字段并给出中文原因
- **条目管理**：保存计算结果、一键载入、删除
- **复制输入**：一键复制当前表达式到剪贴板
- **导出**：JSON（`/api/export.json`）与 CSV（`/api/export.csv`）

### 示例表达式

```text
(9.81 ± 0.02) m/s^2 * (1.20(3) s)^2
2.50(2) km / 400(5) s
3.00(1) kg + 250(2) g
12.0 V / 470(5) Ohm
(1.0 ± 0.1) mmol/L * 0.250 L
60 km/h * 30 min
```

## HTTP API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/calculate` | 计算 `{ "expression": "..." }` |
| `GET` | `/api/entries` | 已保存条目列表 |
| `POST` | `/api/entries` | 保存一条（服务端重新计算校验） |
| `DELETE` | `/api/entries/{id}` | 删除一条 |
| `GET` | `/api/export.json` | 导出全部条目为 JSON |
| `GET` | `/api/export.csv` | 导出全部条目为 CSV |
| `GET` | `/api/units` | 支持的单位与 SI 前缀 |

计算错误响应示例（HTTP 422，字段级）：

```json
{
  "detail": [
    { "field": "expression", "type": "dimension",
      "msg": "量纲不兼容：不能对 L 与 T 执行加法", "pos": 4 }
  ]
}
```

错误类型 `type`：`dimension`（量纲不兼容）、`zero_division`（零除）、
`exponent`（非法指数）、`unit`（未知单位）、`parse`（语法/括号错误）。

## 项目结构

```text
.
├── app/
│   ├── __init__.py
│   ├── main.py            # FastAPI 路由、SQLite、JSON/CSV 导出
│   ├── engine.py          # 词法/语法分析、量纲运算、一阶误差传播
│   ├── units.py           # SI 单位/派生单位/前缀注册表
│   └── static/
│       └── index.html     # 原生 JS 单页前端
├── data/entries.db        # SQLite（首次运行自动创建）
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```
