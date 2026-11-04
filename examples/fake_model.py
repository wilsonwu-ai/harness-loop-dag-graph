"""A scripted stand-in for an LLM so every example runs offline and the same way every time.
Give it a list of replies; each call returns the next one."""

class FakeModel:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), 0

    def __call__(self, messages):
        self.calls += 1
        if not self.replies:
            return {"say": "done"}
        return self.replies.pop(0)
