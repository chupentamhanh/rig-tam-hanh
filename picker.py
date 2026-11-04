"""Picker: bam chon xuong theo so do nguoi, ngay trong N-panel.

Bo cuc theo kieu SOI GUONG — control ben trai cua nhan vat (.L) nam ben PHAI
panel, dung nhu khi dung doi dien nhin vao. Nhan nut van ghi ro .L/.R nen
khong the nham.

Bon bang:
    Picker          — than nguoi: so do co dinh cho bo xuong loi
    Picker > Ban tay— 5 ngon x 2 ben, va chon theo dot de nam tay
    Picker > Mat    — ham, mat, mi, moi... neu rig co
    Picker > Con lai— MOI control chua nut nao nhan, sinh thang tu rig

Bang cuoi la cai bao dam "day du xuong". Bo ref cho phep them chuoi bo tro
(duoi, tai, canh...) va them tay/chan thu N, ma mot so do go cung khong the
biet truoc. Thay vi doan, picker DO lai: quet control dang hien, tru di
nhung gi da co nut, phan du bay ra "Con lai" — khong xuong nao rot lai duoc.

Cac hang tay/chan viet theo ten GOC (`Shoulder`, khong phai `Shoulder.{s}`);
so thu tu chi va hau to ben do `rigdef.bone_name()` chen vao luc ve. Nho vay
nhan vat bon tay sau chan co du nut, thay vi chi chi thu nhat moi ben.
"""

import bpy
from bpy.props import BoolProperty, StringProperty

from . import rigdef

SEPARATOR = ","


def resolve(rig, spec, side=None, inst=1):
    """Doi mot spec thanh danh sach ten xuong CO THAT tren rig.

    Phan tu ket thuc bang '*' la tien to, con lai la ten chinh xac. Ten trong
    spec la ten GOC — so thu tu chi va hau to ben do `rigdef` ghep vao, chu
    picker khong tu noi chuoi: doi quy uoc ten mot cho ma picker ghep kieu
    khac thi no tro truot va khong co gi bao loi, chi la nut tu xam di.
    """
    names = rig.data.bones
    out = []
    for item in spec:
        prefix = item.endswith("*")
        full = rigdef.bone_name(item[:-1] if prefix else item, inst, side)
        if prefix:
            out.extend(bone.name for bone in names if bone.name.startswith(full))
        elif full in names:
            out.append(full)
    return out


def is_pickable(rig, bone_name):
    """Xuong co thuc su bam duoc khong — an roi thi chon cung nhu khong."""
    bone = rig.data.bones.get(bone_name)
    if bone is None or bone.hide:
        return False
    collections = bone.collections
    if not len(collections):
        return True
    return any(collection.is_visible for collection in collections)


def usable(rig, spec, side=None, inst=1):
    return [n for n in resolve(rig, spec, side, inst) if is_pickable(rig, n)]


def is_control(rig, bone_name):
    """Xuong nay co phai control khong.

    Dung dung mot dinh nghia voi nut "Tat ca control": co custom shape la
    control. Hai cho hieu khac nhau thi "Tat ca control" chon duoc mot xuong
    ma khong bang nao liet ke no — dung kieu thieu sot kho lan ra nhat.
    """
    pose_bone = rig.pose.bones.get(bone_name)
    return pose_bone is not None and pose_bone.custom_shape is not None


# ------------------------------------------------------------ bo cuc than

# (nhan, spec) — spec viet bang ten GOC, xem `resolve`.
# Nhan phai ngan: cot trong N-panel hep, dai qua la bi cat cut thanh
# "Tay tren ..." va khong con doc duoc gi.
ARM_ROWS = (
    ("Vai", ("Shoulder",)),
    ("Bắp tay", ("BicepFK",)),
    ("Cẳng tay", ("ForearmFK",)),
    ("Bàn tay", ("Hand_Master_FK",)),
    ("IK tay", ("ArmIK",)),
    ("Pole khuỷu", ("ElbowPole",)),
    ("Ngón tay", ("Palm*", "Index*", "Middle*", "Ring*", "Pinky*", "Thumb*")),
)

LEG_ROWS = (
    ("Đùi", ("ThighFK",)),
    ("Cẳng chân", ("ShinFK",)),
    ("Bàn chân", ("FootFK",)),
    ("IK chân", ("LegIK",)),
    ("Pole gối", ("Pole",)),
    ("Ngón chân", ("Toe",)),
    # Chuoi lan chan — nut tu mo di neu rig khong co (rig cu chua co)
    ("Gót", ("Heel",)),
    ("Mũi chân", ("ToeTip",)),
    ("Ức bàn chân", ("Ball",)),
)

SPINE_ROWS = (
    ("Đầu", ("Head",)),
    ("Cổ", ("Neck", "Neck.001", "Neck.002")),
    ("Ngực", ("Spine.003",)),
    ("Lưng trên", ("Spine.002",)),
    ("Lưng giữa", ("Spine.001",)),
    ("Lưng dưới", ("Spine",)),
    ("Hông", ("Hips",)),
    ("Hip Master", ("Hip_Master",)),
    ("Root", ("Root",)),
)

# Ngon tay, theo thu tu tu ngon cai ra. Ten GOC cua DOT DAU moi ngon.
FINGER_ROWS = (
    ("Cái", "Thumb"),
    ("Trỏ", "Index"),
    ("Giữa", "Middle"),
    ("Nhẫn", "Ring"),
    ("Út", "Pinky"),
)

# Chon ca mot vong dot tren nam ngon — nam tay/xoe tay la keo theo vong,
# khong phai theo tung ngon.
PHALANX_ROWS = (("Đốt gốc", 0), ("Đốt giữa", 1), ("Đốt ngọn", 2))

# Moi nhom gom ca ten cua ho rig goc lan ten bo mat Kid_Rig ma bo sinh rig dung
# ra (`Eyelid_Upper.L`, `Lip_Upper.L.001`, `Tongue.002`...).
FACE_GROUPS = (
    ("Chân mày", ("EyeBrow_Ctrl*", "Eyebrow*")),
    ("Mi trên", ("UpperEyeLids_Ctrl*", "Upper_EyeLid*", "Eyelid_Upper*")),
    ("Mi dưới", ("LowerEyeLids_Ctrl*", "Lower_EyeLid*", "Eyelid_Lower*")),
    ("Khoé mi", ("EyeLids_Ctrl*", "Eyelid_Inner*", "Eyelid_Outer*")),
    # `Eye.L/R` va `Jaw` la xuong do chinh addon sinh ra (bo sinh rig, hoac nut
    # "Them xuong ham & xuong mat"). Ba ten con lai la cua ho rig goc.
    ("Nhìn mắt", ("Eye.L", "Eye.R", "EyeLook", "Eye_Target.L", "Eye_Target.R")),
    ("Nhãn cầu", ("Eyeball.L", "Eyeball.R")),
    ("Môi trên", ("UpperLip_Ctrl*", "UpperLips*", "Lip_Upper*")),
    ("Môi dưới", ("LowerLip_Ctrl*", "LowerLips*", "Lip_Lower*")),
    ("Hàm", ("Jaw", "Jaw_Base", "LowerJaw")),
    ("Răng", ("UpperTeeth", "LowerTeeth", "Teeth_Upper", "Teeth_Lower")),
    ("Lưỡi", ("Tongue*",)),
    ("Má", ("Cheek.L", "Cheek.R")),
    ("Mũi", ("Nose*",)),
    ("Tai", ("Ear.L", "Ear.R")),
    ("Viền mặt", ("Face_Border*",)),
)


FACE_EXACT = tuple(sorted({name for _label, spec in FACE_GROUPS
                           for name in spec if not name.endswith("*")}))
FACE_PREFIX = tuple(sorted({name[:-1] for _label, spec in FACE_GROUPS
                            for name in spec if name.endswith("*")}))


def has_face(rig):
    """Rig co xuong mat bam duoc khong.

    Truoc day ham nay do ba tien to go cung (`EyeBrow`, `Eyebrow`, `Jaw_Base`)
    — ten cua ho rig goc trong project. Rig do addon sinh ra dat `Jaw` va
    `Eye.L/R`, khong trung tien to nao, nen CA bang mat bien mat du ba xuong
    deu dang hien va bam duoc. Gio do thang bang FACE_GROUPS, tuc cai gi ve
    duoc thi mo, khong con hai danh sach de lech nhau.

    Ham nay nam trong `poll()` nen chay lai moi lan ve lai N-panel, ke ca khi
    dang keo chuot trong viewport. Tra tu dien truoc (gan nhu mien phi, va du
    trung cho ca hai ho rig), con quet tien to thi quet MOT lan voi ca tuple —
    `startswith` nhan tuple, khong can moi tien to mot vong.
    """
    bones = rig.data.bones
    for name in FACE_EXACT:
        if name in bones and is_pickable(rig, name):
            return True
    for bone in bones:
        if bone.name.startswith(FACE_PREFIX) and is_pickable(rig, bone.name):
            return True
    return False


def has_fingers(rig):
    """Co xuong ngon nao khong — hoi muoi cai ten, khong quet ca rig.

    Ban `limb_slots()` dung duoc nhung no dung `limbs_for()`, tuc dung 32 doi
    tuong Limb va vai tram phep tra ten cho mot cau tra loi dung/sai chay o
    moi lan ve lai panel.
    """
    bones = rig.data.bones
    for _label, base in FINGER_ROWS:
        for side in rigdef.SIDES:
            if rigdef.bone_name(base, 1, side) in bones:
                return True
    return False


# ------------------------------------------------------------------- chi

def limb_slots(rig, kind=None):
    """[(loai, so thu tu)] cac chi co that tren rig, giu thu tu cua rigdef."""
    seen, out = set(), []
    for limb in rigdef.limbs_for(rig):
        key = (limb.kind, limb.inst)
        if key in seen or (kind is not None and limb.kind != kind):
            continue
        seen.add(key)
        out.append(key)
    return out


def rows_for(kind):
    return ARM_ROWS if kind == 'ARM' else LEG_ROWS


def slot_label(kind, inst):
    template = rigdef.TEMPLATE_BY_KIND[kind]
    return template['label'] if inst <= 1 else "%s #%d" % (template['label'], inst)


def finger_bones(rig, base, side, inst=1):
    """Ba dot cua mot ngon, KEM xuong Palm keo no.

    Palm nao thuoc ngon nao thi hoi rig qua quan he cha con chu khong tra
    theo so thu tu: `_hand_spec` xep tu ngon ut nen `Palm.002` la ngon giua —
    mot thu tu khong ai doan ra, va rig lam tay co the xep kieu khac han.
    """
    names = resolve(rig, (base + "*",), side, inst)
    if not names:
        return []
    root = rig.data.bones.get(rigdef.bone_name(base, inst, side))
    parent = root.parent if root is not None else None
    if parent is not None and parent.name.split(".")[0].startswith("Palm"):
        names.insert(0, parent.name)
    return names


def phalanx_bones(rig, index, side, inst=1):
    """Cung mot dot tren ca nam ngon: 0 = dot goc, 2 = dot ngon."""
    out = []
    for _label, base in FINGER_ROWS:
        name = rigdef.bone_name(base, inst, side)
        if index:
            name = "%s.%03d" % (name, index)
        if name in rig.data.bones:
            out.append(name)
    return out


def hand_bones(rig, side, inst=1):
    out = []
    for _label, base in FINGER_ROWS:
        out.extend(finger_bones(rig, base, side, inst))
    return out


def quick_sets(rig):
    """Hai nut loc nhanh, SINH tu cac chi that thay vi liet ke cung.

    Danh sach cung chi biet chi thu nhat moi ben; nhan vat bon tay bam
    "Chi FK" thi hai tay sau khong duoc chon.
    """
    fk, ik = [], []
    for limb in rigdef.limbs_for(rig):
        fk.extend(limb.fk)
        ik.append(limb.ctrl)
        ik.append(limb.pole)
        ik.extend(limb.roll)
    return (("Chỉ IK", ik), ("Chỉ FK", fk))


# --------------------------------------------------------------- con lai

def covered(rig):
    """Moi ten xuong ma cac bang co dinh da co nut."""
    out = set()
    for _label, spec in SPINE_ROWS:
        out.update(resolve(rig, spec))
    for _label, spec in FACE_GROUPS:
        out.update(resolve(rig, spec))
    for kind, inst in limb_slots(rig):
        for _label, spec in rows_for(kind):
            for side in rigdef.SIDES:
                out.update(resolve(rig, spec, side, inst))
    return out


def _stem(name):
    """`Tail.003` -> `Tail`, `Palm.L.001` -> `Palm.L`, `Eye.L` -> `Eye.L`."""
    head, _, last = name.rpartition(".")
    return head if head and last.isdigit() else name


def leftover_groups(rig):
    """[(ten goc, [ten xuong])] — control dang hien chua nut nao nhan.

    Gom theo goc de mot cai duoi sau dot khong bien thanh sau hang roi rac.
    """
    known = covered(rig)
    groups, order = {}, []
    for bone in rig.data.bones:
        name = bone.name
        if name in known or not is_pickable(rig, name) or not is_control(rig, name):
            continue
        key = _stem(name)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(name)
    return [(key, groups[key]) for key in order]


# -------------------------------------------------------------- operator

class SRP_OT_pick(bpy.types.Operator):
    "Chọn xương. Giữ Shift để chọn thêm"
    bl_idname = "srp.pick"
    bl_label = "Chọn xương"
    bl_options = {'REGISTER', 'UNDO'}

    bones: StringProperty(name="Danh sách xương", default="")
    extend: BoolProperty(name="Chọn thêm", default=False)
    deselect_all: BoolProperty(name="Bỏ chọn hết", default=False)
    all_controls: BoolProperty(name="Mọi control đang hiện", default=False)

    @classmethod
    def poll(cls, context):
        return rigdef.active_rig(context) is not None

    def invoke(self, context, event):
        self.extend = event.shift
        return self.execute(context)

    def execute(self, context):
        rig = rigdef.active_rig(context)
        if rig is None:
            return {'CANCELLED'}

        # Chon xuong chi co nghia trong Pose Mode — tu chuyen cho do vuong.
        if context.mode != 'POSE':
            context.view_layer.objects.active = rig
            rig.select_set(True)
            try:
                bpy.ops.object.mode_set(mode='POSE')
            except RuntimeError:
                self.report({'ERROR'}, "Không vào được Pose Mode")
                return {'CANCELLED'}

        # Blender 5.0 bo `Bone.select`; chon xuong o Pose Mode nam tren PoseBone.
        if self.deselect_all:
            for pose_bone in rig.pose.bones:
                pose_bone.select = False
            return {'FINISHED'}

        if self.all_controls:
            wanted = [b.name for b in rig.data.bones if is_control(rig, b.name)]
        else:
            wanted = [n for n in self.bones.split(SEPARATOR) if n]

        pickable = [n for n in wanted if is_pickable(rig, n)]
        hidden = len(wanted) - len(pickable)

        if not self.extend:
            for pose_bone in rig.pose.bones:
                pose_bone.select = False

        last = None
        for name in pickable:
            rig.pose.bones[name].select = True
            last = name
        if last is not None:
            rig.data.bones.active = rig.data.bones[last]

        if not pickable:
            self.report({'WARNING'}, "Không có xương nào đang hiện để chọn"
                        + (" (%d cai bi an)" % hidden if hidden else ""))
        elif hidden:
            self.report({'INFO'}, "Chọn %d xương, bỏ qua %d cái đang ẩn"
                        % (len(pickable), hidden))
        return {'FINISHED'}


# ----------------------------------------------------------------- panel

def _pick(layout, rig, label, names):
    """Mot nut picker. Sang len khi moi xuong trong nhom dang duoc chon.

    Khong con xuong nao bam duoc thi ve NUT MO chu khong ve chu tran: cong
    tac FK/IK an nua so hang di la binh thuong, nhung chu tran lam luoi nut
    thung lo, nhin y het picker bi thieu xuong. Nut mo doc la "dang khong
    dung duoc", dung cai ma no muon noi.
    """
    if not names:
        layout = layout.row()
        layout.enabled = False
    selected = bool(names) and all(rig.pose.bones[n].select for n in names)
    op = layout.operator("srp.pick", text=label, depress=selected)
    op.bones = SEPARATOR.join(names)
    op.deselect_all = False
    op.all_controls = False


def _cell(layout, rig, label, spec, side=None, inst=1):
    _pick(layout, rig, label, usable(rig, spec, side, inst))


def _sides_header(layout, middle=True):
    """Ghi ben o dau cot mot lan, thay vi nhet ".L"/".R" vao tung nut —
    cot hep san, them hai ky tu la nhan bi cat het."""
    row = layout.row(align=True)
    for text in (("Phải  .R", "", "Trái  .L") if middle else ("Phải  .R", "Trái  .L")):
        cell = row.column(align=True)
        cell.alignment = 'CENTER'
        cell.label(text=text)


def _three(layout, rig, left, center, right):
    """Mot hang: cot trai (.R), cot giua, cot phai (.L) — bo cuc soi guong.

    Chi dung cho so do nguoi, tuc chi THU NHAT moi ben; chi thu hai tro di ve
    bang bang rieng qua `_two`.
    """
    row = layout.row(align=True)
    for column_spec, side in ((left, 'R'), (center, None), (right, 'L')):
        column = row.column(align=True)
        if column_spec is None:
            column.label(text="")
            continue
        label, spec = column_spec
        _cell(column, rig, label, spec, side)


def _two(layout, rig, label, spec, inst=1):
    """Hai nut .R | .L cho mot hang, dung o cac bang khong co cot giua."""
    row = layout.row(align=True)
    for side in ('R', 'L'):
        _cell(row.column(align=True), rig, label, spec, side, inst)


def draw_body(layout, context, rig):
    row = layout.row(align=True)
    op = row.operator("srp.pick", text="Tất cả control")
    op.all_controls, op.deselect_all, op.bones = True, False, ""
    op = row.operator("srp.pick", text="Bỏ chọn")
    op.deselect_all, op.all_controls, op.bones = True, False, ""

    row = layout.row(align=True)
    for label, names in quick_sets(rig):
        _pick(row.row(align=True), rig, label,
              [n for n in names if is_pickable(rig, n)])

    layout.separator()
    box = layout.box()
    _sides_header(box)

    # dau -> co -> nguc, kem vai va tay hai ben
    column = box.column(align=True)
    _three(column, rig, None, SPINE_ROWS[0], None)          # Dau
    _three(column, rig, None, SPINE_ROWS[1], None)          # Co
    _three(column, rig, ARM_ROWS[0], SPINE_ROWS[2], ARM_ROWS[0])
    for index, spine in enumerate(SPINE_ROWS[3:7]):         # lung + hong
        arm = ARM_ROWS[index + 1] if index + 1 < len(ARM_ROWS) else None
        _three(column, rig, arm, spine, arm)
    _three(column, rig, ARM_ROWS[5], SPINE_ROWS[7], ARM_ROWS[5])   # pole khuyu
    _three(column, rig, ARM_ROWS[6], SPINE_ROWS[8], ARM_ROWS[6])   # ngon tay + Root

    column.separator()
    for leg in LEG_ROWS:
        _three(column, rig, leg, None, leg)

    # Chi thu hai tro di khong nhet vua so do nguoi — moi cai mot bang rieng.
    for kind, inst in limb_slots(rig):
        if inst <= 1:
            continue
        extra = layout.box()
        extra.label(text=slot_label(kind, inst))
        _sides_header(extra, middle=False)
        column = extra.column(align=True)
        for label, spec in rows_for(kind):
            _two(column, rig, label, spec, inst)


def draw_hand(layout, context, rig):
    slots = limb_slots(rig, 'ARM')
    if not slots:
        layout.label(text="rig không có tay", icon='INFO')
        return
    for _kind, inst in slots:
        box = layout.box() if len(slots) > 1 else layout
        if len(slots) > 1:
            box.label(text=slot_label('ARM', inst))
        _sides_header(box, middle=False)
        column = box.column(align=True)

        row = column.row(align=True)
        for side in ('R', 'L'):
            _pick(row.column(align=True), rig, "Cả bàn tay",
                  [n for n in hand_bones(rig, side, inst) if is_pickable(rig, n)])
        _two(column, rig, "Lòng bàn tay", ("Palm*",), inst)

        column.separator()
        for label, base in FINGER_ROWS:
            row = column.row(align=True)
            for side in ('R', 'L'):
                _pick(row.column(align=True), rig, label,
                      [n for n in finger_bones(rig, base, side, inst)
                       if is_pickable(rig, n)])

        column.separator()
        for label, index in PHALANX_ROWS:
            row = column.row(align=True)
            for side in ('R', 'L'):
                _pick(row.column(align=True), rig, label,
                      [n for n in phalanx_bones(rig, index, side, inst)
                       if is_pickable(rig, n)])


def draw_face(layout, context, rig):
    column = layout.column(align=True)
    rows = [(label, usable(rig, spec)) for label, spec in FACE_GROUPS]
    rows = [item for item in rows if item[1]]
    for index in range(0, len(rows), 2):
        row = column.row(align=True)
        for label, names in rows[index:index + 2]:
            _pick(row.row(align=True), rig, label, names)


def draw_extra(layout, context, rig):
    groups = leftover_groups(rig)
    if not groups:
        layout.label(text="không còn control nào ngoài bảng", icon='CHECKMARK')
        return
    column = layout.column(align=True)
    for label, names in groups:
        row = column.row(align=True)
        if len(names) == 1:
            _pick(row, rig, label, names)
            continue
        _pick(row, rig, "%s x%d" % (label, len(names)), names)
        for order, name in enumerate(names, 1):
            _pick(row, rig, str(order), [name])


CLASSES = (SRP_OT_pick,)
