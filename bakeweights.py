"""Tối ưu weight thân bằng cách NƯỚNG từ Delta Mush.

Cho rig qua ~40 tư thế, lấy hình dạng mà Delta Mush (modifier Corrective
Smooth) cho ra -- mượt, giữ thể tích hơn LBS -- rồi với từng vertex giải bình
phương tối thiểu tìm weight LBS (không âm, tổng 1, tối đa 4 hoặc 8 xương) bám
gần hình đó nhất. Kết quả vẫn là weight thường: Unity chạy được.

Đo trên Adult (đáp án = weight người dùng vẽ tay, 8 tư thế thử tay/chân trái):
lệch so với tay vẽ ở vai/nách 10.4 -> 7.9 mm, hông/mông 19.2 -> 15.6 mm (đuôi
p95 100 -> 54 mm), vùng người dùng đã sửa 6.4 -> 5.1 mm; chỉ 4 xương mà vẫn
sát bản tay vẽ 8 xương.

Tư thế tính THẲNG bằng ma trận (xoay quanh đầu xương, lan xuống cây xương
deform) -- không pose rig thật, không đụng constraint / FK-IK.
"""

import math

import bpy
import numpy as np
from mathutils import Matrix

from . import cloth, rigdef

DM_ITER = 20            # vòng Corrective Smooth; 12 vòng thì hông còn lệch hơn (p95 62 -> 51 mm)
DM_FACTOR = 0.5
LAM = 10.0              # trọng số ràng buộc tổng weight = 1
MU = 3e-3               # kéo về weight cũ / trung bình hàng xóm
ALPHA = 0.6             # phần trung bình hàng xóm trong mức kéo về (lượt 2+)
SWEEPS = 3
ROBUST = 0.12           # co giãn của đích Delta Mush tại vertex: cỡ này thì đích tính nhẹ đi một nửa
CULL = 0.04             # xương chi xa hơn đoạn xương gần nhất quá 4% chiều cao thì loại
CAP = 100               # gập gối/khuỷu trong tập học tối đa 100°: gập sâu hơn Delta Mush tự gập lưới
CAND = 10
# Nướng làm vùng chuyển Thigh -> Shin quá gắt (vertex cách khớp 1.6 cm đã 97%
# một xương): gập 130° khoeo bật ra một mẩu lưới. Làm mượt cục bộ quanh gối
# (KHÔNG quanh khuỷu: thử rồi, lưới méo ở khuỷu 19% -> 30%).
KNEE_R = 0.045
KNEE_PASSES = 8
KNEE_REACH = 0.09


def _nnls(A, b, iters=60):
    """Bình phương tối thiểu không âm (Lawson-Hanson). Blender không kèm scipy."""
    n = A.shape[1]
    x = np.zeros(n)
    on = np.zeros(n, bool)
    w = A.T @ (b - A @ x)
    for _ in range(iters):
        if on.all() or (w[~on] <= 1e-12).all():
            break
        on[np.argmax(np.where(on, -np.inf, w))] = True
        while True:
            z = np.zeros(n)
            z[on] = np.linalg.lstsq(A[:, on], b, rcond=None)[0]
            if (z[on] > 0).all():
                x = z
                break
            m = on & (z <= 0)
            x = x + np.min(x[m] / np.maximum(x[m] - z[m], 1e-12)) * (z - x)
            on &= x > 1e-12
        w = A.T @ (b - A @ x)
    return x


def training_poses(rig):
    """[[(xương deform, trục world, độ)]] -- tay, chân hai bên, lưng, cổ."""
    from . import posekey
    B = rig.data.bones
    out = []
    for l in rigdef.limbs_for(rig):
        up, low = l.deform[0], l.deform[1]
        if up not in B or low not in B:
            continue
        sg = 1 if l.side == 'L' else -1
        if l.kind == 'ARM':
            ops = [[(up, 'Y', 75)], [(up, 'Y', 40)], [(up, 'Y', -60)], [(up, 'Z', 70)], [(up, 'Z', -40)],
                   [(low, 'Z', -60)], [(low, 'Z', -CAP)], [(up, 'Y', 75), (low, 'Z', -90)]]
            sh = B[up].parent
            if sh is not None and sh.use_deform:
                ops += [[(sh.name, 'Y', -20)], [(sh.name, 'Z', 20)]]
            out += [[(n, ax, d * (sg if ax != 'X' else 1)) for n, ax, d in p] for p in ops]
        elif l.kind == 'LEG':
            ops = [[(up, 'X', -45)], [(up, 'X', -90)], [(up, 'X', 35)], [(up, 'Y', 30)],
                   [(low, 'X', 60)], [(low, 'X', CAP)], [(up, 'X', -90), (low, 'X', CAP)]]
            out += [[(n, ax, d * (sg if ax != 'X' else 1)) for n, ax, d in p] for p in ops]
    head = posekey.head_bone(rig)
    if head is not None:
        chain = []
        b = head.parent
        while b is not None:
            if b.use_deform:
                chain.insert(0, b.name)
            b = b.parent
        if len(chain) >= 3:
            out += [[(chain[1], 'X', 25)], [(chain[1], 'Z', 25)], [(chain[2], 'Y', 20)]]
        if chain:
            out.append([(chain[-1], 'X', 20)])
        out.append([(head.name, 'Z', 35)])
    return out


def skin_mats(rig, deform, ops):
    """Ma trận skin (hệ armature) của từng xương deform cho một tư thế."""
    B = rig.data.bones
    S = {n: np.eye(4) for n in deform}
    for name, axis, deg in ops:
        b = B[name]
        sub = [b.name] + [c.name for c in b.children_recursive]
        h = np.array(tuple(b.head_local) + (1.0,))
        if name in S:
            h = S[name] @ h
        R = np.array(Matrix.Rotation(math.radians(deg), 4, axis))
        T = np.eye(4); T[:3, 3] = h[:3]
        Ti = np.eye(4); Ti[:3, 3] = -h[:3]
        M = T @ R @ Ti
        for n in sub:
            if n in S:
                S[n] = M @ S[n]
    return np.stack([S[n] for n in deform])


def _targets(context, body, rig, deform, W0, V0, poses):
    """Hình Delta Mush của thân (weight W0) ở từng tư thế, hệ armature."""
    me = bpy.data.meshes.new("SRP_bake_tmp")
    me.from_pydata(V0.tolist(), [], [tuple(p.vertices) for p in body.data.polygons])
    ob = bpy.data.objects.new("SRP_bake_tmp", me)
    context.scene.collection.objects.link(ob)
    try:
        ob.shape_key_add(name="Basis")
        key = ob.shape_key_add(name="pose")
        key.value = 1.0
        cs = ob.modifiers.new("DM", 'CORRECTIVE_SMOOTH')
        cs.smooth_type = 'LENGTH_WEIGHTED'
        cs.iterations = DM_ITER
        cs.factor = DM_FACTOR
        cs.rest_source = 'ORCO'
        Vh = np.hstack([V0, np.ones((len(V0), 1))])
        Ss, Ts = [], []
        for ops in poses:
            S = skin_mats(rig, deform, ops)
            P = np.einsum('vj,jab,vb->va', W0, S[:, :3, :], Vh)
            key.data.foreach_set("co", P.ravel())
            ob.data.update()
            dg = context.evaluated_depsgraph_get()
            ev = ob.evaluated_get(dg)
            em = ev.to_mesh()
            T = np.empty(len(V0) * 3)
            em.vertices.foreach_get("co", T)
            ev.to_mesh_clear()
            Ss.append(S)
            Ts.append(T.reshape(-1, 3))
        return Ss, Ts
    finally:
        bpy.data.objects.remove(ob, do_unlink=True)
        bpy.data.meshes.remove(me)


def bake(context, body, rig, limit=4, keep=()):
    """Weight mới cho `body` (np n x xương deform). `keep`: vertex giữ nguyên.
    Trả về (danh sách xương, W mới, W cũ)."""
    B = rig.data.bones
    deform = [b.name for b in B if b.use_deform]
    DI = {n: i for i, n in enumerate(deform)}
    R2 = rig.matrix_world.inverted() @ body.matrix_world
    V0 = np.array([tuple(R2 @ v.co) for v in body.data.vertices])
    n = len(V0)
    gi = {g.index: g.name for g in body.vertex_groups}
    W0 = np.zeros((n, len(deform)))
    for v in body.data.vertices:
        for g in v.groups:
            nm = gi[g.group]
            if nm in DI and g.weight > 0:
                W0[v.index, DI[nm]] += g.weight
    s = W0.sum(1, keepdims=True)
    s[s < 1e-9] = 1
    W0 = W0 / s
    H = V0[:, 2].max() - V0[:, 2].min()
    E = np.array([tuple(e.vertices) for e in body.data.edges], dtype=int).reshape(-1, 2)

    poses = training_poses(rig)
    Ss, Ts = _targets(context, body, rig, deform, W0, V0, poses)
    Sst = np.stack(Ss)[:, :, :3, :]
    Tt = np.stack(Ts, axis=1)
    Vh = np.hstack([V0, np.ones((n, 1))])

    L0 = np.linalg.norm(V0[E[:, 0]] - V0[E[:, 1]], axis=1)
    cnt = np.zeros(n)
    np.add.at(cnt, E[:, 0], 1)
    np.add.at(cnt, E[:, 1], 1)
    cnt[cnt == 0] = 1
    RW = np.ones((n, len(Ts)))
    for k, T in enumerate(Ts):
        L = np.linalg.norm(T[E[:, 0]] - T[E[:, 1]], axis=1)
        st = np.zeros(n)
        np.add.at(st, E[:, 0], np.abs(L / np.maximum(L0, 1e-9) - 1))
        np.add.at(st, E[:, 1], np.abs(L / np.maximum(L0, 1e-9) - 1))
        RW[:, k] = 1.0 / (1.0 + (st / cnt / ROBUST) ** 2)

    nbr = [[] for _ in range(n)]
    for u, v in E:
        nbr[u].append(v)
        nbr[v].append(u)
    limb = {}
    for l in rigdef.limbs_for(rig):
        for nm in l.deform:
            if nm in DI:
                limb[DI[nm]] = (np.array(B[nm].head_local), np.array(B[nm].tail_local))

    def segd(p, ab):
        a, b = ab
        t = np.clip(np.dot(p - a, b - a) / max(np.dot(b - a, b - a), 1e-12), 0, 1)
        return np.linalg.norm(p - (a + (b - a) * t))

    keep = set(keep)
    W = W0.copy()
    for sweep in range(SWEEPS):
        if sweep == 0:
            prior = W0
        else:
            nb = np.zeros_like(W)
            np.add.at(nb, E[:, 0], W[E[:, 1]])
            np.add.at(nb, E[:, 1], W[E[:, 0]])
            prior = (1 - ALPHA) * W0 + ALPHA * nb / cnt[:, None]
        Wn = W.copy()
        for i in range(n):
            if i in keep:
                continue
            cand = set(np.nonzero(W0[i] > 1e-3)[0])
            for j in nbr[i]:
                cand |= set(np.nonzero(W0[j] > 0.05)[0])
            cand = sorted(cand, key=lambda c: -W0[i, c] - 0.01 * sum(W0[j, c] for j in nbr[i]))[:CAND]
            lc = [c for c in cand if c in limb]
            if len(lc) > 1:
                d = {c: segd(V0[i], limb[c]) for c in lc}
                dm = min(d.values())
                cand = [c for c in cand if c not in limb or d[c] - dm <= CULL * H]
            if len(cand) < 2:
                continue
            Xi = Sst[:, cand] @ Vh[i]
            r = np.repeat(RW[i], 3)
            A = np.vstack([Xi.transpose(0, 2, 1).reshape(-1, len(cand)) * r[:, None],
                           LAM * np.ones((1, len(cand))), MU * np.eye(len(cand))])
            b = np.concatenate([Tt[i].reshape(-1) * r, [LAM], MU * prior[i, cand]])
            x = _nnls(A, b)
            if (x > 1e-6).sum() > limit:
                top = np.argsort(-x)[:limit]
                x2 = np.zeros_like(x)
                x2[top] = _nnls(A[:, top], b)
                x = x2
            row = np.zeros(len(deform))
            row[cand] = x
            Wn[i] = row
        W = Wn

    # làm mượt cục bộ quanh gối
    zone = np.zeros(n)
    for l in rigdef.limbs_for(rig):
        if l.kind != 'LEG' or l.deform[0] not in B or l.deform[1] not in B:
            continue
        J = np.array(B[l.deform[1]].head_local)
        ax = np.array(B[l.deform[0]].tail_local) - np.array(B[l.deform[0]].head_local)
        ax /= max(np.linalg.norm(ax), 1e-9)
        d = V0 - J
        s_ = d @ ax
        rad = np.linalg.norm(d - np.outer(s_, ax), axis=1)
        f = np.where((np.abs(s_) < KNEE_R * H) & (rad < KNEE_REACH * H), 1.0 - np.abs(s_) / (KNEE_R * H), 0.0)
        zone = np.maximum(zone, np.clip(2 * f, 0, 1))
    if keep:
        zone[list(keep)] = 0
    Lw = 1.0 / np.maximum(L0, 1e-5)
    deg = np.zeros(n)
    np.add.at(deg, E[:, 0], Lw)
    np.add.at(deg, E[:, 1], Lw)
    for _ in range(KNEE_PASSES):
        acc = np.zeros_like(W)
        np.add.at(acc, E[:, 0], W[E[:, 1]] * Lw[:, None])
        np.add.at(acc, E[:, 1], W[E[:, 0]] * Lw[:, None])
        W = W + (acc / np.maximum(deg, 1e-9)[:, None] - W) * (0.5 * zone)[:, None]

    W = np.clip(W, 0, None)
    if W.shape[1] > limit:
        idx = np.argsort(-W, axis=1)[:, limit:]
        np.put_along_axis(W, idx, 0.0, axis=1)
    s = W.sum(1, keepdims=True)
    s[s < 1e-9] = 1
    return deform, W / s, W0


def write(body, deform, W, W0, keep=()):
    """Ghi W vào nhóm vertex của thân, chỉ những vertex đổi. Trả về số vertex."""
    keep = set(keep)
    names = set(deform)
    changed = 0
    for i in range(len(W)):
        if i in keep or np.abs(W[i] - W0[i]).max() < 1e-4:
            continue
        v = body.data.vertices[i]
        for g in list(v.groups):
            if body.vertex_groups[g.group].name in names:
                body.vertex_groups[g.group].remove([i])
        for j in np.nonzero(W[i] > 1e-4)[0]:
            grp = body.vertex_groups.get(deform[j]) or body.vertex_groups.new(name=deform[j])
            grp.add([i], float(W[i, j]), 'REPLACE')
        changed += 1
    return changed


class SRP_OT_bake_weights(bpy.types.Operator):
    """Tối ưu weight thân: cho rig qua ~40 tư thế, tìm weight thường (LBS) bám
    sát hình Delta Mush -- vai, nách, mông, khuỷu mượt hơn, ít phải vẽ tay.
    Vertex vẽ tay giữ nguyên. Chạy sau Bind, trước khi chỉnh tay"""
    bl_idname = "srp.bake_weights"
    bl_label = "Tối ưu weight (Delta Mush)"
    bl_options = {'REGISTER', 'UNDO'}

    limit4: bpy.props.BoolProperty(
        name="Tối đa 4 xương / vertex", default=True,
        description="Unity mặc định chỉ dùng 4 xương mỗi vertex. Tắt: tối đa 8")

    @classmethod
    def poll(cls, context):
        return rigdef.active_rig(context) is not None

    def execute(self, context):
        rig, body = cloth._body_rig(context)
        if body is None or not cloth.deformed_by(body, rig):
            self.report({'ERROR'}, "Chưa có mesh thân skin vào rig")
            return {'CANCELLED'}
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        keep = cloth.hand_painted(body)
        deform, W, W0 = bake(context, body, rig, limit=4 if self.limit4 else 8, keep=keep)
        n = write(body, deform, W, W0, keep)
        cloth._forget_skin(body, range(len(W)))
        body[cloth.STAMP_KEY] = body.get(cloth.STAMP_KEY, 0) + 1   # quần áo cần cập nhật
        context.view_layer.objects.active = rig
        msg = "%s: tối ưu weight %d vertex" % (body.name, n)
        if keep:
            msg += ", giữ %d vertex vẽ tay" % len(keep)
        msg += " | bấm 'Cập nhật weight từ thân' cho quần áo"
        self.report({'INFO'}, msg)
        return {'FINISHED'}


CLASSES = (SRP_OT_bake_weights,)
