"""Sinh rig moi tu BO XUONG REF — dung dung convention trong `rigdef`.

Truoc day buoc nay doc mot bo marker (empty hinh cau). Da bo han: mot empty
chi noi duoc mot DIEM, khong noi duoc doan xuong chay tu dau toi dau, va nhat
la khong noi duoc ROLL. Roll thi `_align_roll()` doan lay theo huong xuong,
nguoi dung khong nhin thay va khong sua duoc — trong khi chinh no quyet dinh
khuyu gap ve huong nao va `pole_angle` bang bao nhieu.

Gio ban ve la mot armature that (`refrig`), moi doan xuong ref co head/tail/roll
keo tay trong Edit Mode. Ten xuong ref TRUNG ten xuong deform tuong ung, nen
cha cua xuong ref chinh la cha cua xuong rig — khong co bang tra thu hai.

`rigdef` van la nguon su that ve TEN va CAU TRUC; phan dau day giao cho
`build.apply_logic()` — dung cai ham dang dung de SUA rig cu. Mot duong code,
khong co ban sao de lech nhau.
"""

import math
import re

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty,
                       IntProperty, PointerProperty, StringProperty)
from mathutils import Vector

from . import build, cloth, compat, face, prefs, refrig, rigdef, snap, widgets

def eye_bone_names(rig):
    """Mọi xương mắt trên rig, xếp theo cặp: Eye.L, Eye.R, Eye_2.L, Eye_2.R...

    Nhân vật bốn mắt là chuyện bình thường, nên đừng gõ cứng đúng hai cái.
    """
    out = []
    for inst in range(1, rigdef.MAX_INSTANCE + 1):
        for side in rigdef.SIDES:
            name = rigdef.bone_name("Eye", inst, side)
            if name in rig.data.bones:
                out.append(name)
    return out


def face_bone_names(rig):
    """Xương mặt do addon dựng: hàm + mọi xương mắt."""
    return (["Jaw"] if "Jaw" in rig.data.bones else []) + eye_bone_names(rig)


# ------------------------------------------------------------- doc bo ref

class RefBone:
    """Anh chup mot xuong ref o he toa do THE GIOI.

    Chup ra roi moi lap ke hoach, thay vi hoi thang `bone.matrix_local` giua
    chung: bo ref va rig sinh ra co the dung hai ma tran object khac nhau, va
    tron hai he toa do trong cung mot bieu thuc la loi khong bao gio bao ra.
    """

    __slots__ = ("name", "head", "tail", "z_axis", "parent", "connect")

    def __init__(self, name, head, tail, z_axis, parent, connect=False):
        self.name = name
        self.head = head
        self.tail = tail
        self.z_axis = z_axis
        self.parent = parent
        self.connect = connect

    @property
    def vec(self):
        return self.tail - self.head

    @property
    def length(self):
        return self.vec.length


def snapshot(ref):
    """{ten: RefBone} — toan bo bo ref, da doi sang he the gioi."""
    W = ref.matrix_world
    R = W.to_3x3()
    out = {}
    for bone in ref.data.bones:
        basis = bone.matrix_local.to_3x3()
        z = R @ (basis @ Vector((0.0, 0.0, 1.0)))
        if z.length > 1e-9:
            z.normalize()
        out[bone.name] = RefBone(bone.name, W @ bone.head_local.copy(),
                                 W @ bone.tail_local.copy(), z,
                                 bone.parent.name if bone.parent else None,
                                 bone.use_connect)
    return out


def ref_metrics(bones):
    """(chieu cao, day thap nhat, huong TRUOC) do tu chinh bo ref.

    Chieu cao dung cho moi thu ty le: do dai `Root`, khoang cach pole, do dai
    duoi control IK. Do tu bo ref chu khong tu mesh — nguoi dung co the da keo
    bo ref lech han khoi mesh, va rig phai theo bo ref.
    """
    if not bones:
        return 1.7, 0.0, Vector((0.0, -1.0, 0.0))
    points = [p for b in bones.values() for p in (b.head, b.tail)]
    low = min(p.z for p in points)
    high = max(p.z for p in points)
    return max(high - low, 1e-3), low, Vector((0.0, -1.0, 0.0))


# ------------------------------------------------------------- ban ve

class Plan:
    """Danh sach xuong se dung. Moi muc la mot `Row`."""

    def __init__(self):
        self.rows = []
        self.names = set()

    def add(self, name, head, tail, parent, connect, deform, collection,
            z_axis=None):
        if name in self.names:
            return
        self.names.add(name)
        self.rows.append((name, head.copy(), tail.copy(), parent, connect,
                          deform, collection, z_axis))

    def __len__(self):
        return len(self.rows)

    def __iter__(self):
        return iter(self.rows)


def _chain(plan, limb_names, refs, parent, collection, deform, z_from):
    """Mot chuoi ba doan (deform / FK / IK) bam theo cung hinh hoc xuong ref."""
    previous = parent
    for index, name in enumerate(limb_names):
        source = refs[index]
        plan.add(name, source.head, source.tail, previous, index > 0, deform,
                 collection, z_from[index].z_axis)
        previous = name


def _ref_chain(plan, part, bones, fallback_parent, collection="Main Controls"):
    """Dung nguyen si mot nhom xuong ref: 1:1 ca vi tri, roll lan cach noi cha.

    Dung cho ban tay va chuoi bo tro — nhung nhom ma hinh dang HOAN TOAN do
    nguoi dung quyet, addon khong co y kien gi.
    """
    made = 0
    for _base, name in sorted(part.items()):
        source = bones.get(name)
        if source is None:
            continue
        plan.add(source.name, source.head, source.tail,
                 source.parent or fallback_parent, source.connect, True,
                 collection, source.z_axis)
        made += 1
    return made


def _roll_plan(plan, limb, heel, ankle, toe, toe_end):
    """Chuoi lan chan kieu reverse foot.

    Chen GIUA control ma animator cam (`LegIK`) va dich that cua constraint IK
    (`AnkleIK`). O rest moi bone deu identity nen `AnkleIK` trung dung co chan
    — rig co foot roll hay khong, ket qua o rest van y het nhau.
    """
    step = (toe_end - heel).length * 0.35 or 0.05
    collection = limb.collection_ik
    names = limb.roll
    plan.add(names[0], heel, heel + (toe - heel).normalized() * step,
             limb.ctrl, False, False, collection)
    plan.add(names[1], toe_end, toe_end + (heel - toe_end).normalized() * step,
             names[0], False, False, collection)
    plan.add(names[2], toe, toe + (toe_end - toe).normalized() * step,
             names[1], False, False, collection)
    plan.add(names[3], ankle, ankle + Vector((0.0, 0.0, step)),
             names[2], False, False, "Spare Bones")


def _ordered(parts):
    """Duyet bo phan theo thu tu on dinh.

    `sorted()` tran khong dung duoc: khoa la `(kind, inst, side)` va `side` la
    None voi bo phan nam giua (hong, cot song, mat), nen Python phai so sanh
    None voi 'L' va no nem TypeError.
    """
    return sorted(parts.items(), key=lambda item: refrig.part_sort_key(item[0]))


def build_plan(bones, parts, roll=True):
    """Ban ve day du, dung tu anh chup bo ref.

    `parts` = {(kind, inst, side): {ten goc: ten xuong ref}} — do
    `refrig.parts_in()` tra ve, da doi sang ten thay vi object Bone.
    """
    plan = Plan()
    height, floor, forward = ref_metrics(bones)

    def ref(part, base):
        name = part.get(base)
        return bones.get(name) if name else None

    def socket(part, base, fallback=None):
        """Cha cua xuong goc mot bo phan — chinh la cha cua xuong ref tuong ung."""
        source = ref(part, base)
        if source is not None and source.parent:
            return source.parent
        return fallback

    # ---------------------------------------------------------------- goc
    hips_part = None
    for key, part in parts.items():
        if key[0] == 'HIPS':
            hips_part = part
            break
    if hips_part is None:
        return plan, "chưa có xương Hips"
    hips_ref = ref(hips_part, "Hips")
    if hips_ref is None:
        return plan, "bộ ref thiếu xương Hips"
    hips = hips_ref.head

    plan.add("Root", Vector((hips.x, hips.y, floor)),
             Vector((hips.x, hips.y - height * 0.35, floor)),
             None, False, False, "Main Controls")
    plan.add("Hip_Master", hips, hips + forward * (height * 0.12),
             "Root", False, False, "Main Controls")
    plan.add("Hips", hips_ref.head, hips_ref.tail, "Hip_Master", False, False,
             "Main Controls", hips_ref.z_axis)

    # ------------------------------------------------------ cot song + dau
    for key, part in _ordered(parts):
        if key[0] != 'SPINE':
            continue
        order = ("Spine", "Spine.001", "Spine.002", "Spine.003",
                 "Neck", "Neck.001", "Neck.002", "Head")
        previous = socket(part, "Spine", "Hips")
        for index, base in enumerate(order):
            source = ref(part, base)
            if source is None:
                continue
            # Neck.001/002 la dot trung gian: nguoi ta khong keo tay tung dot
            # co, ho keo `Neck` va `Head`. De chung trong Main Controls chi lam
            # ray mat picker.
            collection = ("Deform Bones" if base in ("Neck.001", "Neck.002")
                          else "Main Controls")
            plan.add(source.name, source.head, source.tail, previous,
                     index > 0, True, collection, source.z_axis)
            previous = source.name

    # ------------------------------------------------------------- mat
    for key, part in _ordered(parts):
        # `FACE` la bo mat day du kieu Kid_Rig (ham, luoi, rang, moi, mi, may,
        # mui, tai, mat): dung NGUYEN SI tu bo ref, ca cha lan roll — cay cha
        # con ben trong (moi duoi theo ham, luoi theo ham) da nam san tren bo
        # ref. Bo ref cu chi co ham + mat cung di duong nay, khong can nhanh rieng.
        # Tung vung le (`Mặt · Lưỡi`, `Mặt · Mắt`...) cung vay — cha cheo vung
        # (luoi theo ham) da nam tren bo ref.
        if key[0] in refrig.FACE_KINDS:
            _ref_chain(plan, part, bones, "Head")

    # -------------------------------------------------------------- chi
    for (kind, inst, side), part in _ordered(parts):
        template = rigdef.TEMPLATE_BY_KIND.get(kind)
        if template is None:
            continue
        limb = rigdef.Limb(template, side, inst)
        word_fk, word_ik = limb.collection_fk, limb.collection_ik

        if kind == 'ARM':
            chain = [ref(part, b) for b in ("Bicep", "Forearm", "Hand_Master")]
            if any(b is None for b in chain):
                continue
            shoulder = ref(part, "Shoulder")
            root = socket(part, "Shoulder", "Spine.003")
            if shoulder is not None:
                plan.add(shoulder.name, shoulder.head, shoulder.tail, root,
                         False, True, "Main Controls", shoulder.z_axis)
                root = shoulder.name
            _chain(plan, limb.deform, chain, root, "Deform Bones", True, chain)
            _chain(plan, limb.fk, chain, root, word_fk, False, chain)
            _chain(plan, limb.ik, chain, root, "Spare Bones", False, chain)

            wrist = chain[2].head
            elbow = chain[1].head
            plan.add(limb.ctrl, wrist, wrist + Vector((0.0, height * 0.08, 0.0)),
                     "Root", False, False, word_ik)
            pole = elbow - forward * (height * 0.20)          # ra SAU khuyu
            plan.add(limb.pole, pole, pole + Vector((0.0, height * 0.05, 0.0)),
                     limb.ctrl, False, False, word_ik)

        elif kind == 'LEG':
            chain = [ref(part, b) for b in ("Thigh", "Shin", "Foot")]
            if any(b is None for b in chain):
                continue
            root = socket(part, "Thigh", "Hips")
            pelvis = rigdef.bone_name("Pelvis", inst, side)
            plan.add(pelvis, hips, chain[0].head, root, False, True,
                     "Deform Bones")
            _chain(plan, limb.deform, chain, pelvis, "Deform Bones", True, chain)
            _chain(plan, limb.fk, chain, pelvis, word_fk, False, chain)
            _chain(plan, limb.ik, chain, pelvis, "Spare Bones", False, chain)

            toe = ref(part, "Toe")
            if toe is not None:
                plan.add(toe.name, toe.head, toe.tail, limb.deform[2], True,
                         True, "Main Controls", toe.z_axis)

            ankle = chain[2].head
            knee = chain[1].head
            plan.add(limb.ctrl, ankle, ankle + Vector((0.0, height * 0.08, 0.0)),
                     "Root", False, False, word_ik)
            pole = knee + forward * (height * 0.20)           # ra TRUOC goi
            plan.add(limb.pole, pole, pole + Vector((0.0, height * 0.05, 0.0)),
                     limb.ctrl, False, False, word_ik)

            heel = ref(part, "Heel")
            if roll and heel is not None and toe is not None:
                _roll_plan(plan, limb, heel.head, ankle, toe.head, toe.tail)

    # ------------------------------------- ban tay + chuoi xuong bo tro
    #
    # Hai nhom nay dung NGUYEN SI tu bo ref. Ngon tay truoc day sinh theo ty le
    # ban tay, khong co xuong ref: hau qua la muon sua phai vao Edit Mode cua
    # rig DA DUNG, ma sua o do thi dung lai rig la mat sach — tuc thuc te la
    # khong sua duoc. Gio chung la mot bo phan cua bo ref nhu moi bo phan khac.
    for (kind, inst, side), part in _ordered(parts):
        if kind == 'HAND':
            _ref_chain(plan, part, bones,
                       rigdef.bone_name("Hand_Master", inst, side))
        elif kind == 'CHAIN':
            _ref_chain(plan, part, bones, "Root")

    return plan, None


# ------------------------------------------------------------- dung xuong

def _align_roll(edit_bone):
    """Roll mac dinh khi khong co xuong ref de chep: xuong dung thi Z ra truoc,
    xuong ngang thi Z len tren. Dung cho ngon tay, control IK, pole, chuoi lan
    chan — nhung thu sinh ra theo ty le chu khong do nguoi dung dat."""
    direction = (edit_bone.tail - edit_bone.head)
    if direction.length < 1e-6:
        return
    direction.normalize()
    reference = (Vector((0.0, -1.0, 0.0)) if abs(direction.z) > 0.7
                 else Vector((0.0, 0.0, 1.0)))
    edit_bone.align_roll(reference)


def build_skeleton(context, plan, name="SRP_Rig"):
    armature = bpy.data.armatures.new(name)
    rig = bpy.data.objects.new(name, armature)
    context.scene.collection.objects.link(rig)
    context.view_layer.objects.active = rig
    rig.select_set(True)
    rig.show_in_front = True

    collections = {}
    for row in plan:
        collection_name = row[6]
        if collection_name not in collections:
            collections[collection_name] = armature.collections.new(collection_name)

    bpy.ops.object.mode_set(mode='EDIT')
    edit = armature.edit_bones
    for name_, head, tail, _parent, _connect, deform, _collection, z_axis in plan:
        bone = edit.new(name_)
        bone.head, bone.tail = head, tail
        bone.use_deform = deform
        # Roll: chep tu xuong ref khi co. Day la ca ly do bo he marker — nguoi
        # dung xoay xuong ref thay the nao thi rig ra dung the ay.
        if z_axis is not None and z_axis.length > 1e-6:
            bone.align_roll(z_axis)
        else:
            _align_roll(bone)
    for name_, _h, _t, parent, connect, _d, _c, _z in plan:
        if parent and parent in edit:
            edit[name_].parent = edit[parent]
            edit[name_].use_connect = connect
    bpy.ops.object.mode_set(mode='OBJECT')

    for name_, _h, _t, _p, _c, _d, collection_name, _z in plan:
        collections[collection_name].assign(armature.bones[name_])

    for pose_bone in rig.pose.bones:
        pose_bone.rotation_mode = 'QUATERNION'

    # Chuoi IK va bone deform la co cau ben trong, khong phai control.
    for hidden in ("Spare Bones", "Deform Bones"):
        if hidden in collections:
            collections[hidden].is_visible = False
    return rig


# --------------------------------------------------------------- widget

# (tien to, hinh, ty le). Ty le tinh theo CHIEU DAI XUONG — moi hinh trong thu
# vien co ban kinh 1 don vi, va `use_custom_shape_bone_size` nhan no voi chieu
# dai xuong. Nen de nguyen 1.0 nghia la "ban kinh bang tron mot doan xuong",
# tuc BE NGANG gap doi doan xuong.
#
# Do duoc tren nhan vat cao 1,8 m khi con de 1.0 het: `Bicep` ve ra ban kinh
# 13,5 cm cho canh tay day chung 8 cm; `Thigh` 21,6 cm; control `ArmIK` thanh
# khoi hop 24,6 cm quanh ban tay 10 cm; `Palm` 5,4 cm trong khi ca ban tay chi
# 10 cm — nen ca ban tay thanh mot dam o vuong chong len nhau.
#
# Nhung xuong co the BOC theo da (than, chi) de nho roi cho `auto_fit` phong
# len theo tia ban that; `auto_fit` chi phong TO nen dat nho la an toan. Nhung
# xuong `auto_fit` co y bo qua (control IK, pole, lan chan, ngon tay) thi con
# so o day la con so cuoi cung, nen chung phai dung ngay.
# Ba con so phu them cho moi nhom, deu do MA RA (xem ghi chu duoi bang):
#   ty le      — theo CHIEU DAI XUONG, vi `use_custom_shape_bone_size` nhan
#                hinh don vi voi do dai xuong
#   tinh tien  — theo CHIEU DAI XUONG, nhung `assign_widgets()` phai TU NHAN
#                voi do dai vi `custom_shape_translation` cua Blender la MET
#                THO, khong theo do dai xuong (khac han `custom_shape_scale`).
#                De thang 0.5 vao la widget bay ra xa nua met — da nhin thay
#                tan mat: ca bo widget ban tay xep thanh mot hang ngoai khong
#                trung, cach ban tay gap ba lan chinh no.
#   xoay       — quanh truc CUC BO cua xuong; `FLAT` dua vong tron tu the
#                "vuong goc than xuong" ve "nam ngang"
NO_MOVE = (0.0, 0.0, 0.0)
MID = (0.0, 0.5, 0.0)
FLAT = (math.pi / 2.0, 0.0, 0.0)

WIDGET_RULES = (
    # `Root` va `Hip_Master` deu la xuong NAM NGANG chi ve truoc/sau, nen vong
    # tron vuong goc than xuong se DUNG DUNG chan ngang mat nguoi. Do duoc:
    # phap tuyen cua ca hai hinh trung 100% voi truc Y. Hai control nay phai la
    # vong nam duoi chan va vong quanh eo, nen ep chung ve mat phang ngang.
    (("Root",), 'RING', 0.50, NO_MOVE, FLAT),
    (("Hip_Master",), 'CIRCLE', 1.00, NO_MOVE, FLAT),
    (("Hips", "Spine", "Neck", "Head"), 'CIRCLE', 1.00, NO_MOVE, NO_MOVE),
    # Vai chi ngang ra hai ben, nen vong vuong goc than xuong cat xuyen qua co
    # va nguc. Dat nam ngang va day ra GIUA doan xuong thi no thanh cai dia
    # dat tren vai, dung cho nguoi ta bam.
    # Vai dung thanh det phu NUA NGOAI xuong doi. Vong tron nam ngang o giua
    # xuong doi thi cat xuyen co va nguc — do duoc 13/24 dinh nam trong thit,
    # sau nhat 47,5 mm — va phong to no ra chi lam vet cat rong them.
    (("Shoulder",), 'BAR', 1.00, NO_MOVE, NO_MOVE),
    (("Bicep", "Forearm", "Hand_Master", "Thigh", "Shin", "Foot", "Toe"),
     'CIRCLE', 0.25, NO_MOVE, NO_MOVE),
    (("ArmIK", "LegIK"), 'CUBE', 0.50, NO_MOVE, NO_MOVE),
    (("ElbowPole", "Pole"), 'DIAMOND', 0.60, NO_MOVE, NO_MOVE),
    (("Heel", "ToeTip", "Ball"), 'SQUARE', 0.50, NO_MOVE, NO_MOVE),
    # Ca NAM xuong Palm deu bat dau tu cung mot diem co tay (do duoc: cach nhau
    # 0,0000 mm), nen hinh dat o dau xuong la nam cai chong khit len nhau thanh
    # mot dam. Day ra giua doan xuong thi chung tu tach ra theo huong tung ngon.
    # `Palm` dung thanh det CHAY DOC than xuong: hinh vuong o mot diem thi ca
    # nam cai chong khit len nhau o co tay, con thanh doc thi moi cai trai theo
    # dung ngon cua no. Tinh tien de NO_MOVE vi `widgets.clear_widgets()` tinh
    # rieng — thanh nay nam ngay tren truc xuong nen khong day ra la chim han
    # trong thit.
    (("Palm",), 'SLAB', 1.00, NO_MOVE, NO_MOVE),
    (("Index", "Middle", "Ring", "Pinky", "Thumb"),
     'SQUARE', 0.30, NO_MOVE, NO_MOVE),
)

# Co cau ben trong — khong can hinh, va co hinh thi chi che mat control that.
NO_WIDGET = ("BicepIK", "ForearmIK", "HandIK", "ThighIK", "ShinIK", "FootIK",
             "Pelvis")


def _stem(name):
    """Bo hau to ben va so thu tu chi. `BicepFK_2.L` -> `BicepFK`."""
    base = name.split(".")[0]
    return re.sub(r"_\d+$", "", base)


def _plain(stem):
    """Bo them nhan FK/IK. `BicepFK` -> `Bicep`, `Hand_Master_FK` -> `Hand_Master`."""
    for tag in ("_FK", "_IK", "FK", "IK"):
        if stem.endswith(tag) and len(stem) > len(tag):
            return stem[:-len(tag)]
    return stem


def _rule_match(name, prefixes):
    """Ten xuong co thuoc nhom nay khong.

    Khop CHINH XAC tren phan than ten, thu hai lan: nguyen si truoc, roi moi bo
    nhan FK/IK. Thu tu do quan trong — `ArmIK` la CONTROL that su co ten nhu
    vay, bo nhan truoc thi no thanh `Arm` va roi khoi moi quy tac.
    #
    Ban truoc so bang `startswith` roi bi siet lai qua tay: `BicepFK.L` khong
    con khop `Bicep` nen TOAN BO xuong FK mat widget — anh Art nhin thay ngay
    vi rig cua anh de o che do FK. Con `startswith` tran thi `Hips` nuot ca
    `Hip_Master`. Khop chinh xac tren than ten giai duoc ca hai.
    """
    stem = _stem(name)
    return stem in prefixes or _plain(stem) in prefixes


# Xuong nam trong "Main Controls" ma khong quy tac nao nhan thi van phai co
# hinh — nguoi ta se bam vao no. Chuoi xuong bo tro (duoi, tai thu, vat ao) roi
# vao dung dien nay: ten do nguoi dung dat nen khong bang quy tac nao doan duoc.
FALLBACK = ('CIRCLE', 0.35, NO_MOVE, NO_MOVE)


def assign_widgets(context, rig, overwrite=True):
    made = 0
    for pose_bone in rig.pose.bones:
        if not overwrite and pose_bone.custom_shape is not None:
            continue
        if widgets.apply_face_widget(pose_bone, overwrite=overwrite):
            made += 1
            continue
        if _rule_match(pose_bone.name, NO_WIDGET):
            continue
        spec = None
        for prefixes, kind, scale, move, turn in WIDGET_RULES:
            if _rule_match(pose_bone.name, prefixes):
                spec = (kind, scale, move, turn)
                break
        if spec is None and _main_control(rig, pose_bone):
            spec = FALLBACK
        if spec is None:
            continue
        kind, scale, move, turn = spec
        pose_bone.custom_shape = widgets.build_widget(kind)
        pose_bone.use_custom_shape_bone_size = True
        pose_bone.custom_shape_scale_xyz = (scale, scale, scale)
        # `move` la ty le theo do dai xuong; Blender doi MET.
        length = pose_bone.bone.length or 1.0
        pose_bone.custom_shape_translation = [v * length for v in move]
        pose_bone.custom_shape_rotation_euler = turn
        pose_bone.bone.show_wire = True
        made += 1
    return made


def _main_control(rig, pose_bone):
    """Xuong nay co nam trong bo control nguoi dung bam vao khong."""
    return any(c.name == "Main Controls" for c in pose_bone.bone.collections)


# ------------------------------------------------------------ operators

class SRP_OT_generate(bpy.types.Operator):
    "Dựng rig + widget từ bộ ref, rồi đấu dây bằng chính apply_logic"
    bl_idname = "srp.generate"
    bl_label = "Dựng rig + widget"
    bl_options = {'REGISTER', 'UNDO'}

    rig_name: StringProperty(name="Tên rig", default="")
    use_roll: BoolProperty(name="Có foot roll", default=True)

    @classmethod
    def poll(cls, context):
        return refrig.find_ref(context) is not None

    def execute(self, context):
        settings = context.scene.srp_generate
        ref = refrig.find_ref(context)
        if ref is None:
            self.report({'ERROR'}, "Chưa có bộ xương ref")
            return {'CANCELLED'}
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        missing = refrig.missing_core(ref)
        if missing:
            labels = [refrig.PART_BY_KIND[k]['label'] for k in missing]
            self.report({'ERROR'}, "Bộ ref còn thiếu: %s" % ", ".join(labels))
            return {'CANCELLED'}

        bones = snapshot(ref)
        parts = {key: {base: bone.name for base, bone in group.items()}
                 for key, group in refrig.parts_in(ref).items()}
        plan, error = build_plan(bones, parts, roll=self.use_roll)
        if error:
            self.report({'ERROR'}, error)
            return {'CANCELLED'}

        name = self.rig_name.strip() or settings.rig_name.strip() or "SRP_Rig"
        rig = build_skeleton(context, plan, name)
        # Moc de `srp.ref_apply` biet sau nay nguoi dung keo xuong ref nao.
        refrig.store_baseline(ref)
        shapes = assign_widgets(context, rig)

        # Boc widget than & chi theo DA THAT, roi don nhung cai con chim trong
        # thit. Ca hai deu tu tim mesh qua `widgets.fit_meshes()`: mesh da skin
        # neu co, khong thi chinh `target_mesh` nguoi dung chon o buoc 1.
        result, _error = widgets.auto_fit(context, rig)
        fitted = result[0] if result else 0
        widgets.clear_widgets(context, rig)

        limbs = rigdef.limbs_for(rig)
        if not limbs:
            self.report({'ERROR'}, "Rig dựng ra không khớp chi nào — sai bản vẽ")
            return {'CANCELLED'}

        build.apply_logic(context, rig)

        # `pole_angle` phu thuoc roll nen khong hardcode duoc: hai ben tay
        # guong nhau thi hang so lech dung 180 do. Da co may do roi thi do
        # luon, dung de nguoi dung phai tu phat hien khuyu gap nguoc.
        calibrated = 0
        for limb in limbs:
            _result, error = snap.calibrate_pole(context, rig, limb)
            if not error:
                calibrated += 1

        failures = build.verify_switching(context, rig)
        if failures:
            self.report({'ERROR'}, "Dựng xong nhưng FK↔IK hỏng: %s" % failures[0])
            return {'FINISHED'}

        # Bo ref da xong viec — an di, khong xoa. Xoa la mat ban ve, ma sua rig
        # thi phai sua tu ban ve roi dung lai.
        ref.hide_set(True)
        self.report({'INFO'}, "%s: %d xương, %d widget (%d bọc theo da), %d chi "
                              " | pole đo lại %d/%d | FK↔IK đã kiểm chứng"
                    % (rig.name, len(rig.data.bones), shapes, fitted, len(limbs),
                       calibrated, len(limbs)))
        return {'FINISHED'}


class SRP_OT_bind(bpy.types.Operator):
    "Skin mesh vào rig bằng automatic weights"
    bl_idname = "srp.bind"
    bl_label = "Bind mesh thân"
    bl_options = {'REGISTER', 'UNDO'}

    face_weights: BoolProperty(
        name="Tô riêng trọng số hàm & mắt", default=True,
        description="Automatic weights không biết răng phải cứng và nhãn cầu "
                    "phải quay trọn khối. Bước này tô lại ba xương mặt theo "
                    "nhóm vùng FS_*. Không có nhóm vùng thì tự bỏ qua")
    drop_ref: BoolProperty(
        name="Xoá bộ xương ref", default=True,
        description="Bind xong là bộ ref hết việc — xoá đi cho gọn file. TẮT "
                    "nếu còn muốn nắn lại bộ ref rồi dựng rig lần nữa: dựng lại "
                    "cần bộ ref, không có thì phải nắn lại từ đầu")

    @classmethod
    def poll(cls, context):
        settings = getattr(context.scene, "srp_generate", None)
        return (settings is not None and settings.target_mesh is not None
                and rigdef.active_rig(context) is not None)

    def invoke(self, context, event):
        mesh = context.scene.srp_generate.target_mesh
        rig = rigdef.active_rig(context)
        if not cloth.deformed_by(mesh, rig):
            return self.execute(context)
        hand = len(cloth.hand_painted(mesh))
        msg = "Toàn bộ weight của %s và quần áo sẽ bị tính lại từ đầu." % mesh.name
        if hand:
            msg += " Mất luôn %d vertex bạn đã vẽ tay." % hand
        msg += " Chỉ muốn chép weight thân sang quần áo thì dùng 'Cập nhật quần áo'."
        return context.window_manager.invoke_confirm(
            self, event, title="Bind lại từ đầu?", message=msg, confirm_text="Bind lại",
            icon='ERROR')

    def execute(self, context):
        settings = context.scene.srp_generate
        rig = rigdef.active_rig(context)
        mesh = settings.target_mesh
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        eyes = eyeball_meshes(context)          # [(ten xuong, object)]
        # Mesh mat rời — bo qua neu nguoi dung chon nham chinh mesh than.
        extras = [(role, obj) for role, obj in face_part_meshes(context)
                  if obj is not mesh]

        # Object nam trong collection bi exclude thi `select_set` va gan active
        # deu nem RuntimeError giua chung. Chan tu dau, kem ten collection.
        if face.report_hidden(self, context, mesh, rig,
                              *[o for _b, o in eyes], *[o for _r, o in extras]):
            return {'CANCELLED'}

        for obj in list(context.selected_objects):
            obj.select_set(False)
        mesh.select_set(True)
        rig.select_set(True)
        context.view_layer.objects.active = rig
        # Giau xuong mat khoi automatic weights — NHUNG CHI KHI ta to lai duoc.
        #
        # Giau nham thi xuong mat khong duoc chia phan luc bind, va buoc to lai
        # cung bo cuoc vi thieu nhom vung -> ba xuong do khong co MOT vertex
        # nao. Da mac dung loi nay: tren `My_Body` (khong co nhom FS_ nao),
        # xuong ham thanh xuong chet hoan toan sau khi bind.
        paint = self.face_weights and face.has_face_regions(mesh)
        # Nhan cau da la object rieng gan CUNG vao xuong mat thi xuong mat
        # khong con viec gi tren mesh than — de automatic weights chia phan cho
        # no la no keo da hoc mat theo huong nhin. Do duoc: 1158 vertex than
        # dinh vao `Eye.L` khi khong giau no di.
        eye_bones = {bone for bone, _o in eyes}
        # Cung mot ly le cho MOI xuong dang cong phu kien gan cung — mu, kinh,
        # trang suc, dao cu. Xem `mount_bones`.
        mounted = mount_bones(rig)
        # Rang va luoi da co mesh rieng thi xuong cua chung khong con viec gi
        # tren mesh than — de automatic weights chia phan la chung keo moi va
        # ma theo. Long may thi KHONG giau: tren Kid_Rig xuong Eyebrow van giu
        # da tran cua mesh than (69 vertex moi xuong), nhuong may la keo da.
        apart = set()
        for role, _obj in extras:
            if role in ('TEETH', 'TONGUE'):
                apart.update(face_role_bones(rig, role))
        skip = ((set(face_bone_names(rig)) if paint else eye_bones)
                | set(mounted) | apart)
        hidden = [b for b in rig.data.bones
                  if b.name in skip and b.use_deform]
        for bone in hidden:
            bone.use_deform = False
        # Va XOA nhom cu cua chung tren mesh. `ARMATURE_AUTO` ghi de nhom cua
        # xuong deform nhung khong dong toi nhom cua xuong da bi loai — nen
        # bind lai van con nguyen trong so cu, va xuong do van keo da nhu chua
        # he giau no di. Do duoc: `Eye.L` giu lai 1158 vertex qua ba lan bind.
        for bone in hidden:
            group = mesh.vertex_groups.get(bone.name)
            if group is not None:
                mesh.vertex_groups.remove(group)
        try:
            bpy.ops.object.parent_set(type='ARMATURE_AUTO')
        except RuntimeError as error:
            self.report({'ERROR'}, "Bind that bai: %s" % error)
            return {'CANCELLED'}
        finally:
            for bone in hidden:
                bone.use_deform = True
        # trong so than vua lam moi hoan toan -> ban luu "da goc" cua quan ao vo nghia,
        # danh dau ve tay cung vay (bind lai tu dau = bo weight ve tay)
        if cloth.SKIN_KEY in mesh.keys():
            del mesh[cloth.SKIN_KEY]
        cloth.forget_hand(mesh)
        for entry in settings.cloth_meshes:
            if entry.mesh is not None:
                cloth.forget_hand(entry.mesh)
        # quan ao bind ngay ben duoi tu chinh weight than nay -> da dong bo
        mesh[cloth.SYNC_KEY] = mesh.get(cloth.STAMP_KEY, 0)

        deform = sum(1 for b in rig.data.bones if b.use_deform)
        groups = len(mesh.vertex_groups)
        message = "Bind %s vao %s%s" % (
            mesh.name, rig.name,
            prefs.detail(" | %d xuong deform, %d vertex group" % (deform, groups)))

        # Automatic weights tra ve trong so mem cho MOI thu, ke ca rang va nhan
        # cau — hai khoi CUNG. Sua ngay tai day chu khong de nguoi dung nho bam
        # them mot nut: trong so la viec cua buoc bind.
        if paint:
            counts = face.weigh_face_bones(
                rig, mesh, eyes_apart=[bone for bone, _o in eyes])
            if counts is not None:
                message += prefs.detail(" | xương mặt: %d vertex nhãn cầu, %d da "
                                        "hàm, %d răng dưới" % counts)
        elif self.face_weights and face_bone_names(rig):
            message += (" | chưa có nhóm vùng FS_* nên xương mặt dùng automatic "
                        "weights như mọi xương khác")

        # Nhan cau roi: gan CUNG vao xuong mat. Skin no nhu da la sai — no la
        # khoi cung, va automatic weights se lam no meo theo mi mat.
        attached = []
        for bone, obj in eyes:
            if bone not in rig.data.bones:
                message += " | rig không có xương %s" % bone
                continue
            attached.append(face.attach_eye(obj, rig, bone))
        if attached:
            message += " | gắn cứng %s vào xương mặt" % ", ".join(attached)
        if mounted:
            message += (" | giau %s khoi automatic weights (dang cong %s)"
                        % (", ".join(sorted(mounted)),
                           ", ".join(sorted(n for v in mounted.values() for n in v))))

        # Mesh mat rời bind SAU mesh than: `bind_restricted` doi selection va
        # tat tam `use_deform`, lam truoc thi buoc bind than doc sai trang thai.
        for role, obj in extras:
            message += " | " + bind_face_mesh(context, obj, rig, role)
        if extras:
            context.view_layer.objects.active = rig

        # Than da khop theo nhan vat mau: weight to tay cua mau tot hon automatic
        # weights -- de len. Mesh phu cung hinh mau (long may) cung chep luon.
        if settings.template_weights:
            from . import fitref
            for line in fitref.bind_from_template(context, rig, mesh):
                message += " | " + line
            context.view_layer.objects.active = rig

        # Lap vertex tong trong so < 1 (to lai ham hay de lai vai cai o cam) TRUOC
        # quan ao: "chep tu than" doc lai chinh trong so than.
        filled, _empty = cloth.fill_weights(mesh, rig)
        if filled:
            message += " | lấp %d vertex thiếu trọng số" % filled

        # Quan ao SAU mesh than: che do "chep tu than" doc trong so than vua bind.
        for line in cloth.bind_all(context, rig, mesh):
            message += " | " + line

        # Bo ref het viec sau khi bind: rig da dung, da skin, no chi con nam
        # do cho nang file. Xoa CA object lan armature data — bo moi object
        # thi data thanh mo coi, no van chiem cho tren dia cho toi lan mo file
        # sau. Khong co gi tro toi bo ref (`find_ref` do bang the tren xuong,
        # khong bang con tro) nen xoa khong lam gay lien ket nao.
        if self.drop_ref:
            dropped = drop_ref(context)
            if dropped:
                message += " | đã xoá bộ ref %s" % dropped
        self.report({'INFO'}, message)
        return {'FINISHED'}


class SRP_OT_widget_assign(bpy.types.Operator):
    """Gán hình cho từng control theo bảng quy tắc

    `srp.widget_generate` chỉ TẠO ra các object hình, không gán chúng vào xương
    — việc gán xưa nay nằm trong `srp.generate`. Nên rig nào lỡ mất custom shape
    thì không có đường nào lấy lại ngoài dựng lại cả rig. Nút này lấp chỗ trống đó.
    """
    bl_idname = "srp.widget_assign"
    bl_label = "Gán hình cho control"
    bl_options = {'REGISTER', 'UNDO'}

    overwrite: BoolProperty(
        name="Đè lên hình đang có", default=False,
        description="Tắt: chỉ gán cho control chưa có hình, giữ nguyên hình đã "
                    "chỉnh tay. Bật: gán lại hết theo bảng quy tắc")

    @classmethod
    def poll(cls, context):
        return rigdef.active_rig(context) is not None

    def execute(self, context):
        rig = rigdef.active_rig(context)
        kept = 0 if self.overwrite else sum(1 for pb in rig.pose.bones
                                            if pb.custom_shape is not None)
        made = assign_widgets(context, rig, overwrite=self.overwrite)
        # Widget ban tay, vai va ham deu nam ngay tren truc xuong — tuc trong
        # thit. Don chung ra ngay sau khi gan, bang phep DO chu khong phai bang
        # mot con so day chon san.
        widgets.clear_widgets(context, rig)
        self.report({'INFO'}, "Gan hinh cho %d control%s"
                    % (made, " | giữ nguyên %d cái đã có" % kept if kept else ""))
        return {'FINISHED'}


class SRP_EyeMesh(bpy.types.PropertyGroup):
    """Một nhãn cầu rời: mesh + bên của nhân vật."""
    mesh: PointerProperty(name="Mesh", type=bpy.types.Object,
                          poll=lambda self, obj: obj.type == 'MESH')
    side: EnumProperty(name="Bên", default='L',
                       items=(('L', "Trái", ""), ('R', "Phải", "")))


FACE_ROLES = (
    ('TEETH', "Răng", "Mỗi đảo lưới gắn CỨNG vào Teeth_Upper hoặc Teeth_Lower "
                      "gần nhất — một mesh chứa cả hai hàm cũng được"),
    ('TONGUE', "Lưỡi", "Automatic weights CHỈ trên chuỗi xương Tongue"),
    ('BROW', "Lông mày", "Automatic weights CHỈ trên xương Eyebrow + Head"),
)
FACE_ROLE_LABEL = {key: label for key, label, _d in FACE_ROLES}


class SRP_FaceMesh(bpy.types.PropertyGroup):
    """Một mesh mặt rời (răng, lưỡi, lông mày) + vai trò của nó."""
    mesh: PointerProperty(name="Mesh", type=bpy.types.Object,
                          poll=lambda self, obj: obj.type == 'MESH')
    role: EnumProperty(name="Vai trò", default='TEETH', items=FACE_ROLES)


class SRP_GenerateSettings(bpy.types.PropertyGroup):
    target_mesh: PointerProperty(name="Mesh nhân vật", type=bpy.types.Object,
                                 poll=lambda self, obj: obj.type == 'MESH')
    # Rang, luoi, long may la mesh RIENG trong bo Kid_Rig (hoac dao luoi rieng
    # trong mesh than). Moi loai bind mot kieu — xem `bind_face_mesh()`.
    face_meshes: CollectionProperty(name="Mesh mặt rời", type=SRP_FaceMesh)
    # Quan ao / toc / phu kien la mesh RIENG — xem `cloth.py`.
    cloth_meshes: CollectionProperty(name="Quần áo, phụ kiện", type=cloth.SRP_ClothMesh)
    skin_follow: BoolProperty(
        name="Sửa da dưới áo theo áo (đổi weight thân)", default=True,
        description="Da bị quần áo che lấy trọng số của áo ngay phía trên -- da "
                    "không đâm xuyên áo khi gập tay, cúi người. Da lộ ra ngoài, "
                    "đầu và bàn tay không bị đổi")
    rig_name: StringProperty(
        name="Tên rig", default="SRP_Rig",
        description="Tên armature sẽ dựng ra. Bộ ref lấy chính tên này cộng "
                    "thêm _Ref")
    # Nhan cau la KHOI CUNG, va no thuong la object rieng. Bind skin khong the
    # xu ly no nhu da: automatic weights se lam no meo theo mi mat. Chi ro o day
    # thi buoc bind gan cung no vao xuong mat.
    # Hai o cu, giu lai lam duong lui: file thiet lap tu truoc phien nay khong
    # mat gi. `eyeball_meshes()` chi doc chung khi danh sach moi con rong.
    eye_L: PointerProperty(name="Nhãn cầu trái", type=bpy.types.Object,
                           poll=lambda self, obj: obj.type == 'MESH')
    eye_R: PointerProperty(name="Nhãn cầu phải", type=bpy.types.Object,
                           poll=lambda self, obj: obj.type == 'MESH')
    eyes: CollectionProperty(name="Nhãn cầu rời", type=SRP_EyeMesh)
    eye_index: IntProperty(name="Dòng đang chọn", default=0)
    # Nhan vat DA RIG lam mau -- xem `fitref.py`
    template_rig: PointerProperty(name="Rig mẫu", type=bpy.types.Object,
                                  poll=lambda self, obj: obj.type == 'ARMATURE')
    template_mesh: PointerProperty(name="Mesh mẫu", type=bpy.types.Object,
                                   poll=lambda self, obj: obj.type == 'MESH')
    template_weights: BoolProperty(
        name="Bind: chép weight + shape key từ mẫu", default=True,
        description="Mesh nhân vật đã khớp theo mẫu thì lúc Bind lấy weight của "
                    "mẫu (đã tô tay) thay cho automatic weights, và chép luôn bộ "
                    "shape key của mẫu (key trùng tên bị ghi đè)")


# ------------------------------------------------------- tien do dung rig

def eyeball_meshes(context):
    """[(tên xương mắt, object)] — nhãn cầu rời người dùng đã chỉ ở bước 1.

    Mesh thứ nhất bên L nhận `Eye.L`, thứ hai nhận `Eye_2.L`... đúng quy ước
    đánh số của `rigdef`. Ghép theo THỨ TỰ trong danh sách nên panel phải in
    thẳng tên xương ra từng dòng, không bắt người dùng đoán.
    """
    settings = getattr(context.scene, "srp_generate", None)
    if settings is None:
        return []
    out, count = [], {side: 0 for side in rigdef.SIDES}
    for entry in settings.eyes:
        if entry.mesh is None or entry.mesh.type != 'MESH':
            continue
        count[entry.side] += 1
        out.append((rigdef.bone_name("Eye", count[entry.side], entry.side),
                    entry.mesh))
    if out:
        return out
    # Duong lui cho file lam truoc khi co danh sach.
    for side in rigdef.SIDES:
        obj = getattr(settings, "eye_%s" % side, None)
        if obj is not None and obj.type == 'MESH':
            out.append((rigdef.bone_name("Eye", 1, side), obj))
    return out


def face_part_meshes(context):
    """[(vai tro, object)] — mesh rang/luoi/long may nguoi dung da chi o buoc 1."""
    settings = getattr(context.scene, "srp_generate", None)
    if settings is None:
        return []
    return [(entry.role, entry.mesh) for entry in settings.face_meshes
            if entry.mesh is not None and entry.mesh.type == 'MESH']


def face_role_bones(rig, role):
    """Xuong deform ma mot mesh mat rời duoc phep bam vao.

    Doc tu rig chu khong liet ke cung: rig cu khong co luoi thi tra rong va
    buoc bind bao ra, khong im lang skin nham vao xuong khac.
    """
    bones = rig.data.bones
    if role == 'TEETH':
        return [n for n in refrig.FACE_TEETH if n in bones]
    if role == 'TONGUE':
        return [b.name for b in bones
                if b.use_deform and b.name.startswith(refrig.FACE_TONGUE_PREFIX)]
    if role == 'BROW':
        out = [b.name for b in bones
               if b.use_deform and b.name.startswith(refrig.FACE_BROW_PREFIX)]
        # Kid_Rig: mesh long may van giu mot chut `Head` o ria — de luc nhuong
        # may thi chan long khong bi giat khoi da.
        if out and "Head" in bones:
            out.append("Head")
        return out
    return []


def _mesh_islands(mesh):
    """[[chi so vertex]] — tung dao luoi lien thong theo canh."""
    parent = list(range(len(mesh.vertices)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for edge in mesh.edges:
        a, b = find(edge.vertices[0]), find(edge.vertices[1])
        if a != b:
            parent[a] = b
    groups = {}
    for i in range(len(mesh.vertices)):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def _segment_distance(point, head, tail):
    axis = tail - head
    if axis.length_squared < 1e-12:
        return (point - head).length
    t = max(0.0, min(1.0, (point - head).dot(axis) / axis.length_squared))
    return (point - (head + axis * t)).length


def _reset_skin(obj, rig, bone_names):
    """Go moi armature modifier cu tro toi rig va moi nhom cua xuong rig."""
    for mod in [m for m in obj.modifiers
                if m.type == 'ARMATURE' and m.object is rig]:
        obj.modifiers.remove(mod)
    for group in [g for g in obj.vertex_groups if g.name in bone_names]:
        obj.vertex_groups.remove(group)


def _attach_skin(obj, rig):
    """Parent object vao rig (giu nguyen cho dung) + mot armature modifier."""
    world = obj.matrix_world.copy()
    obj.parent = rig
    obj.parent_type = 'OBJECT'
    obj.matrix_world = world
    mod = obj.modifiers.new(name=rig.name, type='ARMATURE')
    mod.object = rig
    mod.use_vertex_groups = True
    return mod


def bind_rigid_islands(obj, rig, bones):
    """Moi dao luoi gan CUNG (trong so 1.0) vao xuong gan no nhat.

    Dung cho rang: Kid_Rig co hai dao rang, moi dao 1.0 tren dung mot xuong
    (`Teeth_Upper` / `Teeth_Lower`). Do bang khoang cach tu TAM dao toi DOAN
    xuong, nen mot mesh chua ca hai ham van tu tach dung.
    Tra ve {ten xuong: so vertex}.
    """
    all_bones = {b.name for b in rig.data.bones}
    _reset_skin(obj, rig, all_bones)
    to_world = obj.matrix_world
    segments = [(name, rig.matrix_world @ rig.data.bones[name].head_local,
                 rig.matrix_world @ rig.data.bones[name].tail_local)
                for name in bones]
    counts = {}
    groups = {name: obj.vertex_groups.new(name=name) for name in bones}
    for island in _mesh_islands(obj.data):
        centre = Vector((0.0, 0.0, 0.0))
        for i in island:
            centre += to_world @ obj.data.vertices[i].co
        centre /= len(island)
        name = min(segments, key=lambda s: _segment_distance(centre, s[1], s[2]))[0]
        groups[name].add(island, 1.0, 'REPLACE')
        counts[name] = counts.get(name, 0) + len(island)
    for name, group in groups.items():
        if name not in counts:
            obj.vertex_groups.remove(group)
    _attach_skin(obj, rig)
    return counts


def bind_restricted(context, obj, rig, bones):
    """Automatic weights nhung CHI tren `bones`.

    Tat tam `use_deform` cua moi xuong khac roi goi dung `ARMATURE_AUTO` — cung
    thuat toan heat nhu bind than, chi khac la khong xuong ngoai nao gianh
    duoc vertex. Kid_Rig: luoi chia tren 4 dot Tongue, long may tren 4 dot
    Eyebrow moi ben.
    """
    allowed = set(bones)
    _reset_skin(obj, rig, {b.name for b in rig.data.bones})
    muted = [b for b in rig.data.bones if b.use_deform and b.name not in allowed]
    for bone in muted:
        bone.use_deform = False
    try:
        for other in list(context.selected_objects):
            other.select_set(False)
        obj.select_set(True)
        rig.select_set(True)
        context.view_layer.objects.active = rig
        bpy.ops.object.parent_set(type='ARMATURE_AUTO')
    finally:
        for bone in muted:
            bone.use_deform = True
    return len([g for g in obj.vertex_groups if g.name in allowed])


def bind_face_mesh(context, obj, rig, role):
    """Bind mot mesh mat rời theo vai tro. Tra ve dong bao cao."""
    bones = face_role_bones(rig, role)
    label = FACE_ROLE_LABEL.get(role, role)
    if not bones:
        return "%s %s: rig không có xương %s, bỏ qua" % (label, obj.name, label.lower())
    if role == 'TEETH':
        counts = bind_rigid_islands(obj, rig, bones)
        return "%s %s: %s" % (label, obj.name, ", ".join(
            "%s %d vertex" % (n, c) for n, c in sorted(counts.items())))
    try:
        made = bind_restricted(context, obj, rig, bones)
    except RuntimeError as error:
        return "%s %s: bind thất bại (%s)" % (label, obj.name, error)
    return "%s %s: %d xương" % (label, obj.name, made)


def legacy_eyes(context):
    """Hai o chon cu con gia tri ma danh sach moi thi rong."""
    settings = getattr(context.scene, "srp_generate", None)
    if settings is None or len(settings.eyes):
        return []
    return [(side, getattr(settings, "eye_%s" % side))
            for side in rigdef.SIDES
            if getattr(settings, "eye_%s" % side, None) is not None]


def mount_bones(rig):
    """{ten xuong: [ten object]} — xuong dang cong phu kien gan CUNG vao no.

    Object gan bang bone parent di theo phep quay cua xuong, khong dung toi
    mot trong so nao. Nen xuong do KHONG duoc phep an phan trong automatic
    weights: de no deform thi no vua cong cai mu vua keo theo da dau, va keo
    mu la keo ca mat nguoi.

    Do tren `Test_Pig_Rig`: xuong `Hat` (deform, cha la `Head`, dang cong
    `pig_hat` gan cung) om luon 1006 vertex vung dau, trong so toi 1,00.

    Nhan dien bang QUAN HE PARENT chu khong bang ten: dat ten `Hat`, `Cap`,
    `Prop_01` hay gi cung duoc, addon khong phai doan. Va xuong nao cong phu
    kien SKIN (armature modifier) thi khong nam trong day — cai do phai
    deform that.
    """
    out = {}
    for obj in bpy.data.objects:
        if (obj.parent is rig and obj.parent_type == 'BONE'
                and obj.parent_bone):
            out.setdefault(obj.parent_bone, []).append(obj.name)
    return out


def stray_mounts(context, rig):
    """[(mesh, ten xuong, so vertex)] — phu kien gan cung ma van con trong so.

    Rig bind truoc khi gan phu kien thi trong so cu con nguyen; day la cho de
    do ra va bao cho nguoi dung, thay vi de ho tu hoi vi sao keo cai mu thi
    ca dau di theo.
    """
    mounted = mount_bones(rig)
    if not mounted:
        return []
    found = []
    for obj in context.scene.objects:
        if obj.type != 'MESH':
            continue
        if not any(m.type == 'ARMATURE' and m.object is rig
                   for m in obj.modifiers):
            continue
        for name in mounted:
            if obj.vertex_groups.get(name) is None:
                continue
            count = len(face.read_region(obj, name))
            if count:
                found.append((obj, name, count))
    return found


class SRP_OT_free_mounts(bpy.types.Operator):
    """Trả trọng số của xương cõng phụ kiện về xương cha

    Phụ kiện gắn cứng (mũ, kính, trang sức) đi theo phép quay của xương nên
    không cần trọng số nào. Trọng số còn sót lại chỉ làm xương đó kéo thêm
    da người. Nút này gỡ chúng ra và trả lại cho xương cha — tư thế nghỉ
    không xê dịch vì tổng trọng số mỗi vertex giữ nguyên
    """
    bl_idname = "srp.free_mounts"
    bl_label = "Gỡ trọng số khỏi xương cõng phụ kiện"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        rig = rigdef.active_rig(context)
        return rig is not None and bool(stray_mounts(context, rig))

    def execute(self, context):
        rig = rigdef.active_rig(context)
        stray = stray_mounts(context, rig)
        if not stray:
            self.report({'INFO'}, "Không có xương cõng phụ kiện nào giữ trọng "
                                  "số")
            return {'CANCELLED'}
        notes, total = [], 0
        for mesh, name, _count in stray:
            bone = rig.data.bones.get(name)
            parent = bone.parent.name if bone is not None and bone.parent else None
            if parent is None or mesh.vertex_groups.get(parent) is None:
                notes.append("%s: %s không có xương cha để trả về" % (mesh.name, name))
                continue
            moved = face.drop_bone_weight(mesh, name, parent)
            total += moved
            notes.append("%s: tra %d vertex tu %s ve %s"
                         % (mesh.name, moved, name, parent))
        self.report({'INFO'}, "Go %d vertex | %s" % (total, " | ".join(notes)))
        return {'FINISHED'}


def drop_ref(context):
    """Xoa bo xuong ref khoi file. Tra ve ten da xoa, hoac None.

    Xoa het bo ref co trong file chu khong chi cai `find_ref` tra ve dau tien:
    dung rig hai lan cho hai nhan vat thi trong file co hai bo, ma nguoi dung
    bam Bind mot lan roi tuong da don sach.
    """
    refs = [obj for obj in bpy.data.objects if refrig.is_ref(obj)]
    if not refs:
        return None
    names = [obj.name for obj in refs]
    data = [obj.data for obj in refs]
    for obj in refs:
        bpy.data.objects.remove(obj, do_unlink=True)
    # Bo object xong data thanh mo coi: no van nam trong file cho toi lan mo
    # sau moi bi don. Xoa thang cho gon ngay.
    for block in data:
        if block.users == 0:
            bpy.data.armatures.remove(block)
    return ", ".join(names)


def bound_mesh(context, rig):
    """Mesh dang skin vao rig, hoac None."""
    if rig is None:
        return None
    for obj in context.scene.objects:
        if obj.type != 'MESH':
            continue
        if not any(m.type == 'ARMATURE' and m.object is rig for m in obj.modifiers):
            continue
        if any(g.name in rig.data.bones for g in obj.vertex_groups):
            return obj
    return None


def build_progress(context):
    """Trang thai cac buoc dung rig: [(ten, xong chua, con thieu gi)].

    Tinh lai moi lan goi, khong nho ket qua. Da thu nho lai 0,2 giay cho do 5
    lan quet moi lan ve (do duoc 0,84 ms mot lan) — hong ngay: bam nut xong
    panel ve lai trong vong 0,2 giay do va no hien y nguyen trang thai cu, tuc
    buoc sau khong mo ra. Panel nay de phan anh trang thai, nen no khong duoc
    phep tre mot nhip nao.
    """
    settings = getattr(context.scene, "srp_generate", None)
    target = settings.target_mesh if settings else None
    ref = refrig.find_ref(context)
    parts = refrig.parts_in(ref)
    rig = rigdef.active_rig(context)
    bound = bound_mesh(context, rig)

    shaped = rig is not None and any(pb.custom_shape is not None
                                     for pb in rig.pose.bones)
    # Rig dung xong roi thi hai buoc nan bo ref coi nhu xong, ke ca khi bo ref
    # khong con (bind co the da xoa no — xem `drop_ref`). Khong the ma bang
    # tien do tu tut nguoc ve "chua co bo ref" ngay sau khi bind thanh cong.
    built = rig is not None and shaped
    has_hips = built or any(k == 'HIPS' for k, _i, _s in parts)
    missing = [] if built else refrig.missing_core(ref)
    keyed = False
    face_mesh = target or bound
    if face_mesh is not None:
        key = getattr(face_mesh.data, "shape_keys", None)
        keyed = bool(key) and any(face.is_own(key, kb) for kb in key.key_blocks)

    # Vung FS_ do tren mesh nao thi phai hoi dung mesh do — `region_target`
    # cho phep chon rieng mesh mat khac mesh than.
    #
    # Hoi "da TAO nhom chua", khong hoi "da TO chua": doc trong so that mat
    # 11,1 ms tren mesh 2 729 vertex / 150 nhom, ma ham nay chay trong `poll()`
    # cua tung buoc, tuc bay lan moi lan ve lai panel. Panel to vung moi doc
    # that (no chi ve khi dang mo), va `srp.bind` hoi lai mot lan luc bam nut.
    region_mesh = face.region_target(context) or face_mesh
    made = face.face_region_groups(region_mesh)

    later = [refrig.PART_BY_KIND[k]['label'] for k in missing if k != 'HIPS']
    return [
        ("Chọn mesh", target is not None, "chưa chọn mesh nhân vật"),
        ("Xương Hips", has_hips, "chưa có bộ ref"),
        ("Các bộ phận", not missing,
         "còn thiếu %s" % ", ".join(later) if later else "còn thiếu Hips"),
        ("Dựng rig + widget", rig is not None and shaped,
         "chưa dựng rig" if rig is None else "chưa control nào có hình"),
        ("Nhóm vùng khuôn mặt", len(made) == len(face.REQUIRED),
         "chưa tạo nhóm FS_"),
        ("Bind skin", bound is not None, "chưa mesh nào skin vào rig"),
        ("Shape key khuôn mặt", keyed, "chưa có shape key nào"),
    ]


# Buoc TUY CHON: robot, thu, dao cu khong co mat nen ca vung lan shape key deu
# co the bo. Danh dau tuy chon de panel dung nhac viec khong ai no.
OPTIONAL_STEPS = frozenset({5, 7})

# Buoc nao doi buoc nao.
#
# To vung (5) chi doi buoc 1: no la viec tren MESH, khong dinh gi den rig — mo
# som cho phep to xong truoc roi moi bind, va do la ca ly do no duoc tach ra.
# Bind (6) doi rig dung xong, con shape key (7) doi bind.
STEP_NEEDS = {1: (), 2: (1,), 3: (2,), 4: (3,), 5: (1,), 6: (4,), 7: (6,)}

# Bind xong la mo het. Doi so thu tu cac buoc thi sua o day, dung go so 5 vao
# giua `step_visible` nhu truoc — lan them buoc "To vung" vao da tro sai mot
# o va lam moi buoc mo ra sai luc.
BIND_STEP = 6


def step_visible(context, step, done=None):
    """Buoc `step` co duoc hien khong.

    Bind xong roi thi mo het: luc do rig dang duoc dung that, khong con la viec
    lam theo thu tu nua. Nho ve nay ma rig lam xong tu truoc (`3.0_Rig` chang
    han, khong he co bo ref nao) van thay day du bang dieu khien chu khong bi
    khoa lai chi vi thieu bo ref.
    """
    if done is None:
        done = [d for _n, d, _h in build_progress(context)]
    if done[BIND_STEP - 1]:
        return True
    return all(done[index - 1] for index in STEP_NEEDS.get(step, ()))


def draw_progress(layout, context):
    steps = build_progress(context)
    done = [d for _n, d, _h in steps]
    box = layout.box()
    column = box.column(align=True)
    column.scale_y = 0.85
    for index, (name, ok, hint) in enumerate(steps, start=1):
        row = column.row(align=True)
        if ok:
            row.label(text="%d. %s" % (index, name), icon='CHECKMARK')
        elif not step_visible(context, index, done):
            row.label(text="%d. %s" % (index, name), icon='LOCKED')
        elif index in OPTIONAL_STEPS:
            # Buoc tuy chon chua lam KHONG phai viec con no — dung dau nhac
            # viec, khong thi nguoi ta tuong minh bo sot.
            row.label(text="%d. %s (tuy chon)" % (index, name), icon='DOT')
        else:
            row.label(text="%d. %s  <- %s" % (index, name, hint), icon='PLAY')


class SRP_OT_eye_add(bpy.types.Operator):
    """Thêm một nhãn cầu rời vào danh sách"""
    bl_idname = "srp.eye_add"
    bl_label = "Thêm nhãn cầu"
    bl_options = {'REGISTER', 'UNDO'}

    side: EnumProperty(name="Bên", default='L',
                       items=(('L', "Trái", ""), ('R', "Phải", "")))

    def execute(self, context):
        settings = context.scene.srp_generate
        entry = settings.eyes.add()
        entry.side = self.side
        settings.eye_index = len(settings.eyes) - 1
        return {'FINISHED'}


class SRP_OT_eye_remove(bpy.types.Operator):
    """Bỏ một nhãn cầu khỏi danh sách"""
    bl_idname = "srp.eye_remove"
    bl_label = "Bỏ nhãn cầu"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(default=-1)

    def execute(self, context):
        settings = context.scene.srp_generate
        index = self.index if self.index >= 0 else len(settings.eyes) - 1
        if 0 <= index < len(settings.eyes):
            settings.eyes.remove(index)
            settings.eye_index = min(settings.eye_index, len(settings.eyes) - 1)
        return {'FINISHED'}


class SRP_OT_eye_migrate(bpy.types.Operator):
    """Chuyển hai ô chọn cũ sang danh sách"""
    bl_idname = "srp.eye_migrate"
    bl_label = "Chuyển sang danh sách"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(legacy_eyes(context))

    def execute(self, context):
        settings = context.scene.srp_generate
        for side, obj in legacy_eyes(context):
            entry = settings.eyes.add()
            entry.side = side
            entry.mesh = obj
        settings.eye_L = settings.eye_R = None
        self.report({'INFO'}, "Đã chuyển %d nhãn cầu sang danh sách"
                    % len(settings.eyes))
        return {'FINISHED'}


class SRP_OT_face_mesh_add(bpy.types.Operator):
    """Thêm một mesh mặt rời (răng, lưỡi, lông mày) vào danh sách"""
    bl_idname = "srp.face_mesh_add"
    bl_label = "Thêm mesh mặt"
    bl_options = {'REGISTER', 'UNDO'}

    role: EnumProperty(name="Vai trò", default='TEETH', items=FACE_ROLES)

    def execute(self, context):
        settings = context.scene.srp_generate
        entry = settings.face_meshes.add()
        entry.role = self.role
        return {'FINISHED'}


class SRP_OT_face_mesh_remove(bpy.types.Operator):
    """Bỏ một mesh mặt rời khỏi danh sách"""
    bl_idname = "srp.face_mesh_remove"
    bl_label = "Bỏ mesh mặt"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(default=-1)

    def execute(self, context):
        settings = context.scene.srp_generate
        index = self.index if self.index >= 0 else len(settings.face_meshes) - 1
        if 0 <= index < len(settings.face_meshes):
            settings.face_meshes.remove(index)
        return {'FINISHED'}


def draw_face_meshes(layout, context):
    """Danh sach mesh rang / luoi / long may — cung kieu voi danh sach mat."""
    settings = context.scene.srp_generate
    rig = rigdef.active_rig(context)
    box = layout.box()
    box.label(text="Răng, lưỡi, lông mày rời (tuỳ chọn)", icon='MESH_DATA')
    for index, entry in enumerate(settings.face_meshes):
        row = box.row(align=True)
        row.prop(entry, "role", text="")
        row.prop(entry, "mesh", text="")
        # In ra xuong se nhan mesh nay, nhu danh sach mat in ten xuong mat.
        sub = row.row(align=True)
        sub.enabled = False
        bones = face_role_bones(rig, entry.role) if rig is not None else []
        sub.label(text="%d xương" % len(bones) if rig is not None else "—")
        op = row.operator("srp.face_mesh_remove", text="", icon='X')
        op.index = index

    row = box.row(align=True)
    for key, label, _desc in FACE_ROLES:
        op = row.operator("srp.face_mesh_add", text=label, icon='ADD')
        op.role = key


def draw_target(layout, context):
    settings = context.scene.srp_generate
    layout.prop(settings, "target_mesh")
    layout.prop(settings, "rig_name")

    box = layout.box()
    box.label(text="Nhãn cầu rời (tuỳ chọn)", icon='MESH_UVSPHERE')

    # In thang TEN XUONG ra tung dong. Ghep mesh voi xuong theo THU TU trong
    # danh sach, nen khong noi ra la bat nguoi dung doan.
    pairs = eyeball_meshes(context)
    for index, entry in enumerate(settings.eyes):
        row = box.row(align=True)
        row.prop(entry, "side", text="")
        row.prop(entry, "mesh", text="")
        bone = next((b for b, o in pairs if o is entry.mesh), None)
        sub = row.row(align=True)
        sub.enabled = False
        sub.label(text=bone or "—")
        op = row.operator("srp.eye_remove", text="", icon='X')
        op.index = index

    row = box.row(align=True)
    op = row.operator("srp.eye_add", text="Thêm mắt trái", icon='ADD')
    op.side = 'L'
    op = row.operator("srp.eye_add", text="Thêm mắt phải", icon='ADD')
    op.side = 'R'

    old = legacy_eyes(context)
    if old:
        warn = box.column(align=True)
        warn.label(text="Đang dùng 2 ô kiểu cũ: %s"
                        % ", ".join(o.name for _s, o in old), icon='INFO')
        warn.operator("srp.eye_migrate", icon='FORWARD')

    draw_face_meshes(layout, context)


def draw_skeleton(layout, context):
    ref = refrig.find_ref(context)
    column = layout.column(align=True)
    column.enabled = ref is not None and not refrig.missing_core(ref)
    column.scale_y = 1.4
    column.operator("srp.generate", icon='ARMATURE_DATA')

    # Da co rig: sua bo ref roi day vao CHINH rig do, khong dung rig moi.
    if ref is not None and rigdef.active_rig(context) is not None:
        layout.operator("srp.ref_apply", icon='FILE_REFRESH')


def draw_bind(layout, context):
    row = layout.row()
    row.scale_y = 1.4
    row.operator("srp.bind", icon='MOD_ARMATURE')

    # Chi hien khi CO chuyen that: xuong cong phu kien ma van giu trong so.
    # Im lang luc moi thu on, va noi ro so lieu luc khong on.
    rig = rigdef.active_rig(context)
    stray = stray_mounts(context, rig) if rig is not None else []
    if stray:
        box = layout.box()
        box.alert = True
        for mesh, name, count in stray:
            box.label(text="%s kéo %d vertex của %s" % (name, count, mesh.name),
                      icon='ERROR')
        box.operator("srp.free_mounts", icon='UNLINKED')

    if refrig.find_ref(context) is not None:
        layout.label(text="Bind xong sẽ xoá bộ ref (dựng lại được ở bước 2)", icon='TRASH')


def register_extra():
    bpy.types.Scene.srp_generate = PointerProperty(type=SRP_GenerateSettings)


def unregister_extra():
    try:
        del bpy.types.Scene.srp_generate
    except AttributeError:
        pass


CLASSES = (SRP_EyeMesh, SRP_FaceMesh, SRP_GenerateSettings, SRP_OT_generate,
           SRP_OT_bind, SRP_OT_free_mounts, SRP_OT_widget_assign,
           SRP_OT_eye_add, SRP_OT_eye_remove, SRP_OT_eye_migrate,
           SRP_OT_face_mesh_add, SRP_OT_face_mesh_remove)
