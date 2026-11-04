"""Onion skin cho rig — Blender khong co san (chi Grease Pencil moi co).

Ve bang GPU overlay: nuong san vi tri o cac frame duoc chon thanh batch mot
lan, roi moi lan redraw chi ve lai batch. Khong dung toi du lieu file, khong
tao them object nao — tat di la sach tron.

Hai che do:
  * XUONG — re hon ghost mesh khoang hai bac. Ca mot action 330 frame chi
    ~72.000 dinh, nuong trong chop mat. Doc cung arc va spacing thi day la
    thu can nhin, khong phai silhouette.
  * MESH — nang hon nhieu vi phai frame_set + danh gia lai mesh o tung frame.
    Nhan vat trong project nay low-poly (~4.400 dinh) nen van chay duoc, mien
    la co buoc nhay.
"""

import bpy
import gpu
from bpy.app.handlers import persistent
from bpy.props import (BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty,
                       IntProperty, PointerProperty)
from gpu_extras.batch import batch_for_shader

from . import rigdef, widgets

# [(frame, batch)] da nuong san + frame goc luc nuong
_CACHE = {"items": [], "rig": "", "mode": "", "baked_at": 0}
_HANDLE = None
_MAX_MESH_FRAMES = 120        # tran an toan cho che do mesh


def _shader():
    try:
        return gpu.shader.from_builtin('UNIFORM_COLOR')
    except ValueError:
        return gpu.shader.from_builtin('3D_UNIFORM_COLOR')


# ------------------------------------------------------------- thu thap

def _bone_segments(context, rig):
    """Doan thang head->tail cua xuong deform, trong toa do the gioi."""
    evaluated = rig.evaluated_get(context.evaluated_depsgraph_get())
    matrix = evaluated.matrix_world
    points = []
    bones = [b for b in evaluated.pose.bones if b.bone.use_deform] or list(evaluated.pose.bones)
    for pose_bone in bones:
        points.append(matrix @ pose_bone.head)
        points.append(matrix @ pose_bone.tail)
    return points


def _mesh_segments(context, rig, meshes):
    """Canh cua mesh tren nguoi, trong toa do the gioi."""
    depsgraph = context.evaluated_depsgraph_get()
    points = []
    for obj in meshes:
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        if mesh is None:
            continue
        matrix = evaluated.matrix_world
        coords = [matrix @ v.co for v in mesh.vertices]
        for edge in mesh.edges:
            points.append(coords[edge.vertices[0]])
            points.append(coords[edge.vertices[1]])
        evaluated.to_mesh_clear()
    return points


# ---------------------------------------------------------------- nuong

def frames_to_bake(context, settings, rig):
    scene = context.scene
    anim = rig.animation_data
    action = anim.action if anim else None
    step = max(1, settings.step)

    if settings.scope == 'ALL' and action is not None:
        start, end = (int(v) for v in action.frame_range)
    elif settings.scope == 'ALL':
        start, end = scene.frame_start, scene.frame_end
    else:
        start = scene.frame_current - settings.before * step
        end = scene.frame_current + settings.after * step

    frames = list(range(int(start), int(end) + 1, step))
    return [f for f in frames if f != scene.frame_current]


def bake(context, settings):
    rig = rigdef.active_rig(context)
    if rig is None:
        return None, "không có rig"

    frames = frames_to_bake(context, settings, rig)
    if not frames:
        return None, "không có frame nào để vẽ"

    meshes = []
    if settings.mode == 'MESH':
        meshes = widgets.body_meshes(rig)
        if not meshes:
            return None, "không có mesh nào nằm đúng chỗ nhân vật"
        if len(frames) > _MAX_MESH_FRAMES:
            return None, ("che do mesh gioi han %d frame, dang doi %d — tang buoc nhay len"
                          % (_MAX_MESH_FRAMES, len(frames)))

    scene = context.scene
    restore = scene.frame_current
    shader = _shader()
    items = []
    for frame in frames:
        scene.frame_set(frame)
        points = (_mesh_segments(context, rig, meshes) if settings.mode == 'MESH'
                  else _bone_segments(context, rig))
        if points:
            items.append((frame, batch_for_shader(shader, 'LINES', {"pos": points})))
    scene.frame_set(restore)

    _CACHE["items"] = items
    _CACHE["rig"] = rig.name
    _CACHE["mode"] = settings.mode
    _CACHE["baked_at"] = restore
    return len(items), None


def clear():
    _CACHE["items"] = []
    _CACHE["rig"] = ""


# ----------------------------------------------------------------- ve

def _draw():
    items = _CACHE["items"]
    if not items:
        return
    context = bpy.context
    settings = getattr(context.scene, "srp_onion", None)
    if settings is None or not settings.enabled:
        return

    current = context.scene.frame_current
    span = max(1, max(abs(f - current) for f, _ in items))
    shader = _shader()
    gpu.state.blend_set('ALPHA')
    gpu.state.line_width_set(1.0)
    gpu.state.depth_test_set('NONE' if settings.in_front else 'LESS_EQUAL')

    for frame, batch in items:
        distance = abs(frame - current)
        if distance == 0:
            continue
        fade = 1.0 - (distance / span) * 0.75
        colour = settings.colour_before if frame < current else settings.colour_after
        shader.bind()
        shader.uniform_float("color", (colour[0], colour[1], colour[2],
                                       settings.alpha * fade))
        batch.draw(shader)

    gpu.state.blend_set('NONE')
    gpu.state.depth_test_set('LESS_EQUAL')


def enable_draw():
    global _HANDLE
    if _HANDLE is None:
        _HANDLE = bpy.types.SpaceView3D.draw_handler_add(_draw, (), 'WINDOW', 'POST_VIEW')


def disable_draw():
    global _HANDLE
    if _HANDLE is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_HANDLE, 'WINDOW')
        _HANDLE = None


# ------------------------------------------------------------- settings

class SRP_OnionSettings(bpy.types.PropertyGroup):
    enabled: BoolProperty(name="Bật onion skin", default=False)
    mode: EnumProperty(
        name="Vẽ gì",
        items=(('BONE', "Xương", "Nhẹ — cả action cũng được"),
               ('MESH', "Mesh", "Nặng hơn, nên đặt bước nhảy lớn")),
        default='BONE')
    scope: EnumProperty(
        name="Phạm vi",
        items=(('ALL', "Cả action", ""),
               ('AROUND', "Quanh frame hiện tại", "")),
        default='AROUND')
    step: IntProperty(name="Bước nhảy", default=2, min=1, max=20)
    before: IntProperty(name="Số ghost trước", default=3, min=0, max=50)
    after: IntProperty(name="Số ghost sau", default=3, min=0, max=50)
    alpha: FloatProperty(name="Độ đậm", default=0.5, min=0.02, max=1.0, subtype='FACTOR')
    in_front: BoolProperty(name="Vẽ xuyên mesh", default=True)
    colour_before: FloatVectorProperty(name="Màu trước", size=3, subtype='COLOR',
                                       default=(0.25, 0.5, 1.0), min=0.0, max=1.0)
    colour_after: FloatVectorProperty(name="Màu sau", size=3, subtype='COLOR',
                                      default=(1.0, 0.45, 0.2), min=0.0, max=1.0)


# ------------------------------------------------------------ operators

class SRP_OT_onion_bake(bpy.types.Operator):
    "Nướng lại onion skin theo thiết lập hiện tại"
    bl_idname = "srp.onion_bake"
    bl_label = "Nướng onion skin"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return rigdef.active_rig(context) is not None

    def execute(self, context):
        settings = context.scene.srp_onion
        count, error = bake(context, settings)
        if error:
            self.report({'WARNING'}, error)
            return {'CANCELLED'}
        settings.enabled = True
        enable_draw()
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
        self.report({'INFO'}, "Nuong %d ghost (%s)"
                    % (count, "xuong" if settings.mode == 'BONE' else "mesh"))
        return {'FINISHED'}


class SRP_OT_onion_clear(bpy.types.Operator):
    "Tắt và xoá onion skin khỏi bộ nhớ"
    bl_idname = "srp.onion_clear"
    bl_label = "Tắt onion skin"
    bl_options = {'REGISTER'}

    def execute(self, context):
        clear()
        context.scene.srp_onion.enabled = False
        disable_draw()
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
        self.report({'INFO'}, "Đã xoá onion skin")
        return {'FINISHED'}


# --------------------------------------------------------------- panel

def draw_panel(layout, context):
        settings = context.scene.srp_onion

        row = layout.row(align=True)
        row.prop(settings, "enabled", text="Bật", toggle=True)
        row.operator("srp.onion_clear", text="Xoá")

        column = layout.column(align=True)
        column.prop(settings, "mode", expand=True)
        column.prop(settings, "scope", expand=True)

        row = layout.row(align=True)
        row.prop(settings, "step")
        if settings.scope == 'AROUND':
            row = layout.row(align=True)
            row.prop(settings, "before", text="Trước")
            row.prop(settings, "after", text="Sau")

        row = layout.row(align=True)
        row.prop(settings, "colour_before", text="")
        row.prop(settings, "colour_after", text="")
        layout.prop(settings, "alpha")
        layout.prop(settings, "in_front")

        layout.operator("srp.onion_bake", icon='ONIONSKIN_ON'
                        if 'ONIONSKIN_ON' in dir(bpy.types.UILayout) else 'GHOST_ENABLED')

        if _CACHE["items"]:
            box = layout.box()
            box.label(text="%d ghost đang giữ (%s, rig %s)"
                      % (len(_CACHE["items"]),
                         "xương" if _CACHE["mode"] == 'BONE' else "mesh",
                         _CACHE["rig"]))


# ------------------------------------------------------------- lifecycle

@persistent
def _on_load(_dummy):
    """Doi file la ghost cu vo nghia — xoa di, dung de no treo lai tren
    nhan vat khac."""
    clear()
    disable_draw()


def register_extra():
    bpy.types.Scene.srp_onion = PointerProperty(type=SRP_OnionSettings)
    if _on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load)


def unregister_extra():
    disable_draw()
    clear()
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    try:
        del bpy.types.Scene.srp_onion
    except AttributeError:
        pass


CLASSES = (SRP_OnionSettings, SRP_OT_onion_bake, SRP_OT_onion_clear)
