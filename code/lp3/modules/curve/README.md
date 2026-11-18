# Curve · Ethereum 模块（lp3/modules/curve）

版本 1.1.0 · 时段 第一步 · 08:20 · 变更见 `CHANGELOG.md`。

## 数据源

| 用途 | 接口 | 性质 |
| --- | --- | --- |
| 成交、手续费、7 天日线、池列表 | prices.curve.finance | 官方 API |
| TVL | api.curve.finance getPools 的 usdTotal（资产明细合计） | 官方 API，curve.fi 前端同源 |
| LP 分成 | 链上 admin_fee()，ethereum-rpc.publicnode.com | 链上只读，免费公共节点 |
| 采全比分母 | api.llama.fi | 第三方，只作分母 |

## 规则

门槛（`config.json` 的 `rules` 段，初值与 1 号机提交 fe9f8e2 相同）：TVL ≥ $50 万；部署 ≥ 7 天；24h 成交 ≤ 3 × 近 7 天日均（现为整池不过门槛，见 3.0 任务书风险表）。资产类别：任一侧在股票和商品名单里，归「股票和商品」。

Curve 专有：getPools 标 isBroken 或 TVL 为 0 的池排除；前端接口失败时 TVL 退回 Prices API 并告警；admin_fee 读不到按 Curve 文档默认 LP 拿 50%；Yield Basis 杠杆池不进 APY 榜。数据超过 6 小时视为陈旧，模块失败。

## APY 口径

即时 = 24h 手续费 × LP 分成 × 365 ÷ TVL；7 天 = Prices API 最近 7 个完整 UTC 日（至少 6 天）× 52 ÷ TVL。LP 实收口径。

## 输出字段

池地址、池名、TVL（来源写在 tvl_source）、24h/7 天成交和手续费、LP 分成、两种 APY、部署天数。没有费率字段（1.1.0 补）。 另有追溯块：模块版本、提交号、状态、采集时间、接口请求统计。字段覆盖率见《字段清单与降级规则》。

## 开关（1.1.0，默认关）

| 开关 | 作用 | 当前值 |
| --- | --- | --- |
| `read_fee_rate` | 链上读 fee() 补费率（11-18 实测 129 池读到 125，与页面一致） | `false` |
| `use_pool_urls` | 用 getPools 的官方池页链接 | `false` |

M4（至 11-20）结束后在研究机打开，跑满 3 天后随 1.1.0 发布（3.0 模块化任务书决策 #9）。

## 已知限制

- Prices API 的 TVL 系统性偏高，已不用于 TVL
- curve.fi 页面标题 TVL 来自 Prices API，人工核对要看资产明细合计（Yield Basis 池标题高 75%）
- 采全比仍超过 100%（约 109%），分子分母还有一处没对齐
- 11-18 运行耗时 881 秒（平时约 320 秒），观察中

## 改动规矩

- 改规则只改本模块的 `config.json` 或 `rules.py`，升版本号，写 CHANGELOG，补测试，并跑回放对比。
- 规则或数据源变更要 July 批准。
