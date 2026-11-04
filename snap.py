"""Snap IK <-> FK.

Hinh hoc rig nay cho phep snap chinh xac, khong xap xi:

  * Chuoi IK va chuoi FK co rest geometry TRUNG KHIT chuoi deform
    (ThighIK.L == ThighFK.L == Thigh.L den tung so). Nen snap FK theo IK
    chi la gan lai matrix, khong can bu rest.
  * Constraint blend chay WORLD/WORLD/REPLACE — khop world rotation la du.
  * `FootIK <- LegIK` chay LOCAL_WITH_PARENT/LOCAL_OWNER_ORIENT, ma
    FootIK va FootFK cung rest, nen rotation local cua control IK chinh la
    rotation local cua bone FK cuoi chuoi. Copy thang gia tri quaternion.

Rieng pole thi khong co cong thuc dong kin (pole_angle la hang so cua rig,
lai lech nhau giua hai ben). Nen giai bang do — sua — do lai, hoi tu sau
2-3 vong, thay vi doan roi nhin bang mat.
"""

import math

import bpy
from bpy.props import EnumProperty, IntProperty, BoolProperty
from mathutils import Matrix

from . import compat, prefs, rigdef

POLE_TOLERANCE = 1e-4      # radian, ~0.006 do
POLE_MAX_PASSES = 6
ROT_TOLERANCE = 1e-5
ROT_MAX_PASSES = 4


def _wrap(angle):
    """Goi goc ve [-pi, pi].

    Bat buoc: `pole_angle` bi Blender kep trong +-pi. Cong them 180 do vao
    180 do thanh 360 roi bi kep nguoc ve 180 — sai so 180 do se khong bao gio
    sua duoc, va do lai la truong hop hay gap nhat vi hai ben tay guong nhau.
    """
    return ((angle + math.pi) % (2.0 * math.pi)) - math.pi


def _angle_off(quat):
    """Do lech cua mot quaternion so voi phep xoay khong, da xu ly double-cover."""
    angle = abs(quat.angle)
    return min(angle, abs(2.0 * math.pi - angle))


def _move_head(context, rig, name, position):
    """Doi vi tri head cua bone, giu nguyen rotation dang co."""
    bone = rig.pose.bones.get(name)
    if bone is None:
        return
    matrix = compat.evaluated(context, rig).pose.bones[name].matrix.copy()
    matrix.translation = position
    bone.matrix = matrix
    context.view_layer.update()


# ------------------------------------------------------------ FK <- IK

def snap_fk_to_ik(context, rig, limb):
    """Chuoi FK nhan lai pose ma IK dang tao ra. Chinh xac tuyet doi."""
    shot = compat.pose_snapshot(context, rig, limb.ik)
    for fk_name, ik_name in zip(limb.fk, limb.ik):
        matrix = shot.get(ik_name)
        bone = rig.pose.bones.get(fk_name)
        if matrix is None or bone is None:
            continue
        bone.matrix = matrix
        context.view_layer.update()   # con phai thay cha da doi truoc khi tinh
    return True


# ------------------------------------------------------------ IK <- FK

def _pole_error(context, rig, limb):
    """Goc lech giua dau goi IK va dau goi FK, quanh truc hong-co chan."""
    ev_rig = compat.evaluated(context, rig)
    try:
        hip = ev_rig.pose.bones[limb.fk[0]].matrix.translation.copy()
        fk_knee = ev_rig.pose.bones[limb.fk[1]].matrix.translation.copy()
        ik_knee = ev_rig.pose.bones[limb.ik[1]].matrix.translation.copy()
        ankle = ev_rig.pose.bones[limb.fk[1]].tail.copy()
    except KeyError:
        return None, None, None

    axis = ankle - hip
    if axis.length < 1e-6:
        return None, None, None
    axis.normalize()

    to_fk = (fk_knee - hip)
    to_ik = (ik_knee - hip)
    to_fk -= axis * to_fk.dot(axis)
    to_ik -= axis * to_ik.dot(axis)
    if to_fk.length < 1e-5 or to_ik.length < 1e-5:
        return None, None, None      # chi duoi thang, pole khong xac dinh

    angle = to_ik.angle(to_fk)
    if axis.dot(to_ik.cross(to_fk)) < 0.0:
        angle = -angle
    return angle, axis, hip


def snap_pole(context, rig, limb):
    """Xoay pole quanh truc hong-co chan cho toi khi goi IK trung goi FK."""
    pole = rig.pose.bones.get(limb.pole)
    if pole is None:
        return 0.0
    residual = 0.0
    for _ in range(POLE_MAX_PASSES):
        angle, axis, hip = _pole_error(context, rig, limb)
        if angle is None:
            return residual
        residual = angle
        if abs(angle) < POLE_TOLERANCE:
            break
        ev_pole = compat.evaluated(context, rig).pose.bones[limb.pole]
        rotation = Matrix.Rotation(angle, 3, axis)
        moved = hip + rotation @ (ev_pole.matrix.translation - hip)
        _move_head(context, rig, limb.pole, moved)
    return residual


def snap_end_rotation(context, rig, limb, target_rotation):
    """Xoay control IK cho toi khi bone IK cuoi chuoi trung huong voi FK.

    Khong copy thang gia tri quaternion duoc: quan he giua rotation cua
    control va huong ban chan di qua LOCAL_WITH_PARENT/LOCAL_OWNER_ORIENT,
    khong phai copy world — do dung la cho da sai 28.66 do khi thu copy.

    Bay o day: pole la CON cua control, nen xoay control se keo pole di theo
    va lam hong loi giai chuoi vua dat duoc (do duoc 130 mm lech khuyu).
    Nen moi vong phai ghim pole: nho vi tri world cua no truoc khi xoay, tra
    lai ngay sau khi xoay. Ghim roi thi hai buoc doc lap hoan toan — constraint
    IK tat `use_rotation` nen rotation cua control khong con anh huong gi den
    chuoi nua, mot vong la trung.
    """
    ctrl = rig.pose.bones.get(limb.ctrl)
    if ctrl is None:
        return 0.0
    residual = 0.0
    for _ in range(ROT_MAX_PASSES):
        ev_rig = compat.evaluated(context, rig)
        actual = ev_rig.pose.bones[limb.ik[2]].matrix.to_quaternion()
        delta = target_rotation @ actual.inverted()
        residual = _angle_off(delta)
        if residual < ROT_TOLERANCE:
            break

        pole_head = None
        if limb.pole in ev_rig.pose.bones:
            pole_head = ev_rig.pose.bones[limb.pole].matrix.translation.copy()

        matrix = ev_rig.pose.bones[limb.ctrl].matrix.copy()
        head = matrix.translation.copy()
        matrix = delta.to_matrix().to_4x4() @ matrix
        matrix.translation = head          # xoay quanh goc lam troi head, tra lai
        ctrl.matrix = matrix
        context.view_layer.update()

        if pole_head is not None:
            _move_head(context, rig, limb.pole, pole_head)
    return residual


def is_evaluatable(context, rig):
    """Rig co duoc depsgraph danh gia khong.

    Object nam ngoai view layer (collection bi exclude) thi depsgraph KHONG
    tinh, va `evaluated_get` van tra ve object kem ma tran cu — khong bao loi,
    chi ra so rac. Da tuong hai rig trong file sai pole_angle toi 344 mm chi
    vi chuyen nay.
    """
    return rig.name in context.view_layer.objects


def rest_ik_gap(context, rig, limb):
    """Do sai lech cua loi giai IK ngay tai rest pose, tinh bang met.

    Dua tren cung bat bien voi `calibrate_pole`: o rest, IK phai tai tao dung
    rest. Day la phep KIEM TRA that cho `pole_angle`, thay cho viec so goc
    trai/phai — hai ben tay guong nhau nen goc lech dung 180 do la BINH
    THUONG, khong phai loi. (Da tung bao dong nham vi cho nay.)
    """
    if limb.ik_constraint(rig) is None or not is_evaluatable(context, rig):
        return None
    # Phai dua CA RIG ve rest, khong chi rieng chi do. Chuoi tay di theo cot
    # song con control IK di theo Root — rig dang o pose nao do thi hai ben o
    # hai khung khac nhau, va phep do ra so vo nghia (do duoc 344 mm tren mot
    # rig thuc ra hoan toan binh thuong).
    saved = {pb.name: pb.matrix_basis.copy() for pb in rig.pose.bones}
    for pose_bone in rig.pose.bones:
        pose_bone.matrix_basis.identity()
    context.view_layer.update()

    gap = None
    middle = limb.ik[1]
    if middle in rig.data.bones:
        rest = rig.data.bones[middle].matrix_local.translation
        ev_rig = compat.evaluated(context, rig)
        solved = ev_rig.pose.bones[middle].matrix.translation
        gap = (rest - solved).length

    for name, matrix in saved.items():
        rig.pose.bones[name].matrix_basis = matrix
    context.view_layer.update()
    return gap


def calibrate_pole(context, rig, limb, passes=5):
    """Do va sua `pole_angle` cua constraint IK.

    Bat bien dung de do: **o rest pose, loi giai IK phai tai tao dung rest
    pose**. Xuong o rest da nam dung cho theo y do nguoi rig, control IK o
    rest cung dung ngay co chan, nen dau goi ma IK giai ra lech khoi dau goi
    o rest thi phan lech do chinh la sai so cua `pole_angle` — khong con
    nguyen nhan nao khac.

    `pole_angle` la HANG SO cua rig, khong doan duoc tu roll: rig goc trong
    project dang de tay trai 180 do, tay phai 0 do. Nen phai do.

    CANH BAO: doi `pole_angle` la doi ket qua solve cua moi action da bake.
    """
    con = limb.ik_constraint(rig)
    if con is None:
        return None, "khong tim thay constraint IK"
    if not con.pole_subtarget:
        return None, "constraint IK chưa có pole"
    if not is_evaluatable(context, rig):
        return None, ("rig nằm ngoài view layer nên depsgraph không tính — bật "
                      "collection chứa nó lên rồi đo lại")

    # Nhu `rest_ik_gap`: ca rig phai ve rest, khong chi rieng chi dang hieu chuan.
    saved = {pb.name: pb.matrix_basis.copy() for pb in rig.pose.bones}
    for pose_bone in rig.pose.bones:
        pose_bone.matrix_basis.identity()
    context.view_layer.update()

    def restore():
        for name, matrix in saved.items():
            rig.pose.bones[name].matrix_basis = matrix
        context.view_layer.update()

    def measure():
        angle, _axis, _hip = _pole_error(context, rig, limb)
        return angle

    before = con.pole_angle
    residual = measure()
    if residual is None:
        restore()
        return None, ("chi này ở rest gần như thẳng tuyệt đối nên không xác "
                      "định được mặt phẳng gập — kéo marker gối/khuỷu lệch ra "
                      "chút")

    # Chieu cua `pole_angle` phu thuoc roll nen khong suy ra duoc. Thu mot
    # buoc roi DO lai: sai lech giam thi dung chieu, tang thi lat lai.
    sign = 1.0
    con.pole_angle = _wrap(before + residual)
    context.view_layer.update()
    probe = measure()
    if probe is not None and abs(probe) > abs(residual) + POLE_TOLERANCE:
        sign = -1.0
        con.pole_angle = _wrap(before - residual)
        context.view_layer.update()

    for _ in range(passes):
        angle = measure()
        if angle is None or abs(angle) < POLE_TOLERANCE:
            residual = angle if angle is not None else residual
            break
        residual = angle
        con.pole_angle = _wrap(con.pole_angle + sign * angle)
        context.view_layer.update()

    after = con.pole_angle
    restore()
    return (before, after, residual), None


class SRP_OT_calibrate_pole(bpy.types.Operator):
    """Đo và sửa pole_angle cho từng chi.

    ĐỔI KẾT QUẢ SOLVE — chạy trên rig mới thì tốt, trên rig đã bake animation
    thì phải kiểm lại toàn bộ.
    """
    bl_idname = "srp.calibrate_pole"
    bl_label = "Đo lại pole angle"
    bl_options = {'REGISTER', 'UNDO'}

    scope: EnumProperty(
        name="Phạm vi",
        items=(('ACTIVE', "Rig đang chọn", ""), ('ALL', "Mọi rig trong file", "")),
        default='ACTIVE')
    apply_fix: BoolProperty(
        name="Sửa thật", default=False,
        description="Tắt đi thì chỉ ĐO và báo cáo, không đụng vào rig")

    @classmethod
    def poll(cls, context):
        return rigdef.active_rig(context) is not None

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        rigs = ([rigdef.active_rig(context)] if self.scope == 'ACTIVE'
                else rigdef.managed_rigs(context))
        lines = []
        for rig in rigs:
            for limb in rigdef.limbs_for(rig):
                con = limb.ik_constraint(rig)
                original = con.pole_angle if con else 0.0
                result, error = calibrate_pole(context, rig, limb)
                if error:
                    lines.append("%s/%s: %s" % (rig.name, limb.label, error))
                    continue
                before, after, residual = result
                if not self.apply_fix and con is not None:
                    con.pole_angle = original
                lines.append("%s/%s: %.1f do -> %.1f do (du %.4f do)"
                             % (rig.name, limb.label, math.degrees(before),
                                math.degrees(after), math.degrees(abs(residual))))
        if rigs:
            compat.refresh(context, rigs[0])
        for line in lines:
            prefs.log("[Rig Tẩm Hành] " + line)
        self.report({'INFO' if self.apply_fix else 'WARNING'},
                    ("Đã sửa %d chi" if self.apply_fix else "CHỈ ĐO, chưa sửa — %d chi")
                    % len(lines) + " | chi tiet o Console")
        return {'FINISHED'}


def twist_residual(context, rig, limb):
    """Phan chuoi IK khong the tai hien duoc, tinh bang do.

    Goi ngay sau snap_ik_to_fk, luc chuoi FK van con giu pose nguon.

    IK 2 xuong + pole KHONG co bac tu do cho do xoan quanh truc xuong: mat
    phang pole da quyet dinh het. Nen neu animator da xoay tron bap tay
    trong FK, snap sang IK se mat dung phan do — vi tri va huong xuong van
    khop tuyet doi, chi rieng do xoan la mat. Rigify va ARP cung vay.
    Do va bao ra, dung de animator tu phat hien bang mat.
    """
    ev_rig = compat.evaluated(context, rig)
    worst = 0.0
    for fk_name, ik_name in zip(limb.fk, limb.ik):
        fk_bone = ev_rig.pose.bones.get(fk_name)
        ik_bone = ev_rig.pose.bones.get(ik_name)
        if fk_bone is None or ik_bone is None:
            continue
        delta = fk_bone.matrix.to_quaternion().rotation_difference(
            ik_bone.matrix.to_quaternion())
        worst = max(worst, _angle_off(delta))
    return worst


def _roll_pivots(rig, limb):
    """Cac dot lan chan animator xoay duoc (bo `AnkleIK`, no chi la dich)."""
    if not limb.has_roll(rig):
        return []
    return [rig.pose.bones[name] for name in limb.roll[:-1]]


def reset_roll(context, rig, limb):
    """Dua chuoi lan chan ve identity. Tra ve so bone da doi."""
    changed = 0
    for bone in _roll_pivots(rig, limb):
        bone.location = (0.0, 0.0, 0.0)
        bone.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        bone.rotation_euler = (0.0, 0.0, 0.0)
        bone.rotation_axis_angle = (0.0, 0.0, 1.0, 0.0)
        changed += 1
    if changed:
        context.view_layer.update()
    return changed


def snap_ik_to_fk(context, rig, limb):
    """Control IK + pole nhan lai pose ma chuoi FK dang tao ra."""
    ctrl = rig.pose.bones.get(limb.ctrl)
    end_fk = rig.pose.bones.get(limb.fk[2])
    if ctrl is None or end_fk is None:
        return None

    ev_rig = compat.evaluated(context, rig)
    target_position = ev_rig.pose.bones[limb.fk[1]].tail.copy()   # co chan / co tay
    target_rotation = ev_rig.pose.bones[limb.fk[2]].matrix.to_quaternion()

    # Chuoi lan chan dung GIUA control va dich IK (`AnkleIK`). Con xoay got/mui
    # thi dat `LegIK` dung co chan van lech dich, va ban chan con cong them goc
    # cua tung dot qua `Ctrl_Follow_*`. Tra chung ve identity: o do `AnkleIK`
    # trung khit co chan va mix ADD bang khong — dung gia thiet cua ca ham nay.
    reset_roll(context, rig, limb)

    # Thu tu bat buoc: vi tri -> pole -> huong. Hai buoc dau quyet dinh loi
    # giai chuoi, buoc cuoi chi chinh khop cuoi nen khong pha hai buoc truoc.
    _move_head(context, rig, limb.ctrl, target_position)
    residual = snap_pole(context, rig, limb)
    snap_end_rotation(context, rig, limb, target_rotation)
    return residual


# ------------------------------------------------------------------ key

def _key(bone, paths, frame):
    for path in paths:
        bone.keyframe_insert(data_path=path, frame=frame, group=bone.name)


def _rotation_path(bone):
    return {
        'QUATERNION': "rotation_quaternion",
        'AXIS_ANGLE': "rotation_axis_angle",
    }.get(bone.rotation_mode, "rotation_euler")


def key_fk(rig, limb, frame):
    # `snap_fk_to_ik` gan ca ma tran, nen bone KHONG noi cha (dau chuoi FK)
    # co the doi ca vi tri. Chi key rotation thi bake khong dung lai pose IK.
    for name in limb.fk:
        bone = rig.pose.bones.get(name)
        if bone is None:
            continue
        paths = (_rotation_path(bone),)
        if not bone.bone.use_connect:
            paths = ("location",) + paths
        _key(bone, paths, frame)


def key_ik(rig, limb, frame):
    ctrl = rig.pose.bones.get(limb.ctrl)
    if ctrl is not None:
        _key(ctrl, ("location", _rotation_path(ctrl)), frame)
    pole = rig.pose.bones.get(limb.pole)
    if pole is not None:
        _key(pole, ("location",), frame)
    # Lan chan la mot phan cua pose IK: snap da tra no ve identity, khong key
    # thi frame ben canh con goc cu se noi suy nguoc vao frame nay.
    for bone in _roll_pivots(rig, limb):
        _key(bone, ("location", _rotation_path(bone)), frame)


def key_switch(rig, limb, frame):
    bone = rig.pose.bones.get(rigdef.PROP_BONE)
    if bone is not None:
        bone.keyframe_insert(data_path='["%s"]' % limb.prop, frame=frame,
                             group=rigdef.PROP_BONE)


# ------------------------------------------------------------ operators

def _target_limbs(context, rig, scope, limb_name):
    if scope == 'ALL':
        return rigdef.limbs_for(rig)
    limb = rigdef.limb_by_name(rig, limb_name)
    return [limb] if limb else []


class SRP_OT_snap(bpy.types.Operator):
    "Snap một chi tại frame hiện tại, không ghi key"
    bl_idname = "srp.snap"
    bl_label = "Snap IK/FK"
    bl_options = {'REGISTER', 'UNDO'}

    direction: EnumProperty(
        name="Hướng",
        items=(('TO_FK', "FK theo IK", "Chuỗi FK nhận pose đang có của IK"),
               ('TO_IK', "IK theo FK", "Control IK nhận pose đang có của FK")),
        default='TO_FK',
    )
    limb_name: bpy.props.StringProperty(name="Chi", default="")
    scope: EnumProperty(
        name="Phạm vi",
        items=(('ONE', "Một chi", ""), ('ALL', "Mọi chi", "")),
        default='ONE',
    )
    switch: BoolProperty(
        name="Đổi công tắc luôn",
        description="Sau khi snap thì lật công tắc sang chế độ vừa snap tới",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        return rigdef.active_rig(context) is not None and context.mode != 'EDIT_ARMATURE'

    def execute(self, context):
        rig = rigdef.active_rig(context)
        limbs = _target_limbs(context, rig, self.scope, self.limb_name)
        if not limbs:
            self.report({'ERROR'}, "Không xác định được chi nào")
            return {'CANCELLED'}

        lossy = []
        for limb in limbs:
            if self.direction == 'TO_FK':
                snap_fk_to_ik(context, rig, limb)
            else:
                snap_ik_to_fk(context, rig, limb)
                twist = math.degrees(twist_residual(context, rig, limb))
                if twist > 1.0:
                    lossy.append("%s %.1f do" % (limb.label, twist))
            if self.switch:
                limb.set_switch(rig, rigdef.FK_VALUE if self.direction == 'TO_FK'
                                else rigdef.IK_VALUE)
        compat.refresh(context, rig)

        if lossy:
            self.report({'WARNING'}, "Snap %d chi — mat do xoan: %s"
                        % (len(limbs), ", ".join(lossy)))
        else:
            self.report({'INFO'}, "Snap %d chi, khop tuyet doi" % len(limbs))
        return {'FINISHED'}


class SRP_OT_snap_bake(bpy.types.Operator):
    "Snap từng frame trong một đoạn và ghi key"
    bl_idname = "srp.snap_bake"
    bl_label = "Bake snap theo đoạn"
    bl_options = {'REGISTER', 'UNDO'}

    direction: EnumProperty(
        name="Hướng",
        items=(('TO_FK', "FK theo IK", ""), ('TO_IK', "IK theo FK", "")),
        default='TO_FK',
    )
    limb_name: bpy.props.StringProperty(name="Chi", default="")
    scope: EnumProperty(
        name="Phạm vi",
        items=(('ONE', "Một chi", ""), ('ALL', "Mọi chi", "")),
        default='ALL',
    )
    frame_start: IntProperty(name="Frame đầu", default=0)
    frame_end: IntProperty(name="Frame cuối", default=60)
    switch: BoolProperty(name="Key cả công tắc", default=True)

    @classmethod
    def poll(cls, context):
        rig = rigdef.active_rig(context)
        return rig is not None and rig.animation_data is not None \
            and rig.animation_data.action is not None

    def invoke(self, context, event):
        scene = context.scene
        self.frame_start, self.frame_end = scene.frame_start, scene.frame_end
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        rig = rigdef.active_rig(context)
        limbs = _target_limbs(context, rig, self.scope, self.limb_name)
        if not limbs:
            self.report({'ERROR'}, "Không xác định được chi nào")
            return {'CANCELLED'}
        if self.frame_end < self.frame_start:
            self.report({'ERROR'}, "Frame cuối nhỏ hơn frame đầu")
            return {'CANCELLED'}

        scene = context.scene
        restore = scene.frame_current
        value = rigdef.FK_VALUE if self.direction == 'TO_FK' else rigdef.IK_VALUE
        count = 0

        for frame in range(self.frame_start, self.frame_end + 1):
            scene.frame_set(frame)
            for limb in limbs:
                if self.direction == 'TO_FK':
                    snap_fk_to_ik(context, rig, limb)
                    key_fk(rig, limb, frame)
                else:
                    snap_ik_to_fk(context, rig, limb)
                    key_ik(rig, limb, frame)
                if self.switch:
                    limb.set_switch(rig, value)
                    key_switch(rig, limb, frame)
            count += 1

        scene.frame_set(restore)
        compat.refresh(context, rig)
        self.report({'INFO'}, "Bake %d frame x %d chi" % (count, len(limbs)))
        return {'FINISHED'}


CLASSES = (SRP_OT_snap, SRP_OT_snap_bake, SRP_OT_calibrate_pole)
