# curve 模块变更记录

## 1.1.0 · 2026-11-18

- 新增 read_fee_rate（链上 fee() 补费率）和 use_pool_urls（getPools 的官方池页链接）。开关默认关，关闭时输出与 1.0.x 相同（回放 0 差异）。

## 1.0.1 · 2026-11-17

- 链上 admin_fee 批量读取（publicnode）计入 module.source_health。rows 和 summary 不变（回放 0 差异）。

## 1.0.0 · 2026-11-17

- 从 mvp3/collect.py（提交 fe9f8e2）拆出，规则、数据源、输出与原代码一致（录制回放逐字段比对 0 差异）。
