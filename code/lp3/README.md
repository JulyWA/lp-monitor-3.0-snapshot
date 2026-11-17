# lp3 · 3.0 模块化（研究机开发中）

任务书：`~/lp-lab/notes/TASK-3.0-modular.md`。原代码 `mvp3/` 不改，留作对照和回退。

| 路径 | 作用 |
| --- | --- |
| `common/http.py` | 请求与重试（与 mvp3 语义相同）+ 按主机统计 |
| `common/refdata.py` | 股票名单、Solana 标签缓存（只读，带文件指纹） |
| `common/coverage.py` | 采全比纯函数（M1 原样复制自 `mvp3/llama_cover.py`） |
| `common/contract.py` | 模块输出契约 `lp3.module.v1` 与校验 |
| `common/quality.py` | 跨日冻结检测 |
| `run_module.py` | 跑单个模块；任何异常只算本模块失败 |
| `orchestrate.py` + `schedule.json` | 按时段逐个起子进程，独立超时，写 `automation-lab` 状态 |
| `replay/` | 录制上游响应、回放、逐字段对比 |
| `modules/` | 6 个 DEX 模块（M2） |

## 常用命令（仓库根目录）

```bash
/usr/bin/python3 -m unittest discover -s lp3/tests -t .
/usr/bin/python3 -m lp3.replay.legacy record --sources=orca,raydium,meteora --date=YYYY-MM-DD --cassette=out/lab/replay/<名>/cassette --out=out/lab/replay/<名>/legacy-live --seed=out/mvp3
/usr/bin/python3 -m lp3.replay.legacy replay --sources=... --date=... --cassette=... --out=out/lab/replay/<名>/legacy-replay --seed=out/mvp3
/usr/bin/python3 -m lp3.replay.compare --a=<目录A> --b=<目录B> --sources=... --date=... --report=<报告.md>
```

输出在 `out/lab/`（被 .gitignore 忽略），状态在 `~/.local/state/automation-lab/`。编排器拒绝写正式状态目录 `~/.local/state/automation/`。
