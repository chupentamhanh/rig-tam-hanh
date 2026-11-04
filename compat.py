"""Lop tuong thich Blender 5.0 — slotted action va depsgraph.

Hai cai bay da tra gia:
  * Blender 5.0 bo `action.fcurves`. Moi truy cap curve phai di qua
    layers -> strips -> channelbags. Dung `action_fcurves()` o day, dung
    tu viet lai.
  * Doi custom property bang script KHONG tu dong bat driver tinh lai.
    Phai `refresh()` truoc khi doc influence, neu khong se doc ra gia tri
    cu va tuong driver hong.
"""

import bpy


# ---------------------------------------------------------------- actions

def action_slot_for(action, id_):
    """Slot hop voi `id_` nhat trong action.

    Khong duoc lay bua slot OBJECT dau tien: mot action dung chung cho hai
    nhan vat co hai slot, va lay nham thi key ghi vao kenh cua nhan vat kia
    — sai lang le, khong bao loi. Cham diem tung slot theo ty le ten xuong
    co that trong rig.
    """
    slots = list(action.slots)
    if not slots:
        return None

    current = getattr(getattr(id_, "animation_data", None), "action_slot", None)
    if current is not None and current in slots:
        return current

    pose = getattr(id_, "pose", None)
    if pose is not None:
        names = {bone.name for bone in pose.bones}
        best, best_score = None, -1.0
        for slot in slots:
            if slot.target_id_type != 'OBJECT':
                continue
            bones = set()
            for bag in action_channelbags(action, slot):
                for fcurve in bag.fcurves:
                    bone = bone_of(fcurve.data_path)
                    if bone:
                        bones.add(bone)
            score = len(bones & names) / len(bones) if bones else 0.0
            # Hai nhan vat cung he ten xuong thi ca hai slot deu khop 100%,
            # luc do ten slot la manh moi duy nhat con lai.
            if getattr(slot, "name_display", "") == getattr(id_, "name", None):
                score += 0.5
            if score > best_score:
                best, best_score = slot, score
        if best is not None:
            return best

    for slot in slots:
        if slot.target_id_type == 'OBJECT':
            return slot
    return slots[0]


def action_channelbags(action, slot=None):
    """Channelbag cua action; loc theo slot neu co truyen vao."""
    want = getattr(slot, "handle", None)
    for layer in action.layers:
        for strip in layer.strips:
            for bag in getattr(strip, "channelbags", ()):
                if want is None or getattr(bag, "slot_handle", want) == want:
                    yield bag


def action_fcurves(action, slot=None):
    for bag in action_channelbags(action, slot):
        for fcurve in bag.fcurves:
            yield fcurve


def action_channelbag(action, slot=None, create=False):
    """Channelbag de GHI key vao. `create=True` thi tu dung layer/strip/bag."""
    for bag in action_channelbags(action, slot):
        return bag
    if not create:
        return None
    layer = action.layers.new("Layer") if not len(action.layers) else action.layers[0]
    strip = layer.strips.new(type='KEYFRAME') if not len(layer.strips) else layer.strips[0]
    if slot is None:
        slot = action.slots.new('OBJECT', "Slot")
    return strip.channelbag(slot, ensure=True)


def assign_action(rig, action):
    """Gan action va chon dung slot OBJECT — thieu buoc slot thi rig khong nhuc nhich."""
    anim = rig.animation_data or rig.animation_data_create()
    anim.action = action
    if action is None:
        return None
    slot = action_slot_for(action, rig)
    if slot is not None:
        anim.action_slot = slot
    return slot


def bone_of(data_path):
    """Ten bone trong mot data_path, hoac None."""
    if not data_path.startswith('pose.bones["'):
        return None
    rest = data_path[len('pose.bones["'):]
    end = rest.find('"]')
    return rest[:end] if end > 0 else None


def curve_amplitude(fcurve):
    points = fcurve.keyframe_points
    if len(points) < 2:
        return 0.0
    values = [point.co[1] for point in points]
    return max(values) - min(values)


# ------------------------------------------------------------- depsgraph

def refresh(context, rig):
    """Ep driver + constraint tinh lai. BAT BUOC sau khi doi custom prop."""
    rig.update_tag(refresh={'DATA'})
    context.view_layer.depsgraph.update()


def evaluated(context, rig):
    return rig.evaluated_get(context.evaluated_depsgraph_get())


def pose_snapshot(context, rig, names):
    """Matrix object-space da qua constraint, chup mot lan truoc khi sua.

    Phai chup het truoc khi ghi — ghi bone dau tien la moi matrix sau do
    doi het, doc dan xen se ra pose sai ma khong bao loi.
    """
    ev_rig = evaluated(context, rig)
    out = {}
    for name in names:
        bone = ev_rig.pose.bones.get(name)
        if bone is not None:
            out[name] = bone.matrix.copy()
    return out
