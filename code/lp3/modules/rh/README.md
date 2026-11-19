# Robinhood 主流交易对 模块（lp3/modules/rh）

版本 1.1.0 · 时段 第一步 · 08:20（aero 之后） · 变更见 `CHANGELOG.md`。

## 数据源

| 用途 | 接口 | 性质 |
| --- | --- | --- |
| 池列表、TVL、24h 成交、池名费率 | api.geckoterminal.com（networks/robinhood，前 10 页） | 第三方聚合 |
| V3 协议抽成（1.1.0） | 链上 slot0().feeProtocol，robinhood-rpc.publicnode.com（备用官方 RPC） | 链上只读 |

## 规则

门槛（`config.json` 的 `rules` 段，初值与 1 号机提交 fe9f8e2 相同）：TVL ≥ $50 万；部署 ≥ 7 天；24h 成交 ≤ 3 × 近 7 天日均（现为整池不过门槛，见 3.0 任务书风险表）。资产类别：任一侧在股票和商品名单里，归「股票和商品」。

Robinhood 专有：两侧都是主流币（WETH、ETH、USDG、USDC、USDT、WBTC、cbBTC）才收；非股票、非主流币一律按非研究对象 N1（非主流代币池）存档；股票池归 2.0，不在这里。dex 以 aero-、aerodrome-、ramses- 开头的是动态费率池：不用池名费率，费率和 APY 留空，注「动态费率，未取」。

## APY 口径

即时 = 24h 成交 × 池名费率 × 365 ÷ TVL。**名义口径**：Uniswap V3 池没扣协议抽成（11-18 实测 5 池全部开启，APY 高估 20%–33%）。没有 7 天 APY。

## 输出字段

池地址、池名、dex 编号、TVL、24h 成交、费率和即时 APY（非动态费率池）、部署天数、Aero 池前端链接。 另有追溯块：模块版本、提交号、状态、采集时间、接口请求统计。字段覆盖率见《字段清单与降级规则》。

## 开关（1.1.0，默认关）

| 开关 | 作用 | 当前值 |
| --- | --- | --- |
| `deduct_v3_protocol_fee` | Uniswap V3 池按链上协议抽成扣成 LP 实收，与 2.0 同口径；读不到的 APY 留空 | `false` |

M4（至 11-20）结束后在研究机打开，跑满 3 天后随 1.1.0 发布（3.0 模块化任务书决策 #9）。

## 已知限制

- 采全比不适用（只采主流对）
- GeckoTerminal 池名费率不可靠（Aero 池一天内从 0.067% 变成 0.161%）
- 没有 7 天数据

## 改动规矩

- 改规则只改本模块的 `config.json` 或 `rules.py`，升版本号，写 CHANGELOG，补测试，并跑回放对比。
- 规则或数据源变更要 July 批准。
