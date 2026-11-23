"""Dat marker theo tung khop, kieu Mixamo nhung du toi tung dot xuong.

Marker KHONG thay bo ref: no la lop dat khop nam TREN bo ref. Moi marker la mot
khop = mot nhom dau/duoi xuong ref trung nhau. "Xong" ghi vi tri + roll vao bo
ref, con dung rig, IK/FK, xuat Unity van di duong cu.

Thao tac gom trong MOT che do (`srp.marker_mode`):
  click       = chon khop (khong bao gio tu nhay sang khop khac)
  giu + keo   = doi khop
  Ctrl+click  = dua khop dang chon toi cho click, vao giua khoi thit
  chuot phai  = lui mot buoc
  Enter       = xong, Esc = tam dung
Dat cac KHOP CHINH la du: dot giua (cot song, dot ngon, doan chuoi) tu noi suy
theo dang mau, van la marker that va keo duoc.

Xuong ngoai bo rig (tai, duoi, canh, toc, ao) VE ngay trong che do nay: click tu
goc ra ngon, moi click la mot khop. Cha tu tim theo xuong than gan nhat, goc lech
tam thi tu tao ca hai ben, click trung marker co san de re nhanh.

Chong chon nham: empty marker nam trong collection tat han, khong the bam trung.
Trong che do nay viewport chi nhan marker; moi click khac bi nuot.

Quy uoc roll: Y doc xuong, X la truc gap. Than: Z ra sau. Chan: Z ra truoc. Canh
tay: Z ra sau. Ban tay + ngon: khung ban tay that. Tai, toc, quan ao: giu huong
mau, xoay theo huong xuong. Ben R luon la anh guong cua ben L.
"""

import json
import math
import re

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
PICK_PX = 11                    # ban kinh bam trung marker (px, nhan ui_scale)
DRAG_PX = 3                     # chuot dich it hon the nay la click, khong phai keo


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


def end_map(ref):
    """{(ten xuong, 'H'/'T'): marker}"""
    return {(n, e): m for m in markers_of(ref) for n, e in ends_of(m)}


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


def marker_side(marker):
    # Khop giua nguoi co the mang goc ca hai chuoi Wing.L + Wing.R: khop do khong co ben
    if TAG_TWIN not in marker.keys() and _center_side(marker):
        return None
    for name, _end in ends_of(marker):
        side = _pair_side(name)[0]
        if side:
            return side
    return None


# ---------------------------------------------------- gom dau/duoi thanh khop

def joint_groups(ref):
    """[[(ten xuong, 'H'/'T'), ...]] — moi nhom la MOT khop.

    Chi gop theo quan he cha/con. Goc chuoi toc moc o dinh dau nhung khac bo
    phan nen la marker rieng. Xuong ban va dot ngon cung bo phan, khong noi lien
    nhung trung diem: phai la MOT khop, khong thi nguoi dung dat hai lan.
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
    # Sai so theo CO nhan vat: mesh FBX co ma tran xoay / scale lam hai diem trung
    # nhau lech vai phan van don vi, nguong co dinh se tach doi khop gốc ngón.
    near = max(EPS, _ref_height(ref) * 2e-4)
    for bone in bones:
        find((bone.name, 'H'))
        find((bone.name, 'T'))
        up = bone.parent
        if up is None:
            continue
        same_part = refrig.part_of(bone) == refrig.part_of(up)
        if bone.use_connect or (same_part and (bone.head_local - up.tail_local).length < near):
            join((bone.name, 'H'), (up.name, 'T'))
        elif (bone.head_local - up.head_local).length < near:
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
    old = end_map(ref)
    coll = bpy.data.collections.get(collection_name(ref))
    if coll is None:
        coll = bpy.data.collections.new(collection_name(ref))
        context.scene.collection.children.link(coll)
    # Tat han: khong bam trung trong viewport lan outliner. Che do dat tu ve marker.
    coll.hide_viewport = True
    coll.hide_select = True
    coll.hide_render = True

    if TAG_CX not in ref.keys():
        ref[TAG_CX] = float(refrig.mesh_fit(mesh)[1].x) if mesh is not None else 0.0

    used, by_end = set(), {}
    for group in joint_groups(ref):
        known = [old[tuple(e)] for e in group if tuple(e) in old]
        marker = next((m for m in known if m.name not in used), None)
        if marker is None:
            # Khop chung vua tach doi (doi cha cua mot nhanh): khop moi giu dung cho cu
            source = known[0] if known else None
            marker = bpy.data.objects.new("MK_" + _key(group), None)
            coll.objects.link(marker)
            marker.empty_display_type = 'SPHERE'
            marker.empty_display_size = 0.01
            marker.hide_render = True
            marker.location = source.location.copy() if source is not None \
                else _world(ref, *group[0])
            marker[TAG_MARKER] = ref.name
            marker[TAG_PLACED] = bool(source.get(TAG_PLACED)) if source is not None else False
        marker[TAG_ENDS] = json.dumps(["%s:%s" % e for e in group])
        used.add(marker.name)
        for e in group:
            by_end[e] = marker
    for marker in markers_of(ref):       # bo phan da xoa khoi bo ref
        if marker.name not in used:
            bpy.data.objects.remove(marker)

    for marker in markers_of(ref):
        marker.pop(TAG_PARENT, None)
    for bone in ref.data.bones:
        here, tip = by_end[(bone.name, 'H')], by_end[(bone.name, 'T')]
        if tip != here:
            tip[TAG_PARENT] = here.name
    for bone in ref.data.bones:          # goc bo phan: cha la khop dau xuong cha
        here = by_end[(bone.name, 'H')]
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

    names = end_map(ref)
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
    """Khop giua that (cot song) — khac voi khop co ben nhung chua co cap.

    Chuoi phu khong tinh: duoi va toc lech mot ben la chuyen binh thuong, ghim
    vao mat doi xung la keo chung ve giua nguoi.
    """
    ref = bpy.data.objects.get(marker.get(TAG_MARKER, ""))
    names = [n for n, _e in ends_of(marker)]
    if ref is not None:
        # Goc chuoi moc tu cot song van la khop cot song: chi xet xuong khong phai chuoi
        names = [n for n in names if n not in ref.data.bones
                 or ref.data.bones[n].get(refrig.TAG_PART) != 'CHAIN']
    return bool(names) and all(_pair_side(n)[0] is None for n in names)


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


def _on_own_side(ref, marker, point):
    """Doi xung bat: click ben nao cung duoc, diem tu ve dung ben cua khop."""
    side = marker_side(marker)
    if side is None or is_center(marker):
        return point
    dx = point.x - ref.get(TAG_CX, 0.0)
    if (side == 'L' and dx < 0.0) or (side == 'R' and dx > 0.0):
        return mirror_point(ref, point)
    return point


# ------------------------------------------------------ dat + noi suy

def _children_map(ref):
    kids = {}
    for marker in markers_of(ref):
        up = marker.get(TAG_PARENT)
        if up:
            kids.setdefault(up, []).append(marker)
    return kids


def _descendants(root, kids):
    out, stack, seen = [], list(kids.get(root.name, ())), {root.name}
    while stack:
        marker = stack.pop()
        if marker.name in seen or marker.get(TAG_PLACED):   # khop dat tay la moc
            continue
        seen.add(marker.name)
        out.append(marker)
        stack.extend(kids.get(marker.name, ()))
    return out


def _parts_at(ref, marker):
    return {refrig.part_of(ref.data.bones[n]) for n, _e in ends_of(marker)}


def _walk_to_anchor(ref, marker):
    """(moc da dat gan nhat, [khop chua dat nam giua, tu gan toi xa]).

    Chi di trong CUNG bo phan. Vuot qua ranh gioi thi dat xuong don se keo ca
    cot song va canh tay ben kia, vi chung deu la nhanh cua `Spine.003`.
    """
    mine = _parts_at(ref, marker)
    seen, between = {marker.name}, []
    up = bpy.data.objects.get(marker.get(TAG_PARENT, ""))
    while up is not None and up.name not in seen and mine & _parts_at(ref, up):
        if up.get(TAG_PLACED):
            return up, between
        seen.add(up.name)
        between.append(up)
        up = bpy.data.objects.get(up.get(TAG_PARENT, ""))
    return None, []


def _ref_height(ref):
    points = [p for b in ref.data.bones for p in (b.head_local, b.tail_local)]
    return max((max(p.z for p in points) - min(p.z for p in points)), 1e-3) \
        if points else 1.0


def place(ref, marker, point, mirror=True, auto_side=True):
    """Dat mot khop. Khop giua va khop con CHUA dat tu di theo.

    Co moc da dat thi dung phep dong dang quanh moc: dat `Neck` xong, ba dot
    lung giua tu chia theo dang cong cua mau. Khop qua sat moc (xuong don so voi
    than) thi ti le vo nghia, chi tinh tien.
    """
    old = marker.location.copy()
    new = Vector(point)
    if mirror and auto_side:
        new = _on_own_side(ref, marker, new)
    if mirror and is_center(marker) and _center_side(marker):
        new.x = ref.get(TAG_CX, 0.0)

    kids = _children_map(ref)
    anchor, between = _walk_to_anchor(ref, marker)
    moved = {m.name: m for m in _descendants(marker, kids)}
    if between:
        top = between[-1]
        moved[top.name] = top
        for m in _descendants(top, kids):
            moved[m.name] = m
    moved.pop(marker.name, None)

    similar = False
    if anchor is not None:
        pivot = anchor.location.copy()
        a, b = old - pivot, new - pivot
        limit = world_height(ref) * 0.02    # marker o he the gioi, bo ref co the scale
        if a.length > limit and b.length > limit and 0.2 < b.length / a.length < 5.0:
            similar = True
            turn = a.rotation_difference(b).to_matrix()
            scale = b.length / a.length
            for child in moved.values():
                child.location = pivot + turn @ (child.location - pivot) * scale
    if not similar:
        for child in moved.values():
            child.location += new - old
    marker.location = new
    marker[TAG_PLACED] = True
    derive(ref)
    if mirror:
        # Chi chep tu ben vua dat sang ben kia. Chep theo tung khop bi keo thi
        # ben chua dat de len ben da dat, xoa luon vi tri va co "da dat".
        mirror_all(ref, marker_side(marker) or 'L')


def derive(ref):
    """Hai dau xuong khong ai click: duoi xuong don va duoi ban tay."""
    ends = end_map(ref)
    bones = ref.data.bones
    for (kind, inst, side), part in refrig.parts_in(ref).items():
        if kind != 'ARM':
            continue
        shoulder, bicep = part.get("Shoulder"), part.get("Bicep")
        if shoulder is not None and bicep is not None:
            tip = ends[(shoulder.name, 'T')]
            if not tip.get(TAG_PLACED):
                h0, t0 = Vector(shoulder[TAG_H0]), Vector(shoulder[TAG_T0])
                full = (Vector(bicep[TAG_H0]) - h0).length
                frac = min((t0 - h0).length / full, 0.97) if full > 1e-6 else 0.85
                a = ends[(shoulder.name, 'H')].location
                b = ends[(bicep.name, 'H')].location
                if (b - a).length > 1e-4:
                    tip.location = a + (b - a) * frac
        hand = part.get("Hand_Master")
        if hand is None:
            continue
        tip = ends[(hand.name, 'T')]
        if tip.get(TAG_PLACED):
            continue
        palms = [b for b in bones if b.get(refrig.TAG_PART) == 'HAND'
                 and int(b.get(refrig.TAG_INST, 1)) == inst
                 and (b.get(refrig.TAG_SIDE) or None) == side
                 and (b.get(refrig.TAG_BASE) or "").startswith("Palm")
                 and b.get(refrig.TAG_BASE) != "Palm.004"]
        if not palms:
            continue
        w0, w1 = Vector(hand[TAG_H0]), ends[(hand.name, 'H')].location
        k0 = sum((Vector(b[TAG_T0]) for b in palms), Vector()) / len(palms)
        k1 = sum((ends[(b.name, 'T')].location for b in palms), Vector()) / len(palms)
        if (k0 - w0).length > 1e-6 and (k1 - w1).length > 1e-6:
            ratio = (Vector(hand[TAG_T0]) - w0).length / (k0 - w0).length
            tip.location = w1 + (k1 - w1) * ratio


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


# --------------------------------------------------------- danh sach khop chinh

_DIGITS = (("Thumb", "CÁI"), ("Index", "TRỎ"), ("Middle", "GIỮA"),
           ("Ring", "ÁP ÚT"), ("Pinky", "ÚT"))
STAGES = ("Thân", "Chân", "Tay", "Bàn tay", "Mặt", "Phụ kiện")


def guide_of(ref, mirror=True):
    """Cac khop nguoi dung can click, dung thu tu. Con lai tu noi suy.

    [{"marker": ten, "stage": chang, "label": cau hoi}]
    """
    ends = end_map(ref)
    out, seen = [], set()

    def ask(stage, label, bone, end, side=None):
        if bone is None:
            return
        marker = ends.get((bone.name, end))
        if marker is None or marker.name in seen:
            return
        if mirror and not is_center(marker) and marker_side(marker) == 'R':
            return
        seen.add(marker.name)
        if not mirror and side:
            label += " " + ("TRÁI" if side == 'L' else "PHẢI")
        out.append({"marker": marker.name, "stage": stage, "label": label})

    parts = sorted(refrig.parts_in(ref).items(), key=lambda x: refrig.part_sort_key(x[0]))
    for key, part in parts:
        if key[0] == 'HIPS':
            ask("Thân", "HÔNG (tâm chậu)", part.get("Hips"), 'H')
    for key, part in parts:
        if key[0] == 'SPINE':
            ask("Thân", "GỐC CỔ", part.get("Neck"), 'H')
            ask("Thân", "ĐÁY SỌ", part.get("Head"), 'H')
            ask("Thân", "ĐỈNH ĐẦU", part.get("Head"), 'T')
    for (kind, _i, side), part in parts:
        if kind != 'LEG':
            continue
        beast = (part.get("Thigh") or {}).get(refrig.TAG_LEG, 'HUMAN') != 'HUMAN'
        ask("Chân", "KHỚP HÁNG", part.get("Thigh"), 'H', side)
        ask("Chân", "ĐẦU GỐI", part.get("Shin"), 'H', side)
        ask("Chân", "CỔ CHÂN SAU" if beast else "CỔ CHÂN", part.get("Foot"), 'H', side)
        ask("Chân", "CHỖ BÀN CHẠM ĐẤT" if beast else "GỐC NGÓN CHÂN", part.get("Toe"), 'H', side)
        ask("Chân", "MŨI CHÂN", part.get("Toe"), 'T', side)
        ask("Chân", "GÓT CHÂN", part.get("Heel"), 'H', side)
    for (kind, _i, side), part in parts:
        if kind != 'ARM':
            continue
        ask("Tay", "ĐẦU TRONG XƯƠNG ĐÒN (sát cổ)", part.get("Shoulder"), 'H', side)
        ask("Tay", "KHỚP VAI", part.get("Bicep"), 'H', side)
        ask("Tay", "KHUỶU TAY", part.get("Forearm"), 'H', side)
        ask("Tay", "CỔ TAY", part.get("Hand_Master"), 'H', side)
    for (kind, _i, side), part in parts:
        if kind != 'HAND':
            continue
        for base, word in _DIGITS:
            ask("Bàn tay", "GỐC NGÓN " + word, part.get(base), 'H', side)
            ask("Bàn tay", "ĐẦU NGÓN " + word, part.get(base + ".002"), 'T', side)
    for (kind, _i, _s), part in parts:
        if kind not in refrig.FACE_KINDS:
            continue
        ask("Mặt", "BẢN LỀ HÀM", part.get("Jaw"), 'H')
        ask("Mặt", "CHÓP CẰM", part.get("Jaw"), 'T')
        ask("Mặt", "CHÓP MŨI", part.get("Nose"), 'T')
        for side in 'LR':
            ask("Mặt", "TÂM NHÃN CẦU", part.get("Eye." + side), 'H', side)
            ask("Mặt", "GỐC TAI", part.get("Ear." + side), 'H', side)
            ask("Mặt", "ĐẦU TAI", part.get("Ear." + side), 'T', side)
    for (kind, _i, side), part in parts:
        if kind != 'CHAIN':
            continue
        names = {b.name for b in part.values()}
        roots = [b for b in part.values() if not b.parent or b.parent.name not in names]
        for root in roots:
            tip = root
            while True:
                nxt = [c for c in tip.children if c.name in names]
                if not nxt:
                    break
                tip = nxt[0]
            ask("Phụ kiện", "GỐC " + root.name, root, 'H', side)
            ask("Phụ kiện", "CUỐI " + root.name, tip, 'T', side)
    return out


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
            if a0.length > 1e-6 and a1.length > 1e-6:
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


def chain_bones(ref, marker):
    """Chuoi xuong noi lien di qua khop nay, tu goc ra ngon (vd ca ngon cai)."""
    names = bones_at(marker)
    bones = ref.data.bones
    start = next((bones[n] for n in names
                  if bones[n].use_connect or any(c.use_connect for c in bones[n].children)),
                 bones[names[0]])
    return _walk_chain(start)


def _walk_chain(bone):
    """Ca chuoi noi lien chua `bone`, tu goc ra ngon."""
    while bone.use_connect and bone.parent is not None:
        bone = bone.parent
    out = [bone]
    while True:
        nxt = [c for c in out[-1].children if c.use_connect]
        if not nxt:
            return out
        out.append(nxt[0])


def _is_chain(chain):
    return chain[0].get(refrig.TAG_PART) == 'CHAIN'


def chain_menu(ref, marker):
    """Cac chuoi co the chinh tai khop nay. Khop re nhanh (goc canh) co nhieu chuoi."""
    default = chain_bones(ref, marker)
    out = [] if _is_chain(default) else [default]
    seen = {c[0].name for c in out}
    bones = ref.data.bones
    for name in bones_at(marker):
        chain = _walk_chain(bones[name])
        if _is_chain(chain) and chain[0].name not in seen:
            seen.add(chain[0].name)
            out.append(chain)
    return out


def picked_chains(ref, marker, pick=None):
    """Chuoi dang duoc chinh. Mac dinh o khop re nhanh: moi nhanh cung luc.

    Khop than co chuoi phu moc vao (cot song + goc canh) thi mac dinh van la than,
    bam vao khop lung khong duoc am tham xoay ca canh.
    """
    menu = chain_menu(ref, marker)
    if len(menu) == 1:
        return menu
    if pick:
        twin = _pair_side(pick)[1]
        for chain in menu:
            if chain[0].name in (pick, twin):
                return [chain]
    return [menu[0]] if not _is_chain(menu[0]) else menu


def chain_target(ref, marker, pick=None):
    """Khop dai dien cho MOT chuoi phu dang chon, hoac None neu dang chon nhieu."""
    chains = picked_chains(ref, marker, pick)
    if len(chains) != 1 or not _is_chain(chains[0]):
        return None
    return end_map(ref)[(chains[0][0].name, 'T')]


def _on_source_side(ref, chain, mirror):
    """Doi xung: luon tinh tren ben L, ben R tu lay anh guong."""
    if mirror and _pair_side(chain[0].name)[0] == 'R':
        twins = [_pair_side(b.name)[1] for b in chain]
        if all(n in ref.data.bones for n in twins):
            return [ref.data.bones[n] for n in twins]
    return chain


def _source_chain(ref, marker, mirror):
    """Doi xung: luon tinh tren ben L, ben R tu lay anh guong."""
    if mirror and marker_side(marker) == 'R' and marker.get(TAG_TWIN):
        twin = bpy.data.objects.get(marker[TAG_TWIN])
        if twin is not None:
            return chain_bones(ref, twin)
    return chain_bones(ref, marker)


def center_joint(tree, point, direction, reach, limit=None):
    """Dua mot khop vao giua tiet dien thit, chi dich VUONG GOC voi huong xuong.

    Dich qua `limit` la dang bam nham bo phan khac (canh, ban tay ke ben): giu
    nguyen cho cu, de nguoi dung tu keo con hon la be gay ca chuoi.
    """
    limit = reach if limit is None else limit
    d = direction.normalized()
    u = _orth(Vector((0, 0, 1)), d)
    v = d.cross(u)
    p = point.copy()
    found = tree.find_nearest(p)
    if found[0] is not None and found[1] is not None \
            and (p - found[0]).dot(found[1]) > 0.0:     # dang nam ngoai da
        if (p - found[0]).length > limit:
            return point.copy()
        p = found[0] - found[1] * min(reach * 0.1, 0.002)
    # Moi vong chi rut lech con mot nua (trung diem cac day cung), nen can nhieu vong.
    for _round in range(14):
        mids = []
        for i in range(8):
            a = math.pi * i / 8.0
            ray = (u * math.cos(a) + v * math.sin(a)).normalized()
            one = tree.ray_cast(p, ray, reach)
            two = tree.ray_cast(p, -ray, reach)
            # Phai cham mat TRONG ca hai phia, khong thi tia da chui sang bo phan khac
            if one[0] is None or two[0] is None:
                continue
            if one[1].dot(ray) <= 0.0 or two[1].dot(-ray) <= 0.0:
                continue
            mids.append((one[0] + two[0]) * 0.5)
        if len(mids) < 2:
            break
        mid = sum(mids, Vector()) / len(mids)
        step = mid - p
        p += step - d * step.dot(d)
        if step.length < 1e-5:
            break
    shift = (p - point) - d * (p - point).dot(d)
    if shift.length > limit:
        return point.copy()
    return point + shift


def center_chain(ref, tree, marker, mirror=True, chain=None, keep_root=False):
    """Can moi khop cua chuoi vao giua thit. Tra ve so khop da dich.

    Khop nao lam mot doan xuong doi huong qua 25 do thi tra ve cho cu: can giua
    chi duoc tinh chinh, khong duoc doi dang cua ngon. `keep_root`: goc dung chung
    cho nhieu nhanh, moi nhanh keo mot huong nen giu nguyen.
    """
    chain = _on_source_side(ref, chain, mirror) if chain else _source_chain(ref, marker, mirror)
    ends = end_map(ref)
    joints = [ends[(b.name, 'H')] for b in chain] + [ends[(chain[-1].name, 'T')]]
    old = [m.location.copy() for m in joints]
    new = []
    for i, point in enumerate(old):
        a, b = old[max(i - 1, 0)], old[min(i + 1, len(old) - 1)]
        near = [(old[j] - point).length for j in (i - 1, i + 1) if 0 <= j < len(old)]
        near = [x for x in near if x > 1e-6]
        if (b - a).length < 1e-6 or not near:
            new.append(point.copy())
            continue
        step = min(near)
        new.append(center_joint(tree, point, b - a, max(step, 1e-3), step * 0.6))
    if keep_root:
        new[0] = old[0].copy()
    for _pass in range(len(new)):
        bad = None
        for i in range(len(new) - 1):
            before, after = old[i + 1] - old[i], new[i + 1] - new[i]
            if after.length < 1e-6 or before.angle(after) > math.radians(25.0):
                # tra ve khop dich nhieu hon trong hai dau doan
                bad = max((i, i + 1), key=lambda j: (new[j] - old[j]).length)
                break
        if bad is None or (new[bad] - old[bad]).length < 1e-9:
            break
        new[bad] = old[bad].copy()
    moved = 0
    for m, before, after in zip(joints, old, new):
        if (after - before).length > 1e-5:
            m.location = after
            m[TAG_PLACED] = True
            moved += 1
    if not moved:
        return 0
    derive(ref)
    if mirror:
        mirror_all(ref, marker_side(joints[0]) or 'L')
    return moved


def hinge_chain(ref, marker, mirror=True, chain=None):
    """Dat truc X cua ca chuoi trung truc gap that, suy tu dang cong cua no.

    Tra ve (so xuong, None) hoac (0, ly do).
    """
    chain = _on_source_side(ref, chain, mirror) if chain else _source_chain(ref, marker, mirror)
    return _hinge_bones(ref, chain, mirror)


def _hinge_bones(ref, chain, mirror=True):
    if len(chain) < 2:
        return 0, "Chuỗi chỉ có một xương, chỉnh bằng nút xoay"
    plan = frames(ref, mirror)
    dirs = [(plan[b.name][1] - plan[b.name][0]).normalized() for b in chain]
    bends = [a.cross(b) for a, b in zip(dirs, dirs[1:])]
    # Lat cac doan cong nguoc ve cung phia voi doan cong nhieu nhat
    main = max(bends, key=lambda c: c.length)
    hinge = sum((c if c.dot(main) >= 0.0 else -c for c in bends), Vector())
    if hinge.length < math.sin(math.radians(2.0)):
        return 0, "Chuỗi gần như thẳng nên chưa suy ra được trục gập, hãy uốn nhẹ các đốt"
    hinge.normalize()
    now_x = sum((d.cross(plan[b.name][2]) for b, d in zip(chain, dirs)), Vector())
    if hinge.dot(now_x) < 0.0:
        hinge = -hinge
    turn = _hand_turn(ref, bone_points(ref))
    for bone, d in zip(chain, dirs):
        base = auto_z(bone, d, turn)
        want = _orth(hinge, d).cross(d).normalized()
        deg = math.degrees(math.atan2(d.dot(base.cross(want)), base.dot(want)))
        bone[TAG_ROLL] = deg
    return len(chain), None


# ------------------------------------------------------- chuoi xuong phu

# (nhan tren nut, ten xuong, so dot khi chi click goc + ngon, bo phan duoc lam cha)
# Canh moc o lung nhung goc thuong nam sat canh tay: lay xuong gan nhat thi canh
# giat theo tay. Tai, toc, duoi cung chi bam vao than. Ao va "Khac" moi bam tu do.
_TORSO = ('HIPS', 'SPINE')
# Cot cuoi: chuoi moc giua nguoi co duoc phep cong sang mot ben ma van la chuoi don.
# Chi duoi nhu vay; canh moc giua lung roi toa ra thi phai thanh hai canh.
CHAIN_PRESETS = (("Tai", "Ear", 2, _TORSO, False), ("Đuôi", "Tail", 5, _TORSO, True),
                 ("Cánh", "Wing", 3, _TORSO, False), ("Tóc", "Hair", 3, _TORSO, False),
                 ("Áo", "Cloth", 3, None, False), ("Khác", "Chain", 3, None, False))


def world_height(ref):
    points = [p for pair in bone_points(ref).values() for p in pair]
    if not points:
        return 1.0
    return max(max(p.z for p in points) - min(p.z for p in points), 1e-3)


def nearest_parent(ref, point, skip_right=False, kinds=None):
    """Xuong than gan diem nay nhat — cha mac dinh cua chuoi moi.

    Bo xuong mat: goc tai nam sat mi mat, noi vao mi thi tai giat theo chop mat.
    """
    best, best_d = None, None
    for name, (head, tail) in bone_points(ref).items():
        bone = ref.data.bones[name]
        base = bone.get(refrig.TAG_BASE, name)
        if bone.get(refrig.TAG_PART) in refrig.FACE_KINDS or base in refrig.POINT_ONLY:
            continue
        if skip_right and _pair_side(name)[0] == 'R':
            continue
        if kinds and bone.get(refrig.TAG_PART) not in kinds:
            continue
        span = tail - head
        t = 0.0 if span.length_squared < 1e-12 \
            else max(0.0, min(1.0, (point - head).dot(span) / span.length_squared))
        d = (head + span * t - point).length
        if best_d is None or d < best_d:
            best, best_d = name, d
    return best


def divide_points(points, count):
    """Chi click goc + ngon thi chia deu thanh `count` dot."""
    if len(points) != 2 or count <= 1:
        return [Vector(p) for p in points]
    a, b = Vector(points[0]), Vector(points[1])
    return [a.lerp(b, i / count) for i in range(count + 1)]


def _chain_names(stem, count, side):
    return [refrig._digit_name(stem if i == 0 else "%s.%03d" % (stem, i), 1, side)
            for i in range(count)]


def add_chain(context, ref, name, points, mesh=None, mirror=True, attach=None, parent=None,
              kinds=None, root_only=False):
    """Tao chuoi xuong dung theo cac diem da click. Tra ve (ten xuong ben dat, loi).

    Goc lech khoi mat doi xung thi tu tao ca hai ben. `attach` = marker co san ma
    goc bam vao (de re nhanh, vd nan canh moc tu mot khop canh).
    """
    pts = [Vector(p) for p in points]
    if len(pts) < 2:
        return None, "Chuỗi cần ít nhất 2 điểm"
    if any((a - b).length < 1e-4 for a, b in zip(pts, pts[1:])):
        return None, "Có hai khớp liền nhau trùng chỗ"
    stem = re.sub(r"[^\w]+", "_", name or "").strip("_") or "Chain"
    cx = ref.get(TAG_CX, 0.0)
    # Xet CA chuoi: canh moc dung giua lung roi toa sang mot ben van la mot doi.
    far = pts[0] if root_only else max(pts, key=lambda p: abs(p.x - cx))
    pair = mirror and abs(far.x - cx) > world_height(ref) * 0.015
    root_marker = bpy.data.objects.get(attach) if attach else None
    if pair and far.x < cx:             # ve ben phai: quy ve ben L, ben R la anh guong
        pts = [mirror_point(ref, p) for p in pts]
        if root_marker is not None and root_marker.get(TAG_TWIN):
            root_marker = bpy.data.objects.get(root_marker[TAG_TWIN])

    join = None
    if root_marker is not None:
        ends = ends_of(root_marker)
        heads = [n for n, e in ends if e == 'H']
        parent, join = (heads[0], 'H') if heads else (ends[0][0], 'T')
    parent = parent or nearest_parent(ref, pts[0], pair, kinds) or nearest_parent(ref, pts[0], pair)
    if parent is None or parent not in ref.data.bones:
        return None, "Không tìm được xương cha"

    sides = ('L', 'R') if pair else (None,)
    count = len(pts) - 1
    final, n = stem, 1
    while any(x in ref.data.bones for s in sides for x in _chain_names(final, count, s)):
        n += 1
        final = "%s_%d" % (stem, n)

    was_hidden = ref.hide_get()
    if context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    ref.hide_set(False)
    made, parents = {}, {}
    try:
        for side in sides:
            socket = parent
            if side == 'R' and _pair_side(parent)[0] == 'L':
                twin = _pair_side(parent)[1]
                socket = twin if twin in ref.data.bones else parent
            parents[side] = socket
            names = refrig.add_part(context, ref, 'CHAIN', side=side, socket=socket,
                                    mesh_object=mesh, chain_name=final, chain_count=count)
            wanted = _chain_names(final, count, side)
            for old, new in zip(names, wanted):
                if old != new:
                    ref.data.bones[old].name = new
            made[side] = wanted
        if join:
            context.view_layer.objects.active = ref
            bpy.ops.object.mode_set(mode='EDIT')
            try:
                edit = ref.data.edit_bones
                for side in sides:
                    first, up = edit[made[side][0]], edit[parents[side]]
                    if join == 'T':
                        first.use_connect = True
                    else:
                        first.head = up.head.copy()
            finally:
                bpy.ops.object.mode_set(mode='OBJECT')
        sync_markers(context, ref, mesh)
        ends = end_map(ref)
        main = made[sides[0]]
        joints = [ends[(b, 'H')] for b in main] + [ends[(main[-1], 'T')]]
        for i, (marker, point) in enumerate(zip(joints, pts)):
            if not (i == 0 and root_marker is not None):
                marker.location = point
            marker[TAG_PLACED] = True
        # Mau roll theo dung dang vua ve, ben R la anh guong cua ben L
        for i, bone_name in enumerate(main):
            bone = ref.data.bones[bone_name]
            head, tail = joints[i].location.copy(), joints[i + 1].location.copy()
            z = _orth(Vector(bone[TAG_Z0]), (tail - head).normalized())
            bone[TAG_H0], bone[TAG_T0], bone[TAG_Z0] = list(head), list(tail), list(z)
            if pair:
                other = ref.data.bones[made['R'][i]]
                other[TAG_H0] = list(mirror_point(ref, head))
                other[TAG_T0] = list(mirror_point(ref, tail))
                other[TAG_Z0] = [-z.x, z.y, z.z]
        if pair:
            mirror_all(ref, 'L')
        _hinge_bones(ref, [ref.data.bones[b] for b in main], mirror)
    finally:
        ref.hide_set(was_hidden)
    return main, None


def pair_chain(context, ref, marker, mesh=None):
    """Bien mot chuoi don da ve thanh mot doi L/R, giu nguyen dang va xuong cha.

    Tra ve (ten xuong ben L, loi).
    """
    key = chain_part_of(ref, marker)
    if key is None:
        return None, "Khớp này không thuộc chuỗi phụ"
    if key[2] is not None or len(_chain_keys(ref, key)) > 1:
        return None, "Chuỗi này đã có hai bên"
    root = chain_root(ref, key)
    if root is None:
        return None, "Không đọc được chuỗi"
    names = {b.name for b in refrig.parts_in(ref)[key].values()}
    bones, now = [root], root
    while True:
        nxt = [c for c in now.children if c.name in names]
        if not nxt:
            break
        now = nxt[0]
        bones.append(now)
    if len(bones) != len(names):
        return None, "Chuỗi có rẽ nhánh, hãy xoá rồi vẽ lại"
    ends = end_map(ref)
    points = [ends[(b.name, 'H')].location.copy() for b in bones]
    points.append(ends[(bones[-1].name, 'T')].location.copy())
    cx = ref.get(TAG_CX, 0.0)
    if max(abs(p.x - cx) for p in points) <= world_height(ref) * 0.015:
        return None, "Chuỗi nằm đúng giữa người, không có bên đối xứng"
    parent = root.parent.name if root.parent is not None else None
    # Chi bam lai khop cu khi khop do la dau cua chinh xuong cha. Khop chung voi
    # mot chuoi anh em thi tao goc rieng, khong thi chuoi moi thanh con cua anh em.
    root_marker = ends[(root.name, 'H')]
    here = [tuple(e) for e in ends_of(root_marker)]
    attach = root_marker.name if parent and (parent, 'H') in here else None
    stem = root.name
    delete_chain(context, ref, marker, mesh)
    if attach is not None and attach not in bpy.data.objects:
        attach = None
    if attach is not None:
        heads = [n for n, e in ends_of(bpy.data.objects[attach]) if e == 'H']
        if not heads or heads[0] != parent:     # add_chain lay xuong dau tien lam cha
            attach = None
    return add_chain(context, ref, stem, points, mesh, True, attach=attach, parent=parent)


def chain_part_of(ref, marker):
    """(kind, inst, side) cua chuoi phu ma khop nay thuoc ve, hoac None."""
    for name, _end in ends_of(marker):
        tag = refrig.part_of(ref.data.bones[name])
        if tag is not None and tag[0] == 'CHAIN':
            return tag
    return None


def _chain_keys(ref, key):
    """Chuoi nay va chuoi doi xung cua no."""
    keys = [key]
    part = refrig.parts_in(ref).get(key)
    if part:
        twin = _pair_side(next(iter(part.values())).name)[1]
        if twin and twin in ref.data.bones:
            other = refrig.part_of(ref.data.bones[twin])
            if other and other != key:
                keys.append(other)
    return keys


def chain_root(ref, key):
    part = refrig.parts_in(ref).get(key, {})
    names = {b.name for b in part.values()}
    return next((b for b in part.values()
                 if b.parent is None or b.parent.name not in names), None)


def delete_chain(context, ref, marker, mesh=None):
    key = chain_part_of(ref, marker)
    if key is None:
        return 0
    was_hidden = ref.hide_get()
    ref.hide_set(False)
    try:
        count = sum(refrig.drop_part(ref, *k) for k in _chain_keys(ref, key))
        sync_markers(context, ref, mesh)
    finally:
        ref.hide_set(was_hidden)
    return count


def set_chain_parent(context, ref, marker, parent, mesh=None):
    """Doi xuong cha cua chuoi (ca chuoi doi xung). Tra ve loi hoac None."""
    key = chain_part_of(ref, marker)
    if key is None:
        return "Khớp này không thuộc chuỗi phụ"
    if parent not in ref.data.bones:
        return "Không có xương %s" % parent
    todo = []
    for k in _chain_keys(ref, key):
        root = chain_root(ref, k)
        if root is None:
            continue
        up = parent
        side = _pair_side(parent)
        if k[2] in ('L', 'R') and side[0] and side[0] != k[2]:
            up = side[1] if side[1] in ref.data.bones else parent
        if up in {b.name for b in refrig.parts_in(ref)[k].values()}:
            return "Không thể nối chuỗi vào chính nó"
        todo.append((root.name, up))
    was_hidden = ref.hide_get()
    ref.hide_set(False)
    context.view_layer.objects.active = ref
    bpy.ops.object.mode_set(mode='EDIT')
    try:
        edit = ref.data.edit_bones
        for name, up in todo:
            edit[name].use_connect = False
            edit[name].parent = edit[up]
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')
        ref.hide_set(was_hidden)
    sync_markers(context, ref, mesh)
    return None


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
_S = {"active": False}


def is_active():
    return bool(_S.get("active"))


def _here():
    area = bpy.context.area
    return is_active() and area is not None and area.as_pointer() == _S.get("area")


def _on_view():
    if not _here():
        return
    ref = bpy.data.objects.get(_S["ref"])
    if ref is None:
        return
    settings = bpy.context.scene.srp_marker
    plan = frames(ref, settings.mirror)
    bones, xs, zs = [], [], []
    high = max((max(p[0].z, p[1].z) for p in plan.values()), default=1.0)
    low = min((min(p[0].z, p[1].z) for p in plan.values()), default=0.0)
    size = max(high - low, 0.1) * AXIS_RATIO
    chosen = bpy.data.objects.get(_S.get("selected") or "")
    wanted = set()
    if chosen is not None:      # hien truc ca chuoi de thay cac dot co cung truc gap khong
        wanted = {b.name for c in picked_chains(ref, chosen, _S.get("chain_pick")) for b in c}
    for name, (head, tail, z) in plan.items():
        bones += [head, tail]
        if z is None or (not settings.show_all_axes and name not in wanted):
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
    for points, color, width in ((bones, (1.0, 0.75, 0.2, 0.75), 1.5),
                                 (xs, (1.0, 0.2, 0.2, 1.0), 3.0),
                                 (zs, (0.25, 0.5, 1.0, 1.0), 3.0)):
        if points:
            gpu.state.line_width_set(width)
            batch = batch_for_shader(shader, 'LINES', {"pos": points})
            shader.bind()
            shader.uniform_float("color", color)
            batch.draw(shader)
    gpu.state.line_width_set(1.0)
    gpu.state.blend_set('NONE')


def _disc(tris, x, y, r, steps=14):
    for i in range(steps):
        a, b = 2 * math.pi * i / steps, 2 * math.pi * (i + 1) / steps
        tris += [(x, y), (x + r * math.cos(a), y + r * math.sin(a)),
                 (x + r * math.cos(b), y + r * math.sin(b))]


def _on_text():
    if not _here():
        return
    context = bpy.context
    ref = bpy.data.objects.get(_S["ref"])
    region, rv3d = context.region, context.region_data
    if ref is None or rv3d is None:
        return
    scale = context.preferences.system.ui_scale
    guide = {g["marker"] for g in _S["guide"]}
    target = _S.get("selected")
    layers = {k: [] for k in ("rest", "key", "done", "halo", "now", "pick")}
    tag = None
    for marker in markers_of(ref):
        c = view3d_utils.location_3d_to_region_2d(region, rv3d, marker.location)
        if c is None:
            continue
        name = marker.name
        if name == (_S.get("hover") or _S.get("selected")):
            tag = (c.x + 12 * scale, c.y + 8 * scale, name[3:])
        if name == target:
            _disc(layers["halo"], c.x, c.y, 11 * scale)
            _disc(layers["now"], c.x, c.y, 6 * scale)
        elif name == _S.get("hover"):
            _disc(layers["pick"], c.x, c.y, 7 * scale)
        elif marker.get(TAG_PLACED):
            _disc(layers["done"], c.x, c.y, 4.5 * scale)
        elif name in guide or marker.get(TAG_TWIN) in guide:
            _disc(layers["key"], c.x, c.y, 4 * scale)
        else:
            _disc(layers["rest"], c.x, c.y, 2.5 * scale)
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    for layer, color in (("rest", (0.75, 0.75, 0.75, 0.55)), ("key", (0.95, 0.95, 0.95, 0.9)),
                         ("done", (0.3, 0.9, 0.4, 1.0)), ("halo", (1.0, 0.55, 0.1, 0.35)),
                         ("now", (1.0, 0.55, 0.1, 1.0)), ("pick", (0.3, 0.85, 1.0, 1.0))):
        if layers[layer]:
            batch = batch_for_shader(shader, 'TRIS', {"pos": layers[layer]})
            shader.bind()
            shader.uniform_float("color", color)
            batch.draw(shader)
    sketch = _S.get("draw")
    if sketch is not None and sketch["points"]:     # chuoi dang ve + day cao su toi chuot
        line = []
        for p in sketch["points"]:
            c = view3d_utils.location_3d_to_region_2d(region, rv3d, p)
            if c is not None:
                line.append((c.x, c.y))
        dots = []
        for x0, y0 in line:
            _disc(dots, x0, y0, 5 * scale)
        if sketch.get("mouse") is not None:
            line.append(tuple(sketch["mouse"]))
        gpu.state.blend_set('ALPHA')
        shader.bind()
        shader.uniform_float("color", (1.0, 0.35, 0.8, 1.0))
        gpu.state.line_width_set(2.0)
        if len(line) > 1:
            batch_for_shader(shader, 'LINE_STRIP', {"pos": line}).draw(shader)
        if dots:
            batch_for_shader(shader, 'TRIS', {"pos": dots}).draw(shader)
        gpu.state.line_width_set(1.0)
        gpu.state.blend_set('NONE')

    font = 0
    if tag is not None:
        blf.size(font, 12 * scale)
        blf.color(font, 0.55, 0.92, 1.0, 1.0)
        blf.position(font, tag[0], tag[1], 0)
        blf.draw(font, tag[2])
    x, y = 70 * scale, 76 * scale
    blf.size(font, 22 * scale)
    blf.color(font, 1.0, 0.8, 0.3, 1.0)
    blf.position(font, x, y, 0)
    blf.draw(font, _prompt())
    blf.size(font, 13 * scale)
    blf.color(font, 0.92, 0.92, 0.92, 1.0)
    blf.position(font, x, y - 28 * scale, 0)
    if sketch is not None:
        blf.draw(font, "Click: thêm khớp    Click trúng marker ở khớp đầu: nối vào đó"
                       "    Chuột phải: bỏ khớp vừa vẽ    Enter: xong chuỗi    Esc: huỷ")
    else:
        blf.draw(font, "Click: chọn khớp    Giữ và kéo: dời    Ctrl+click: đưa khớp đang chọn tới đó"
                       "    Chuột phải: lùi    Enter: xong    Esc: tạm dừng")


def _label(name):
    """Ten de doc cua khop: tu danh sach khop chinh (ca khi chon ben doi xung)."""
    marker = bpy.data.objects.get(name or "")
    if marker is None:
        return ""
    keys = {name, marker.get(TAG_TWIN)}
    for item in _S.get("guide", ()):
        if item["marker"] in keys:
            return item["label"]
    return name[3:]


def _prompt():
    sketch = _S.get("draw")
    if sketch is not None:
        n = len(sketch["points"])
        if n == 0:
            return "Vẽ %s: click vào GỐC chuỗi" % sketch["name"]
        if n == 1:
            return "Vẽ %s: click khớp tiếp theo, tới NGỌN" % sketch["name"]
        return "Vẽ %s: %d khớp, click thêm hoặc Enter để xong" % (sketch["name"], n)
    chosen = _S.get("selected")
    if not chosen:
        return "Click vào một khớp để chọn"
    return "%s: kéo để dời, Ctrl+click để đưa tới chỗ khác" % _label(chosen)


@persistent
def _on_load(_scene=None, _depsgraph=None):
    _S.clear()
    _S["active"] = False


# -------------------------------------------------------------- operators

class SRP_OT_marker_start(bpy.types.Operator):
    "Tạo marker cho mọi khớp rồi vào chế độ đặt"
    bl_idname = "srp.marker_start"
    bl_label = "Bắt đầu đặt marker"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        settings = getattr(context.scene, "srp_generate", None)
        return settings is not None and settings.target_mesh is not None and not is_active()

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
        sync_markers(context, ref, mesh)
        if context.area is not None and context.area.type == 'VIEW_3D':
            bpy.ops.srp.marker_mode('INVOKE_DEFAULT')
        return {'FINISHED'}


class SRP_OT_marker_cmd(bpy.types.Operator):
    "Lệnh trong lúc đặt marker"
    bl_idname = "srp.marker_cmd"
    bl_label = "Lệnh marker"

    cmd: StringProperty()
    index: IntProperty(default=0)

    @classmethod
    def description(cls, _context, props):
        return {"BACK": "Lùi một bước",
                "DONE": "Ghi vào bộ ref và thoát", "PAUSE": "Thoát, giữ marker để đặt tiếp",
                "STAGE": "Mở hoặc đóng danh sách khớp của bộ phận này",
                "SELECT": "Chọn khớp này",
                "DRAW": "Vẽ chuỗi mới: click từ gốc ra ngọn. Gốc lệch tâm thì tự tạo cả hai bên",
                "DRAW_OK": "Tạo chuỗi từ các khớp vừa vẽ (Enter)",
                "DRAW_NO": "Huỷ chuỗi đang vẽ (Esc)",
                "REPARENT": "Đổi xương cha của chuỗi này (cả bên đối xứng)",
                "DEL_CHAIN": "Xoá chuỗi này (cả bên đối xứng)",
                "PICK_CHAIN": "Chọn chuỗi sẽ chịu tác động của các nút xoay, căn và trục gập",
                "PAIR_CHAIN": "Tạo thêm bên đối xứng cho chuỗi đã vẽ, giữ nguyên dáng và xương cha",
                "CENTER": "Đưa mọi đốt của chuỗi vào giữa khối thịt, giữ nguyên độ dài dọc xương",
                "HINGE": "Đặt trục X của cả chuỗi trùng trục gập, suy từ độ cong của các đốt"
                }.get(props.cmd, "")

    @classmethod
    def poll(cls, _context):
        return is_active()

    def execute(self, _context):
        _S["req"] = (self.cmd, self.index)
        return {'FINISHED'}


class SRP_OT_marker_mode(bpy.types.Operator):
    "Vào chế độ đặt marker. Trong lúc này viewport chỉ nhận marker, không chọn nhầm object khác"
    bl_idname = "srp.marker_mode"
    bl_label = "Đặt marker"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D' \
            and not is_active() and bool(markers_of(refrig.find_ref(context)))

    # ------------------------------------------------ vao / ra

    def invoke(self, context, _event):
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        ref = refrig.find_ref(context)
        settings = context.scene.srp_marker
        self.ref_name = ref.name
        self.mirror = settings.mirror
        self.area = context.area
        self.history = []
        self.drag = None
        mesh = context.scene.srp_generate.target_mesh
        # File luu tu ban cu: gop khop goc ngon, an empty, dung lai cay khop.
        # Vi tri marker da co giu nguyen.
        sync_markers(context, ref, mesh)
        self.tree = mesh_tree(context, mesh) if mesh is not None else None
        ref.hide_set(True)          # xuong ref nam chong len marker, che mat khop
        self._deselect(context)
        guide = guide_of(ref, self.mirror)
        _S.clear()
        _S.update(active=True, area=context.area.as_pointer(), ref=ref.name, guide=guide,
                  selected=None, hover=None, req=None, open_stage=None)
        self.timer = context.window_manager.event_timer_add(0.15, window=context.window)
        context.window_manager.modal_handler_add(self)
        context.window.cursor_modal_set('CROSSHAIR')
        self._redraw()
        return {'RUNNING_MODAL'}

    def _leave(self, context):
        _S["active"] = False
        context.window_manager.event_timer_remove(self.timer)
        context.window.cursor_modal_restore()
        ref = bpy.data.objects.get(self.ref_name)
        if ref is not None:
            ref.hide_set(False)
            self._deselect(context)
            ref.select_set(True)
            context.view_layer.objects.active = ref
        self._redraw()

    def cancel(self, context):
        self._leave(context)

    def _finish(self, context):
        ref = bpy.data.objects[self.ref_name]
        if self.mirror:
            mirror_all(ref)
        bad = zero_bones(ref)
        if bad:
            self.report({'ERROR'}, "Hai đầu xương trùng nhau: %s" % ", ".join(bad[:5]))
            return {'RUNNING_MODAL'}
        count = apply_markers(context, ref, self.mirror)
        self._leave(context)
        self.report({'INFO'}, "Đã ghi %d xương vào bộ ref. Bấm Dựng rig + widget" % count)
        return {'FINISHED'}

    def _pause(self, context):
        self._leave(context)
        self.report({'INFO'}, "Tạm dừng. Marker vẫn giữ, bấm Tiếp tục đặt")
        return {'FINISHED'}

    # ------------------------------------------------ tien ich

    def _redraw(self):
        if self.area is not None:
            self.area.tag_redraw()

    @staticmethod
    def _deselect(context):
        for obj in list(context.view_layer.objects.selected):
            obj.select_set(False)

    def _regions(self):
        return {r.type: r for r in self.area.regions}

    @staticmethod
    def _inside(region, event):
        return region is not None and region.width > 1 and region.height > 1 \
            and region.x <= event.mouse_x < region.x + region.width \
            and region.y <= event.mouse_y < region.y + region.height

    def _over_nav_gizmo(self, context, event, regions):
        """Cum gizmo xoay / zoom goc tren ben phai viewport."""
        view = regions.get('WINDOW')
        space = self.area.spaces.active
        if view is None or not (space.show_gizmo and space.show_gizmo_navigate):
            return False
        scale = context.preferences.system.ui_scale
        panel = regions.get('UI')
        right = view.x + view.width
        if panel is not None and panel.width > 1:
            right = min(right, panel.x)
        top = view.y + view.height
        for name in ('HEADER', 'TOOL_HEADER'):
            bar = regions.get(name)
            if bar is not None and bar.height > 1 and bar.y > view.y + view.height / 2:
                top = min(top, bar.y)
        # Do sat hinh that: vung chu nhat rong hon se nuot click o dau canh, chop tai.
        dx, dy = event.mouse_x - (right - 58 * scale), event.mouse_y - (top - 52 * scale)
        if math.hypot(dx, dy) <= 50 * scale:
            return True
        return right - 46 * scale <= event.mouse_x <= right - 12 * scale \
            and top - 205 * scale <= event.mouse_y <= top - 95 * scale

    def _xy(self, region, event):
        return event.mouse_x - region.x, event.mouse_y - region.y

    def _pick(self, context, region, xy):
        """Marker gan chuot nhat."""
        ref = bpy.data.objects[self.ref_name]
        rv3d = self.area.spaces.active.region_3d
        limit = PICK_PX * context.preferences.system.ui_scale
        best, best_d = None, limit
        # Bat duoc MOI khop, ke ca dot giua tu noi suy.
        for marker in markers_of(ref):
            c = view3d_utils.location_3d_to_region_2d(region, rv3d, marker.location)
            if c is None:
                continue
            d = math.hypot(c.x - xy[0], c.y - xy[1])
            if d < best_d:
                best, best_d = marker.name, d
        return best

    def _snapshot(self):
        ref = bpy.data.objects[self.ref_name]
        return (_S.get("selected"), {m.name: (m.location.copy(), bool(m.get(TAG_PLACED)))
                                     for m in markers_of(ref)})

    def _restore(self, saved):
        _S["selected"], rows = saved
        for name, (loc, placed) in rows.items():
            marker = bpy.data.objects.get(name)
            if marker is not None:
                marker.location = loc
                marker[TAG_PLACED] = placed

    def _back(self):
        if self.history:
            self._restore(self.history.pop())

    def _command(self, context, cmd, index):
        if cmd == 'BACK':
            self._back()
        elif cmd == 'STAGE':
            stage = STAGES[index]
            _S["open_stage"] = None if _S.get("open_stage") == stage else stage
        elif cmd == 'SELECT':
            if 0 <= index < len(_S["guide"]):
                _S["selected"] = _S["guide"][index]["marker"]
        elif cmd == 'DRAW':
            settings = context.scene.srp_marker
            label, bone_name, count, kinds, root_only = CHAIN_PRESETS[index]
            settings.chain_name, settings.chain_count = bone_name, count
            _S["draw"] = {"name": label, "points": [], "attach": None, "mouse": None,
                          "kinds": kinds, "root_only": root_only}
        elif cmd == 'PICK_CHAIN':
            chosen = bpy.data.objects.get(_S.get("selected") or "")
            if chosen is not None:
                menu = chain_menu(bpy.data.objects[self.ref_name], chosen)
                _S["chain_pick"] = menu[index][0].name if 0 <= index < len(menu) else None
        elif cmd == 'PAIR_CHAIN':
            chosen = bpy.data.objects.get(_S.get("selected") or "")
            ref = bpy.data.objects[self.ref_name]
            chosen = chain_target(ref, chosen, _S.get("chain_pick")) if chosen else None
            if chosen is not None:
                made, why = pair_chain(context, ref, chosen,
                                       context.scene.srp_generate.target_mesh)
                self._deselect(context)
                if why:
                    self.report({'WARNING'}, why)
                else:
                    self.history = []       # marker cu da doi ten, lui lai la vo nghia
                    _S["guide"] = guide_of(ref, self.mirror)
                    _S["selected"] = end_map(ref)[(made[0], 'T')].name
                    self.report({'INFO'}, "Đã tạo hai bên: %s" % made[0])
        elif cmd == 'DRAW_OK':
            self._draw_commit(context)
        elif cmd == 'DRAW_NO':
            _S["draw"] = None
        elif cmd in {'REPARENT', 'DEL_CHAIN'}:
            chosen = bpy.data.objects.get(_S.get("selected") or "")
            ref = bpy.data.objects[self.ref_name]
            mesh = context.scene.srp_generate.target_mesh
            chosen = chain_target(ref, chosen, _S.get("chain_pick")) if chosen else None
            if chosen is not None and cmd == 'DEL_CHAIN':
                gone = delete_chain(context, ref, chosen, mesh)
                # Lich su giu vi tri cua khop da xoa, lui lai la vo nghia
                self.history = []
                _S["selected"] = None
                _S["guide"] = guide_of(ref, self.mirror)
                self.report({'INFO'}, "Đã xoá %d xương" % gone)
            elif chosen is not None:
                why = set_chain_parent(context, ref, chosen,
                                       context.scene.srp_marker.chain_socket.strip(), mesh)
                self.report({'ERROR'} if why else {'INFO'}, why or "Đã đổi xương cha")
            self._deselect(context)
        elif cmd in {'CENTER', 'HINGE'}:
            chosen = bpy.data.objects.get(_S.get("selected") or "")
            ref = bpy.data.objects[self.ref_name]
            if chosen is not None and cmd == 'CENTER' and self.tree is not None:
                self.history.append(self._snapshot())
                chains = picked_chains(ref, chosen, _S.get("chain_pick"))
                count = sum(center_chain(ref, self.tree, chosen, self.mirror, chain=c,
                                         keep_root=len(chains) > 1) for c in chains)
                if count:
                    self.report({'INFO'}, "Đã căn %d khớp vào giữa khối thịt" % count)
                else:
                    self.history.pop()
                    self.report({'WARNING'}, "Các đốt còn nằm xa bộ phận này. "
                                             "Kéo chúng vào gần rồi căn lại")
            elif chosen is not None and cmd == 'HINGE':
                count, why = 0, None
                for chain in picked_chains(ref, chosen, _S.get("chain_pick")):
                    done, reason = hinge_chain(ref, chosen, self.mirror, chain=chain)
                    count += done
                    why = why or reason
                self.report({'WARNING'} if why else {'INFO'},
                            "Đã đặt trục gập cho %d xương%s"
                            % (count, ". " + why if why else ""))
        elif cmd == 'DONE':
            return self._finish(context)
        elif cmd == 'PAUSE':
            return self._pause(context)
        self._redraw()
        return None

    def _click_point(self, region, xy, event, depth):
        """Diem 3D duoi chuot; `depth` la diem giu do sau khi click ra ngoai model."""
        rv3d = self.area.spaces.active.region_3d
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, xy)
        direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, xy)
        point = None
        if self.tree is not None:
            if event.shift:
                point = self.tree.ray_cast(origin, direction)[0]
            else:
                point = center_hit(self.tree, origin, direction)
        if point is None:
            point = view3d_utils.region_2d_to_location_3d(region, rv3d, xy, depth)
        return point

    # ------------------------------------------------ ve chuoi

    def _draw_commit(self, context):
        sketch = _S.get("draw")
        if sketch is None:
            return
        if len(sketch["points"]) < 2:
            self.report({'WARNING'}, "Chuỗi cần ít nhất gốc và ngọn")
            return
        ref = bpy.data.objects[self.ref_name]
        settings = context.scene.srp_marker
        mesh = context.scene.srp_generate.target_mesh
        points = divide_points(sketch["points"], settings.chain_count)
        made, why = add_chain(context, ref, settings.chain_name, points, mesh,
                              self.mirror, attach=sketch["attach"], kinds=sketch.get("kinds"),
                              root_only=sketch.get("root_only", False))
        self._deselect(context)
        if why:
            self.report({'ERROR'}, why)
            return
        _S["draw"] = None
        _S["guide"] = guide_of(ref, self.mirror)
        _S["open_stage"] = "Phụ kiện"
        _S["selected"] = end_map(ref)[(made[0], 'T')].name
        parent = ref.data.bones[made[0]].parent
        self.report({'INFO'}, "Đã thêm %s, %d đốt, nối vào %s"
                    % (made[0], len(made), parent.name if parent else "gốc"))

    def _draw_event(self, context, event, regions, view, over_view):
        sketch, kind = _S["draw"], event.type
        if kind == 'MOUSEMOVE':
            sketch["mouse"] = self._xy(view, event) if over_view else None
            hover = None
            if over_view and not sketch["points"]:
                hover = self._pick(context, view, self._xy(view, event))
            if hover != _S.get("hover"):
                _S["hover"] = hover
                context.window.cursor_modal_set('HAND' if hover else 'CROSSHAIR')
            self._redraw()
            return {'PASS_THROUGH'} if over_view else {'RUNNING_MODAL'}
        if event.value != 'PRESS':
            return {'RUNNING_MODAL'}
        if kind in {'RET', 'NUMPAD_ENTER'}:
            self._draw_commit(context)
        elif kind == 'ESC':
            _S["draw"] = None
        elif kind == 'RIGHTMOUSE' or (kind == 'Z' and event.ctrl):
            if sketch["points"]:
                sketch["points"].pop()
                if not sketch["points"]:
                    sketch["attach"] = None
            else:
                _S["draw"] = None
        elif kind == 'LEFTMOUSE' and over_view:
            if self._over_nav_gizmo(context, event, regions):
                return {'PASS_THROUGH'}
            xy = self._xy(view, event)
            if not sketch["points"]:
                hit = self._pick(context, view, xy)
                if hit is not None:
                    sketch["attach"] = hit
                    sketch["points"].append(bpy.data.objects[hit].location.copy())
                else:
                    ref = bpy.data.objects[self.ref_name]
                    sketch["points"].append(self._click_point(
                        view, xy, event, ref.matrix_world.translation))
            else:
                point = self._click_point(view, xy, event, sketch["points"][-1])
                if (point - sketch["points"][-1]).length > 1e-4:
                    sketch["points"].append(point)
        self._redraw()
        return {'RUNNING_MODAL'}

    # ------------------------------------------------ vong su kien

    def modal(self, context, event):
        if not is_active():
            return {'CANCELLED'}
        # Moi nhip: khong de object nao duoc chon, ke ca qua duong khong luong truoc.
        if context.view_layer.objects.selected:
            self._deselect(context)

        settings = context.scene.srp_marker
        if settings.mirror != self.mirror:
            self.mirror = settings.mirror
            if self.mirror:
                mirror_all(bpy.data.objects[self.ref_name])
            _S["guide"] = guide_of(bpy.data.objects[self.ref_name], self.mirror)
            self._redraw()

        request = _S.get("req")
        if request:
            _S["req"] = None
            result = self._command(context, *request)
            if result is not None and result != {'RUNNING_MODAL'}:
                return result
        if event.type == 'TIMER':
            return {'PASS_THROUGH'}

        regions = self._regions()
        kind, value = event.type, event.value

        if self.drag is not None:
            return self._on_drag(context, event, regions)

        # Dieu huong viewport luon di qua
        if kind in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'TRACKPADPAN',
                    'TRACKPADZOOM', 'MOUSEROTATE', 'MOUSESMARTZOOM', 'HOME'} \
                or (kind.startswith('NUMPAD') and kind != 'NUMPAD_ENTER'):
            return {'PASS_THROUGH'}
        inputs = context.preferences.inputs
        if kind == 'LEFTMOUSE' and event.alt and inputs.use_mouse_emulate_3_button:
            return {'PASS_THROUGH'}
        if kind == 'S' and event.ctrl:      # Ctrl+S
            return {'PASS_THROUGH'}

        # Panel ben phai cua chinh viewport nay: bam nut, keo thanh roll
        if self._inside(regions.get('UI'), event):
            if _S.get("hover"):
                _S["hover"] = None
                self._redraw()
            return {'PASS_THROUGH'}

        view = regions.get('WINDOW')
        over_view = self._inside(view, event) \
            and not self._inside(regions.get('TOOLS'), event) \
            and not self._inside(regions.get('HEADER'), event) \
            and not self._inside(regions.get('TOOL_HEADER'), event)

        if _S.get("draw") is not None:
            return self._draw_event(context, event, regions, view, over_view)

        if kind == 'MOUSEMOVE':
            hover = self._pick(context, view, self._xy(view, event)) if over_view else None
            if hover != _S.get("hover"):
                _S["hover"] = hover
                context.window.cursor_modal_set('HAND' if hover else 'CROSSHAIR')
                self._redraw()
            return {'PASS_THROUGH'} if over_view else {'RUNNING_MODAL'}

        if value == 'PRESS':
            if kind in {'RET', 'NUMPAD_ENTER'}:
                result = self._finish(context)
                return result
            if kind == 'ESC':
                return self._pause(context)
            if kind == 'RIGHTMOUSE' or (kind == 'Z' and event.ctrl):
                if over_view or kind == 'Z':
                    self._back()
                    self._redraw()
                return {'RUNNING_MODAL'}
            if kind == 'LEFTMOUSE' and over_view:
                if self._over_nav_gizmo(context, event, regions):
                    return {'PASS_THROUGH'}
                self._press(context, event, view)
                return {'RUNNING_MODAL'}
        return {'RUNNING_MODAL'}    # moi thu khac bi nuot: khong chon, khong doi gi

    def _press(self, context, event, view):
        xy = self._xy(view, event)
        chosen = bpy.data.objects.get(_S.get("selected") or "")
        # Ctrl truoc: dich toi sat marker khac van la dich, khong bi hieu la chon.
        if event.ctrl:
            if chosen is not None:
                ref = bpy.data.objects[self.ref_name]
                self.history.append(self._snapshot())
                place(ref, chosen, self._click_point(view, xy, event, chosen.location),
                      self.mirror)
                self._redraw()
            return
        hit = self._pick(context, view, xy)
        if hit is not None:
            _S["selected"] = hit
            self.drag = {"name": hit, "start": xy, "saved": self._snapshot(), "moved": False}
            self._redraw()
        # Click ra ngoai: khong lam gi. Bam truot marker khong duoc lam khop nhay di
        # hay mat khop dang chon.

    def _on_drag(self, context, event, regions):
        drag, kind = self.drag, event.type
        ref = bpy.data.objects[self.ref_name]
        if kind in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            self._restore(drag["saved"])
            self.drag = None
            self._redraw()
            return {'RUNNING_MODAL'}
        if kind == 'LEFTMOUSE' and event.value == 'RELEASE':
            self.drag = None
            if drag["moved"]:
                self.history.append(drag["saved"])
            self._redraw()
            return {'RUNNING_MODAL'}
        if kind == 'MOUSEMOVE':
            view = regions['WINDOW']
            xy = self._xy(view, event)
            if not drag["moved"] and math.hypot(xy[0] - drag["start"][0],
                                                xy[1] - drag["start"][1]) < DRAG_PX:
                return {'RUNNING_MODAL'}
            drag["moved"] = True
            marker = bpy.data.objects[drag["name"]]
            rv3d = self.area.spaces.active.region_3d
            point = view3d_utils.region_2d_to_location_3d(view, rv3d, xy, marker.location)
            place(ref, marker, point, self.mirror, auto_side=False)
            self._redraw()
        return {'RUNNING_MODAL'}


class SRP_OT_marker_apply(bpy.types.Operator):
    "Ghi vị trí và roll từ marker vào bộ ref"
    bl_idname = "srp.marker_apply"
    bl_label = "Ghi vào bộ ref"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return not is_active() and bool(markers_of(refrig.find_ref(context)))

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
    "Đổi roll của xương tại marker đang chọn"
    bl_idname = "srp.marker_roll"
    bl_label = "Đổi roll"

    delta: FloatProperty(default=90.0)
    reset: BoolProperty(default=False)

    @classmethod
    def poll(cls, _context):
        return is_active() and bool(_S.get("selected"))

    def execute(self, context):
        marker = bpy.data.objects.get(_S["selected"])
        if marker is None:
            return {'CANCELLED'}
        ref = bpy.data.objects.get(marker[TAG_MARKER])
        settings = context.scene.srp_marker
        mirror = settings.mirror
        picked = [b.name for c in picked_chains(ref, marker, _S.get("chain_pick")) for b in c]
        names = picked if settings.roll_chain \
            else [n for n in bones_at(marker) if n in picked]
        for name in names:
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
        return not is_active() and bool(markers_of(refrig.find_ref(context)))

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
                         description="Đặt một bên, bên kia đi theo. Click bên nào cũng được")
    show_all_axes: BoolProperty(name="Hiện trục mọi xương", default=False,
                                description="Tắt: chỉ hiện trục của chuỗi đang chọn")
    roll_chain: BoolProperty(name="Xoay cả chuỗi", default=True,
                             description="Nút xoay áp dụng cho mọi đốt của chuỗi đang chọn")
    with_face: BoolProperty(name="Kèm marker mặt", default=False,
                            description="Thêm đủ hàm, răng, lưỡi, môi, mắt, mí, mày, tai")
    chain_name: StringProperty(name="Tên", default="Hair",
                               description="Tên xương, các đốt sau tự thêm .001, .002")
    chain_count: IntProperty(name="Số đốt", default=3, min=1, max=32,
                             description="Chỉ dùng khi bạn chỉ click gốc và ngọn: chia đều "
                                         "thành chừng này đốt. Click nhiều khớp thì mỗi click là một khớp")
    chain_socket: StringProperty(name="Nối vào", default="",
                                 description="Xương cha mới của chuỗi đang chọn")


def draw_panel(layout, context):
    """Ngoai che do dat: chuan bi, hoac tiep tuc."""
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
        big.scale_y = 1.5
        big.operator("srp.marker_start", icon='EMPTY_AXIS')
        return

    guide = guide_of(ref, settings.mirror)
    done = sum(1 for g in guide if bpy.data.objects[g["marker"]].get(TAG_PLACED))
    layout.label(text="Đã đặt %d/%d khớp chính" % (done, len(guide)), icon='EMPTY_AXIS')
    big = layout.column()
    big.scale_y = 1.5
    big.operator("srp.marker_mode", text="Mở chỉnh marker", icon='RESTRICT_SELECT_OFF')
    layout.operator("srp.marker_clear", icon='X')


def draw_mode(layout, context):
    """Trong che do dat: chi con nhung gi can de dat xong."""
    settings = context.scene.srp_marker
    ref = bpy.data.objects.get(_S.get("ref", ""))
    if ref is None:
        return
    sketch = _S.get("draw")
    if sketch is not None:
        box = layout.box()
        box.label(text="Đang vẽ: " + sketch["name"], icon='GREASEPENCIL')
        box.label(text="%d khớp" % len(sketch["points"]))
        box.prop(settings, "chain_name")
        sub = box.row()
        sub.enabled = len(sketch["points"]) <= 2
        sub.prop(settings, "chain_count")
        if settings.mirror:
            box.label(text="Gốc lệch tâm: tự tạo cả hai bên", icon='MOD_MIRROR')
        row = layout.row(align=True)
        row.scale_y = 1.5
        row.operator("srp.marker_cmd", text="Xong chuỗi", icon='CHECKMARK').cmd = 'DRAW_OK'
        row.operator("srp.marker_cmd", text="Huỷ", icon='X').cmd = 'DRAW_NO'
        layout.prop(settings, "mirror", toggle=True, icon='MOD_MIRROR')
        return

    guide = _S["guide"]
    chosen = bpy.data.objects.get(_S.get("selected") or "")
    same = {chosen.name, chosen.get(TAG_TWIN)} if chosen is not None else set()

    box = layout.box()
    box.scale_y = 1.2
    box.label(text=_label(_S.get("selected")) or "Chưa chọn khớp",
              icon='RESTRICT_SELECT_OFF')

    col = layout.column(align=True)
    for stage_index, stage in enumerate(STAGES):
        rows = [i for i, g in enumerate(guide) if g["stage"] == stage]
        if not rows:
            continue
        left = [i for i in rows if not bpy.data.objects[guide[i]["marker"]].get(TAG_PLACED)]
        is_open = _S.get("open_stage") == stage
        op = col.operator("srp.marker_cmd", depress=is_open,
                          text="%s  %d/%d" % (stage, len(rows) - len(left), len(rows)),
                          icon='DOWNARROW_HLT' if is_open else 'RIGHTARROW')
        op.cmd, op.index = 'STAGE', stage_index
        if is_open:
            for i in rows:
                item = guide[i]
                placed = bpy.data.objects[item["marker"]].get(TAG_PLACED)
                op = col.operator("srp.marker_cmd", text=item["label"],
                                  depress=item["marker"] in same,
                                  icon='CHECKMARK' if placed else 'RADIOBUT_OFF')
                op.cmd, op.index = 'SELECT', i

    row = layout.row(align=True)
    row.operator("srp.marker_cmd", text="Lùi", icon='LOOP_BACK').cmd = 'BACK'
    row.prop(settings, "mirror", toggle=True, icon='MOD_MIRROR')

    add = layout.box()
    add.label(text="Thêm chuỗi xương", icon='ADD')
    grid = add.grid_flow(columns=3, even_columns=True, align=True)
    for i, (label, *_rest) in enumerate(CHAIN_PRESETS):
        op = grid.operator("srp.marker_cmd", text=label)
        op.cmd, op.index = 'DRAW', i

    if chosen is not None and chosen.get(TAG_MARKER) == ref.name:
        pick = _S.get("chain_pick")
        menu = chain_menu(ref, chosen)
        chains = picked_chains(ref, chosen, pick)
        if len(menu) > 1:
            branch = layout.box()
            branch.label(text="Khớp này có %d chuỗi, chỉnh chuỗi nào?" % len(menu),
                         icon='OUTLINER_DATA_ARMATURE')
            col = branch.column(align=True)
            col.scale_y = 1.15
            every = [c for c in menu if _is_chain(c)]
            if len(every) > 1:
                op = col.operator("srp.marker_cmd", text="Tất cả nhánh",
                                  depress=len(chains) > 1)
                op.cmd, op.index = 'PICK_CHAIN', -1
            for i, option in enumerate(menu):
                op = col.operator("srp.marker_cmd", text="%s  (%d đốt)"
                                  % (option[0].name, len(option)),
                                  depress=len(chains) == 1 and chains[0][0] == option[0])
                op.cmd, op.index = 'PICK_CHAIN', i
        target = chain_target(ref, chosen, pick)
        key = chain_part_of(ref, target) if target is not None else None
        if key is None and len(chains) > 1:
            layout.label(text="Chọn một nhánh để đổi cha hoặc xoá", icon='INFO')
        if key is not None:
            extra = layout.box()
            root = chain_root(ref, key)
            up = root.parent.name if root is not None and root.parent else "gốc"
            extra.label(text="Chuỗi %s · nối vào %s" % (root.name if root else "", up),
                        icon='LINKED')
            row = extra.row(align=True)
            row.prop_search(settings, "chain_socket", ref.data, "bones", text="")
            row.operator("srp.marker_cmd", text="Đổi cha").cmd = 'REPARENT'
            if key[2] is None and len(_chain_keys(ref, key)) == 1:
                extra.operator("srp.marker_cmd", text="Tạo bên đối xứng",
                               icon='MOD_MIRROR').cmd = 'PAIR_CHAIN'
            extra.operator("srp.marker_cmd", text="Xoá chuỗi", icon='TRASH').cmd = 'DEL_CHAIN'
        tune = layout.box()
        tune.label(text=chains[0][0].name if len(chains) == 1 else "%d nhánh" % len(chains),
                   icon='BONE_DATA')
        col = tune.column(align=True)
        col.scale_y = 1.2
        col.operator("srp.marker_cmd", text="Căn cả chuỗi vào giữa thịt",
                     icon='PIVOT_MEDIAN').cmd = 'CENTER'
        col.operator("srp.marker_cmd", text="Trục gập theo chuỗi",
                     icon='ORIENTATION_GIMBAL').cmd = 'HINGE'
        tune.prop(settings, "roll_chain")
        row = tune.row(align=True)
        for step in (-15.0, -5.0, 5.0, 15.0):
            row.operator("srp.marker_roll", text="%+d°" % step).delta = step
        row = tune.row(align=True)
        row.operator("srp.marker_roll", text="-90°").delta = -90.0
        row.operator("srp.marker_roll", text="+90°").delta = 90.0
        row.operator("srp.marker_roll", text="Tự động").reset = True
        every_bone = [b for c in chains for b in c]
        shown = every_bone if settings.roll_chain \
            else [b for b in every_bone if b.name in bones_at(chosen)]
        col = tune.column(align=True)
        for item in shown:
            bone = item
            side, other = _pair_side(item.name)
            if settings.mirror and side == 'R' and other in ref.data.bones:
                bone = ref.data.bones[other]
            col.prop(bone, '["%s"]' % TAG_ROLL, text=bone.name)
        tune.prop(settings, "show_all_axes")

    big = layout.row(align=True)
    big.scale_y = 1.5
    big.operator("srp.marker_cmd", text="Xong", icon='CHECKMARK').cmd = 'DONE'
    big.operator("srp.marker_cmd", text="Tạm dừng", icon='PAUSE').cmd = 'PAUSE'


def register_extra():
    global _draw_view, _draw_text
    bpy.types.Scene.srp_marker = bpy.props.PointerProperty(type=SRP_MarkerSettings)
    _draw_view = bpy.types.SpaceView3D.draw_handler_add(_on_view, (), 'WINDOW', 'POST_VIEW')
    _draw_text = bpy.types.SpaceView3D.draw_handler_add(_on_text, (), 'WINDOW', 'POST_PIXEL')
    if _on_load not in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.append(_on_load)


def unregister_extra():
    global _draw_view, _draw_text
    _S.clear()
    _S["active"] = False
    if _on_load in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.remove(_on_load)
    for handle in (_draw_view, _draw_text):
        if handle is not None:
            bpy.types.SpaceView3D.draw_handler_remove(handle, 'WINDOW')
    _draw_view = _draw_text = None
    try:
        del bpy.types.Scene.srp_marker
    except AttributeError:
        pass


CLASSES = (SRP_MarkerSettings, SRP_OT_marker_start,
           SRP_OT_marker_cmd, SRP_OT_marker_mode, SRP_OT_marker_apply,
           SRP_OT_marker_roll, SRP_OT_marker_clear)
