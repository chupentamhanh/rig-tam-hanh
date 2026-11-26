"""Chép weight từ nhân vật mẫu đã tô tay -- kiểu Mixamo.

Mixamo không công bố công thức; bằng sáng chế của họ (US 8,797,328) mô tả: khớp
bộ xương mẫu vào nhân vật, rồi lấy weight từ "skinning template" làm từ các
nhân vật đã tô weight bằng tay. Hai cách ở đây, đều lấy mẫu là "Rig mẫu / Mesh
mẫu" ở bước dựng ref (nhân vật đã rig trong cùng file):

1. THEO XƯƠNG (`by_bone`): không cần hai lưới giống nhau. Mỗi vertex được gán
   cho một xương chính (theo weight tính theo lưới, topoweights). Vị trí của nó
   trong hệ toạ độ của xương đó: t = đi dọc xương (0 ở đầu, 1 ở đuôi), góc quanh
   trục xương. Vertex mẫu có cùng xương chính và (t, góc) gần nhất cho weight
   (trung bình 4 điểm gần nhất theo nghịch đảo khoảng cách). Xương mà mẫu không
   có (đuôi, tai, cánh...) giữ weight theo lưới.
2. UỐN LƯỚI MẪU (`by_fit`): cơ chế fitref có sẵn -- uốn lưới mẫu bằng rig mẫu
   cho áp lên lưới mới rồi chép weight điểm gần nhất. Hợp nhân vật cùng dáng.

Xương mặt của mẫu bị bỏ (phần weight xương mặt của nhân vật mới giữ nguyên).
"""

import math

import numpy as np
from mathutils import Matrix, Vector, kdtree

from . import cloth, posekey, topoweights as TW

K = 4                   # số vertex mẫu lấy trung bình
ANGLE = 0.35            # trọng số của góc quanh xương so với vị trí dọc xương
SMOOTH = 2


def template(context):
    """(rig mẫu, mesh mẫu) đang chọn ở bước dựng ref, hoặc (None, None)."""
    st = getattr(context.scene, "srp_generate", None)
    if st is None or st.template_rig is None or st.template_mesh is None:
        return None, None
    if not cloth.deformed_by(st.template_mesh, st.template_rig):
        return None, None
    return st.template_rig, st.template_mesh


def _frames(rig, names):
    B = rig.data.bones
    return {n: (B[n].matrix_local.inverted(), max(B[n].length, 1e-6)) for n in names if n in B}


def _feat(inv_len, p):
    inv, ln = inv_len
    q = inv @ p
    t = q.y / ln
    a = math.atan2(q.z, q.x)
    return (t, ANGLE * math.cos(a), ANGLE * math.sin(a))


def _rest(ob, rig):
    M = rig.matrix_world.inverted() @ ob.matrix_world
    return [M @ v.co for v in ob.data.vertices]


def by_bone(body, rig, trig, tmesh):
    """Weight mẫu theo xương. Trả về (tên xương, W (n,m), số vertex lấy từ mẫu)."""
    names, W, info = TW.compute(body, rig)
    col = {n: j for j, n in enumerate(names)}
    face_t = posekey.face_bones(trig) or set()
    deform_t = {b.name for b in trig.data.bones if b.use_deform and b.name not in face_t}
    Bt = trig.data.bones

    def rename(n):                                  # xương mẫu -> xương của rig mới
        b = Bt.get(n)
        while b is not None and b.name not in col:
            b = b.parent
        return b.name if b is not None else None

    # vertex mẫu: xương chính + đặc trưng + weight (đã đổi tên, bỏ xương mặt)
    vg = tmesh.vertex_groups
    Pt = _rest(tmesh, trig)
    fr_t = _frames(trig, deform_t)
    lib = {}
    for v, p in zip(tmesh.data.vertices, Pt):
        raw = {vg[g.group].name: g.weight for g in v.groups if vg[g.group].name in deform_t}
        if not raw:
            continue
        dom = max(raw, key=raw.get)
        row = np.zeros(len(names))
        for n, w in raw.items():
            m = rename(n)
            if m is not None:
                row[col[m]] += w
        s = row.sum()
        if s <= 0 or dom not in fr_t:
            continue
        lib.setdefault(dom, ([], []))
        lib[dom][0].append(_feat(fr_t[dom], p))
        lib[dom][1].append(row / s)
    trees = {}
    for b, (F, R) in lib.items():
        if len(F) < K:
            continue
        kd = kdtree.KDTree(len(F))
        for i, f in enumerate(F):
            kd.insert(f, i)
        kd.balance()
        trees[b] = (kd, np.array(R))

    # vertex mới: xương chính theo lưới, tra mẫu của đúng xương đó
    P = _rest(body, rig)
    fr = _frames(rig, names)
    dom = W.argmax(1)
    out = W.copy()
    used = np.zeros(len(P), dtype=bool)
    boneless = info["boneless"]
    for i, p in enumerate(P):
        b = names[dom[i]]
        if boneless[i] or b not in trees:
            continue
        kd, R = trees[b]
        hits = kd.find_n(_feat(fr[b], p), K)
        w = np.array([1.0 / max(d, 1e-4) for _c, _j, d in hits])
        out[i] = (w[:, None] * R[[j for _c, j, _d in hits]]).sum(0) / w.sum()
        used[i] = True

    # làm mượt dọc cạnh, đối xứng, tối đa 4 xương
    me = body.data
    edges = np.array([tuple(e.vertices) for e in me.edges], dtype=np.int64).reshape(-1, 2)
    if SMOOTH and len(edges):
        deg = np.bincount(edges.ravel(), minlength=len(P)).astype(float)[:, None]
        for _ in range(SMOOTH):
            acc = np.zeros_like(out)
            np.add.at(acc, edges[:, 0], out[edges[:, 1]])
            np.add.at(acc, edges[:, 1], out[edges[:, 0]])
            out = np.where(deg > 0, 0.5 * out + 0.5 * acc / np.maximum(deg, 1), out)
    Pa = np.array([tuple(p) for p in P])
    height = float(np.ptp(Pa[:, 2]) or 1.0)
    # đảo không xương (lông mày, decal, nhãn cầu) đi theo lớp da ngay dưới -- da
    # vừa đổi weight theo mẫu, không chép lại thì nó tách khỏi da khi pose
    out = TW.attach_boneless(Pa, out, info["islands_of"], boneless, height)
    out = TW._symmetrize(Pa, out, names, height)
    out = TW.limit(out)
    return names, out, int(used.sum())


def rebuild_by_bone(context, body, rig):
    trig, tmesh = template(context)
    if trig is None or tmesh is body:
        raise LookupError("chưa chọn nhân vật mẫu")
    names, W, n = by_bone(body, rig, trig, tmesh)
    TW.apply(body, rig, names, W, keep=cloth.hand_painted(body))
    return n


def rebuild_by_fit(context, body, rig):
    from . import fitref
    trig, tmesh = template(context)
    if trig is None or tmesh is body:
        raise LookupError("chưa chọn nhân vật mẫu")
    # fitref khớp trong toạ độ world: mẫu phải chồng lên nhân vật. Tạm dời rig mẫu
    # cho đáy-tâm hộp bao hai lưới trùng nhau (mẫu đặt cạnh nhân vật vẫn dùng được).
    def foot(ob):
        pts = [ob.matrix_world @ Vector(c) for c in ob.bound_box]
        return Vector(((min(p.x for p in pts) + max(p.x for p in pts)) / 2,
                       (min(p.y for p in pts) + max(p.y for p in pts)) / 2,
                       min(p.z for p in pts)))
    old = trig.matrix_world.copy()
    trig.matrix_world = Matrix.Translation(foot(body) - foot(tmesh)) @ old
    context.view_layer.update()
    try:
        fit, _mean, _worst = fitref.solve(trig, tmesh, body)
        n, _far = fitref.copy_weights(fit, tmesh, body, rig)
    finally:
        trig.matrix_world = old
        context.view_layer.update()
    return n
