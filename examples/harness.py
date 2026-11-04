"""HARNESS: everything around the model that turns its words into work.
agent = model + harness. This is a deliberately tiny one with the 7 parts:
loop, model call, tools, memory/context, permissions, orchestration (sub-agents), extensibility (hooks)."""
from loop import agent_loop

class Harness:
    def __init__(self, model, tools, policy, max_context=8, hooks=None):
        self.model, self.tools, self.policy = model, dict(tools), policy   # policy is data, not prose
        self.max_context = max_context                                       # memory: keep the last N messages
        self.hooks = hooks or {}                                             # extensibility: before_tool hooks
        self.log = []

    def _call_model(self, messages):                                         # LLM integration + compaction
        if len(messages) > self.max_context:
            messages = [messages[0], {"role": "system", "content": f"[{len(messages) - self.max_context + 1} older messages compacted]"}] + messages[-(self.max_context - 2):]
        return self.model(messages)

    def _guarded(self, name):                                                # safety: allow / ask / deny per tool
        def run(**args):
            rule = self.policy.get(name, "deny")
            for hook in self.hooks.get("before_tool", []):
                hook(name, args)
            if rule == "deny" or (rule == "ask" and not self.policy.get("approved", set()) >= {name}):
                self.log.append(("blocked", name))
                return f"BLOCKED: {name} needs approval"
            self.log.append(("ran", name))
            return self.tools[name](**args)
        return run

    def subagent(self, model, task):                                         # orchestration: a child with its own context
        return Harness(model, self.tools, self.policy, self.max_context, self.hooks).run(task)

    def run(self, task, max_turns=10):
        guarded = {n: self._guarded(n) for n in self.tools}
        return agent_loop(self._call_model, guarded, task, max_turns)
