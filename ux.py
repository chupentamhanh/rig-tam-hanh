"""Lớp dễ dùng phủ lên các nút sẵn có: gom nút trùng việc, hỏi lại trước khi
ghi đè, và thanh "Bước tiếp theo" ở đầu tab.

Các toán tử cũ (srp.bake_weights, srp.hip_weights, srp.fill_weights,
srp.cloth_bind, srp.sync_from_body...) vẫn còn nguyên -- script và bài test gọi
thẳng chúng; panel chỉ không bày chúng ra nữa.
"""

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
from bpy.types import Operator

from . import cloth, prefs, rigdef, uikit, weightauto

FOLLOW_KEY = "srp_follow_keys"      # tên key mặt lúc mesh phụ bám da lần cuối


# ============================================================ sửa weight: một nút

WEIGHT_TASKS = (
    ('BAKE', "Tự làm mượt weight các khớp",
     "Cho nhân vật qua khoảng 40 tư thế rồi tìm weight để vai, nách, mông, khuỷu "
     "gập mượt hơn (tối đa 4 xương mỗi vertex cho Unity). Nên chạy ngay sau khi "
     "Bind, trước khi vẽ tay", 'MOD_SMOOTH'),
    ('JOINTS', "Sửa hông, gối, khuỷu",
     "Háng gập thành khe, mông gãy khi giơ chân, khoeo / lòng khuỷu móp khi gập "
     "sâu: đặt lại vùng chuyển weight quanh các khớp đó", 'MOD_VERTEX_WEIGHT'),
    ('LEGS', "Sửa hông và gối (không đụng tay)",
     "Như trên nhưng để nguyên khuỷu tay", 'MOD_VERTEX_WEIGHT'),
    ('FENCE', "Rào weight theo vùng",
     "Gỡ weight của xương lấn sang vùng không phải của nó: vai lên má, hàm ra sau "
     "gáy / xuống ngực, chân bên này sang chân bên kia. Vùng (đầu / thân / tay / "
     "chân) lấy theo cấu trúc rig. Làm mượt chỗ vừa gỡ, tối đa 4 xương, normalize",
     'MOD_MASK'),
    ('FILL', "Lấp chỗ thiếu weight",
     "Vertex có tổng weight chưa đủ (đứng yên khi pose) được lấp từ xung quanh",
     'BRUSH_DATA'),
)
_TASK_OP = {'BAKE': ("bake_weights", {}), 'JOINTS': ("hip_weights", {}),
            'LEGS': ("hip_weights", {'part': 'LEGS'}), 'FILL': ("fill_weights", {}),
            'FENCE': ("weight_fence", {})}


def _body(context):
    rig, body = cloth._body_rig(context)
    return rig, body


class SRP_OT_weights_fix(Operator):
    """Sửa weight của mesh thân -- chọn việc cần làm trong danh sách"""
    bl_idname = "srp.weights_fix"
    bl_label = "Sửa weight"
    bl_options = {'REGISTER', 'UNDO'}

    task: EnumProperty(name="Việc", items=[t[:3] + (t[3], i) for i, t in enumerate(WEIGHT_TASKS)])

    @classmethod
    def poll(cls, context):
        return rigdef.active_rig(context) is not None

    @classmethod
    def description(cls, context, props):
        return next((t[2] for t in WEIGHT_TASKS if t[0] == props.task), cls.__doc__)

    def invoke(self, context, event):
        if self.task == 'FILL':
            return self.execute(context)
        _rig, body = _body(context)
        if body is None:
            return self.execute(context)
        kept = len(cloth.hand_painted(body))
        label = next(t[1] for t in WEIGHT_TASKS if t[0] == self.task)
        msg = ("Weight của %s sẽ được tính lại. " % body.name
               + ("%d vertex bạn đã vẽ tay được giữ nguyên." % kept if kept
                  else "Chưa có vertex nào được đánh dấu vẽ tay -- chỗ bạn đã sửa sẽ bị tính lại."))
        if self.task in ('JOINTS', 'LEGS'):
            msg += " Quần áo cũng được cập nhật theo."
        return context.window_manager.invoke_confirm(
            self, event, title=label, message=msg, confirm_text="Làm", icon='WARNING')

    def execute(self, context):
        name, kw = _TASK_OP[self.task]
        op = getattr(bpy.ops.srp, name)
        try:
            return op('EXEC_DEFAULT', **kw)
        except RuntimeError as e:          # toán tử con đã báo lỗi
            self.report({'ERROR'}, str(e).replace("Error: ", ""))
            return {'CANCELLED'}


class SRP_OT_weights_auto(Operator):
    """Sửa weight mesh thân một lần bấm: khu trú, rào vùng, (thử) sửa hông / gối / khuỷu,
    (thử) tự làm mượt các khớp, dọn weight vụn, tối đa 4 xương, normalize, lấp chỗ
    thiếu. Bước nào khám tư thế thấy không tốt hơn thì tự bỏ. Vertex vẽ tay giữ
    nguyên; quần áo cập nhật theo thân"""
    bl_idname = "srp.weights_auto"
    bl_label = "Sửa weight tự động"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return rigdef.active_rig(context) is not None

    def invoke(self, context, event):
        _rig, body = _body(context)
        if body is None:
            return self.execute(context)
        kept = len(cloth.hand_painted(body))
        msg = ("Weight của %s sẽ được tính lại. " % body.name
               + ("%d vertex bạn đã vẽ tay được giữ nguyên." % kept if kept
                  else "Chưa có vertex nào được đánh dấu vẽ tay -- chỗ bạn đã sửa sẽ bị tính lại."))
        if len(context.scene.srp_generate.cloth_meshes):
            msg += " Quần áo cũng được cập nhật theo."
        return context.window_manager.invoke_confirm(
            self, event, title=self.bl_label, message=msg, confirm_text="Sửa", icon='WARNING')

    def execute(self, context):
        rig, body = _body(context)
        if body is None or not cloth.deformed_by(body, rig):
            self.report({'ERROR'}, "Chưa có mesh thân skin vào rig")
            return {'CANCELLED'}
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        result = weightauto.autofix(context, body, rig)
        lines = weightauto.lines(result)
        for line in lines:
            print("Rig Tẩm Hành | sửa weight |", line)
        if result["changed"] and len(context.scene.srp_generate.cloth_meshes):
            lines += update_clothes(context, rig, body)
            # da dưới áo vừa chép weight áo: dọn lại (vụn, quá 4 xương)
            weightauto.tidy(body, rig, cloth.hand_painted(body))
        context.view_layer.objects.active = rig
        b, a = result["before"], result["after"]
        kept = [label for _k, label, s, _n in result["steps"] if s == 'KEPT']
        msg = "%s: sửa %d vertex (%s). Tư thế có lỗi %d -> %d" % (
            body.name, result["changed"], ", ".join(kept) or "không bước nào cần", b[0], a[0])
        self.report({'INFO'}, msg + prefs.detail(" | " + " | ".join(lines)))
        return {'FINISHED'}


# ============================================================ quần áo: một nút

def update_clothes(context, rig, body, hair=False):
    """Bind món chưa bind / gắn cứng / automatic, chép weight thân (đúng như đang
    có) sang món "chép từ thân" và mesh phụ dán da; rồi -- nếu bật -- cho da dưới
    áo theo áo (vertex vẽ tay của thân giữ nguyên). Trả về các dòng báo cáo."""
    st = context.scene.srp_generate
    lines = []
    fresh = [e for e in st.cloth_meshes if e.mesh is not None and e.mesh.type == 'MESH'
             and (e.mode != 'TRANSFER' or not cloth.deformed_by(e.mesh, rig))]
    with cloth.keep_hand([e.mesh for e in fresh]):
        for e in fresh:
            if e.mode == 'RIGID' and hair and cloth.deformed_by(e.mesh, rig):
                continue                    # tóc sẽ chép từ thân ngay bên dưới
            lines.append(cloth.bind_one(context, e, rig, body))
    synced, _kept = cloth.sync_from_body(context, rig, body, hair)
    lines += synced
    if st.skin_follow:
        done = [e.mesh for e in st.cloth_meshes if e.mesh is not None and e.mode != 'RIGID'
                and cloth.deformed_by(e.mesh, rig)]
        if done:
            with cloth.keep_hand([body]):
                n = cloth.skin_follow(rig, body, done)
            if n:
                lines.append("%d vertex da dưới áo đi theo áo" % n)
                body[cloth.SYNC_KEY] = body.get(cloth.STAMP_KEY, 0)
    context.view_layer.objects.active = rig
    return lines


class SRP_OT_cloth_update(Operator):
    """Bind quần áo mới và chép lại weight của thân sang mọi quần áo, giày, lông
    mày... Bấm sau khi thêm quần áo hoặc sửa weight thân"""
    bl_idname = "srp.cloth_update"
    bl_label = "Cập nhật quần áo"
    bl_options = {'REGISTER', 'UNDO'}

    hair: BoolProperty(
        name="Cả tóc", default=False,
        description="Tóc đang gắn cứng vào đầu cũng chép weight từ thân (tóc dài "
                    "chạm vai, gáy)")

    @classmethod
    def poll(cls, context):
        settings = getattr(context.scene, "srp_generate", None)
        return (settings is not None and len(settings.cloth_meshes) > 0
                and rigdef.active_rig(context) is not None)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=360, title=self.bl_label,
                                                          confirm_text="Cập nhật")

    def draw(self, context):
        L = self.layout
        rig, body = _body(context)
        st = context.scene.srp_generate
        items = [e for e in st.cloth_meshes if e.mesh is not None]
        new = [e.mesh.name for e in items if rig is not None and not cloth.deformed_by(e.mesh, rig)]
        col = L.column(align=True)
        col.label(text="%d món trong danh sách" % len(items), icon='MOD_CLOTH')
        if new:
            col.label(text="Bind mới: " + ", ".join(new[:4]) + (" ..." if len(new) > 4 else ""), icon='ADD')
        col.label(text="Weight lấy từ %s, thân không bị đổi" % (body.name if body else "thân"), icon='CHECKMARK')
        L.prop(self, "hair")
        L.prop(st, "skin_follow", text="Sửa da dưới áo theo áo (đổi weight thân)")
        if st.skin_follow and body is not None:
            kept = len(cloth.hand_painted(body))
            L.label(text="Da thân dưới áo sẽ đổi weight%s" % (
                ", giữ %d vertex vẽ tay" % kept if kept else ""), icon='ERROR')

    def execute(self, context):
        rig, body = _body(context)
        if body is None or not cloth.deformed_by(body, rig):
            self.report({'ERROR'}, "Chưa bind mesh thân (bước 6)")
            return {'CANCELLED'}
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        lines = update_clothes(context, rig, body, self.hair)
        bad = [ln for ln in lines if "chưa" in ln or "thất bại" in ln or "không có" in ln]
        self.report({'WARNING'} if bad else {'INFO'}, "Cập nhật quần áo | " + " | ".join(lines))
        return {'FINISHED'}


# ============================================================ mesh phụ bám da tự động

def skin_parts_of(context, face):
    from . import posekey
    rig = next((m.object for m in face.modifiers if m.type == 'ARMATURE' and m.object), None)
    if rig is None:
        return []
    return [o for o, _a in cloth.skin_parts(context, rig, face)]


def follow_all(context, face, names=None):
    """Mesh phụ dán da của nhân vật bám theo key của `face`. Trả về dòng báo cáo."""
    from . import followkeys
    out = []
    for o in skin_parts_of(context, face):
        made, redone, _s = followkeys.follow(face, o, names=names)
        o[FOLLOW_KEY] = sorted(kb.name for kb in face.data.shape_keys.key_blocks[1:])
        if made or redone:
            out.append("%s bám da (%d key)" % (o.name, len(made) + len(redone)))
    return out


def follow_stale(context, face):
    """Mesh phụ dán da chưa bám theo bộ key hiện tại của mặt."""
    key = face.data.shape_keys if face is not None else None
    if key is None or len(key.key_blocks) < 2:
        return []
    now = sorted(kb.name for kb in key.key_blocks[1:])
    return [o for o in skin_parts_of(context, face) if list(o.get(FOLLOW_KEY, [])) != now]


# ============================================================ thanh "Bước tiếp theo"

class SRP_OT_goto(Operator):
    """Mở đúng chỗ cần làm tiếp"""
    bl_idname = "srp.goto"
    bl_label = "Đi tới"
    bl_options = {'INTERNAL'}

    zone: StringProperty(default='BUILD')
    step: IntProperty(default=0)

    def execute(self, context):
        uikit._state['zone'] = self.zone
        if self.step:
            uikit._state['manual'], uikit._state['focus'] = True, self.step
        uikit._redraw(context)
        return {'FINISHED'}


def next_step(context):
    """(chữ, icon, toán tử, {thuộc tính}) cho việc nên làm tiếp."""
    from . import generate
    st = getattr(context.scene, "srp_generate", None)
    if st is None:
        return None
    steps = generate.build_progress(context)
    for i in uikit.REQUIRED_STEPS:
        name, done = steps[i - 1][0], steps[i - 1][1]
        if not done:
            return ("Tiếp: %s" % name, 'TRIA_RIGHT', "srp.goto", {'zone': 'BUILD', 'step': i})
    rig, body = cloth._body_rig(context)
    if rig is None or body is None:
        return None
    if cloth.unbound(context):
        return ("Có quần áo / phụ kiện chưa bind", 'ERROR', "srp.goto", {'zone': 'BUILD', 'step': 0})
    if len(st.cloth_meshes) and cloth.sync_stale(body):
        return ("Thân đã sửa weight -> cập nhật quần áo", 'ERROR', "srp.cloth_update", {})
    if follow_stale(context, body):
        return ("Lông mày / râu rời chưa bám theo key mặt mới", 'ERROR', "face_shapes.follow_skin", {})
    key = body.data.shape_keys
    if key is None or len(key.key_blocks) < 2:
        return ("Tuỳ chọn: dựng shape key khuôn mặt", 'SHAPEKEY_DATA', "srp.goto", {'zone': 'FACE'})
    return ("Sẵn sàng: xuất sang Unity", 'CHECKMARK', "srp.goto", {'zone': 'EXPORT'})


def draw_next(layout, context):
    try:
        nxt = next_step(context)
    except Exception:           # thanh gợi ý không được làm hỏng cả tab
        return
    if nxt is None:
        return
    text, icon, op, props = nxt
    row = layout.row()
    row.alert = icon == 'ERROR'
    b = row.operator(op, text=text, icon=icon)
    for k, v in props.items():
        setattr(b, k, v)


CLASSES = (SRP_OT_weights_fix, SRP_OT_weights_auto, SRP_OT_cloth_update, SRP_OT_goto)
