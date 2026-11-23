"""Dat marker theo tung khop, kieu Mixamo nhung chi tiet toi tung dot xuong.

Marker KHONG thay bo ref: no la lop dat khop nam TREN bo ref. Moi marker la mot
khop = mot nhom dau/duoi xuong ref trung nhau. "Ap dung" ghi vi tri + roll
nguoc lai vao bo ref, con dung rig, IK/FK, xuat Unity van di duong cu.

Roll (ly do truoc day bo marker) gio duoc TINH tu vi tri khop theo mot quy uoc
co dinh, ve truc len viewport, va chinh duoc rieng tung xuong bang `srp_roll`
(do) ghi tren chinh xuong ref.

Quy uoc: Y doc xuong, X la truc gap. Than: Z ra sau. Chan: Z ra truoc. Canh tay:
Z ra sau. Ban tay + ngon: khung ban tay that. Tai, toc, quan ao: giu huong mau,
xoay theo huong xuong. Ben R luon la anh guong cua ben L.
"""

import json
import math

import blf
import bpy
import gpu
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, FloatProperty, IntProperty, StringProperty
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

from . import refrig

TAG_MARKER = "srp_marker"       # ten bo ref ma marker thuoc ve
TAG_ENDS = "srp_mk_ends"        # JSON ["Bicep.L:H", "Shoulder.L:T"]
TAG_PARENT = "srp_mk_parent"    # ten marker cha
TAG_TWIN = "srp_mk_twin"        # ten marker doi xung
TAG_PLACED = "srp_mk_placed"    # nguoi dung da dat tay
TAG_CX = "srp_mk_cx"            # mat phang doi xung (X the gioi), ghi tren ref
TAG_ROLL = "srp_roll"           # do lech roll tay, ghi tren xuong ref
TAG_H0, TAG_T0, TAG_Z0 = "srp_mk_h0", "srp_mk_t0", "srp_mk_z0"

EPS = 1e-5
AXIS_RATIO = 0.035              # do dai truc ve tren viewport, theo chieu cao


# ------------------------------------------------------------ tim marker

def markers_of(ref):
    if ref is None:
        return []
    return [o for o in bpy.data.objects
            if o.type == 'EMPTY' and o.get(TAG_MARKER) == ref.name]


def collection_name(ref):
    return ref.name + "_Markers"


def ends_of(marker):
    return [e.rsplit(":", 1) for e in json.loads(marker.get(TAG_ENDS, "[]"))]


def bones_at(marker):
    """Xuong chinh roll tai khop nay: xuong bat dau o day, khop cuoi thi xuong ket thuc."""
    ends = ends_of(marker)
    return [n for n, e in ends if e == 'H'] or [n for n, _e in ends]


def _pair_side(name):
    for here, there in (('L', 'R'), ('R', 'L')):
        twin = refrig.flip_side(name, here, there)
        if twin is not None:
            return here, twin
    return None, None


# ---------------------------------------------------- gom dau/duoi thanh khop

def joint_groups(ref):
    """[[(ten xuong, 'H'/'T'), ...]] — moi nhom la MOT khop.

    Chi gop theo quan he cha/con/anh em. Gop theo vi tri tran thi hai xuong
    khong lien quan tinh co trung nhau se bi dinh chat vao nhau.
    """
    root = {}

    def find(x):
        root.setdefault(x, x)
        while root[x] != x:
            root[x] = root[root[x]]
            x = root[x]
        return x

    def join(a, b):
        root[find(a)] = find(b)

    bones = list(ref.data.bones)
    for bone in bones:
        find((bone.name, 'H'))
        find((bone.name, 'T'))
        up = bone.parent
        if up is None:
            continue
        # Goc chuoi toc/tai moc o dinh dau nhung KHONG noi lien: phai la marker
        # rieng, gop vao thi keo goc toc la keo luon dinh dau.
        if bone.use_connect:
            join((bone.name, 'H'), (up.name, 'T'))
        elif (bone.head_local - up.head_local).length < EPS:
            join((bone.name, 'H'), (up.name, 'H'))
    groups = {}
    for bone in bones:
        for end in 'HT':
            groups.setdefault(find((bone.name, end)), []).append((bone.name, end))
    return list(groups.values())


def _key(group):
    heads = [n for n, e in group if e == 'H']
    return heads[0] if heads else group[0][0] + "_End"


def _world(ref, name, end):
    bone = ref.data.bones[name]
    return ref.matrix_world @ (bone.head_local if end == 'H' else bone.tail_local)


def sync_markers(context, ref, mesh=None):
    """Tao / cap nhat marker theo bo ref. Marker da co giu nguyen vi tri."""
    old = {}
    for marker in markers_of(ref):
        for name, end in ends_of(marker):
            old[(name, end)] = marker
    coll = bpy.data.collections.get(collection_name(ref))
    if coll is None:
        coll = bpy.data.collections.new(collection_name(ref))
        context.scene.collection.children.link(coll)

    height = refrig.mesh_fit(mesh)[0] if mesh is not None else 1.7
    if TAG_CX not in ref.keys():
        ref[TAG_CX] = float(refrig.mesh_fit(mesh)[1].x) if mesh is not None else 0.0
    size = height * 0.012

    groups = joint_groups(ref)
    used, by_end = set(), {}
    for group in groups:
        marker = next((old[e] for e in group if e in old), None)
        if marker is None:
            marker = bpy.data.objects.new("MK_" + _key(group), None)
            coll.objects.link(marker)
            marker.empty_display_type = 'SPHERE'
            marker.empty_display_size = size
            marker.show_in_front = True
            marker.hide_render = True
            marker.location = _world(ref, *group[0])
            marker[TAG_MARKER] = ref.name
            marker[TAG_PLACED] = False
        marker[TAG_ENDS] = json.dumps(["%s:%s" % e for e in group])
        used.add(marker.name)
        for e in group:
            by_end[e] = marker
    for marker in markers_of(ref):       # bo phan da xoa khoi bo ref
        if marker.name not in used:
            bpy.data.objects.remove(marker)

    for bone in ref.data.bones:
        here, tip = by_end[(bone.name, 'H')], by_end[(bone.name, 'T')]
        tip[TAG_PARENT] = here.name
        # Spine va Hips chung mot khop: cha cua khop khong duoc la chinh no,
        # khong thi duyet cay khop quay vong mai mai.
        if TAG_PARENT not in here.keys() and bone.parent is not None:
            up = by_end[(bone.parent.name, 'H')]
            if up != here:
                here[TAG_PARENT] = up.name
        if TAG_ROLL not in bone.keys():
            bone[TAG_ROLL] = 0.0
            ui = bone.id_properties_ui(TAG_ROLL)
            ui.update(min=-180.0, max=180.0, soft_min=-180.0, soft_max=180.0,
                      step=100, precision=1, subtype='NONE',
                      description="Xoay thêm quanh trục xương (độ)")
        if TAG_Z0 not in bone.keys():
            W = ref.matrix_world
            z = (W.to_3x3() @ bone.matrix_local.to_3x3() @ Vector((0, 0, 1))).normalized()
            bone[TAG_H0], bone[TAG_T0] = list(W @ bone.head_local), list(W @ bone.tail_local)
            bone[TAG_Z0] = list(z)

    names = {}
    for marker in markers_of(ref):
        for name, end in ends_of(marker):
            names[(name, end)] = marker
    for marker in markers_of(ref):
        marker.pop(TAG_TWIN, None)
        for name, end in ends_of(marker):
            _side, other = _pair_side(name)
            twin = names.get((other, end)) if other else None
            if twin is not None and twin != marker:
                marker[TAG_TWIN] = twin.name
                break
    return markers_of(ref)


# -------------------------------------------------------------- doi xung

def mirror_point(ref, p):
    return Vector((2.0 * ref.get(TAG_CX, 0.0) - p.x, p.y, p.z))


def is_center(marker):
    return TAG_TWIN not in marker.keys()


def _center_side(marker):
    """Khop giua that (cot song) — khac voi khop co ben nhung chua co cap."""
    return all(_pair_side(n)[0] is None for n, _e in ends_of(marker))


def mirror_from(ref, marker):
    """Dua marker doi xung ve dung anh guong cua `marker`."""
    if is_center(marker):
        if _center_side(marker) and abs(marker.location.x - ref.get(TAG_CX, 0.0)) > 1e-6:
            marker.location.x = ref.get(TAG_CX, 0.0)
        return
    twin = bpy.data.objects.get(marker[TAG_TWIN])
    if twin is None:
        return
    want = mirror_point(ref, marker.location)
    if (twin.location - want).length > 1e-6:
        twin.location = want
    twin[TAG_PLACED] = bool(marker.get(TAG_PLACED))


def mirror_all(ref, side='L'):
    for marker in markers_of(ref):
        names = [n for n, _e in ends_of(marker)]
        if is_center(marker) or any(_pair_side(n)[0] == side for n in names):
            mirror_from(ref, marker)


# ------------------------------------------------------ dat + uoc luong

def _descendants(ref, root):
    kids = {}
    for marker in markers_of(ref):
        up = marker.get(TAG_PARENT)
        if up:
            kids.setdefault(up, []).append(marker)
    out, stack, seen = [], list(kids.get(root.name, ())), {root.name}
    while stack:
        marker = stack.pop()
        if marker.name in seen or marker.get(TAG_PLACED):   # khop dat tay la moc
            continue
        seen.add(marker.name)
        out.append(marker)
        stack.extend(kids.get(marker.name, ()))
    return out


def _placed_ancestor(marker):
    seen = set()
    up = bpy.data.objects.get(marker.get(TAG_PARENT, ""))
    while up is not None and up.name not in seen:
        if up.get(TAG_PLACED):
            return up
        seen.add(up.name)
        up = bpy.data.objects.get(up.get(TAG_PARENT, ""))
    return None


def place(ref, marker, point, mirror=True):
    """Dat mot khop, keo theo cac khop con CHUA dat de chung nam gan dung cho.

    Co khop cha da dat thi dung phep dong dang (xoay + co gian quanh khop cha):
    dat co tay xong, ca ban tay xoay va co theo canh tay that.
    """
    old = marker.location.copy()
    new = Vector(point)
    if mirror and is_center(marker) and _center_side(marker):
        new.x = ref.get(TAG_CX, 0.0)
    anchor = _placed_ancestor(marker)
    tail = _descendants(ref, marker)
    if anchor is not None and (old - anchor.location).length > 1e-5 \
            and (new - anchor.location).length > 1e-5:
        pivot = anchor.location.copy()
        a, b = old - pivot, new - pivot
        turn = a.rotation_difference(b).to_matrix()
        scale = b.length / a.length
        for child in tail:
            child.location = pivot + turn @ (child.location - pivot) * scale
    else:
        for child in tail:
            child.location += new - old
    marker.location = new
    marker[TAG_PLACED] = True
    if mirror:
        for child in tail:
            mirror_from(ref, child)
        mirror_from(ref, marker)


def center_hit(tree, origin, direction):
    """Diem GIUA khoi thit theo tia nhin. Mesh ho thi lay diem cham dau tien."""
    first = tree.ray_cast(origin, direction)
    if first[0] is None:
        return None
    entry = first[0]
    at = entry + direction * 1e-4
    for _i in range(32):
        hit = tree.ray_cast(at, direction)
        if hit[0] is None:
            break
        if hit[1].dot(direction) > 0.0:
            return (entry + hit[0]) * 0.5
        at = hit[0] + direction * 1e-4
    return entry


def mesh_tree(context, mesh):
    depsgraph = context.evaluated_depsgraph_get()
    ev = mesh.evaluated_get(depsgraph)
    data = ev.to_mesh()
    try:
        W = ev.matrix_world
        points = [W @ v.co for v in data.vertices]
        polys = [tuple(p.vertices) for p in data.polygons]
    finally:
        ev.to_mesh_clear()
    return BVHTree.FromPolygons(points, polys)


def queue_of(ref, mirror=True):
    """Thu tu dat: di theo cay xuong, than truoc roi tay chan, ngon, mat."""
    order = {'HIPS': 0, 'SPINE': 1, 'LEG': 2, 'ARM': 3, 'HAND': 4, 'CHAIN': 5}
    rank = {}
    for index, bone in enumerate(ref.data.bones):
        kind = bone.get(refrig.TAG_PART, "")
        rank[bone.name] = (order.get(kind, 6), index)
    out = []
    for marker in markers_of(ref):
        names = [n for n, _e in ends_of(marker)]
        if mirror and not is_center(marker) and any(_pair_side(n)[0] == 'R' for n in names):
            continue
        out.append((min(rank[n] for n in names), marker.name))
    return [name for _r, name in sorted(out)]


# ---------------------------------------------------------------- roll

def _orth(z, d):
    out = z - d * z.dot(d)
    if out.length < 1e-4:
        other = Vector((1, 0, 0)) if abs(d.x) < 0.9 else Vector((0, 1, 0))
        out = other - d * other.dot(d)
    return out.normalized()


def _frame(d, a):
    d = d.normalized()
    a = _orth(a, d)
    return Matrix((d, a, d.cross(a))).transposed()


def _hand_turn(ref, points):
    """{(inst, side): ma tran 3x3} — ban tay da xoay bao nhieu so voi mau."""
    hands = {}
    for bone in ref.data.bones:
        if bone.get(refrig.TAG_PART) != 'HAND':
            continue
        base = bone.get(refrig.TAG_BASE, "")
        if base.startswith("Palm") and base != "Palm.004":
            key = (int(bone.get(refrig.TAG_INST, 1)), bone.get(refrig.TAG_SIDE) or None)
            hands.setdefault(key, []).append((base, bone))
    out = {}
    for key, palms in hands.items():
        palms = [b for _n, b in sorted(palms, key=lambda x: x[0])]
        wrist0 = Vector(palms[0][TAG_H0])
        wrist1 = points[palms[0].name][0]
        tips0 = [Vector(b[TAG_T0]) for b in palms]
        tips1 = [points[b.name][1] for b in palms]
        d0 = sum((t - wrist0 for t in tips0), Vector()) / len(tips0)
        d1 = sum((t - wrist1 for t in tips1), Vector()) / len(tips1)
        if d0.length < 1e-6 or d1.length < 1e-6:
            continue
        if len(palms) > 1:
            a0, a1 = tips0[-1] - tips0[0], tips1[-1] - tips1[0]
            if _orth(a0, d0.normalized()).length > 0 and a0.length > 1e-6 and a1.length > 1e-6:
                out[key] = _frame(d1, a1) @ _frame(d0, a0).inverted()
                continue
        out[key] = d0.rotation_difference(d1).to_matrix()
    return out


def bone_points(ref):
    """{ten xuong: (head, tail)} the gioi — doc tu marker."""
    pts = {b.name: [_world(ref, b.name, 'H'), _world(ref, b.name, 'T')]
           for b in ref.data.bones}
    for marker in markers_of(ref):
        for name, end in ends_of(marker):
            if name in pts:
                pts[name][0 if end == 'H' else 1] = marker.location.copy()
    return pts


def roll_value(ref, bone, mirror=True):
    """Do lech tay; ben R doc tu ben L va doi dau de hai ben la anh guong."""
    if mirror:
        side, other = _pair_side(bone.name)
        if side == 'R' and other in ref.data.bones:
            return -float(ref.data.bones[other].get(TAG_ROLL, 0.0))
    return float(bone.get(TAG_ROLL, 0.0))


def auto_z(bone, d, turn):
    """Truc Z tu dong (the gioi) cho mot xuong co huong `d`, CHUA tinh do lech."""
    kind, base = bone.get(refrig.TAG_PART, ""), bone.get(refrig.TAG_BASE, bone.name)
    back, up = Vector((0, 1, 0)), Vector((0, 0, 1))
    z0 = Vector(bone[TAG_Z0])
    if kind in ('HIPS', 'SPINE') or base in ("Bicep", "Forearm"):
        return _orth(up if abs(d.y) > 0.9 else back, d)
    if base == "Shoulder":
        return _orth(up, d)
    if kind == 'LEG' and base in ("Thigh", "Shin", "Foot"):
        return _orth(up if abs(d.y) > 0.9 else -back, d)
    key = (int(bone.get(refrig.TAG_INST, 1)), bone.get(refrig.TAG_SIDE) or None)
    if (kind == 'HAND' or base == "Hand_Master") and key in turn:
        return _orth(turn[key] @ z0, d)
    d0 = Vector(bone[TAG_T0]) - Vector(bone[TAG_H0])
    if d0.length > 1e-6:
        return _orth(d0.rotation_difference(d).to_matrix() @ z0, d)
    return _orth(z0, d)


def frames(ref, mirror=True):
    """{ten xuong: (head, tail, z)} — dung dung thu se ghi vao bo ref."""
    pts = bone_points(ref)
    turn = _hand_turn(ref, pts)
    out = {}
    for bone in ref.data.bones:
        head, tail = pts[bone.name]
        d = tail - head
        if d.length < 1e-6:
            out[bone.name] = (head, tail, None)
            continue
        d = d.normalized()
        z = auto_z(bone, d, turn)
        deg = roll_value(ref, bone, mirror)
        if abs(deg) > 1e-6:
            z = Matrix.Rotation(math.radians(deg), 3, d) @ z
        out[bone.name] = (head, tail, z)
    return out


def zero_bones(ref):
    """Xuong dai bang 0 — Blender se XOA chung khi thoat Edit Mode."""
    return sorted(n for n, (h, t, _z) in frames(ref).items() if (t - h).length < 1e-4)


def apply_markers(context, ref, mirror=True):
    """Ghi vi tri + roll tu marker vao bo ref. Tra ve so xuong da ghi."""
    if mirror:
        mirror_all(ref)
    plan = frames(ref, mirror)
    if context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    hidden = ref.hide_get()
    ref.hide_set(False)
    context.view_layer.objects.active = ref
    inv = ref.matrix_world.inverted()
    rot = inv.to_3x3()
    bpy.ops.object.mode_set(mode='EDIT')
    try:
        edit = ref.data.edit_bones
        for name, (head, tail, _z) in plan.items():
            bone = edit[name]
            bone.use_connect = bone.use_connect and bone.parent is not None
            bone.head, bone.tail = inv @ head, inv @ tail
        for name, (_h, _t, z) in plan.items():
            if z is not None:
                edit[name].align_roll(rot @ z)
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')
        ref.hide_set(hidden)
    return len(plan)


def clear_markers(ref):
    count = 0
    for marker in markers_of(ref):
        bpy.data.objects.remove(marker)
        count += 1
    coll = bpy.data.collections.get(collection_name(ref))
    if coll is not None and not coll.objects:
        bpy.data.collections.remove(coll)
    if TAG_CX in ref.keys():
        del ref[TAG_CX]
    for bone in ref.data.bones:
        for tag in (TAG_H0, TAG_T0, TAG_Z0):
            if tag in bone.keys():
                del bone[tag]
    return count


def build_template(context, ref, mesh, settings, face=False):
    """Dung bo khung neu bo ref con trong, theo kieu chan + so ngon da chon."""
    have = {k for k, _i, _s in refrig.parts_in(ref)}
    add = lambda *a, **k: refrig.add_part(context, ref, *a, mesh_object=mesh, **k)
    if 'HIPS' not in have:
        add('HIPS')
    if 'SPINE' not in have:
        add('SPINE', socket="Hips")
    for side in 'LR':
        if 'ARM' not in have:
            add('ARM', side=side, inst=1, socket="Spine.003")
            add('HAND', side=side, socket=refrig.bone_name("Hand_Master", 1, side),
                fingers=settings.fingers, thumb=settings.thumb)
        if 'LEG' not in have:
            add('LEG', side=side, inst=1, socket="Hips", leg_type=settings.leg_type)
    if face and not have.intersection(refrig.FACE_KINDS):
        add('FACE', socket="Head")


# ---------------------------------------------------------------- overlay

_draw_view = _draw_text = None
_place_state = {}


def _active_ref():
    context = bpy.context
    obj = getattr(context, "active_object", None)
    if obj is not None and obj.get(TAG_MARKER):
        return bpy.data.objects.get(obj[TAG_MARKER])
    scene = getattr(context, "scene", None)
    if scene is None:
        return None
    for candidate in scene.objects:
        if candidate.type == 'EMPTY' and candidate.get(TAG_MARKER) \
                and candidate.visible_get():
            return bpy.data.objects.get(candidate[TAG_MARKER])
    return None


def _on_view():
    settings = getattr(bpy.context.scene, "srp_marker", None)
    if settings is None or not settings.overlay:
        return
    ref = _active_ref()
    if ref is None or not markers_of(ref):
        return
    plan = frames(ref, settings.mirror)
    bones, xs, zs = [], [], []
    size = max((max(p[0].z, p[1].z) for p in plan.values()), default=1.0)
    low = min((min(p[0].z, p[1].z) for p in plan.values()), default=0.0)
    size = max(size - low, 0.1) * AXIS_RATIO
    selected = {n for o in bpy.context.selected_objects if o.get(TAG_MARKER)
                for n in bones_at(o)}
    for name, (head, tail, z) in plan.items():
        bones += [head, tail]
        if z is None or (settings.axes_selected and name not in selected):
            continue
        d = tail - head
        length = min(size, d.length * 0.45)     # ngon tay ngan, truc khong de len nhau
        d = d.normalized()
        mid = (head + tail) * 0.5
        xs += [mid, mid + d.cross(z) * length]
        zs += [mid, mid + z * length]
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.depth_test_set('NONE')
    gpu.state.blend_set('ALPHA')
    gpu.state.line_width_set(2.0)
    for points, color in ((bones, (1.0, 0.75, 0.2, 0.85)), (xs, (1.0, 0.2, 0.2, 1.0)),
                          (zs, (0.25, 0.5, 1.0, 1.0))):
        if points:
            batch = batch_for_shader(shader, 'LINES', {"pos": points})
            shader.bind()
            shader.uniform_float("color", color)
            batch.draw(shader)
    gpu.state.line_width_set(1.0)
    gpu.state.blend_set('NONE')


def _on_text():
    if not _place_state.get("active"):
        return
    font = 0
    # Goc duoi: goc tren da co chu cua viewport va thanh cong cu.
    x, y = 70, 74
    blf.size(font, 20)
    blf.color(font, 1.0, 0.85, 0.3, 1.0)
    blf.position(font, x, y, 0)
    blf.draw(font, _place_state.get("title", ""))
    blf.size(font, 13)
    blf.color(font, 0.9, 0.9, 0.9, 1.0)
    blf.position(font, x, y - 24, 0)
    blf.draw(font, "Chuột trái: đặt   Shift+trái: đặt trên da   Space: giữ, sang khớp sau")
    blf.position(font, x, y - 44, 0)
    blf.draw(font, "Backspace: lùi   Tab: sang bộ phận sau   Enter/Esc: xong")


@persistent
def _on_depsgraph(scene, _depsgraph=None):
    """Keo marker mot ben thi ben kia di theo."""
    settings = getattr(scene, "srp_marker", None)
    if settings is None or not settings.mirror or _place_state.get("active"):
        return
    try:
        chosen = [o for o in bpy.context.selected_objects if o.get(TAG_MARKER)]
    except AttributeError:
        return
    for marker in chosen:
        ref = bpy.data.objects.get(marker[TAG_MARKER])
        if ref is not None:
            mirror_from(ref, marker)


# -------------------------------------------------------------- operators

class SRP_OT_marker_start(bpy.types.Operator):
    "Tạo marker cho mọi khớp. Bộ ref còn trống thì dựng khung theo kiểu chân và số ngón đang chọn"
    bl_idname = "srp.marker_start"
    bl_label = "Tạo marker"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        settings = getattr(context.scene, "srp_generate", None)
        return settings is not None and settings.target_mesh is not None

    def execute(self, context):
        generate = context.scene.srp_generate
        mesh = generate.target_mesh
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        ref = refrig.find_ref(context) or refrig.ensure_ref(
            context, refrig.ref_object_name(generate.rig_name), mesh)
        ref.hide_set(False)
        build_template(context, ref, mesh, context.scene.srp_ref,
                       context.scene.srp_marker.with_face)
        found = sync_markers(context, ref, mesh)
        ref.hide_set(True)
        self.report({'INFO'}, "%d marker. Bấm 'Đặt lần lượt' để click từng khớp" % len(found))
        return {'FINISHED'}


class SRP_OT_marker_chain(bpy.types.Operator):
    "Thêm chuỗi marker cho tai, tóc, đuôi, vạt áo... (đôi thì tạo cả hai bên)"
    bl_idname = "srp.marker_chain"
    bl_label = "Thêm chuỗi"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return refrig.find_ref(context) is not None

    def execute(self, context):
        ref = refrig.find_ref(context)
        s = context.scene.srp_marker
        mesh = context.scene.srp_generate.target_mesh
        base = s.chain_name.strip() or "Chain"
        socket = s.chain_socket.strip() or "Head"
        if socket not in ref.data.bones:
            self.report({'ERROR'}, "Không có xương %r" % socket)
            return {'CANCELLED'}
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        ref.hide_set(False)         # bo ref an thi khong vao Edit Mode duoc
        made = []
        for side in (('L', 'R') if s.chain_pair else (None,)):
            names = refrig.add_part(context, ref, 'CHAIN', side=side, socket=socket,
                                    mesh_object=mesh, chain_name=base,
                                    chain_count=s.chain_count)
            made.append(names[0])
        sync_markers(context, ref, mesh)
        ref.hide_set(True)
        self.report({'INFO'}, "Đã thêm %s, %d đốt" % (", ".join(made), s.chain_count))
        return {'FINISHED'}


class SRP_OT_marker_place(bpy.types.Operator):
    "Click lần lượt từng khớp trên model. Marker tự nằm giữa khối thịt"
    bl_idname = "srp.marker_place"
    bl_label = "Đặt lần lượt"
    bl_options = {'REGISTER', 'UNDO'}

    only_unplaced: BoolProperty(name="Bỏ qua khớp đã đặt", default=True)

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D' \
            and bool(markers_of(refrig.find_ref(context)))

    def _title(self):
        if self.index >= len(self.queue):
            return "Xong"
        name = self.queue[self.index]
        return "%d/%d  %s" % (self.index + 1, len(self.queue), name[3:])

    def _focus(self, context):
        _place_state["title"] = self._title()
        for obj in list(context.selected_objects):
            obj.select_set(False)
        if self.index < len(self.queue):
            marker = bpy.data.objects[self.queue[self.index]]
            marker.select_set(True)
            context.view_layer.objects.active = marker
        context.area.tag_redraw()

    def _finish(self, context):
        _place_state["active"] = False
        context.area.tag_redraw()
        return {'FINISHED'}

    def invoke(self, context, _event):
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        self.ref = refrig.find_ref(context)
        settings = context.scene.srp_marker
        self.mirror = settings.mirror
        self.queue = queue_of(self.ref, self.mirror)
        first = next((i for i, n in enumerate(self.queue)
                      if not bpy.data.objects[n].get(TAG_PLACED)), None)
        self.index = first if (first is not None and self.only_unplaced) else 0
        mesh = context.scene.srp_generate.target_mesh
        self.tree = mesh_tree(context, mesh) if mesh is not None else None
        self.history = []
        _place_state["active"] = True
        self._focus(context)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _view(self, context, event):
        region = next((r for r in context.area.regions if r.type == 'WINDOW'), None)
        if region is None:
            return None
        x, y = event.mouse_x - region.x, event.mouse_y - region.y
        if not (0 <= x < region.width and 0 <= y < region.height):
            return None
        rv3d = context.area.spaces.active.region_3d
        coord = (x, y)
        return (region, rv3d, coord,
                view3d_utils.region_2d_to_origin_3d(region, rv3d, coord),
                view3d_utils.region_2d_to_vector_3d(region, rv3d, coord))

    def _snapshot(self):
        return (self.index, {m.name: (m.location.copy(), bool(m.get(TAG_PLACED)))
                             for m in markers_of(self.ref)})

    def _next_part(self):
        def part(marker_name):
            bone = self.ref.data.bones[ends_of(bpy.data.objects[marker_name])[0][0]]
            return refrig.part_of(bone)
        now = part(self.queue[self.index])
        i = self.index + 1
        while i < len(self.queue) and part(self.queue[i]) == now:
            i += 1
        return i

    def modal(self, context, event):
        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} \
                or (event.type.startswith('NUMPAD') and event.type != 'NUMPAD_ENTER') \
                or event.type == 'MOUSEMOVE':
            return {'PASS_THROUGH'}
        if event.value != 'PRESS':
            return {'RUNNING_MODAL'} if event.type == 'LEFTMOUSE' else {'PASS_THROUGH'}
        if event.type in {'ESC', 'RET', 'NUMPAD_ENTER', 'RIGHTMOUSE'}:
            return self._finish(context)
        if event.type == 'BACK_SPACE':
            if self.history:
                self.index, saved = self.history.pop()
                for name, (loc, placed) in saved.items():
                    marker = bpy.data.objects[name]
                    marker.location, marker[TAG_PLACED] = loc, placed
                self._focus(context)
            return {'RUNNING_MODAL'}
        if event.type in {'SPACE', 'TAB'}:
            self.history.append(self._snapshot())
            self.index = self.index + 1 if event.type == 'SPACE' else self._next_part()
        elif event.type == 'LEFTMOUSE':
            view = self._view(context, event)
            if view is None:
                return {'PASS_THROUGH'}
            region, rv3d, coord, origin, direction = view
            marker = bpy.data.objects[self.queue[self.index]]
            point = None
            if self.tree is not None:
                if event.shift:
                    point = self.tree.ray_cast(origin, direction)[0]
                else:
                    point = center_hit(self.tree, origin, direction)
            if point is None:       # ngoai model: giu do sau hien tai
                point = view3d_utils.region_2d_to_location_3d(region, rv3d, coord,
                                                              marker.location)
            self.history.append(self._snapshot())
            place(self.ref, marker, point, self.mirror)
            self.index += 1
        else:
            return {'PASS_THROUGH'}
        if self.index >= len(self.queue):
            self._focus(context)
            return self._finish(context)
        self._focus(context)
        return {'RUNNING_MODAL'}


class SRP_OT_marker_apply(bpy.types.Operator):
    "Ghi vị trí và roll từ marker vào bộ ref"
    bl_idname = "srp.marker_apply"
    bl_label = "Áp dụng vào bộ ref"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(markers_of(refrig.find_ref(context)))

    def execute(self, context):
        ref = refrig.find_ref(context)
        settings = context.scene.srp_marker
        if settings.mirror:
            mirror_all(ref)
        bad = zero_bones(ref)
        if bad:
            self.report({'ERROR'}, "Hai đầu xương trùng nhau: %s" % ", ".join(bad[:5]))
            return {'CANCELLED'}
        count = apply_markers(context, ref, settings.mirror)
        self.report({'INFO'}, "Đã ghi %d xương. Sang bước Dựng rig" % count)
        return {'FINISHED'}


class SRP_OT_marker_roll(bpy.types.Operator):
    "Đổi roll của các xương bắt đầu tại marker đang chọn"
    bl_idname = "srp.marker_roll"
    bl_label = "Đổi roll"
    bl_options = {'REGISTER', 'UNDO'}

    delta: FloatProperty(default=90.0)
    reset: BoolProperty(default=False)

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and bool(obj.get(TAG_MARKER))

    def execute(self, context):
        marker = context.active_object
        ref = bpy.data.objects.get(marker[TAG_MARKER])
        mirror = context.scene.srp_marker.mirror
        for name in bones_at(marker):
            side, other = _pair_side(name)
            # Doi xung: ben R doc gia tri tu ben L, nen phai sua ben L, nguoc dau
            sign = 1.0
            if mirror and side == 'R' and other in ref.data.bones:
                name, sign = other, -1.0
            bone = ref.data.bones[name]
            value = 0.0 if self.reset else float(bone.get(TAG_ROLL, 0.0)) + self.delta * sign
            bone[TAG_ROLL] = (value + 180.0) % 360.0 - 180.0 if value != 180.0 else 180.0
        context.area.tag_redraw()
        return {'FINISHED'}


class SRP_OT_marker_clear(bpy.types.Operator):
    "Xoá toàn bộ marker. Bộ ref giữ nguyên"
    bl_idname = "srp.marker_clear"
    bl_label = "Xoá marker"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(markers_of(refrig.find_ref(context)))

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        ref = refrig.find_ref(context)
        count = clear_markers(ref)
        ref.hide_set(False)
        self.report({'INFO'}, "Đã xoá %d marker" % count)
        return {'FINISHED'}


class SRP_MarkerSettings(bpy.types.PropertyGroup):
    mirror: BoolProperty(name="Đối xứng", default=True,
                         description="Đặt một bên, bên kia đi theo")
    overlay: BoolProperty(name="Hiện xương + trục", default=True,
                          description="Đỏ = X (trục gập), xanh = Z")
    axes_selected: BoolProperty(name="Chỉ trục khớp đang chọn", default=True,
                                description="Tắt để xem trục của mọi xương")
    with_face: BoolProperty(name="Kèm marker mặt", default=False,
                            description="Thêm đủ hàm, răng, lưỡi, môi, mắt, mí, mày, tai")
    chain_name: StringProperty(name="Tên", default="Hair")
    chain_count: IntProperty(name="Số đốt", default=3, min=1, max=32)
    chain_pair: BoolProperty(name="Đôi L/R", default=False)
    chain_socket: StringProperty(name="Nối vào", default="Head")


def draw_panel(layout, context):
    settings = context.scene.srp_marker
    refs = context.scene.srp_ref
    ref = refrig.find_ref(context)
    found = markers_of(ref)
    if not found:
        col = layout.column(align=True)
        col.row(align=True).prop(refs, "leg_type", expand=True)
        row = col.row(align=True)
        row.prop(refs, "fingers")
        row.prop(refs, "thumb", toggle=True)
        col.prop(settings, "with_face")
        big = layout.column()
        big.scale_y = 1.4
        big.operator("srp.marker_start", icon='EMPTY_AXIS')
        return

    placed = sum(1 for m in found if m.get(TAG_PLACED))
    layout.label(text="%d/%d khớp đã đặt" % (placed, len(found)), icon='EMPTY_AXIS')
    big = layout.column()
    big.scale_y = 1.4
    big.operator("srp.marker_place", icon='RESTRICT_SELECT_OFF')
    row = layout.row(align=True)
    row.prop(settings, "mirror", toggle=True, icon='MOD_MIRROR')
    row.prop(settings, "overlay", toggle=True, icon='OVERLAY')

    active = context.active_object
    if active is not None and active.get(TAG_MARKER) == ref.name:
        box = layout.box()
        box.label(text="Roll · " + active.name[3:], icon='ORIENTATION_GIMBAL')
        for name in bones_at(active):
            bone = ref.data.bones[name]
            side, other = _pair_side(name)
            if settings.mirror and side == 'R' and other in ref.data.bones:
                bone = ref.data.bones[other]
            box.prop(bone, '["%s"]' % TAG_ROLL, text=bone.name)
        row = box.row(align=True)
        row.operator("srp.marker_roll", text="-90").delta = -90.0
        row.operator("srp.marker_roll", text="+90").delta = 90.0
        row.operator("srp.marker_roll", text="Tự động").reset = True
        box.prop(settings, "axes_selected")

    box = layout.box()
    box.label(text="Tai, tóc, đuôi, quần áo", icon='OUTLINER_OB_CURVES')
    row = box.row(align=True)
    row.prop(settings, "chain_name", text="")
    row.prop(settings, "chain_count", text="")
    row.prop(settings, "chain_pair", toggle=True)
    box.prop_search(settings, "chain_socket", ref.data, "bones", icon='BONE_DATA')
    box.operator("srp.marker_chain", icon='ADD')

    row = layout.row(align=True)
    row.scale_y = 1.3
    row.operator("srp.marker_apply", icon='CHECKMARK')
    row.operator("srp.marker_clear", text="", icon='X')


def register_extra():
    global _draw_view, _draw_text
    bpy.types.Scene.srp_marker = bpy.props.PointerProperty(type=SRP_MarkerSettings)
    _draw_view = bpy.types.SpaceView3D.draw_handler_add(_on_view, (), 'WINDOW', 'POST_VIEW')
    _draw_text = bpy.types.SpaceView3D.draw_handler_add(_on_text, (), 'WINDOW', 'POST_PIXEL')
    if _on_depsgraph not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph)


def unregister_extra():
    global _draw_view, _draw_text
    if _on_depsgraph in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph)
    for handle in (_draw_view, _draw_text):
        if handle is not None:
            bpy.types.SpaceView3D.draw_handler_remove(handle, 'WINDOW')
    _draw_view = _draw_text = None
    try:
        del bpy.types.Scene.srp_marker
    except AttributeError:
        pass


CLASSES = (SRP_MarkerSettings, SRP_OT_marker_start, SRP_OT_marker_chain,
           SRP_OT_marker_place, SRP_OT_marker_apply, SRP_OT_marker_roll,
           SRP_OT_marker_clear)
