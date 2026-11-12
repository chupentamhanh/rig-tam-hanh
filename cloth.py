"""Bind quần áo, tóc, giày, phụ kiện là mesh RIÊNG vào rig.

Trước đây `srp.bind` chỉ bind mesh thân + mắt + răng/lưỡi/mày. Trên chính
file Kid, `hair`, `hoodie`, `shoes`, `short` không gắn gì vào rig: animate thì
đứng yên, xuất Unity thì không có.

Ba cách bind cho mỗi mesh:
- CHÉP TỪ THÂN (mặc định): mỗi vertex quần áo lấy trọng số của điểm GẦN NHẤT
  trên bề mặt thân (nội suy trong tam giác). Áo bám đúng như da bên dưới, nên
  khi gập tay áo không đâm xuyên da như automatic weights hay làm -- hai bên
  dùng hai bộ trọng số khác nhau.
- AUTOMATIC WEIGHTS: như bind thân (bỏ xương mặt ra). Cho đồ rộng / xa thân.
- GẮN CỨNG: 100% vào một xương (tóc, mũ, kính -> Head). Skin chứ KHÔNG
  parent-bone: `generate.mount_bones` coi xương có object gắn-bone là xương đỡ
  phụ kiện và loại nó khỏi automatic weights -- gắn tóc vào Head kiểu đó thì
  lần bind thân sau Head mất hết da đầu.
"""

import bpy
from bpy.props import EnumProperty, IntProperty, PointerProperty, StringProperty
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.interpolate import poly_3d_calc

from . import prefs, rigdef

MODES = (
    ('TRANSFER', "Chép từ thân", "Lấy trọng số của điểm gần nhất trên mesh thân -- "
                                 "áo, quần, giày bám sát người"),
    ('AUTO', "Automatic", "Automatic weights như bind thân -- đồ rộng, xa thân"),
    ('RIGID', "Gắn cứng", "100% vào một xương -- tóc, mũ, kính, phụ kiện cứng"),
)
MAX_INFLUENCE = 4
# tên gợi ý đồ cứng gắn vào đầu
RIGID_WORDS = ('hair', 'toc', 'tóc', 'hat', 'cap', 'helmet', 'mu', 'mũ', 'glass',
               'kinh', 'kính', 'mask', 'horn', 'sung', 'sừng')


class SRP_ClothMesh(bpy.types.PropertyGroup):
    """Một mesh quần áo / phụ kiện + cách bind."""
    mesh: PointerProperty(name="Mesh", type=bpy.types.Object,
                          poll=lambda self, obj: obj.type == 'MESH')
    mode: EnumProperty(name="Cách bind", default='TRANSFER', items=MODES)
    bone: StringProperty(name="Xương", default="Head",
                         description="Xương gắn cứng vào (chỉ dùng khi Gắn cứng)")


def guess_mode(obj):
    n = obj.name.lower()
    words = set(n.replace('.', '_').replace('-', '_').split('_'))
    return 'RIGID' if any(w in words or n.startswith(w) for w in RIGID_WORDS) else 'TRANSFER'


def deformed_by(obj, rig):
    return any(m.type == 'ARMATURE' and m.object is rig for m in obj.modifiers)


def _bbox(obj, pad=0.0):
    pts = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    lo = [min(p[i] for p in pts) - pad for i in range(3)]
    hi = [max(p[i] for p in pts) + pad for i in range(3)]
    return lo, hi


def candidates(context, rig, body):
    """Mesh trong scene nằm quanh nhân vật mà chưa ai bind."""
    from . import generate
    settings = context.scene.srp_generate
    taken = {body} | {o for _b, o in generate.eyeball_meshes(context)}
    taken |= {o for _r, o in generate.face_part_meshes(context)}
    taken |= {e.mesh for e in settings.cloth_meshes if e.mesh}
    # mesh phụ chép weight từ nhân vật mẫu lúc bind (lông mày...) -- xem fitref
    fit = body.get("srp_fit")
    if fit:
        taken |= {bpy.data.objects.get(n) for n in fit.get("pairs", {})}
    lo, hi = _bbox(body, pad=0.15)
    out = []
    for o in context.view_layer.objects:
        if o.type != 'MESH' or o in taken or o.hide_render or not o.visible_get():
            continue
        if any(m.type == 'ARMATURE' and m.object is not None for m in o.modifiers):
            continue
        if o.parent is not None and o.parent.type == 'ARMATURE':
            continue
        olo, ohi = _bbox(o)
        if all(olo[i] <= hi[i] and ohi[i] >= lo[i] for i in range(3)):
            out.append(o)
    return out


# ============================================================ trọng số

def _clean(obj, rig):
    """Gỡ mọi liên kết cũ với rig: modifier, nhóm trùng tên xương, parent."""
    for m in [m for m in obj.modifiers if m.type == 'ARMATURE']:
        obj.modifiers.remove(m)
    names = {b.name for b in rig.data.bones}
    for g in [g for g in obj.vertex_groups if g.name in names]:
        obj.vertex_groups.remove(g)
    mw = obj.matrix_world.copy()
    obj.parent = None
    obj.matrix_world = mw


def _attach(obj, rig):
    mw = obj.matrix_world.copy()
    obj.parent = rig
    obj.parent_type = 'OBJECT'
    obj.matrix_world = mw
    mod = obj.modifiers.new("Armature", 'ARMATURE')
    mod.object = rig
    # modifier phải đứng ĐẦU: sau Subdivision/Solidify là biến dạng lưới đã đổi
    obj.modifiers.move(len(obj.modifiers) - 1, 0)


def _write(obj, rows, limit=MAX_INFLUENCE):
    """rows: [{tên xương: trọng số}] mỗi vertex -> nhóm vertex, giữ `limit`, tổng 1."""
    groups = {}
    for i, row in enumerate(rows):
        top = sorted(row.items(), key=lambda kv: -kv[1])[:limit]
        tot = sum(w for _n, w in top)
        if tot <= 0:
            continue
        for n, w in top:
            g = groups.get(n) or obj.vertex_groups.get(n) or obj.vertex_groups.new(name=n)
            groups[n] = g
            g.add([i], w / tot, 'REPLACE')
    return len(groups)


def remap_bones(rig):
    """{xương: xương thay thế} cho quần áo chép từ thân: Head và mọi xương dưới
    nó -> xương cha của Head (Neck), ngón / lòng bàn tay -> bàn tay.

    Chép thẳng thì cổ áo hoodie của Kid nhận Jaw (59 vertex, trọng số 1.0),
    môi dưới, mí mắt -- há miệng là cổ áo há theo; cổ tay áo nhận Palm.* --
    nắm tay là tay áo co theo. Lấy theo CÂY chứ không theo danh sách tên:
    `generate.face_bone_names` chỉ có Jaw + mắt, không có môi, mí, mày.

    Head cũng phải dồn đi: mũ trùm sát gáy chép Head = 1.0, quay đầu 40° là
    nửa mũ quay theo đầu, nửa kia đứng theo lưng -- mũ rách thành một cái vây
    dựng cạnh đầu (thấy trên viewport, tư thế cúi + quay đầu). Đồ phải đi theo
    đầu (mũ, nón, kính) thì dùng Gắn cứng.
    """
    from . import posekey
    B = rig.data.bones
    out = {}
    head = posekey.head_bone(rig)
    if head is not None:
        up = head.parent.name if head.parent else head.name
        out[head.name] = up
        for c in head.children_recursive:
            out[c.name] = up
    for l in rigdef.limbs_for(rig):
        hand = B.get(l.deform[-1]) if l.kind == 'ARM' else None
        if hand is not None:
            for c in hand.children_recursive:
                out[c.name] = hand.name
    return out


def transfer(obj, body, rig, remap=None, current=False, allowed=None, smooth_ok=True,
             limit=MAX_INFLUENCE):
    """Trọng số điểm gần nhất trên bề mặt thân. Trả về (số nhóm, xa nhất m).

    `remap` None = `remap_bones` (quần áo không theo đầu / ngón); `current`:
    đọc weight thân đang có, không thay bằng bản "da gốc" (thân là nguồn chuẩn
    -- người dùng đã tự vẽ xong); `allowed`: chỉ giữ các xương này (lông mày chỉ
    theo xương của nó); `smooth_ok` False: không làm mượt (mesh nhỏ dán da)."""
    deform = {b.name for b in rig.data.bones if b.use_deform}
    if remap is None:
        remap = remap_bones(rig)
    mw = body.matrix_world
    verts = [mw @ v.co for v in body.data.vertices]
    body.data.calc_loop_triangles()
    tris = [tuple(t.vertices) for t in body.data.loop_triangles]
    bvh = BVHTree.FromPolygons(verts, tris)
    W = []
    src = ([{n: w for n, w in r.items() if n in deform and w > 0} for r in _rows_of(body, exact=True)]
           if current else skin_rows(body, deform))
    for raw in src:
        row = {}
        for n, w in raw.items():
            n = remap.get(n, n)
            row[n] = row.get(n, 0.0) + w
        W.append(row)
    omw = obj.matrix_world
    rows, far = [], 0.0
    for v in obj.data.vertices:
        loc, _n, ti, dist = bvh.find_nearest(omw @ v.co)
        if ti is None:
            rows.append({})
            continue
        far = max(far, dist)
        tri = tris[ti]
        acc = {}
        for idx, f in zip(tri, poly_3d_calc([verts[k] for k in tri], loc)):
            for n, w in W[idx].items():
                acc[n] = acc.get(n, 0.0) + w * f
        if allowed is not None:
            acc = {n: w for n, w in acc.items() if n in allowed}
        rows.append(acc)
    blo, bhi = _bbox(body)
    hb = bhi[2] - blo[2]
    limb_cull(obj, rig, rows, hb)
    passes, scores = pick_smoothing(obj, rig, rows, height=hb) if smooth_ok else (0, {})
    if passes:
        smooth(obj, rows, passes, height=hb)
    transfer.last = (passes, scores)
    return _write(obj, rows, limit), far


LIMB_CULL = (0.02, 0.06)    # dư khoảng cách (phần chiều cao) bắt đầu / hết bỏ weight


def _seg_dist(p, a, b):
    ab = b - a
    t = max(0.0, min(1.0, (p - a).dot(ab) / max(ab.length_squared, 1e-12)))
    return (p - (a + ab * t)).length


def limb_cull(obj, rig, rows, height):
    """Bỏ weight xương CHI ở vertex nằm xa đoạn xương đó (tại chỗ).

    Chép từ da = nội suy trong tam giác da. Cẳng chân Adult gần như chỉ có vòng
    gối (Thigh 0.43) và vòng cổ chân (Foot 0.3): vòng giữa cẳng của QUẦN nhận
    15% Thigh + 12% Foot -- gập gối là cẳng quần teo lại ngay dưới gối. Một xương
    chi chỉ giữ weight nếu đoạn xương của nó không xa hơn hẳn đoạn xương gần
    nhất trong hàng (dư > LIMB_CULL[1] chiều cao là bỏ hẳn). Ở vòng gối hai
    đoạn cách gần như nhau nên vẫn trộn. Xương thân (Pelvis, Spine) không đụng:
    dải hông là việc của hip_band.
    """
    B = rig.data.bones
    limb = set()
    for l in rigdef.limbs_for(rig):
        limb |= {n for n in l.deform if n in B}
    if not limb:
        return 0
    seg = {n: (B[n].head_local, B[n].tail_local) for n in limb}
    to_rig = rig.matrix_world.inverted() @ obj.matrix_world
    lo_, hi_ = LIMB_CULL[0] * height, LIMB_CULL[1] * height
    changed = 0
    for i, row in enumerate(rows):
        names = [n for n in row if n in seg and row[n] > 0]
        if len(names) < 2:
            continue
        p = to_rig @ obj.data.vertices[i].co
        d = {n: _seg_dist(p, *seg[n]) for n in names}
        dmin = min(d.values())
        hit = False
        for n in names:
            ex = d[n] - dmin
            if ex <= lo_:
                continue
            f = 0.0 if ex >= hi_ else 1.0 - (ex - lo_) / (hi_ - lo_)
            row[n] *= f
            hit = True
        if hit:
            changed += 1
            for n in [n for n, w in row.items() if w <= 1e-6]:
                del row[n]
    return changed


# ============================================================ tự chọn mức làm mượt
#
# Làm mượt có lợi hay có hại tuỳ MÓN ĐỒ (đo trên Kid, 5 tư thế):
#   hoodie: cạnh giãn 127 (0 lượt) -> 42 (8 lượt)   -- chân mũ chồm qua vai
#   short : cạnh giãn  15 (0 lượt) -> 45 (8 lượt)   -- dốc hông/đùi vốn đúng
# Nên mỗi món tự thử vài mức trên một bộ tư thế tổng hợp và giữ mức ít cạnh giãn
# nhất. Biến dạng tính bằng LBS thuần Python từ ma trận xương tổng hợp -- không
# pose rig thật, không đụng constraint, nhanh.

SMOOTH_TRY = (0, 4, 8)


def _test_poses(rig):
    """[[(tên xương, trục world, độ)]] -- buông tay, giơ trước, co khuỷu, bước, cúi, quay cổ."""
    from . import posekey
    out = []
    arms = [l for l in rigdef.limbs_for(rig) if l.kind == 'ARM']
    legs = [l for l in rigdef.limbs_for(rig) if l.kind == 'LEG']
    sgn = lambda l: 1 if l.side == 'L' else -1
    out.append([(l.deform[0], 'Y', 75 * sgn(l)) for l in arms])
    out.append([(l.deform[0], 'Z', -80 * sgn(l)) for l in arms]
               + [(l.deform[1], 'Z', -70 * sgn(l)) for l in arms])
    out.append([(l.deform[0], 'X', 60 if l.side == 'L' else -30) for l in legs]
               + [(l.deform[1], 'X', -70) for l in legs])
    head = posekey.head_bone(rig)
    chain = []
    b = head.parent if head is not None else None
    while b is not None and len(chain) < 4:
        chain.append(b.name)
        b = b.parent
    if chain:
        out.append([(n, 'X', 15) for n in chain[1:3]] + [(chain[0], 'Z', 35)])
    return out


def _deform_mats(rig, pose):
    """{xương: ma trận biến dạng (không gian armature)} cho một tư thế tổng hợp."""
    from mathutils import Matrix
    import math
    rot = {}
    for n, axis, deg in pose:
        if n in rig.data.bones:
            ax = rig.matrix_world.inverted().to_3x3() @ Vector({'X': (1, 0, 0), 'Y': (0, 1, 0),
                                                                'Z': (0, 0, 1)}[axis])
            rot[n] = Matrix.Rotation(math.radians(deg), 4, ax.normalized())
    D = {}
    for b in sorted(rig.data.bones, key=lambda b: len(b.parent_recursive)):
        m = D[b.parent.name] if b.parent else Matrix()
        if b.name in rot:
            h = b.head_local
            m = m @ Matrix.Translation(h) @ rot[b.name] @ Matrix.Translation(-h)
        D[b.name] = m
    return D


def stretch_score(obj, rig, rows, poses=None):
    """Số cạnh giãn > 1.6 lần VÀ > 0.3% kích thước mesh ở ít nhất một tư thế."""
    poses = poses or _test_poses(rig)
    M = rig.matrix_world.inverted() @ obj.matrix_world
    rest = [M @ v.co for v in obj.data.vertices]
    edges = [tuple(e.vertices) for e in obj.data.edges]
    lo = Vector(tuple(min(p[k] for p in rest) for k in range(3)))
    hi = Vector(tuple(max(p[k] for p in rest) for k in range(3)))
    tol = (hi - lo).length * 0.003
    norm = []
    for r in rows:
        top = sorted(r.items(), key=lambda kv: -kv[1])[:MAX_INFLUENCE]
        tot = sum(w for _n, w in top) or 1.0
        norm.append([(n, w / tot) for n, w in top])
    bad = set()
    for pose in poses:
        D = _deform_mats(rig, pose)
        pos = []
        for p, ws in zip(rest, norm):
            q = Vector()
            for n, w in ws:
                q += (D[n] @ p) * w if n in D else p * w
            pos.append(q)
        for k, (a, b) in enumerate(edges):
            l0 = (rest[a] - rest[b]).length
            l1 = (pos[a] - pos[b]).length
            if l1 > 1.6 * l0 and l1 - l0 > tol:
                bad.add(k)
    return len(bad)


def pick_smoothing(obj, rig, rows, height=None):
    """(số lượt làm mượt tốt nhất, {lượt: điểm})."""
    poses = _test_poses(rig)
    scores = {}
    for n in SMOOTH_TRY:
        trial = [dict(r) for r in rows]
        if n:
            smooth(obj, trial, n, height=height)
        scores[n] = stretch_score(obj, rig, trial, poses)
    best = min(scores, key=lambda n: (scores[n], n))
    return best, scores


SMOOTH_PASSES = 8
SMOOTH_ALPHA = 0.5
# Chỉ làm mượt vertex có BẬC: tổng chênh trọng số với một vertex kề vượt
# ngưỡng này. Làm mượt đều tay thì có lợi cho hoodie (cạnh giãn 127 -> 42) nhưng
# hại quần short vốn đã có dốc mượt (15 -> 45): trọng số đùi lan lên hông.
SMOOTH_JUMP = 0.5
# Cạnh dài hơn ngần này chiều cao nhân vật thì không trộn weight qua nó (xem smooth)
SMOOTH_REACH = 0.04


def neighbours(obj):
    adj = [[] for _v in obj.data.vertices]
    for e in obj.data.edges:
        a, b = e.vertices
        adj[a].append(b)
        adj[b].append(a)
    return adj


def smooth(obj, rows, passes=None, alpha=None, height=None):
    """Làm mượt trọng số dọc theo lưới quần áo (tại chỗ).

    Chép điểm gần nhất cho ra BẬC ở nơi hai vertex kề nhau có điểm da gần nhất
    ở hai vùng khác hẳn: chân mũ hoodie chồm qua vai, vertex này gần cổ (Neck
    1.0), vertex kề gần đầu cánh tay (Bicep 0.6) -- buông tay xuôi là cạnh đó
    giãn 3.5 lần (đo trên Kid). Trộn với trung bình vertex kề vài lượt là bậc
    thành dốc.
    """
    passes = SMOOTH_PASSES if passes is None else passes
    alpha = SMOOTH_ALPHA if alpha is None else alpha
    adj = neighbours(obj)
    # Hàng xóm chỉ được trộn theo KHOẢNG CÁCH: cạnh dài hơn SMOOTH_REACH chiều
    # cao thì không trộn. Lưới quần Adult thưa (cạnh 6-19 cm): vertex giữa cẳng
    # nối thẳng vòng gối và vòng cổ chân, làm mượt đổ 17% Thigh + 15% Foot vào
    # giữa cẳng -- gập gối là cẳng quần teo lại ngay dưới gối (da theo quần teo
    # theo); Pelvis cũng loang xuống giữa đùi như thế.
    co = [obj.matrix_world @ v.co for v in obj.data.vertices]
    lo, hi = _bbox(obj)
    reach = max(hi[2] - lo[2], 1e-6) * SMOOTH_REACH if height is None else height * SMOOTH_REACH
    near = [[(j, max(0.0, 1.0 - (co[i] - co[j]).length / reach)) for j in nb]
            for i, nb in enumerate(adj)]

    # Không bao giờ trộn trái sang phải: bậc Thigh.L | Thigh.R ở đáy quần là bậc
    # ĐÚNG, làm mượt qua đó là đùi trái kéo ống quần phải (short: 15 -> 52 cạnh
    # giãn). Bậc Neck | Bicep.L ở chân mũ hoodie thì xương giữa với một bên.
    def side(n):
        return 'L' if n.endswith('.L') or '.L.' in n else ('R' if n.endswith('.R') or '.R.' in n else None)

    def own_side(row):
        return side(max(row, key=row.get)) if row else None

    def diff(a, b):
        s = own_side(a)
        return sum(abs(a.get(n, 0.0) - b.get(n, 0.0)) for n in set(a) | set(b)
                   if s is None or side(n) in (None, s))

    # vùng làm mượt cố định từ trọng số GỐC, nới thêm một vòng vertex kề
    jump = {i for i, row in enumerate(rows)
            if any(diff(row, rows[j]) > SMOOTH_JUMP for j in adj[i])}
    jump |= {j for i in list(jump) for j in adj[i]}
    for _p in range(passes):
        new = []
        for i, row in enumerate(rows):
            nb = adj[i]
            if not nb or i not in jump:
                new.append(row)
                continue
            s = own_side(row)
            tot_k = sum(k for _j, k in near[i])
            if tot_k <= 1e-6:
                new.append(row)
                continue
            avg = {}
            for j, k in near[i]:
                for n, w in rows[j].items():
                    if s is not None and side(n) not in (None, s):
                        n = None    # phần bên kia: giữ nguyên trọng số của chính vertex
                    avg[n] = avg.get(n, 0.0) + w * k / tot_k
            lost = avg.pop(None, 0.0)
            if lost:
                for n, w in row.items():
                    avg[n] = avg.get(n, 0.0) + lost * w / max(sum(row.values()), 1e-9)
            keys = set(row) | set(avg)
            a_ = alpha * min(1.0, tot_k / len(nb))
            new.append({n: (1 - a_) * row.get(n, 0.0) + a_ * avg.get(n, 0.0) for n in keys})
        rows[:] = new
    return rows


# ============================================================ trọng số thiếu

def face_roots(rig):
    """{xương mặt: tổ tiên gần nhất KHÔNG phải xương mặt} -- Jaw, môi... -> Head."""
    from . import posekey
    head = posekey.head_bone(rig)
    return {c.name: head.name for c in head.children_recursive} if head else {}


def fill_weights(obj, rig, tol=0.995):
    """Lấp vertex có tổng trọng số deform < 1. Trả về (số vertex lấp, số vertex trống).

    Armature modifier không chuẩn hoá: vertex chỉ có Jaw 0.08 thì 92% còn lại
    đứng yên ở rest dù đầu có quay -- trên body của Kid có 25 vertex như vậy ở
    hàm/cằm, cạnh nối giãn 18 lần khi cúi đầu, thành mảnh nhọn thò sau tai.
    - Phần thiếu của vertex có xương mặt mạnh nhất -> tổ tiên không-mặt (Head):
      đúng nghĩa "Jaw w + Head (1 - w)" của trọng số hàm.
    - Còn lại thì chuẩn hoá theo tỉ lệ.
    - Vertex không có gì: lấy trung bình vertex kề đã có trọng số.
    """
    deform = {b.name for b in rig.data.bones if b.use_deform}
    up = face_roots(rig)
    idx = {g.index: g.name for g in obj.vertex_groups}
    rows = [{idx[g.group]: g.weight for g in v.groups
             if idx[g.group] in deform and g.weight > 0} for v in obj.data.vertices]
    fixed, empty = set(), [i for i, r in enumerate(rows) if not r]
    adj = neighbours(obj) if empty else None
    for _pass in range(20):
        if not empty:
            break
        left = []
        for i in empty:
            got = [rows[j] for j in adj[i] if rows[j] and j not in left]
            if not got:
                left.append(i)
                continue
            acc = {}
            for r in got:
                for n, w in r.items():
                    acc[n] = acc.get(n, 0.0) + w / len(got)
            rows[i] = acc
            fixed.add(i)
        empty = left
    for i, r in enumerate(rows):
        tot = sum(r.values())
        if not r or tot >= tol:
            continue
        top = max(r, key=r.get)
        if top in up:
            r[up[top]] = r.get(up[top], 0.0) + (1.0 - tot)
        else:
            for n in r:
                r[n] /= tot
        fixed.add(i)
    for i in fixed:
        for n, w in rows[i].items():
            g = obj.vertex_groups.get(n) or obj.vertex_groups.new(name=n)
            g.add([i], min(1.0, w), 'REPLACE')
    return len(fixed), len(empty)


class SRP_OT_fill_weights(bpy.types.Operator):
    """Lấp vertex có tổng trọng số < 1 trên mọi mesh skin vào rig (vertex bị bỏ lại khi pose)"""
    bl_idname = "srp.fill_weights"
    bl_label = "Lấp trọng số thiếu"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return rigdef.active_rig(context) is not None

    def execute(self, context):
        rig = rigdef.active_rig(context)
        out = []
        for o in context.scene.objects:
            if o.type == 'MESH' and deformed_by(o, rig):
                n, e = fill_weights(o, rig)
                if n or e:
                    out.append("%s %d vertex%s" % (o.name, n, ", %d không lấp được" % e if e else ""))
        self.report({'INFO'}, "Đã lấp: " + ", ".join(out) if out else "Mọi vertex đủ trọng số")
        return {'FINISHED'}


# ============================================================ weight hông

# Dải chuyển Thigh <-> hông quanh mỗi khớp đùi, theo phần chiều cao nhân vật:
# (tâm dải so với khớp, nửa bề rộng). Trước: hẹp, ngay nếp háng. Sau: rộng, lệch
# lên -- mông quay một phần theo đùi. Đo trên Adult (weight chép từ Kid): mông
# chỉ 20-45% Thigh, giơ chân 90° là mông gãy thành gờ có góc nhọn, háng trước
# gập thành khe; dải này cho háng trơn, mông tròn, ngồi xổm/bước đi không đổi.
# Mặt sau 1.19.5: (0.05, 0.07) -> (0.06, 0.09). Adult giơ chân 90°: nếp mông-đùi
# còn gãy thành gờ tối; rộng hơn thì mông tròn như Kid, bước lùi 35° không đổi.
HIP_FRONT = (0.005, 0.025)
HIP_BACK = (0.06, 0.09)
HIP_REACH = (0.16, 0.14)    # vùng sửa: cao / ngang quanh khớp, ngoài đó tắt dần


def pants_top(obj, rig, body_height):
    """Độ cao cạp (hệ rig) nếu `obj` là quần / quần short: có weight Thigh ở
    phần đáng kể vertex, cạp cao hơn khớp đùi không quá 25% chiều cao. Không
    phải quần thì None."""
    B = rig.data.bones
    legs = [l.deform[0] for l in rigdef.limbs_for(rig) if l.kind == 'LEG' and l.deform[0] in B]
    if not legs:
        return None
    gi = {g.index: g.name for g in obj.vertex_groups}
    n = sum(1 for v in obj.data.vertices
            if any(gi[g.group] in legs and g.weight > 0.5 for g in v.groups))
    if n < 0.05 * len(obj.data.vertices):
        return None
    to_rig = rig.matrix_world.inverted() @ obj.matrix_world
    top = max((to_rig @ v.co).z for v in obj.data.vertices)
    jz = max(B[l].head_local.z for l in legs)
    return top if 0.0 < top - jz < 0.25 * body_height else None


def hip_band(obj, rig, front=HIP_FRONT, back=HIP_BACK, reach=HIP_REACH, height=None,
             top=None):
    """Đặt lại weight Thigh <-> hông/thắt lưng quanh mỗi khớp đùi. Phần không
    thuộc Thigh chia lại cho Pelvis/Hips/Spine theo tỉ lệ cũ. Vertex mang weight
    của chi khác (chân bên kia, cẳng chân, tay) hay của đầu thì để nguyên.

    `top` (độ cao cạp, cho QUẦN): dải tính theo chính cái quần -- tâm 40%, nửa
    rộng 30% quãng khớp -> cạp, cả trước lẫn sau. Quần short Kid giơ chân 60-90°:
    mảng quần trước bụng (cao hơn khớp) đi theo Pelvis, mặt trên đùi quét lên
    đúng chỗ đó -> đùi xuyên ra trước quần; ngoài đời vải ở đó bị đùi kéo căng
    theo. Dải của da (hẹp ngay nếp háng) dùng cho quần thì không cứu được;
    dải cố định theo chiều cao thì với lên tới cạp (cạp quần Adult chỉ cao hơn
    khớp 10 cm) và hở da ở cạp.
    Trả về số vertex đã sửa."""
    from . import posekey
    import math
    B = rig.data.bones
    deform = {b.name for b in B if b.use_deform}
    legs = [l for l in rigdef.limbs_for(rig) if l.kind == 'LEG' and l.deform[0] in B]
    if not legs:
        return 0
    limb_bones = set()
    for l in rigdef.limbs_for(rig):
        for n in l.deform:
            if n in B:
                limb_bones |= {n} | {c.name for c in B[n].children_recursive}
    head = posekey.head_bone(rig)
    if head is not None:
        limb_bones |= {head.name} | {c.name for c in head.children_recursive}
    lo, hi = _bbox(obj)
    H = height or (hi[2] - lo[2])
    to_rig = rig.matrix_world.inverted() @ obj.matrix_world
    rows = skin_rows(obj, deform)
    gi = {g.index: g.name for g in obj.vertex_groups}

    def ss(e0, e1, x):
        t = min(1.0, max(0.0, (x - e0) / (e1 - e0)))
        return t * t * (3 - 2 * t)

    changed = []
    for v in obj.data.vertices:
        p = to_rig @ v.co
        leg = min(legs, key=lambda l: (p - B[l.deform[0]].head_local).length)
        thigh = leg.deform[0]
        d = p - B[thigh].head_local
        if abs(d.z) > reach[0] * H or abs(d.x) > reach[1] * H:
            continue
        row = rows[v.index]
        if not row or any(w > 0.05 and n in limb_bones and n != thigh for n, w in row.items()):
            continue
        if top is not None:
            gap = top - B[thigh].head_local.z
            c, hw = 0.4 * gap, 0.3 * gap
        else:
            # 0 = trước (-Y của rig), 1 = sau
            t = (math.sin(math.atan2(d.y, abs(d.x) + 1e-6)) + 1.0) * 0.5
            c = (front[0] + (back[0] - front[0]) * t) * H
            hw = (front[1] + (back[1] - front[1]) * t) * H
        wt = 1.0 - ss(c - hw, c + hw, d.z)
        if top is not None:
            # Quần chỉ được THÊM theo đùi, không bớt: phía sau quần đã chép
            # weight của da mông (theo đùi nhiều); bớt đi là mông Adult đâm qua
            # đáy quần, hở da dưới gấu áo.
            wt = max(wt, row.get(thigh, 0.0))
        r = max(abs(d.z) / (reach[0] * H), abs(d.x) / (reach[1] * H))
        f = 1.0 if r < 0.7 else (1.0 - r) / 0.3
        rest = {n: w for n, w in row.items() if n != thigh}
        tot = sum(rest.values())
        if tot < 1e-6:
            up = B[thigh].parent
            rest, tot = {(up.name if up is not None else thigh): 1.0}, 1.0
        new = {n: w / tot * (1.0 - wt) for n, w in rest.items()}
        new[thigh] = new.get(thigh, 0.0) + wt
        new = {n: (1 - f) * row.get(n, 0.0) + f * new.get(n, 0.0) for n in set(row) | set(new)}
        # quần áo giữ chuẩn MAX_INFLUENCE xương / vertex, thân giữ tới 8
        new = dict(sorted(new.items(), key=lambda kv: -kv[1])[:MAX_INFLUENCE if top is not None else 8])
        s = sum(new.values()) or 1.0
        for g in list(v.groups):
            if gi[g.group] in deform:
                obj.vertex_groups[g.group].remove([v.index])
        for n, w in new.items():
            if w / s > 1e-3:
                grp = obj.vertex_groups.get(n) or obj.vertex_groups.new(name=n)
                grp.add([v.index], w / s, 'REPLACE')
        changed.append(v.index)
    # weight da vừa đổi: bản lưu "da gốc" của bước da-theo-áo hết giá trị
    _forget_skin(obj, changed)
    return len(changed)


# Dải chuyển ở khớp giữa của chi (gối, khuỷu), theo phần chiều cao: nửa rộng ở
# mặt NGOÀI (bánh chè, khuỷu) và mặt TRONG (khoeo, lòng khuỷu tay).
# Đo trên Adult (gập gối 130°, ngồi xổm): weight gối chép từ Kid rộng tới mức
# cách gối 10 cm bắp chân còn 28% Thigh -- khoeo móp, bắp chân teo. Đã thử
# trong 0.6% / ngoài 3.5%: lưới quần thưa (vòng cách 2-4 cm) gập ngược thành lỗ
# ở nếp gối; trong 2% vẫn còn một ô gập nhỏ ở nếp -- đó là nếp vải ép vào nhau.
# 1.19.5: trong 2% / ngoài 3% / mượt 3% làm khoeo gập 90-130° thành khía chữ V
# sắc (Kid thì nếp tròn). Thử 3/4/4.5%, 4/4.5/5.5%, 5/5/6%: 5/5/6% khoeo cong
# mềm, gối tròn khi ngồi xổm, bắp chân không móp (móp cũ là do weight Kid trộn
# 50/50 cả vòng gối, không phải do dải rộng).
JOINT_OUT = 0.05
JOINT_IN = 0.05
JOINT_REACH = 0.09
# Làm mượt cục bộ mặt trong: số lượt, bán kính quanh khớp (phần chiều cao).
# Adult gập gối 130°: 3 lượt còn ô gập ở nếp, 6 lượt hết, bắp chân vẫn đầy.
JOINT_SMOOTH = 6
JOINT_SMOOTH_R = 0.06
# Khuỷu tay mềm hơn gối: tay áo len rộng, gập khuỷu 90° với dải trong 2% là
# lòng khuỷu thành một bậc gắt (Adult). 3.5% còn gợn, 5% thành đường cong trơn.
ARM_IN = 0.05
ARM_OUT = 0.04
ARM_SMOOTH_R = 0.06


def joint_band(obj, rig, height=None, out_w=JOINT_OUT, in_w=JOINT_IN, reach=JOINT_REACH,
               limit=MAX_INFLUENCE, kinds=None):
    """Đặt lại weight xương trên <-> xương dưới quanh gối và khuỷu.

    Mặt trong của khớp gập: chuyển GẮT ngay tại khớp; mặt ngoài: chuyển RỘNG.
    Weight trộn đều 50/50 quanh cả vòng khớp (vòng gối Adult: 0.55 Shin / 0.44
    Thigh) thì gập sâu là vertex khoeo rơi vào giữa dây cung -- khoeo móp hẳn
    vào, không giống chân người. Chuyển gắt ở khoeo thì bắp chân và mặt sau
    đùi ép vào nhau như thật; chuyển rộng ở bánh chè thì gối tròn, không nhọn.
    Mặt trong lấy NGƯỢC hướng pole (gối/khuỷu chĩa về pole) -- dùng chung cho
    chân và tay. Trả về số vertex đã sửa."""
    import math
    B = rig.data.bones
    deform = {b.name for b in B if b.use_deform}
    lo, hi = _bbox(obj)
    H = height or (hi[2] - lo[2])
    to_rig = rig.matrix_world.inverted() @ obj.matrix_world
    rows = skin_rows(obj, deform)
    gi = {g.index: g.name for g in obj.vertex_groups}
    joints = []
    for l in rigdef.limbs_for(rig):
        up, low = l.deform[0], l.deform[1]
        if up not in B or low not in B or (kinds is not None and l.kind not in kinds):
            continue
        J = B[low].head_local
        axis = (B[up].tail_local - B[up].head_local).normalized()
        pole = B.get(l.pole) if l.pole else None
        if pole is None:
            continue
        out = pole.head_local - J
        out -= axis * out.dot(axis)
        if out.length < 1e-6:
            continue
        joints.append((up, low, J, axis, out.normalized(), l.kind))
    if not joints:
        return 0

    def ss(e0, e1, x):
        t = min(1.0, max(0.0, (x - e0) / (e1 - e0)))
        return t * t * (3 - 2 * t)

    done = 0
    plan = {}
    for v in obj.data.vertices:
        row = rows[v.index]
        if not row:
            continue
        p = to_rig @ v.co
        best = min(joints, key=lambda j: (p - j[2]).length)
        up, low, J, axis, out, kind = best
        iw, ow = (ARM_IN, ARM_OUT) if kind == 'ARM' else (in_w, out_w)
        if up not in row and low not in row:
            continue
        d = p - J
        s = d.dot(axis)                              # + = về phía xương dưới
        radial = d - axis * s
        if abs(s) > reach * H or radial.length > reach * H:
            continue
        lim = row.get(up, 0.0) + row.get(low, 0.0)
        if lim < 0.5 * sum(row.values()):
            continue                                 # vùng của xương khác (bàn tay, hông...)
        # 1 = mặt ngoài (về phía pole), 0 = mặt trong
        c = radial.normalized().dot(out) if radial.length > 1e-6 else 0.0
        hw = (iw + (ow - iw) * (c + 1.0) * 0.5) * H
        wl = ss(-hw, hw, s)
        f = 1.0 if abs(s) < 0.7 * reach * H else (reach * H - abs(s)) / (0.3 * reach * H)
        plan[v.index] = [up, low, lim, wl, f, c, s, kind]

    # Làm mượt CỤC BỘ ở mặt trong (khoeo, lòng khuỷu): chỉ tỉ lệ xương dưới,
    # chỉ vertex trong JOINT_SMOOTH_R quanh khớp, chỉ qua cạnh ngắn. Dải gắt ở
    # mặt trong đúng là để khoeo không móp, nhưng trên lưới thưa nó đổi gần hết
    # 0 -> 1 qua một vòng vertex: nếp gối/khuỷu ra răng cưa, có ô gập ngược.
    # Không nới dải (nới là khoeo móp lại): trộn với hàng xóm vài lượt thôi.
    if JOINT_SMOOTH and plan:
        co = {i: obj.matrix_world @ obj.data.vertices[i].co for i in plan}
        def rad(i):
            return (ARM_SMOOTH_R if plan[i][7] == 'ARM' else JOINT_SMOOTH_R) * H
        rr = max(JOINT_SMOOTH_R, ARM_SMOOTH_R) * H
        zone = {i for i, r in plan.items() if r[5] < 0.3 and abs(r[6]) < rad(i)}
        adj = {i: [] for i in zone}
        for e in obj.data.edges:
            a, b = e.vertices
            if a in zone and b in plan and plan[a][0] == plan[b][0]:
                L = (co[a] - co[b]).length
                if L < 2 * rr:
                    adj[a].append((b, 1.0 - L / (2 * rr)))
            if b in zone and a in plan and plan[a][0] == plan[b][0]:
                L = (co[a] - co[b]).length
                if L < 2 * rr:
                    adj[b].append((a, 1.0 - L / (2 * rr)))
        for _p in range(JOINT_SMOOTH):
            new_wl = {}
            for i in zone:
                nb = adj[i]
                k = sum(w for _j, w in nb)
                if k <= 0:
                    continue
                avg = sum(plan[j][3] * w for j, w in nb) / k
                # mép vùng chỉ trộn một nửa để không thành bậc mới
                edge = abs(plan[i][6]) / rad(i)
                a_ = 0.5 * (1.0 - edge)
                new_wl[i] = plan[i][3] + (avg - plan[i][3]) * a_
            for i, w in new_wl.items():
                plan[i][3] = w

    for i, (up, low, lim, wl, f, _c, _s, _k) in plan.items():
        v = obj.data.vertices[i]
        row = rows[i]
        new = dict(row)
        new[up] = (1 - f) * row.get(up, 0.0) + f * lim * (1.0 - wl)
        new[low] = (1 - f) * row.get(low, 0.0) + f * lim * wl
        new = dict(sorted(((n, w) for n, w in new.items() if w > 1e-4), key=lambda kv: -kv[1])[:limit])
        tot = sum(new.values()) or 1.0
        for g in list(v.groups):
            if gi[g.group] in deform:
                obj.vertex_groups[g.group].remove([i])
        for n, w in new.items():
            grp = obj.vertex_groups.get(n) or obj.vertex_groups.new(name=n)
            grp.add([i], w / tot, 'REPLACE')
        done += 1
    _forget_skin(obj, plan)
    return done


def leg_bones(rig):
    B = rig.data.bones
    out = set()
    for l in rigdef.limbs_for(rig):
        if l.kind == 'LEG':
            for n in l.deform:
                if n in B:
                    out |= {n} | {c.name for c in B[n].children_recursive}
    return out


def _leg_sums(obj, bones):
    gi = {g.index: g.name for g in obj.vertex_groups}
    return [sum(g.weight for g in v.groups if gi[g.group] in bones) for v in obj.data.vertices]


def leg_share(obj, bones):
    """Phần vertex của `obj` chủ yếu theo xương chân (quần, giày ~1, áo ~0)."""
    s = _leg_sums(obj, bones)
    return sum(1 for w in s if w >= 0.5) / max(1, len(s))


def leg_zone(body, bones, tol=0.2):
    """Vertex thân có >= `tol` weight xương chân (cả mông, háng)."""
    return {i for i, w in enumerate(_leg_sums(body, bones)) if w >= tol}


class SRP_OT_hip_weights(bpy.types.Operator):
    """Đặt lại weight quanh hông, gối, khuỷu: háng không gập thành khe, mông
    không gãy thành gờ khi giơ chân, khoeo và lòng khuỷu không móp khi gập sâu.
    Rồi bind lại quần áo"""
    bl_idname = "srp.hip_weights"
    bl_label = "Sửa weight hông, gối, khuỷu"
    bl_options = {'REGISTER', 'UNDO'}

    rebind_cloth: bpy.props.BoolProperty(
        name="Bind lại quần áo", default=True,
        description="Quần áo 'chép từ thân' lấy lại weight hông mới; da dưới áo "
                    "đi theo áo được tính lại")
    part: bpy.props.EnumProperty(
        name="Vùng", default='ALL',
        items=(('ALL', "Hông, gối, khuỷu", "Đặt lại cả ba vùng, bind lại mọi quần áo"),
               ('LEGS', "Chỉ hông và gối",
                "Không đụng tay: giữ weight nách / khuỷu đã tự vẽ. Chỉ bind lại "
                "quần áo ở chân (quần, giày), da theo áo chỉ làm lại ở chân")))

    @classmethod
    def poll(cls, context):
        return rigdef.active_rig(context) is not None

    def execute(self, context):
        rig, body = _body_rig(context)
        if body is None or not deformed_by(body, rig):
            self.report({'ERROR'}, "Chưa có mesh thân skin vào rig")
            return {'CANCELLED'}
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        legs = self.part == 'LEGS'
        cloths = [e.mesh for e in context.scene.srp_generate.cloth_meshes]
        with keep_hand([body] + cloths) as kept:
            n = hip_band(body, rig)
            k = joint_band(body, rig, limit=8, kinds={'LEG'} if legs else None)
            if not n and not k:
                self.report({'WARNING'}, "Không tìm thấy vùng hông / gối / khuỷu (rig không có chi?)")
                return {'CANCELLED'}
            msg = "%s: sửa weight %d vertex quanh hông, %d quanh %s" % (
                body.name, n, k, "gối" if legs else "gối/khuỷu")
            if self.rebind_cloth and len(context.scene.srp_generate.cloth_meshes):
                if legs:
                    lb = leg_bones(rig)
                    only = {m for m in cloths if m is not None and m.type == 'MESH'
                            and leg_share(m, lb) > 0.3}
                    lines = bind_all(context, rig, body, only=only, zone=leg_zone(body, lb))
                else:
                    lines = bind_all(context, rig, body)
                msg += " | bind lại quần áo" + prefs.detail(": " + " | ".join(lines))
        if kept.count():
            msg += " | giữ nguyên %d vertex vẽ tay" % kept.count()
        self.report({'INFO'}, msg)
        return {'FINISHED'}


def count_low(obj, rig, tol=0.995):
    deform = {b.name for b in rig.data.bones if b.use_deform}
    idx = {g.index: g.name for g in obj.vertex_groups}
    return sum(1 for v in obj.data.vertices
               if sum(g.weight for g in v.groups if idx[g.group] in deform) < tol)


def rigid(obj, bone):
    return _write(obj, [{bone: 1.0} for _v in obj.data.vertices])


def automatic(context, obj, rig):
    """Automatic weights, giấu xương mặt như bind thân (áo không bám theo môi)."""
    from . import posekey
    head = posekey.head_bone(rig)
    skip = {c.name for c in head.children_recursive} if head else set()
    hidden = [b for b in rig.data.bones if b.name in skip and b.use_deform]
    for b in hidden:
        b.use_deform = False
    try:
        for o in list(context.selected_objects):
            o.select_set(False)
        obj.select_set(True)
        rig.select_set(True)
        context.view_layer.objects.active = rig
        # parent_set tự thêm modifier + parent; gỡ cái _attach vừa thêm để
        # khỏi hai modifier chồng nhau
        for m in [m for m in obj.modifiers if m.type == 'ARMATURE']:
            obj.modifiers.remove(m)
        bpy.ops.object.parent_set(type='ARMATURE_AUTO')
    finally:
        for b in hidden:
            b.use_deform = True
    return len([g for g in obj.vertex_groups if g.name in rig.data.bones])


def bind_one(context, entry, rig, body):
    """Bind một dòng. Trả về câu báo cáo."""
    obj = entry.mesh
    rest = rig.data.pose_position
    rig.data.pose_position = 'REST'
    context.view_layer.update()
    try:
        _clean(obj, rig)
        if entry.mode == 'RIGID':
            bone = entry.bone if entry.bone in rig.data.bones else None
            if bone is None:
                return "%s: rig không có xương %r" % (obj.name, entry.bone)
            rigid(obj, bone)
            _attach(obj, rig)
            return "%s gắn cứng vào %s" % (obj.name, bone)
        if entry.mode == 'TRANSFER':
            if body is None or not deformed_by(body, rig):
                return "%s: mesh thân chưa bind, chưa chép được trọng số" % obj.name
            n, far = transfer(obj, body, rig)
            _attach(obj, rig)
            note = " (điểm xa thân nhất %.0f cm -- đồ rộng thì thử Automatic)" % (far * 100) \
                if far > 0.08 else ""
            passes, scores = transfer.last
            sm = ", làm mượt %d lượt (cạnh giãn %s)" % (passes, " / ".join(
                "%d:%d" % kv for kv in sorted(scores.items())))
            return "%s chép trọng số từ %s: %d xương%s%s" % (obj.name, body.name, n,
                                                           prefs.detail(sm), note)
        n = automatic(context, obj, rig)
        return "%s automatic weights: %d xương" % (obj.name, n)
    finally:
        rig.data.pose_position = rest
        context.view_layer.update()


def bind_all(context, rig, body, only=None, zone=None):
    """Bind lại quần áo. `only`: chỉ những mesh này; `zone`: da theo áo chỉ
    làm lại trong tập vertex thân này (xem skin_follow)."""
    lines = []
    done = []
    for entry in context.scene.srp_generate.cloth_meshes:
        if entry.mesh is None or entry.mesh.type != 'MESH':
            continue
        if only is not None and entry.mesh not in only:
            continue
        try:
            lines.append(bind_one(context, entry, rig, body))
            if entry.mode != 'RIGID' and deformed_by(entry.mesh, rig):
                done.append(entry.mesh)
        except RuntimeError as e:
            lines.append("%s: bind thất bại (%s)" % (entry.mesh.name, e))
    # Quần / quần short chép từ thân: dải Thigh <-> hông theo chính cái quần
    # (xem hip_band) -- TRƯỚC da-theo-áo, để da dưới quần lấy weight mới.
    if body is not None:
        lo, hi = _bbox(body)
        hb = hi[2] - lo[2]
        for entry in context.scene.srp_generate.cloth_meshes:
            o = entry.mesh
            if o is None or entry.mode != 'TRANSFER' or not deformed_by(o, rig) \
                    or (only is not None and o not in only):
                continue
            top = pants_top(o, rig, hb)
            if top is not None:
                n = hip_band(o, rig, height=hb, top=top)
                if n:
                    lines.append("%s: weight hông theo quần (%d vertex)" % (o.name, n))
            n = joint_band(o, rig, height=hb)
            if n:
                lines.append("%s: weight gối/khuỷu (%d vertex)" % (o.name, n))
    settings = context.scene.srp_generate
    if done and body is not None and getattr(settings, "skin_follow", True) and deformed_by(body, rig):
        n = skin_follow(rig, body, done, zone=zone)
        if n:
            lines.append("%d vertex da dưới áo đi theo áo" % n)
    context.view_layer.objects.active = rig
    return lines


# ============================================================ da dưới áo

# Trọng số GỐC của da đã bị `skin_follow` đổi, lưu trên object thân:
# {"chỉ số vertex": {xương: trọng số}}. Không có nó thì bind áo lần hai
# chép lại chính trọng số áo đã đè lên da (rồi làm mượt thêm lượt nữa) -- bind
# càng nhiều lần trọng số càng trôi (đo trên Kid: hoodie 17 -> 15 nhóm).
# `srp.bind` xoá nó khi bind lại thân.
SKIN_KEY = "srp_skin_orig"


def skin_rows(body, deform):
    """Trọng số deform của da, vertex đã bị đổi thì lấy bản gốc."""
    gname = {g.index: g.name for g in body.vertex_groups}
    rows = [{gname[g.group]: g.weight for g in v.groups
             if g.weight > 0 and gname[g.group] in deform} for v in body.data.vertices]
    for k, row in (body.get(SKIN_KEY) or {}).items():
        i = int(k)
        if i < len(rows):
            rows[i] = {n: w for n, w in row.items() if n in deform}
    return rows


# ============================================================ weight vẽ tay

# Vertex người dùng tự vẽ weight (Weight Paint / sửa trong Edit Mode), lưu trên
# object: danh sách chỉ số. Các nút sửa weight và bind quần áo GIỮ NGUYÊN weight
# của chúng. Adult: người dùng vẽ lại nách + khuỷu (464 vertex), rồi bấm "Sửa
# weight hông, gối, khuỷu" là dải khuỷu và da-theo-áo đè mất sạch.
HAND_KEY = "srp_handpaint"
# Mỗi phiên vẽ có đổi weight tăng STAMP_KEY; "Cập nhật weight từ thân" ghi lại
# số đó vào SYNC_KEY của thân. Khác nhau = thân đã vẽ lại, đồ chưa cập nhật.
STAMP_KEY = "srp_wstamp"
SYNC_KEY = "srp_synced"
_watch = {"cur": None}


def _deform_names(obj):
    names = set()
    for m in obj.modifiers:
        if m.type == 'ARMATURE' and m.object is not None and m.object.type == 'ARMATURE':
            names |= {b.name for b in m.object.data.bones if b.use_deform}
    return names


def _rows_of(obj, names=None, exact=False):
    """Weight từng vertex. Mặc định làm tròn (so sánh trước/sau khi vẽ);
    `exact` lấy nguyên giá trị (để ghi lại y hệt)."""
    gi = {g.index: g.name for g in obj.vertex_groups}
    if exact:
        return [{gi[g.group]: g.weight for g in v.groups} for v in obj.data.vertices]
    return [{gi[g.group]: round(g.weight, 4) for g in v.groups
             if g.weight > 1e-4 and (names is None or gi[g.group] in names)}
            for v in obj.data.vertices]


def hand_painted(obj):
    marks = obj.get(HAND_KEY)
    return set(marks) if marks else set()


def forget_hand(obj, idx=None):
    """Bỏ đánh dấu vẽ tay (`idx` None: bỏ hết)."""
    if HAND_KEY not in obj.keys():
        return
    if idx is None:
        del obj[HAND_KEY]
        return
    left = sorted(hand_painted(obj) - set(idx))
    if left:
        obj[HAND_KEY] = left
    else:
        del obj[HAND_KEY]


def _commit_watch(state):
    name, n, rows = state
    obj = bpy.data.objects.get(name)
    if obj is None or obj.type != 'MESH':
        return
    if len(obj.data.vertices) != n:
        forget_hand(obj)          # đổi topology: chỉ số cũ vô nghĩa
        return
    names = _deform_names(obj)
    now = _rows_of(obj, names or None)
    changed = {i for i, (a, b) in enumerate(zip(rows, now)) if a != b}
    if changed:
        obj[HAND_KEY] = sorted(hand_painted(obj) | changed)
        obj[STAMP_KEY] = obj.get(STAMP_KEY, 0) + 1
        _forget_skin(obj, changed)


@bpy.app.handlers.persistent
def _reset_watch(*_args):
    _watch["cur"] = None


@bpy.app.handlers.persistent
def _watch_modes(scene, depsgraph=None):
    """Vào Weight Paint / Edit Mode của mesh: chụp weight; ra: vertex nào đổi
    là vẽ tay."""
    ctx = bpy.context
    obj = getattr(ctx, "active_object", None)
    mode = getattr(ctx, "mode", None)
    cur = _watch["cur"]
    if mode in ('PAINT_WEIGHT', 'EDIT_MESH') and obj is not None and obj.type == 'MESH':
        if cur is not None and cur[0] == obj.name:
            return
        if cur is not None:
            _commit_watch(cur)
        names = _deform_names(obj)
        if not names:
            _watch["cur"] = None
            return
        _watch["cur"] = (obj.name, len(obj.data.vertices), _rows_of(obj, names))
    elif cur is not None:
        _watch["cur"] = None
        _commit_watch(cur)


class keep_hand:
    """`with keep_hand(objs):` -- vertex vẽ tay của các object giữ nguyên weight
    qua mọi bước bên trong (dải hông/gối/khuỷu, bind quần áo, da theo áo)."""

    def __init__(self, objs):
        self.saved = []
        for o in objs:
            if o is None or o.type != 'MESH':
                continue
            marks = hand_painted(o)
            if not marks or max(marks) >= len(o.data.vertices):
                continue
            rows = _rows_of(o, exact=True)
            self.saved.append((o.name, {i: rows[i] for i in marks}))

    def __enter__(self):
        return self

    def count(self):
        return sum(len(r) for _n, r in self.saved)

    def __exit__(self, *exc):
        for name, rows in self.saved:
            o = bpy.data.objects.get(name)
            if o is None:
                continue
            for i, row in rows.items():
                v = o.data.vertices[i]
                for g in list(v.groups):
                    o.vertex_groups[g.group].remove([i])
                for n, w in row.items():
                    grp = o.vertex_groups.get(n) or o.vertex_groups.new(name=n)
                    grp.add([i], w, 'REPLACE')
            _forget_skin(o, rows)
        return False


def register_extra():
    for lst, fn in ((bpy.app.handlers.depsgraph_update_post, _watch_modes),
                    (bpy.app.handlers.load_pre, _reset_watch)):
        for h in [h for h in lst if getattr(h, "__name__", "") == fn.__name__]:
            lst.remove(h)          # bản cũ còn sót sau khi nạp lại addon
        lst.append(fn)


def unregister_extra():
    for lst, fn in ((bpy.app.handlers.depsgraph_update_post, _watch_modes),
                    (bpy.app.handlers.load_pre, _reset_watch)):
        for h in [h for h in lst if getattr(h, "__name__", "") == fn.__name__]:
            lst.remove(h)
    _watch["cur"] = None


def _forget_skin(obj, idx):
    """Bỏ bản "da gốc" của các vertex `idx` (weight của chúng vừa đặt lại, giờ
    chính nó là gốc). Chỉ bỏ những vertex đó: xoá cả bản lưu là lần bind sau
    coi da-đã-theo-áo ở chỗ khác là gốc, còn xoá rồi khôi phục cả bản thì đè
    mất weight người dùng tự vẽ ở nách / khuỷu."""
    saved = obj.get(SKIN_KEY)
    if not saved:
        return
    idx = {str(i) for i in idx}
    keep = {k: dict(row.items()) for k, row in saved.items() if k not in idx}
    if keep:
        obj[SKIN_KEY] = keep
    else:
        del obj[SKIN_KEY]


def _restore_skin(body, deform, zone=None):
    saved = body.get(SKIN_KEY)
    if not saved:
        return {}
    orig = {}
    for k, row in saved.items():
        i = int(k)
        if i >= len(body.data.vertices) or (zone is not None and i not in zone):
            continue
        row = dict(row.items())
        for g in list(body.data.vertices[i].groups):
            name = body.vertex_groups[g.group].name
            if name in deform:
                body.vertex_groups[g.group].remove([i])
        for n, w in row.items():
            grp = body.vertex_groups.get(n) or body.vertex_groups.new(name=n)
            grp.add([i], w, 'REPLACE')
        orig[i] = row
    return orig

# Áo phải nằm trong khoảng này theo pháp tuyến da mới tính là che, tính theo
# chiều cao nhân vật (Kid 1.37 m -> 6 cm). 3.5 cm còn sót da sâu trong nếp nách.
COVER_RATIO = 0.045


def skin_follow(rig, body, cloths, dist=None, zone=None):
    """Da bị quần áo che lấy trọng số của chính điểm áo ngay phía trên nó.

    Da và áo cùng trọng số thì biến dạng như nhau, khoảng cách giữ nguyên --
    không thể đâm xuyên. Đo trên Kid: buông tay xuôi là da nếp nách sau đâm qua
    lưng hoodie (ẩn body đi thì mảnh đó biến mất), dù trọng số áo đã chép từ
    chính da đó: hai điểm gần nhau trên áo lấy trọng số từ hai vùng da khác nhau
    (cánh tay / lưng), còn da trong nếp gập thì không.

    Không đụng: vertex có xương mạnh nhất thuộc Head hoặc dưới Head (gáy dưới mũ
    áo vẫn phải theo đầu), bàn tay và ngón. Vertex ở mép vùng che chỉ trộn một
    nửa để không thành bậc ở cổ tay áo / cổ áo / gấu áo.
    `zone` (tập chỉ số vertex): chỉ làm lại da trong vùng đó, ngoài vùng giữ
    nguyên cả weight lẫn bản lưu da gốc.
    Trả về số vertex da đã đổi.
    """
    from . import posekey
    B = rig.data.bones
    keep = set()
    head = posekey.head_bone(rig)
    if head is not None:
        keep |= {head.name} | {c.name for c in head.children_recursive}
    for l in rigdef.limbs_for(rig):
        if l.kind == 'ARM' and l.deform[-1] in B:
            hb = B[l.deform[-1]]
            keep |= {hb.name} | {c.name for c in hb.children_recursive}
    deform = {b.name for b in B if b.use_deform}
    # chạy lại thì bắt đầu từ da GỐC, không từ da đã theo áo lần trước
    outside = {k: dict(r.items()) for k, r in (body.get(SKIN_KEY) or {}).items()
               if zone is not None and int(k) not in zone}
    orig = _restore_skin(body, deform, zone)

    # áo ở rest, cùng không gian world với da
    trees = []
    for c in cloths:
        mw = c.matrix_world
        vs = [mw @ v.co for v in c.data.vertices]
        c.data.calc_loop_triangles()
        tris = [tuple(t.vertices) for t in c.data.loop_triangles]
        gi = {g.index: g.name for g in c.vertex_groups}
        W = [{gi[g.group]: g.weight for g in v.groups if gi[g.group] in deform and g.weight > 0}
             for v in c.data.vertices]
        trees.append((BVHTree.FromPolygons(vs, tris), vs, tris, W))

    bmw = body.matrix_world
    if dist is None:
        lo, hi = _bbox(body)
        dist = (hi[2] - lo[2]) * COVER_RATIO
    n3 = bmw.inverted().transposed().to_3x3()
    bi = {g.index: g.name for g in body.vertex_groups}
    hit = {}
    for v in body.data.vertices:
        row = {bi[g.group]: g.weight for g in v.groups if bi[g.group] in deform and g.weight > 0}
        if not row or max(row, key=row.get) in keep or (zone is not None and v.index not in zone):
            continue
        p = bmw @ v.co
        nrm = (n3 @ v.normal).normalized()
        best = None
        for tree, vs, tris, W in trees:
            loc, _n, ti, d = tree.ray_cast(p, nrm, dist)
            if loc is not None and (best is None or d < best[0]):
                tri = tris[ti]
                acc = {}
                for k, f in zip(tri, poly_3d_calc([vs[k] for k in tri], loc)):
                    for name, w in W[k].items():
                        acc[name] = acc.get(name, 0.0) + w * f
                best = (d, acc)
        if best is not None and best[1]:
            hit[v.index] = best[1]
    if not hit:
        body[SKIN_KEY] = dict(outside, **{str(i): p for i, p in orig.items()})
        return 0
    for i in hit:
        if i not in orig:
            orig[i] = {bi[g.group]: g.weight for g in body.data.vertices[i].groups
                       if bi[g.group] in deform and g.weight > 0}
    body[SKIN_KEY] = dict(outside, **{str(i): p for i, p in orig.items()})
    adj = neighbours(body)
    edge = {i for i in hit if any(j not in hit and (zone is None or j in zone) for j in adj[i])}
    for i, acc in hit.items():
        tot = sum(acc.values()) or 1.0
        acc = {n: w / tot for n, w in acc.items()}
        if i in edge:
            old = {bi[g.group]: g.weight for g in body.data.vertices[i].groups
                   if bi[g.group] in deform}
            acc = {n: 0.5 * acc.get(n, 0.0) + 0.5 * old.get(n, 0.0) for n in set(acc) | set(old)}
        for g in list(body.data.vertices[i].groups):
            name = bi[g.group]
            if name in deform and name not in acc:
                body.vertex_groups[name].remove([i])
        top = sorted(acc.items(), key=lambda kv: -kv[1])[:MAX_INFLUENCE]
        tot = sum(w for _n, w in top) or 1.0
        for n in set(acc) - {n for n, _w in top}:
            g = body.vertex_groups.get(n)
            if g is not None:
                g.remove([i])
        for n, w in top:
            grp = body.vertex_groups.get(n) or body.vertex_groups.new(name=n)
            grp.add([i], w / tot, 'REPLACE')
    return len(hit)


# ============================================================ operator

def _body_rig(context):
    from . import generate
    settings = context.scene.srp_generate
    rig = rigdef.active_rig(context)
    body = settings.target_mesh or (generate.bound_mesh(context, rig) if rig else None)
    return rig, body


class SRP_OT_cloth_find(bpy.types.Operator):
    """Thêm vào danh sách mọi mesh quanh nhân vật mà chưa bind vào rig nào"""
    bl_idname = "srp.cloth_find"
    bl_label = "Tìm quần áo chưa bind"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        rig, body = _body_rig(context)
        if body is None:
            self.report({'ERROR'}, "Chọn mesh nhân vật ở bước 1 trước")
            return {'CANCELLED'}
        found = candidates(context, rig, body)
        for o in found:
            e = context.scene.srp_generate.cloth_meshes.add()
            e.mesh, e.mode = o, guess_mode(o)
        self.report({'INFO'}, "Thêm %d mesh: %s" % (len(found), ", ".join(o.name for o in found))
                    if found else "Không còn mesh nào quanh nhân vật chưa bind")
        return {'FINISHED'}


class SRP_OT_cloth_add(bpy.types.Operator):
    """Thêm các mesh đang chọn vào danh sách quần áo / phụ kiện"""
    bl_idname = "srp.cloth_add"
    bl_label = "Thêm mesh đang chọn"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        settings = context.scene.srp_generate
        have = {e.mesh for e in settings.cloth_meshes}
        new = [o for o in context.selected_objects
               if o.type == 'MESH' and o not in have and o is not settings.target_mesh]
        for o in new:
            e = settings.cloth_meshes.add()
            e.mesh, e.mode = o, guess_mode(o)
        if not new:
            settings.cloth_meshes.add()
        return {'FINISHED'}


class SRP_OT_cloth_remove(bpy.types.Operator):
    """Bỏ một mesh khỏi danh sách (không gỡ bind đã làm)"""
    bl_idname = "srp.cloth_remove"
    bl_label = "Bỏ khỏi danh sách"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(default=-1)

    def execute(self, context):
        items = context.scene.srp_generate.cloth_meshes
        i = self.index if self.index >= 0 else len(items) - 1
        if 0 <= i < len(items):
            items.remove(i)
        return {'FINISHED'}


# ============================================================ cập nhật từ thân

def _clear_bone_groups(obj, rig):
    names = {b.name for b in rig.data.bones}
    for g in [g for g in obj.vertex_groups if g.name in names]:
        obj.vertex_groups.remove(g)


def _used_bones(obj, rig):
    names = {b.name for b in rig.data.bones}
    gi = {g.index: g.name for g in obj.vertex_groups}
    return {gi[g.group] for v in obj.data.vertices for g in v.groups
            if g.weight > 1e-3 and gi[g.group] in names}


def skin_parts(context, rig, body):
    """[(object, xương được phép)] -- mesh dán sát da theo xương mặt: lông mày
    (vai trò BROW ở bước 1) và mesh phụ khớp theo nhân vật mẫu (fitref)."""
    from . import generate
    out, seen = [], {body.name}
    for role, o in generate.face_part_meshes(context):
        if role == 'BROW' and o.name not in seen and deformed_by(o, rig):
            out.append((o, set(generate.face_role_bones(rig, role)) or None))
            seen.add(o.name)
    for name in (body.get("srp_fit") or {}).get("pairs", {}):
        o = bpy.data.objects.get(name)
        if o is not None and o.type == 'MESH' and o.name not in seen and deformed_by(o, rig):
            out.append((o, _used_bones(o, rig) or None))
            seen.add(o.name)
    return out


def sync_targets(context, rig, body, hair=False):
    """[(object, cách)] sẽ được cập nhật. cách: 'CLOTH' / 'SKIN' / 'HAIR'."""
    out = []
    for e in context.scene.srp_generate.cloth_meshes:
        o = e.mesh
        if o is None or o.type != 'MESH' or o is body or not deformed_by(o, rig):
            continue
        if e.mode == 'TRANSFER':
            out.append((o, 'CLOTH', None))
        elif e.mode == 'RIGID' and hair:
            out.append((o, 'HAIR', None))
    out += [(o, 'SKIN', allowed) for o, allowed in skin_parts(context, rig, body)]
    return out


def sync_from_body(context, rig, body, hair=False):
    """Chép weight của thân (đúng như đang có -- KHÔNG sửa thân) sang quần áo,
    giày, lông mày... Vertex vẽ tay trên chính các mesh đó giữ nguyên.
    Trả về (các dòng báo cáo, số vertex vẽ tay được giữ)."""
    from . import posekey
    targets = sync_targets(context, rig, body, hair)
    head = posekey.head_bone(rig)
    to_head = {}
    if head is not None:
        to_head = {c.name: head.name for c in head.children_recursive}
    lines = []
    rest = rig.data.pose_position
    rig.data.pose_position = 'REST'
    context.view_layer.update()
    try:
        with keep_hand([o for o, _k, _a in targets]) as kept:
            for o, kind, allowed in targets:
                _clear_bone_groups(o, rig)
                if kind == 'CLOTH':
                    n, far = transfer(o, body, rig, current=True)
                    note = " (điểm xa thân nhất %.0f cm -- nên kiểm tra tay)" % (far * 100) \
                        if far > 0.08 else ""
                elif kind == 'HAIR':
                    # tóc theo đầu: xương mặt dồn về Head, không làm mượt
                    n, far = transfer(o, body, rig, remap=to_head, current=True, smooth_ok=False)
                    note = ""
                else:
                    n, far = transfer(o, body, rig, remap={}, current=True, allowed=allowed,
                                      smooth_ok=False, limit=8)
                    note = ""
                filled, _e = fill_weights(o, rig)
                lines.append("%s: %d xương%s%s" % (o.name, n,
                             " (lấp %d vertex)" % filled if filled else "", note))
    finally:
        rig.data.pose_position = rest
        context.view_layer.update()
    # thân giờ là nguồn chuẩn: bản "da gốc" cũ hết nghĩa
    if SKIN_KEY in body.keys():
        del body[SKIN_KEY]
    body[SYNC_KEY] = body.get(STAMP_KEY, 0)
    return lines, kept.count()


def sync_stale(body):
    """Thân đã vẽ lại weight sau lần cập nhật cuối?"""
    return body is not None and body.get(STAMP_KEY, 0) != body.get(SYNC_KEY, 0)


class SRP_OT_sync_from_body(bpy.types.Operator):
    """Chép weight của mesh thân (y như đang có) sang quần áo, giày, lông mày...
    Thân KHÔNG bị sửa. Vertex vẽ tay trên quần áo được giữ"""
    bl_idname = "srp.sync_from_body"
    bl_label = "Cập nhật weight từ thân"
    bl_options = {'REGISTER', 'UNDO'}

    hair: bpy.props.BoolProperty(
        name="Cả tóc", default=False,
        description="Tóc đang gắn cứng vào Head cũng chép từ thân (tóc dài chạm "
                    "vai, gáy). Tắt: tóc giữ nguyên. Lưu ý 'Bind quần áo' sẽ lại "
                    "gắn cứng nó")

    @classmethod
    def poll(cls, context):
        return rigdef.active_rig(context) is not None

    def execute(self, context):
        rig, body = _body_rig(context)
        if body is None or not deformed_by(body, rig):
            self.report({'ERROR'}, "Chưa có mesh thân skin vào rig")
            return {'CANCELLED'}
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        lines, kept = sync_from_body(context, rig, body, self.hair)
        context.view_layer.objects.active = rig
        if not lines:
            self.report({'WARNING'}, "Không có mesh nào để cập nhật (danh sách quần áo trống?)")
            return {'CANCELLED'}
        msg = "Cập nhật từ %s: %s" % (body.name, " | ".join(lines))
        if kept:
            msg += " | giữ %d vertex vẽ tay" % kept
        self.report({'INFO'}, msg)
        return {'FINISHED'}


def hand_objects(context):
    """[(object, số vertex vẽ tay)] của thân + quần áo trong danh sách."""
    rig, body = _body_rig(context)
    objs = [body] + [e.mesh for e in context.scene.srp_generate.cloth_meshes]
    seen, out = set(), []
    for o in objs:
        if o is not None and o.name not in seen:
            seen.add(o.name)
            n = len(hand_painted(o))
            if n:
                out.append((o, n))
    return out


class SRP_OT_hand_forget(bpy.types.Operator):
    """Thôi giữ weight vẽ tay: các nút sửa weight / bind quần áo lại được
    phép ghi đè những vertex đó"""
    bl_idname = "srp.hand_forget"
    bl_label = "Thôi giữ weight vẽ tay"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        n = 0
        for o, k in hand_objects(context):
            forget_hand(o)
            n += k
        self.report({'INFO'}, "Bỏ giữ %d vertex vẽ tay" % n)
        return {'FINISHED'}


class SRP_OT_cloth_bind(bpy.types.Operator):
    """Bind mọi mesh trong danh sách quần áo / phụ kiện vào rig. Chạy lại được"""
    bl_idname = "srp.cloth_bind"
    bl_label = "Bind quần áo"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        settings = getattr(context.scene, "srp_generate", None)
        return (settings is not None and len(settings.cloth_meshes) > 0
                and rigdef.active_rig(context) is not None)

    def execute(self, context):
        rig, body = _body_rig(context)
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        with keep_hand([body] + [e.mesh for e in context.scene.srp_generate.cloth_meshes]) as kept:
            lines = bind_all(context, rig, body)
        if kept.count():
            lines.append("giữ nguyên %d vertex vẽ tay" % kept.count())
        bad = [ln for ln in lines if "chưa" in ln or "thất bại" in ln or "không có" in ln]
        self.report({'WARNING'} if bad else {'INFO'}, " | ".join(lines) or "Danh sách trống")
        return {'FINISHED'}


def unbound(context):
    """Số mesh quanh nhân vật chưa gắn vào rig nào (cho tiêu đề panel)."""
    rig, body = _body_rig(context)
    if rig is None or body is None:
        return 0
    return len(candidates(context, rig, body))


def draw_cloth(layout, context):
    settings = context.scene.srp_generate
    rig, body = _body_rig(context)
    box = layout
    if body is None:
        box.label(text="Chọn mesh nhân vật ở bước 1 trước", icon='INFO')
        return
    left = candidates(context, rig, body) if rig else []
    if left:
        row = box.row()
        row.alert = True
        row.label(text="Chưa bind: " + ", ".join(o.name for o in left), icon='ERROR')
    for i, e in enumerate(settings.cloth_meshes):
        row = box.row(align=True)
        row.prop(e, "mesh", text="")
        row.prop(e, "mode", text="")
        if e.mode == 'RIGID' and rig is not None:
            row.prop_search(e, "bone", rig.data, "bones", text="")
        if e.mesh is not None and rig is not None:
            row.label(text="", icon='CHECKMARK' if deformed_by(e.mesh, rig) else 'DOT')
        row.operator("srp.cloth_remove", text="", icon='X').index = i
    row = box.row(align=True)
    row.operator("srp.cloth_find", icon='VIEWZOOM')
    row.operator("srp.cloth_add", text="Thêm đang chọn", icon='ADD')
    if len(settings.cloth_meshes):
        draw_sync(box, context, body)


def draw_sync(layout, context, body):
    """Nút "Cập nhật quần áo" + cảnh báo khi thân đã vẽ lại / còn món chưa bind."""
    col = layout.column(align=True)
    if sync_stale(body):
        row = col.row()
        row.alert = True
        row.label(text="%s đã sửa weight, quần áo chưa cập nhật" % body.name, icon='ERROR')
    r = col.row()
    r.scale_y = 1.4
    r.operator("srp.cloth_update", icon='MOD_CLOTH')


CLASSES = (SRP_ClothMesh, SRP_OT_cloth_find, SRP_OT_cloth_add, SRP_OT_cloth_remove,
           SRP_OT_cloth_bind, SRP_OT_fill_weights, SRP_OT_hip_weights, SRP_OT_hand_forget,
           SRP_OT_sync_from_body)
