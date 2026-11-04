"""LOOP: two loops people mean.

1. The agent loop (inside every coding agent): ask the model, run the tool it picked,
   show it the result, repeat until it says done or you hit a turn limit.
2. The outer loop (loop engineering, the "Ralph" pattern): run a whole fresh agent attempt,
   check the result with something that cannot argue back (a test), and run again until it passes.
   Progress lives in files, not in the model's memory, so every attempt starts clean."""

def agent_loop(model, tools, task, max_turns=10):
    messages = [{"role": "user", "content": task}]
    for turn in range(1, max_turns + 1):
        reply = model(messages)
        if "tool" not in reply:
            return {"turns": turn, "answer": reply.get("say"), "messages": messages}
        result = tools[reply["tool"]](**reply.get("args", {}))
        messages += [{"role": "assistant", "content": reply}, {"role": "tool", "content": result}]
    return {"turns": max_turns, "answer": None, "messages": messages, "stopped": "turn limit"}

def outer_loop(attempt, check, state, max_attempts=5):
    """attempt(state) does one fresh try and writes to state; check(state) is the anchor."""
    for n in range(1, max_attempts + 1):
        attempt(state)
        if check(state):
            return {"attempts": n, "passed": True}
    return {"attempts": max_attempts, "passed": False}
