"""Sua bo xuong ref SAU KHI rig da dung va da bind skin.

Truoc day bo ref chi song toi luc bind (`drop_ref`), va muon sua thi chi con
cach dung rig MOI tu bo ref — tuc mat skin, mat weight to tay, mat animation,
mat driver shape key tro vao rig cu. Module nay lam hai viec:

1. `ref_from_rig` — dung lai bo ref tu CHINH rig dang co. Ten xuong ref trung
   ten xuong deform, nen chi viec chep head/tail/roll va gan the bo phan theo
   dung ban ve cua `refrig`. Rig lam tay (Kid_Rig.001) cung di duoc duong nay.

2. `apply_ref` — day bo ref vao rig dang co, SUA TAI CHO trong Edit Mode cua
   rig. Khong xoa xuong, khong doi ten, nen vertex group, constraint, driver,
   action deu con nguyen. Mesh skin khong nhuc nhich: o rest pose bien dang
   cua Armature modifier la don vi bat ke xuong nam dau.

Doi theo HIEU SO, khong theo toa do tuyet doi. Moi xuong rig dich di dung bang
"ban ve tu bo ref bay gio" tru "ban ve tu anh chup luc rig con khop"
(`refrig.TAG_BASELINE`). Nho vay xuong nao nguoi dung khong dong toi thi rig
dung yen tuyet doi — ke ca control ma rig lam tay dat lech ban ve vai phan
muoi mm, dung theo toa do tuyet doi la chung bi keo ve ban ve mot cach vo co.
"""

import bpy
from bpy.props import BoolProperty
from mathutils import Vector

from . import build, generate, refrig, rigdef, snap

# Duoi nguong nay coi nhu khong dich (met). Sai so float32 cua head/tail.
EPS = 1e-6
# Truc Z (vector don vi) lech hon nguong nay moi coi la xoay roll.
EPS_AXIS = 1e-4

Z = Vector((0.0, 0.0, 1.0))


# ------------------------------------------------------- rig -> bo ref

def _ref_table(rig):
    """{ten xuong rig: (kind, inst, side, ten ban ve, ten cha theo ban ve)}.

    Duyet ban ve cua `refrig` va hoi xuong nao CO tren rig — khong doan tu ten
    xuong. Cung mot ham ghep ten (`_digit_name`) voi luc dung bo ref, nen hai
    ben khong the lech nhau.
    """
    bones = rig.data.bones
    table = {}

    def put(name, kind, inst, side, base, parent):
        if name in bones and name not in table:
            table[name] = (kind, inst, side, base, parent)

    for spec in refrig.PARTS:
        kind = spec['kind']
        # Mat gan the theo TUNG VUNG (Ham, Luoi, Mi...) chu khong gop vao
        # "đủ bộ": dung lai xong con xoa le duoc tung vung.
        if kind in ('HAND', 'FACE'):
            continue
        insts = (1,) if spec['once'] else range(1, rigdef.MAX_INSTANCE + 1)
        sides = rigdef.SIDES if spec['sided'] else (None,)
        for inst in insts:
            for side in sides:
                for base, _h, _t, parent, _c, mirror, *_z in spec['bones']:
                    for this in (rigdef.SIDES if mirror else (side,)):
                        full = refrig._digit_name(base, inst, this)
                        up = refrig._digit_name(parent, inst, this) if parent else None
                        put(full, kind, inst, side,
                            base + "." + this if mirror else base, up)
        if kind == 'SPINE':
            # Dot co trung gian cua bo ref doi cu — `build_plan` van doc chung.
            for base in ("Neck.001", "Neck.002"):
                put(base, 'SPINE', 1, None, base, None)

    for inst in range(1, rigdef.MAX_INSTANCE + 1):
        for side in rigdef.SIDES:
            if refrig.bone_name("Hand_Master", inst, side) not in bones:
                continue
            for base, _h, _t, parent, _c, _z in refrig.HAND_LAYOUT:
                full = refrig._digit_name(base, inst, side)
                up = refrig._digit_name(parent, inst, side) if parent else None
                put(full, 'HAND', inst, side, base, up)
    return table


def _generated_only(rig):
    """Xuong deform do `build_plan` tu dat, KHONG co xuong ref tuong ung."""
    return {refrig.bone_name("Pelvis", inst, side)
            for inst in range(1, rigdef.MAX_INSTANCE + 1)
            for side in rigdef.SIDES}


def _chains(rig, table):
    """Xuong deform khong thuoc ban ve nao -> chuoi bo tro (`CHAIN`).

    Moi cay con lien mach la mot chuoi. {ten: (kind, inst, side, ban ve, cha)}.
    """
    skip = _generated_only(rig)
    loose = [b for b in rig.data.bones
             if b.use_deform and b.name not in table and b.name not in skip]
    names = {b.name for b in loose}
    out = {}
    inst = 0
    for bone in loose:
        if bone.parent is not None and bone.parent.name in names:
            continue
        inst += 1
        stack = [bone]
        while stack:
            current = stack.pop()
            out[current.name] = ('CHAIN', inst, None, current.name, None)
            stack.extend(c for c in current.children if c.name in names)
    return out


def ref_from_rig(context, rig, name=None):
    """Dung bo ref moi tu rig. Tra ve (object ref, so xuong)."""
    table = _ref_table(rig)
    table.update(_chains(rig, table))
    if not table:
        return None, 0

    def ref_parent(bone):
        # Cha gan nhat CUNG nam trong bo ref: `Thigh` noi `Pelvis` (xuong
        # dat ra) -> leo len `Hips`, dung nhu luc dung bo ref tu dau.
        up = bone.parent
        while up is not None:
            if up.name in table:
                return up.name
            up = up.parent
        # `Heel` tren rig la mot nut cua chuoi lan chan, cha that la `LegIK`.
        # Trong bo ref no thuoc ban chan — lay cha theo ban ve.
        return table[bone.name][4]

    name = name or refrig.ref_object_name(rig.name)
    armature = bpy.data.armatures.new(name)
    ref = bpy.data.objects.new(name, armature)
    armature.display_type = 'OCTAHEDRAL'
    armature.show_axes = True
    ref.show_in_front = True
    context.scene.collection.objects.link(ref)
    # Chung ma tran voi rig: head/tail chep thang tu he cuc bo cua rig sang.
    ref.matrix_world = rig.matrix_world.copy()

    if context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for obj in list(context.selected_objects):
        obj.select_set(False)
    context.view_layer.objects.active = ref
    ref.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    try:
        edit = armature.edit_bones
        for bone_name in table:
            source = rig.data.bones[bone_name]
            target = edit.new(bone_name)
            target.head = source.head_local.copy()
            target.tail = source.tail_local.copy()
            target.align_roll(source.matrix_local.to_3x3() @ Z)
            target.use_deform = False
        for bone_name in table:
            source = rig.data.bones[bone_name]
            parent = ref_parent(source)
            target = edit[bone_name]
            if parent and parent in edit:
                target.parent = edit[parent]
                target.use_connect = bool(source.use_connect and source.parent
                                          and source.parent.name == parent)
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')

    for bone_name, (kind, inst, side, base, _p) in table.items():
        bone = armature.bones[bone_name]
        bone[refrig.TAG_PART] = kind
        bone[refrig.TAG_INST] = inst
        bone[refrig.TAG_SIDE] = side or ""
        bone[refrig.TAG_BASE] = base
        if kind == 'LEG':
            thigh = rig.data.bones.get(refrig.bone_name("Thigh", inst, side))
            bone[refrig.TAG_LEG] = thigh.get(rigdef.TAG_LEG, 'HUMAN') if thigh else 'HUMAN'
    refrig.store_baseline(ref)
    return ref, len(table)


# ------------------------------------------------------- bo ref -> rig

def _baseline_bones(ref, now):
    """Anh chup bo ref luc rig con khop, dang {ten: RefBone} the gioi.

    None neu bo ref chua tung duoc chup (bo ref dung tu ban addon cu).
    Xuong moi them sau anh chup thi lay vi tri hien tai — hieu so bang 0.
    """
    stored = ref.data.get(refrig.TAG_BASELINE)
    if stored is None:
        return None
    stored = stored.to_dict()
    W = ref.matrix_world
    R = W.to_3x3()
    out = {}
    for name, bone in now.items():
        row = stored.get(name)
        if row is None:
            out[name] = bone
            continue
        z = R @ Vector(row[6:9])
        if z.length > 1e-9:
            z.normalize()
        out[name] = generate.RefBone(name, W @ Vector(row[0:3]),
                                     W @ Vector(row[3:6]), z,
                                     bone.parent, bone.connect)
    return out


def _bone_parented(rig):
    """[(object, ma tran the gioi)] — moi object gan cung vao mot xuong rig.

    Nhan cau, mu, kinh... gan kieu parent BONE. Doi rest cua xuong la chung bi
    keo theo, trong khi nguoi ta dich xuong ref chinh la de khop VOI CHUNG.
    """
    return [(obj, obj.matrix_world.copy()) for obj in bpy.data.objects
            if obj.parent is rig and obj.parent_type == 'BONE']


def apply_ref(context, ref, rig):
    """Doi rest pose cua `rig` theo bo ref. Tra ve (bao cao, loi)."""
    now = generate.snapshot(ref)
    parts = {key: {base: bone.name for base, bone in group.items()}
             for key, group in refrig.parts_in(ref).items()}
    roll = any(limb.has_roll(rig) for limb in rigdef.limbs_for(rig))
    plan, error = generate.build_plan(now, parts, roll=roll)
    if error:
        return None, error
    then = _baseline_bones(ref, now)
    before = {}
    if then is not None:
        base_plan, _error = generate.build_plan(then, parts, roll=roll)
        before = {row[0]: row for row in base_plan}

    pinned = _bone_parented(rig)
    inv = rig.matrix_world.inverted()
    rot = inv.to_3x3()

    if context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for obj in list(context.selected_objects):
        obj.select_set(False)
    rig.hide_set(False)
    context.view_layer.objects.active = rig
    rig.select_set(True)

    changed, added = [], []
    bpy.ops.object.mode_set(mode='EDIT')
    try:
        edit = rig.data.edit_bones
        # Tha het noi lien truoc khi dich: dat head cua xuong con dang noi
        # lien la keo luon tail cua cha, va thu tu duyet se quyet dinh ai
        # thang. Noi lai o cuoi — luc do head con da trung tail cha.
        joined = {eb.name: eb.use_connect for eb in edit}
        for eb in edit:
            eb.use_connect = False

        for name, head, tail, parent, connect, deform, collection, z_axis in plan:
            eb = edit.get(name)
            want_z = None
            if z_axis is not None and z_axis.length > 1e-6:
                want_z = (rot @ z_axis).normalized()
            if eb is None:
                eb = edit.new(name)
                eb.head, eb.tail = inv @ head, inv @ tail
                eb.use_deform = deform
                if want_z is not None:
                    eb.align_roll(want_z)
                else:
                    generate._align_roll(eb)
                added.append((name, parent, connect, collection))
                continue

            old = before.get(name)
            if old is not None:
                new_head = eb.head + rot @ (head - old[1])
                new_tail = eb.tail + rot @ (tail - old[2])
                turned = (want_z is not None and old[7] is not None
                          and (z_axis - old[7]).length > EPS_AXIS)
            else:
                new_head, new_tail = inv @ head, inv @ tail
                turned = (want_z is not None
                          and (eb.z_axis.normalized() - want_z).length > EPS_AXIS)
            moved = ((new_head - eb.head).length > EPS
                     or (new_tail - eb.tail).length > EPS)
            if not moved and not turned:
                continue
            # Khong co lenh roll tu ban ve (control, pole, lan chan) thi giu
            # nguyen huong Z dang co — rig lam tay co roll rieng cua no.
            keep_z = eb.z_axis.copy()
            eb.head, eb.tail = new_head, new_tail
            eb.align_roll(want_z if turned or (want_z is not None and old is None)
                          else keep_z)
            changed.append(name)

        for name, parent, connect, _c in added:
            if parent and parent in edit:
                edit[name].parent = edit[parent]
                joined[name] = connect
        for name, value in joined.items():
            eb = edit.get(name)
            if eb is not None and value and eb.parent is not None:
                eb.use_connect = True
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')

    for name, _p, _c, collection in added:
        group = rig.data.collections_all.get(collection) \
            or rig.data.collections.new(collection)
        group.assign(rig.data.bones[name])
        rig.pose.bones[name].rotation_mode = 'QUATERNION'

    context.view_layer.update()
    for obj, matrix in pinned:
        obj.matrix_world = matrix

    if added:
        build.apply_logic(context, rig)
        generate.assign_widgets(context, rig, overwrite=False)

    touched = set(changed) | {n for n, *_r in added}
    calibrated = 0
    for limb in rigdef.limbs_for(rig):
        if touched & set(limb.bones() + limb.roll):
            _result, error = snap.calibrate_pole(context, rig, limb)
            if not error:
                calibrated += 1
    failures = build.verify_switching(context, rig) if touched else []

    refrig.store_baseline(ref)
    stale = [n for n in now if n not in rig.data.bones
             and n not in {a[0] for a in added}]
    return dict(changed=changed, added=[a[0] for a in added],
                pinned=[o.name for o, _m in pinned], calibrated=calibrated,
                failures=failures, absolute=then is None, stale=stale), None


# ----------------------------------------------------------- operators

class SRP_OT_ref_from_rig(bpy.types.Operator):
    """Dựng lại bộ xương ref từ chính rig đang có — kể cả rig đã bind skin.
    Sửa bộ ref xong thì bấm 'Cập nhật rig từ ref' ở mục 4"""
    bl_idname = "srp.ref_from_rig"
    bl_label = "Chỉnh lại vị trí xương của rig"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (rigdef.active_rig(context) is not None
                and refrig.find_ref(context) is None)

    def execute(self, context):
        rig = rigdef.active_rig(context)
        ref, count = ref_from_rig(context, rig)
        if ref is None:
            self.report({'ERROR'}, "%s không có xương nào khớp bản vẽ" % rig.name)
            return {'CANCELLED'}
        missing = refrig.missing_core(ref)
        message = "Đã dựng %s: %d xương ref từ %s" % (ref.name, count, rig.name)
        if missing:
            message += " | thiếu %s" % ", ".join(
                refrig.PART_BY_KIND[k]['label'] for k in missing)
        self.report({'WARNING'} if missing else {'INFO'}, message)
        return {'FINISHED'}


class SRP_OT_ref_apply(bpy.types.Operator):
    """Dời xương của rig đang có theo bộ ref — sửa tại chỗ, không dựng rig mới.
    Giữ nguyên skin, weight, driver, animation; vật gắn cứng vào xương
    (nhãn cầu, mũ) đứng yên"""
    bl_idname = "srp.ref_apply"
    bl_label = "Cập nhật rig từ ref"
    bl_options = {'REGISTER', 'UNDO'}

    rebind: BoolProperty(
        name="Bind lại weight", default=False,
        description="Chạy lại Bind skin sau khi dời xương. TẮT mặc định: bind "
                    "lại là GHI ĐÈ toàn bộ weight trên mesh thân, mọi chỗ đã tô "
                    "tay đều mất. Chỉ bật khi weight đang là automatic weights")

    @classmethod
    def poll(cls, context):
        return (refrig.find_ref(context) is not None
                and rigdef.active_rig(context) is not None)

    def execute(self, context):
        ref = refrig.find_ref(context)
        rig = rigdef.active_rig(context)
        if context.mode != 'OBJECT':
            # Thoat Edit Mode cua bo ref TRUOC: chua thoat thi bone data chua
            # nhan cac xuong vua keo, va ta doc phai ban cu.
            bpy.ops.object.mode_set(mode='OBJECT')
        result, error = apply_ref(context, ref, rig)
        if error:
            self.report({'ERROR'}, error)
            return {'CANCELLED'}

        changed, added = result['changed'], result['added']
        if not changed and not added and not self.rebind:
            self.report({'INFO'}, "Bộ ref không đổi gì so với %s" % rig.name)
            return {'FINISHED'}
        message = "%s: dời %d xương" % (rig.name, len(changed))
        if added:
            message += ", thêm %d xương" % len(added)
        if result['calibrated']:
            message += " | đo lại pole %d chi" % result['calibrated']
        if result['pinned']:
            message += " | giữ yên %s" % ", ".join(result['pinned'])
        if result['absolute']:
            message += " | bộ ref cũ chưa có ảnh chụp, đặt theo toạ độ tuyệt đối"
        if result['stale']:
            message += " | %d xương ref không có trên rig" % len(result['stale'])

        if self.rebind:
            settings = context.scene.srp_generate
            if settings.target_mesh is None:
                settings.target_mesh = generate.bound_mesh(context, rig)
            if settings.target_mesh is None:
                message += " | chưa chọn mesh nên không bind lại"
            else:
                bpy.ops.srp.bind(drop_ref=False)
                message += " | đã bind lại weight %s" % settings.target_mesh.name
        else:
            message += " | weight giữ nguyên"
            fresh = [n for n in added if rig.data.bones[n].use_deform]
            if fresh:
                # Xuong deform moi chua co vertex nao — nhac de khong ai tuong
                # no hong khi xoay ma da khong theo.
                message += (" | %d xương deform mới chưa có weight: tô tay "
                            "hoặc bật 'Bind lại weight'" % len(fresh))

        if result['failures']:
            self.report({'ERROR'}, message + " | FK↔IK hỏng: %s"
                        % result['failures'][0])
            return {'FINISHED'}
        self.report({'INFO'}, message)
        return {'FINISHED'}


CLASSES = (SRP_OT_ref_from_rig, SRP_OT_ref_apply)
