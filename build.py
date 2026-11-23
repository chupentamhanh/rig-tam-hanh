"""Ap lai rig logic len xuong CO SAN — khong dung toi ten hay hierarchy.

Chay bao nhieu lan cung ra cung mot ket qua. Day la thu dang le da chan
duoc vu mat driver: rig logic tro thanh cai tai dung lai duoc, khong con
la trang thai mo ho nam trong file .blend.

Ranh gioi phai giu:
  * `apply_logic()` KHONG doi ket qua solve. No chi dat ten constraint,
    dung lai driver, chuan hoa UI cua custom property.
  * Thu nao doi ket qua solve (pole_angle, use_stretch) nam o operator
    rieng, phai bam co y thuc. Vi rig nay co 31 action da bake — doi solve
    la doi ca thu vien animation.
"""

import bpy

from . import compat, rigdef


class Change:
    """Gom thay doi de bao cao lai, thay vi in tung dong ra console."""

    def __init__(self):
        self.items = []

    def add(self, text):
        self.items.append(text)

    def __len__(self):
        return len(self.items)

    def summary(self):
        return "; ".join(self.items) if self.items else "không có gì phải sửa"


# ----------------------------------------------------- tao constraint

# Do dung y: WORLD/WORLD/REPLACE giong het rig goc. Blend bang ROTATION chu
# khong phai TRANSFORMS — copy ca vi tri se cong dồn transform cua cha vao
# lan nua, chi bi keo dan khi than nguoi di chuyen.
BLEND_SPACE = 'WORLD'


def ensure_blend_constraints(rig, limb, changes):
    """Tao cap Copy Rotation IK/FK neu chua co.

    Nho vay `apply_logic` dung duoc cho ca rig vua sinh ra lan rig cu bi mat
    constraint — mot duong code duy nhat, khong co ban sao de lech nhau.
    """
    made = 0
    for def_name, ik_name, fk_name in zip(limb.deform, limb.ik, limb.fk):
        bone = rig.pose.bones.get(def_name)
        if bone is None:
            continue
        existing = {c.subtarget for c in bone.constraints if c.type == 'COPY_ROTATION'}
        for target, name in ((ik_name, rigdef.CON_IK), (fk_name, rigdef.CON_FK)):
            if target in existing or target not in rig.pose.bones:
                continue
            con = bone.constraints.new('COPY_ROTATION')
            con.name = name
            con.target = rig
            con.subtarget = target
            con.target_space = con.owner_space = BLEND_SPACE
            con.mix_mode = 'REPLACE'
            made += 1
    if made:
        changes.add("%s: tao %d constraint blend" % (limb.label, made))
    return made


def ensure_ik_constraint(rig, limb, changes):
    """Tao constraint IK tren bone giai chuoi, neu chua co."""
    bone = rig.pose.bones.get(limb.solver)
    if bone is None or limb.ik_constraint(rig) is not None:
        return 0
    if limb.ctrl not in rig.pose.bones:
        return 0
    con = bone.constraints.new('IK')
    con.target = rig
    con.subtarget = limb.ik_target(rig)      # cuoi chuoi lan chan, neu co
    if limb.pole in rig.pose.bones:
        con.pole_target = rig
        con.pole_subtarget = limb.pole
        con.pole_angle = limb.pole_angle
    con.chain_count = 2
    con.use_tail = True
    # Blender bat use_stretch mac dinh, va chinh health check cua addon canh
    # bao dieu do. Rig moi thi tat san — chi gian ra la loi hinh hoc chu khong
    # phai tinh nang. Rig cu khong bi dung toi: ham nay thoat som neu da co
    # constraint IK.
    con.use_stretch = False
    changes.add("%s: tao constraint IK" % limb.label)
    return 1


def ensure_tip_follow(rig, limb, changes):
    """Bone CUOI chuoi IK bam theo huong cua control IK.

    Constraint IK chi giai HAI doan dau (`chain_count=2`), nen doan thu ba —
    ban tay / ban chan — khong ai dieu khien ca: no chi thua huong cua cang tay
    hay cang chan. Xoay control IK thi ban tay van doi huong, nhung do CHUOI
    GIAI LAI chu khong do y dinh cua nguoi keo — do duoc 31,7 do lech tren tay
    va 18,5 do tren chan khi xoay control 40 do quanh truc no. Ben FK thi khong
    bi, vi `Hand_Master_FK` la con truc tiep cua `ForearmFK`.

    Cap khong gian LOCAL_OWNER_ORIENT / LOCAL_WITH_PARENT la BAT BUOC: no chep
    goc XOAY CUC BO cua control chu khong chep huong tuyet doi, nen o rest (khi
    control chua xoay) ban tay dung y nguyen cho cu. Dung WORLD la ban tay bi
    keo ve dung huong cua control ngay tu tu the nghi.

    Ba so nay lay dung theo `3.0_Rig` — rig anh Art dung tay, no von da co
    constraint nay, chi bo sinh rig la thieu.
    """
    tip = limb.ik[-1]
    bone = rig.pose.bones.get(tip)
    if bone is None:
        return 0
    # Tro vao CONTROL, khong tro vao dich cua constraint IK. Voi chan co chuoi
    # lan chan thi dich la `AnkleIK` — ma `AnkleIK` khong bao gio co goc xoay
    # CUC BO cua rieng no (no chi thua huong tu chuoi lan), nen chep goc cuc bo
    # cua no ra dung so khong. Do duoc: tay khop 40,0 do con chan 0,0 do.
    target = limb.ctrl
    if target == tip or target not in rig.pose.bones:
        return 0
    for con in bone.constraints:
        if con.type == 'COPY_ROTATION' and con.subtarget == target:
            return 0                       # da co roi, khong dong vao
    def follow(subtarget, mix, name):
        con = bone.constraints.new('COPY_ROTATION')
        con.name = name
        con.target = rig
        con.subtarget = subtarget
        con.target_space = 'LOCAL_OWNER_ORIENT'
        con.owner_space = 'LOCAL_WITH_PARENT'
        con.mix_mode = mix

    follow(target, 'REPLACE', rigdef.CON_TIP)
    made = [target]
    # Chuoi lan chan: moi dot la mot TRUC QUAY that (got, mui, uc ban chan).
    # Xoay chung thi ban chan phai pitch theo, nhung chung chi doi vi tri dich
    # IK — do duoc 0,0 do tren ban chan. Cong don goc cua tung dot vao huong
    # ban chan bang mix ADD; tong lai dung bang y dinh nguoi keo.
    if limb.has_roll(rig):
        for pivot in limb.roll[:-1]:          # bo `AnkleIK`, no chi la dich
            if pivot in rig.pose.bones:
                follow(pivot, 'ADD', "%s_%s" % (rigdef.CON_TIP, pivot))
                made.append(pivot)
    changes.add("%s: %s bam theo %s" % (limb.label, tip, ", ".join(made)))
    return len(made)


def ensure_digi_toe(rig, limb, changes):
    """Chan thu: o IK, ban chan / mong giu huong theo `ToeTip`.

    Nhac hock (xoay `Ball`) la doan ban `Foot` quay quanh cho cham dat. `Toe` la
    con cua no nen se cam xuong dat neu khong co xuong dem nay.
    """
    if not limb.is_digitigrade(rig) or not limb.has_roll(rig):
        return None
    bone = rig.pose.bones.get(limb.toe_mch)
    if bone is None:
        return None
    con = bone.constraints.get("Toe_Plant")
    if con is None:
        con = bone.constraints.new('COPY_ROTATION')
        con.name = "Toe_Plant"
        con.target = rig
        con.subtarget = limb.roll[1]
        con.target_space = con.owner_space = BLEND_SPACE
        con.mix_mode = 'REPLACE'
        changes.add("%s: toe bam dat" % limb.label)
    return con


# ------------------------------------------------------- ten constraint

def rename_constraints(rig, limb, changes):
    """Dat ten chuan cho cap constraint blend.

    Ten mac dinh "Copy Rotation" / "Copy Rotation.001" phan biet IK voi FK
    bang THU TU. Ai keo doi thu tu mot cai la driver tro sai ma khong bao
    loi. Ten co nghia thi khong con phu thuoc thu tu nua.
    """
    for _bone, con_ik, con_fk in limb.blend_pairs(rig):
        for con, want in ((con_ik, rigdef.CON_IK), (con_fk, rigdef.CON_FK)):
            if con is not None and con.name != want:
                changes.add("%s: %s -> %s" % (con.id_data.name, con.name, want))
                con.name = want


# --------------------------------------------------------------- driver

def clear_drivers(rig, limb):
    """Xoa moi driver influence tren cac bone deform cua chi."""
    anim = rig.animation_data
    if anim is None:
        return
    doomed = []
    for fcurve in anim.drivers:
        bone = compat.bone_of(fcurve.data_path)
        if bone in limb.deform and fcurve.data_path.endswith(".influence"):
            doomed.append(fcurve.data_path)
    for path in doomed:
        try:
            rig.driver_remove(path)
        except Exception:
            pass


def add_switch_driver(rig, limb, bone_name, con_name, inverted):
    path = limb.con_path(bone_name, con_name)
    fcurve = rig.driver_add(path)
    driver = fcurve.driver
    driver.type = 'SCRIPTED'
    for var in list(driver.variables):
        driver.variables.remove(var)
    var = driver.variables.new()
    var.name = "switch"
    var.type = 'SINGLE_PROP'
    target = var.targets[0]
    target.id_type = 'OBJECT'
    target.id = rig
    target.data_path = limb.prop_path
    # switch: 0 = FK, 1 = IK
    driver.expression = "1.0 - switch" if inverted else "switch"
    return fcurve


def rebuild_drivers(rig, limb, changes):
    clear_drivers(rig, limb)
    made = 0
    for bone, con_ik, con_fk in limb.blend_pairs(rig):
        if con_ik is not None:
            add_switch_driver(rig, limb, bone.name, con_ik.name, inverted=False)
            made += 1
        if con_fk is not None:
            add_switch_driver(rig, limb, bone.name, con_fk.name, inverted=True)
            made += 1
    if made:
        changes.add("%s: %d driver" % (limb.label, made))
    return made


# --------------------------------------------- hien/an bone collection

def clear_collection_drivers(rig, limb):
    """Xoa driver visibility cu tren armature DATA (khong phai tren object).

    Phai xoa CA HAI cach viet duong dan: `collections["X"]` va
    `collections_all["X"]` tro toi cung mot thuoc tinh, nhung Blender luu
    thanh hai F-curve rieng. Chi xoa mot dang thi lan ap lai se chong them
    driver moi len driver cu, hai cai tranh nhau mot thuoc tinh.
    """
    armature = rig.data
    anim = armature.animation_data
    if anim is None:
        return
    wanted = set()
    for name, _expression in limb.collections():
        for attr in ("collections", "collections_all"):
            wanted.add('%s["%s"].is_visible' % (attr, name))
    for path in [fcurve.data_path for fcurve in anim.drivers
                 if fcurve.data_path in wanted]:
        try:
            armature.driver_remove(path)
        except Exception:
            pass


def add_collection_driver(rig, limb, collection_name, expression):
    """Noi visibility cua mot bone collection vao cong tac FK/IK."""
    armature = rig.data
    path = rigdef.collection_path(armature, collection_name)
    if path is None:
        return False
    fcurve = armature.driver_add(path)
    driver = fcurve.driver
    driver.type = 'SCRIPTED'
    for var in list(driver.variables):
        driver.variables.remove(var)
    var = driver.variables.new()
    var.name = "switch"
    var.type = 'SINGLE_PROP'
    target = var.targets[0]
    target.id_type = 'OBJECT'
    target.id = rig            # prop nam tren OBJECT, driver nam tren DATA
    target.data_path = limb.prop_path
    driver.expression = expression
    return True


def rebuild_collection_drivers(rig, limb, changes):
    """Bat/tat collection control theo cong tac.

    Thieu cai nay thi rig van chay dung ve mat bien dang nhung animator
    nhin thay control FK khi dang o IK — bam vao keo thi khong co gi nhuc
    nhich. Driver dieu khien bien dang ma khong dieu khien cai nguoi ta
    nhin thay thi quy trinh moi xong mot nua.
    """
    clear_collection_drivers(rig, limb)
    made = missing = 0
    for name, expression in limb.collections():
        if add_collection_driver(rig, limb, name, expression):
            made += 1
        else:
            missing += 1
            changes.add("thieu collection %r" % name)
    if made:
        changes.add("%s: %d driver collection" % (limb.label, made))
    return made


# ------------------------------------------------------ custom property

def ensure_prop(rig, limb, changes):
    bone = rig.pose.bones.get(rigdef.PROP_BONE)
    if bone is None:
        return False
    if limb.prop not in bone.keys():
        # Mac dinh theo tung chi, khong phai FK cho tat ca: chan cua rig nay
        # dung IK toan bo, dat nham ve FK la chan dung im o moi action.
        bone[limb.prop] = limb.default_switch
        changes.add("tao prop %r = %.1f" % (limb.prop, limb.default_switch))
    ui = bone.id_properties_ui(limb.prop)
    ui.update(min=0.0, max=1.0, soft_min=0.0, soft_max=1.0,
              description="0 = FK, 1 = IK")
    return True


# ----------------------------------------------------------------- main

def apply_logic(context, rig):
    """Ap lai toan bo rig logic an toan. Tra ve Change."""
    changes = Change()
    for limb in rigdef.limbs_for(rig):
        ensure_prop(rig, limb, changes)
        ensure_blend_constraints(rig, limb, changes)
        ensure_ik_constraint(rig, limb, changes)
        ensure_tip_follow(rig, limb, changes)
        rename_constraints(rig, limb, changes)
        rebuild_drivers(rig, limb, changes)
        if ensure_digi_toe(rig, limb, changes) is not None:
            add_switch_driver(rig, limb, limb.toe_mch, "Toe_Plant", inverted=False)
        rebuild_collection_drivers(rig, limb, changes)
    rig.data.update_tag()
    compat.refresh(context, rig)
    return changes


def verify_switching(context, rig):
    """Bat cong tac thu ca hai dau va DO lai, thay vi tin la da sua xong.

    Tra ve danh sach mo ta cho hong. Rong nghia la rig chuyen FK<->IK that.
    """
    failures = []
    for limb in rigdef.limbs_for(rig):
        keep = limb.switch(rig)
        for value, want_ik in ((rigdef.FK_VALUE, 0.0), (rigdef.IK_VALUE, 1.0)):
            limb.set_switch(rig, value)
            compat.refresh(context, rig)
            ev_rig = compat.evaluated(context, rig)
            for bone_name, con_ik, con_fk in limb.blend_pairs(rig):
                ev_bone = ev_rig.pose.bones.get(bone_name.name)
                if ev_bone is None:
                    continue
                for con, want in ((con_ik, want_ik), (con_fk, 1.0 - want_ik)):
                    if con is None:
                        continue
                    got = ev_bone.constraints[con.name].influence
                    if abs(got - want) > 1e-4:
                        failures.append("%s/%s: cong tac %.0f -> influence %.2f, cho doi %.2f"
                                        % (bone_name.name, con.name, value, got, want))
        if keep is not None:
            limb.set_switch(rig, keep)
    compat.refresh(context, rig)
    return failures


class SRP_OT_apply_logic(bpy.types.Operator):
    """Dựng lại toàn bộ rig logic: constraint, driver switch, driver hiện/ẩn
    collection, custom property. Dùng sau khi append nhân vật sang file khác.

    An toàn: không đổi kết quả solve, không đụng tới tên hay hierarchy bone,
    không đụng tới action nào. Chạy lại bao nhiêu lần cũng thế.
    """
    bl_idname = "srp.apply_logic"
    bl_label = "Áp lại rig logic"
    bl_options = {'REGISTER', 'UNDO'}

    scope: bpy.props.EnumProperty(
        name="Phạm vi",
        items=(('ALL', "Mọi rig trong file",
                "Quét cả file — dùng sau khi append vì thường có nhiều rig cùng "
                "lúc"),
               ('ACTIVE', "Chỉ rig đang chọn", "")),
        default='ALL',
    )
    verify: bpy.props.BoolProperty(
        name="Kiểm chứng sau khi sửa", default=True,
        description="Bật công tắc thử cả hai đầu và đo lại influence")

    @classmethod
    def poll(cls, context):
        return rigdef.active_rig(context) is not None

    def execute(self, context):
        if self.scope == 'ALL':
            rigs = rigdef.managed_rigs(context)
        else:
            rig = rigdef.active_rig(context)
            rigs = [rig] if rig else []
        if not rigs:
            self.report({'ERROR'}, "Không tìm thấy rig nào khớp convention")
            return {'CANCELLED'}

        total, broken = 0, []
        for rig in rigs:
            changes = apply_logic(context, rig)
            total += len(changes)
            if self.verify:
                for line in verify_switching(context, rig):
                    broken.append("%s: %s" % (rig.name, line))

        if broken:
            self.report({'ERROR'}, "%d rig, van con hong: %s"
                        % (len(rigs), broken[0]))
            return {'FINISHED'}
        suffix = " — da kiem chung FK<->IK" if self.verify else ""
        self.report({'INFO'}, "%d rig, %d nhom thay doi%s" % (len(rigs), total, suffix))
        return {'FINISHED'}


class SRP_OT_ik_stretch(bpy.types.Operator):
    """Tắt IK stretch trên mọi chi của rig.

    ĐỔI KẾT QUẢ SOLVE — chỉ khác đi ở những frame chi bị kéo quá tầm với.
    Chạy QC lại sau khi bấm.
    """
    bl_idname = "srp.ik_stretch"
    bl_label = "Tắt IK stretch"
    bl_options = {'REGISTER', 'UNDO'}

    enable: bpy.props.BoolProperty(name="Bật lại thay vì tắt", default=False)

    @classmethod
    def poll(cls, context):
        return rigdef.active_rig(context) is not None

    def execute(self, context):
        rig = rigdef.active_rig(context)
        touched = 0
        for limb in rigdef.limbs_for(rig):
            con = limb.ik_constraint(rig)
            if con is not None and con.use_stretch != self.enable:
                con.use_stretch = self.enable
                touched += 1
        compat.refresh(context, rig)
        self.report({'WARNING' if touched else 'INFO'},
                    "Doi IK stretch tren %d chi — kiem tra lai animation" % touched)
        return {'FINISHED'}


CLASSES = (SRP_OT_apply_logic, SRP_OT_ik_stretch)
