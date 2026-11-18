# lp3 · 3.0 模块化采集

任务书：`mvp3/TASK-3.0-modular.md`（3.0 第一阶段总任务书是 `mvp3/TASK-3.0.md`）。原代码 `mvp3/` 不改，留作对照和回退。
研究机开发、验证；正式上线走 `release/` 发布包，由 1 号机预检、影子运行、July 批准后启用。

## 目录

| 路径 | 作用 |
| --- | --- |
| `modules/<模块>/` | 6 个 DEX 模块：curve、aero、rh、orca、raydium、meteora。每个模块有 `README.md`（数据源、规则、APY 口径、开关、已知限制）、`config.json`、`rules.py`、`module.py`、`VERSION`、`CHANGELOG.md` |
| `common/` | 共享工具，不含业务规则：请求与重试（`http.py`）、参考数据读取（`refdata.py`）、采全比公式（`coverage.py`）、DefiLlama 与 GeckoTerminal 客户端、输出格式与校验（`contract.py`）、冻结检测 |
| `run_module.py` | 跑单个模块；任何异常只算本模块失败 |
| `orchestrate.py` + `schedule.json` | 按时段逐个起子进程，独立超时，写状态文件；拒绝写 1 号机正式状态目录 |
| `run_stage.sh` | 一个时段：编排 + 整合日报（研究机、1 号机影子、1 号机正式都用它） |
| `aggregate.py` + `aggregate.json` | 整合层：只读 6 个模块当天文件，校验并标注状态，生成本地日报和卡片草稿；没有发送代码 |
| `refresh/` | 内部阶段 3：Solana 标签刷新（`sol_labels.py`）、股票和商品名单刷新（`stocklist.py`）、扫描覆盖率每天重算（`coverage_daily.py`） |
| `acceptance/` | 验收核对脚本：阶段 2 分类抽查、阶段 1 动态费率实跑核对 |
| `replay/` | 录制上游响应、回放、逐字段对比（证明新旧一致） |
| `lab/` | 研究机专用：定时入口、从 1 号机只读拉取、历史播种、与 1 号机同日对比；不进发布包的部分见 `release/build_release.py` |
| `release/` | 发布包：打包器、影子与正式 plist 模板、preflight / install / verify / activate / rollback |
| `tests/` | 单元测试、差分测试、故障注入（68 个） |

## 模块版本（11-18）

| 模块 | 版本 | 说明 |
| --- | --- | --- |
| curve | 1.1.0 | 1.1.0 开关默认关：链上费率、官方池页链接 |
| aero | 1.0.0 | — |
| rh | 1.1.0 | 1.1.0 开关默认关：Uniswap V3 协议抽成扣成实收 |
| orca | 1.0.0 | — |
| raydium | 1.1.0 | 1.1.0 开关默认关：按池类型扣成 LP 实收 |
| meteora | 1.0.0 | — |

开关关闭时 6 个模块与旧代码逐字段 0 差异。发布顺序：先 1.0.0（纯拆分），再在研究机打开开关跑 3 天后发 1.1.0（模块化任务书决策 #9）。

## 研究机定时任务（`com.july.lab.*`，只写 `out/lab/` 和 `~/.local/state/automation-lab/`）

| 时间 | 任务 |
| --- | --- |
| 06:30 | `lp3-refdata`：标签增量刷新；周日全量 + 股票名单 |
| 08:20 / 10:20 | `lp3-stage1` / `lp3-stage2`：模块化采集 + 整合日报 |
| 10:40、18:40 | `lp3-pull`：从 1 号机只读拉取当天产出 |
| 10:50 | `lp3-coverage`：扫描覆盖率重算（干跑，对照原脚本） |

## 常用命令（仓库根目录）

```bash
/usr/bin/python3 -m unittest discover -s lp3/tests -t .
/usr/bin/python3 -m lp3.run_module orca --date=YYYY-MM-DD --out-root=<目录>
/usr/bin/python3 -m lp3.aggregate --date=YYYY-MM-DD
/usr/bin/python3 -m lp3.replay.compare --a=<目录A> --b=<目录B> --sources=... --date=...
/usr/bin/python3 -m lp3.lab.compare_prod --prod=out/mvp3 --date=YYYY-MM-DD
```
