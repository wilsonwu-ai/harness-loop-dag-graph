"""DAG: fixed steps that hand files to each other, decided before the run starts.
Each step names its inputs and outputs. The runner goes in dependency order, skips a step whose
inputs have not changed since it last ran (so a crash resumes instead of restarting), and stops at a
gate until a person approves a digest of exactly what they saw."""
import hashlib, json
from pathlib import Path

def digest(paths):
    h = hashlib.sha256()
    for p in sorted(paths):
        h.update(p.encode()); h.update(Path(p).read_bytes() if Path(p).exists() else b"<missing>")
    return h.hexdigest()[:16]

def order(steps):
    done, out = set(), []
    produced = {o: s["name"] for s in steps for o in s.get("outputs", [])}
    while len(out) < len(steps):
        ready = [s for s in steps if s["name"] not in done and all(produced.get(i) in done or i not in produced for i in s.get("inputs", []))]
        if not ready:
            raise ValueError("cycle: a DAG cannot loop")
        for s in ready:
            done.add(s["name"]); out.append(s)
    return out

def run(steps, state_file, approvals=None):
    state = json.loads(Path(state_file).read_text()) if Path(state_file).exists() else {}
    approvals, ran = approvals or {}, []
    for s in order(steps):
        d = digest(s.get("inputs", []))
        if s.get("gate"):
            if approvals.get(s["name"]) != d:
                Path(state_file).write_text(json.dumps(state))
                return {"ran": ran, "waiting_at": s["name"], "approve_digest": d}
            continue
        if state.get(s["name"]) == d and all(Path(o).exists() for o in s.get("outputs", [])):
            continue                                     # unchanged since last run: resume, don't redo
        s["fn"](); state[s["name"]] = d; ran.append(s["name"])
    Path(state_file).write_text(json.dumps(state))
    return {"ran": ran, "waiting_at": None}
