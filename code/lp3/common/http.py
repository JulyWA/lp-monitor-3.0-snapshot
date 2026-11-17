"""lp3 共享网络工具。只放无业务规则的取数逻辑。

get() / get_curl() 的重试语义与 mvp3/collect.py 的 get() / get_curl() 完全一致（M1 原样搬过来）：
  - 400/404 是确定性错误，不重试；
  - 429 退避加长 4 倍；
  - 超时、读断等瞬时错误有限重试；
  - 最终失败抛 SourceError。
新增：按主机统计请求次数、HTTP 状态、重试和异常，写进模块输出的 source_health。
"""
import json
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

UA = {'User-Agent': 'Mozilla/5.0 (Macintosh) lp-coverage-collect'}


class SourceError(RuntimeError):
    """上游取数失败（已按规则重试）。"""


_STATS = {}


def reset_stats():
    _STATS.clear()


def stats():
    """返回 {主机: {requests, ok, retries, http_errors: {code: n}, exceptions: n}} 的副本。"""
    return json.loads(json.dumps(_STATS))


def _host(url):
    return urllib.parse.urlsplit(url).netloc or url[:40]


def _bump(url, key, code=None):
    s = _STATS.setdefault(_host(url), {'requests': 0, 'ok': 0, 'retries': 0, 'http_errors': {}, 'exceptions': 0})
    if key == 'http_error':
        s['http_errors'][str(code)] = s['http_errors'].get(str(code), 0) + 1
    else:
        s[key] += 1


def record(url, ok, retry=False, error=None):
    """给不经过 get()/get_curl() 的调用（如 Curve 的批量 eth_call）记一笔统计。error：HTTP 状态码或任意真值（记为异常）。"""
    _bump(url, 'requests')
    if retry:
        _bump(url, 'retries')
    if ok:
        _bump(url, 'ok')
    elif isinstance(error, int):
        _bump(url, 'http_error', error)
    else:
        _bump(url, 'exceptions')


def get(url, tries=4, wait=4, timeout=60):
    last = None
    for k in range(tries):
        _bump(url, 'requests')
        if k:
            _bump(url, 'retries')
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                data = json.loads(r.read())
            _bump(url, 'ok')
            return data
        except urllib.error.HTTPError as e:
            last = e
            _bump(url, 'http_error', e.code)
            if e.code in (400, 404):  # 确定性错误：参数或地址错，不重试
                break
            time.sleep(wait * (k + 1) * (4 if e.code == 429 else 1))
        except Exception as e:  # 超时、读断：瞬时错误，重试
            last = e
            _bump(url, 'exceptions')
            time.sleep(wait * (k + 1))
    raise SourceError('%s -> %s' % (url[:160], last))


def get_curl(url, tries=4, wait=5):
    """DefiLlama 的大响应用 Python urllib 在 1 号机常报 SSL 解密错误（11-11 实测），改走 curl。"""
    last = None
    for k in range(tries):
        _bump(url, 'requests')
        if k:
            _bump(url, 'retries')
        p = subprocess.run(['curl', '-sS', '--fail', '--max-time', '120', '-A', UA['User-Agent'], url], capture_output=True)
        if p.returncode == 0:
            try:
                data = json.loads(p.stdout)
                _bump(url, 'ok')
                return data
            except ValueError as e:
                last = e
                _bump(url, 'exceptions')
        else:
            last = p.stderr.decode(errors='replace').strip()[-120:]
            _bump(url, 'exceptions')
            if 'error: 400' in last or 'error: 404' in last:
                break
        time.sleep(wait * (k + 1))
    raise SourceError('%s -> %s' % (url[:160], last))
