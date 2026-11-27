"""Face rig bằng BENDY BONE -- điều khiển biểu cảm hoàn toàn bằng xương, không
shape key, và vẫn xuất được sang game engine.

Game engine không hiểu bendy bone, nên chia hai lớp:
- Lớp điều khiển (chỉ trong Blender): mỗi đường trên mặt (mày, mí, môi) là một
  chuỗi bendy bone nối giữa vài control. Kéo control là đường cong theo.
- Lớp deform (vào game): chính các xương mặt đang skin vào da. Mỗi xương gắn vào
  một KHỚP NỐI bám đúng một điểm trên đường cong (Copy Transforms + Follow
  B-Bone). Lúc xuất, addon lấy mẫu từng frame các xương deform này thành
  animation xương thường.

Weight không đổi một vertex nào. Khớp nối được đặt trùng tư thế mà đường cong
cho ra ở tư thế nghỉ, nên dựng xong mặt không xê dịch.

Mí mắt: đường cong kéo mí đi THẲNG, nhãn cầu thì lồi -- nhắm mắt là mí cắt qua
nhãn cầu, rách mép (đo trên Adult). Nên xương mí treo dưới một cần xoay quanh
tâm nhãn cầu, cần luôn chĩa vào điểm trên đường cong: mí quay ôm theo mắt.
"""

import bpy
from bpy.props import EnumProperty
from bpy.types import Operator
from mathutils import Matrix, Vector

from . import rigdef

CTRL, SEG, SOCK, MCH = "FCtl_", "FBB_", "FSk_", "FMch_"
LID_AIM = MCH + "LidAim_"
LID_REF, LID_PUSH = MCH + "LidRef_", MCH + "LidPush_"
LID_PUSH_RATE = 0.2    # mí nhắm đẩy ra xa tâm mắt: phần bán kính / radian
PREFIXES = (CTRL, SEG, SOCK, MCH)
COLL_CTRL, COLL_MCH = "Face Controls", "Face Mechanism"
ORIG_PARENT = "srp_orig_parent"
SEGMENTS = 8            # đoạn uốn mỗi bendy bone
CORNER_JAW = 0.5        # khoé miệng đi theo hàm bao nhiêu


def _names(B, base, side):
    """Xương `base.side`, `base.side.001`, ... có thật trong rig."""
    out = []
    n = "%s.%s" % (base, side)
    if n in B:
        out.append(n)
    for i in range(1, 10):
        m = "%s.%s.%03d" % (base, side, i)
        if m in B:
            out.append(m)
    return out


def curves(arm):
    """Các đường cần dựng: [(tên, [(tên control, vị trí)], [xương deform], cha control)].
    Control trùng tên (góc mí, khoé miệng) được hai đường dùng chung."""
    B = arm.data.bones
    H = lambda n: B[n].head_local.copy()
    out = []
    for s in ('L', 'R'):
        brow = sorted(_names(B, "Eyebrow", s), key=lambda n: abs(B[n].head_local.x))
        if len(brow) >= 2:
            mid = brow[len(brow) // 2]
            pts = [("Brow_In.%s" % s, H(brow[0])), ("Brow_Mid.%s" % s, H(mid)),
                   ("Brow_Out.%s" % s, H(brow[-1]))]
            out.append(("Brow.%s" % s, pts, brow, "Head"))
        inner, outer = "Eyelid_Inner.%s" % s, "Eyelid_Outer.%s" % s
        if inner in B and outer in B:
            for part in ("Upper", "Lower"):
                mids = sorted(_names(B, "Eyelid_" + part, s), key=lambda n: abs(B[n].head_local.x))
                if not mids:
                    continue
                c = sum((H(n) for n in mids), Vector()) / len(mids)
                pts = [("Lid_In.%s" % s, H(inner)), ("Lid_%s.%s" % (part, s), c),
                       ("Lid_Out.%s" % s, H(outer))]
                bones = ([inner] + mids + [outer]) if part == "Upper" else mids
                out.append(("Lid_%s.%s" % (part, s), pts, bones, "Head"))
    for part, parent in (("Upper", "Head"), ("Lower", "Jaw")):
        mid = "Lip_%s_Mid" % part
        R = sorted(_names(B, "Lip_" + part, 'R'), key=lambda n: B[n].head_local.x)
        L = sorted(_names(B, "Lip_" + part, 'L'), key=lambda n: B[n].head_local.x)
        if mid not in B or not R or not L or parent not in B:
            continue
        other = "Lip_Lower" if part == "Upper" else "Lip_Upper"
        oR = sorted(_names(B, other, 'R'), key=lambda n: B[n].head_local.x)
        oL = sorted(_names(B, other, 'L'), key=lambda n: B[n].head_local.x)
        # khoé miệng: giữa xương ngoài cùng của môi trên và môi dưới -- dùng chung
        cr = (H(R[0]) + H(oR[0] if oR else R[0])) * 0.5
        cl = (H(L[-1]) + H(oL[-1] if oL else L[-1])) * 0.5
        rm = R[len(R) // 2] if len(R) > 1 else R[0]
        lm = L[len(L) // 2] if len(L) > 1 else L[0]
        pts = [("Lip_Corner.R", cr), ("Lip_%s.R" % part, H(rm)), ("Lip_%s_Mid" % part, H(mid)),
               ("Lip_%s.L" % part, H(lm)), ("Lip_Corner.L", cl)]
        out.append(("Lip_%s" % part, pts, R + [mid] + L, parent))
    return out


def has_layer(arm):
    return any(b.name.startswith(PREFIXES) for b in arm.data.bones)


def _project(p, pts):
    """(đoạn, t) gần nhất của điểm p trên đường gấp khúc pts."""
    best = (0, 0.0, 1e30)
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        ab = b - a
        t = max(0.0, min(1.0, (p - a).dot(ab) / max(ab.length_squared, 1e-12)))
        d = (p - (a + ab * t)).length
        if d < best[2]:
            best = (i, t, d)
    return best[0], best[1]


def _collection(arm, name, visible):
    c = arm.data.collections_all.get(name) or arm.data.collections.new(name)
    c.is_visible = visible
    return c


def _rest_pose(arm):
    saved = {pb.name: pb.matrix_basis.copy() for pb in arm.pose.bones}
    for pb in arm.pose.bones:
        pb.matrix_basis = Matrix()
    return saved


def build(context, arm):
    """Dựng lớp bendy bone. Trả về (số control, số xương deform gắn vào, sai số mm)."""
    from . import widgets
    if has_layer(arm):
        remove(context, arm)
    spec = curves(arm)
    if not spec:
        raise ValueError("Rig không có xương mặt theo quy ước (Eyebrow / Eyelid / Lip)")
    B = arm.data.bones
    unit = B["Head"].length if "Head" in B else 0.1
    clen = unit * 0.12
    prev_mode = context.mode
    for o in list(context.selected_objects):
        o.select_set(False)
    context.view_layer.objects.active = arm
    arm.select_set(True)
    saved = _rest_pose(arm)

    # ---- lượt 1: control, khoé miệng, đoạn bendy, khớp nối
    bpy.ops.object.mode_set(mode='EDIT')
    E = arm.data.edit_bones
    made_ctrl, corner_mch = {}, {}
    seg_names = {}
    socks = []                       # (khớp nối, xương deform, đoạn, t)
    jaw = "Jaw" if "Jaw" in E else None
    for name, pts, bones, parent in spec:
        cnames = []
        for cn, p in pts:
            full = CTRL + cn
            if full not in E:
                eb = E.new(full)
                eb.head = p
                eb.tail = p + Vector((0, -clen, 0))
                eb.use_deform = False
                par = parent
                if cn.startswith("Lip_Corner") and jaw is not None:
                    mn = MCH + cn
                    m = E.new(mn)
                    m.head, m.tail, m.use_deform = p, p + Vector((0, -clen, 0)), False
                    m.parent = E["Head"]
                    corner_mch[mn] = True
                    eb.parent = m
                else:
                    eb.parent = E[par]
                made_ctrl[full] = cn
            cnames.append(full)
        segs = []
        for i in range(len(cnames) - 1):
            sn = "%s%s.%d" % (SEG, name, i)
            s = E.new(sn)
            s.head, s.tail = E[cnames[i]].head.copy(), E[cnames[i + 1]].head.copy()
            s.align_roll(Vector((0, -1, 0)))
            s.parent = E[cnames[i]]
            s.use_deform = False
            s.bbone_segments = SEGMENTS
            segs.append(sn)
        for i, sn in enumerate(segs):
            s = E[sn]
            if i > 0:
                s.bbone_handle_type_start = 'ABSOLUTE'
                s.bbone_custom_handle_start = E[segs[i - 1]]
            if i < len(segs) - 1:
                s.bbone_handle_type_end = 'ABSOLUTE'
                s.bbone_custom_handle_end = E[segs[i + 1]]
        seg_names[name] = (segs, [p for _c, p in pts], cnames)
        line = [p for _c, p in pts]
        for d in bones:
            if (SOCK + d) in E:
                continue                # góc mí: đã gắn vào mí trên
            i, t = _project(E[d].head, line)
            k = E.new(SOCK + d)
            k.head, k.tail = E[d].head.copy(), E[d].tail.copy()
            k.roll = E[d].roll
            k.parent = E[segs[i]]
            k.use_deform = False
            socks.append((SOCK + d, d, segs[i], t))
    # mí: xương deform treo dưới một cần xoay từ tâm nhãn cầu (xem _aim_lids)
    aims = {}
    pivots = {}
    for sd in ('L', 'R'):
        c = eye_center(arm, sd)
        lids = [E[d].head for _sk, d, _s, _t in socks if d.startswith("Eyelid_") and d.endswith("." + sd)]
        if c is None or not lids:
            continue
        radius = sum((h - c).length for h in lids) / len(lids)
        pivots[sd] = (c, radius)
    for sk, d, _s, _t in socks:
        sd = d.split(".")[1] if "." in d else None
        if not d.startswith("Eyelid_") or sd not in pivots or "Head" not in E:
            continue
        c, radius = pivots[sd]
        for pre in (LID_AIM, LID_REF):
            a = E.new(pre + d)
            a.head, a.tail, a.use_deform = c, E[d].head.copy(), False
            a.parent = E["Head"]
        q = E.new(LID_PUSH + d)
        q.head, q.tail, q.use_deform = E[d].head.copy(), E[d].head + Vector((0, -clen, 0)), False
        q.parent = E[LID_AIM + d]
        aims[d] = radius
    bpy.ops.object.mode_set(mode='POSE')

    # ---- ràng buộc
    P = arm.pose.bones
    for name, (segs, _line, cnames) in seg_names.items():
        for i, sn in enumerate(segs):
            c = P[sn].constraints.new('STRETCH_TO')
            c.target, c.subtarget = arm, cnames[i + 1]
            c.volume = 'NO_VOLUME'
    for mn in corner_mch:
        c = P[mn].constraints.new('CHILD_OF')
        c.target, c.subtarget = arm, jaw
        c.influence = CORNER_JAW
        c.inverse_matrix = B[jaw].matrix_local.inverted()
    for sk, _d, sn, t in socks:
        c = P[sk].constraints.new('COPY_TRANSFORMS')
        c.target, c.subtarget = arm, sn
        c.head_tail, c.use_bbone_shape = t, True
    context.view_layer.update()
    rest = {sk: P[sk].matrix.copy() for sk, _d, _s, _t in socks}

    # ---- lượt 2: khớp nối trùng điểm đường cong ở tư thế nghỉ, gắn xương deform
    bpy.ops.object.mode_set(mode='EDIT')
    E = arm.data.edit_bones
    orig = {}
    for sk, d, _s, _t in socks:
        k = E[sk]
        length = k.length
        k.matrix = rest[sk]
        k.length = length
        orig[d] = E[d].parent.name if E[d].parent else ""
        if d in aims:
            p = rest[sk].translation
            for pre in (LID_AIM, LID_REF):
                E[pre + d].tail = p
            q = E[LID_PUSH + d]
            q.head, q.tail = p, p + (p - E[LID_AIM + d].head).normalized() * clen
            q.roll = 0.0
            E[d].parent = q
        else:
            E[d].parent = k
    bpy.ops.object.mode_set(mode='POSE')
    for d, p in orig.items():
        arm.data.bones[d][ORIG_PARENT] = p
    _aim_lids(arm, aims)

    # ---- trình bày
    cc, mc = _collection(arm, COLL_CTRL, True), _collection(arm, COLL_MCH, False)
    shape = widgets.build_widget('SPHERE')
    for b in arm.data.bones:
        if b.name.startswith(CTRL):
            cc.assign(b)
            pb = P[b.name]
            pb.custom_shape = shape
            pb.custom_shape_scale_xyz = (0.35, 0.35, 0.35)
            pb.use_custom_shape_bone_size = True
            pb.lock_scale = (False, False, False)
        elif b.name.startswith((SEG, SOCK, MCH)):
            mc.assign(b)
    for b in arm.data.bones:
        if b.name in orig:
            mc.assign(b)                # xương deform mặt: không cầm trực tiếp nữa

    for pb in P:
        if pb.name in saved:
            pb.matrix_basis = saved[pb.name]
    context.view_layer.update()
    err = check_rest(context, arm)
    if prev_mode != 'POSE':
        bpy.ops.object.mode_set(mode='OBJECT')
    return len(made_ctrl), len(orig), err


def eyeball_for(arm, side):
    """Mesh nhãn cầu gắn cứng vào xương Eye.<side> (skin 100% hay parent BONE
    kiểu cũ), hoặc None."""
    from .face import rigid_bone
    bone = "Eye.%s" % side
    for o in bpy.data.objects:
        if o.type == 'MESH' and o.parent is arm and rigid_bone(o, arm) == bone:
            return o
    return None


def eye_center(arm, side):
    """Tâm nhãn cầu trong không gian armature: giữa bounding box của mesh mắt,
    không có mesh thì lấy đầu xương Eye.<side>."""
    eye = eyeball_for(arm, side)
    inv = arm.matrix_world.inverted()
    if eye is not None and eye.data.vertices:
        vs = [inv @ (eye.matrix_world @ v.co) for v in eye.data.vertices]
        lo = Vector([min(v[i] for v in vs) for i in range(3)])
        hi = Vector([max(v[i] for v in vs) for i in range(3)])
        return (lo + hi) * 0.5
    b = arm.data.bones.get("Eye.%s" % side)
    return b.head_local.copy() if b else None


def _aim_lids(arm, aims):
    """Mí quay ôm nhãn cầu.

    Đường cong kéo mí đi thẳng, nhãn cầu thì lồi: nếu xương mí chỉ TRƯỢT theo
    đường cong thì da mí cắt qua mắt. Nên mỗi xương mí treo dưới:
      cần xoay  FMch_LidAim_*  -- gốc ở tâm nhãn cầu, Damped Track vào điểm trên
                                 đường cong: mí quay theo mặt cầu;
      đẩy ra    FMch_LidPush_* -- trượt ra xa tâm theo góc đã quay (driver so
                                 với cần mốc FMch_LidRef_* đứng yên). Da mí
                                 trộn weight với xương đứng yên sẽ "cắt dây cung"
                                 vào trong; đẩy ra bù lại để nhãn cầu không lòi.
    Ở tư thế nghỉ góc quay = 0 nên không lệch gì."""
    P = arm.pose.bones
    for d, radius in aims.items():
        c = P[LID_AIM + d].constraints.new('DAMPED_TRACK')
        c.name = "Ôm nhãn cầu"
        c.target, c.subtarget = arm, SOCK + d
        pb = P[LID_PUSH + d]
        pb.driver_remove("location", 1)
        fc = pb.driver_add("location", 1)
        dr = fc.driver
        dr.type = 'SCRIPTED'
        v = dr.variables.new()
        v.name, v.type = "a", 'ROTATION_DIFF'
        v.targets[0].id, v.targets[0].bone_target = arm, LID_AIM + d
        v.targets[1].id, v.targets[1].bone_target = arm, LID_REF + d
        dr.expression = "a * %.6f" % (radius * LID_PUSH_RATE)
        for m in list(fc.modifiers):
            fc.modifiers.remove(m)


def check_rest(context, arm):
    """Lệch tư thế nghỉ của xương deform mặt (mm) khi mọi control ở rest."""
    saved = _rest_pose(arm)
    context.view_layer.update()
    worst = 0.0
    for b in arm.data.bones:
        if ORIG_PARENT in b.keys():
            M = arm.pose.bones[b.name].matrix
            worst = max(worst, (M.translation - b.matrix_local.translation).length,
                        max((M.col[i].xyz - b.matrix_local.col[i].xyz).length for i in range(3)) * b.length)
    for pb in arm.pose.bones:
        pb.matrix_basis = saved.get(pb.name, Matrix())
    context.view_layer.update()
    return worst * 1000.0 * max(arm.matrix_world.to_scale())


def remove(context, arm):
    """Gỡ lớp bendy bone: xương deform về cha cũ, xoá control / đoạn / khớp nối."""
    prev = context.mode
    for o in list(context.selected_objects):
        o.select_set(False)
    context.view_layer.objects.active = arm
    arm.select_set(True)
    orig = {b.name: b[ORIG_PARENT] for b in arm.data.bones if ORIG_PARENT in b.keys()}
    ad = arm.animation_data
    if ad is not None:
        for fc in list(ad.drivers):
            if any('pose.bones["%s' % pre in fc.data_path for pre in PREFIXES):
                ad.drivers.remove(fc)
    bpy.ops.object.mode_set(mode='EDIT')
    E = arm.data.edit_bones
    for d, p in orig.items():
        if d in E:
            E[d].parent = E.get(p) if p else None
    gone = [eb for eb in E if eb.name.startswith(PREFIXES)]
    for eb in gone:
        E.remove(eb)
    bpy.ops.object.mode_set(mode='POSE')
    for d in orig:
        if d in arm.data.bones:
            del arm.data.bones[d][ORIG_PARENT]
    for cn in (COLL_CTRL, COLL_MCH):
        c = arm.data.collections_all.get(cn)
        if c is not None and not len(c.bones):
            arm.data.collections.remove(c)
    if prev != 'POSE':
        bpy.ops.object.mode_set(mode='OBJECT')
    return len(gone)


class SRP_OT_face_bendy(Operator):
    """Điều khiển khuôn mặt bằng bendy bone: mỗi đường mày, mí, môi thành một
    đường cong kéo bằng vài control; xương mặt đang skin bám theo đường cong.
    Không dùng shape key, xuất sang game engine như xương thường"""
    bl_idname = "srp.face_bendy"
    bl_label = "Face rig bằng bendy bone"
    bl_options = {'REGISTER', 'UNDO'}

    action: EnumProperty(items=(('BUILD', "Dựng", "Dựng (hoặc dựng lại) lớp điều khiển bendy bone"),
                                ('REMOVE', "Gỡ", "Gỡ lớp bendy bone, xương mặt về như cũ")),
                         default='BUILD')

    @classmethod
    def poll(cls, context):
        arm = rigdef.active_rig(context)
        return arm is not None and "Head" in arm.data.bones

    def invoke(self, context, event):
        arm = rigdef.active_rig(context)
        if self.action == 'BUILD' and has_layer(arm):
            return context.window_manager.invoke_confirm(
                self, event, title="Dựng lại face rig bendy bone?",
                message="Lớp bendy bone hiện có sẽ được dựng lại: pose / animation "
                        "đang đặt trên các control mặt sẽ mất.", confirm_text="Dựng lại",
                icon='WARNING')
        return self.execute(context)

    def execute(self, context):
        arm = rigdef.active_rig(context)
        if self.action == 'REMOVE':
            n = remove(context, arm)
            self.report({'INFO'}, "Đã gỡ face rig bendy bone (%d xương)" % n)
            return {'FINISHED'}
        try:
            nc, nd, err = build(context, arm)
        except ValueError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        level = {'INFO'} if err < 0.05 else {'WARNING'}
        self.report(level, "Face rig bendy bone: %d control, %d xương mặt bám theo | "
                           "lệch tư thế nghỉ %.3f mm" % (nc, nd, err))
        return {'FINISHED'}


def draw(L, context):
    arm = rigdef.active_rig(context)
    if arm is None:
        return
    box = L.box()
    row = box.row()
    row.label(text="Face rig bằng bendy bone", icon='IPO_BEZIER')
    if has_layer(arm):
        n = sum(1 for b in arm.data.bones if b.name.startswith(CTRL))
        box.label(text="Đang dùng: %d control mặt (collection '%s')" % (n, COLL_CTRL), icon='CHECKMARK')
        r = box.row(align=True)
        r.operator("srp.face_bendy", text="Dựng lại", icon='FILE_REFRESH').action = 'BUILD'
        r.operator("srp.face_bendy", text="Gỡ", icon='X').action = 'REMOVE'
        box.label(text="Xuất Unity: tắt 'Chỉ xương Humanoid' để giữ xương mặt", icon='INFO')
    else:
        box.label(text="Mày, mí, môi kéo bằng đường cong -- không cần shape key", icon='INFO')
        box.operator("srp.face_bendy", text="Dựng face rig bendy bone", icon='ADD').action = 'BUILD'


CLASSES = (SRP_OT_face_bendy,)
