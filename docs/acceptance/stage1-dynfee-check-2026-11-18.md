# 动态费率补丁实跑核对 · 2026-11-18

来源：`/Users/tool-03/lp-lab/sync/20261118-115256/out-mvp3`

| # | 检查 | 证据 | 结果 |
| --- | --- | --- | --- |
| 1 | Robinhood 动态费率池 fee/APY 为空 | 2 池：WETH / USDG fee=None apy=None；WETH / USDG fee=None apy=None | 符合 |
| 2 | notes 以「动态费率，未取」开头并写明 GT 池名费率 | 动态费率，未取（GeckoTerminal 池名费率 0.161% 不可信）；动态费率，未取（GeckoTerminal 池名费率 0.01% 不可信） | 符合 |
| 3 | 池名去掉费率，原名在 name_gt | WETH / USDG ← WETH / USDG 0.161%；WETH / USDG ← WETH / USDG 0.01% | 符合 |
| 4 | Aero 池链接 app.aero.xyz/deposit/4663-<地址>；Ramses 无链接 | aero-slipstream-robinhood https://app.aero.xyz/deposit/4663-0x7615926023bb149f36095645c2a81dc367d39750；ramses-v3-robinhood None | 符合 |
| 5 | Base 协议名只有 Aero / Aerodrome 旧版 | {'Aerodrome 旧版': 42, 'Aero': 50}；大池 92 | 符合 |
| 6 | 「旧版沉睡」只在旧版低成交池上，且不挡榜 | 12 池；其中过门槛 12 | 符合 |
| 7 | 非动态费率池照常算费率和 APY | 6 池有费率：USDG / WETH 0.01% 0.01%；USDG / WETH 0.05% 0.05%；cbBTC / WETH 0.05% 0.05%；WETH / USDG 0.05% 0.05%；USDG / WETH 0.3% 0.3% | 符合 |
| 8 | 运行 rc=0 | [2026-11-18T08:52:07+08:00] task=lp3-collect rc=0 duration=1923s | 符合 |

**8 / 8 符合**
