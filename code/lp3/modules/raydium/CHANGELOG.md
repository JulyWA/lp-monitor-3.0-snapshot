# raydium 模块变更记录

## 1.1.0 · 2026-11-18

- 新增 lp_share_mode=net：按池类型把 APY 扣成 LP 实收（Concentrated 84%；CPMM 扣创建者费和协议/基金；AMM v4 88%）。11-18 核实官方 volumeFee 与页面 feeApr 都是总手续费口径。开关默认关，关闭时输出与 1.0.x 相同（回放 0 差异）。

## 1.0.0 · 2026-11-17

- 从 mvp3/collect.py（提交 fe9f8e2）拆出，规则、数据源、输出与原代码一致（录制回放逐字段比对 0 差异）。
