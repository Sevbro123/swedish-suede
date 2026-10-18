import gzip
import json

import pytest

from nhlmodel.ingest.http import CachedClient, NotFound


class FakeResp:
    def __init__(self, status, body=b"{}"):
        self.status_code = status
        self.content = body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}
        self.calls = []

    def get(self, url, timeout):
        self.calls.append(url)
        return self.responses.pop(0)


class FakeClock:
    def __init__(self):
        self.t = 0.0
        self.sleeps = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def make(tmp_path, responses, **kw):
    clock = FakeClock()
    sess = FakeSession(responses)
    c = CachedClient(tmp_path, "test-agent", session=sess, sleep=clock.sleep, clock=clock.now, **kw)
    return c, sess, clock


def test_cache_hit_makes_no_network_call(tmp_path):
    c, sess, _ = make(tmp_path, [FakeResp(200, b'{"a": 1}')])
    assert c.get_json("https://x.test/a", "src/a") == {"a": 1}
    assert c.get_json("https://x.test/a", "src/a") == {"a": 1}
    assert len(sess.calls) == 1
    assert json.loads(gzip.decompress((tmp_path / "src/a.json.gz").read_bytes())) == {"a": 1}


def test_manifest_records_fetch(tmp_path):
    c, _, _ = make(tmp_path, [FakeResp(200, b'{"a": 1}')])
    c.get_json("https://x.test/a", "src/a")
    rec = json.loads((tmp_path / "manifest.jsonl").read_text().splitlines()[0])
    assert rec["url"] == "https://x.test/a" and rec["status"] == 200 and len(rec["sha256"]) == 64


def test_404_is_cached_as_marker(tmp_path):
    c, sess, _ = make(tmp_path, [FakeResp(404)])
    for _ in range(2):
        with pytest.raises(NotFound):
            c.get_json("https://x.test/missing", "src/missing")
    assert len(sess.calls) == 1


def test_raw_cache_is_write_once(tmp_path):
    c, _, _ = make(tmp_path, [])
    p = tmp_path / "f.json.gz"
    c._write_once(p, b"x")
    with pytest.raises(FileExistsError):
        c._write_once(p, b"y")
    assert p.read_bytes() == b"x"


def test_rate_limit_spaces_requests_per_host(tmp_path):
    c, _, clock = make(tmp_path, [FakeResp(200), FakeResp(200)], min_interval_s=1.0)
    c.get_json("https://x.test/1", "src/1")
    c.get_json("https://x.test/2", "src/2")
    assert clock.sleeps == [pytest.approx(1.0)]


def test_retries_5xx_with_backoff_then_succeeds(tmp_path):
    c, sess, clock = make(tmp_path, [FakeResp(503), FakeResp(200, b"[1]")], min_interval_s=0.0, backoff_base_s=2.0)
    assert c.get_json("https://x.test/r", "src/r") == [1]
    assert len(sess.calls) == 2 and 2.0 in clock.sleeps


def test_invalid_json_is_not_cached(tmp_path):
    c, _, _ = make(tmp_path, [FakeResp(200, b"<html>")])
    with pytest.raises(json.JSONDecodeError):
        c.get_json("https://x.test/h", "src/h")
    assert not c.is_cached("src/h")


@pytest.mark.parametrize("key", ["../escape", "a/../../b", "a b", ""])
def test_unsafe_cache_keys_rejected(tmp_path, key):
    c, _, _ = make(tmp_path, [])
    with pytest.raises(ValueError):
        c.is_cached(key)
