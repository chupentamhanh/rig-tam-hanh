"""Mesh phụ dán trên da (lông mày, râu, mi rời...) BÁM DA theo shape key của mặt.

"Thử biểu cảm" và mọi animation chỉ đặt slider trên mesh mặt; mesh phụ đi
theo bằng driver -- nhưng chỉ ở những key nó CÓ, và hình của key đó phải khớp
da. Đo trên Adult: lông mày chỉ có 8 key BRW_* (chép từ Kid) -- EYE_Blink kéo da
dưới lông mày xuống 16-22 mm, EYE_Squint 9.7 mm, EYE_Wide 4.8 mm mà lông mày
đứng yên, tách khỏi da; 8 key BRW_* cũng lệch da 3.9-8.7 mm.

Cách làm: mỗi vertex mesh phụ neo vào điểm da gần nhất trên mesh mặt (tam
giác + toạ độ trọng tâm) kèm khoảng hở tới da, tính trong khung tam giác đó.
Mỗi key của mặt: điểm neo dời bao nhiêu thì vertex dời bấy nhiêu, khoảng hở
xoay theo mặt da. Chỉ dùng dữ liệu shape key (Basis -> key), không pose rig.

Da giãn thì mesh phụ giãn theo: key nhắm mắt của Adult kéo mép dưới vùng mày
xuống nhiều hơn mép trên, lông mày dày ra x1.25 (nhướng mày x1.34). `smooth`
làm mượt độ dời trên chính lưới mesh phụ -- bớt giãn nhưng hở / lún khỏi da:
nhắm mắt 4 lượt x1.21 hở 2.0 mm, 25 lượt x1.10 hở 3.8 mm. Mặc định 0: bám da.
"""

import bpy
from bpy.types import Operator
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree
from mathutils.interpolate import poly_3d_calc

THRESH = 2e-4       # dưới ngần này (đơn vị mesh mặt) coi như mesh phụ không nhúc nhích


def _frame(a, b, c):
    e1 = b - a
    n = e1.cross(c - a)
    if e1.length < 1e-12 or n.length < 1e-12:
        return None
    e1.normalize()
    n.normalize()
    return Matrix((e1, n.cross(e1), n)).transposed()


def bind(face, follower):
    """Neo từng vertex của `follower` vào da (Basis) của `face`, hệ local của face."""
    base = [d.co.copy() for d in face.data.shape_keys.key_blocks[0].data]
    face.data.calc_loop_triangles()
    tris = [tuple(t.vertices) for t in face.data.loop_triangles]
    tree = BVHTree.FromPolygons(base, tris)
    to_face = face.matrix_world.inverted() @ follower.matrix_world
    fsrc = follower.data.shape_keys.key_blocks[0].data if follower.data.shape_keys else follower.data.vertices
    anchors = []
    for v in fsrc:
        p = to_face @ v.co
        loc, _n, ti, _d = tree.find_nearest(p)
        t = tris[ti]
        w = poly_3d_calc([base[i] for i in t], loc)
        F = _frame(*(base[i] for i in t))
        off = (F.inverted() @ (p - loc)) if F is not None else (p - loc)
        anchors.append((t, w, off, F is not None))
    return base, anchors, to_face


def follow_deltas(base, key_co, anchors, to_face):
    """Độ dời (hệ local của mesh phụ) cho một key của mặt."""
    back = to_face.inverted().to_3x3()
    out = []
    for t, w, off, framed in anchors:
        s0 = sum((base[i] * wi for i, wi in zip(t, w)), Vector())
        s1 = sum((key_co[i] * wi for i, wi in zip(t, w)), Vector())
        if framed:
            F0 = _frame(*(base[i] for i in t))
            F1 = _frame(*(key_co[i] for i in t)) or F0
            d = (s1 + F1 @ off) - (s0 + F0 @ off)
        else:
            d = s1 - s0
        out.append(back @ d)
    return out


def followers(context, face):
    """Mesh phụ cần bám da: mesh đang chọn (khác mặt), không thì lông mày /
    mesh phụ khớp theo mẫu của nhân vật."""
    sel = [o for o in context.selected_objects if o.type == 'MESH' and o is not face]
    if sel:
        return sel
    from . import cloth, posekey
    rig = None
    for m in face.modifiers:
        if m.type == 'ARMATURE' and m.object is not None:
            rig = m.object
    if rig is None:
        return []
    return [o for o, _a in cloth.skin_parts(context, rig, face)]


def _smooth(obj, deltas, passes):
    if passes <= 0:
        return deltas
    nb = [[] for _ in obj.data.vertices]
    for e in obj.data.edges:
        a, b = e.vertices
        nb[a].append(b)
        nb[b].append(a)
    d = [x.copy() for x in deltas]
    for _ in range(passes):
        d = [d[i] * 0.5 + sum((d[j] for j in nb[i]), Vector()) * (0.5 / len(nb[i])) if nb[i] else d[i]
             for i in range(len(d))]
    return d


def follow(face, follower, names=None, smooth=0):
    """Dựng / ghi đè shape key bám da cho `follower`. Trả về (tạo, ghi đè, bỏ qua)."""
    from . import face as F
    fkey = face.data.shape_keys
    if fkey is None or len(fkey.key_blocks) < 2:
        return [], [], []
    base, anchors, to_face = bind(face, follower)
    F.ensure_basis(follower)
    fk = follower.data.shape_keys
    basis = fk.key_blocks[0]
    made, redone, skipped = [], [], []
    scale = max(to_face.to_scale())
    for kb in list(fkey.key_blocks)[1:]:
        if names is not None and kb.name not in names:
            continue
        co = [d.co for d in kb.data]
        d = _smooth(follower, follow_deltas(base, co, anchors, to_face), smooth)
        moved = max((x.length for x in d), default=0.0) * scale >= THRESH
        have = fk.key_blocks.get(kb.name)
        if have is None and not moved:
            skipped.append(kb.name)
            continue
        if have is None:
            have = follower.shape_key_add(name=kb.name, from_mix=False)
            have.value = 0.0
            have.slider_min, have.slider_max = kb.slider_min, kb.slider_max
            made.append(kb.name)
        else:
            redone.append(kb.name)
        for i, x in enumerate(d):
            have.data[i].co = basis.data[i].co + x
        path = 'key_blocks["%s"].value' % kb.name
        drv = fk.animation_data.drivers.find(path) if fk.animation_data else None
        if drv is None:
            F.add_driver(have, fkey, kb.name)
    return made, redone, skipped


class FACESHAPES_OT_follow_skin(Operator):
    """Lông mày, râu, mi rời... bám da theo MỌI shape key của mặt: key thiếu
    thì tạo (kèm driver), key có sẵn thì ghi lại theo da. Mesh đang chọn, không
    chọn thì lấy lông mày của nhân vật"""
    bl_idname = "face_shapes.follow_skin"
    bl_label = "Mesh phụ bám da"
    bl_options = {'REGISTER', 'UNDO'}

    smooth: bpy.props.IntProperty(
        name="Làm mượt", default=0, min=0, max=50,
        description="0: dán sát da (da giãn thì mesh phụ giãn theo). Tăng lên: "
                    "mesh phụ đi theo da như một khối cứng hơn, bớt giãn nhưng có "
                    "thể hở / lún khỏi da vài mm")

    @classmethod
    def poll(cls, context):
        from . import face as F
        _arm, face = F.find_rig_and_mesh(context)
        return face is not None and face.data.shape_keys is not None

    def execute(self, context):
        from . import face as F
        _arm, face = F.find_rig_and_mesh(context)
        objs = followers(context, face)
        if not objs:
            self.report({'ERROR'}, "Không có mesh phụ: chọn lông mày / râu rời rồi bấm lại")
            return {'CANCELLED'}
        lines = []
        for o in objs:
            made, redone, _skip = follow(face, o, smooth=self.smooth)
            lines.append("%s: tạo %d, ghi lại %d key" % (o.name, len(made), len(redone)))
        self.report({'INFO'}, "Bám da theo %s | %s" % (face.name, " | ".join(lines)))
        return {'FINISHED'}


CLASSES = (FACESHAPES_OT_follow_skin,)
