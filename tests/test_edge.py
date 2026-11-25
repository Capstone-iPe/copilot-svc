"""Rate limit and policy-search cache, with an in-memory stand-in for Key Value."""

from copilot.edge import CachedCorpus, allow, cached_search


class Memory:
    def __init__(self, fail=False):
        self.values = {}
        self.fail = fail
        self.expired = {}

    def incr(self, key):
        if self.fail:
            raise OSError("down")
        self.values[key] = int(self.values.get(key, 0)) + 1
        return self.values[key]

    def expire(self, key, seconds):
        self.expired[key] = seconds
        return True

    def get(self, key):
        if self.fail:
            raise OSError("down")
        return self.values.get(key)

    def set(self, key, value, ex=None):
        if self.fail:
            raise OSError("down")
        self.values[key] = value
        self.expired[key] = ex
        return True


def test_thirty_messages_in_a_minute_then_wait():
    store = Memory()
    assert all(allow("google:1", client=store, limit=2) for _ in range(2))
    assert allow("google:1", client=store, limit=2) is False
    assert allow("google:2", client=store, limit=2) is True


def test_a_down_store_still_allows_the_turn():
    assert allow("google:1", client=Memory(fail=True), limit=1) is True


def test_the_second_identical_search_does_not_call_the_corpus():
    store = Memory()
    calls = []

    def fetch(query, k):
        calls.append((query, k))
        return [{"document_id": "ONB-POL-001"}]

    assert cached_search("Why do you need that?", 4, fetch, client=store)[0]["document_id"] == "ONB-POL-001"
    assert cached_search("why do you need that?", 4, fetch, client=store)[0]["document_id"] == "ONB-POL-001"
    assert calls == [("Why do you need that?", 4)]


def test_an_empty_search_is_not_cached():
    store = Memory()
    calls = []

    def fetch(query, k):
        calls.append(query)
        return []

    assert cached_search("why", 4, fetch, client=store) == []
    assert cached_search("why", 4, fetch, client=store) == []
    assert calls == ["why", "why"]


def test_cached_corpus_uses_the_inner_search():
    class Inner:
        def __init__(self):
            self.calls = 0

        def search(self, query, k=4):
            self.calls += 1
            return [{"document_id": "ONB-POL-001"}]

    inner = Inner()
    corpus = CachedCorpus(inner)
    corpus.search("why", k=4)
    corpus.search("why", k=4)
    assert inner.calls == 2  # no store in this process
