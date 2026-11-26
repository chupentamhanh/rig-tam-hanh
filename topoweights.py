"""Weight theo lưới: tính weight thân theo cấu trúc lưới, không theo "toả nhiệt".

Automatic weights (heat) của Blender lan weight xuyên qua khe hở và sang mảnh
lưới rời -- đùi bên này ăn sang chân bên kia, vỏ bánh mì đi theo cánh tay --
vì nhiệt toả trong không gian. Ở đây:

1. ĐẢO LƯỚI: chia mesh thành các mảnh rời. Xương nằm TRONG một mảnh (đếm số lần
   tia cắt mặt của chính mảnh đó) là xương của mảnh; mảnh được dùng xương của
   nó cộng xương cha nơi nó bám vào (tay rời dùng được vai). Mảnh không chứa
   xương nào (vỏ, decal, nhãn cầu) chép weight từ chỗ gần nhất của mảnh có
   xương; mảnh nhỏ (< SMALL chiều cao) đi cứng theo một bộ weight.
2. HẠT GIỐNG: vertex mà xương của mảnh "nhìn thấy" (đoạn thẳng tới điểm gần
   nhất trên xương không cắt mặt của mảnh) và gần nhất trong số các xương nhìn
   thấy (sai không quá SEED_SLACK).
3. KHOẢNG CÁCH DỌC BỀ MẶT: D[v, xương] = min qua hạt giống s của (s -> xương) +
   (đường ngắn nhất theo cạnh lưới s -> v). Không đi xuyên khe.
4. WEIGHT = exp(-(D - Dmin) / (FALLOFF * Dmin)): Dmin là độ dày lưới ở vertex --
   chi to thì vùng chuyển rộng, ngón tay thì hẹp. Làm mượt dọc cạnh SMOOTH
   lượt, tối đa 4 xương, bỏ < 0.01, normalize.

Xương mặt (con cháu xương đầu) không tính: phần weight xương mặt của mỗi vertex
giữ nguyên, phần còn lại chia lại. Vertex vẽ tay giữ nguyên.
"""

import numpy as np
from mathutils import Vector, kdtree
from mathutils.bvhtree import BVHTree

from . import cloth, posekey

SEED_SLACK = 1.25
FALLOFF = 0.4
SMOOTH = 4
ROOT = 2.0             # khoảng cách tới xương gốc chi (Shoulder, Pelvis) nhân thêm
SMALL = 0.15            # mảnh không xương nhỏ hơn 15% chiều cao: đi cứng
MAX_INF = 4
MIN_W = 0.01


def _seg_dist(P, A, Bt):
    """Khoảng cách và điểm gần nhất từ mọi điểm P (n,3) tới mọi đoạn A->Bt (m,3)."""
    AB = Bt - A
    L2 = np.maximum((AB * AB).sum(1), 1e-12)
    AP = P[:, None, :] - A[None, :, :]
    t = np.clip((AP * AB[None]).sum(2) / L2[None], 0, 1)
    Q = A[None] + t[..., None] * AB[None]
    return np.linalg.norm(P[:, None, :] - Q, axis=2), Q


def _islands(n, edges):
    parent = np.arange(n)

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    return np.array([find(i) for i in range(n)])


def geodesic(n, edges, lengths, D0):
    """Khoảng cách theo cạnh lưới cho nhiều nguồn cùng lúc. D0 (n,m): khoảng cách
    khởi đầu (inf nếu không phải hạt giống). Trả về D (n,m)."""
    D = D0.copy()
    if not len(edges):
        return D
    src = np.concatenate([edges[:, 0], edges[:, 1]])
    dst = np.concatenate([edges[:, 1], edges[:, 0]])
    ln = np.concatenate([lengths, lengths])[:, None]
    for _ in range(4 * n):
        new = D.copy()
        np.minimum.at(new, dst, D[src] + ln)
        if np.array_equal(new, D):
            break
        D = new
    return D


_DIRS = (Vector((0.0, 0.0, 1.0)), Vector((0.577, 0.577, -0.577)), Vector((-0.6, 0.0, 0.8)))


def _inside(bvh, p, size):
    """p nằm trong mảnh kín? Đếm số lần tia cắt mặt theo 3 hướng, đa số lẻ."""
    odd = 0
    for d in _DIRS:
        o = Vector(p)
        hits = 0
        for _ in range(64):
            loc, _n, _i, dist = bvh.ray_cast(o, d, size * 4)
            if loc is None:
                break
            hits += 1
            o = loc + d * (size * 1e-5)
        odd += hits % 2
    return odd >= 2


def compute(body, rig, falloff=FALLOFF, smooth=SMOOTH, seed_slack=SEED_SLACK, root=ROOT,
            symmetric=True):
    """Weight theo lưới cho `body`. Trả về (tên xương, W (n,m), thông tin) chưa ghi
    vào mesh. Chỉ xương deform không phải xương mặt."""
    face = posekey.face_bones(rig) or set()
    bones = [b for b in rig.data.bones if b.use_deform and b.name not in face and b.length > 1e-5]
    names = [b.name for b in bones]
    col = {nm: j for j, nm in enumerate(names)}
    M = rig.matrix_world.inverted() @ body.matrix_world
    me = body.data
    n, m = len(me.vertices), len(bones)
    P = np.array([tuple(M @ v.co) for v in me.vertices])
    N = np.array([tuple((M.to_3x3() @ v.normal).normalized()) for v in me.vertices])
    A = np.array([tuple(b.head_local) for b in bones])
    Bt = np.array([tuple(b.tail_local) for b in bones])
    dE, Q = _seg_dist(P, A, Bt)
    size = float(np.ptp(P, axis=0).max() or 1.0)
    height = float(np.ptp(P[:, 2]) or size)
    eps = 1e-4 * size
    edges = np.array([tuple(e.vertices) for e in me.edges], dtype=np.int64).reshape(-1, 2)
    lengths = np.linalg.norm(P[edges[:, 0]] - P[edges[:, 1]], axis=1) if len(edges) else np.zeros(0)
    isl = _islands(n, edges)
    vert_poly = [tuple(p.vertices) for p in me.polygons]

    # 1. đảo lưới và xương của từng đảo
    info = {"islands": []}
    cand = {}                       # đảo -> mảng bool (m,) xương được dùng
    bvhs = {}
    samples = [A + (Bt - A) * t for t in (0.2, 0.4, 0.6, 0.8)]
    for r in np.unique(isl):
        idx = np.nonzero(isl == r)[0]
        local = {int(v): k for k, v in enumerate(idx)}
        polys = [tuple(local[v] for v in p) for p in vert_poly if p[0] in local]
        if not polys:
            continue
        bvh = BVHTree.FromPolygons([tuple(P[i]) for i in idx], polys, epsilon=0.0)
        lo, hi = P[idx].min(0), P[idx].max(0)
        mask = np.zeros(m, dtype=bool)
        for j in range(m):
            pts = [s[j] for s in samples]
            if not any((lo - eps <= p).all() and (p <= hi + eps).all() for p in pts):
                continue
            if sum(_inside(bvh, p, size) for p in pts) >= 2:
                mask[j] = True
        own = [names[j] for j in np.nonzero(mask)[0]]
        for nm in own:                                  # + xương cha nơi mảnh bám vào
            par = rig.data.bones[nm].parent
            while par is not None and (par.name not in col):
                par = par.parent
            if par is not None:
                mask[col[par.name]] = True
        cand[r] = mask
        bvhs[r] = bvh
        info["islands"].append((len(idx), own))

    # 2. hạt giống: xương của đảo nhìn thấy vertex (chỉ mặt của chính đảo đó che)
    D0 = np.full((n, m), np.inf)
    for i in range(n):
        r = isl[i]
        mask = cand.get(r)
        if mask is None or not mask.any():
            continue
        js = np.nonzero(mask)[0]
        js = js[np.argsort(dE[i, js])]
        o = P[i] - N[i] * eps
        best = None
        for j in js[:8]:
            if best is not None and dE[i, j] > best * seed_slack + eps:
                break
            d = Q[i, j] - o
            L = float(np.linalg.norm(d))
            if L < eps or bvhs[r].ray_cast(tuple(o), tuple(d / L), L - eps)[0] is None:
                D0[i, j] = dE[i, j]
                if best is None:
                    best = dE[i, j]
        if best is None:                                # không xương nào nhìn thấy: gần nhất
            D0[i, js[0]] = dE[i, js[0]]

    # 3. khoảng cách dọc bề mặt (chỉ trong đảo: không có cạnh nối đảo)
    D = geodesic(n, edges, lengths, D0)
    if root != 1.0:
        from .weightfence import Layout
        roots = {b for rs in Layout(rig).roots.values() for b in rs}
        for nm in roots & set(col):
            D[:, col[nm]] *= root

    # 4. weight theo độ dày, làm mượt dọc cạnh
    Dm = D.min(1, keepdims=True)
    ok = np.isfinite(Dm[:, 0])
    r_ = np.maximum(np.where(ok[:, None], Dm, 1.0), eps * 10)
    W = np.where(np.isfinite(D), np.exp(-(D - np.where(ok[:, None], Dm, 0)) / (falloff * r_)), 0.0)
    W[W < 1e-3] = 0
    W /= np.maximum(W.sum(1, keepdims=True), 1e-12)
    if smooth and len(edges):
        deg = np.bincount(edges.ravel(), minlength=n).astype(float)[:, None]
        for _ in range(smooth):
            acc = np.zeros_like(W)
            np.add.at(acc, edges[:, 0], W[edges[:, 1]])
            np.add.at(acc, edges[:, 1], W[edges[:, 0]])
            W = np.where(deg > 0, 0.5 * W + 0.5 * acc / np.maximum(deg, 1), W)

    # 5. đảo không xương: chép từ chỗ gần nhất của đảo có xương
    src = np.nonzero(ok)[0]
    if len(src) and not ok.all():
        kd = kdtree.KDTree(len(src))
        for k, i in enumerate(src):
            kd.insert(P[i], k)
        kd.balance()
        for r in np.unique(isl[~ok]):
            idx = np.nonzero((isl == r) & ~ok)[0]
            rows = np.array([W[src[kd.find(P[i])[1]]] for i in idx])
            if np.ptp(P[idx], axis=0).max() < SMALL * height:
                rows[:] = rows.mean(0)                  # mảnh nhỏ: đi cứng
            W[idx] = rows

    # 6. đối xứng: cặp vertex gương (qua x = 0 của rig) lấy trung bình, đổi .L <-> .R
    if symmetric:
        W = _symmetrize(P, W, names, height)

    # tối đa 4 xương, bỏ vụn, normalize
    if m > MAX_INF:                                     # đúng 4 xương nặng nhất (kể cả khi bằng nhau)
        top = np.argsort(-W, axis=1, kind='stable')[:, :MAX_INF]
        keep = np.zeros_like(W, dtype=bool)
        np.put_along_axis(keep, top, True, axis=1)
        W = np.where(keep, W, 0)
    W[W < MIN_W] = 0
    W /= np.maximum(W.sum(1, keepdims=True), 1e-12)
    return names, W, info


def _mirror_name(nm):
    for a, b in (('.L', '.R'), ('.R', '.L'), ('_L', '_R'), ('_R', '_L')):
        if a in nm:
            return nm.replace(a, b, 1)
    return nm


def _symmetrize(P, W, names, height, tol=0.002):
    """Vertex có ảnh gương (trong tol * chiều cao): weight = trung bình của nó và
    ảnh gương đã đổi bên. Mesh không đối xứng thì chỉ đụng chỗ đối xứng."""
    col = {nm: j for j, nm in enumerate(names)}
    perm = np.array([col.get(_mirror_name(nm), j) for j, nm in enumerate(names)])
    kd = kdtree.KDTree(len(P))
    for i, p in enumerate(P):
        kd.insert(p, i)
    kd.balance()
    out = W.copy()
    lim = tol * height
    for i, p in enumerate(P):
        _co, j, d = kd.find((-p[0], p[1], p[2]))
        if j is None or d > lim:
            continue
        out[i] = 0.5 * (W[i] + W[j][perm])
    return out


def apply(body, rig, names, W, keep=()):
    """Ghi W vào mesh. Phần weight xương mặt của mỗi vertex giữ nguyên (W co lại
    cho vừa phần còn lại). Trả về số vertex đổi."""
    face = posekey.face_bones(rig) or set()
    vg = body.vertex_groups
    deform = {b.name for b in rig.data.bones if b.use_deform}
    groups = {nm: (vg.get(nm) or vg.new(name=nm)) for nm in names}
    changed = 0
    for v in body.data.vertices:
        i = v.index
        if i in keep:
            continue
        fs = min(sum(g.weight for g in v.groups if vg[g.group].name in face), 1.0)
        for g in list(v.groups):
            nm = vg[g.group].name
            if nm in deform and nm not in face:
                vg[g.group].remove([i])
        for j in np.nonzero(W[i] > 0)[0]:
            groups[names[j]].add([i], float(W[i, j] * (1 - fs)), 'REPLACE')
        changed += 1
    return changed


def rebuild(body, rig, **kw):
    """Tính và ghi. Vertex vẽ tay giữ nguyên. Trả về (số vertex đổi, thông tin)."""
    keep = cloth.hand_painted(body)
    names, W, info = compute(body, rig, **kw)
    return apply(body, rig, names, W, keep), info
