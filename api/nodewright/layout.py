"""Automatic placement, so an agent never has to invent coordinates (design §7).

A layered ("Sugiyama") layout: break cycles, assign layers by longest path,
give each edge that skips layers a placeholder in every layer it crosses (so
the layers it passes leave a lane open for it instead of a node in its way),
order each layer by barycentre sweeps, then place nodes along each layer as
close to their neighbours as the spacing allows. Groups are laid out
recursively: a group's children form their own block, and the group is sized
around that block and then placed like any other node at its own level.

Pure functions over ids, sizes and edges; ops.py maps canvases onto them.
"""

from __future__ import annotations

from collections import defaultdict

GRID = 20
NODE_GAP = 40
RANK_GAP = 80
GROUP_PAD = 40
SWEEPS = 4
LANE = 40  # cross-axis room reserved for an edge passing through a layer


def snap(v: float) -> int:
    return int(round(v / GRID)) * GRID


def _break_cycles(ids: list[str], succ: dict[str, list[str]]) -> set[tuple[str, str]]:
    """Edges to reverse so the graph is acyclic (DFS back edges)."""
    state: dict[str, int] = {}
    back: set[tuple[str, str]] = set()
    for root in ids:
        if root in state:
            continue
        stack = [(root, iter(succ[root]))]
        state[root] = 1
        while stack:
            node, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                state[node] = 2
                stack.pop()
            elif state.get(nxt) == 1:
                back.add((node, nxt))
            elif nxt not in state:
                state[nxt] = 1
                stack.append((nxt, iter(succ[nxt])))
    return back


def _layers(ids: list[str], edges: list[tuple[str, str]]) -> dict[str, int]:
    succ: dict[str, list[str]] = defaultdict(list)
    for a, b in edges:
        succ[a].append(b)
    back = _break_cycles(ids, succ)
    dag = [(b, a) if (a, b) in back else (a, b) for a, b in edges]
    indeg = {i: 0 for i in ids}
    out: dict[str, list[str]] = defaultdict(list)
    for a, b in dag:
        out[a].append(b)
        indeg[b] += 1
    layer = {i: 0 for i in ids}
    ready = [i for i in ids if indeg[i] == 0]
    while ready:
        a = ready.pop(0)
        for b in out[a]:
            layer[b] = max(layer[b], layer[a] + 1)
            indeg[b] -= 1
            if indeg[b] == 0:
                ready.append(b)
    return layer


def _pav(values: list[float]) -> list[float]:
    """Closest non-decreasing sequence (least squares): pool adjacent violators."""
    blocks: list[list[float]] = []   # [sum, count]
    for v in values:
        blocks.append([v, 1])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
            s, c = blocks.pop()
            blocks[-1][0] += s
            blocks[-1][1] += c
    out: list[float] = []
    for s, c in blocks:
        out.extend([s / c] * c)
    return out


def _pack(order: list[str], cross: dict[str, float], want: dict[str, float]) -> None:
    """Place `order` along the cross axis, each as near its wanted centre as the
    gaps allow (least squares), in place."""
    offs, acc = [], 0.0
    for i, n in enumerate(order):
        if i:
            acc += cross[order[i - 1]] / 2 + NODE_GAP + cross[n] / 2
        offs.append(acc)
    fitted = _pav([want[n] - o for n, o in zip(order, offs)])
    for n, f, o in zip(order, fitted, offs):
        want[n] = f + o


def layered(ids: list[str], sizes: dict[str, tuple[int, int]], edges: list[tuple[str, str]],
            direction: str = "TB") -> tuple[dict[str, tuple[int, int]], tuple[int, int]]:
    """Top-left positions for `ids`, relative to the block's own top-left, and
    the block's (width, height)."""
    if not ids:
        return {}, (0, 0)
    tb = direction.upper() != "LR"
    idset = set(ids)
    pairs = list(dict.fromkeys((a, b) for a, b in edges if a in idset and b in idset and a != b))
    layer = _layers(ids, pairs)
    real = ids
    ids, sizes = list(ids), dict(sizes)
    chained: list[tuple[str, str]] = []
    for k, (a, b) in enumerate(pairs):
        lo, hi = (a, b) if layer[a] <= layer[b] else (b, a)
        prev = lo
        for li in range(layer[lo] + 1, layer[hi]):
            d = f"\0lane{k}:{li}"
            ids.append(d)
            layer[d] = li
            sizes[d] = (LANE, 0) if tb else (0, LANE)
            chained.append((prev, d))
            prev = d
        chained.append((prev, hi))
    pairs = chained
    nbrs_up: dict[str, list[str]] = defaultdict(list)
    nbrs_down: dict[str, list[str]] = defaultdict(list)
    for a, b in pairs:
        if layer[a] < layer[b]:
            nbrs_up[b].append(a)
            nbrs_down[a].append(b)
        elif layer[b] < layer[a]:
            nbrs_up[a].append(b)
            nbrs_down[b].append(a)

    rows: dict[int, list[str]] = defaultdict(list)
    for i in ids:
        rows[layer[i]].append(i)
    depth = max(rows) + 1
    pos = {n: float(k) for r in rows.values() for k, n in enumerate(r)}

    def frac(n: str) -> float:
        r = rows[layer[n]]
        return pos[n] / max(1, len(r) - 1) if len(r) > 1 else 0.5

    for sweep in range(SWEEPS):
        down = sweep % 2 == 0
        for li in (range(1, depth) if down else range(depth - 2, -1, -1)):
            row = rows[li]
            nb = nbrs_up if down else nbrs_down
            keys = {n: (sum(frac(m) for m in nb[n]) / len(nb[n]) if nb[n] else frac(n))
                    for n in row}
            row.sort(key=lambda n: (keys[n], pos[n]))
            for k, n in enumerate(row):
                pos[n] = float(k)

    cross = {n: float(sizes[n][0] if tb else sizes[n][1]) for n in ids}
    main = {n: float(sizes[n][1] if tb else sizes[n][0]) for n in ids}

    # Cross axis: centre each layer first, then pull nodes towards their neighbours.
    centre: dict[str, float] = {}
    for li in range(depth):
        row = rows[li]
        total = sum(cross[n] for n in row) + NODE_GAP * (len(row) - 1)
        x = -total / 2
        for n in row:
            centre[n] = x + cross[n] / 2
            x += cross[n] + NODE_GAP
    for _ in range(3):
        for li in list(range(depth)) + list(range(depth - 1, -1, -1)):
            row = rows[li]
            want = {}
            for n in row:
                nb = nbrs_up[n] + nbrs_down[n]
                want[n] = sum(centre[m] for m in nb) / len(nb) if nb else centre[n]
            _pack(row, cross, want)
            centre.update(want)

    # Main axis: bands of the tallest node in each layer.
    band_start, at = {}, 0.0
    for li in range(depth):
        band_start[li] = at
        at += max(main[n] for n in rows[li]) + RANK_GAP
    band = {li: max(main[n] for n in rows[li]) for li in range(depth)}

    raw: dict[str, tuple[float, float]] = {}
    for n in real:
        c = centre[n] - cross[n] / 2
        m = band_start[layer[n]] + (band[layer[n]] - main[n]) / 2
        raw[n] = (c, m) if tb else (m, c)
    minx = min(x for x, _ in raw.values())
    miny = min(y for _, y in raw.values())
    out = {n: (snap(x - minx), snap(y - miny)) for n, (x, y) in raw.items()}
    w = max(out[n][0] + sizes[n][0] for n in real)
    h = max(out[n][1] + sizes[n][1] for n in real)
    return out, (w, h)


def compound(top: list[str], children: dict[str, list[str]], sizes: dict[str, tuple[int, int]],
             edges: list[tuple[str, str]], direction: str = "TB"
             ) -> tuple[dict[str, tuple[int, int, int, int]], tuple[int, int]]:
    """Lay out `top` (some of which may be groups with `children`) as one block.

    Returns {id: (x, y, width, height)} relative to the block's top-left, for
    every id in the tree (groups get their fitted size), and the block size.
    """
    boxes: dict[str, tuple[int, int, int, int]] = {}
    size = dict(sizes)
    owner: dict[str, str] = {}

    def claim(root: str, n: str) -> None:
        for c in children.get(n, []):
            owner[c] = root
            claim(root, c)

    for t in top:
        owner[t] = t
        claim(t, t)

    inner: dict[str, dict[str, tuple[int, int, int, int]]] = {}
    for t in top:
        kids = children.get(t, [])
        if kids:
            sub, (w, h) = compound(kids, children, sizes, edges, direction)
            inner[t] = sub
            size[t] = (max(sizes[t][0], w + 2 * GROUP_PAD), max(sizes[t][1], h + 2 * GROUP_PAD))

    lifted = [(owner[a], owner[b]) for a, b in edges
              if a in owner and b in owner and owner[a] != owner[b]]
    pos, block = layered(top, size, lifted, direction)
    for t in top:
        x, y = pos[t]
        boxes[t] = (x, y, size[t][0], size[t][1])
        for k, (cx, cy, cw, ch) in inner.get(t, {}).items():
            boxes[k] = (x + GROUP_PAD + cx, y + GROUP_PAD + cy, cw, ch)
    return boxes, block
