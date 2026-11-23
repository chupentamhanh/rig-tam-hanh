"""Toan bo panel gom o day, chia theo KHU tren thanh chon khu (xem uikit.py).

  Dung  -> Mat -> Dien -> Xuat, roi Sua   (dung thu tu luong lam viec)

Moi luc chi khu dang chon duoc ve. Chi panel GOC mang `zone`; panel con tu an
theo cha. Cac module khac chi cung cap ham `draw_*`, khong tu dinh nghia panel
— de cay phan cap nam gon mot cho, doi thu tu hay gop nhom thi sua mot file.

Chu giai thich khong ve san tren panel nua: dat `help = '<chu de>'` la panel
co nut "?" tren dau, noi dung o `uikit.HELP`.
"""

import bpy

from . import (cloth, face, facebendy, fitref, generate, health, markers, onion, picker, posekey, prefs, refrig,
               remap, retarget, rigdef, uikit, unityexport, ux, weightfence, widgets)


class _Base:
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Rig Tẩm Hành"
    zone = None     # chi panel goc dat
    help = None

    @classmethod
    def poll(cls, context):
        return cls.zone is None or uikit.zone(context) == cls.zone

    def draw_header_preset(self, context):
        uikit.help_button(self.layout, self.help)


class _NeedRig(_Base):
    @classmethod
    def poll(cls, context):
        return super().poll(context) and rigdef.active_rig(context) is not None


class _Step(_Base):
    """Buoc dung rig: chi ve buoc DANG MO (uikit.focus).

    Danh sach buoc o panel cha liet ke du ca bay buoc kem dau xong / khoa, nen
    an cac buoc kia khong lam ai phai doan con thieu gi — ma cot ngan lai con
    mot phan ba.
    """
    step = 0

    @classmethod
    def poll(cls, context):
        return uikit.focus(context) == cls.step


# ============================================================ THANH CHON KHU

class SRP_PT_zone(_Base, bpy.types.Panel):
    bl_label = "Rig Tẩm Hành"
    bl_idname = "SRP_PT_zone"
    bl_options = {'HIDE_HEADER'}

    def draw(self, context):
        uikit.draw_zone_bar(self.layout, context)
        ux.draw_next(self.layout, context)


# ============================================================ DUNG

class SRP_PT_build(_Base, bpy.types.Panel):
    bl_label = "Dựng rig"
    bl_idname = "SRP_PT_build"
    zone = 'BUILD'
    help = 'build'

    def draw(self, context):
        layout = self.layout
        cur = uikit.draw_steps(layout, context)
        if cur is None:
            layout.label(text="Đã xong -- bấm một bước để mở lại", icon='INFO')
        elif cur == 1:
            box = layout.box()
            row = box.row()
            row.label(text="1 · Chọn mesh", icon='MESH_DATA')
            uikit.help_button(row, 'target')
            generate.draw_target(box, context)


class SRP_PT_markers(_Base, bpy.types.Panel):
    """Cach dat khop nhanh, dung chung cho buoc 2-4 nen khong phai mot `_Step`."""
    bl_label = "Đặt marker từng khớp"
    bl_idname = "SRP_PT_markers"
    bl_parent_id = "SRP_PT_build"
    help = 'markers'

    @classmethod
    def poll(cls, context):
        return uikit.focus(context) in (2, 3, 4)

    def draw(self, context):
        markers.draw_panel(self.layout, context)


class SRP_PT_ref_start(_Step, bpy.types.Panel):
    bl_label = "2 · Xương Hips"
    bl_idname = "SRP_PT_ref_start"
    bl_parent_id = "SRP_PT_build"
    step = 2
    help = 'ref_start'

    def draw(self, context):
        refrig.draw_start(self.layout, context)
        fitref.draw_template(self.layout, context)


class SRP_PT_ref_parts(_Step, bpy.types.Panel):
    bl_label = "3 · Các bộ phận"
    bl_idname = "SRP_PT_ref_parts"
    bl_parent_id = "SRP_PT_build"
    step = 3
    help = 'ref_parts'

    def draw(self, context):
        refrig.draw_parts(self.layout, context)


class SRP_PT_skeleton(_Step, bpy.types.Panel):
    bl_label = "4 · Dựng rig + widget"
    bl_idname = "SRP_PT_skeleton"
    bl_parent_id = "SRP_PT_build"
    step = 4
    help = 'skeleton'

    def draw(self, context):
        generate.draw_skeleton(self.layout, context)


class SRP_PT_shape(_Base, bpy.types.Panel):
    """Cong cu widget rieng le — cho sua lai, khong phai mot buoc."""
    bl_label = "Chỉnh lại bone shape"
    bl_idname = "SRP_PT_shape"
    bl_parent_id = "SRP_PT_skeleton"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        column = layout.column(align=True)
        column.operator("srp.widget_generate", icon='ADD')
        column.operator("srp.widget_assign", icon='BONE_DATA')
        column.operator("srp.widget_display", icon='XRAY')
        column.operator("srp.widget_fit", icon='FULLSCREEN_ENTER')
        layout.operator("srp.widget_offset", text="Đẩy widget ra khỏi thân")


class SRP_PT_regions(_Step, bpy.types.Panel):
    """Nhom vung FS_ — dat TRUOC bind skin, chi can mesh nen mo ngay sau buoc 1."""
    bl_label = "5 · Nhóm vùng khuôn mặt"
    bl_idname = "SRP_PT_regions"
    bl_parent_id = "SRP_PT_build"
    step = 5
    help = 'regions'

    def draw(self, context):
        face.draw_regions(self.layout, context)


class SRP_PT_bind(_Step, bpy.types.Panel):
    bl_label = "6 · Bind skin"
    bl_idname = "SRP_PT_bind"
    bl_parent_id = "SRP_PT_build"
    step = 6
    help = 'bind'

    def draw(self, context):
        generate.draw_bind(self.layout, context)
        face.draw_face_weights(self.layout, context)


class SRP_PT_cloth(_Base, bpy.types.Panel):
    """Quan ao / toc / phu kien — LUON hien khi da co rig, khong theo wizard.

    Ban dau nam trong buoc 6, ma wizard chi mo buoc dang lam: rig da bind xong
    thi buoc 6 dong lai va khung quan ao bien mat — nguoi dung tim khong ra.
    """
    bl_label = "Quần áo, tóc, phụ kiện"
    bl_idname = "SRP_PT_cloth"
    bl_parent_id = "SRP_PT_build"
    help = 'cloth'

    @classmethod
    def poll(cls, context):
        return rigdef.active_rig(context) is not None

    def draw_header(self, context):
        n = cloth.unbound(context)
        if n:
            self.layout.label(text="", icon='ERROR')

    def draw(self, context):
        cloth.draw_cloth(self.layout, context)


# ============================================================ MAT

class SRP_PT_face(_Base, bpy.types.Panel):
    bl_label = "Shape key khuôn mặt"
    bl_idname = "SRP_PT_face"
    zone = 'FACE'
    help = 'face'

    def draw_header_preset(self, context):
        row = self.layout.row(align=True)
        if prefs.verbose():
            row.label(text="v%d.%d.%d" % face.VERSION)
        uikit.help_button(row, self.help)

    def draw(self, context):
        facebendy.draw(self.layout, context)
        face.draw_main(self.layout, context)


class SRP_PT_face_pose(_Base, bpy.types.Panel):
    bl_label = "Pose → Shape key · Đối xứng L↔R"
    bl_idname = "SRP_PT_face_pose"
    bl_parent_id = "SRP_PT_face"
    help = 'posekey'

    def draw(self, context):
        posekey.draw_pose_key(self.layout, context)


class SRP_PT_face_test(_Base, bpy.types.Panel):
    bl_label = "Thử biểu cảm"
    bl_idname = "SRP_PT_face_test"
    bl_parent_id = "SRP_PT_face"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        face.draw_test(self.layout, context)


class SRP_PT_face_config(_Base, bpy.types.Panel):
    """Hang so noi bo — chi hien khi bat 'Hien so lieu ky thuat'."""
    bl_label = "Hằng số hiệu chỉnh"
    bl_idname = "SRP_PT_face_config"
    bl_parent_id = "SRP_PT_face"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return prefs.verbose()

    def draw(self, context):
        face.draw_config(self.layout, context)


# ============================================================ DIEN

class SRP_PT_animate(_Base, bpy.types.Panel):
    bl_label = "Diễn xuất"
    bl_idname = "SRP_PT_animate"
    bl_options = {'HIDE_HEADER'}
    zone = 'ANIM'

    def draw(self, context):
        layout = self.layout
        rig = rigdef.active_rig(context)
        if rig is None:
            layout.label(text="Chưa có rig Rig Tẩm Hành nào", icon='INFO')
            layout.operator("srp.zone", text="Sang khu Dựng", icon='ARMATURE_DATA').zone = 'BUILD'
            return
        anim = rig.animation_data
        action = anim.action if anim else None
        row = layout.row(align=True)
        row.label(text=rig.name, icon='ARMATURE_DATA')
        row.operator_menu_enum("srp.assign_action", "action_name",
                               text=action.name if action else "Chưa gán action",
                               icon='ACTION' if action else 'DOT')


class SRP_PT_picker(_NeedRig, bpy.types.Panel):
    bl_label = "Picker"
    bl_idname = "SRP_PT_picker"
    zone = 'ANIM'

    def draw(self, context):
        picker.draw_body(self.layout, context, rigdef.active_rig(context))


class SRP_PT_picker_hand(_NeedRig, bpy.types.Panel):
    bl_label = "Bàn tay"
    bl_idname = "SRP_PT_picker_hand"
    bl_parent_id = "SRP_PT_picker"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        rig = rigdef.active_rig(context)
        return rig is not None and picker.has_fingers(rig)

    def draw(self, context):
        picker.draw_hand(self.layout, context, rigdef.active_rig(context))


class SRP_PT_picker_face(_NeedRig, bpy.types.Panel):
    bl_label = "Mặt"
    bl_idname = "SRP_PT_picker_face"
    bl_parent_id = "SRP_PT_picker"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        rig = rigdef.active_rig(context)
        return rig is not None and picker.has_face(rig)

    def draw(self, context):
        picker.draw_face(self.layout, context, rigdef.active_rig(context))
        # Pose -> shape key nam o khu Mat; o day chi mot nut tat cho nguoi dang pose
        self.layout.operator("face_shapes.pose_to_key", icon='SHAPEKEY_DATA')


class SRP_PT_picker_extra(_NeedRig, bpy.types.Panel):
    """Control con lai — dong san: biet co gi phai quet ca rig (~2,3 ms)."""
    bl_label = "Còn lại"
    bl_idname = "SRP_PT_picker_extra"
    bl_parent_id = "SRP_PT_picker"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        picker.draw_extra(self.layout, context, rigdef.active_rig(context))


class SRP_PT_fkik(_NeedRig, bpy.types.Panel):
    """Bang mot dong moi chi: ten | thanh truot FK..IK | ->FK ->IK.

    Ban truoc moi chi mot box ba dong voi hai nut chu dai, bon chi la muoi nut
    cung co — mat khong biet nhin vao dau.
    """
    bl_label = "FK / IK"
    bl_idname = "SRP_PT_fkik"
    zone = 'ANIM'
    help = 'fkik'

    def draw(self, context):
        layout = self.layout
        rig = rigdef.active_rig(context)
        prop_bone = rig.pose.bones.get(rigdef.PROP_BONE)
        limbs = rigdef.limbs_for(rig)
        col = layout.column(align=True)
        for limb in limbs:
            row = col.row(align=True)
            split = row.split(factor=0.34, align=True)
            split.label(text=limb.label)
            right = split.row(align=True)
            if prop_bone is not None and limb.prop in prop_bone.keys():
                right.prop(prop_bone, '["%s"]' % limb.prop, text="", slider=True)
            else:
                right.label(text="—")
            op = right.operator("srp.snap", text="→FK")
            op.direction, op.scope, op.limb_name = 'TO_FK', 'ONE', limb.name
            op = right.operator("srp.snap", text="→IK")
            op.direction, op.scope, op.limb_name = 'TO_IK', 'ONE', limb.name

        row = layout.row(align=True)
        op = row.operator("srp.snap", text="Tất cả → FK")
        op.direction, op.scope = 'TO_FK', 'ALL'
        op = row.operator("srp.snap", text="Tất cả → IK")
        op.direction, op.scope = 'TO_IK', 'ALL'


class SRP_PT_bake(_NeedRig, bpy.types.Panel):
    bl_label = "Bake theo đoạn"
    bl_idname = "SRP_PT_bake"
    bl_parent_id = "SRP_PT_fkik"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        rig = rigdef.active_rig(context)
        anim = rig.animation_data
        row = layout.row(align=True)
        row.enabled = anim is not None and anim.action is not None
        op = row.operator("srp.snap_bake", text="Bake FK theo IK")
        op.direction, op.scope = 'TO_FK', 'ALL'
        op = row.operator("srp.snap_bake", text="Bake IK theo FK")
        op.direction, op.scope = 'TO_IK', 'ALL'


class SRP_PT_tools(_NeedRig, bpy.types.Panel):
    bl_label = "Công cụ"
    bl_idname = "SRP_PT_tools"
    zone = 'ANIM'
    help = 'tools'

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        row = col.row(align=True)
        row.operator("srp.key", text="Ghi key", icon='KEY_HLT')
        op = row.operator("srp.jump_key", text="", icon='PREV_KEYFRAME')
        op.forward = False
        op = row.operator("srp.jump_key", text="", icon='NEXT_KEYFRAME')
        op.forward = True

        row = col.row(align=True)
        row.operator("srp.mirror_pose", text="Lật pose", icon='MOD_MIRROR')
        row.operator("srp.select_mirror", text="Chọn bên kia", icon='ARROW_LEFTRIGHT')

        row = col.row(align=True)
        op = row.operator("srp.reset", text="Reset đang chọn", icon='LOOP_BACK')
        op.whole_rig = False
        op = row.operator("srp.reset", text="Reset cả rig")
        op.whole_rig = True

        row = layout.row(align=True)
        row.label(text="Tween", icon='IPO_EASE_IN_OUT')
        for percent in (25, 40, 50, 60, 75):
            op = row.operator("srp.tween", text=str(percent))
            op.factor = percent / 100.0


class SRP_PT_retarget(_NeedRig, bpy.types.Panel):
    bl_label = "Retarget animation"
    bl_idname = "SRP_PT_retarget"
    bl_options = {'DEFAULT_CLOSED'}
    zone = 'ANIM'
    help = 'retarget'

    def draw(self, context):
        retarget.draw(self.layout, context)


class SRP_PT_onion(_NeedRig, bpy.types.Panel):
    bl_label = "Onion skin"
    bl_idname = "SRP_PT_onion"
    bl_options = {'DEFAULT_CLOSED'}
    zone = 'ANIM'

    def draw(self, context):
        onion.draw_panel(self.layout, context)


# ============================================================ XUAT

class SRP_PT_unity(_Base, bpy.types.Panel):
    bl_label = "Unity (Humanoid)"
    bl_idname = "SRP_PT_unity"
    zone = 'EXPORT'
    help = 'unity'

    def draw(self, context):
        unityexport.draw_unity(self.layout, context)


# ============================================================ SUA

class SRP_PT_repair(_Base, bpy.types.Panel):
    bl_label = "Sửa & kiểm tra"
    bl_idname = "SRP_PT_repair"
    zone = 'FIX'
    help = 'repair'

    def draw(self, context):
        layout = self.layout
        broken = health.broken_rigs()
        row = layout.row(align=True)
        if broken:
            row.alert = True
            row.label(text="%d rig thiếu driver/constraint: %s"
                      % (len(broken), ", ".join(broken[:3])), icon='ERROR')
            op = layout.operator("srp.apply_logic", text="Sửa ngay", icon='FILE_REFRESH')
            op.scope, op.verify = 'ALL', True
        elif health.STATUS:
            row.label(text="%d rig có cảnh báo nhẹ" % len(health.STATUS), icon='INFO')
        else:
            row.label(text="Mọi rig đều ổn", icon='CHECKMARK')
        row.operator("srp.quick_scan", text="", icon='FILE_REFRESH')


class SRP_PT_repair_logic(_NeedRig, bpy.types.Panel):
    bl_label = "Driver & rig logic"
    bl_idname = "SRP_PT_repair_logic"
    bl_parent_id = "SRP_PT_repair"
    help = 'repair_logic'

    def draw(self, context):
        rigs = rigdef.managed_rigs(context)
        row = self.layout.row(align=True)
        op = row.operator("srp.apply_logic", text="Áp lại (%d rig)" % len(rigs),
                          icon='FILE_REFRESH')
        op.scope, op.verify = 'ALL', True
        op = row.operator("srp.apply_logic", text="Chỉ rig đang chọn")
        op.scope, op.verify = 'ACTIVE', True


class SRP_PT_repair_weights(_NeedRig, bpy.types.Panel):
    bl_label = "Trọng số skin"
    bl_idname = "SRP_PT_repair_weights"
    bl_parent_id = "SRP_PT_repair"
    help = 'repair_weights'

    def draw(self, context):
        layout = self.layout
        rig = rigdef.active_rig(context)
        low = [(o.name, cloth.count_low(o, rig)) for o in context.scene.objects
               if o.type == 'MESH' and cloth.deformed_by(o, rig)]
        low = [(n, c) for n, c in low if c]
        row = layout.row()
        row.alert = bool(low)
        row.label(text=", ".join("%s: %d vertex thiếu" % x for x in low) if low
                  else "Mọi vertex đủ trọng số", icon='ERROR' if low else 'CHECKMARK')
        row = layout.row()
        row.scale_y = 1.3
        row.operator_menu_enum("srp.weights_fix", "task", text="Sửa weight…", icon='MOD_VERTEX_WEIGHT')
        weightfence.draw_regions(layout, context)
        _rig, body = cloth._body_rig(context)
        if body is not None and len(context.scene.srp_generate.cloth_meshes):
            cloth.draw_sync(layout, context, body)
        hand = cloth.hand_objects(context)
        if hand:
            box = layout.box()
            box.label(text="Giữ weight vẽ tay: " + ", ".join(
                "%s %d" % (o.name, n) for o, n in hand), icon='LOCKED')
            box.operator("srp.hand_forget", icon='UNLOCKED')


class SRP_PT_repair_health(_NeedRig, bpy.types.Panel):
    bl_label = "Khám rig đầy đủ"
    bl_idname = "SRP_PT_repair_health"
    bl_parent_id = "SRP_PT_repair"

    def draw(self, context):
        layout = self.layout
        row = layout.row(align=True)
        row.operator("srp.health", icon='VIEWZOOM')
        text = bpy.data.texts.get(health.TEXT_NAME)
        if text is not None:
            body = text.as_string()
            errors = body.count("[LOI ]")
            warns = body.count("[canh]")
            layout.label(text="%d lỗi, %d cảnh báo — xem text %r"
                         % (errors, warns, health.TEXT_NAME),
                         icon='ERROR' if errors else 'CHECKMARK')


class SRP_PT_repair_shape(_NeedRig, bpy.types.Panel):
    bl_label = "Dọn bone shape"
    bl_idname = "SRP_PT_repair_shape"
    bl_parent_id = "SRP_PT_repair"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        used = widgets.widget_objects([o for o in bpy.data.objects if o.type == 'ARMATURE'])
        loose = [o for o in used if o.users_collection]
        row = layout.row()
        row.alert = bool(loose)
        row.label(text="%d widget đang dùng%s"
                  % (len(used), ", %d cái nằm trong collection" % len(loose) if loose else ""),
                  icon='MESH_CIRCLE')
        layout.operator("srp.widget_cleanup", icon='BRUSH_DATA')


class SRP_PT_repair_remap(_NeedRig, bpy.types.Panel):
    bl_label = "Đổi tên xương trong action"
    bl_idname = "SRP_PT_repair_remap"
    bl_parent_id = "SRP_PT_repair"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        remap.draw_panel(self.layout, context)


class SRP_PT_repair_solve(_NeedRig, bpy.types.Panel):
    bl_label = "Đổi kết quả solve"
    bl_idname = "SRP_PT_repair_solve"
    bl_parent_id = "SRP_PT_repair"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        layout.label(text="Đổi cả animation đã bake", icon='ERROR')
        row = layout.row(align=True)
        row.operator("srp.calibrate_pole", icon='CON_KINEMATIC')
        row.operator("srp.ik_stretch", text="Tắt IK stretch").enable = False


# Cha phai dang ky truoc con; thu tu goc = thu tu tren thanh chon khu.
CLASSES = (
    SRP_PT_zone,
    SRP_PT_build, SRP_PT_markers, SRP_PT_ref_start, SRP_PT_ref_parts, SRP_PT_skeleton,
    SRP_PT_shape, SRP_PT_regions, SRP_PT_bind, SRP_PT_cloth,
    SRP_PT_face, SRP_PT_face_pose, SRP_PT_face_test, SRP_PT_face_config,
    SRP_PT_animate, SRP_PT_picker, SRP_PT_picker_hand, SRP_PT_picker_face,
    SRP_PT_picker_extra, SRP_PT_fkik, SRP_PT_bake, SRP_PT_tools, SRP_PT_retarget, SRP_PT_onion,
    SRP_PT_unity,
    SRP_PT_repair, SRP_PT_repair_logic, SRP_PT_repair_weights, SRP_PT_repair_health,
    SRP_PT_repair_shape, SRP_PT_repair_remap, SRP_PT_repair_solve,
)
