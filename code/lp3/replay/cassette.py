"""录制 / 回放上游响应。用来证明「同一份上游数据进新旧两套代码，输出相同」。

拦截三处底层调用（新旧代码都只经过这三处访问外部）：
  urllib.request.urlopen     —— collect.get() / lp3.common.http.get()
  subprocess.run(['curl',…]) —— get_curl()、Curve admin_fee 批量 eth_call
  time.time / time.sleep     —— 录制与回放都把 time.time 固定成同一个时刻，回放时 sleep 不等待
其他 subprocess（例如 git）原样放行。

请求键 = 方法 + 完整 URL + 请求体的 sha256。同一个键可出现多次（重试），按顺序存取。
回放时取不到录制的响应，抛 ReplayMiss，不会悄悄走网络。
目录结构：<cassette>/meta.json、index.jsonl、bodies/<sha256>.gz
"""
import contextlib
import gzip
import hashlib
import io
import json
import os
import subprocess
import time
import urllib.error
import urllib.request

_REAL_URLOPEN = urllib.request.urlopen
_REAL_RUN = subprocess.run
_REAL_SLEEP = time.sleep
_REAL_TIME = time.time


class ReplayMiss(RuntimeError):
    """回放时找不到对应的录制响应。"""


class _Resp(io.BytesIO):
    def __init__(self, body, status=200, url=''):
        super().__init__(body)
        self.status, self.code, self.url = status, status, url

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _sha(b):
    return hashlib.sha256(b or b'').hexdigest()


def _curl_key(args):
    url, body = None, b''
    for i, a in enumerate(args):
        if isinstance(a, str) and a.startswith(('http://', 'https://')):
            url = a
        if a == '-d' and i + 1 < len(args):
            body = args[i + 1].encode() if isinstance(args[i + 1], str) else args[i + 1]
    return 'CURL %s %s' % (url, _sha(body))


class Cassette:
    def __init__(self, path, mode, reuse_exhausted=False):
        """reuse_exhausted：回放时同一个键的录制用完后重复给最后一条。
        用于新模块：旧代码在一个进程里只拉一次的 DefiLlama 全表，拆成独立模块后每个模块各拉一次；
        同一冻结时刻、同一 URL，内容本来就该相同。重复次数记在 reused 里，报告中列出。"""
        assert mode in ('record', 'replay')
        self.path, self.mode = path, mode
        self.reuse_exhausted, self.reused = reuse_exhausted, {}
        self.bodies = os.path.join(path, 'bodies')
        self.entries = {}
        self.cursor = {}
        self.meta = {}
        self.n_recorded = 0
        if mode == 'record':
            os.makedirs(self.bodies, exist_ok=True)
            self._index = open(os.path.join(path, 'index.jsonl'), 'a')
        else:
            self.meta = json.load(open(os.path.join(path, 'meta.json')))
            for line in open(os.path.join(path, 'index.jsonl')):
                e = json.loads(line)
                self.entries.setdefault(e['key'], []).append(e)

    # ---------- 存取 ----------
    def _put_body(self, b):
        h = _sha(b)
        f = os.path.join(self.bodies, h + '.gz')
        if not os.path.exists(f):
            with gzip.open(f, 'wb') as fh:
                fh.write(b)
        return h

    def _get_body(self, h):
        if h is None:
            return b''
        with gzip.open(os.path.join(self.bodies, h + '.gz'), 'rb') as fh:
            return fh.read()

    def _append(self, entry):
        self._index.write(json.dumps(entry, ensure_ascii=False) + '\n')
        self._index.flush()
        self.n_recorded += 1

    def _next(self, key):
        lst = self.entries.get(key) or []
        i = self.cursor.get(key, 0)
        if i >= len(lst) and self.reuse_exhausted and lst:
            self.reused[key] = self.reused.get(key, 0) + 1
            return lst[-1]
        if i >= len(lst):
            raise ReplayMiss('回放缺少录制响应（第 %d 次）：%s' % (i + 1, key[:200]))
        self.cursor[key] = i + 1
        return lst[i]

    def unused(self):
        """回放结束后，还有多少条录制响应没被用到（新代码少发了请求时会出现）。"""
        return {k: len(v) - self.cursor.get(k, 0) for k, v in self.entries.items() if len(v) > self.cursor.get(k, 0)}

    # ---------- urlopen ----------
    def urlopen(self, req, *a, **kw):
        if isinstance(req, str):
            req = urllib.request.Request(req)
        url, body = req.full_url, req.data or b''
        key = '%s %s %s' % (req.get_method(), url, _sha(body))
        if self.mode == 'replay':
            e = self._next(key)
            if e['kind'] == 'http_error':
                raise urllib.error.HTTPError(url, e['status'], e.get('reason') or '', {}, io.BytesIO(self._get_body(e.get('body'))))
            if e['kind'] == 'exception':
                raise OSError('[replay] %s: %s' % (e['etype'], e['message']))
            return _Resp(self._get_body(e['body']), e['status'], url)
        try:
            with _REAL_URLOPEN(req, *a, **kw) as r:
                b = r.read()
                status = getattr(r, 'status', 200)
        except urllib.error.HTTPError as ex:
            eb = b''
            try:
                eb = ex.read() or b''
            except Exception:
                pass
            self._append({'key': key, 'kind': 'http_error', 'status': ex.code, 'reason': str(ex.reason), 'body': self._put_body(eb)})
            raise urllib.error.HTTPError(url, ex.code, ex.reason, ex.headers, io.BytesIO(eb))
        except Exception as ex:
            self._append({'key': key, 'kind': 'exception', 'etype': type(ex).__name__, 'message': str(ex)[:300]})
            raise
        self._append({'key': key, 'kind': 'ok', 'status': status, 'body': self._put_body(b)})
        return _Resp(b, status, url)

    # ---------- subprocess.run(curl) ----------
    def run(self, args, *a, **kw):
        if not (isinstance(args, (list, tuple)) and args and args[0] == 'curl'):
            return _REAL_RUN(args, *a, **kw)
        key = _curl_key(args)
        text = kw.get('text') or kw.get('universal_newlines')
        if self.mode == 'replay':
            e = self._next(key)
            out, err = self._get_body(e['stdout']), self._get_body(e['stderr'])
            if text:
                out, err = out.decode(), err.decode()
            return subprocess.CompletedProcess(args, e['returncode'], out, err)
        p = _REAL_RUN(args, *a, **kw)
        out = p.stdout.encode() if isinstance(p.stdout, str) else (p.stdout or b'')
        err = p.stderr.encode() if isinstance(p.stderr, str) else (p.stderr or b'')
        self._append({'key': key, 'kind': 'curl', 'returncode': p.returncode, 'stdout': self._put_body(out), 'stderr': self._put_body(err)})
        return p

    # ---------- 打补丁 ----------
    @contextlib.contextmanager
    def patched(self, now=None):
        """now：录制时传入要冻结的时刻（缺省取当前）；回放时忽略，用录制时的时刻。"""
        if self.mode == 'record':
            frozen = int(_REAL_TIME()) if now is None else int(now)
            self.meta = {'now': frozen, 'recorded_at': int(_REAL_TIME())}
            json.dump(self.meta, open(os.path.join(self.path, 'meta.json'), 'w'), indent=1)
        else:
            frozen = self.meta['now']
        saved = (urllib.request.urlopen, subprocess.run, time.time, time.sleep)
        urllib.request.urlopen = self.urlopen
        subprocess.run = self.run
        time.time = lambda: float(frozen)
        if self.mode == 'replay':
            time.sleep = lambda s: None
        try:
            yield frozen
        finally:
            urllib.request.urlopen, subprocess.run, time.time, time.sleep = saved
            if self.mode == 'record':
                self._index.close()
