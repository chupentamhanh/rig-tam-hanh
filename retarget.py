"""Retarget animation từ một bộ xương nguồn sang rig Rig Tẩm Hành.

Nguồn: armature bất kỳ trong file -- Mixamo FBX, BVH mocap, FBX khác, hay rig
Rig Tẩm Hành khác (Kid / Adult). Nút "Nhập file…" gọi importer FBX / BVH của
Blender.

Ghép xương: bảng Humanoid (unityexport.auto_map) cho cả hai bên -- đoán được
mixamorig:*, tên BVH (LeftUpLeg, LeftForeArm…), quy ước Rig Tẩm Hành. Sai thì
sửa trong text block SRP_Retarget_Map (dòng "LeftHand = tên bone NGUỒN").

Cách chép: mỗi frame, mỗi bone Humanoid của đích nhận đúng ĐỘ XOAY (hệ thế
giới) mà bone nguồn đã xoay so với tư thế nghỉ của nó:
    R_đích = Δ_nguồn · A · R_nghỉ_đích,   Δ_nguồn = R_nguồn · R_nghỉ_nguồn⁻¹
A xoay hướng xương đích lúc nghỉ về hướng xương nguồn lúc nghỉ, nên tư thế
nghỉ khác nhau (A-pose / T-pose) không làm lệch. Hai bên nhìn khác hướng thì
xoay nguồn quanh trục đứng cho cùng hướng trước. Hông dịch theo tỉ lệ độ cao
hông (đích / nguồn): nhân vật chibi chân ngắn bước ngắn lại, chân không trượt.

Bake: thân, cổ, đầu, vai, ngón, mũi chân key thẳng; tay / chân key vào chuỗi
FK (xương deform chi chép xoay của FK / IK). Chi để IK thì từng frame snap IK
theo FK (snap.snap_ik_to_fk) rồi key control IK + pole. Kết quả là một action
mới "<action nguồn>_<rig>" có slot cho rig, chỉnh tiếp được bằng FK / IK.
"""

import math
import os

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import Operator, PropertyGroup
from mathutils import Matrix, Quaternion, Vector

from . import compat, rigdef, snap, unityexport as UE

MAP_TEXT = "SRP_Retarget_Map"
SKIP = {'LeftEye', 'RightEye'}
# thân / cổ / đầu / hàm: hai nhân vật đều đứng thẳng lúc nghỉ, chép thẳng độ xoay.
# KHÔNG nắn hướng xương ở đây: xương gốc mỗi rig đặt một kiểu (Hips của
# Cat_Rig nằm ngang, của Mixamo dựng đứng) -- nắn là khung chậu xoay 90°.
AXIAL = {'Hips', 'Spine', 'Chest', 'UpperChest', 'Neck', 'Head', 'Jaw'}
_LIN = 1


# ============================================================ ghép xương

def overrides():
    t = bpy.data.texts.get(MAP_TEXT)
    out = {}
    if t is None:
        return out
    for line in t.as_string().splitlines():
        line = line.split('#', 1)[0]
        if '=' in line:
            k, v = (x.strip() for x in line.split('=', 1))
            if k in UE.HUMAN_PARENTS or k == 'Hips':
                out[k] = v or None
    return out


def source_map(src):
    m = UE.auto_map(src)
    for k, v in overrides().items():
        if v and v in src.data.bones:
            m[k] = v
        else:
            m.pop(k, None)
    return m


def pairs(src, tgt):
    """[(Humanoid, bone nguồn, bone đích)] theo thứ tự cha trước con."""
    sm, tm = source_map(src), UE.humanoid_map(tgt)
    return [(h, sm[h], tm[h]) for h in UE.HUMAN_ORDER
            if h in sm and h in tm and h not in SKIP]


def write_map(src):
    m = source_map(src)
    t = bpy.data.texts.get(MAP_TEXT) or bpy.data.texts.new(MAP_TEXT)
    t.clear()
    t.write("# Ghép xương NGUỒN (%s) cho retarget. Sửa tên bên phải dấu =,\n" % src.name)
    t.write("# để trống là bỏ bone đó. Bone đích lấy theo bảng Humanoid của rig.\n")
    for h in UE.HUMAN_ORDER:
        if h not in SKIP:
            t.write("%s = %s\n" % (h, m.get(h, "")))
    return t


# ============================================================ hình học nghỉ

def _rest_world(arm, name):
    return arm.matrix_world @ arm.data.bones[name].matrix_local


def _rot(M):
    return M.to_3x3().normalized().to_quaternion()


def _dir(arm, m, h, name):
    """Hướng xương lúc nghỉ (thế giới): tới đầu bone Humanoid con nếu có, không
    thì tới con đầu tiên, không thì tới đuôi bone."""
    B = arm.data.bones
    b = B[name]
    head = arm.matrix_world @ b.head_local
    kids = [k for k, ps in UE.HUMAN_PARENTS.items() if ps and ps[0] == h and k in m]
    pref = {'Hips': 'Spine', 'LeftHand': 'Left Middle Proximal', 'RightHand': 'Right Middle Proximal',
            'LeftFoot': 'LeftToes', 'RightFoot': 'RightToes'}.get(h)
    if pref in m:
        kids = [pref]
    for k in kids:
        p = arm.matrix_world @ B[m[k]].head_local
        if (p - head).length > 1e-6:
            return (p - head).normalized()
    for c in b.children:
        p = arm.matrix_world @ c.head_local
        if (p - head).length > 1e-6:
            return (p - head).normalized()
    return ((arm.matrix_world @ b.tail_local) - head).normalized()


def _facing(arm, m):
    """Hướng nhìn (thế giới, nằm ngang) từ hai khớp háng hoặc hai vai."""
    for l, r in (('LeftUpperLeg', 'RightUpperLeg'), ('LeftUpperArm', 'RightUpperArm')):
        if l in m and r in m:
            v = (arm.matrix_world @ arm.data.bones[m[l]].head_local) - (arm.matrix_world @ arm.data.bones[m[r]].head_local)
            f = v.cross(Vector((0, 0, 1)))
            f.z = 0
            if f.length > 1e-6:
                return f.normalized()
    return Vector((0, -1, 0))


def _digi(arm, m):
    """Rig co chan di bang ngon / mong (ghi tren xuong dui)."""
    b = arm.data.bones.get(m.get('LeftUpperLeg', ''))
    return b is not None and b.get(rigdef.TAG_LEG, 'HUMAN') != 'HUMAN'


def _hip_height(arm, m):
    """Độ cao hông trên bàn chân lúc nghỉ (thế giới)."""
    hip = (arm.matrix_world @ arm.data.bones[m['Hips']].head_local).z
    keys = ('LeftFoot', 'RightFoot')
    if _digi(arm, m) and 'LeftToes' in m and 'RightToes' in m:
        keys = ('LeftToes', 'RightToes')     # chan thu: `Foot` bat dau o hock, cao hon dat
    feet = [(arm.matrix_world @ arm.data.bones[m[k]].head_local).z for k in keys if k in m]
    return hip - (min(feet) if feet else 0.0)


# ============================================================ retarget

def _write_bones(tgt):
    """{bone deform chi: bone FK tương ứng}."""
    out = {}
    for l in rigdef.limbs_for(tgt):
        for d, f in zip(l.deform, l.fk):
            if d in tgt.data.bones and f in tgt.data.bones:
                out[d] = f
    return out


def sample(context, src, action, frames, names):
    """{frame: {bone nguồn: ma trận thế giới}} -- cho nguồn chạy action rồi đọc."""
    anim = src.animation_data or src.animation_data_create()
    old = (anim.action, anim.action_slot if anim.action else None)
    compat.assign_action(src, action)
    sc = context.scene
    out = {}
    try:
        for f in frames:
            sc.frame_set(f)
            ev = src.evaluated_get(context.evaluated_depsgraph_get())
            out[f] = {n: src.matrix_world @ ev.pose.bones[n].matrix for n in names}
    finally:
        anim.action = old[0]
        if old[0] is not None and old[1] is not None:
            anim.action_slot = old[1]
    return out


def solve(src, tgt, pr, poses, in_place=False, scale_root=True):
    """{frame: {bone đích được key: (location, quaternion basis)}}."""
    sm = {h: s for h, s, _t in pr}
    tm = {h: t for h, _s, t in pr}
    Ts, Tt = src.matrix_world, tgt.matrix_world
    Tt_inv = Tt.inverted()
    yaw = _facing(src, sm).rotation_difference(_facing(tgt, tm))      # nguồn -> hướng của đích
    Y = yaw.to_matrix().to_4x4()
    k = 1.0
    if scale_root and 'Hips' in sm:
        hs = _hip_height(src, sm)
        k = _hip_height(tgt, tm) / hs if hs > 1e-6 else 1.0
    fk_of = _write_bones(tgt)
    B = tgt.data.bones
    digi_t = _digi(tgt, tm)
    # lúc nghỉ
    rest = {}
    for h, s, t in pr:
        Rs = _rot(Y @ _rest_world(src, s))
        Rt = _rot(_rest_world(tgt, t))
        # Chan thu gap chu Z: nan thang theo chan nguoi la mat dang chan. Chep do xoay.
        if h in AXIAL or (digi_t and h.endswith(('UpperLeg', 'LowerLeg', 'Foot', 'Toes'))):
            A = Quaternion()
        else:                                 # chi: nắn tư thế nghỉ (A-pose / T-pose)
            A = (yaw @ _dir(src, sm, h, s)).rotation_difference(_dir(tgt, tm, h, t))
            A = A.inverted()                  # hướng đích -> hướng nguồn
        rest[t] = (Rs, Rt, A, s)
    hips_t = tm.get('Hips')
    hips_rest_t = (Tt @ B[hips_t].head_local) if hips_t else None
    hips_rest_s = (Y @ Ts @ src.data.bones[sm['Hips']].head_local) if 'Hips' in sm else None

    order = sorted(B, key=lambda b: len(b.parent_recursive))
    keyed = set(fk_of.get(t, t) for t in rest)
    out = {}
    for f, mats in poses.items():
        want = {}                             # bone đích -> quaternion thế giới mong muốn
        for t, (Rs, Rt, A, s) in rest.items():
            D = _rot(Y @ mats[s]) @ Rs.inverted()
            want[t] = D @ A @ Rt
        hip_pos = None
        if hips_t and hips_rest_s is not None:
            d = (Y @ mats[sm['Hips']]).translation - hips_rest_s
            if in_place:
                d.x = d.y = 0.0
            hip_pos = hips_rest_t + d * k
        M = {}                                # ma trận pose (hệ armature) đã tính
        res = {}
        for b in order:
            rb = b.matrix_local
            if b.parent is not None:
                chain = M[b.parent.name] @ b.parent.matrix_local.inverted() @ rb
            else:
                chain = rb.copy()
            q_world = None
            if b.name in want:
                q_world = want[b.name]
            else:
                # bone FK nhận đúng xoay của bone deform nó điều khiển
                for d, fk in fk_of.items():
                    if fk == b.name and d in want:
                        q_world = want[d] @ _rot(Tt @ B[d].matrix_local).inverted() @ _rot(Tt @ rb)
                        break
            if q_world is None:
                M[b.name] = chain
                continue
            q_arm = _rot(Tt_inv.to_3x3().to_4x4()) @ q_world
            Md = q_arm.to_matrix().to_4x4()
            Md.translation = (Tt_inv @ hip_pos) if (b.name == hips_t and hip_pos is not None) else chain.translation
            M[b.name] = Md
            if b.name in keyed:
                basis = chain.inverted() @ Md
                loc, q, _sc = basis.decompose()
                res[b.name] = (loc if b.name == hips_t else Vector(), q)
        out[f] = res
    return out, k, yaw


def _fcurves(tgt, action, slot, rows, frames):
    bag = compat.action_channelbag(action, slot, create=True)
    P = tgt.pose.bones
    for name in sorted({n for r in rows.values() for n in r}):
        pb = P[name]
        base = 'pose.bones["%s"].' % name
        mode = pb.rotation_mode
        vals_loc, vals_rot, prev = [], [], None
        for f in frames:
            loc, q = rows[f].get(name, (Vector(), Quaternion()))
            if mode == 'QUATERNION':
                if prev is not None:
                    q.make_compatible(prev)
                prev = q
                vals_rot.append(tuple(q))
            elif mode == 'AXIS_ANGLE':
                ax, ang = q.to_axis_angle()
                vals_rot.append((ang,) + tuple(ax))
            else:
                e = q.to_euler(mode, prev) if prev is not None else q.to_euler(mode)
                prev = e
                vals_rot.append(tuple(e))
            vals_loc.append(tuple(loc))
        path = {'QUATERNION': 'rotation_quaternion', 'AXIS_ANGLE': 'rotation_axis_angle'}.get(mode, 'rotation_euler')
        chans = [(path, vals_rot)]
        if any(v.length > 1e-7 for v in (Vector(x) for x in vals_loc)):
            chans.append(('location', vals_loc))
        for p, vals in chans:
            for i in range(len(vals[0])):
                fc = bag.fcurves.new(base + p, index=i)
                fc.keyframe_points.add(len(frames))
                co = []
                for f, v in zip(frames, vals):
                    co += (f, v[i])
                fc.keyframe_points.foreach_set('co', co)
                fc.keyframe_points.foreach_set('interpolation', [_LIN] * len(frames))
                fc.update()


def retarget(context, src, action, tgt, in_place=False, scale_root=True, arms='KEEP', legs='KEEP',
             step=1, name=None):
    """Retarget một action. Trả về (action mới, thông tin)."""
    pr = pairs(src, tgt)
    if not any(h == 'Hips' for h, _s, _t in pr):
        raise ValueError("Không ghép được Hips -- xem text block %s" % MAP_TEXT)
    s, e = (int(round(x)) for x in action.frame_range)
    frames = list(range(s, max(e, s + 1) + 1, max(1, step)))
    if frames[-1] != max(e, s + 1):
        frames.append(max(e, s + 1))
    sc = context.scene
    keep = (sc.frame_current, sc.frame_start, sc.frame_end)
    poses = sample(context, src, action, frames, {p[1] for p in pr})
    rows, k, yaw = solve(src, tgt, pr, poses, in_place, scale_root)

    name = name or "%s_%s" % (action.name.split("|")[-1], tgt.name)
    old = bpy.data.actions.get(name)
    if old is not None:
        bpy.data.actions.remove(old)
    act = bpy.data.actions.new(name)
    slot = act.slots.new('OBJECT', tgt.name)
    _fcurves(tgt, act, slot, rows, frames)
    act.use_cyclic = bool(getattr(action, 'use_cyclic', False))
    act.use_frame_range = True
    act.frame_start, act.frame_end = frames[0], frames[-1]

    # rig về tư thế nghỉ rồi gán action mới: bone không key không giữ pose cũ
    for pb in tgt.pose.bones:
        pb.matrix_basis = Matrix()
    compat.assign_action(tgt, act)

    # IK theo FK
    limbs = rigdef.limbs_for(tgt)
    ik = []
    for l in limbs:
        want = arms if l.kind == 'ARM' else legs
        val = l.switch(tgt) if want == 'KEEP' else (rigdef.IK_VALUE if want == 'IK' else rigdef.FK_VALUE)
        l.set_switch(tgt, val)
        if val >= 0.5:
            ik.append(l)
    prev_active = context.view_layer.objects.active
    try:
        context.view_layer.objects.active = tgt
        if ik:
            for f in frames:
                sc.frame_set(f)
                for l in ik:
                    snap.snap_ik_to_fk(context, tgt, l)
                    snap.key_ik(tgt, l, f)
        for l in limbs:
            snap.key_switch(tgt, l, frames[0])
    finally:
        context.view_layer.objects.active = prev_active
        sc.frame_start, sc.frame_end = frames[0], frames[-1]
        sc.frame_set(frames[0])
    info = dict(pairs=len(pr), frames=len(frames), scale=k, yaw=math.degrees(yaw.angle),
                ik=[l.label for l in ik])
    return act, info


def upright(src):
    """File lạ trục (BVH ghi Z-up, FBX xuất sai trục) nhập vào thành nằm: xoay
    object cho hông -> đầu chỉ lên +Z. Trả về góc đã xoay (độ)."""
    m = source_map(src)
    top = m.get('Head') or m.get('Neck')
    if 'Hips' not in m or not top:
        return 0.0
    B = src.data.bones
    v = (src.matrix_world @ B[top].head_local) - (src.matrix_world @ B[m['Hips']].head_local)
    if v.length < 1e-9 or v.normalized().dot(Vector((0, 0, 1))) > math.cos(math.radians(30)):
        return 0.0
    q = v.normalized().rotation_difference(Vector((0, 0, 1)))
    loc = src.matrix_world.translation.copy()
    src.matrix_world = Matrix.Translation(loc) @ q.to_matrix().to_4x4() @ Matrix.Translation(-loc) @ src.matrix_world
    return math.degrees(q.angle)


# ============================================================ UI / toán tử

def _src_poll(self, ob):
    return ob.type == 'ARMATURE'


def _act_poll(self, a):
    src = self.source
    if src is None:
        return True
    return any(x is a for x, _s in UE.rig_clips(src))


class SRP_RetargetSettings(PropertyGroup):
    source: PointerProperty(type=bpy.types.Object, name="Nguồn", poll=_src_poll,
                            description="Armature mang animation cần chép (Mixamo, BVH, FBX, rig khác)")
    action: PointerProperty(type=bpy.types.Action, name="Animation", poll=_act_poll,
                            description="Animation của nguồn cần chép")
    all_actions: BoolProperty(name="Mọi animation của nguồn", default=False,
                              description="Chép hết các animation có slot cho nguồn, mỗi cái một action mới")
    in_place: BoolProperty(name="Đứng tại chỗ", default=False,
                           description="Bỏ phần hông đi ngang (giữ nhún lên xuống): hợp cho vòng đi / chạy "
                                       "để game tự đẩy nhân vật")
    scale_root: BoolProperty(name="Bù tỉ lệ thân", default=True,
                             description="Hông dịch theo tỉ lệ độ cao hông đích / nguồn: nhân vật chân ngắn "
                                         "bước ngắn lại, chân không trượt / xuyên sàn")
    arms: EnumProperty(name="Tay", default='KEEP',
                       items=(('KEEP', "Như rig đang để", ""), ('FK', "FK", ""), ('IK', "IK", "")))
    legs: EnumProperty(name="Chân", default='KEEP',
                       items=(('KEEP', "Như rig đang để", ""), ('FK', "FK", ""), ('IK', "IK", "")))
    step: IntProperty(name="Mỗi", default=1, min=1, max=10,
                      description="Key mỗi N frame (1 = mọi frame)")


class SRP_OT_retarget_import(Operator):
    """Nhập animation từ file FBX (Mixamo…) hoặc BVH (mocap) làm nguồn retarget"""
    bl_idname = "srp.retarget_import"
    bl_label = "Nhập file animation"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default="*.fbx;*.bvh", options={'HIDDEN'})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        p = self.filepath
        if not os.path.isfile(p):
            self.report({'ERROR'}, "Không thấy file %s" % p)
            return {'CANCELLED'}
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        before = set(bpy.data.objects)
        ext = os.path.splitext(p)[1].lower()
        if ext == '.bvh':
            bpy.ops.import_anim.bvh(filepath=p, rotate_mode='NATIVE', update_scene_fps=False,
                                    update_scene_duration=False)
        elif ext == '.fbx':
            bpy.ops.import_scene.fbx(filepath=p, use_anim=True, automatic_bone_orientation=True,
                                     ignore_leaf_bones=True)
        else:
            self.report({'ERROR'}, "Chỉ nhận .fbx hoặc .bvh")
            return {'CANCELLED'}
        arms = [o for o in bpy.data.objects if o not in before and o.type == 'ARMATURE']
        if not arms:
            self.report({'ERROR'}, "File không có bộ xương")
            return {'CANCELLED'}
        src = arms[0]
        turned = upright(src)
        st = context.scene.srp_retarget
        st.source = src
        clips = UE.rig_clips(src)
        st.action = clips[0][0] if clips else (src.animation_data.action if src.animation_data else None)
        n = len(source_map(src))
        self.report({'INFO'}, "Nhập %s: %d animation, ghép được %d bone Humanoid%s" % (
            src.name, len(clips), n, " | đã dựng đứng (xoay %.0f°)" % turned if turned else ""))
        return {'FINISHED'}


class SRP_OT_retarget_map(Operator):
    """Ghi bảng ghép xương nguồn vào text block SRP_Retarget_Map để xem / sửa tay"""
    bl_idname = "srp.retarget_map"
    bl_label = "Sửa bảng ghép xương"

    def execute(self, context):
        src = context.scene.srp_retarget.source
        tgt = rigdef.active_rig(context)
        if src is None or tgt is None:
            self.report({'ERROR'}, "Chọn nguồn và rig đích trước")
            return {'CANCELLED'}
        write_map(src)
        n = len(pairs(src, tgt))
        self.report({'INFO'}, "%d cặp xương ghép được -- sửa ở text block %s" % (n, MAP_TEXT))
        return {'FINISHED'}


class SRP_OT_retarget(Operator):
    """Chép animation của nguồn sang rig đang chọn, bake ra FK / IK để chỉnh tiếp"""
    bl_idname = "srp.retarget"
    bl_label = "Retarget"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        st = context.scene.srp_retarget
        tgt = rigdef.active_rig(context)
        src = st.source
        if tgt is None or src is None:
            self.report({'ERROR'}, "Chọn nguồn và rig đích trước")
            return {'CANCELLED'}
        if src is tgt:
            self.report({'ERROR'}, "Nguồn và đích là cùng một rig")
            return {'CANCELLED'}
        acts = [a for a, _s in UE.rig_clips(src)] if st.all_actions else ([st.action] if st.action else [])
        if not acts:
            self.report({'ERROR'}, "Nguồn chưa có animation nào")
            return {'CANCELLED'}
        if context.mode != 'OBJECT' and context.mode != 'POSE':
            bpy.ops.object.mode_set(mode='OBJECT')
        made = []
        try:
            for a in acts:
                act, info = retarget(context, src, a, tgt, st.in_place, st.scale_root, st.arms, st.legs, st.step)
                made.append((act, info))
        except ValueError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        act, info = made[-1]
        self.report({'INFO'}, "Retarget %d animation -> %s (%d cặp xương, %d frame, tỉ lệ hông %.2f%s)"
                    % (len(made), act.name, info['pairs'], info['frames'], info['scale'],
                       ", IK: " + ", ".join(info['ik']) if info['ik'] else ""))
        return {'FINISHED'}


def draw(L, context):
    st = context.scene.srp_retarget
    tgt = rigdef.active_rig(context)
    col = L.column(align=True)
    col.operator("srp.retarget_import", icon='IMPORT')
    L.prop(st, "source")
    src = st.source
    if src is not None:
        row = L.row(align=True)
        row.enabled = not st.all_actions
        row.prop(st, "action")
        L.prop(st, "all_actions")
        if tgt is not None and src is not tgt:
            n = len(pairs(src, tgt))
            row = L.row(align=True)
            row.label(text="%d cặp xương ghép được" % n, icon='CHECKMARK' if n >= 15 else 'ERROR')
            row.operator("srp.retarget_map", text="", icon='TEXT')
    col = L.column(align=True)
    col.prop(st, "scale_root")
    col.prop(st, "in_place")
    row = L.row(align=True)
    row.prop(st, "arms")
    row.prop(st, "legs")
    L.prop(st, "step")
    r = L.row()
    r.scale_y = 1.3
    r.enabled = tgt is not None and src is not None and src is not tgt
    r.operator("srp.retarget", text="Retarget sang %s" % (tgt.name if tgt else "rig"), icon='ARMATURE_DATA')


CLASSES = (SRP_RetargetSettings, SRP_OT_retarget_import, SRP_OT_retarget_map, SRP_OT_retarget)


def register_extra():
    bpy.types.Scene.srp_retarget = PointerProperty(type=SRP_RetargetSettings)


def unregister_extra():
    try:
        del bpy.types.Scene.srp_retarget
    except AttributeError:
        pass
