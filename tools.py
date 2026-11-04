"""Cong cu dung hang ngay — nham cat bot thao tac lap di lap lai.

Uu tien nhung thu RIENG cua rig nay, vi phan do khong addon ngoai nao lam ho:
gan action dung slot, tween biet slerp, key dung nhom kenh.
"""

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty
from mathutils import Quaternion

from . import compat, rigdef

ROTATION_PATHS = {
    'QUATERNION': "rotation_quaternion",
    'AXIS_ANGLE': "rotation_axis_angle",
}


def rotation_path(pose_bone):
    return ROTATION_PATHS.get(pose_bone.rotation_mode, "rotation_euler")


def target_bones(context, rig):
    """Xuong dang chon, khong chon cai nao thi lay moi control dang hien."""
    chosen = [pb for pb in rig.pose.bones if pb.select]
    if chosen:
        return chosen
    return [pb for pb in rig.pose.bones
            if pb.custom_shape is not None and not pb.bone.hide
            and (not len(pb.bone.collections)
                 or any(c.is_visible for c in pb.bone.collections))]


def _ensure_pose(context, rig):
    if context.mode == 'POSE':
        return True
    context.view_layer.objects.active = rig
    try:
        rig.select_set(True)
        bpy.ops.object.mode_set(mode='POSE')
    except RuntimeError:
        return False
    return True


# ---------------------------------------------------------------- action

def action_items(self, context):
    """Action GAN DUOC cho rig nay.

    Tieu chi la TUONG THICH (phan lon ten xuong co that trong rig), khong
    phai "thuoc ve rig nao" nhu ben health. Ba rig trong file dung chung bo
    xuong loi nen action cua rig 216 xuong van chay tot tren rig 109 xuong —
    loc theo kieu so huu thi danh sach rong tron.
    """
    rig = rigdef.active_rig(context)
    if rig is None:
        return [('NONE', "không có rig", "")]
    names = {bone.name for bone in rig.data.bones}
    found = []
    for action in bpy.data.actions:
        bones = set()
        for fcurve in compat.action_fcurves(action):
            bone = compat.bone_of(fcurve.data_path)
            if bone:
                bones.add(bone)
        if not bones:
            continue
        score = len(bones & names) / len(bones)
        if score > 0.5:
            found.append((score, action))
    if not found:
        return [('NONE', "không có action nào hợp", "")]
    found.sort(key=lambda pair: pair[1].name)
    return [(a.name, a.name, "%d - %d  (khop %.0f%%)" % (a.frame_range[0],
                                                         a.frame_range[1], s * 100))
            for s, a in found]


class SRP_OT_assign_action(bpy.types.Operator):
    """Gán action và chọn đúng slot.

    Blender 4.4+ dùng slotted action: gán action mà quên chọn slot thì rig
    đứng im, nhìn như action hỏng. Nút này làm cả hai bước.
    """
    bl_idname = "srp.assign_action"
    bl_label = "Gán action"
    bl_options = {'REGISTER', 'UNDO'}

    action_name: EnumProperty(name="Action", items=action_items)
    set_range: BoolProperty(name="Đặt luôn frame range", default=True)

    @classmethod
    def poll(cls, context):
        return rigdef.active_rig(context) is not None

    def execute(self, context):
        rig = rigdef.active_rig(context)
        action = bpy.data.actions.get(self.action_name)
        if action is None:
            self.report({'ERROR'}, "Không tìm thấy action")
            return {'CANCELLED'}
        slot = compat.assign_action(rig, action)
        if self.set_range:
            start, end = action.frame_range
            context.scene.frame_start = int(start)
            context.scene.frame_end = int(end)
        self.report({'INFO'}, "%s | slot: %s%s" % (
            action.name, getattr(slot, "name_display", "?"),
            " | range %d-%d" % (context.scene.frame_start, context.scene.frame_end)
            if self.set_range else ""))
        return {'FINISHED'}


# ------------------------------------------------------------ doi xung

class SRP_OT_mirror_pose(bpy.types.Operator):
    "Lật pose sang bên kia (copy rồi paste flipped)"
    bl_idname = "srp.mirror_pose"
    bl_label = "Lật pose sang bên kia"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        rig = rigdef.active_rig(context)
        return rig is not None and any(pb.select for pb in rig.pose.bones)

    def execute(self, context):
        rig = rigdef.active_rig(context)
        if not _ensure_pose(context, rig):
            self.report({'ERROR'}, "Không vào được Pose Mode")
            return {'CANCELLED'}
        count = sum(1 for pb in rig.pose.bones if pb.select)
        try:
            bpy.ops.pose.copy()
            bpy.ops.pose.paste(flipped=True)
        except RuntimeError as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        self.report({'INFO'}, "Lat %d xuong sang ben doi dien" % count)
        return {'FINISHED'}


class SRP_OT_select_mirror(bpy.types.Operator):
    "Chọn thêm các xương đối xứng bên kia"
    bl_idname = "srp.select_mirror"
    bl_label = "Chọn cả bên kia"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return rigdef.active_rig(context) is not None

    def execute(self, context):
        rig = rigdef.active_rig(context)
        if not _ensure_pose(context, rig):
            return {'CANCELLED'}
        try:
            bpy.ops.pose.select_mirror(extend=True)
        except RuntimeError as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        self.report({'INFO'}, "Đang chọn %d xương"
                    % sum(1 for pb in rig.pose.bones if pb.select))
        return {'FINISHED'}


# --------------------------------------------------------------- reset

class SRP_OT_reset(bpy.types.Operator):
    "Đưa transform về rest — xương đang chọn, hoặc cả rig"
    bl_idname = "srp.reset"
    bl_label = "Reset về rest"
    bl_options = {'REGISTER', 'UNDO'}

    whole_rig: BoolProperty(name="Cả rig", default=False)

    @classmethod
    def poll(cls, context):
        return rigdef.active_rig(context) is not None

    def execute(self, context):
        rig = rigdef.active_rig(context)
        bones = rig.pose.bones if self.whole_rig else target_bones(context, rig)
        for pose_bone in bones:
            pose_bone.matrix_basis.identity()
        compat.refresh(context, rig)
        self.report({'INFO'}, "Reset %d xuong" % len(list(bones)))
        return {'FINISHED'}


# ------------------------------------------------------------------ key

def insert_keys(pose_bone, frame, location=True, rotation=True, scale=False):
    made = 0
    paths = []
    if location:
        paths.append("location")
    if rotation:
        paths.append(rotation_path(pose_bone))
    if scale:
        paths.append("scale")
    for path in paths:
        try:
            if pose_bone.keyframe_insert(data_path=path, frame=frame,
                                         group=pose_bone.name):
                made += 1
        except RuntimeError:
            pass
    return made


class SRP_OT_key(bpy.types.Operator):
    "Ghi key cho xương đang chọn (không chọn gì thì ghi cả bộ control)"
    bl_idname = "srp.key"
    bl_label = "Ghi key"
    bl_options = {'REGISTER', 'UNDO'}

    location: BoolProperty(name="Vị trí", default=True)
    rotation: BoolProperty(name="Xoay", default=True)
    scale: BoolProperty(name="Tỷ lệ", default=False,
                        description="Mặc định tắt — key scale làm phình action "
                                    "mà hiếm khi dùng")

    @classmethod
    def poll(cls, context):
        return rigdef.active_rig(context) is not None

    def execute(self, context):
        rig = rigdef.active_rig(context)
        bones = target_bones(context, rig)
        frame = context.scene.frame_current
        made = sum(insert_keys(pb, frame, self.location, self.rotation, self.scale)
                   for pb in bones)
        self.report({'INFO'}, "%d kênh trên %d xương, frame %d"
                    % (made, len(bones), frame))
        return {'FINISHED'}


# ------------------------------------------------- nhay giua cac keyframe

def keyed_frames(rig, bones):
    """Moc thoi gian co key cua nhung xuong nay."""
    anim = rig.animation_data
    if anim is None or anim.action is None:
        return []
    slot = compat.action_slot_for(anim.action, rig)
    wanted = {pb.name for pb in bones}
    frames = set()
    for fcurve in compat.action_fcurves(anim.action, slot):
        name = compat.bone_of(fcurve.data_path)
        if name in wanted:
            frames.update(round(point.co[0], 4) for point in fcurve.keyframe_points)
    return sorted(frames)


class SRP_OT_jump_key(bpy.types.Operator):
    "Nhảy tới key trước/sau của riêng những xương đang chọn"
    bl_idname = "srp.jump_key"
    bl_label = "Nhảy key"
    bl_options = {'REGISTER', 'UNDO'}

    forward: BoolProperty(name="Về sau", default=True)

    @classmethod
    def poll(cls, context):
        rig = rigdef.active_rig(context)
        return rig is not None and rig.animation_data is not None \
            and rig.animation_data.action is not None

    def execute(self, context):
        rig = rigdef.active_rig(context)
        frames = keyed_frames(rig, target_bones(context, rig))
        if not frames:
            self.report({'WARNING'}, "Xương đang chọn không có key nào")
            return {'CANCELLED'}
        current = context.scene.frame_current
        if self.forward:
            later = [f for f in frames if f > current]
            target = later[0] if later else frames[0]
        else:
            earlier = [f for f in frames if f < current]
            target = earlier[-1] if earlier else frames[-1]
        context.scene.frame_set(int(round(target)))
        return {'FINISHED'}


# ---------------------------------------------------------------- tween

def _channel_groups(action, slot, bones):
    """Gom fcurve theo (ten xuong, data_path) de xu ly ca nhom mot luot."""
    wanted = {pb.name for pb in bones}
    groups = {}
    for fcurve in compat.action_fcurves(action, slot):
        name = compat.bone_of(fcurve.data_path)
        if name in wanted:
            groups.setdefault((name, fcurve.data_path), []).append(fcurve)
    return groups


def _bracket(fcurve, frame):
    """(key truoc, key sau) bao quanh frame; None neu khong du hai ben."""
    before = after = None
    for point in fcurve.keyframe_points:
        time = point.co[0]
        if time <= frame and (before is None or time > before.co[0]):
            before = point
        if time >= frame and (after is None or time < after.co[0]):
            after = point
    if before is None or after is None or before.co[0] == after.co[0]:
        return None
    return before, after


def tween(context, rig, factor, bones=None):
    """Dat pose hien tai thanh pha tron giua key truoc va key sau.

    Quaternion phai SLERP, khong duoc lerp tung thanh phan — lerp 4 so roi
    chuan hoa se cho ra duong xoay sai, va o goc lon thi tay chan quay nguoc.
    Day la loi da tra gia trong quy trinh polish nen o day lam dung ngay.
    """
    anim = rig.animation_data
    if anim is None or anim.action is None:
        return None, "chua gan action nao"
    slot = compat.action_slot_for(anim.action, rig)
    bones = bones if bones is not None else target_bones(context, rig)
    frame = context.scene.frame_current
    groups = _channel_groups(anim.action, slot, bones)
    if not groups:
        return None, "xương đang chọn không có curve nào"

    touched = 0
    for (_name, path), curves in groups.items():
        curves.sort(key=lambda fc: fc.array_index)
        brackets = [_bracket(fc, frame) for fc in curves]
        if any(b is None for b in brackets):
            continue

        if path.endswith("rotation_quaternion") and len(curves) == 4:
            start = Quaternion([b[0].co[1] for b in brackets])
            end = Quaternion([b[1].co[1] for b in brackets])
            blended = start.slerp(end, factor)
            values = [blended.w, blended.x, blended.y, blended.z]
        else:
            values = [b[0].co[1] + (b[1].co[1] - b[0].co[1]) * factor
                      for b in brackets]

        for fcurve, value in zip(curves, values):
            fcurve.keyframe_points.insert(frame, value, options={'NEEDED'})
            fcurve.update()
        touched += 1
    return touched, None


class SRP_OT_tween(bpy.types.Operator):
    "Tạo pose trung gian giữa key trước và key sau, rồi ghi key luôn"
    bl_idname = "srp.tween"
    bl_label = "Tween"
    bl_options = {'REGISTER', 'UNDO'}

    factor: FloatProperty(name="Nghiêng về", default=0.5, min=0.0, max=1.0,
                          subtype='FACTOR',
                          description="0 = giống hệt key trước, 1 = giống hệt "
                                      "key sau")

    @classmethod
    def poll(cls, context):
        rig = rigdef.active_rig(context)
        return rig is not None and rig.animation_data is not None \
            and rig.animation_data.action is not None

    def execute(self, context):
        rig = rigdef.active_rig(context)
        result, error = tween(context, rig, self.factor)
        if error:
            self.report({'WARNING'}, error)
            return {'CANCELLED'}
        compat.refresh(context, rig)
        self.report({'INFO'}, "Tween %.0f%% tren %d kenh, frame %d"
                    % (self.factor * 100, result, context.scene.frame_current))
        return {'FINISHED'}


CLASSES = (SRP_OT_assign_action, SRP_OT_mirror_pose, SRP_OT_select_mirror,
           SRP_OT_reset, SRP_OT_key, SRP_OT_jump_key, SRP_OT_tween)
