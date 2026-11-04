"""Doi ten xuong trong action — cuu thu vien animation sau khi sua rig.

Doi ten hay doi cha mot xuong la moi fcurve tro toi no thanh mo coi: data_path
van ghi `pose.bones["TenCu"]`, Blender khong bao loi, chi lang le khong chay.
Day dung la thu chan chung ta khong dam dong vao ten xuong cua `3.0_Rig` suot
tu dau — co no roi thi doi ten khong con la duong mot chieu.

Cach lam: QUET ra text block cho nguoi doc va sua, roi moi AP DUNG. Khong tu
doan roi tu sua — goi y ten gan giong chi la goi y, `Foot.L` va `FootFK.L`
giong nhau den muc may khong the tu quyet.
"""

import difflib
import re
from collections import Counter

import bpy
from bpy.props import BoolProperty

from . import compat, prefs, rigdef

TEXT_NAME = "RigTamHanh_Remap"
BONE_TOKEN = 'pose.bones["%s"]'
BONE_RE = re.compile(r'pose\.bones\["([^"]+)"\]')


def actions_for(rig):
    """Action can xet cho rig nay.

    Lay theo hai duong, va PHAI co ca hai:

      1. Action dang gan cho rig — ke ca khi khong mot ten xuong nao trung.
      2. Action co it nhat mot xuong trung ten.

    Chi lay theo (2) la hong dung ca quan trong nhat: action muon tu rig khac
    thi KHONG trung ten nao ca, bi loai khoi danh sach, va remap khong bao gio
    cham toi duoc no. Do dung la thu can sua.

    Khong quet bua moi action trong file: lam vay la de nghi doi ten channel
    cua nhan vat khac.
    """
    names = {bone.name for bone in rig.data.bones}
    found = []
    anim = rig.animation_data
    if anim is not None and anim.action is not None:
        found.append(anim.action)
        for track in anim.nla_tracks:
            for strip in track.strips:
                if strip.action is not None and strip.action not in found:
                    found.append(strip.action)

    for action in bpy.data.actions:
        if action in found:
            continue
        bones = set()
        for fcurve in compat.action_fcurves(action):
            bone = compat.bone_of(fcurve.data_path)
            if bone:
                bones.add(bone)
        if bones and (bones & names):
            found.append(action)
    return found


def orphan_bones(rig, actions):
    """{ten xuong khong ton tai: so fcurve tro toi no}."""
    names = {bone.name for bone in rig.data.bones}
    found = Counter()
    for action in actions:
        for fcurve in compat.action_fcurves(action):
            bone = compat.bone_of(fcurve.data_path)
            if bone and bone not in names:
                found[bone] += 1
    return found


def suggest(name, candidates, cutoff=0.72):
    matches = difflib.get_close_matches(name, candidates, n=1, cutoff=cutoff)
    return matches[0] if matches else None


# --------------------------------------------------------------- ke hoach

HEADER = """# Ke hoach doi ten channel — Rig Tẩm Hành
#
# Moi dong: TEN_CU -> TEN_MOI
# Dong bat dau bang # bi bo qua. Xoa dong nao thi channel do giu nguyen.
# Sua xong bam "Ap dung ke hoach".
#
# Rig: %s
# Action quet: %d
"""


def shared_actions(context, rig, actions):
    """Action ma rig KHAC cung dung — doi ten o day la sua ca cua ho.

    Ca that trong project: 31 action dung chung giua `3.0_Rig` (109 xuong) va
    `Simplified_Female` (216 xuong). Voi rig 109 xuong thi 44 channel xuong mat
    la "mo coi", nhung voi rig 216 xuong chung hoan toan hop le. Remap o day la
    pha du lieu cua rig kia.
    """
    others = [r for r in rigdef.managed_rigs(context) if r is not rig]
    if not others:
        return []
    out = []
    for action in actions:
        bones = set()
        for fcurve in compat.action_fcurves(action):
            bone = compat.bone_of(fcurve.data_path)
            if bone:
                bones.add(bone)
        if not bones:
            continue
        mine = len(bones & {b.name for b in rig.data.bones}) / len(bones)
        for other in others:
            theirs = len(bones & {b.name for b in other.data.bones}) / len(bones)
            if theirs > mine:
                out.append((action.name, other.name))
                break
    return out


def write_plan(rig, orphans, actions, context=None):
    names = sorted(bone.name for bone in rig.data.bones)
    lines = [HEADER % (rig.name, len(actions))]

    shared = shared_actions(context, rig, actions) if context else []
    if shared:
        lines.append("# !!! CAN THAN: %d action duoi day khop VOI RIG KHAC hon."
                     % len(shared))
        lines.append("# Đổi tên channel ở đây là sửa cả animation của rig đó.")
        for name, owner in shared[:8]:
            lines.append("#    %s  ->  hop voi %s hon" % (name, owner))
        if len(shared) > 8:
            lines.append("#    ... va %d action nua" % (len(shared) - 8))
        lines.append("#")
    if not orphans:
        lines.append("# Không có channel mồ côi nào. Không phải làm gì.")
    for old, count in orphans.most_common():
        guess = suggest(old, names)
        if guess:
            lines.append("%s -> %s" % (old, guess))
            lines.append("#    ^ %d fcurve | gợi ý tự động, KIỂM LẠI trước khi "
                         "áp dụng"
                         % count)
        else:
            lines.append("# %s -> ???" % old)
            lines.append("#    ^ %d fcurve | không đoán được, tự điền tên rồi "
                         "bỏ dấu #"
                         % count)
    text = bpy.data.texts.get(TEXT_NAME) or bpy.data.texts.new(TEXT_NAME)
    text.clear()
    text.write("\n".join(lines) + "\n")
    return text


def read_plan(rig):
    """[(cu, moi)] tu text block, kem danh sach dong loi."""
    text = bpy.data.texts.get(TEXT_NAME)
    if text is None:
        return [], ["chưa có text %r — bấm 'Quét channel mồ côi' trước" % TEXT_NAME]

    names = {bone.name for bone in rig.data.bones}
    pairs, problems = [], []
    for number, raw in enumerate(text.as_string().splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "->" not in line:
            problems.append("dong %d: thieu '->'" % number)
            continue
        old, new = (part.strip() for part in line.split("->", 1))
        if not old or not new:
            problems.append("dong %d: thieu ten" % number)
        elif new not in names:
            problems.append("dòng %d: %r không có trong rig" % (number, new))
        else:
            pairs.append((old, new))
    return pairs, problems


# ---------------------------------------------------------------- ap dung

def _rewrite(path, old, new):
    return path.replace(BONE_TOKEN % old, BONE_TOKEN % new)


def apply_plan(context, rig, pairs, actions, dry_run=True):
    """Doi data_path cua fcurve va driver. Tra ve (so doi, so bo qua, ghi chu)."""
    mapping = dict(pairs)
    changed = skipped = 0
    notes = []

    for action in actions:
        slot = compat.action_slot_for(action, rig)
        for bag in compat.action_channelbags(action, slot):
            taken = {(fc.data_path, fc.array_index) for fc in bag.fcurves}
            for fcurve in list(bag.fcurves):
                bone = compat.bone_of(fcurve.data_path)
                if bone not in mapping:
                    continue
                target = _rewrite(fcurve.data_path, bone, mapping[bone])
                if (target, fcurve.array_index) in taken:
                    # Ghi de len channel dang co la mat du lieu that — bo qua.
                    skipped += 1
                    notes.append("%s: %s đã có sẵn, giữ nguyên channel cũ"
                                 % (action.name, target))
                    continue
                if not dry_run:
                    taken.discard((fcurve.data_path, fcurve.array_index))
                    fcurve.data_path = target
                    taken.add((target, fcurve.array_index))
                changed += 1

            # Ten nhom kenh van hien ten cu thi nhin rat kho hieu.
            if not dry_run:
                for group in bag.groups:
                    if group.name in mapping:
                        group.name = mapping[group.name]

    # Driver nam o CA object lan armature data (driver hien/an collection). Dem
    # nhu nhau o dry run va chay that — truoc day chay that khong dem, nen hai
    # che do bao hai con so khac nhau cho cung mot ke hoach.
    for owner in (rig, rig.data):
        anim = owner.animation_data
        for fcurve in (anim.drivers if anim else ()):
            bone = compat.bone_of(fcurve.data_path)
            if bone in mapping:
                if not dry_run:
                    fcurve.data_path = _rewrite(fcurve.data_path, bone,
                                                mapping[bone])
                changed += 1
            for variable in fcurve.driver.variables:
                for target in variable.targets:
                    hit = BONE_RE.search(target.data_path or "")
                    if hit and hit.group(1) in mapping:
                        if not dry_run:
                            target.data_path = _rewrite(
                                target.data_path, hit.group(1),
                                mapping[hit.group(1)])
                        changed += 1
                    # Bien TRANSFORMS / ROTATION_DIFF / LOC_DIFF tro bone qua
                    # `bone_target`, khong qua data_path.
                    if variable.type != 'SINGLE_PROP' and target.bone_target in mapping:
                        if not dry_run:
                            target.bone_target = mapping[target.bone_target]
                        changed += 1
    return changed, skipped, notes


# ------------------------------------------------------------- operators

class SRP_OT_remap_scan(bpy.types.Operator):
    "Quét channel mồ côi và ghi kế hoạch đổi tên ra text block"
    bl_idname = "srp.remap_scan"
    bl_label = "Quét channel mồ côi"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return rigdef.active_rig(context) is not None

    def execute(self, context):
        rig = rigdef.active_rig(context)
        actions = actions_for(rig)
        orphans = orphan_bones(rig, actions)
        write_plan(rig, orphans, actions, context)
        if not orphans:
            self.report({'INFO'}, "%d action, không có channel mồ côi" % len(actions))
        else:
            self.report({'WARNING'}, "%d tên xương mồ côi trong %d action — sửa "
                                     "text %r"
                        % (len(orphans), len(actions), TEXT_NAME))
        return {'FINISHED'}


class SRP_OT_remap_apply(bpy.types.Operator):
    "Đọc kế hoạch từ text block và đổi tên channel"
    bl_idname = "srp.remap_apply"
    bl_label = "Áp dụng kế hoạch"
    bl_options = {'REGISTER', 'UNDO'}

    dry_run: BoolProperty(
        name="Chỉ thử, chưa sửa thật", default=True,
        description="Bật: chỉ đếm xem sẽ đổi bao nhiêu. Tắt: sửa thật")

    @classmethod
    def poll(cls, context):
        return rigdef.active_rig(context) is not None

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        rig = rigdef.active_rig(context)
        pairs, problems = read_plan(rig)
        if problems:
            self.report({'ERROR'}, "Ke hoach co loi: %s" % problems[0])
            return {'CANCELLED'}
        if not pairs:
            self.report({'WARNING'}, "Kế hoạch rỗng")
            return {'CANCELLED'}

        actions = actions_for(rig)
        changed, skipped, notes = apply_plan(context, rig, pairs, actions,
                                             dry_run=self.dry_run)
        for note in notes:
            prefs.log("[Rig Tẩm Hành remap] " + note)
        head = "THU: se doi" if self.dry_run else "Da doi"
        message = "%s %d channel tren %d action" % (head, changed, len(actions))
        if skipped:
            message += " | bỏ qua %d cái vì trùng channel có sẵn" % skipped
        self.report({'WARNING' if skipped or self.dry_run else 'INFO'}, message)
        return {'FINISHED'}


def draw_panel(layout, context):
    rig = rigdef.active_rig(context)
    column = layout.column(align=True)
    column.operator("srp.remap_scan", icon='VIEWZOOM')

    text = bpy.data.texts.get(TEXT_NAME)
    if text is not None:
        pairs, problems = read_plan(rig) if rig else ([], [])
        box = layout.box()
        if problems:
            row = box.row()
            row.alert = True
            row.label(text=problems[0], icon='ERROR')
        else:
            box.label(text="%d dòng đổi tên" % len(pairs),
                      icon='CHECKMARK' if pairs else 'DOT')
        box.label(text="Sửa ở text %r" % TEXT_NAME)

    layout.operator("srp.remap_apply", icon='FILE_REFRESH')


CLASSES = (SRP_OT_remap_scan, SRP_OT_remap_apply)
