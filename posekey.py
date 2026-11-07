"""Pose khuôn mặt bằng tay trong Pose Mode rồi nướng thành shape key.

Cùng công thức với bộ dựng tự động (`face.bake`): key = Basis + (evaluated
posed - evaluated rest). Hai điều khác:

- Chỉ lấy pose của XƯƠNG MẶT (con cháu của bone Head). Tay, cổ, chính bone Head
  đang pose dở thì bị đưa về rest lúc đo -- không thì cả cái đầu nghiêng hay
  cánh tay giơ lên sẽ bị nướng vào key biểu cảm.
- "Chỉ xương đang chọn": chỉ lấy pose của các xương đang chọn, xương khác
  tạm về rest lúc đo -- pose cả hai bên rồi chọn bên trái nướng key trái,
  chọn bên phải nướng key phải. Nướng xong chỉ xương vừa dùng về rest.
- Key làm tay KHÔNG ghi vào bản kê khai `srp_face`, nên "Dựng bộ shape key" lần
  sau không xoá nó. Ghi đè lên key của addon thì giữ nguyên cờ cũ (dựng lại sẽ
  thay lại key ấy -- báo ra cho người dùng biết).
"""

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy.types import Operator
from mathutils import Matrix

from . import face, facerig

THRESH = 2e-4       # giống face.bake: dưới ngần này coi như mesh không nhúc nhích


def head_bone(arm):
    """Bone đầu: đúng tên Head trước, không thì bone gần gốc nhất có chữ 'head'."""
    bones = arm.data.bones
    if 'Head' in bones:
        return bones['Head']
    cands = [b for b in bones if 'head' in b.name.lower()
             and not any(t in b.name.lower() for t in ('top', 'end', 'tail'))]
    return min(cands, key=lambda b: len(b.parent_recursive), default=None)


def face_bones(arm):
    """Tên các xương mặt. Không tìm thấy bone đầu thì None (= mọi bone)."""
    head = head_bone(arm)
    if head is None:
        return None
    return {b.name for b in head.children_recursive}


def posed(arm, names=None):
    return [pb.name for pb in arm.pose.bones
            if (names is None or pb.name in names) and pb.matrix_basis != Matrix()]


def selected(context, arm):
    """Tên các pose bone đang chọn của `arm`."""
    sel = getattr(context, "selected_pose_bones", None)
    if sel:
        return {pb.name for pb in sel if pb.id_data is arm}
    # ngoài Pose Mode (gọi từ script, panel Object Mode): đọc cờ trên bone
    return {pb.name for pb in arm.pose.bones
            if getattr(pb, "select", None) or getattr(pb.bone, "select", False)}


def rig_and_mesh(context):
    """Đang ở Pose Mode thì rig là chính armature đang pose."""
    ob = context.object
    if ob is not None and ob.type == 'ARMATURE':
        arm = ob
        mesh = face.find_face_mesh(context, arm)
    else:
        arm, mesh = face.find_rig_and_mesh(context)
    return arm, mesh


def write_key(obj, name, delta, create):
    """Ghi Basis + delta vào key `name`. Trả về (key block, có phải vừa tạo)."""
    face.ensure_basis(obj)
    kbs = obj.data.shape_keys.key_blocks
    kb = kbs.get(name)
    new = kb is None
    if new:
        if not create:
            return None, False
        kb = obj.shape_key_add(name=name, from_mix=False)
        kb.value = 0.0
        kb.slider_min, kb.slider_max = 0.0, 1.0
    basis = kbs['Basis']
    for i, d in enumerate(delta):
        kb.data[i].co = basis.data[i].co + d
    return kb, new


def key_items(self, context):
    _arm, mesh = rig_and_mesh(context)
    key = mesh.data.shape_keys if mesh is not None else None
    items = [(kb.name, kb.name, "") for kb in key.key_blocks if kb.name != 'Basis'] \
        if key else []
    # Blender chỉ giữ tham chiếu yếu tới chuỗi của enum động: phải neo lại
    # trong Python, không thì tên trong dropdown thành rác.
    key_items.cache = items or [('NONE', "(chưa có shape key)", "")]
    return key_items.cache


class FACESHAPES_OT_pose_to_key(Operator):
    bl_idname = "face_shapes.pose_to_key"
    bl_label = "Pose → Shape key"
    bl_description = ("Nướng pose xương mặt hiện tại thành shape key: tạo key "
                      "mới hoặc ghi đè một key có sẵn của nhân vật")
    bl_options = {'REGISTER', 'UNDO'}

    mode: EnumProperty(
        name="Cách lưu",
        items=(('NEW', "Tạo mới", "Tạo shape key mới với tên tự đặt"),
               ('OVERWRITE', "Ghi đè", "Thay hình dạng của một shape key có sẵn")),
        default='NEW')
    key_name: StringProperty(name="Tên", default="Pose")
    target: EnumProperty(name="Shape key", items=key_items)
    selected_only: BoolProperty(
        name="Chỉ xương đang chọn", default=False,
        description="Chỉ lấy pose của các xương đang chọn; xương mặt khác "
                    "(kể cả đang pose) tạm về rest lúc đo. Pose cả hai bên, chọn "
                    "bên trái nướng key trái, rồi chọn bên phải nướng key phải. "
                    "Nướng xong chỉ xương đã dùng về rest")
    face_only: BoolProperty(
        name="Chỉ xương mặt", default=True,
        description="Chỉ lấy pose các xương con của Head. Tay, cổ, đầu đang "
                    "pose dở không bị nướng vào key")
    reset_pose: BoolProperty(
        name="Trả xương mặt về rest", default=True,
        description="Xong thì đưa xương mặt về tư thế nghỉ, để khỏi cộng đôi "
                    "pose với shape key vừa tạo")
    mirror_too: BoolProperty(
        name="Tạo luôn bản đối xứng", default=False,
        description="Lật key vừa nướng sang bên kia, tên tự đổi L <-> R "
                    "(không có dấu bên thì thêm _Mirror). Có sẵn thì ghi đè")

    @classmethod
    def poll(cls, context):
        arm, mesh = rig_and_mesh(context)
        return arm is not None and mesh is not None

    def invoke(self, context, event):
        _arm, mesh = rig_and_mesh(context)
        key = mesh.data.shape_keys
        names = {kb.name for kb in key.key_blocks} if key else set()
        i = 1
        while "Pose_%03d" % i in names:
            i += 1
        self.key_name = "Pose_%03d" % i
        act = mesh.active_shape_key
        if act is not None and act.name != 'Basis':
            self.target = act.name
        # Đang chọn một phần các xương đã pose -> mặc định chỉ lấy phần đó
        arm, _m = rig_and_mesh(context)
        moved = set(posed(arm, face_bones(arm)))
        sel = selected(context, arm) & moved
        self.selected_only = bool(sel) and sel != moved
        return context.window_manager.invoke_props_dialog(self, width=320)

    def draw(self, context):
        L = self.layout
        _arm, mesh = rig_and_mesh(context)
        L.label(text="Mesh: %s" % mesh.name, icon='MESH_DATA')
        L.row().prop(self, "mode", expand=True)
        if self.mode == 'NEW':
            L.prop(self, "key_name")
        elif mesh.data.shape_keys and len(mesh.data.shape_keys.key_blocks) > 1:
            L.prop(self, "target")
        else:
            L.label(text="Nhân vật chưa có shape key nào để ghi đè", icon='ERROR')
        arm, _m = rig_and_mesh(context)
        moved = posed(arm, face_bones(arm) if self.face_only else None)
        sel = selected(context, arm)
        L.prop(self, "selected_only")
        col = L.column(align=True)
        col.scale_y = 0.8
        if self.selected_only:
            use = [n for n in moved if n in sel]
            col.label(text="Lấy %d / %d xương đang pose" % (len(use), len(moved)),
                      icon='CHECKMARK' if use else 'ERROR')
            skip = [n for n in moved if n not in sel]
            if skip:
                col.label(text="Bỏ qua: " + ", ".join(skip[:4]) + (" ..." if len(skip) > 4 else ""),
                          icon='HIDE_ON')
        L.prop(self, "face_only")
        L.prop(self, "reset_pose")
        L.prop(self, "mirror_too")
        if self.mirror_too:
            from . import mirrorkey
            name = self.key_name if self.mode == 'NEW' else self.target
            L.label(text="Bản đối xứng: %s" % mirrorkey.mirror_name(name), icon='MOD_MIRROR')

    def execute(self, context):
        arm, mesh = rig_and_mesh(context)
        if arm is None or mesh is None:
            self.report({'ERROR'}, "Không tìm thấy rig hoặc mesh mặt")
            return {'CANCELLED'}
        if not face.deformed_by(mesh, arm):
            self.report({'ERROR'}, "%s không do rig %s làm biến dạng" % (mesh.name, arm.name))
            return {'CANCELLED'}

        key = mesh.data.shape_keys
        if self.mode == 'NEW':
            name = self.key_name.strip()
            if not name or name == 'Basis':
                self.report({'ERROR'}, "Đặt tên cho shape key mới")
                return {'CANCELLED'}
            if key and name in key.key_blocks:
                self.report({'ERROR'}, "Đã có shape key '%s' -- đổi tên hoặc chọn Ghi đè" % name)
                return {'CANCELLED'}
        else:
            name = self.target
            if not key or not name or name not in key.key_blocks or name == 'Basis':
                self.report({'ERROR'}, "Chọn shape key cần ghi đè")
                return {'CANCELLED'}

        keep = face_bones(arm) if self.face_only else None
        if self.selected_only:
            sel = selected(context, arm)
            if not sel:
                self.report({'ERROR'}, "Chưa chọn xương nào -- chọn các xương của bên cần nướng")
                return {'CANCELLED'}
            keep = sel if keep is None else keep & sel
        if not posed(arm, keep):
            self.report({'ERROR'}, ("Các xương đang chọn chưa được pose" if self.selected_only
                                    else "Chưa pose xương mặt nào" if keep is not None
                                    else "Rig đang ở tư thế nghỉ"))
            return {'CANCELLED'}
        used = posed(arm, keep)

        targets = facerig.targets_for(arm, mesh)
        saved = {pb.name: pb.matrix_basis.copy() for pb in arm.pose.bones}
        try:
            with face.KeyScope(targets):
                for pb in arm.pose.bones:
                    if keep is not None and pb.name not in keep:
                        pb.matrix_basis = Matrix()
                context.view_layer.update()
                pose_co = {o.name: facerig.eval_co(o) for o in targets}
                for pb in arm.pose.bones:
                    pb.matrix_basis = Matrix()
                context.view_layer.update()
                rest_co = {o.name: facerig.eval_co(o) for o in targets}
        finally:
            for pb in arm.pose.bones:
                pb.matrix_basis = saved[pb.name]
            context.view_layer.update()

        deltas = {o.name: [p - r for p, r in zip(pose_co[o.name], rest_co[o.name])]
                  for o in targets}
        if max(d.length for d in deltas[mesh.name]) < THRESH:
            self.report({'ERROR'}, "Pose này không làm %s nhúc nhích" % mesh.name)
            return {'CANCELLED'}

        kb, _new = write_key(mesh, name, deltas[mesh.name], create=True)
        src = mesh.data.shape_keys
        others = []
        for o in targets[1:]:
            d = deltas[o.name]
            moved = max(v.length for v in d) >= THRESH
            # Ghi đè thì mesh phụ có key cùng tên cũng phải ghi lại, kể cả khi
            # pose mới không chạm tới nó -- không thì giữ nguyên hình CŨ.
            okb, onew = write_key(o, name, d, create=moved)
            if okb is None:
                continue
            others.append(o.name)
            if onew:
                face.add_driver(okb, src, name)

        if self.reset_pose:
            for n in used:
                arm.pose.bones[n].matrix_basis = Matrix()
            context.view_layer.update()

        mesh.active_shape_key_index = list(src.key_blocks).index(kb)
        msg = "%s shape key '%s' trên %s" % (
            "Đã tạo" if self.mode == 'NEW' else "Đã ghi đè", name, mesh.name)
        if self.selected_only:
            msg += " | từ %d xương đang chọn" % len(used)
        if others:
            msg += " + %s (driver theo %s)" % (", ".join(others), mesh.name)
        level = {'INFO'}
        if self.mode == 'OVERWRITE' and face.is_own(src, kb):
            level = {'WARNING'}
            msg += " | key của addon: bấm Dựng lại sẽ thay lại nó"
        if self.mirror_too:
            from . import mirrorkey
            dst = mirrorkey.mirror_name(name)
            mkb, _o, off, _asym = mirrorkey.mirror_key(arm, mesh, name, dst)
            msg += " | đối xứng → '%s'" % dst
            if off > len(mkb.data) * mirrorkey.ASYM_WARN:
                level = {'WARNING'}
                msg += " (%d vertex lệch cặp)" % off
            mesh.active_shape_key_index = list(src.key_blocks).index(kb)
        self.report(level, msg)
        return {'FINISHED'}


def draw_pose_key(L, context):
    arm, mesh = rig_and_mesh(context)
    r = L.row()
    r.scale_y = 1.4
    r.operator("face_shapes.pose_to_key", icon='SHAPEKEY_DATA')
    if arm is not None and mesh is not None:
        keep = face_bones(arm)
        moved = posed(arm, keep)
        n = len(moved)
        L.label(text="%s → %s | %d xương mặt đang pose" % (arm.name, mesh.name, n),
                icon='ARMATURE_DATA' if n else 'INFO')
        sel = selected(context, arm) & set(moved)
        if sel and len(sel) < n:
            L.label(text="Đang chọn %d -> nướng riêng phần đã chọn" % len(sel), icon='RESTRICT_SELECT_OFF')
    L.operator("face_shapes.mirror_key", icon='MOD_MIRROR')


CLASSES = (FACESHAPES_OT_pose_to_key,)
