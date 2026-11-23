"""Dinh nghia rig — nguon su that duy nhat cho toan bo addon.

Moi module khac hoi o day thay vi tu doan ten bone. Doi convention thi
sua mot cho nay, khong phai luc tim trong bay file.

`generate.py` dung chinh file nay lam ban ve khi dung rig moi, nen rig vua
sinh ra la moi cong cu (snap, kham rig, picker, widget, onion) chay duoc
ngay — khong co ban dac ta thu hai de lech nhau.
"""

import math

import bpy

SIDES = ('L', 'R')
SIDE_WORD = {'L': "Left", 'R': "Right"}
# Chu HIEN RA cho nguoi doc. Tach han khoi `SIDE_WORD` vi `SIDE_WORD` di
# vao TEN custom property va ten bone collection ("Left Arm FK/IK") — nhung
# ten do nam trong rig va co driver tro toi, doi mot chu la hong het rig cu.
SIDE_LABEL = {'L': "trái", 'R': "phải"}

# So chi TOI DA cung loai cung ben. Nhan vat bon tay, sau chan, duoi doi... deu
# nam gon trong day. Con la can tren cua vong do trong `limbs_for()` — khong
# phai gioi han thiet ke, nang len khong hong gi.
MAX_INSTANCE = 8


def inst_name(base, inst):
    """`Bicep` -> `Bicep`, `Bicep_2`, `Bicep_3`...

    Gach duoi chu khong phai `.001`: Blender tu danh so bang `.001` khi trung
    ten, nen dung dau cham thi khong phan biet duoc "tay thu hai" voi "ban sao
    do Blender de ra". Chi thu nhat giu nguyen ten cu — rig lam tu truoc
    (`3.0_Rig` chang han) van khop y nguyen.
    """
    return base if inst <= 1 else "%s_%d" % (base, inst)


def bone_name(base, inst=1, side=None):
    """Ten day du. Hau to ben LUON o cuoi de Blender lat trai/phai duoc."""
    name = inst_name(base, inst)
    return name + "." + side if side else name

# Ten chuan cho hai constraint blend tren moi bone deform.
CON_IK = "IK_Follow"
CON_FK = "FK_Follow"
# Bone cuoi chuoi IK bam theo huong control. Xem `ensure_tip_follow`.
CON_TIP = "Ctrl_Follow"

# Ten cu do Blender tu dat — build.py doi sang ten chuan.
LEGACY_CON = ("Copy Rotation", "Copy Rotation.001", "Copy Rotation.002")


LIMB_TEMPLATES = (
    dict(
        kind='ARM',
        label="Tay",
        deform=("Bicep", "Forearm", "Hand_Master"),
        fk=("BicepFK", "ForearmFK", "Hand_Master_FK"),
        ik=("BicepIK", "ForearmIK", "HandIK"),
        ctrl="ArmIK",
        pole="ElbowPole",
        solver="ForearmIK",   # bone mang constraint IK
        roll=(),
        prop="{word} Arm{n} FK/IK",
        collection_fk="{word} Arm{n} FK",
        collection_ik="{word} Arm{n} IK",
        default_switch=0.0,        # tay dung FK lam mac dinh
        pole_angle=math.pi,        # xem ghi chu POLE_ANGLE ben duoi
    ),
    dict(
        kind='LEG',
        label="Chân",
        deform=("Thigh", "Shin", "Foot"),
        fk=("ThighFK", "ShinFK", "FootFK"),
        ik=("ThighIK", "ShinIK", "FootIK"),
        ctrl="LegIK",
        pole="Pole",
        solver="ShinIK",
        # Chuoi lan chan (foot roll), neu rig co. Chung nam GIUA control ma
        # animator cam va dich that su cua constraint IK:
        #   LegIK -> Heel -> ToeTip -> Ball -> AnkleIK
        # O rest tat ca deu identity nen AnkleIK trung dung co chan, tuc rig
        # co hay khong co foot roll thi ket qua o rest van y het nhau.
        roll=("Heel", "ToeTip", "Ball", "AnkleIK"),
        prop="{word} Leg{n} FK/IK",
        collection_fk="{word} Leg{n} FK",
        collection_ik="{word} Leg{n} IK",
        default_switch=1.0,        # chan dung IK: 100% animation chan nam tren LegIK
        pole_angle=math.pi / 2.0,
    ),
)

TEMPLATE_BY_KIND = {t['kind']: t for t in LIMB_TEMPLATES}

# Kiểu chân. Chân chó / dê về giải phẫu là chân người ĐI BẰNG NGÓN: xương `Foot`
# là đoạn bàn dài dựng đứng (khớp đầu là cổ chân sau, "hock"), `Toe` là bàn chân
# / móng chạm đất. Giữ nguyên ba tên Thigh-Shin-Foot nên FK/IK, weight, retarget
# và Humanoid dùng chung một đường. Khác duy nhất: control IK đặt ở chỗ chạm đất.
TAG_LEG = "srp_leg"
TAG_CHAIN = "srp_chain"     # xuong phu nguoi dung them (tai, duoi, canh...), luon xuat sang game
LEG_TYPES = (
    ('HUMAN', "Người", "Đi bằng cả bàn chân, gót chạm đất"),
    ('PAW', "Chó / thú", "Đi bằng ngón: cổ chân sau nhấc cao, gối sau gập ngược"),
    ('HOOF', "Dê / móng guốc", "Đi trên móng: cổ chân sau nhấc cao, bàn thẳng đứng"),
)

# POLE_ANGLE: gia tri nay phu thuoc roll cua xuong nen khong the doan chac.
# Rig goc trong project dang lech: tay trai 180 do, tay phai 0 do, hai chan
# deu 90 do — dau vet mirror sai. Day chi la MAC DINH luc sinh rig; sau khi
# tao pose gap thi chay `srp.calibrate_pole` de do va sua cho dung.

# Hien collection theo dung influence that, khong theo nguong cung: o giua
# chung thi ca hai ben deu con tac dung nen phai thay duoc ca hai.
COLLECTION_FK_EXPR = "switch < 1.0"
COLLECTION_IK_EXPR = "switch > 0.0"

# Bone giu cac custom property cong tac.
PROP_BONE = "Root"

# Quy uoc cong tac. Doi hai so nay la doi nghia ca rig.
FK_VALUE = 0.0
IK_VALUE = 1.0


class Limb:
    """Mot chi da gan vao mot armature cu the."""

    __slots__ = ("kind", "label", "side", "inst", "deform", "fk", "ik",
                 "ctrl", "pole", "solver", "prop",
                 "collection_fk", "collection_ik", "default_switch", "pole_angle",
                 "roll", "toe", "toe_mch")

    def __init__(self, template, side, inst=1):
        self.kind = template['kind']
        self.side = side
        self.inst = inst
        self.label = "%s %s%s" % (template['label'], SIDE_LABEL[side],
                                  "" if inst <= 1 else " #%d" % inst)
        word = SIDE_WORD[side]
        # `{n}` la phan danh so chen vao ten prop va ten collection. Chi thu
        # nhat de trong, nen rig cu doc y nguyen ten cu.
        tag = "" if inst <= 1 else " %d" % inst

        def named(base):
            return bone_name(base, inst, side)

        self.deform = tuple(named(name) for name in template['deform'])
        self.fk = tuple(named(name) for name in template['fk'])
        self.ik = tuple(named(name) for name in template['ik'])
        self.ctrl = named(template['ctrl'])
        self.pole = named(template['pole'])
        self.solver = named(template['solver'])
        self.prop = template['prop'].format(word=word, n=tag)
        self.collection_fk = template['collection_fk'].format(word=word, n=tag)
        self.collection_ik = template['collection_ik'].format(word=word, n=tag)
        self.default_switch = template['default_switch']
        self.pole_angle = template['pole_angle']
        self.roll = tuple(named(name) for name in template['roll'])
        self.toe = named("Toe")
        self.toe_mch = named("ToeMch")

    def leg_type(self, rig):
        """'HUMAN' / 'PAW' / 'HOOF' -- ghi trên xương đùi lúc dựng rig."""
        if self.kind != 'LEG':
            return 'HUMAN'
        bone = rig.data.bones.get(self.deform[0])
        return bone.get(TAG_LEG, 'HUMAN') if bone is not None else 'HUMAN'

    def is_digitigrade(self, rig):
        return self.leg_type(rig) != 'HUMAN'

    def ik_target(self, rig):
        """Bone ma constraint IK tro toi.

        Co chuoi lan chan thi la bone cuoi chuoi do, khong thi chinh la
        control. Tach hai khai niem nay ra cho phep chen foot roll vao ma
        khong dong gi den snap hay calibrate — chung van lam viec voi `ctrl`.
        """
        if self.roll and self.roll[-1] in rig.pose.bones:
            return self.roll[-1]
        return self.ctrl

    def has_roll(self, rig):
        return bool(self.roll) and all(n in rig.pose.bones for n in self.roll)

    def collections(self):
        """[(ten collection, expression driver)] cho ca hai ben."""
        return ((self.collection_fk, COLLECTION_FK_EXPR),
                (self.collection_ik, COLLECTION_IK_EXPR))

    @property
    def name(self):
        """Khoa dinh danh, dung lam gia tri EnumProperty trong cac operator."""
        return "%s.%s%s" % (self.kind, self.side,
                            "" if self.inst <= 1 else ".%d" % self.inst)

    def bones(self):
        return self.deform + self.fk + self.ik + (self.ctrl, self.pole)

    def missing(self, rig):
        return [n for n in self.bones() if n not in rig.data.bones]

    def is_complete(self, rig):
        bones = rig.data.bones
        return all(name in bones for name in self.bones())

    # -- cong tac ---------------------------------------------------------

    def switch(self, rig):
        """Gia tri cong tac hien tai (0 = FK, 1 = IK), None neu thieu prop."""
        bone = rig.pose.bones.get(PROP_BONE)
        if bone is None or self.prop not in bone.keys():
            return None
        return float(bone[self.prop])

    def set_switch(self, rig, value):
        bone = rig.pose.bones.get(PROP_BONE)
        if bone is not None:
            bone[self.prop] = float(value)

    @property
    def prop_path(self):
        return 'pose.bones["%s"]["%s"]' % (PROP_BONE, self.prop)

    def con_path(self, bone_name, con_name):
        return 'pose.bones["%s"].constraints["%s"].influence' % (bone_name, con_name)

    # -- constraint -------------------------------------------------------

    def blend_pairs(self, rig):
        """[(pose_bone, con_ik, con_fk)] cho tung bone deform cua chi."""
        out = []
        for def_name, ik_name, fk_name in zip(self.deform, self.ik, self.fk):
            bone = rig.pose.bones.get(def_name)
            if bone is None:
                continue
            con_ik = con_fk = None
            for con in bone.constraints:
                if con.type != 'COPY_ROTATION' or not con.subtarget:
                    continue
                if con.subtarget == ik_name:
                    con_ik = con
                elif con.subtarget == fk_name:
                    con_fk = con
            out.append((bone, con_ik, con_fk))
        return out

    def ik_constraint(self, rig):
        bone = rig.pose.bones.get(self.solver)
        if bone is None:
            return None
        for con in bone.constraints:
            if con.type == 'IK':
                return con
        return None


def collection_path(armature, name):
    """Data path toi `is_visible` cua mot bone collection, None neu khong co.

    Thu ca `collections` (chi cap dau) lan `collections_all` (co long nhau)
    vi rig long collection thi path cap dau khong giai duoc.
    """
    for attr in ("collections", "collections_all"):
        path = '%s["%s"].is_visible' % (attr, name)
        try:
            armature.path_resolve(path)
        except (ValueError, KeyError):
            continue
        return path
    return None


def limbs_for(rig):
    """Cac chi day du bone tren `rig` — DO tu rig, khong liet ke cung.

    Truoc day ham nay tra ve dung 4 chi vi no duyet `LIMB_TEMPLATES x SIDES`.
    Nhan vat bon tay thi hai tay sau khong ai biet den: khong co cong tac
    FK/IK, khong driver, snap bo qua. Gio quet het `MAX_INSTANCE` so thu tu —
    quet HET chu khong dung o cho trong dau tien, vi xoa mot chi o giua la
    chuyen binh thuong va no khong duoc phep lam bien mat cac chi phia sau.
    """
    return [limb for limb in
            (Limb(t, s, i) for t in LIMB_TEMPLATES for s in SIDES
             for i in range(1, MAX_INSTANCE + 1))
            if limb.is_complete(rig)]


def all_limbs():
    return [Limb(t, s) for t in LIMB_TEMPLATES for s in SIDES]


def is_managed(obj):
    """True neu object la armature theo dung convention cua addon.

    Chi hoi chi THU NHAT moi ben, va thoat ngay khi thay mot chi day du. Ham
    nay chay trong `poll()` cua moi panel, tuc vai chuc lan moi lan ve lai man
    hinh, moi lan lai duyet het object trong file — goi `limbs_for()` o day la
    nhan so phep tra ten bone len 8 lan cho mot cau tra loi dung/sai.
    """
    if obj is None or obj.type != 'ARMATURE':
        return False
    return any(Limb(t, s, 1).is_complete(obj)
               for t in LIMB_TEMPLATES for s in SIDES)


def managed_rigs(context):
    """Moi armature theo convention co trong file.

    Dung ca `bpy.data` chu khong chi scene: append xong ma quen link vao
    scene thi rig van nam trong file va van can sua.
    """
    seen, out = set(), []
    scene = getattr(context, "scene", None)      # _RestrictContext khong co scene
    for source in ((scene.objects if scene else ()), bpy.data.objects):
        for obj in source:
            if obj.name not in seen and is_managed(obj):
                seen.add(obj.name)
                out.append(obj)
    return out


def active_rig(context):
    """Rig dang lam viec: object active, roi selected, roi rig dau tien.

    Sau khi append thuong co nhieu rig cung luc — tra ve cai dau tien con
    hon tra ve None, vi operator nao can quet het da co `managed_rigs()`.
    """
    obj = context.object
    if is_managed(obj):
        return obj
    for obj in context.selected_objects:
        if is_managed(obj):
            return obj
    # Uu tien rig DANG HIEN trong view layer. Rig nam trong collection bi
    # exclude thi nguoi dung khong nhin thay, ma depsgraph cung khong tinh —
    # panel tro vao no la vua kho hieu vua cho ra so lieu rac.
    found = managed_rigs(context)
    visible = [r for r in found if r.name in context.view_layer.objects]
    return (visible or found or [None])[0]


def limb_by_name(rig, name):
    for limb in limbs_for(rig):
        if limb.name == name:
            return limb
    return None


def limb_items(self, context):
    rig = active_rig(context)
    if rig is None:
        return [('NONE', "không có rig", "")]
    return [(l.name, l.label, "") for l in limbs_for(rig)]
