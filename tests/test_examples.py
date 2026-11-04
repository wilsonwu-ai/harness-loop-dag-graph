import os, sys, tempfile, threading, time, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
from fake_model import FakeModel
import loop, harness, dag, graph

class Loop(unittest.TestCase):
    def test_agent_loop_runs_tool_then_answers(self):
        m = FakeModel([{"tool": "add", "args": {"a": 2, "b": 3}}, {"say": "5"}])
        r = loop.agent_loop(m, {"add": lambda a, b: a + b}, "2+3?")
        self.assertEqual((r["turns"], r["answer"]), (2, "5"))
        self.assertEqual(r["messages"][-1]["content"], 5)
    def test_agent_loop_turn_limit(self):
        m = FakeModel([{"tool": "noop"}] * 20)
        r = loop.agent_loop(m, {"noop": lambda: None}, "x", max_turns=3)
        self.assertEqual(r.get("stopped"), "turn limit")
    def test_outer_loop_retries_until_check_passes(self):
        state = {"n": 0}
        r = loop.outer_loop(lambda s: s.update(n=s["n"] + 1), lambda s: s["n"] >= 3, state)
        self.assertEqual(r, {"attempts": 3, "passed": True})
    def test_outer_loop_gives_up(self):
        self.assertFalse(loop.outer_loop(lambda s: None, lambda s: False, {}, max_attempts=2)["passed"])

class Harness(unittest.TestCase):
    def tools(self):
        return {"read": lambda path: f"contents of {path}", "delete": lambda path: "deleted"}
    def test_policy_blocks_denied_tool(self):
        m = FakeModel([{"tool": "delete", "args": {"path": "/"}}, {"say": "ok"}])
        h = harness.Harness(m, self.tools(), {"read": "allow", "delete": "deny"})
        r = h.run("clean up")
        self.assertIn(("blocked", "delete"), h.log)
        self.assertTrue(r["messages"][-1]["content"].startswith("BLOCKED"))
    def test_ask_needs_approval(self):
        m = FakeModel([{"tool": "delete", "args": {"path": "a"}}])
        h = harness.Harness(m, self.tools(), {"delete": "ask"})
        h.run("x"); self.assertIn(("blocked", "delete"), h.log)
        m2 = FakeModel([{"tool": "delete", "args": {"path": "a"}}])
        h2 = harness.Harness(m2, self.tools(), {"delete": "ask", "approved": {"delete"}})
        h2.run("x"); self.assertIn(("ran", "delete"), h2.log)
    def test_unknown_tool_defaults_to_deny(self):
        m = FakeModel([{"tool": "read", "args": {"path": "a"}}])
        h = harness.Harness(m, self.tools(), {})
        h.run("x"); self.assertIn(("blocked", "read"), h.log)
    def test_compaction_caps_context(self):
        seen = []
        def model(msgs):
            seen.append(len(msgs)); return {"tool": "read", "args": {"path": "a"}} if len(seen) < 8 else {"say": "done"}
        h = harness.Harness(model, self.tools(), {"read": "allow"}, max_context=5)
        h.run("x", max_turns=10)
        self.assertLessEqual(max(seen), 5)
    def test_hook_sees_every_tool_call(self):
        calls = []
        m = FakeModel([{"tool": "read", "args": {"path": "a"}}, {"say": "ok"}])
        harness.Harness(m, self.tools(), {"read": "allow"}, hooks={"before_tool": [lambda n, a: calls.append(n)]}).run("x")
        self.assertEqual(calls, ["read"])
    def test_subagent_has_own_context(self):
        parent = harness.Harness(FakeModel([]), self.tools(), {"read": "allow"})
        r = parent.subagent(FakeModel([{"tool": "read", "args": {"path": "b"}}, {"say": "child done"}]), "sub task")
        self.assertEqual(r["answer"], "child done"); self.assertEqual(parent.log, [])

class Dag(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory(); self.d = Path(self.t.name); self.count = {"fetch": 0, "draft": 0}
        raw, draft = str(self.d / "raw.txt"), str(self.d / "draft.txt")
        def fetch(): self.count["fetch"] += 1; Path(raw).write_text("data")
        def make(): self.count["draft"] += 1; Path(draft).write_text(Path(raw).read_text().upper())
        self.steps = [{"name": "publish", "inputs": [draft], "gate": True},
                      {"name": "draft", "inputs": [raw], "outputs": [draft], "fn": make},
                      {"name": "fetch", "outputs": [raw], "fn": fetch}]
        self.state = str(self.d / "state.json")
    def tearDown(self): self.t.cleanup()
    def test_runs_in_dependency_order_and_stops_at_gate(self):
        r = dag.run(self.steps, self.state)
        self.assertEqual(r["ran"], ["fetch", "draft"]); self.assertEqual(r["waiting_at"], "publish")
    def test_resume_skips_finished_steps(self):
        dag.run(self.steps, self.state); r = dag.run(self.steps, self.state)
        self.assertEqual(r["ran"], []); self.assertEqual(self.count, {"fetch": 1, "draft": 1})
    def test_approval_is_bound_to_what_was_seen(self):
        d = dag.run(self.steps, self.state)["approve_digest"]
        self.assertIsNone(dag.run(self.steps, self.state, {"publish": d})["waiting_at"])
        (self.d / "draft.txt").write_text("CHANGED AFTER APPROVAL")
        self.assertEqual(dag.run(self.steps, self.state, {"publish": d})["waiting_at"], "publish")
    def test_cycle_rejected(self):
        a = {"name": "a", "inputs": ["y"], "outputs": ["x"]}; b = {"name": "b", "inputs": ["x"], "outputs": ["y"]}
        with self.assertRaises(ValueError): dag.order([a, b])

class Graph(unittest.TestCase):
    def step(self, name, reads=(), writes=(), fn=None):
        return {"name": name, "reads": list(reads), "writes": list(writes), "fn": fn or (lambda r: name)}
    def test_fake_edges_removed(self):
        s = [self.step("plan", writes=["plan.md"]), self.step("a", reads=["plan.md"], writes=["a.md"]),
             self.step("b", reads=["plan.md"], writes=["b.md"]), self.step("merge", reads=["a.md", "b.md"], writes=["out.md"])]
        self.assertEqual(graph.layers(s), [["plan"], ["a", "b"], ["merge"]])
    def test_shared_write_target_is_hidden_edge(self):
        s = [self.step("a", writes=["sheet"]), self.step("b", writes=["sheet"])]
        self.assertEqual(graph.layers(s), [["a"], ["b"]])
    def test_amdahl(self):
        s, ceil = graph.speedup(0.95, 16)
        self.assertAlmostEqual(s, 9.14, places=2); self.assertAlmostEqual(ceil, 20.0)
        self.assertAlmostEqual(graph.speedup(0.6, 100)[1], 2.5)
    def test_parallel_layer_really_overlaps(self):
        live, peak, lock = [0], [0], threading.Lock()
        def work(r):
            with lock: live[0] += 1; peak[0] = max(peak[0], live[0])
            time.sleep(0.05)
            with lock: live[0] -= 1
            return 1
        s = [self.step(n, writes=[n], fn=work) for n in "abcd"]
        r = graph.run(s, verify=lambda res: sum(res.values()) == 4)
        self.assertTrue(r["verified"]); self.assertGreaterEqual(peak[0], 2)
    def test_verifier_reads_results(self):
        s = [self.step("a", writes=["x"], fn=lambda r: 2), self.step("b", reads=["x"], writes=["y"], fn=lambda r: r["a"] * 10)]
        self.assertTrue(graph.run(s, verify=lambda res: res["b"] == 20)["verified"])

if __name__ == "__main__":
    unittest.main()
