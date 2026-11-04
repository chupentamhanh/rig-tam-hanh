"""Bone shape: sinh bang code, don sau khi append, day ra ngoai than.

Ba van de that voi custom shape, va cach giai:

1. **Append luon xo widget ra scene.** Da test `bpy.ops.wm.append` tren ca ba
   cau hinh — widget khong thuoc collection nao, widget trong collection, va
   append ca collection — CA BA deu bi link thang vao Scene Collection. Blender
   lam vay voi moi object duoc append, ke ca object chi di theo dang phu thuoc.
   Nen khong co cach to chuc file nguon nao ngan duoc. Loi giai la don SAU khi
   append, di thuan theo Blender thay vi chong lai.

2. **Widget nhan ban thanh X.001 moi lan append.** Gop lai duoc, nhung phai so
   hinh hoc truoc khi gop — trung ten khong co nghia la trung hinh.

3. **Shape chim trong mesh.** Thuong khong phai loi vi tri widget ma la
   `show_in_front` cua object armature dang tat. Doi mot thuoc tinh la xong,
   khong can dời widget.

Widget do addon sinh ra KHONG link vao collection nao: chi can `custom_shape`
tro toi la no du song, va nhu vay no khong hien trong Outliner, khong chon
nham duoc. Da test qua luu/mo lai.
"""

import math

import bpy
from mathutils import Euler, Vector
from mathutils.bvhtree import BVHTree

from . import rigdef

PREFIX = "WGT_"

# CANH BAO: `custom_shape_translation` la MET THO. No co `unit=NONE` nen trong
# giong "he so", va ghi chu o day tung viet nham la "theo chieu dai xuong" —
# tra gia bang mot lan ca bo widget ban tay bay ra xa nua met. CHI
# `custom_shape_scale_xyz` moi nhan voi chieu dai xuong (qua
# `use_custom_shape_bone_size`). Muon dich theo ty le xuong thi TU nhan
# `bone.length`.
OFFSET_MARGIN = 0.25       # theo chieu dai xuong, khoang ho them ngoai da
OFFSET_MAX = 4.0           # tran an toan, tranh widget bay ra xa tit
RAY_STEPS = 8              # so lan xuyen toi da khi tim mat thoat

FINGER_PREFIXES = ("Palm", "Index", "Middle", "Ring", "Pinky", "Thumb")

# Hinh DAI THEO THAN XUONG. `auto_fit` khong duoc dung toi chung.
#
# No phong DEU ca ba truc de vong tron trum ra ngoai da — dung voi vong tron,
# sai hoan toan voi thanh dai: be ngang thanh vai chi 0,14 don vi nen muon dat
# be day vai no phai nhan 5,53 lan, va cung phep nhan do keo CHIEU DAI thanh
# len 344 mm tren mot doan xuong 109 mm — thanh vai chay tit ra tan khuyu tay.
# Hai hinh nay von da vua khit doan xuong theo thiet ke, khong can boc gi them.
LENGTHWISE_SHAPES = (PREFIX + "Slab", PREFIX + "Bar")


def is_lengthwise(pose_bone):
    shape = pose_bone.custom_shape
    return shape is not None and shape.name in LENGTHWISE_SHAPES

# Khoang ho va tran, tinh bang MET — de deu mat giua xuong to va xuong nho.
# Truoc day dung don vi "chieu dai xuong" cho ca hai, thanh ra ngon tay duoc
# ho 5 mm con xuong song duoc ho 3,5 cm; nhin ra hai the gioi khac nhau.
MARGIN_M = 0.03
OFFSET_CAP_M = 0.20

# BANG QUY TAC — huong tinh trong khong gian RIG, khong phai khong gian xuong.
#
# Day la cho ban dau lam sai. Cho thuat toan tu chon "huong thoat khoi da som
# nhat" thi tung xuong ra mot huong rieng: ve mat so thi widget nao cung ra
# ngoai than that, nhung rig mat sach trat tu doc duoc — control lung bay len
# troi, control ngon vung vai quanh ban tay. Huong phai do NGUOI dinh theo
# nhom; raycast chi tra loi "ra bao xa thi het da".
#
# Nhan vat quay mat ve -Y (mui chan tro -Y), nen "ra truoc" = -Y.
OFFSET_RULES = (
    (("Spine", "Hips", "Hip_Master", "Ribs"), (0.0, -1.0, 0.0), False),
    (("Neck", "Head"), (0.0, -1.0, 0.0), False),
    (("Shoulder",), (0.0, 0.0, 1.0), False),
    (("Bicep", "Forearm", "Hand_Master"), (0.0, 0.0, 1.0), False),
    (("Thigh", "Shin", "Foot"), (1.0, 0.0, 0.0), True),      # doi chieu theo ben
)

# De yen: control von da o ngoai than, control phai nam dung tren bo phan cua
# no (ngon tay, mat), va control san.
SKIP_PREFIXES = FINGER_PREFIXES + (
    "Toe", "ArmIK", "LegIK", "Pole", "ElbowPole", "Root", "Breast",
    "Eye", "Jaw", "Upper", "Lower", "Teeth", "Tongue", "Nose", "Cheek", "Mouth",
)


def _rule_for(bone_name):
    """(huong trong khong gian rig) cho mot xuong, None neu de yen."""
    if any(bone_name.startswith(prefix) for prefix in SKIP_PREFIXES):
        return None
    for prefixes, direction, mirrored in OFFSET_RULES:
        if any(bone_name.startswith(prefix) for prefix in prefixes):
            vector = Vector(direction)
            if mirrored and bone_name.endswith(".R"):
                vector = Vector((-direction[0], -direction[1], -direction[2]))
            return vector.normalized()
    return None


# ------------------------------------------------------- thu vien hinh

def _circle(segments=24, radius=1.0, axis='Z'):
    verts = []
    for i in range(segments):
        angle = 2.0 * math.pi * i / segments
        x, y = math.cos(angle) * radius, math.sin(angle) * radius
        verts.append({'Z': (x, y, 0.0), 'Y': (x, 0.0, y), 'X': (0.0, x, y)}[axis])
    edges = [(i, (i + 1) % segments) for i in range(segments)]
    return verts, edges


def _combine(*parts):
    verts, edges = [], []
    for part_verts, part_edges in parts:
        offset = len(verts)
        verts.extend(part_verts)
        edges.extend((a + offset, b + offset) for a, b in part_edges)
    return verts, edges


def _cube(size=1.0):
    s = size
    verts = [(-s, -s, -s), (s, -s, -s), (s, s, -s), (-s, s, -s),
             (-s, -s, s), (s, -s, s), (s, s, s), (-s, s, s)]
    edges = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4),
             (0, 4), (1, 5), (2, 6), (3, 7)]
    return verts, edges


def _diamond(size=1.0):
    s = size
    verts = [(0, s, 0), (0, -s, 0), (s, 0, 0), (-s, 0, 0), (0, 0, s), (0, 0, -s)]
    edges = [(0, 2), (0, 3), (0, 4), (0, 5), (1, 2), (1, 3), (1, 4), (1, 5),
             (2, 4), (4, 3), (3, 5), (5, 2)]
    return verts, edges


def _square(size=1.0):
    s = size
    return [(-s, 0, -s), (s, 0, -s), (s, 0, s), (-s, 0, s)], [(0, 1), (1, 2), (2, 3), (3, 0)]


def _arrow(size=1.0):
    s = size
    verts = [(0, 0, 0), (0, s * 2, 0), (-s * 0.6, s * 1.4, 0), (s * 0.6, s * 1.4, 0)]
    return verts, [(0, 1), (1, 2), (1, 3)]


def _slab(width=0.08, lo=0.05, hi=0.95, seg=6):
    """Thanh det CHAY DOC than xuong, nam trong mat phang XY.

    Khac moi hinh khac trong thu vien: chung deu la vong/khoi doi xung quanh
    GOC xuong, con cai nay trai dai tu `lo` toi `hi` theo truc Y — tuc theo
    dung doan xuong, vi `use_custom_shape_bone_size` nhan toa do voi chieu dai
    xuong. Mat phang XY nghia la phap tuyen trung truc Z cuc bo, va voi xuong
    ban tay thi truc Z chinh la huong LUNG BAN TAY (do duoc: (0.05, 0.02, 1.0)
    trong he the gioi).
    """
    r = width
    y0, y1 = lo + r, hi - r
    verts = []
    for i in range(seg + 1):
        a = math.pi * i / seg
        verts.append((math.cos(a) * r, y1 + math.sin(a) * r, 0.0))
    for i in range(seg + 1):
        a = math.pi + math.pi * i / seg
        verts.append((math.cos(a) * r, y0 + math.sin(a) * r, 0.0))
    return verts, [(i, (i + 1) % len(verts)) for i in range(len(verts))]


def _bar(width=0.14, lo=0.45, hi=1.02, seg=6):
    """Thanh det chi phu NUA NGOAI doan xuong.

    Dung cho xuong doi (vai): nua TRONG cua no nam canh co, day widget len o do
    thi phai len toi 373 mm moi ra khoi thit (do duoc), trong khi o 75-100%
    doan xuong — tuc mom vai — chi can 33-39 mm. Nen bo han nua trong di.
    """
    return _slab(width=width, lo=lo, hi=hi, seg=seg)


def _horseshoe(width=0.62, back=0.30, front=1.05, seg=9):
    """Chu U nam ngang OM THEO DUONG QUAI HAM.

    Hai dau ho vuon ve phia TAI (goc xuong ham, tuc ban le), day cong om lay
    CAM (duoi xuong). Nam trong mat phang XY, ma voi xuong ham thi truc Z cuc
    bo chinh la phuong THANG DUNG (do duoc: (0.00, 0.06, -1.00) trong he the
    gioi) — nen mat phang XY la mat phang ngang, dung nhu can.

    Hai canh dung lai o 30% doan xuong chu khong keo toi tan ban le: ban le nam
    SAU trong dau (gan tai), nen keo den do la hai dau ho cam thang vao so —
    do duoc 12/12 dinh nam trong thit, va noi rong bao nhieu cung khong cuu
    duoc vi hai dau do khong dich sang ngang.

    Ca hinh duoc ha xuong DUOI duong ham bang `custom_shape_translation` trong
    `FACE_WIDGETS`, nen no vay quanh quai ham tu ben duoi — dung nhu goc nhin
    tu duoi len ma anh Art ve ra.
    """
    r = width
    y_arc = front - r
    verts = [(-r, back, 0.0)]
    for i in range(seg + 1):
        a = math.pi - math.pi * i / seg
        verts.append((math.cos(a) * r, y_arc + math.sin(a) * r, 0.0))
    verts.append((r, back, 0.0))
    return verts, [(i, i + 1) for i in range(len(verts) - 1)]


def _arch(segments=11, radius=1.0):
    """Nua cung tron mo XUONG — hinh quen thuoc cho control ham.

    Mo xuong (nua duoi) chu khong phai nua tren: keo no xuong la ha ham, nen
    huong cua hinh trung voi huong dieu khien.
    """
    verts = []
    for i in range(segments):
        angle = math.pi * i / (segments - 1)
        verts.append((math.cos(angle) * radius, 0.0, -math.sin(angle) * radius))
    return verts, [(i, i + 1) for i in range(segments - 1)]


# TRUC Y CHAY DOC THAN XUONG trong khong gian custom shape. Nen vong tron "om
# quanh xuong" phai nam trong mat phang XZ, tuc `_circle(axis='Y')`.
#
# Truoc day CIRCLE va RING dung `axis='Z'` (mat phang XY) — mat phang do CHUA
# truc xuong, nen moi vong tron than nguoi va tay chan deu dung dung doc theo
# xuong thay vi om quanh no. Do duoc: 17 trong 28 widget mau bi sai phuong.
# `_square` va `_arch` von da dung XZ nen chung khong bao gio bi.
SHAPES = {
    'ARCH': _arch,
    'SLAB': _slab,
    'HORSESHOE': _horseshoe,
    'BAR': _bar,
    'CIRCLE': lambda: _circle(24, axis='Y'),
    'SPHERE': lambda: _combine(_circle(16, axis='Z'), _circle(16, axis='Y'), _circle(16, axis='X')),
    'CUBE': _cube,
    'SQUARE': _square,
    'DIAMOND': _diamond,
    'ARROW': _arrow,
    'RING': lambda: _combine(_circle(24, 1.0, axis='Y'), _circle(24, 0.75, axis='Y')),
}


# Xuong mat can ca PHEP BIEN HINH cua widget chu khong chi ten hinh: hinh phai
# om lay bo phan no dieu khien (vong quanh nhan cau, cung om duoi cam) chu khong
# nam o goc xuong. Bon so nay lay dung theo cai anh Art tu chinh tay tren
# `3.0_Rig`: (hinh, ty le, tinh tien, xoay).
# Hai xuong mat khong con phai xoay bu: vong tron gio von da nam trong mat
# phang XZ. Truoc day `(pi/2, 0, 0)` chinh la phep xoay bu cho cai vong tron
# dat sai mat phang — sua goc roi thi giu no lai la xoay sai lan thu hai.
#
# TINH TIEN o day la TY LE THEO CHIEU DAI XUONG, khong phai met. Bang nay von
# chep nguyen so met ma anh Art chinh tay tren `3.0_Rig`, va so met thi khong
# chuyen duoc sang nhan vat khac: xuong ham cua `3.0_Rig` dai 160,5 mm nen
# 130 mm la 0,81 lan chieu dai, nhung tren mot rig co xuong ham 94,8 mm thi
# dung 130 mm do thanh 1,37 lan — cung ham bay ra truoc mat, trung binh cach
# da 34,6 mm va cho xa nhat 72,7 mm. `apply_face_widget()` nhan lai voi
# `bone.length`.
FACE_WIDGETS = {
    "Jaw": ('HORSESHOE', 1.00, (0.0, 0.0, 0.30), (0.0, 0.0, 0.0)),
    "Eye.L": ('CIRCLE', 0.30, (0.0, 1.159, 0.0), (0.0, 0.0, 0.0)),
    "Eye.R": ('CIRCLE', 0.30, (0.0, 1.159, 0.0), (0.0, 0.0, 0.0)),
}


def _face_key(name):
    """`Eye_2.L` -> `Eye.L`. Bo so thu tu chi de tra bang quy tac."""
    stem, dot, side = name.rpartition(".")
    if not dot:
        stem, side = name, ""
    base = stem.rsplit("_", 1)
    if len(base) == 2 and base[1].isdigit():
        stem = base[0]
    return stem + dot + side


def apply_face_widget(pose_bone, overwrite=True):
    """Gan hinh cho mot xuong mat. Tra ve True neu co gan.

    `overwrite=False` de KHONG de len hinh nguoi ta da tu chinh: tren rig co
    san, anh Art da chon hinh va chinh phep bien hinh bang tay roi.
    """
    # `Eye_2.L` cua nhan vat bon mat phai dung chung hinh voi `Eye.L`: bo so
    # thu tu di roi tra lai. Khong bo thi cap mat thu hai khong co widget nao
    # va animator khong bam vao dau de chon.
    spec = FACE_WIDGETS.get(pose_bone.name) or FACE_WIDGETS.get(
        _face_key(pose_bone.name))
    if spec is None or (pose_bone.custom_shape is not None and not overwrite):
        return False
    kind, scale, translate, rotate = spec
    pose_bone.custom_shape = build_widget(kind)
    pose_bone.use_custom_shape_bone_size = True
    pose_bone.custom_shape_scale_xyz = (scale, scale, scale)
    length = pose_bone.bone.length or 1.0
    pose_bone.custom_shape_translation = [v * length for v in translate]
    pose_bone.custom_shape_rotation_euler = rotate
    pose_bone.bone.show_wire = True
    return True


def _matches(mesh, verts):
    """Mesh hien co dung la hinh dang duoc dinh nghia bay gio khong."""
    if mesh is None or len(mesh.vertices) != len(verts):
        return False
    for existing, wanted in zip(mesh.vertices, verts):
        if (existing.co - Vector(wanted)).length > 1e-5:
            return False
    return True


def build_widget(kind):
    """Tao (hoac tra ve) object widget cho mot hinh. KHONG link vao dau ca.

    Object da co ma hinh hoc KHONG khop ban dinh nghia hien tai thi dung lai —
    khong thi file lam tu ban addon cu giu mai cai hinh sai (vong tron dat sai
    mat phang chang han) va khong nut nao chua duoc, vi ham nay tra ve theo TEN.
    Chi chay khi nguoi dung bam nut gan hinh, khong dong gi luc mo file.
    """
    name = PREFIX + kind.title()
    verts, edges = SHAPES[kind]()
    existing = bpy.data.objects.get(name)
    if existing is not None and existing.type == 'MESH':
        if _matches(existing.data, verts):
            return existing
        existing.data.clear_geometry()
        existing.data.from_pydata(verts, edges, [])
        existing.data.update()
        return existing
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, edges, [])
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    obj.hide_render = True
    return obj                      # khong link — custom_shape giu no song


# ---------------------------------------------------------- tim widget

def widget_objects(rigs=None):
    """Moi object dang duoc dung lam custom shape."""
    found = {}
    sources = rigs if rigs is not None else [o for o in bpy.data.objects if o.type == 'ARMATURE']
    for rig in sources:
        for bone in rig.pose.bones:
            if bone.custom_shape is not None:
                found[bone.custom_shape.name] = bone.custom_shape
    return list(found.values())


def _canonical_name(name):
    """'Circle.001' -> 'Circle'."""
    if len(name) > 4 and name[-4] == '.' and name[-3:].isdigit():
        return name[:-4]
    return name


def _same_geometry(a, b):
    """So tung dinh — trung ten khong dam bao trung hinh."""
    if a.data is None or b.data is None:
        return False
    va, vb = a.data.vertices, b.data.vertices
    if len(va) != len(vb) or len(a.data.edges) != len(b.data.edges):
        return False
    for pa, pb in zip(va, vb):
        if (pa.co - pb.co).length > 1e-5:
            return False
    return tuple(a.scale) == tuple(b.scale) and tuple(a.location) == tuple(b.location)


# ------------------------------------------------------------- thao tac

def dedupe(rigs):
    """Gop widget trung: doi trỏ moi bone ve ban goc roi xoa ban sao."""
    groups = {}
    for obj in widget_objects(rigs):
        groups.setdefault(_canonical_name(obj.name), []).append(obj)

    remapped, removed, kept_apart = 0, [], 0
    for base, objs in groups.items():
        if len(objs) < 2:
            continue
        objs.sort(key=lambda o: len(o.name))      # ten ngan nhat lam ban goc
        master = objs[0]
        for other in objs[1:]:
            if not _same_geometry(master, other):
                kept_apart += 1                   # khac hinh that -> khong dam gop
                continue
            for rig in rigs:
                for bone in rig.pose.bones:
                    if bone.custom_shape == other:
                        bone.custom_shape = master
                        remapped += 1
            removed.append(other)

    for obj in removed:
        mesh = obj.data
        bpy.data.objects.remove(obj)
        if mesh is not None and mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    return remapped, len(removed), kept_apart


def widget_collections(rigs):
    """Collection dang chua widget — de biet cai nao duoc phep dong vao."""
    found = {}
    for obj in widget_objects(rigs):
        for col in obj.users_collection:
            found[col.name] = col
    return list(found.values())


def orphan_duplicates(rigs):
    """Ban sao widget khong bone nao dung.

    Nhan dien bang TRUNG HINH HOC voi mot widget dang duoc dung, khong bang
    chuyen no nam o dau — vi sau lan don dau tien thi widget da ra khoi
    collection, khong con manh moi vi tri de lan theo nua.

    Khong duoc quet theo kieu "mesh khong ai dung": file nay co hang tram
    mesh quan ao va dao cu cung o trang thai do, quet bua la xoa nham tai san.
    Phep so trung tung dinh du chat de khong cham vao chung.
    """
    in_use = widget_objects(rigs)
    used = {o.name for o in in_use}
    out = []
    for obj in bpy.data.objects:
        if obj.type != 'MESH' or obj.name in used or obj.data is None:
            continue
        if any(_same_geometry(obj, other) for other in in_use):
            out.append(obj)
    return out


def unlink_from_collections(rigs, collections):
    """Go widget khoi collection. Chung song nho custom_shape tro toi.

    Chi dong nhung collection DA TUNG chua widget — khong duoc quet ca file
    tim collection rong, vi nhu vay se xoa ca collection to chuc cua nguoi ta.
    """
    touched = 0
    for obj in widget_objects(rigs):
        cols = list(obj.users_collection)
        if not cols:
            continue
        for col in cols:
            col.objects.unlink(obj)
        touched += 1
    purged = 0
    for col in collections:
        try:
            if not col.objects and not col.children:
                bpy.data.collections.remove(col)
                purged += 1
        except ReferenceError:
            pass
    return touched, purged


def set_display(rig, in_front=True, wire=True):
    """Cho control noi len tren mesh — day thuong la thu that su can."""
    rig.show_in_front = in_front
    count = 0
    for bone in rig.pose.bones:
        if bone.custom_shape is not None and bone.bone.show_wire != wire:
            bone.bone.show_wire = wire
            count += 1
    return count


# ------------------------------------------------------ day ra ngoai da

def _bone_bounds(rig):
    """Hop bao cua xuong, trong khong gian rig."""
    points = [bone.matrix_local.translation for bone in rig.data.bones]
    points += [bone.tail_local for bone in rig.data.bones]
    if not points:
        return None
    return (Vector((min(p.x for p in points), min(p.y for p in points), min(p.z for p in points))),
            Vector((max(p.x for p in points), max(p.y for p in points), max(p.z for p in points))))


def body_meshes(rig, margin=0.5):
    """Mesh THUC SU dang o tren nguoi, khong phai ca thu vien skin vao rig.

    File nay day mot bai hoc: `Simplified_Female` co 39 mesh skin vao, nhung
    37 cai nam cach nhan vat ~105 met — do la gia treo quan ao, chi vao dung
    cho khi duoc chon mac. Gop tat ca lai lam BVH thi ra mot khoi hinh o tan
    dau dau, tia ban ra khong trung gi, va ham im lang tra ve "khong lam gi".
    Nen phai loc theo VI TRI THAT chu khong theo "co skin vao rig hay khong".
    """
    bounds = _bone_bounds(rig)
    if bounds is None:
        return []
    low, high = bounds[0] - Vector((margin,) * 3), bounds[1] + Vector((margin,) * 3)
    to_rig = rig.matrix_world.inverted()
    out = []
    for obj in bpy.data.objects:
        if obj.type != 'MESH' or obj.hide_viewport:
            continue
        if not any(m.type == 'ARMATURE' and m.object == rig for m in obj.modifiers):
            continue
        corners = [to_rig @ obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
        if any(low.x <= c.x <= high.x and low.y <= c.y <= high.y and low.z <= c.z <= high.z
               for c in corners):
            out.append(obj)
    return out


def fit_meshes(context, rig, meshes=None):
    """Mesh dung lam thuoc do cho moi phep boc/day/don widget.

    Ba nac, theo thu tu:
      1. `meshes` truyen thang — de goi rieng le van chu dong duoc.
      2. Mesh DA SKIN vao rig (`body_meshes`) — sau khi bind thi day la thuoc
         do dung nhat: no gom ca quan ao, ma widget thi phai boc ra ngoai quan
         ao chu khong phai ngoai da tran.
      3. `target_mesh` — CHINH LA MESH NGUOI DUNG CHON O BUOC 1.

    Nac 3 la cho truoc day con thieu, va no thieu dung luc can nhat: vua dung
    rig xong thi chua bind, `body_meshes()` tra ve rong, nen `srp.widget_fit`
    va `srp.widget_offset` bao "khong co mesh nao nam dung cho nhan vat" — dung
    khi nguoi dung vua chon mesh do o buoc 1 va no dang nam ngay day.
    """
    if meshes:
        return [m for m in meshes if m is not None]
    found = body_meshes(rig)
    if found:
        return found
    settings = getattr(context.scene, "srp_generate", None)
    target = getattr(settings, "target_mesh", None) if settings else None
    return [target] if target is not None else []


def _character_bvh(context, rig, meshes=None):
    """BVH gop cac mesh dang o tren nguoi, o toa do cua rig."""
    depsgraph = context.evaluated_depsgraph_get()
    verts, faces = [], []
    to_rig = rig.matrix_world.inverted()
    for obj in fit_meshes(context, rig, meshes):
        mesh = obj.evaluated_get(depsgraph).to_mesh()
        if mesh is None:
            continue
        matrix = to_rig @ obj.matrix_world
        base = len(verts)
        verts.extend((matrix @ v.co).to_tuple() for v in mesh.vertices)
        for poly in mesh.polygons:
            idx = [i + base for i in poly.vertices]
            for k in range(1, len(idx) - 1):
                faces.append((idx[0], idx[k], idx[k + 1]))
        obj.evaluated_get(depsgraph).to_mesh_clear()
    if not faces:
        return None
    return BVHTree.FromPolygons(verts, faces)


def _exit_distance(bvh, origin, direction, limit):
    """Khoang cach tu `origin` di theo `direction` cho toi khi ra khoi than.

    Ban xuyen nhieu lan: BVH tra ve va cham DAU TIEN, ma tu trong nguoi ban ra
    thi cham dau tien da la mat da roi — nhung voi quan ao nhieu lop thi con
    nhieu lop nua. Lay lan cham CUOI CUNG moi dung la mat ngoai cung.
    """
    total, last = 0.0, None
    point = origin.copy()
    for _ in range(RAY_STEPS):
        hit, _normal, _index, distance = bvh.ray_cast(point, direction, limit - total)
        if hit is None:
            break
        total += distance + 1e-4
        last = total
        point = origin + direction * total
    return last


def auto_offset(context, rig, only_missing=True, margin=MARGIN_M, bones=None,
                meshes=None):
    """Day widget ra ngoai than bang `custom_shape_translation`.

    KHONG dời xuong — chi dời hinh ve. Rig van giai y nguyen, action van chay
    y nguyen; chi khac cho animator bam vao.
    """
    bvh = _character_bvh(context, rig, meshes)
    if bvh is None:
        skinned = sum(1 for o in bpy.data.objects if o.type == 'MESH'
                      and any(m.type == 'ARMATURE' and m.object == rig for m in o.modifiers))
        return None, ("không có mesh nào nằm đúng chỗ nhân vật (%d mesh có skin "
                      "vào rig nhưng đều ở xa — thư viện quần áo chứ không phải "
                      "thân)" % skinned)

    moved, skipped, attempted = 0, 0, 0
    planned = []
    for pose_bone in rig.pose.bones:
        if pose_bone.custom_shape is None:
            continue
        if bones is not None and pose_bone.name not in bones:
            continue
        direction = _rule_for(pose_bone.name)
        if direction is None:
            continue                          # bang quy tac cho de yen
        if only_missing and tuple(pose_bone.custom_shape_translation) != (0.0, 0.0, 0.0):
            skipped += 1
            continue

        bone = pose_bone.bone
        length = bone.length
        if length < 1e-6:
            continue
        attempted += 1
        rest = bone.matrix_local              # rest pose, trong khong gian rig
        center = rest.translation + rest.col[1].to_3d().normalized() * (length * 0.5)

        distance = _exit_distance(bvh, center, direction, OFFSET_CAP_M)
        if distance is None:
            continue                          # von da o ngoai than, khong can day

        amount_m = min(distance + margin, OFFSET_CAP_M)
        local = (rest.to_3x3().inverted() @ direction).normalized()
        # MET THO, khong chia cho do dai xuong — xem CANH BAO dau file. Chia
        # thi xuong 10 cm bi day 5 cm thanh 50 cm.
        planned.append((pose_bone, local * amount_m))
        moved += 1

    # BVH khong rong khong co nghia la co than nguoi: `Simplified_Female` chi
    # con hai chiec dep dung cho, du de BVH ton tai nhung tia gan nhu khong
    # trung gi — lan dau chay no lang le doi dung 1 bone roi bao "xong".
    # Nen gom lai va chi GHI khi ty le trung du cao; thap qua thi bo het,
    # bao ra, khong de lai mot nua ket qua rac.
    if attempted and moved / attempted < 0.5:
        return None, ("chỉ đo được %d/%d bone nên bỏ qua — mesh đúng chỗ nhân "
                      "vật không đủ (chỉ có %d mesh ở đúng chỗ)"
                      % (moved, attempted, len(body_meshes(rig))))
    for pose_bone, value in planned:
        pose_bone.custom_shape_translation = value
    return (moved, skipped), None


# -------------------------------------------------- boc widget ra ngoai

RADIAL_SAMPLES = 12
FIT_MARGIN_M = 0.02


def widget_radius(pose_bone):
    """Ban kinh widget trong mat phang vuong goc truc xuong, don vi goc.

    Tinh ca transform cua chinh object widget — Blender co ap matrix cua no.
    """
    shape = pose_bone.custom_shape
    if shape is None or shape.data is None or not len(shape.data.vertices):
        return None
    scale = shape.scale
    return max(math.hypot(v.co.x * scale.x, v.co.z * scale.z)
               for v in shape.data.vertices)


SHELL_GAP_M = 0.03


def _shell_exit(bvh, origin, direction, limit, gap=SHELL_GAP_M):
    """Khoang cach ra khoi LOP VO LIEN MACH quanh `origin`.

    Khac `_exit_distance`: cai kia di xuyen het moi thu trong tam ban, dung de
    day widget ra ngoai. O day dang do BE NGANG cua mot bo phan, nen gap
    khoang trong lon la phai dung — neu khong, tia bat tu xuong vai chay doc
    suot than nguoi roi moi thoat, va bao ban kinh vai la 52 cm.
    """
    total, last = 0.0, None
    point = origin.copy()
    for _ in range(RAY_STEPS):
        hit, _normal, _index, distance = bvh.ray_cast(point, direction, limit - total)
        if hit is None:
            break
        if last is not None and distance > gap:
            break                       # da sang bo phan khac cua co the
        total += distance + 1e-4
        last = total
        point = origin + direction * total
    return last


def body_radius(bvh, bone, samples=RADIAL_SAMPLES, limit=0.6):
    """Ban kinh lop vo quanh mot xuong, lay TRUNG VI cua cac tia toa tron.

    Lay max thi hong: voi xuong nam ngang nhu vai, hai tia doc than van chay
    suot nguoi (than va vai lien mach nen `_shell_exit` khong cat), va ban
    kinh vai bao thanh 23 cm thay vi 9 cm. Trung vi bo qua vai tia lac loai
    ma van bam sat be ngang thuc.
    """
    rest = bone.matrix_local
    center = rest.translation + rest.col[1].to_3d().normalized() * (bone.length * 0.5)
    basis = rest.to_3x3()
    found = []
    for index in range(samples):
        angle = 2.0 * math.pi * index / samples
        local = Vector((math.cos(angle), 0.0, math.sin(angle)))
        distance = _shell_exit(bvh, center, (basis @ local).normalized(), limit)
        if distance is not None:
            found.append(distance)
    if not found:
        return None
    found.sort()
    middle = len(found) // 2
    if len(found) % 2:
        return found[middle]
    return (found[middle - 1] + found[middle]) * 0.5


def auto_fit(context, rig, margin=FIT_MARGIN_M, only_grow=True, bones=None,
             meshes=None):
    """Phong widget cho BOC NGOAI than, khong dời no di dau ca.

    Day moi la thu can. Ban truoc dem widget dich ra khoi than bang
    `custom_shape_translation` — control roi han khoi nhan vat, nhin nhu bi
    van ra ngoai. Cai dung la giu nguyen tam va tang `custom_shape_scale_xyz`
    cho toi khi vong tron trum qua da.

    Phong deu ca ba truc de khong meo hinh, va mac dinh CHI PHONG TO: widget
    nao da trum roi thi de yen, khong thu nho lai cho "vua khit".
    """
    bvh = _character_bvh(context, rig, meshes)
    if bvh is None:
        skinned = sum(1 for o in bpy.data.objects if o.type == 'MESH'
                      and any(m.type == 'ARMATURE' and m.object == rig for m in o.modifiers))
        return None, ("không có mesh nào để đo: chưa bind, và cũng chưa chọn "
                      "'Mesh nhân vật' ở bước 1 (%d mesh có skin nhưng đều ở "
                      "xa)"
                      % skinned)

    planned, attempted, measured = [], 0, 0
    for pose_bone in rig.pose.bones:
        if pose_bone.custom_shape is None:
            continue
        if bones is not None and pose_bone.name not in bones:
            continue
        if _rule_for(pose_bone.name) is None or is_lengthwise(pose_bone):
            continue                       # ngon tay, control IK, xuong mat: de yen
        if is_lengthwise(pose_bone):
            continue                       # thanh dai: phong la keo dai theo
        bone = pose_bone.bone
        radius = widget_radius(pose_bone)
        if radius is None or radius < 1e-6 or bone.length < 1e-6:
            continue
        attempted += 1

        flesh = body_radius(bvh, bone)
        if flesh is None:
            continue                       # xuong nam ngoai than, khong can boc
        measured += 1

        current = max(abs(v) for v in pose_bone.custom_shape_scale_xyz) or 1.0
        drawn = radius * bone.length * current
        needed = flesh + margin
        if only_grow and drawn >= needed:
            continue
        factor = needed / drawn
        planned.append((pose_bone, factor,
                        drawn * 100.0, needed * 100.0))

    if attempted and measured / attempted < 0.5:
        return None, ("chỉ đo được %d/%d xương nên bỏ qua — mesh đúng chỗ nhân "
                      "vật không đủ" % (measured, attempted))
    for pose_bone, factor, _before, _after in planned:
        pose_bone.custom_shape_scale_xyz = [v * factor for v in pose_bone.custom_shape_scale_xyz]
    return (len(planned), attempted - len(planned)), None


# ------------------------------------------- don widget ra khoi trong thit
#
# Ba nhom control nam ngay tren truc xuong ma truc xuong thi chay TRONG nguoi,
# nen hinh cua chung mac dinh chim han trong thit. Do duoc tren `My_Body`:
# vai 13/24 dinh nam trong, sau nhat 47,5 mm; ham 4/11 dinh, sau 12,8 mm.
#
# Khong doan khoang day nua — thu tung nac roi DO xem con dinh nao nam trong
# khong. Hai cach don, vi hai kieu hong khac nhau:
#
#   PUSH — day ca hinh ra theo mot truc cuc bo. Dung cho vai va ban tay: chung
#          co mot huong "ra ngoai" ro rang (lung ban tay, mom vai).
#   GROW — phong to tai cho. Dung cho ham: cung ham phai OM LAY cam, day no
#          ra thi no roi khoi cai no dieu khien. Do duoc: day xuong cho het
#          cham thit phai toi 150 mm, tuc treo lo lung duoi co.
CLEAR_RULES = (
    ("Palm", 'PUSH', (0.0, 0.0, 1.0)),
    ("Shoulder", 'PUSH', (0.0, 0.0, 1.0)),
    ("Jaw", 'WIDEN', None),
)


# Sau huong thu khi don kieu FREE: cung ham nam giua dau nen khong co huong
# "ra ngoai" hien nhien. Da thu phong to truoc — vo ich, vi phep phong giu
# nguyen tam nen hai dau cung cang cam sau vao ma.
FREE_AXES = ((0.0, 0.0, 1.0), (0.0, 0.0, -1.0), (1.0, 0.0, 0.0),
             (-1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, -1.0, 0.0))

CLEAR_MARGIN_M = 0.008      # ho them sau khi vua sach, tinh bang met
CLEAR_PUSH_CAP = 1.20       # tran, theo chieu dai xuong
CLEAR_GROW_CAP = 3.00       # tran he so phong to
CLEAR_STEPS = 16


def _clear_rule(name):
    base = name.split(".")[0].rstrip("0123456789_")
    for prefix, how, axis in CLEAR_RULES:
        if base == prefix:
            return how, axis
    return None, None


def drawn_points(rig, pose_bone, extra_push=0.0, axis=None, extra_scale=1.0):
    """Toa do cua tung dinh widget trong khong gian RIG, dung nhu Blender ve ra.

    Khong gian RIG chu khong phai the gioi: `_character_bvh` dung BVH o toa do
    rig, tron hai he la rig nao bi dời/xoay khoi goc cung do sai trong/ngoai.

    Phai dung dung thu tu Blender ghep ma tran (ty le -> xoay -> tinh tien),
    khong thi phep do noi doi mot cach rat thuyet phuc.

    `extra_scale` nhan mot so (deu ba truc) hoac bo ba (rieng tung truc).
    """
    shape = pose_bone.custom_shape
    if shape is None or shape.data is None or not len(shape.data.vertices):
        return []
    length = pose_bone.bone.length if pose_bone.use_custom_shape_bone_size else 1.0
    grow = (Vector((extra_scale,) * 3) if isinstance(extra_scale, (int, float))
            else Vector(extra_scale))
    base = Vector(pose_bone.custom_shape_scale_xyz) * length
    scale = Vector((base.x * grow.x, base.y * grow.y, base.z * grow.z))
    turn = Euler(pose_bone.custom_shape_rotation_euler, 'XYZ').to_matrix()
    move = Vector(pose_bone.custom_shape_translation)
    if axis is not None and extra_push:
        move = move + Vector(axis).normalized() * extra_push
    matrix = pose_bone.bone.matrix_local
    basis = matrix.to_3x3()
    head = matrix.translation
    return [head + basis @ (move + turn @ Vector((v.co.x * scale.x,
                                                  v.co.y * scale.y,
                                                  v.co.z * scale.z)))
            for v in shape.data.vertices]


def _inside_count(bvh, points):
    """So dinh nam TRONG thit — do bang phap tuyen mat gan nhat."""
    n = 0
    for point in points:
        location, normal, _index, _distance = bvh.find_nearest(point)
        if location is None:
            continue
        if (point - Vector(location)).dot(Vector(normal)) < 0.0:
            n += 1
    return n


def clear_widgets(context, rig, meshes=None, margin=CLEAR_MARGIN_M):
    """Don cac widget dang chim trong thit. Tra ve (so cai sua, so cai chiu thua)."""
    bvh = _character_bvh(context, rig, meshes)
    if bvh is None:
        return 0, 0
    fixed, stuck = 0, 0
    for pose_bone in rig.pose.bones:
        if pose_bone.custom_shape is None:
            continue
        how, axis = _clear_rule(pose_bone.name)
        if how is None:
            continue
        length = pose_bone.bone.length
        if length < 1e-6:
            continue
        if not _inside_count(bvh, drawn_points(rig, pose_bone)):
            continue                       # von da sach
        if how == 'WIDEN':
            done = False
            for step in range(1, CLEAR_STEPS + 1):
                wide = 1.0 + (CLEAR_GROW_CAP - 1.0) * step / float(CLEAR_STEPS)
                if _inside_count(bvh, drawn_points(rig, pose_bone,
                                                   extra_scale=(wide, 1.0, 1.0))):
                    continue
                sx, sy, sz = pose_bone.custom_shape_scale_xyz
                pose_bone.custom_shape_scale_xyz = (sx * wide, sy, sz)
                fixed += 1
                done = True
                break
            if not done:
                stuck += 1
            continue

        best = None
        axes = [axis] if how == 'PUSH' else (
            FREE_AXES if how == 'FREE' else [None])
        for try_axis in axes:
            for step in range(1, CLEAR_STEPS + 1):
                f = step / float(CLEAR_STEPS)
                if try_axis is None:
                    amount = 1.0 + (CLEAR_GROW_CAP - 1.0) * f
                    points = drawn_points(rig, pose_bone, extra_scale=amount)
                else:
                    amount = length * CLEAR_PUSH_CAP * f
                    points = drawn_points(rig, pose_bone, amount, try_axis)
                if _inside_count(bvh, points):
                    continue
                # Giu phuong an RE NHAT: day cang ngan thi control cang nam
                # dung tren bo phan no dieu khien.
                if best is None or amount < best[1]:
                    best = (try_axis, amount)
                break
        if best is None:
            stuck += 1
            continue
        try_axis, amount = best
        if try_axis is None:
            pose_bone.custom_shape_scale_xyz = [
                v * amount for v in pose_bone.custom_shape_scale_xyz]
        else:
            extra = Vector(try_axis).normalized() * (amount + margin)
            pose_bone.custom_shape_translation = (
                Vector(pose_bone.custom_shape_translation) + extra)
        fixed += 1

    return fixed, stuck


# ---------------------------------------------------------- operators

def _rigs(context, scope):
    if scope == 'ALL':
        return rigdef.managed_rigs(context)
    rig = rigdef.active_rig(context)
    return [rig] if rig else []


class SRP_OT_widget_cleanup(bpy.types.Operator):
    """Gộp widget trùng lặp, gỡ chúng khỏi mọi collection, xoá collection rỗng.

    Chạy sau mỗi lần append — Blender luôn xổ widget ra Scene Collection.
    """
    bl_idname = "srp.widget_cleanup"
    bl_label = "Dọn widget"
    bl_options = {'REGISTER', 'UNDO'}

    unlink: bpy.props.BoolProperty(
        name="Gỡ khỏi collection", default=True,
        description="Widget vẫn sống nhờ custom_shape trỏ tới, và biến khỏi "
                    "Outliner")
    remove_orphans: bpy.props.BoolProperty(
        name="Xoá bản sao không ai dùng", default=True,
        description="Chỉ xoá mesh nằm trong collection widget VÀ trùng hình với "
                    "một widget đang được dùng")

    @classmethod
    def poll(cls, context):
        return bool(rigdef.managed_rigs(context))

    def execute(self, context):
        rigs = [o for o in bpy.data.objects if o.type == 'ARMATURE']
        before = len(widget_objects(rigs))
        collections = widget_collections(rigs)      # phai lay TRUOC khi go
        remapped, removed, kept = dedupe(rigs)

        orphans = []
        if self.remove_orphans:
            for obj in orphan_duplicates(rigs):
                orphans.append(obj.name)
                # collection cua ban sao cung duoc phep dong neu rong theo
                collections.extend(c for c in obj.users_collection if c not in collections)
                mesh = obj.data
                bpy.data.objects.remove(obj)
                if mesh is not None and mesh.users == 0:
                    bpy.data.meshes.remove(mesh)

        unlinked = purged = 0
        if self.unlink:
            unlinked, purged = unlink_from_collections(rigs, collections)
        after = len(widget_objects(rigs))

        message = ("widget %d -> %d | doi tro %d bone, xoa %d ban sao"
                   % (before, after, remapped, removed))
        if orphans:
            message += " | xoa %d ban sao mo coi (%s)" % (len(orphans), ", ".join(orphans[:3]))
        if self.unlink:
            message += " | go %d khoi collection, xoa %d collection" % (unlinked, purged)
        if kept:
            message += " | GIU RIENG %d cai vi khac hinh" % kept
        self.report({'INFO'}, message)
        return {'FINISHED'}


class SRP_OT_widget_display(bpy.types.Operator):
    "Cho control nổi lên trên mesh (show_in_front + vẽ dạng nét viền)"
    bl_idname = "srp.widget_display"
    bl_label = "Control nổi lên trên mesh"
    bl_options = {'REGISTER', 'UNDO'}

    scope: bpy.props.EnumProperty(
        name="Phạm vi",
        items=(('ALL', "Mọi rig trong file", ""), ('ACTIVE', "Chỉ rig đang chọn", "")),
        default='ALL')
    in_front: bpy.props.BoolProperty(name="Vẽ lên trước mesh", default=True)
    wire: bpy.props.BoolProperty(name="Vẽ dạng nét viền", default=True)

    @classmethod
    def poll(cls, context):
        return bool(rigdef.managed_rigs(context))

    def execute(self, context):
        rigs = _rigs(context, self.scope)
        total = sum(set_display(rig, self.in_front, self.wire) for rig in rigs)
        self.report({'INFO'}, "%d rig, doi show_wire tren %d bone" % (len(rigs), total))
        return {'FINISHED'}


class SRP_OT_widget_offset(bpy.types.Operator):
    """Day widget ra ngoai than nhan vat, khong dời xuong"""
    bl_idname = "srp.widget_offset"
    bl_label = "Đẩy widget ra ngoài thân"
    bl_options = {'REGISTER', 'UNDO'}

    scope: bpy.props.EnumProperty(
        name="Phạm vi",
        items=(('ALL', "Mọi rig trong file", ""), ('ACTIVE', "Chỉ rig đang chọn", "")),
        default='ACTIVE')
    only_missing: bpy.props.BoolProperty(
        name="Chỉ bone chưa có offset", default=True,
        description="Tắt đi là ghi đè cả offset đã chỉnh tay trước đây")
    margin: bpy.props.FloatProperty(
        name="Khoảng hở (m)", default=MARGIN_M, min=0.0, max=0.3, unit='LENGTH',
        description="Hở thêm bao nhiêu sau khi ra khỏi da")
    skip_fingers: bpy.props.BoolProperty(
        name="Bỏ qua ngón tay", default=False,
        description="Control ngón thường nên nằm ngay trên ngón")
    reset: bpy.props.BoolProperty(
        name="Đưa hết về 0 thay vì đẩy", default=False,
        description="Đường lui: xoá mọi offset do addon đặt ra")

    @classmethod
    def poll(cls, context):
        return bool(rigdef.managed_rigs(context))

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        parts, failed = [], False
        for rig in _rigs(context, self.scope):
            if self.reset:
                count = 0
                for pose_bone in rig.pose.bones:
                    if tuple(pose_bone.custom_shape_translation) != (0.0, 0.0, 0.0):
                        pose_bone.custom_shape_translation = (0.0, 0.0, 0.0)
                        count += 1
                parts.append("%s: dua %d bone ve 0" % (rig.name, count))
                continue

            bones = None
            if self.skip_fingers:
                bones = {b.name for b in rig.pose.bones
                         if not any(b.name.startswith(p) for p in FINGER_PREFIXES)}
            result, error = auto_offset(context, rig, self.only_missing, self.margin, bones)
            if error:
                parts.append("%s: %s" % (rig.name, error))
                failed = True
                continue
            parts.append("%s: day %d, giu nguyen %d" % (rig.name, result[0], result[1]))
        self.report({'WARNING' if failed else 'INFO'}, " | ".join(parts) or "không có gì")
        return {'FINISHED'}


class SRP_OT_widget_fit(bpy.types.Operator):
    "Phóng widget cho bọc ra ngoài mesh — giữ nguyên vị trí, chỉ đổi kích thước"
    bl_idname = "srp.widget_fit"
    bl_label = "Bọc widget ra ngoài mesh"
    bl_options = {'REGISTER', 'UNDO'}

    scope: bpy.props.EnumProperty(
        name="Phạm vi",
        items=(('ALL', "Mọi rig trong file", ""), ('ACTIVE', "Chỉ rig đang chọn", "")),
        default='ACTIVE')
    margin: bpy.props.FloatProperty(
        name="Hở ra ngoài da (m)", default=FIT_MARGIN_M, min=0.0, max=0.2, unit='LENGTH')
    only_grow: bpy.props.BoolProperty(
        name="Chỉ phóng to", default=True,
        description="Tắt đi thì widget đang quá to cũng bị kéo nhỏ lại cho vừa "
                    "khít")

    @classmethod
    def poll(cls, context):
        return bool(rigdef.managed_rigs(context))

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        parts, failed = [], False
        for rig in _rigs(context, self.scope):
            result, error = auto_fit(context, rig, self.margin, self.only_grow)
            if error:
                parts.append("%s: %s" % (rig.name, error))
                failed = True
                continue
            parts.append("%s: phong %d, da vua %d" % (rig.name, result[0], result[1]))
        self.report({'WARNING' if failed else 'INFO'}, " | ".join(parts) or "không có gì")
        return {'FINISHED'}


class SRP_OT_widget_generate(bpy.types.Operator):
    "Sinh bộ widget chuẩn bằng code (không cần file thư viện)"
    bl_idname = "srp.widget_generate"
    bl_label = "Sinh bộ widget"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        made = [build_widget(kind).name for kind in SHAPES]
        self.report({'INFO'}, "%d widget: %s" % (len(made), ", ".join(made)))
        return {'FINISHED'}


CLASSES = (SRP_OT_widget_cleanup, SRP_OT_widget_display, SRP_OT_widget_fit,
           SRP_OT_widget_offset, SRP_OT_widget_generate)
