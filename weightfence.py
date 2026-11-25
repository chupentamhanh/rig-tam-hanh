"""Rào vùng weight + khám weight bằng tư thế.

Automatic weights và Delta Mush chỉ nhìn khoảng cách và độ mượt, nên không
chặn được lỗi "dính sai vùng": xương vai ăn lên má (nhún vai là má bị kéo),
xương hàm ăn ra sau gáy (há miệng là sau đầu bị kéo), đùi bên này ăn sang chân
bên kia. Module này:

1. Chia xương deform thành VÙNG theo CẤU TRÚC rig, không đoán theo tên:
   - Head: xương đầu (posekey.head_bone) và mọi xương con của nó (hàm, mắt, môi...).
   - Arm.L / Arm.R / Leg.L / Leg.R: chuỗi chi của rig (rigdef.limbs_for) từ xương
     đầu chi (Bicep / Thigh) xuống hết con cháu, cộng các xương GỐC CHI ở trên nó
     (Shoulder, Pelvis): leo lên từ xương đầu chi chừng nào nhánh đó chưa chứa chi
     khác hay đầu.
   - Torso: phần còn lại. Cổ là các xương leo lên từ đầu chừng nào nhánh chưa có chi.
2. Gán vùng cho từng VERTEX: vùng có tổng weight lớn nhất, lưu vào attribute INT
   `srp_region` trên mesh (sửa được: chọn vertex trong Edit Mode rồi gán vùng).
3. Luật được phép: xương ăn vùng của nó; một số "cầu nối" được sang vùng kề --
   cổ vào đầu, gốc chi / đầu chi vào thân, xương thân chỗ chi bám vào chi, hai
   chân trộn nhau trong dải giữa háng. Hàm chỉ được ăn phía trước khớp hàm và
   không cao hơn khớp hàm nhiều (phần thừa trả về xương cha).
4. Rào: gỡ weight phạm luật (vertex vẽ tay giữ nguyên), làm mượt chỗ vừa gỡ,
   tối đa 4 xương, bỏ weight vụn, normalize.
5. Khám: kiểm tĩnh (sai vùng, chưa normalize, quá 4 xương, vụn, xa xương, lệch
   trái/phải) và kiểm bằng tư thế (bakeweights.training_poses + há miệng): vùng
   không liên quan bị kéo theo, cạnh lưới giãn quá mạnh. Báo cáo vào text block.
"""

import math
from collections import Counter, defaultdict

import bpy
import numpy as np
from bpy.props import EnumProperty
from bpy.types import Operator
from mathutils import Vector, kdtree
from mathutils.geometry import intersect_point_line

from . import bakeweights, cloth, rigdef

REGIONS = ('Head', 'Torso', 'Arm.L', 'Arm.R', 'Leg.L', 'Leg.R')
REGION_LABEL = {'Head': "Đầu", 'Torso': "Thân", 'Arm.L': "Tay trái", 'Arm.R': "Tay phải",
                'Leg.L': "Chân trái", 'Leg.R': "Chân phải"}
ATTR = "srp_region"
REPORT = "SRP_Weight_Check"
MAX_INF = 4
MIN_W = 0.01
SYM_TOL = 0.10
MIDLINE = 0.25          # dải giữa háng: phần khoảng cách hai khớp háng
JUNCTION = 1.0          # chỗ cổ giáp vai: vertex đầu cách xương gốc tay dưới 1.0 lần
                        # khoảng cách gốc tay -> khớp đầu thì vai / tay được ăn (đo: cổ
                        # mèo 0.5-0.9, má mèo >= 1.3, má Adult >= 1.56)
JAW_BACK = (0.3, 0.45)  # hàm: sau khớp hàm quá 0.3 chiều dài hàm thì bớt dần, 0.45 thì hết
                        # (Adult vẽ tay: hàm ăn sau khớp tới 0.375 chiều dài, ở góc hàm dưới tai)
JAW_UP = (0.3, 0.65)    # hàm: cao hơn khớp hàm quá 0.3 chiều dài thì bớt dần, 0.65 thì hết
JAW_DOWN = (0.6, 1.0)   # hàm: thấp hơn khớp hàm quá 0.6 chiều dài (cổ dưới cằm) thì bớt dần, 1.0 thì hết
MOVE = 0.003            # khám tư thế: vertex dịch quá 0.3% chiều cao nhân vật là "bị kéo"
STRETCH = 1.5           # cạnh dài gấp 2.5 lần là giãn mạnh (gập khuỷu / nhún vai thường tới 1.2)


def _clamp01(x):
    return max(0.0, min(1.0, x))


# ============================================================ vùng của xương

class Layout:
    """Vùng của mọi xương deform + các luật cầu nối, đọc từ cấu trúc rig."""

    def __init__(self, rig):
        from . import posekey
        B = rig.data.bones
        self.rig = rig
        self.deform = [b.name for b in B if b.use_deform]
        self.region = {}
        self.bridge = defaultdict(set)      # vùng vertex -> xương được sang
        head = posekey.head_bone(rig)
        tops = {}                           # xương đầu chi -> vùng
        for l in rigdef.limbs_for(rig):
            if l.deform and l.deform[0] in B:
                tops[l.deform[0]] = ('Arm.' if l.kind == 'ARM' else 'Leg.') + l.side
        self.head = head.name if head else None
        marks = set(tops) | ({self.head} if self.head else set())

        def holds_other(b, own):
            """Nhánh của b có chứa chi khác / đầu (ngoài `own`)?"""
            names = {b.name} | {c.name for c in b.children_recursive}
            return bool((names & marks) - {own})

        # đầu
        if head is not None:
            for n in [head.name] + [c.name for c in head.children_recursive]:
                self.region[n] = 'Head'
        # chi
        self.roots = {}                     # vùng chi -> [xương gốc chi]
        self.attach = {}                    # vùng chi -> xương thân nơi chi bám vào
        for top, reg in tops.items():
            b = B[top]
            for n in [b.name] + [c.name for c in b.children_recursive]:
                self.region.setdefault(n, reg)
            roots, p = [], b.parent
            while p is not None and not holds_other(p, top):
                roots.append(p.name)
                self.region.setdefault(p.name, reg)
                p = p.parent
            self.roots[reg] = roots
            self.attach[reg] = p.name if p is not None else None
        # cổ: leo từ đầu lên chừng nào nhánh chưa có chi
        self.neck = []
        if head is not None:
            p = head.parent
            while p is not None and not ((({p.name} | {c.name for c in p.children_recursive}) & set(tops))):
                self.neck.append(p.name)
                p = p.parent
        for n in self.deform:
            self.region.setdefault(n, 'Torso')

        # cầu nối
        self.bridge['Head'].update(self.neck)
        if self.head:
            self.bridge['Torso'].add(self.head)
        if 'Jaw' in self.region:
            self.bridge['Torso'].add('Jaw')     # cổ dưới cằm -- jaw_cap chặn vai / ngực
        for top, reg in tops.items():
            self.bridge['Torso'].update(self.roots[reg])
            self.bridge['Torso'].add(top)
            att = self.attach.get(reg)
            if att is not None and att in B:
                self.bridge[reg].update(self._torso_near(B[att], 2))
            if reg.startswith('Arm'):
                self.bridge[reg].update(self.neck)
                if self.head:
                    self.bridge[reg].add(self.head)     # đầu ăn chút vai (cổ ngắn)
        # chỗ cổ giáp vai: vertex vùng đầu sát xương gốc tay
        self.junction = []                  # (đoạn gốc tay, bán kính, xương được ăn)
        if head is not None:
            for top, reg in tops.items():
                if not reg.startswith('Arm') or not self.roots.get(reg):
                    continue
                r = B[self.roots[reg][0]]          # xương gốc sát đầu chi nhất
                rad = (r.head_local - head.head_local).length * JUNCTION
                ok = set(self.roots[reg]) | {top}
                if self.attach.get(reg):
                    ok.add(self.attach[reg])
                self.junction.append((r.head_local.copy(), r.tail_local.copy(), rad, ok))
        # chân: dải giữa háng
        legs = {reg: B[top] for top, reg in tops.items() if reg.startswith('Leg')}
        self.mid = None
        if 'Leg.L' in legs and 'Leg.R' in legs:
            hl, hr = legs['Leg.L'].head_local, legs['Leg.R'].head_local
            self.mid = ((hl.x + hr.x) * 0.5, abs(hl.x - hr.x) * MIDLINE)
        # hàm
        self.jaw = None
        if self.head and 'Jaw' in B and B['Jaw'].use_deform:
            J, H = B['Jaw'], B[self.head]
            up = (H.tail_local - H.head_local).normalized()
            d = J.tail_local - J.head_local
            fwd = d - up * d.dot(up)
            if fwd.length > 1e-6:
                self.jaw = (J.head_local.copy(), fwd.normalized(), up, J.length,
                            J.parent.name if J.parent else self.head)

    def _torso_near(self, start, depth):
        """Xương deform thân cách `start` tối đa `depth` xương deform (lên và xuống
        chuỗi thân; xương không deform như Hips / Hip_Master chỉ là chỗ đi qua)."""
        out, seen = set(), {start.name}
        todo = [(start, 1 if start.use_deform else 0)]
        if start.use_deform:
            out.add(start.name)
        while todo:
            b, d = todo.pop()
            nxt = ([b.parent] if b.parent else []) + list(b.children)
            for c in nxt:
                if c.name in seen:
                    continue
                seen.add(c.name)
                reg = self.region.get(c.name, 'Torso' if not c.use_deform else None)
                if reg != 'Torso' or c.name in self.neck:
                    continue
                dc = d + (1 if c.use_deform else 0)
                if dc > depth:
                    continue
                if c.use_deform:
                    out.add(c.name)
                todo.append((c, dc))
        return out

    def allowed(self, bone, vreg, co):
        """Xương `bone` được ăn vertex vùng `vreg` ở `co` (hệ armature)?"""
        br = self.region.get(bone)
        if br is None or vreg is None or br == vreg:
            return True
        if (self.mid is not None and vreg.startswith('Leg') and br.startswith('Leg')
                and abs(co.x - self.mid[0]) < self.mid[1]):
            return True
        if bone in self.bridge.get(vreg, ()):
            return True
        if vreg == 'Head':
            for h, t, rad, ok in self.junction:
                if bone in ok:
                    p, f = intersect_point_line(co, h, t)
                    if (co - (h + (t - h) * _clamp01(f))).length < rad:
                        return True
        return False

    def jaw_cap(self, co):
        """Phần tối đa của hàm ở `co` (1 = không giới hạn)."""
        if self.jaw is None:
            return 1.0
        h, fwd, up, L, _p = self.jaw
        p = co - h
        back = -p.dot(fwd) / L
        high = p.dot(up) / L
        f1 = _clamp01((JAW_BACK[1] - back) / (JAW_BACK[1] - JAW_BACK[0]))
        f2 = _clamp01((JAW_UP[1] - high) / (JAW_UP[1] - JAW_UP[0]))
        f3 = _clamp01((JAW_DOWN[1] + high) / (JAW_DOWN[1] - JAW_DOWN[0]))
        return f1 * f2 * f3


# ============================================================ vùng của vertex

def weights(ob):
    vg = ob.vertex_groups
    return [{vg[g.group].name: g.weight for g in v.groups if g.weight > 0} for v in ob.data.vertices]


def rest_co(ob, rig):
    M = rig.matrix_world.inverted() @ ob.matrix_world
    return [M @ v.co for v in ob.data.vertices]


def get_regions(ob):
    a = ob.data.attributes.get(ATTR)
    if a is None or a.domain != 'POINT' or a.data_type != 'INT':
        return None
    return [REGIONS[d.value] if 0 <= d.value < len(REGIONS) else None for d in a.data]


def build_regions(ob, rig, lay=None):
    """Vùng mỗi vertex = vùng có tổng weight lớn nhất. Ghi attribute, trả về list."""
    lay = lay or Layout(rig)
    W = weights(ob)
    me = ob.data
    a = me.attributes.get(ATTR)
    if a is not None and (a.domain != 'POINT' or a.data_type != 'INT'):
        me.attributes.remove(a)
        a = None
    a = a or me.attributes.new(ATTR, 'INT', 'POINT')
    vals = []
    for w in W:
        acc = Counter()
        for k, x in w.items():
            r = lay.region.get(k)
            if r:
                acc[r] += x
        vals.append(REGIONS.index(acc.most_common(1)[0][0]) if acc else REGIONS.index('Torso'))
    a.data.foreach_set('value', vals)
    me.update()
    return [REGIONS[v] for v in vals]


def regions_for(ob, rig, lay=None):
    R = get_regions(ob)
    return R if R is not None else build_regions(ob, rig, lay)


# ============================================================ rào

def _neighbours(me):
    nb = defaultdict(set)
    for e in me.edges:
        a, b = e.vertices
        nb[a].add(b)
        nb[b].add(a)
    return nb


def _nearest_bone(rig, names, co):
    B = rig.data.bones
    best = (1e30, None)
    for n in names:
        b = B[n]
        p, f = intersect_point_line(co, b.head_local, b.tail_local)
        f = _clamp01(f)
        d = (co - (b.head_local + (b.tail_local - b.head_local) * f)).length
        if d < best[0]:
            best = (d, n)
    return best[1]


def _violates(lay, w, r, co):
    deform = set(lay.deform)
    for k, x in w.items():
        if k in deform and x > 0 and not lay.allowed(k, r, co):
            return True
    if lay.jaw is not None and w.get('Jaw', 0) > 0:
        s = sum(x for k, x in w.items() if k in deform) or 1.0
        if w['Jaw'] / s > lay.jaw_cap(co) + 0.01:
            return True
    return False


def _pass(lay, W, R, C, idx, only_bad=False):
    """Một lượt luật trên các vertex `idx` (only_bad: chỉ vertex phạm luật).
    Trả về W mới (copy nông) + tập vertex đổi."""
    deform = set(lay.deform)
    out, changed = list(W), set()
    for i in idx:
        w = W[i]
        if only_bad and not _violates(lay, w, R[i], C[i]):
            continue
        keep = {k: x for k, x in w.items() if k in deform and lay.allowed(k, R[i], C[i])}
        if lay.jaw is not None and 'Jaw' in keep:
            s = sum(keep.values()) or 1.0
            cap = lay.jaw_cap(C[i])
            if keep['Jaw'] / s > cap + 1e-6:
                parent = lay.jaw[4]
                extra = keep['Jaw'] - cap * s
                keep['Jaw'] -= extra
                keep[parent] = keep.get(parent, 0.0) + extra
        if not keep:
            own = [n for n in lay.deform if lay.region.get(n) == R[i]] or lay.deform
            keep = {_nearest_bone(lay.rig, own, C[i]): 1.0}
        top = sorted(keep.items(), key=lambda t: -t[1])[:MAX_INF]
        top = [(k, x) for k, x in top if x >= MIN_W] or top[:1]
        s = sum(x for _k, x in top) or 1.0
        new = {k: x / s for k, x in top}
        if set(new) != set(w) or any(abs(new[k] - w[k]) > 1e-4 for k in new):
            changed.add(i)
        out[i] = new
    return out, changed


def _smooth(W, nb, band, iters=3, f=0.5):
    for _ in range(iters):
        new = list(W)
        for i in band:
            if not nb[i]:
                continue
            acc = defaultdict(float)
            for j in nb[i]:
                for k, x in W[j].items():
                    acc[k] += x / len(nb[i])
            new[i] = {k: (1 - f) * W[i].get(k, 0.0) + f * acc.get(k, 0.0) for k in set(W[i]) | set(acc)}
        W = new
    return W


def _write(ob, W, idx):
    vg = ob.vertex_groups
    for i in idx:
        v = ob.data.vertices[i]
        for g in list(v.groups):
            vg[g.group].remove([i])
        for k, x in W[i].items():
            (vg.get(k) or vg.new(name=k)).add([i], x, 'REPLACE')


def fence(ob, rig, smooth=True):
    """Rào weight theo vùng. Trả về (số vertex đổi, số vertex vẽ tay được giữ)."""
    lay = Layout(rig)
    R = regions_for(ob, rig, lay)
    C = rest_co(ob, rig)
    W0 = weights(ob)
    hand = cloth.hand_painted(ob)
    idx = [i for i in range(len(W0)) if i not in hand]
    # chỉ đụng vertex phạm luật (và dải làm mượt quanh chúng): weight chỗ
    # khác -- kể cả quá 4 xương / chưa normalize -- là của người dùng, xuất
    # Unity tự giới hạn 4 xương
    W, changed = _pass(lay, W0, R, C, idx, only_bad=True)
    # chỉ làm mượt quanh chỗ gỡ đi đáng kể; vụn (0.001 của hàm ở vai...) thì
    # gỡ xong là thôi, không làm xê dịch weight vẽ tay quanh đó
    stripped = {i for i in changed
                if sum(max(0.0, x - W[i].get(k, 0.0)) for k, x in W0[i].items()) >= 0.05}
    if smooth and stripped:
        nb = _neighbours(ob.data)
        band = set(stripped)
        for _ in range(2):
            band |= {j for i in band for j in nb[i]}
        band -= hand
        Ws = _smooth(W, nb, band)
        # dải chỉ nhận phần đã mượt khi nó đã phạm luật hoặc đã được gỡ; vertex
        # sạch quanh đó giữ nguyên weight cũ
        for i in band - stripped:
            if not _violates(lay, Ws[i], R[i], C[i]):
                Ws[i] = W[i]
        W, ch2 = _pass(lay, Ws, R, C, sorted(stripped))
        W, ch3 = _pass(lay, W, R, C, sorted(band - stripped), only_bad=True)
        changed |= {i for i in band if W[i] != W0[i]}
    changed -= hand
    with cloth.keep_hand([ob]) as kept:
        _write(ob, W, sorted(changed))
    ob.data.update()
    return len(changed), kept.count()


# ============================================================ khu trú

ROOT_BLEND = 0.30       # gốc chuỗi phụ được hoà vào thân trong 0.3 chiều dài đốt đầu
ISLAND_OWNER = 0.40     # đảo lưới rời thuộc về chuỗi chiếm từ 40% tổng weight
SIDE_MARGIN = 0.02      # xương .L/.R được qua đường giữa tối đa 2% chiều cao


def _seg_dist(co, head, tail):
    _p, f = intersect_point_line(co, head, tail)
    return (co - head.lerp(tail, _clamp01(f))).length


def _bone_side(name):
    parts = name.split(".")
    return next((p for p in parts[1:] if p in ('L', 'R')), None)


def _chain_zones(rig):
    """{xương chuỗi phụ: xương gốc của chuỗi}. Mỗi chuỗi nối liền là một vùng riêng."""
    out = {}
    for b in rig.data.bones:
        if not b.use_deform or not b.get(rigdef.TAG_CHAIN):
            continue
        root = b
        while root.use_connect and root.parent is not None and root.parent.get(rigdef.TAG_CHAIN):
            root = root.parent
        out[b.name] = root.name
    return out


def _islands(me, nb):
    label, sizes = [-1] * len(me.vertices), []
    for i in range(len(label)):
        if label[i] >= 0:
            continue
        k, stack, n = len(sizes), [i], 0
        label[i] = k
        while stack:
            x = stack.pop()
            n += 1
            for y in nb[x]:
                if label[y] < 0:
                    label[y] = k
                    stack.append(y)
        sizes.append(n)
    return label, sizes


def localize(ob, rig, smooth=True):
    """Gom weight về đúng bộ phận. Trả về (số vertex đổi, số vertex vẽ tay được giữ).

    Automatic weights tính theo khoảng cách nên xương tai ăn cả da đầu và tai kia.
    Mỗi vertex được xác định "nhà" (một chuỗi phụ, hoặc thân), rồi chỉ giữ xương:
    - cùng chuỗi; xương thân / chuỗi cha chỉ được hoà ở sát gốc chuỗi;
    - với vertex thân: đúng luật vùng đầu / thân / tay / chân;
    - đúng bên trái / phải, trừ dải sát đường giữa.
    """
    B = rig.data.bones
    lay = Layout(rig)
    deform = set(lay.deform)
    if not deform:
        return 0, 0
    C = rest_co(ob, rig)
    rows = weights(ob)
    W0 = [{k: x for k, x in w.items() if k in deform} for w in rows]
    hand = cloth.hand_painted(ob)
    nb = _neighbours(ob.data)
    label, sizes = _islands(ob.data, nb)
    main = max(range(len(sizes)), key=sizes.__getitem__) if sizes else -1
    zones = _chain_zones(rig)
    zs =[p.z for n in deform for p in (B[n].head_local, B[n].tail_local)]
    margin = (max(zs) - min(zs)) * SIDE_MARGIN
    mid = lay.mid[0] if lay.mid is not None else 0.0

    roots = {}                      # vùng -> (đầu xương gốc, bán kính hoà, xương cha)
    for z in set(zones.values()):
        b = B[z]
        up = b.parent
        while up is not None and not up.use_deform:
            up = up.parent
        roots[z] = (b.head_local.copy(), b.length * ROOT_BLEND, up.name if up else None)

    # Đảo lưới rời thuộc về chuỗi nào: xét HÌNH HỌC, không tin weight tự động. Vertex
    # phải nằm DỌC theo xương chuỗi; nằm phía sau gốc chuỗi thì không tính. Mắt của
    # Mothman nằm sát gốc râu, tính theo khoảng cách thì 83% mắt thành của râu.
    names = sorted(deform)
    H = np.array([tuple(B[n].head_local) for n in names])
    A = np.array([tuple(B[n].tail_local) for n in names]) - H
    P = np.array([tuple(c) for c in C])
    span = np.maximum((A * A).sum(axis=1), 1e-12)
    rel = P[:, None, :] - H[None, :, :]
    frac = np.clip((rel * A[None, :, :]).sum(axis=2) / span, 0.0, 1.0)
    gap = rel - frac[:, :, None] * A[None, :, :]
    nearest = (gap * gap).sum(axis=2).argmin(axis=1)
    near_f = frac[np.arange(len(P)), nearest]
    along = [None] * len(P)         # vùng chuỗi mà vertex thật sự nằm dọc theo
    for i, (b, f) in enumerate(zip(nearest.tolist(), near_f.tolist())):
        z = zones.get(names[b])
        if z is not None and (names[b] != z or f > 0.02):
            along[i] = z
    tally = defaultdict(Counter)
    for i, z in enumerate(along):
        tally[label[i]][z] += 1
    owner = {}                      # đảo -> các chuỗi sở hữu (cánh: hai chuỗi chung một đảo)
    for k, acc in tally.items():
        size = sizes[k]
        picked = {z for z, n in acc.items() if z is not None and n / size >= 0.15}
        share = sum(acc[z] for z in picked) / size
        owner[k] = picked if k != main and share >= ISLAND_OWNER else set()
    owned = {z for s in owner.values() for z in s}
    trunk = [n for n in lay.deform if n not in zones] or lay.deform

    home, region, lead = [None] * len(W0), [None] * len(W0), [None] * len(W0)
    for i, w in enumerate(W0):
        if not w:
            continue
        s = sum(w.values()) or 1.0
        acc, reg = Counter(), Counter()
        for k, x in w.items():
            if k in zones:
                acc[zones[k]] += x / s
            if lay.region.get(k):
                reg[lay.region[k]] += x
        mine = owner.get(label[i])
        if mine:
            inside = {z: x for z, x in acc.items() if z in mine}
            if inside:
                home[i] = max(inside, key=inside.get)
            else:
                pool = [n for n, z in zones.items() if z in mine]
                home[i] = zones[_nearest_bone(rig, pool, C[i])]
        elif label[i] == main and acc and along[i] is not None \
                and along[i] not in owned and acc.get(along[i], 0.0) >= 0.5:
            home[i] = along[i]
        region[i] = reg.most_common(1)[0][0] if reg else None
        body = {k: x for k, x in w.items() if k not in zones}
        lead[i] = max(body, key=body.get) if body else _nearest_bone(rig, trunk, C[i])

    def near_root(i, z):
        head, radius, _up = roots[z]
        return (C[i] - head).length <= radius

    # Hai chân chỉ được trộn nhau ở háng. Bàn chân đứng sát nhau cũng nằm trong dải giữa,
    # giữ luật đó ở đây thì mũi chân trái vẫn kéo mũi chân phải.
    thighs = [B[l.deform[0]] for l in rigdef.limbs_for(rig)
              if l.kind == 'LEG' and l.deform and l.deform[0] in B]
    groin = (sum(t.head_local.z + t.tail_local.z for t in thighs) / (2 * len(thighs))
             if thighs else None)

    def allowed_part(i, w):
        keep, z_home = {}, home[i]
        mine = owner.get(label[i])
        for k, x in w.items():
            side = _bone_side(k)
            dx = C[i].x - mid
            own = lay.region.get(k) or ""
            if groin is not None and own.startswith('Leg') and (region[i] or "").startswith('Leg') \
                    and own != region[i] and C[i].z < groin:
                continue
            # Chỉ tay, chân, chuỗi phụ. Mí, mày, môi .L/.R vốn hoà qua sống mũi.
            limb = k in zones or (lay.region.get(k) or "").startswith(('Arm', 'Leg'))
            if limb and side and ((side == 'L' and dx < -margin) or (side == 'R' and dx > margin)):
                continue
            z = zones.get(k)
            if mine:                    # đảo rời của chuỗi: chỉ xương của các chuỗi đó
                if z in mine:
                    keep[k] = x
            elif z is not None:
                if z in owned or label[i] != main:
                    continue            # chuỗi đã có lưới riêng thì không ăn sang lưới khác
                if z == z_home:
                    keep[k] = x
                elif z_home is None:
                    if near_root(i, z):
                        keep[k] = x
                elif roots[z_home][2] in zones and zones[roots[z_home][2]] == z \
                        and near_root(i, z_home):
                    keep[k] = x         # chuỗi con hoà vào chuỗi cha ở sát gốc
            elif z_home is not None:
                if k == roots[z_home][2] and near_root(i, z_home):
                    keep[k] = x
            elif lay.allowed(k, region[i], C[i]):
                keep[k] = x
        return keep

    def clean(i, w):
        keep, z_home = allowed_part(i, w), home[i]
        if not keep:
            pool = [n for n, z in zones.items() if z == z_home] if z_home else [lead[i]]
            keep = {_nearest_bone(rig, pool, C[i]): 1.0}
        top = sorted(keep.items(), key=lambda t: -t[1])[:MAX_INF]
        top = [(k, x) for k, x in top if x >= MIN_W] or top[:1]
        s = sum(x for _k, x in top) or 1.0
        return {k: x / s for k, x in top}

    todo = [i for i, w in enumerate(W0) if w and i not in hand]
    # Chỉ đụng vertex có xương sai chỗ. Vertex sạch giữ nguyên từng số, kể cả quá
    # 4 xương: đó có thể là weight vẽ tay, xuất Unity tự giới hạn sau.
    W = list(W0)
    for i in todo:
        if len(allowed_part(i, W0[i])) < len(W0[i]):
            W[i] = clean(i, W0[i])
    stripped = {i for i in todo
                if sum(max(0.0, x - W[i].get(k, 0.0)) for k, x in W0[i].items()) >= 0.05}
    if smooth and stripped:
        # Chỗ cắt mạnh (háng) cần thêm một vòng vertex để không thành bậc gãy;
        # chỗ gỡ vụn thì để yên hàng xóm.
        strong = {i for i in stripped
                  if sum(max(0.0, x - W[i].get(k, 0.0)) for k, x in W0[i].items()) >= 0.15}
        band = (stripped | {j for i in strong for j in nb[i]}) - hand
        band = {i for i in band if W0[i]}
        smoothed = _smooth(W, nb, band, iters=3)
        for i in band:
            W[i] = clean(i, smoothed[i])
    changed = [i for i in todo
               if set(W[i]) != set(W0[i]) or any(abs(W[i][k] - W0[i][k]) > 1e-4 for k in W[i])]
    vg = ob.vertex_groups
    with cloth.keep_hand([ob]) as kept:
        for i in changed:
            for g in list(ob.data.vertices[i].groups):
                if vg[g.group].name in deform:
                    vg[g.group].remove([i])
            for k, x in W[i].items():
                (vg.get(k) or vg.new(name=k)).add([i], x, 'REPLACE')
    ob.data.update()
    return len(changed), kept.count()


# ============================================================ khám

def check_static(ob, rig, lay=None, R=None):
    """{loại lỗi: [ví dụ]} -- không sửa gì."""
    lay = lay or Layout(rig)
    R = R or regions_for(ob, rig, lay)
    C = rest_co(ob, rig)
    W = weights(ob)
    deform = set(lay.deform)
    B = rig.data.bones
    height = max(max(c.z for c in C) - min(c.z for c in C), 1e-6) if C else 1.0
    bad = defaultdict(list)
    leak = Counter()
    for i, w in enumerate(W):
        if not w:
            bad["không có weight"].append(i)
            continue
        dw = sum(x for k, x in w.items() if k in deform)
        if len(w) > MAX_INF:
            bad["quá %d xương" % MAX_INF].append(i)
        if abs(dw - 1) > 1e-3:
            bad["chưa normalize"].append(i)
        for k, x in w.items():
            if k not in deform:
                continue
            if x < MIN_W:
                bad["weight vụn (<%.2f)" % MIN_W].append((i, k))
            if x >= 0.02 and not lay.allowed(k, R[i], C[i]):
                bad["xương lấn sai vùng"].append((i, k, round(x, 2)))
                leak[(k, R[i])] += 1
            if k == 'Jaw' and lay.jaw is not None and x > lay.jaw_cap(C[i]) * max(dw, 1e-6) + 0.02:
                bad["hàm ăn ra sau gáy / lên đỉnh đầu"].append((i, round(x, 2)))
            if x >= 0.05:
                b = B[k]
                p, f = intersect_point_line(C[i], b.head_local, b.tail_local)
                p = b.head_local + (b.tail_local - b.head_local) * _clamp01(f)
                if (C[i] - p).length > max(0.08 * height, 3 * b.length):
                    bad["weight xa xương"].append((i, k, round(x, 2)))
    # trái / phải
    kd = kdtree.KDTree(len(C))
    for i, c in enumerate(C):
        kd.insert(c, i)
    kd.balance()
    tol = height * 0.002
    for i, c in enumerate(C):
        if c.x <= tol:
            continue
        _co, j, d = kd.find(Vector((-c.x, c.y, c.z)))
        if j is None or d > tol:
            continue
        a, b = W[i], {_mirror(k): x for k, x in W[j].items()}
        diff = max((abs(a.get(k, 0) - b.get(k, 0)) for k in set(a) | set(b)), default=0)
        if diff > SYM_TOL:
            bad["lệch trái / phải"].append((i, j, round(diff, 2)))
    return bad, leak


def _mirror(n):
    for a, b in (('.L', '.R'), ('.R', '.L'), ('_L', '_R'), ('_R', '_L')):
        if a in n:
            return n.replace(a, b, 1)
    return n


def check_poses(ob, rig, lay=None, R=None):
    """[(tên tư thế, {vùng bị kéo sai: số vertex}, độ giãn lớn nhất, số vertex sau gáy bị hàm kéo)]."""
    lay = lay or Layout(rig)
    R = R or regions_for(ob, rig, lay)
    C = rest_co(ob, rig)
    W = weights(ob)
    deform = lay.deform
    di = {n: j for j, n in enumerate(deform)}
    n = len(C)
    Wm = np.zeros((n, len(deform)))
    for i, w in enumerate(W):
        s = sum(x for k, x in w.items() if k in di)
        for k, x in w.items():
            if k in di and s > 0:
                Wm[i, di[k]] = x / s
    V = np.array([tuple(c) + (1.0,) for c in C]) if n else np.zeros((0, 4))
    height = float(V[:, 2].max() - V[:, 2].min()) if n else 1.0
    edges = np.array([tuple(e.vertices) for e in ob.data.edges]) if len(ob.data.edges) else np.zeros((0, 2), int)
    l0 = np.linalg.norm(V[edges[:, 0], :3] - V[edges[:, 1], :3], axis=1) if len(edges) else np.zeros(0)
    poses = [("chi / lưng / cổ #%d: %s" % (k + 1, ", ".join("%s %s%+d°" % (b, a, d) for b, a, d in p)), p)
             for k, p in enumerate(bakeweights.training_poses(rig))]
    if lay.jaw is not None:
        poses.append(("há miệng: Jaw X+20°", [('Jaw', 'X', 20)]))
    out = []
    for label, ops in poses:
        S = bakeweights.skin_mats(rig, deform, ops)                     # (bones, 4, 4)
        P = np.einsum('vb,bij,vj->vi', Wm, S, V)[:, :3]
        mv = np.linalg.norm(P - V[:, :3], axis=1)
        B = rig.data.bones
        moved = set()
        for b, _a, _d in ops:
            moved.add(b)
            moved.update(c.name for c in B[b].children_recursive)
        regs = {lay.region.get(b) for b in moved if b in lay.region}
        ok_regs = set(regs)
        for reg in REGIONS:
            if any(b in lay.bridge.get(reg, ()) for b in moved):
                ok_regs.add(reg)
        leaks = Counter()
        jaw_back = 0
        for i in np.nonzero(mv > MOVE * height)[0]:
            r = R[i]
            if r in ok_regs:
                if ops[0][0] == 'Jaw' and lay.jaw_cap(C[i]) < 0.05:
                    jaw_back += 1
                continue
            if (lay.mid is not None and r and r.startswith('Leg') and any(x and x.startswith('Leg') for x in regs)
                    and abs(C[i].x - lay.mid[0]) < lay.mid[1]):
                continue
            leaks[r] += 1
        worst = 0.0
        if len(edges):
            l1 = np.linalg.norm(P[edges[:, 0]] - P[edges[:, 1]], axis=1)
            ok = l0 > 1e-7
            worst = float(np.abs(l1[ok] / l0[ok] - 1).max()) if ok.any() else 0.0
        out.append((label, dict(leaks), worst, jaw_back))
    return out


def report(ob, rig):
    """Khám đủ, ghi text block REPORT. Trả về (số loại lỗi tĩnh, số tư thế có lỗi, text)."""
    lay = Layout(rig)
    R = regions_for(ob, rig, lay)
    bad, leak = check_static(ob, rig, lay, R)
    poses = check_poses(ob, rig, lay, R)
    cnt = Counter(R)
    lines = ["KHÁM WEIGHT -- %s (rig %s), %d vertex" % (ob.name, rig.name, len(R)), "",
             "Vùng vertex: " + ", ".join("%s %d" % (REGION_LABEL[r], cnt[r]) for r in REGIONS if cnt[r]),
             "Vùng xương: " + "; ".join("%s: %d xương" % (REGION_LABEL[r], sum(1 for b in lay.deform if lay.region[b] == r))
                                      for r in REGIONS),
             "", "KIỂM TĨNH:"]
    if not bad:
        lines.append("  sạch")
    for k, ex in sorted(bad.items(), key=lambda t: -len(t[1])):
        lines.append("  %-34s %5d   vd: %s" % (k, len(ex), ex[:4]))
    if leak:
        lines.append("  xương lấn vùng nhiều nhất:")
        for (b, r), c in leak.most_common(8):
            lines.append("    %-22s -> %-10s %d vertex" % (b, REGION_LABEL.get(r, r), c))
    lines += ["", "KIỂM BẰNG TƯ THẾ (vertex dịch > %.1f%% chiều cao):" % (MOVE * 100)]
    nbad = 0
    for label, leaks, worst, jaw_back in poses:
        flag = []
        if leaks:
            flag.append("KÉO SAI VÙNG " + ", ".join("%s %d" % (REGION_LABEL.get(r, r), c) for r, c in leaks.items()))
        if jaw_back:
            flag.append("hàm kéo sau gáy / đỉnh đầu %d vertex" % jaw_back)
        if worst > STRETCH and not label.startswith("há miệng"):
            flag.append("giãn mạnh %.2f" % worst)
        nbad += bool(flag)
        lines.append("  %-60s %s" % (label[:60], " | ".join(flag) or "ok"))
    lines += ["", "Sửa: Sửa weight… → Rào weight theo vùng. Vùng của vertex sai thì chọn vertex trong",
              "Edit Mode → Gán vùng (attribute %s)." % ATTR]
    text = "\n".join(lines)
    t = bpy.data.texts.get(REPORT) or bpy.data.texts.new(REPORT)
    t.clear()
    t.write(text)
    return len(bad), nbad, text


# ============================================================ toán tử

def _target(context):
    rig, body = cloth._body_rig(context)
    ob = context.object
    if ob is not None and ob.type == 'MESH' and ob.find_armature() is not None:
        body, rig = ob, ob.find_armature()
    return rig, body


class SRP_OT_weight_fence(Operator):
    """Gỡ weight của xương lấn sang vùng không phải của nó (vai lên má, hàm ra sau
    gáy, chân bên này sang chân bên kia...), làm mượt chỗ vừa gỡ, tối đa 4 xương,
    normalize. Vertex vẽ tay giữ nguyên"""
    bl_idname = "srp.weight_fence"
    bl_label = "Rào weight theo vùng"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        rig, body = _target(context)
        if rig is None or body is None:
            self.report({'ERROR'}, "Chưa có mesh thân đã bind vào rig")
            return {'CANCELLED'}
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        n, kept = fence(body, rig)
        bad, _leak = check_static(body, rig)
        left = len(bad.get("xương lấn sai vùng", ())) + len(bad.get("hàm ăn ra sau gáy / lên đỉnh đầu", ()))
        self.report({'INFO'}, "Rào weight %s: sửa %d vertex, giữ %d vertex vẽ tay%s"
                    % (body.name, n, kept, ", còn %d chỗ lấn (ở vertex vẽ tay)" % left if left else ""))
        return {'FINISHED'}


class SRP_OT_weight_localize(Operator):
    """Gom weight về đúng bộ phận: xương tai không ăn da đầu và tai kia, cánh không ăn
    tay, trái không ăn phải. Vertex vẽ tay giữ nguyên"""
    bl_idname = "srp.weight_localize"
    bl_label = "Khu trú weight"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        rig, body = _target(context)
        if rig is None or body is None:
            self.report({'ERROR'}, "Chưa có mesh thân đã bind vào rig")
            return {'CANCELLED'}
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        n, kept = localize(body, rig)
        self.report({'INFO'}, "Khu trú weight %s: sửa %d vertex, giữ %d vertex vẽ tay"
                    % (body.name, n, kept))
        return {'FINISHED'}


class SRP_OT_weight_check(Operator):
    """Khám weight mesh thân: sai vùng, chưa normalize, quá 4 xương, lệch trái/phải;
    rồi cho nhân vật qua các tư thế (tay, chân, lưng, cổ, há miệng) xem vùng nào bị
    kéo theo sai và lưới giãn quá mạnh. Không sửa gì -- báo cáo ở text block
    SRP_Weight_Check"""
    bl_idname = "srp.weight_check"
    bl_label = "Khám weight"
    bl_options = {'REGISTER'}

    def execute(self, context):
        rig, body = _target(context)
        if rig is None or body is None:
            self.report({'ERROR'}, "Chưa có mesh thân đã bind vào rig")
            return {'CANCELLED'}
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        nst, npose, _t = report(body, rig)
        lvl = {'WARNING'} if (nst or npose) else {'INFO'}
        self.report(lvl, "Khám weight %s: %d loại lỗi tĩnh, %d tư thế có lỗi -- xem text block %s"
                    % (body.name, nst, npose, REPORT))
        return {'FINISHED'}


class SRP_OT_weight_regions(Operator):
    """Vùng của vertex (đầu / thân / tay / chân) cho Rào weight và Khám weight"""
    bl_idname = "srp.weight_regions"
    bl_label = "Vùng weight"
    bl_options = {'REGISTER', 'UNDO'}

    action: EnumProperty(items=(('BUILD', "Tính lại vùng", "Tính lại vùng mọi vertex theo weight hiện tại"),
                                ('ASSIGN', "Gán vùng", "Gán vùng cho các vertex đang chọn (Edit Mode)"),
                                ('SELECT', "Chọn vùng", "Chọn mọi vertex của một vùng (Edit Mode)")))
    region: EnumProperty(name="Vùng", items=[(r, REGION_LABEL[r], "") for r in REGIONS])

    @classmethod
    def description(cls, context, props):
        return {'BUILD': "Tính lại vùng của mọi vertex theo weight hiện tại (vùng có tổng weight lớn nhất). "
                         "Chỉ nên làm khi weight đã gần đúng",
                'ASSIGN': "Gán vùng cho các vertex đang chọn trong Edit Mode -- dùng khi vùng tự tính sai",
                'SELECT': "Chọn mọi vertex thuộc một vùng trong Edit Mode để soát"}[props.action]

    def execute(self, context):
        rig, body = _target(context)
        if rig is None or body is None:
            self.report({'ERROR'}, "Chưa có mesh thân đã bind vào rig")
            return {'CANCELLED'}
        if self.action == 'BUILD':
            mode = context.mode
            if mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            R = build_regions(body, rig)
            c = Counter(R)
            self.report({'INFO'}, "Vùng: " + ", ".join("%s %d" % (REGION_LABEL[r], c[r]) for r in REGIONS if c[r]))
            return {'FINISHED'}
        if context.object is not body or context.mode != 'EDIT_MESH':
            self.report({'ERROR'}, "Vào Edit Mode của %s trước" % body.name)
            return {'CANCELLED'}
        bpy.ops.object.mode_set(mode='OBJECT')
        R = regions_for(body, rig)
        a = body.data.attributes[ATTR]
        k = REGIONS.index(self.region)
        n = 0
        if self.action == 'ASSIGN':
            for v in body.data.vertices:
                if v.select:
                    a.data[v.index].value = k
                    n += 1
        else:
            for v in body.data.vertices:
                v.select = R[v.index] == self.region
                n += v.select
        bpy.ops.object.mode_set(mode='EDIT')
        self.report({'INFO'}, "%s %d vertex: %s" % ("Gán" if self.action == 'ASSIGN' else "Chọn", n,
                                                    REGION_LABEL[self.region]))
        return {'FINISHED'}


def draw_regions(L, context):
    """Hộp nhỏ: vùng vertex + khám weight."""
    rig, body = _target(context)
    box = L.box()
    head = box.row(align=True)
    head.label(text="Vùng weight & khám", icon='MOD_VERTEX_WEIGHT')
    if body is None:
        box.label(text="Chưa có mesh thân đã bind", icon='INFO')
        return
    R = get_regions(body)
    col = box.column(align=True)
    if R is None:
        col.label(text="%s chưa có vùng -- Khám / Rào sẽ tự tính" % body.name, icon='DOT')
    else:
        c = Counter(R)
        col.label(text=", ".join("%s %d" % (REGION_LABEL[r], c[r]) for r in REGIONS if c[r]), icon='DOT')
    box.operator("srp.weight_localize", icon='MOD_VERTEX_WEIGHT')
    row = box.row(align=True)
    row.operator("srp.weight_check", icon='VIEWZOOM')
    row.operator("srp.weight_regions", text="", icon='FILE_REFRESH').action = 'BUILD'
    if context.mode == 'EDIT_MESH' and context.object is body:
        for act, label in (('ASSIGN', "Gán vùng cho vertex đang chọn:"), ('SELECT', "Chọn vertex của vùng:")):
            box.label(text=label)
            grid = box.grid_flow(columns=3, even_columns=True, align=True)
            for r in REGIONS:
                op = grid.operator("srp.weight_regions", text=REGION_LABEL[r])
                op.action, op.region = act, r


CLASSES = (SRP_OT_weight_fence, SRP_OT_weight_localize, SRP_OT_weight_check,
           SRP_OT_weight_regions)
