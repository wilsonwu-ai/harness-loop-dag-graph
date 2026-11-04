"""GRAPH: plan the job as a graph to decide what can run at the same time.
The fake edge test: an arrow from A to B is real only if B READS what A WRITES. Steps with no
real arrow between them can run in parallel. Two steps that WRITE the same place have a hidden
edge and must not. Then estimate the speedup before paying for it (Amdahl):
    S = 1 / ((1 - p) + p / N),  ceiling 1 / (1 - p)
where p is the share of the work that can run in parallel."""
from concurrent.futures import ThreadPoolExecutor

def real_edges(steps):
    edges = set()
    for a in steps:
        for b in steps:
            if a is b:
                continue
            if set(a["writes"]) & set(b["reads"]):
                edges.add((a["name"], b["name"]))                  # data really flows
            elif set(a["writes"]) & set(b["writes"]) and a["name"] < b["name"]:
                edges.add((a["name"], b["name"]))                  # shared write target: hidden edge
    return edges

def layers(steps):
    edges, left, out = real_edges(steps), {s["name"] for s in steps}, []
    while left:
        layer = sorted(n for n in left if not any(a in left and b == n for a, b in edges))
        if not layer:
            raise ValueError("cycle")
        out.append(layer); left -= set(layer)
    return out

def speedup(p, n):
    return 1 / ((1 - p) + p / n), 1 / (1 - p) if p < 1 else float("inf")

def run(steps, verify, workers=8):
    by = {s["name"]: s for s in steps}
    results = {}
    for layer in layers(steps):
        with ThreadPoolExecutor(workers) as ex:
            for name, out in zip(layer, ex.map(lambda n: by[n]["fn"](results), layer)):
                results[name] = out
    return {"layers": layers(steps), "results": results, "verified": verify(results)}
