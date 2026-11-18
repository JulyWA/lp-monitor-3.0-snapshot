# rh 模块变更记录

## 1.1.0 · 2026-11-18

- 新增 deduct_v3_protocol_fee：Uniswap V3 池按链上 slot0.feeProtocol 扣成 LP 实收（与 2.0 同口径）；读不到的 APY 留空。开关默认关，关闭时输出与 1.0.x 相同（回放 0 差异）。

## 1.0.0 · 2026-11-17

- 从 mvp3/collect.py（提交 fe9f8e2）拆出，规则、数据源、输出与原代码一致（录制回放逐字段比对 0 差异）。
