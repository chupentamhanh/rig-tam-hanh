"""Lấy một nhân vật ĐÃ RIG làm mẫu cho nhân vật mới.

Bộ ref mặc định (`refrig.PARTS`) đặt xương theo tỉ lệ chiều cao -- người dùng
vẫn phải kéo từng khớp, và weight thì automatic weights làm lại từ đầu. Nhân
vật cùng studio thường cùng phong cách (Kid và Adult chung đầu, chung bàn tay,
khác chiều dài chân, thân, tay), nên cách người ta ĐÃ đặt khớp và ĐÃ tô weight
trên nhân vật cũ là dữ liệu mặc định tốt hơn mọi bảng tỉ lệ.

Cách làm: uốn chính lưới mẫu bằng chính rig mẫu cho áp lên lưới mới.
- Mỗi xương (xương mặt dồn về Head, trừ Jaw) có một phép biến đổi affine T_b.
  Lưới mẫu biến dạng kiểu LBS: x = Σ w_b · T_b(p), w là weight mẫu.
- Lặp ICP: điểm gần nhất trên lưới mới (chiều xuôi) + vertex lưới mới kéo vertex
  mẫu gần nhất (chiều ngược, để tay/chân dài hơn vẫn được kéo ra tới đầu), cộng
  ràng buộc khớp: xương con và xương cha phải đưa khớp chung về cùng một chỗ --
  nhờ vậy bộ xương không rời ra từng khúc. Mỗi vòng là một bài bình phương tối
  thiểu tuyến tính, x/y/z tách rời nên giải rất nhanh.
- Khớp mới = T áp lên khớp mẫu; roll = trục Z mẫu qua phần tuyến tính của T.
- Weight: lưới mẫu đã uốn nằm trên lưới mới, mỗi vertex mới lấy weight của điểm
  gần nhất trên lưới mẫu đã uốn (nội suy tam giác, cùng đảo lưới).

Đo trên Kid -> Adult (cao 1.52 -> 1.98 m, đầu giữ nguyên): lệch bề mặt trung
bình 1.3 mm sau 60 vòng (~20 s); khớp Head dịch đúng 0.457 m như lưới.
"""

import math
import time

import bpy
import numpy as np
from bpy.props import BoolProperty
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree
from mathutils.interpolate import poly_3d_calc
from mathutils.kdtree import KDTree

from . import cloth, posekey, refrig, refsync, rigdef

FIT_KEY = "srp_fit"
ITERS = 60
JOINT_W = 20.0          # ràng buộc khớp cha/con
REVERSE_W = 1.0         # chiều ngược: vertex lưới mới kéo vertex mẫu
MAX_SAMPLES = 6000      # lưới lớn hơn thì lấy mẫu đều, đủ để định khớp
PAIR_TOL = 0.006        # mesh phụ (lông mày) khớp mẫu nếu lệch < 0.6% chiều cao


# ============================================================ khớp lưới

def _fit_bone_map(rig):
    """{xương deform mẫu: xương dùng để khớp}. Xương mặt đi theo Head, trừ Jaw:
    đầu là một khối. Đã thử cho mỗi xương mí/môi tự khớp: lệch bề mặt TB tăng
    1.3 -> 2.4 mm, chậm gấp đôi, mí vẫn chép sai -- chỗ sai nằm ở bước chép
    weight, xem `refine`."""
    head = posekey.head_bone(rig)
    face = {c.name for c in head.children_recursive} if head else set()
    out = {}
    for b in rig.data.bones:
        if b.use_deform:
            out[b.name] = head.name if (b.name in face and b.name != "Jaw") else b.name
    return out


def _world(obj):
    """matrix_world tự tính, rig ở rest. Nhân vật mẫu hay nằm trong collection
    đã tắt khỏi view layer (chỉ để tham khảo) -- object con của nó không được
    evaluate, matrix_world có thể là đồ cũ hoặc ma trận đơn vị."""
    if obj.parent is None:
        return obj.matrix_basis.copy()
    m = _world(obj.parent)
    if obj.parent_type == 'BONE' and obj.parent.type == 'ARMATURE':
        b = obj.parent.data.bones.get(obj.parent_bone)
        if b is not None:
            m = m @ b.matrix_local @ Matrix.Translation((0.0, b.length, 0.0))
    return m @ obj.matrix_parent_inverse @ obj.matrix_basis


def _rows(obj, deform):
    return cloth.skin_rows(obj, deform)


def _stride(n):
    return max(1, int(math.ceil(n / MAX_SAMPLES)))


class Fit:
    """Kết quả khớp: T_b (4x3, nhân vector hàng [x y z 1]) cho từng xương khớp,
    trong hệ toạ độ của rig mẫu."""

    def __init__(self, rig, names, T, fmap):
        self.rig = rig
        self.names = list(names)
        self.index = {n: i for i, n in enumerate(self.names)}
        self.T = np.asarray(T, dtype=float).reshape(len(self.names) * 4, 3)
        self.map = dict(fmap)

    # ---- tra xương
    def bone_for(self, name, at=None):
        """Xương khớp cho một xương bất kỳ của rig mẫu: leo lên cha tới khi gặp
        xương deform. Không có cha deform (Heel nằm dưới LegIK) thì lấy xương
        deform gần nhất theo vị trí `at`."""
        B = self.rig.data.bones
        b = B.get(name)
        while b is not None:
            if b.name in self.map:
                return self.map[b.name]
            b = b.parent
        if at is None:
            return self.names[0]
        best = min((n for n in self.map), key=lambda n: (B[n].head_local - at).length)
        return self.map[best]

    def block(self, fit_name):
        i = self.index[fit_name] * 4
        return self.T[i:i + 4]

    def point(self, fit_name, p):
        return Vector(np.append(np.array(p), 1.0) @ self.block(fit_name))

    def direction(self, fit_name, d):
        return Vector(np.array(d) @ self.block(fit_name)[:3])

    # ---- lưu / đọc
    def store(self, obj, template_mesh, pairs, error):
        obj[FIT_KEY] = {"rig": self.rig.name, "mesh": template_mesh.name,
                        "bones": self.names, "T": [float(x) for x in self.T.ravel()],
                        "map": self.map,
                        "pairs": pairs, "error_mm": error}

    @classmethod
    def load(cls, obj):
        data = obj.get(FIT_KEY) if obj is not None else None
        if not data:
            return None
        rig = bpy.data.objects.get(data["rig"])
        if rig is None or rig.type != 'ARMATURE':
            return None
        fit = cls(rig, list(data["bones"]), list(data["T"]), dict(data.get("map", {})))
        B = rig.data.bones
        if not fit.map or any(n not in B for n in fit.map):
            return None         # rig mẫu đã đổi từ lúc khớp
        return fit

    # ---- uốn lưới mẫu
    def deform_mesh(self, obj):
        """Vertex (hệ rig mẫu) của một mesh skin vào rig mẫu, uốn theo T."""
        deform = set(self.map)
        Ri = _world(self.rig).inverted() @ _world(obj)
        P = np.array([tuple(Ri @ v.co) for v in obj.data.vertices])
        W = np.zeros((len(P), len(self.names)))
        for i, row in enumerate(_rows(obj, deform)):
            for n, w in row.items():
                W[i, self.index[self.map[n]]] += w
        s = W.sum(1)
        bare = s < 1e-6
        W[bare, self.index[self.names[0]]] = 1.0
        s[bare] = 1.0
        W /= s[:, None]
        Ph = np.hstack([P, np.ones((len(P), 1))])
        M = (W[:, :, None] * Ph[:, None, :]).reshape(len(P), -1)
        return M @ self.T


LANDMARK_W = 400.0      # mốc giải phẫu (đáy quần) so với ~6000 dòng bề mặt
ROOT_SLOPE = 2.0        # gốc tay: mặt dưới tay dốc dưới 2:1 là hết vách nách


def _crotch(m, obj):
    """Đáy quần: điểm đầu tiên trên lưới khi bắn tia thẳng lên từ dưới chân,
    ở đường giữa x = 0, giữa độ dày người (hệ toạ độ qua ma trận `m`)."""
    pts = [m @ v.co for v in obj.data.vertices]
    obj.data.calc_loop_triangles()
    bvh = BVHTree.FromPolygons(pts, [tuple(t.vertices) for t in obj.data.loop_triangles])
    ys = sorted(p.y for p in pts)
    zlo = min(p.z for p in pts)
    hit = bvh.ray_cast(Vector((0.0, (ys[0] + ys[-1]) * 0.5, zlo - 0.05)), Vector((0, 0, 1)))
    return hit[0] if hit[0] is not None else None


def _armpit(m, obj, bicep, hip_z):
    """Nách (bên +X, hệ qua ma trận `m`): quét tia thẳng đứng từ dưới lên, x tăng
    dần; chỗ đầu tiên tia chạm mặt dưới cánh tay (gần độ cao vai) thay vì thân
    là nách. `bicep` = đầu xương cánh tay ước lượng, `hip_z` = độ cao khớp đùi."""
    pts = [m @ v.co for v in obj.data.vertices]
    obj.data.calc_loop_triangles()
    bvh = BVHTree.FromPolygons(pts, [tuple(t.vertices) for t in obj.data.loop_triangles])
    zb = bicep.z - 0.35 * (bicep.z - hip_z)
    prev = None
    step = max(bicep.x, 0.05) / 60.0
    for k in range(1, 120):
        x = k * step
        h = bvh.ray_cast(Vector((x, bicep.y, zb)), Vector((0, 0, 1)))
        if h[0] is None:
            continue
        z = h[0].z
        if prev is not None and z < bicep.z + 0.02 * (bicep.z - hip_z) and abs(z - prev) > 1e-3 \
                and z > zb + 0.05 * (bicep.z - hip_z):
            return Vector((x, bicep.y, z))
        prev = z
    return None


def _arm_root(m, obj, pit, bicep, hip_z):
    """Gốc cánh tay sau nách: (x chỗ mặt dưới tay hết dựng đứng -- dốc còn
    ROOT_SLOPE --, z tâm ống tay, nửa độ dày ống tay). Không lấy chỗ dốc 45°:
    dưới tay Adult là cả một sườn 45° dài 4 cm, chỗ đó trôi ra tận 0.181."""
    pts = [m @ v.co for v in obj.data.vertices]
    obj.data.calc_loop_triangles()
    bvh = BVHTree.FromPolygons(pts, [tuple(t.vertices) for t in obj.data.loop_triangles])
    zb = bicep.z - 0.35 * (bicep.z - hip_z)
    step = max(bicep.x, 0.05) / 150.0
    rows = []
    for k in range(0, 120):
        x = pit.x + k * step
        h1 = bvh.ray_cast(Vector((x, bicep.y, zb)), Vector((0, 0, 1)))[0]
        if h1 is None:
            break
        h2 = bvh.ray_cast(h1 + Vector((0, 0, 1e-4)), Vector((0, 0, 1)))[0]
        if h2 is None:
            break
        rows.append((x, h1.z, h2.z))
    w = 4
    for i in range(len(rows) - w):
        (x0, u0, _t0), (x1, u1, _t1) = rows[i], rows[i + w]
        if (u1 - u0) <= ROOT_SLOPE * (x1 - x0):
            x45 = (x0 + x1) * 0.5
            thick = rows[i + w // 2][2] - rows[i + w // 2][1]
            flat = [(u, t) for x, u, t in rows if x45 + 0.5 * thick <= x <= x45 + thick]
            if not flat:
                return None
            under = sorted(u for u, _t in flat)[len(flat) // 2]
            top = sorted(t for _u, t in flat)[len(flat) // 2]
            return Vector((x45, (under + top) * 0.5, (top - under) * 0.5))
    return None


def solve(rig, src, dst, iters=ITERS, report=None):
    """Khớp lưới mẫu `src` (skin vào `rig`) lên lưới mới `dst`.

    Trả về (Fit, sai số trung bình mm, sai số lớn nhất mm)."""
    t0 = time.time()
    fmap = _fit_bone_map(rig)
    B = rig.data.bones
    names = sorted(set(fmap.values()), key=lambda n: len(B[n].parent_recursive))
    fi = {n: i for i, n in enumerate(names)}
    nb = len(names)

    Ri = _world(rig).inverted()
    ms = Ri @ _world(src)
    md = Ri @ _world(dst)
    rows = _rows(src, set(fmap))
    step = _stride(len(src.data.vertices))
    keep = range(0, len(src.data.vertices), step)
    P = np.array([tuple(ms @ src.data.vertices[i].co) for i in keep])
    W = np.zeros((len(P), nb))
    for r, i in enumerate(keep):
        for n, w in rows[i].items():
            W[r, fi[fmap[n]]] += w
    s = W.sum(1)
    W = W[s > 1e-6] / s[s > 1e-6, None]
    P = P[s > 1e-6]
    n = len(P)
    Ph = np.hstack([P, np.ones((n, 1))])
    M = (W[:, :, None] * Ph[:, None, :]).reshape(n, nb * 4)

    dverts = [md @ v.co for v in dst.data.vertices]
    dst.data.calc_loop_triangles()
    bvh = BVHTree.FromPolygons(dverts, [tuple(t.vertices) for t in dst.data.loop_triangles])
    Q = np.array([tuple(dverts[i]) for i in range(0, len(dverts), _stride(len(dverts)))])

    # ràng buộc khớp: đầu xương + giữa xương, xương con và cha cùng đưa về một chỗ
    rows_j = []
    for nm in names:
        b = B[nm]
        up = b.parent
        while up is not None and up.name not in fi:
            up = up.parent
        if up is None:
            continue
        for p in (b.head_local, (b.head_local + b.tail_local) * 0.5):
            r = np.zeros(nb * 4)
            h = np.append(np.array(p), 1.0)
            r[fi[nm] * 4:fi[nm] * 4 + 4] += h
            r[fi[up.name] * 4:fi[up.name] * 4 + 4] -= h
            rows_j.append(r)
    J = np.array(rows_j) if rows_j else np.zeros((0, nb * 4))

    # khởi đầu: co giãn theo hộp bao (Y giữ nguyên -- độ dày người ít đổi),
    # chiều cao co giãn TỪNG ĐOẠN qua mốc đáy quần. Chân là ống trơn: dữ liệu
    # bề mặt không nói được khớp gối nằm đâu dọc ống, nên khớp chân giữ nguyên
    # vị trí khởi đầu. Co giãn đều cả người thì sai khi tỉ lệ chân/thân khác:
    # Kid -> Adult đầu đùi rơi xuống dưới đáy quần 8.5 cm, gối thấp 5.5 cm --
    # gập gối là gãy sai chỗ, gối mesh đâm qua quần.
    lo, hi = P.min(0), P.max(0)
    qlo, qhi = Q.min(0), Q.max(0)
    sc = (qhi - qlo) / np.maximum(hi - lo, 1e-6)
    sc[1] = 1.0
    ck = _crotch(ms, src)
    ca = _crotch(md, dst)
    crotch = (ck is not None and ca is not None and lo[2] < ck[2] < hi[2]
              and qlo[2] < ca[2] < qhi[2])
    zknots = [(lo[2], qlo[2])] + ([(ck[2], ca[2])] if crotch else []) + [(hi[2], qhi[2])]
    xmax_k = max(abs(lo[0]), abs(hi[0]))
    xmax_a = max(abs(qlo[0]), abs(qhi[0]))
    xknots = [(0.0, 0.0), (xmax_k, xmax_a)]

    def warp(knots, z):
        """(giá trị, độ dốc) của phép co giãn từng đoạn qua các mốc."""
        for (z0, w0), (z1, w1) in zip(knots, knots[1:]):
            if z <= z1 or (z1, w1) == knots[-1]:
                s_ = (w1 - w0) / max(z1 - z0, 1e-6)
                return w0 + (z - z0) * s_, s_
        return knots[-1][1], 1.0

    def init(zk, xk):
        T = np.zeros((nb * 4, 3))
        for nm in names:
            mid = (B[nm].head_local + B[nm].tail_local) * 0.5
            z1, sz = warp(zk, mid.z)
            ax, sx = warp(xk, abs(mid.x))
            sgn = 1.0 if mid.x >= 0 else -1.0
            A = np.zeros((4, 3))
            A[0, 0], A[1, 1], A[2, 2] = sx, 1.0, sz
            A[3, 0] = sgn * (ax - sx * abs(mid.x))
            A[3, 1] = ((qlo[1] + qhi[1]) - (lo[1] + hi[1])) / 2
            A[3, 2] = z1 - mid.z * sz
            T[fi[nm] * 4:fi[nm] * 4 + 4] = A
        return T

    # Mốc đáy quần giữ suốt quá trình khớp (vertex mẫu gần mốc nhất, theo weight
    # của nó) -- không thì ICP lại trượt dọc ống chân.
    LM = np.zeros((0, nb * 4))
    LQ = np.zeros((0, 3))
    if crotch:
        vi = min(range(len(src.data.vertices)),
                 key=lambda i: ((ms @ src.data.vertices[i].co) - ck).length)
        row = np.zeros(nb * 4)
        tot = sum(rows[vi].values()) or 1.0
        ph = np.append(np.array(ms @ src.data.vertices[vi].co), 1.0)
        for nm_, w in rows[vi].items():
            row[fi[fmap[nm_]] * 4:fi[fmap[nm_]] * 4 + 4] += ph * (w / tot)
        LM, LQ = row[None, :] * math.sqrt(LANDMARK_W), np.array([tuple(ca)]) * math.sqrt(LANDMARK_W)

    eye = np.eye(nb * 4)
    zj = np.zeros((len(J), 3))

    def lm_row(pk):
        """Dòng mốc: vertex mẫu gần điểm `pk` nhất, theo weight của nó."""
        vi = min(range(len(src.data.vertices)),
                 key=lambda i: ((ms @ src.data.vertices[i].co) - pk).length)
        row = np.zeros(nb * 4)
        tot = sum(rows[vi].values()) or 1.0
        ph = np.append(np.array(ms @ src.data.vertices[vi].co), 1.0)
        for nm_, w in rows[vi].items():
            row[fi[fmap[nm_]] * 4:fi[fmap[nm_]] * 4 + 4] += ph * (w / tot)
        return row * math.sqrt(LANDMARK_W)

    def icp(T, done, LM=LM, LQ=LQ):
        for it in range(iters):
            X = M @ T
            C = np.array([tuple(bvh.find_nearest(Vector(x))[0]) for x in X])
            kd = KDTree(n)
            for i, x in enumerate(X):
                kd.insert(Vector(x), i)
            kd.balance()
            rv = np.array([kd.find(Vector(q))[1] for q in Q])
            damp = 2.0 * (0.85 ** it) + 0.01
            A_ = np.vstack([M, math.sqrt(REVERSE_W) * M[rv], math.sqrt(JOINT_W) * J,
                            LM, math.sqrt(damp) * eye])
            b_ = np.vstack([C, math.sqrt(REVERSE_W) * Q, zj, LQ, math.sqrt(damp) * T])
            T = np.linalg.lstsq(A_, b_, rcond=None)[0]
            if report and it % 10 == 9:
                report(done + it + 1, 2 * iters, time.time() - t0)
        return T

    # Lượt 1 tìm các khớp được HÌNH DẠNG neo chắc: Head (mặt nhiều chi tiết),
    # vai và cổ tay (bàn tay, cánh tay chữ T). Lượt 2 khởi đầu lại bằng co giãn
    # từng đoạn qua chính các mốc đó, theo chiều cao lẫn chiều ngang -- khớp nằm
    # giữa ống trơn (hông, đốt sống, gối, khuỷu) giữ đúng tỉ lệ của mẫu. Một
    # lượt thì thân cũng trượt như chân: Hips Adult chỉ cao hơn đáy quần 1.8 cm,
    # Kid 6.4 cm (14% quãng đáy quần -> cổ).
    T = icp(init(zknots, xknots), 0)
    first = Fit(rig, names, T, fmap)
    head = posekey.head_bone(rig)
    zk2 = list(zknots)
    if head is not None and head.name in fi:
        hz = first.point(head.name, head.head_local).z
        if zk2[-2][0] < head.head_local.z < zk2[-1][0] and zk2[-2][1] < hz < zk2[-1][1]:
            zk2.insert(-1, (head.head_local.z, hz))
    xk2 = [(0.0, 0.0)]
    LM2, LQ2 = LM, LQ
    pk = pa = None
    arm = next((l for l in rigdef.limbs_for(rig) if l.kind == 'ARM' and l.side == 'L'), None)
    leg = next((l for l in rigdef.limbs_for(rig) if l.kind == 'LEG' and l.side == 'L'), None)
    if arm is not None and all(b in B for b in (arm.deform[0], arm.deform[-1])):
        # Mốc NÁCH: cánh tay cũng là ống trơn theo chiều ngang -- neo vai bằng
        # đầu xương cánh tay của lượt 1 là tự neo vào chỗ sai: Bicep Adult nằm
        # ngoài nách 6.5 cm (Kid 1.4 cm), vai deform lệch hẳn.
        bk = B[arm.deform[0]].head_local
        ba = first.point(first.bone_for(arm.deform[0]), bk)
        hk = B[leg.deform[0]].head_local.z if leg is not None else lo[2]
        ha = first.point(first.bone_for(leg.deform[0]), B[leg.deform[0]].head_local).z \
            if leg is not None else qlo[2]
        pk, pa = _armpit(ms, src, bk, hk), _armpit(md, dst, ba, ha)
        if pk is not None and pa is not None:
            xk2.append((pk.x, pa.x))
            cand = sorted(zk2 + [(pk.z, pa.z)])
            if all(a0 < a1 and b0 < b1 for (a0, b0), (a1, b1) in zip(cand, cand[1:])):
                zk2 = cand
            rows_lm = [lm_row(pk), lm_row(Vector((-pk.x, pk.y, pk.z)))]
            q_lm = [tuple(pa), (-pa.x, pa.y, pa.z)]
            LM2 = np.vstack([LM] + [r[None, :] for r in rows_lm])
            LQ2 = np.vstack([LQ, np.array(q_lm) * math.sqrt(LANDMARK_W)])
        bn = arm.deform[-1]
        k = abs(B[bn].head_local.x)
        a = abs(first.point(first.bone_for(bn), B[bn].head_local).x)
        if k > xk2[-1][0] + 1e-3 and a > xk2[-1][1] + 1e-3:
            xk2.append((k, a))
    if xmax_k > xk2[-1][0] + 1e-3 and xmax_a > xk2[-1][1] + 1e-3:
        xk2.append((xmax_k, xmax_a))
    T = icp(init(zk2, xk2), iters, LM2, LQ2)

    X = M @ T
    d = np.array([bvh.find_nearest(Vector(x))[3] for x in X])
    fit = Fit(rig, names, T, fmap)
    if arm is not None and pk is not None and pa is not None:
        fit.armpit = (pk, pa)
        rk, ra = _arm_root(ms, src, pk, bk, hk), _arm_root(md, dst, pa, ba, ha)
        if rk is not None and ra is not None and rk.z > 1e-4 and ra.z > 1e-4:
            fit.arm_root = (rk, ra)
    return fit, float(d.mean() * 1000), float(d.max() * 1000)


# ============================================================ đặt bộ ref

def _mirror_name(name):
    from . import mirrorkey
    return mirrorkey.swap_side(name)


def place_ref(context, ref, fit):
    """Dời mọi xương ref (dựng từ rig mẫu) theo phép khớp. Trả về số xương."""
    if context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for o in list(context.selected_objects):
        o.select_set(False)
    ref.hide_set(False)
    ref.hide_viewport = False
    context.view_layer.objects.active = ref
    ref.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    try:
        E = ref.data.edit_bones
        plan = {}
        for eb in E:
            fb = fit.bone_for(eb.name, at=eb.head)
            up = fit.bone_for(eb.parent.name, at=eb.parent.head) if eb.parent else fb
            h = (fit.point(fb, eb.head) + fit.point(up, eb.head)) * 0.5
            t = fit.point(fb, eb.tail)
            z = fit.direction(fb, eb.z_axis)
            plan[eb.name] = [h, t, z, abs(eb.head.x) < 1e-4 and abs(eb.tail.x) < 1e-4]
        # Khớp vai (gốc cánh tay): đặt so với NÁCH như ở mẫu, co giãn theo quãng
        # nách -> khuỷu. Cánh tay là ống trơn theo chiều ngang; theo tỉ lệ bắp
        # tay/cẳng tay của mẫu thì vai Adult nằm ngoài nách 6.5 cm (mẫu 1.4 cm)
        # -- vai deform lệch hẳn, nách kéo theo cánh tay.
        # Có gốc tay (chỗ mặt dưới tay dốc 45°) thì đặt theo nó, co giãn theo
        # độ dày ống tay: nách Adult là sườn dốc dài, neo vào nách vẫn ngoài 2.5 cm.
        pits = getattr(fit, "armpit", None)
        roots = getattr(fit, "arm_root", None)
        if pits is not None:
            pk, pa = pits
            for limb in rigdef.limbs_for(fit.rig):
                if limb.kind != 'ARM':
                    continue
                a, b = limb.deform[:2]
                if a not in plan or b not in plan or a not in E or b not in E:
                    continue
                sg = 1.0 if E[a].head.x >= 0 else -1.0
                if roots is not None:
                    rk, ra = roots
                    s = ra.z / rk.z
                    x = ra.x + (abs(E[a].head.x) - rk.x) * s
                    z = ra.y + (E[a].head.z - rk.y) * s
                    plan[a][0] = Vector((sg * x, plan[a][0].y, z))
                else:
                    span_t = abs(E[b].head.x) - pk.x
                    span_n = abs(plan[b][0].x) - pa.x
                    if span_t <= 1e-4 or span_n <= 1e-4:
                        continue
                    x = pa.x + (abs(E[a].head.x) - pk.x) * span_n / span_t
                    plan[a][0] = Vector((sg * x, plan[a][0].y, plan[a][0].z))
                up = E[a].parent
                if up is not None and up.name in plan and (up.tail - E[a].head).length < 1e-5:
                    plan[up.name][1] = plan[a][0]
        # Khớp giữa của chi (gối, khuỷu): hướng lệch khỏi đường gốc -> ngọn lấy
        # theo MẪU, chỉ vị trí dọc chi lấy theo phép khớp. Mặt phẳng gập ở tư thế
        # nghỉ là thứ pole IK được hiệu chỉnh theo: lượt khớp 2 dời đầu đùi Adult
        # vào trong 1 cm, gối lệch ra ngoài 5 mm so với đường hông -> cổ chân,
        # mặt phẳng gập xoay 42° -- ngồi xổm là hai gối choãi sang bên.
        for limb in rigdef.limbs_for(fit.rig):
            a, b, c_ = limb.deform[:3]
            if not all(n in plan and n in E for n in (a, b, c_)):
                continue
            th, tk, ta = E[a].head, E[b].head, E[c_].head
            nh, nk, na = plan[a][0], plan[b][0], plan[c_][0]
            ut, un = ta - th, na - nh
            if ut.length < 1e-6 or un.length < 1e-6:
                continue
            off_t = (tk - th) - ut.normalized() * (tk - th).dot(ut.normalized())
            t = (nk - nh).dot(un.normalized()) / un.length
            rot = ut.normalized().rotation_difference(un.normalized())
            plan[b][0] = nh + un * t + (rot @ off_t) * (un.length / ut.length)
            if (E[a].tail - E[b].head).length < 1e-5:
                plan[a][1] = plan[b][0]
        # khớp nối liền: đuôi cha = đầu con
        for eb in E:
            if eb.use_connect and eb.parent is not None and eb.parent.name in plan:
                plan[eb.parent.name][1] = plan[eb.name][0]
        # đối xứng: trung bình hai bên, xương giữa về x = 0
        flip = Vector((-1.0, 1.0, 1.0))
        for name, row in plan.items():
            other = _mirror_name(name)
            if other != name and other in plan and name < other:
                o = plan[other]
                for k in (0, 1):
                    m = (row[k] + o[k] * flip) * 0.5
                    m_ = m.copy()
                    row[k] = m
                    o[k] = Vector((-m_.x, m_.y, m_.z))
                # roll hai bên có thể theo quy ước gương (z_R = gương z_L) hoặc
                # ngược dấu -- giữ đúng quy ước của rig mẫu
                mz = Vector((-o[2].x, o[2].y, o[2].z)).normalized()
                sign = 1.0 if row[2].dot(mz) >= 0 else -1.0
                zm = row[2].normalized() + mz * sign
                if zm.length > 1e-6:
                    row[2] = zm
                    o[2] = Vector((-zm.x, zm.y, zm.z)) * sign
            elif row[3]:
                row[0].x = row[1].x = 0.0
        order = sorted(E, key=lambda b: len(b.parent_recursive))
        for eb in order:
            h, t, z, _c = plan[eb.name]
            eb.head = h
            eb.tail = t
        for eb in order:
            eb.align_roll(plan[eb.name][2])
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')
    return len(plan)


# ============================================================ mesh đi kèm

def _islands(obj):
    adj = cloth.neighbours(obj)
    lab = [-1] * len(adj)
    k = 0
    for s in range(len(adj)):
        if lab[s] >= 0:
            continue
        stack = [s]
        lab[s] = k
        while stack:
            v = stack.pop()
            for u in adj[v]:
                if lab[u] < 0:
                    lab[u] = k
                    stack.append(u)
        k += 1
    return lab, k


def _stem(name):
    n = name.lower()
    return n.split("_", 1)[1] if "_" in n else n


def template_meshes(rig):
    """Mesh skin vào rig mẫu (trừ chính mesh thân xử lý riêng)."""
    return [o for o in bpy.data.objects if o.type == 'MESH' and cloth.deformed_by(o, rig)]


def eye_pairs(context, fit, height):
    """[(bên, mesh mới)]: nhãn cầu gắn vào xương Eye của rig mẫu, đưa qua phép
    khớp, tìm mesh mới chưa bind có tâm trùng."""
    from . import generate
    out = []
    B = fit.rig.data.bones
    eye_bones = set(generate.eye_bone_names(fit.rig))
    free = [o for o in context.scene.objects if o.type == 'MESH' and o.parent is None
            and not any(m.type == 'ARMATURE' for m in o.modifiers)]
    Ri = _world(fit.rig).inverted()

    def centre(o, m):
        pts = [m @ v.co for v in o.data.vertices]
        return sum(pts, Vector()) / max(len(pts), 1)

    for o in bpy.data.objects:
        if o.type != 'MESH' or o.parent is not fit.rig or o.parent_type != 'BONE':
            continue
        bone = B.get(o.parent_bone)
        if bone is None or bone.name not in eye_bones:
            continue
        c = fit.point(fit.bone_for(bone.name), centre(o, Ri @ _world(o)))
        best = min(free, key=lambda f: (centre(f, Ri @ _world(f)) - c).length, default=None)
        if best is not None and (centre(best, Ri @ _world(best)) - c).length < height * 0.01:
            side = 'L' if bone.name.endswith(".L") else 'R'
            out.append((side, best))
            free.remove(best)
    return out


def mesh_pairs(context, fit, body_src, body_dst, height):
    """{mesh mới: mesh mẫu} cho mesh phụ có hình y như mẫu (lông mày...).
    Ghép theo tên bỏ tiền tố ("Kid_eyebrow" ~ "Adult_eyebrow"), rồi kiểm bằng
    hình: lưới mẫu đã uốn phải nằm trên lưới mới."""
    out = {}
    for src in template_meshes(fit.rig):
        if src is body_src:
            continue
        stem = _stem(src.name)
        cands = [o for o in context.scene.objects if o.type == 'MESH' and o is not body_dst
                 and _stem(o.name) == stem and not cloth.deformed_by(o, fit.rig)]
        for dst in cands:
            X = fit.deform_mesh(src)
            md = _world(fit.rig).inverted() @ _world(dst)
            dv = [md @ v.co for v in dst.data.vertices]
            dst.data.calc_loop_triangles()
            bvh = BVHTree.FromPolygons(dv, [tuple(t.vertices) for t in dst.data.loop_triangles])
            d = np.array([bvh.find_nearest(Vector(x))[3] for x in X])
            if d.mean() < height * PAIR_TOL:
                out[dst.name] = src.name
                break
    return out


# ============================================================ chép weight

COPY_INFLUENCE = 8
REFINE_ITERS = 25
REFINE_SMOOTH = 4


def _island_votes(P, lab_p, Q, lab_q, kq):
    """Đảo của P -> đảo của Q mà đa số điểm P rơi gần nhất."""
    tree = KDTree(len(Q))
    for i, q in enumerate(Q):
        tree.insert(Vector(q), i)
    tree.balance()
    votes = {}
    for i, p in enumerate(P):
        j = tree.find(Vector(p))[1]
        v = votes.setdefault(lab_p[i], {})
        v[lab_q[j]] = v.get(lab_q[j], 0) + 1
    return {k: max(v, key=v.get) for k, v in votes.items()}


def refine(X, src, lab_s, dst, Y, lab_d):
    """Nắn lưới mẫu đã uốn cho áp sát lưới mới bằng một trường dịch chuyển MƯỢT.

    Uốn bằng xương còn lệch vài mm ở chỗ xương phải gánh cả một vùng (cả mặt đi
    theo Head). Mí, môi xếp weight sát nhau từng vertex nên lệch 4 mm là chép
    nhầm mí trên sang mí dưới -- đo trên Kid -> Adult: 150/334 vertex mí sai,
    nhắm mắt ra mép mí răng cưa dù hai cái đầu trùng nhau tới 0.4 mm. Mỗi vòng:
    điểm gần nhất trên lưới mới (cùng đảo), làm mượt độ dời dọc theo cạnh lưới
    mẫu rồi mới cộng vào -- vùng nào trùng hình thì về đúng chỗ, vùng khác hình
    (đáy quần Adult) chỉ trôi theo hàng xóm, không co rúm.
    """
    X = np.array(X, dtype=float)
    dst.data.calc_loop_triangles()
    by_isl = {}
    for t in dst.data.loop_triangles:
        by_isl.setdefault(lab_d[t.vertices[0]], []).append(tuple(t.vertices))
    trees = {k: BVHTree.FromPolygons([Vector(y) for y in Y], ts) for k, ts in by_isl.items()}
    to_dst = _island_votes(X, lab_s, Y, lab_d, None)
    E = np.array([tuple(e.vertices) for e in src.data.edges], dtype=int).reshape(-1, 2)
    deg = np.bincount(E.ravel(), minlength=len(X)).astype(float)
    deg[deg == 0] = 1.0
    own = [trees.get(to_dst.get(lab_s[i])) for i in range(len(X))]
    for _it in range(REFINE_ITERS):
        D = np.zeros_like(X)
        for i, x in enumerate(X):
            if own[i] is not None:
                loc = own[i].find_nearest(Vector(x))[0]
                if loc is not None:
                    D[i] = tuple(loc - Vector(x))
        for _s in range(REFINE_SMOOTH):
            acc = np.zeros_like(D)
            np.add.at(acc, E[:, 0], D[E[:, 1]])
            np.add.at(acc, E[:, 1], D[E[:, 0]])
            D = 0.5 * D + 0.5 * acc / deg[:, None]
        X += D
    return X


def copy_weights(fit, src, dst, rig):
    """Weight của `src` (mẫu) sang `dst` qua lưới mẫu đã uốn. Tên xương mẫu
    không có trên rig mới thì leo lên cha. Trả về (số nhóm, xa nhất mm)."""
    deform_src = set(fit.map)
    B_new = rig.data.bones
    deform_new = {b.name for b in B_new if b.use_deform}
    Bt = fit.rig.data.bones

    def rename(n):
        b = Bt.get(n)
        while b is not None and b.name not in deform_new:
            b = b.parent
        return b.name if b is not None else None

    lab_s, ks = _islands(src)
    lab_d, kd_ = _islands(dst)
    md = _world(fit.rig).inverted() @ _world(dst)
    Y = [md @ v.co for v in dst.data.vertices]
    X = refine(fit.deform_mesh(src), src, lab_s, dst, Y, lab_d)
    X = [Vector(x) for x in X]
    rows = []
    for raw in _rows(src, deform_src):
        row = {}
        for n, w in raw.items():
            m = rename(n)
            if m:
                row[m] = row.get(m, 0.0) + w
        rows.append(row)

    src.data.calc_loop_triangles()
    tris = [tuple(t.vertices) for t in src.data.loop_triangles]

    # mỗi đảo lưới mới (thân, răng trên, răng dưới, lưỡi) chỉ tìm trong đảo mẫu
    # tương ứng -- môi sát răng, tìm chung là môi lấy weight của răng
    tree = KDTree(len(X))
    for i, x in enumerate(X):
        tree.insert(x, i)
    tree.balance()
    votes = [dict() for _k in range(kd_)]
    for i, y in enumerate(Y):
        j = tree.find(y)[1]
        votes[lab_d[i]][lab_s[j]] = votes[lab_d[i]].get(lab_s[j], 0) + 1
    match = [max(v, key=v.get) if v else 0 for v in votes]
    by_island = {}
    for t in tris:
        by_island.setdefault(lab_s[t[0]], []).append(t)
    trees = {k: (BVHTree.FromPolygons(X, ts), ts) for k, ts in by_island.items()}

    out, far = [], 0.0
    for i, y in enumerate(Y):
        bvh, ts = trees.get(match[lab_d[i]], (None, None))
        if bvh is None:
            out.append({})
            continue
        loc, _n, ti, dist = bvh.find_nearest(y)
        if ti is None:
            out.append({})
            continue
        far = max(far, dist)
        tri = ts[ti]
        acc = {}
        for k, f in zip(tri, poly_3d_calc([X[k] for k in tri], loc)):
            for n, w in rows[k].items():
                acc[n] = acc.get(n, 0.0) + w * f
        out.append(acc)

    for g in [g for g in dst.vertex_groups if g.name in B_new]:
        dst.vertex_groups.remove(g)
    if not cloth.deformed_by(dst, rig):
        cloth._clean(dst, rig)
        cloth._attach(dst, rig)
    # Giữ đủ số xương như mẫu: mí mắt Kid tới 7 xương một vertex, cắt về 4 là
    # mép mí lệch. Xuất Unity tự gộp còn 4 (unityexport.limit_weights).
    n = cloth._write(dst, out, limit=COPY_INFLUENCE)
    copy_weights.last = (X, tris, trees, match, lab_d, Y)
    return n, far * 1000


def copy_shape_keys(fit, src, dst, body_pair=None):
    """Chép shape key của mẫu sang mesh mới, dùng đúng tương ứng của lần chép
    weight vừa rồi (`copy_weights.last`). Độ dời mỗi vertex mẫu đi qua phần
    tuyến tính của phép khớp tại chỗ đó (đầu Kid -> Adult gần như tịnh tiến nên
    gần như chép nguyên). Key trùng tên trên mesh mới bị ghi đè, key khác giữ.

    Vì sao không dựng lại bằng `face_shapes.build`: đo trên Kid, dựng lại bằng
    face rig cho mí nhắm mép răng cưa, trong khi bộ key đang có của Kid nhắm
    sạch -- mặt hai nhân vật trùng nhau thì bộ key tốt nhất chính là bộ của mẫu.

    `body_pair` = (key thân mẫu, key thân mới): driver của mesh phụ (lông mày
    đọc giá trị key thân) được chép và trỏ sang key thân mới.
    Trả về số key."""
    from . import face
    skey = src.data.shape_keys
    if skey is None or len(skey.key_blocks) < 2:
        return 0
    X, tris, trees, match, lab_d, Y = copy_weights.last
    Ri = _world(fit.rig).inverted()
    ms3 = (Ri @ _world(src)).to_3x3()
    md3i = (Ri @ _world(dst)).to_3x3().inverted()
    # phần tuyến tính pha theo weight mẫu, mỗi vertex mẫu
    deform = set(fit.map)
    L = [np.array(fit.block(n)[:3]) for n in fit.names]
    lin = []
    for row in _rows(src, deform):
        tot = sum(row.values()) or 1.0
        m = np.zeros((3, 3))
        for n, w in row.items():
            m += L[fit.index[fit.map[n]]] * (w / tot)
        lin.append(m if row else np.eye(3))
    # vị trí trên tam giác mẫu của từng vertex mới
    where = []
    for i, y in enumerate(Y):
        bvh, ts = trees.get(match[lab_d[i]], (None, None))
        hit = bvh.find_nearest(y) if bvh is not None else (None, None, None, None)
        if hit[2] is None:
            where.append(None)
            continue
        tri = ts[hit[2]]
        where.append((tri, poly_3d_calc([X[k] for k in tri], hit[0])))
    basis = skey.reference_key
    if dst.data.shape_keys is None:
        dst.shape_key_add(name="Basis", from_mix=False)
    dkey = dst.data.shape_keys
    dbasis = dkey.reference_key
    names = []
    for kb in skey.key_blocks:
        if kb == basis:
            continue
        delta = []
        for k in range(len(src.data.vertices)):
            d = kb.data[k].co - basis.data[k].co
            delta.append(np.array(ms3 @ d) @ lin[k] if d.length_squared > 0 else None)
        out = dkey.key_blocks.get(kb.name) or dst.shape_key_add(name=kb.name, from_mix=False)
        out.slider_min, out.slider_max = kb.slider_min, kb.slider_max
        # Đặt tường minh: trong Blender có giao diện key mới tạo ra mang giá trị
        # 1.0 (chạy nền thì 0) -- 56 biểu cảm cộng dồn thành một cái mỏ dài
        # tới ngực, chỉ thấy khi nhìn viewport thật.
        out.value = 0.0
        for i, w in enumerate(where):
            acc = np.zeros(3)
            if w is not None:
                for k, f in zip(*w):
                    if delta[k] is not None:
                        acc += delta[k] * f
            out.data[i].co = dbasis.data[i].co + md3i @ Vector(acc)
        names.append(kb.name)
    own = face.own_list(skey)
    if own is not None:
        mine = face.own_list(dkey) or set()
        face.set_own_list(dkey, mine | (own & set(names)))
    if body_pair is not None and skey.animation_data:
        old_key, new_key = body_pair
        ad = dkey.animation_data or dkey.animation_data_create()
        for fc in skey.animation_data.drivers:
            if ad.drivers.find(fc.data_path, index=fc.array_index):
                ad.drivers.remove(ad.drivers.find(fc.data_path, index=fc.array_index))
            new = ad.drivers.from_existing(src_driver=fc)
            for v in new.driver.variables:
                for t in v.targets:
                    if t.id is old_key:
                        t.id = new_key
    return len(names)


def bind_from_template(context, rig, body):
    """Gọi trong `srp.bind`: chép weight mẫu sang thân + mesh phụ đã ghép.
    Trả về danh sách câu báo cáo (rỗng nếu thân không khớp mẫu nào)."""
    fit = Fit.load(body)
    if fit is None:
        return []
    data = body[FIT_KEY]
    src = bpy.data.objects.get(data["mesh"])
    if src is None:
        return ["mẫu %s không còn, giữ automatic weights" % data["mesh"]]
    lines = []
    n, far = copy_weights(fit, src, body, rig)
    k = copy_shape_keys(fit, src, body)
    lines.append("chép weight %s -> %s: %d xương (xa nhất %.0f mm)%s" % (
        src.name, body.name, n, far, ", %d shape key" % k if k else ""))
    pair_keys = (src.data.shape_keys, body.data.shape_keys)
    for dst_name, src_name in data.get("pairs", {}).items():
        d, s = bpy.data.objects.get(dst_name), bpy.data.objects.get(src_name)
        if d is None or s is None:
            continue
        n, far = copy_weights(fit, s, d, rig)
        k = copy_shape_keys(fit, s, d, body_pair=pair_keys if all(pair_keys) else None)
        lines.append("%s -> %s: %d xương%s" % (s.name, d.name, n, ", %d shape key" % k if k else ""))
    return lines


# ============================================================ operator

def _height(obj):
    pts = [_world(obj) @ Vector(c) for c in obj.bound_box]
    return max(p.z for p in pts) - min(p.z for p in pts)


class SRP_OT_template_fit(bpy.types.Operator):
    """Dựng bộ ref cho mesh nhân vật bằng cách khớp một nhân vật ĐÃ RIG lên nó:
    vị trí khớp, roll và (lúc Bind) weight đều lấy từ nhân vật mẫu"""
    bl_idname = "srp.template_fit"
    bl_label = "Dựng ref theo nhân vật mẫu"
    bl_options = {'REGISTER', 'UNDO'}

    fill_lists: BoolProperty(
        name="Tự điền mắt, lông mày", default=True,
        description="Nhãn cầu / lông mày của nhân vật mới trùng hình với mẫu thì "
                    "tự vào danh sách bước 1 và được chép weight lúc bind")

    @classmethod
    def poll(cls, context):
        st = getattr(context.scene, "srp_generate", None)
        return (st is not None and st.target_mesh is not None and st.template_rig is not None
                and st.template_mesh is not None)

    def execute(self, context):
        st = context.scene.srp_generate
        rig, src, dst = st.template_rig, st.template_mesh, st.target_mesh
        if src is dst:
            self.report({'ERROR'}, "Mesh mẫu trùng mesh nhân vật")
            return {'CANCELLED'}
        if not cloth.deformed_by(src, rig):
            self.report({'ERROR'}, "%s chưa skin vào %s" % (src.name, rig.name))
            return {'CANCELLED'}
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        wm = context.window_manager
        wm.progress_begin(0, 2 * ITERS)
        try:
            fit, mean, worst = solve(rig, src, dst,
                                     report=lambda i, n, t: wm.progress_update(i))
        finally:
            wm.progress_end()

        name = refrig.ref_object_name(st.rig_name.strip() or "SRP_Rig")
        old = bpy.data.objects.get(name)
        if old is not None and refrig.is_ref(old):
            data = old.data
            bpy.data.objects.remove(old, do_unlink=True)
            if data.users == 0:
                bpy.data.armatures.remove(data)
        ref, _count = refsync.ref_from_rig(context, rig, name=name)
        if ref is None:
            self.report({'ERROR'}, "Rig mẫu không có xương nào theo bản vẽ")
            return {'CANCELLED'}
        moved = place_ref(context, ref, fit)
        refrig.store_baseline(ref)

        height = _height(dst)
        pairs = mesh_pairs(context, fit, src, dst, height)
        eyes = eye_pairs(context, fit, height) if self.fill_lists else []
        fit.store(dst, src, pairs if self.fill_lists else {}, round(mean, 2))
        if self.fill_lists:
            # mắt / mesh mặt / quần áo của chính nhân vật mẫu -> bỏ khỏi danh sách
            def theirs(m):
                return m is None or m.parent is rig or cloth.deformed_by(m, rig)
            for coll in (st.eyes, st.face_meshes):
                for i in reversed(range(len(coll))):
                    if theirs(coll[i].mesh):
                        coll.remove(i)
            have = {e.mesh for e in st.eyes}
            for side, o in eyes:
                if o not in have:
                    e = st.eyes.add()
                    e.side, e.mesh = side, o
            for i in reversed(range(len(st.cloth_meshes))):
                m = st.cloth_meshes[i].mesh
                if theirs(m) or (m.name in pairs):
                    st.cloth_meshes.remove(i)
        context.view_layer.objects.active = ref
        self.report({'INFO'}, "Ref %s: %d xương khớp theo %s | lệch bề mặt TB %.1f mm, "
                              "max %.0f mm%s%s" % (
                                  ref.name, moved, src.name, mean, worst,
                                  " | mắt: " + ", ".join(o.name for _s, o in eyes) if eyes else "",
                                  " | chép weight lúc bind: " + ", ".join(pairs) if pairs else ""))
        return {'FINISHED'}


def draw_template(layout, context):
    st = context.scene.srp_generate
    box = layout.box()
    box.label(text="Hoặc lấy từ nhân vật mẫu đã rig", icon='DUPLICATE')
    box.prop(st, "template_rig", text="Rig mẫu")
    box.prop(st, "template_mesh", text="Mesh mẫu")
    box.prop(st, "template_weights")
    row = box.row()
    row.scale_y = 1.3
    row.operator("srp.template_fit", icon='MOD_MESHDEFORM')
    fit = st.target_mesh.get(FIT_KEY) if st.target_mesh else None
    if fit:
        box.label(text="Đã khớp theo %s (lệch %.1f mm)" % (fit["mesh"], fit.get("error_mm", 0)),
                  icon='CHECKMARK')


CLASSES = (SRP_OT_template_fit,)
