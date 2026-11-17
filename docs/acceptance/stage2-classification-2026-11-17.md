# 阶段 2 分类抽查 · 2026-11-17 输出（20 池）

**结论：19 / 20 正确**。

- 数据：1 号机 2026-11-17 10:20 自然运行产出（同步包 `lp-lab/sync/20261117-134937/out-mvp3`）。
- 管线标签：来自 11-16 17:22 刷新的 Solana 标签缓存；对照：CoinGecko 公开接口实时查询（时间见每行）。
- 方法：分层抽样（种子 20261117），每家覆盖全部标签类型，必含 USDG / sUSD.infra 和 BLESS / USDC；判定 = 资产类别一致且标签一致。

| # | 协议 | 池 | TVL | 管线（类别 · 标签 · 挡因） | 实时（类别 · 标签） | 判定 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Orca | USDG / sUSD.infra | $1.6M | 代币 · ok · 过门槛 | 代币 · ok | 正确 |
| 2 | Orca | TSLA / USDC | $0.9M | 股票和商品 · ok · 过门槛 | 股票和商品 · ok | 正确 |
| 3 | Orca | SOL / PENGU | $2.2M | 代币 · meme · CoinGecko meme 标签 | 代币 · meme | 正确 |
| 4 | Orca | SOL / NEAR | $1.1M | 代币 · unlisted · 过门槛 | 代币 · unlisted | 正确 |
| 5 | Orca | cbBTC / USDC | $4.3M | 代币 · anchor · 过门槛 | 代币 · anchor | 正确 |
| 6 | Orca | USDu / USDC | $2.8M | 代币 · ok · 过门槛 | 代币 · ok | 正确 |
| 7 | Orca | SOL / CARDS | $0.8M | 代币 · ok · 过门槛 | 代币 · ok | 正确 |
| 8 | Raydium Concentrated | BLESS / USDC | $11.1M | 代币 · unknown · 代币分类待更新 | 代币 · unlisted | **错误** |
| 9 | Raydium Concentrated | NVDAx / USDC | $2.8M | 股票和商品 · ok · 过门槛 | 股票和商品 · ok | 正确 |
| 10 | Raydium Standard | WSOL / Fartcoin  | $5.0M | 代币 · meme · CoinGecko meme 标签 | 代币 · meme | 正确 |
| 11 | Raydium Standard | ONE / FOL | $1.0M | 代币 · unlisted · CoinGecko 未收录且 7 天手续费/TVL < 0.01% | 代币 · unlisted | 正确 |
| 12 | Raydium Concentrated | WSOL / CAPX | $0.5M | 代币 · ok · 过门槛 | 代币 · ok | 正确 |
| 13 | Raydium Concentrated | WSOL / USDC | $5.4M | 代币 · anchor · 过门槛 | 代币 · anchor | 正确 |
| 14 | Raydium Standard | WSOL / NPC | $0.5M | 代币 · meme · CoinGecko meme 标签 | 代币 · meme | 正确 |
| 15 | Meteora DLMM | SPCX-USDC | $0.9M | 股票和商品 · ok · 过门槛 | 股票和商品 · ok | 正确 |
| 16 | Meteora DLMM | MELANIA-USDC | $7.0M | 代币 · meme · CoinGecko meme 标签 | 代币 · meme | 正确 |
| 17 | Meteora DAMM v2 | VBC-SOL | $0.6M | 代币 · unlisted · 过门槛 | 代币 · unlisted | 正确 |
| 18 | Meteora DAMM v2 | MET-USDC | $2.7M | 代币 · ok · 过门槛 | 代币 · ok | 正确 |
| 19 | Meteora DLMM | SOL-USDC | $1.7M | 代币 · anchor · 过门槛 | 代币 · anchor | 正确 |
| 20 | Meteora DLMM | BP-USDC | $6.0M | 代币 · ok · 过门槛 | 代币 · ok | 正确 |

## 错误与无法核实

- **Raydium Concentrated BLESS / USDC**：管线标签 unknown，CoinGecko 实时 unlisted（标签缓存未覆盖或过期）；该池**仅因待分类被挡**

## 逐代币查询

- sUSD.infra `GvEMgNT6…`：HTTP 200，id=staked-usd-infra，分类=Solana Ecosystem、Yield-Bearing Stablecoin、Yield-Bearing Tokens（2026-11-17T13:55:15+08:00）
- TSLA `TSLAqBbv…`：HTTP 200，id=tesla-backpack-securities，分类=Tokenized Assets、Solana Ecosystem、Tokenized Stocks、Real World Assets (RWA)、Backpack Securities Ecosystem（2026-11-17T13:55:24+08:00）
- PENGU `2zMMhcVQ…`：HTTP 200，id=pudgy-penguins，分类=BNB Chain Ecosystem、Solana Ecosystem、Meme、Ethereum Ecosystem、Solana Meme、Hyperliquid Ecosystem、Binance HODLer Airdrops、Airdropped Tokens by NFT Projects、Abstrac（2026-11-17T13:55:34+08:00）
- NEAR `3ZLekZYq…`：HTTP 404，id=None，分类=—（2026-11-17T13:55:43+08:00）
- USDu `9ckR7pPP…`：HTTP 200，id=usdu，分类=BNB Chain Ecosystem、Solana Ecosystem、Yield-Bearing Stablecoin、Unitas Ecosystem（2026-11-17T13:55:52+08:00）
- CARDS `CARDSccU…`：HTTP 200，id=collector-crypt，分类=Solana Ecosystem、Real World Assets (RWA)、RWA Protocol、Trading Card RWA Platform（2026-11-17T13:56:02+08:00）
- BLESS `67eejmec…`：HTTP 404，id=None，分类=—（2026-11-17T13:57:19+08:00）
- NVDAx `Xsc9qvGR…`：HTTP 200，id=nvidia-xstock，分类=Tokenized Assets、BNB Chain Ecosystem、Solana Ecosystem、Arbitrum Ecosystem、Tokenized Stocks、Ethereum Ecosystem、Real World Assets (RWA)、Mantle Ecosystem、TON Ecosys（2026-11-17T13:57:29+08:00）
- Fartcoin  `9BB6NFEc…`：HTTP 200，id=fartcoin，分类=Solana Ecosystem、Meme、Solana Meme、AI Meme、Pump.fun Ecosystem、Terminal of Truths、Binance Alpha Spotlight（2026-11-17T13:57:38+08:00）
- ONE `9Fdne837…`：HTTP 404，id=None，分类=—（2026-11-17T13:57:48+08:00）
- FOL `As8wX7HW…`：HTTP 404，id=None，分类=—（2026-11-17T13:57:56+08:00）
- CAPX `7AoBuYcG…`：HTTP 200，id=capx-ai-2，分类=Artificial Intelligence (AI)、Infrastructure、Solana Ecosystem（2026-11-17T13:58:06+08:00）
- NPC `BeGY8KqK…`：HTTP 200，id=non-playable-coin，分类=NFT、BNB Chain Ecosystem、Solana Ecosystem、Meme、Ethereum Ecosystem、Base Ecosystem、Hybrid Token Standards、Wojak-Themed、4chan-Themed、Base Native、Robinhood Ecosystem（2026-11-17T13:58:15+08:00）
- SPCX `SPCXxcqX…`：HTTP 200，id=spacex-backpack-securities，分类=Tokenized Assets、Solana Ecosystem、Tokenized Stocks、Real World Assets (RWA)、Backpack Securities Ecosystem（2026-11-17T13:59:26+08:00）
- MELANIA `FUAfBo2j…`：HTTP 200，id=melania-meme，分类=Solana Ecosystem、Meme、Solana Meme、PolitiFi、Made in USA、Trump-Affiliated（2026-11-17T13:59:36+08:00）
- VBC `6N7aaD1N…`：HTTP 404，id=None，分类=—（2026-11-17T13:59:44+08:00）
- MET `METvsvVR…`：HTTP 200，id=meteora，分类=Decentralized Exchange (DEX)、Exchange-based Tokens、Decentralized Finance (DeFi)、Solana Ecosystem、Launchpad、Binance Alpha Spotlight（2026-11-17T13:59:53+08:00）
- BP `BPxxfRCX…`：HTTP 200，id=backpack，分类=Exchange-based Tokens、Centralized Exchange (CEX) Token、Solana Ecosystem、Wallets（2026-11-17T14:00:09+08:00）
