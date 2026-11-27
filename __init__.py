"""Rig Tẩm Hành — bo cong cu rig rieng cho convention .L/.R + *FK/*IK.

Da xong: nen tang, ap lai rig logic, kham rig, snap IK/FK, bo sinh rig tu BO
XUONG REF (thay cho marker kieu ARP), widget, picker, onion skin, shape key
khuon mat.
Chua lam: tool socket/outfit, jiggle physics, pose library.

Xem CHANGELOG.md ben canh file nay: ghi doi gi o ban nao, kem SO DO DUOC.
"""

bl_info = {
    "name": "Rig Tẩm Hành",
    "author": "Chú Pen Tẩm Hành",
    "version": (1, 41, 1),
    "blender": (5, 0, 0),
    "location": "View3D > N-Panel > Rig Tẩm Hành",
    "description": "Dựng rig từ bộ xương ref hoặc theo nhân vật mẫu, weight, "
                   "quần áo, shape key khuôn mặt, snap IK/FK, picker, xuất Unity "
                   "Humanoid. Chạy hoàn toàn offline",
    "category": "Rigging",
}

import importlib

import bpy
from bpy.props import BoolProperty

from . import (prefs, compat, rigdef, build, health, snap, widgets, picker,
               tools, onion, refrig, cloth, generate, refsync, facerig, face, posekey,
               mirrorkey, fitref, bakeweights, followkeys, facebendy, weightfence, topoweights, templateweights, weightauto, retarget, markers, unityexport, remap, uikit, ux, ui)

_MODULES = (prefs, compat, rigdef, build, health, snap, widgets, picker, tools,
            onion, refrig, cloth, generate, refsync, facerig, face, posekey, mirrorkey,
            fitref, bakeweights, followkeys, facebendy, weightfence, topoweights, templateweights, weightauto, retarget, markers, unityexport, remap, uikit, ux, ui)


class SRP_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    auto_fix: BoolProperty(
        name="Tự sửa rig logic khi mở file",
        default=False,
        description="Mở file thấy rig thiếu driver/constraint thì tự dựng lại "
                    "ngay. Mặc định TẮT: tự sửa là tự ghi vào file của người ta "
                    "trước khi họ kịp nhìn, và nếu code sai thì hỏng mà không "
                    "ai bấm nút nào")

    verbose: BoolProperty(
        name="Hiện số liệu kỹ thuật",
        default=False,
        description="Bật: in hết phép đo ra console và gắn vào báo cáo (bán "
                    "kính nhãn cầu, sai số khớp cầu, độ giãn cạnh, hằng số hiệu "
                    "chỉnh...), kèm panel hằng số. Mặc định TẮT — người dùng "
                    "addon để rig nhân vật không cần nhìn những số đó, và thấy "
                    "chúng thì tưởng máy hỏng")

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "auto_fix")
        column = layout.column(align=True)
        column.scale_y = 0.85
        column.label(text="Tắt hay bật, addon vẫn luôn TỰ QUÉT khi mở file và "
                          "báo")
        column.label(text="ở mục 'Sửa & kiểm tra'. Khác biệt chỉ là có tự bấm "
                          "nút hay không.")
        layout.separator()
        layout.prop(self, "verbose")

for _module in _MODULES:
    importlib.reload(_module)

# PropertyGroup phai dang ky TRUOC khi gan PointerProperty tro toi no.
_CLASSES = ((SRP_Preferences,) + build.CLASSES + health.CLASSES + snap.CLASSES
            + widgets.CLASSES + picker.CLASSES + tools.CLASSES + onion.CLASSES
            + refrig.CLASSES + cloth.CLASSES + generate.CLASSES + refsync.CLASSES
            + face.CLASSES + posekey.CLASSES + mirrorkey.CLASSES
            + fitref.CLASSES + bakeweights.CLASSES + followkeys.CLASSES + facebendy.CLASSES + weightfence.CLASSES + retarget.CLASSES + markers.CLASSES + unityexport.CLASSES + remap.CLASSES
            + uikit.CLASSES + ux.CLASSES + ui.CLASSES)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    onion.register_extra()
    cloth.register_extra()
    refrig.register_extra()
    generate.register_extra()
    face.register_extra()
    unityexport.register_extra()
    retarget.register_extra()
    markers.register_extra()
    health.register_extra()
    # Khong quet ngay trong register(): luc do `bpy.context` la _RestrictContext,
    # chua co `scene`. Hoan mot nhip qua timer, dung duong nhu khi mo file.
    bpy.app.timers.register(health._scan_after_load, first_interval=0.5)


def unregister():
    health.unregister_extra()
    markers.unregister_extra()
    retarget.unregister_extra()
    unityexport.unregister_extra()
    face.unregister_extra()
    generate.unregister_extra()
    refrig.unregister_extra()
    cloth.unregister_extra()
    onion.unregister_extra()
    for cls in reversed(_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
