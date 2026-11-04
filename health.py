"""Kham rig — tim loi cau truc truoc khi no am tham pha animation.

Kiem tra dat nhat o day la `chi bi don`: cong tac de mot ben, nhung toan
bo chuyen dong lai nam o ben kia. Do dung la thu da xay ra voi 3.0_Rig —
driver mat, cong tac chan tro ve FK, trong khi 100% animation chan nam
tren LegIK. Khong render ra thi khong ai thay, va no im lang suot 31 action.
"""

import math

import bpy
from bpy.app.handlers import persistent

from . import compat, prefs, rigdef

ERROR, WARN, INFO = 'ERROR', 'WARN', 'INFO'
_RANK = {ERROR: 0, WARN: 1, INFO: 2}

# Bien do toi thieu de coi la "co chuyen dong".
MOVE_EPS = 0.02      # met, cho control IK
ROT_EPS = 0.01       # quaternion, cho chuoi FK
DEAD_EPS = 1e-4


class Finding:
    __slots__ = ("level", "code", "message", "hint")

    def __init__(self, level, code, message, hint=""):
        self.level = level
        self.code = code
        self.message = message
        self.hint = hint

    def line(self):
        mark = {ERROR: "[LOI ]", WARN: "[canh]", INFO: "[    ]"}[self.level]
        text = "%s %-14s %s" % (mark, self.code, self.message)
        if self.hint:
            text += "\n                      -> %s" % self.hint
        return text


# ------------------------------------------------------- kiem tra rig

def check_drivers(rig, limb, out):
    anim = rig.animation_data
    known = {}
    if anim is not None:
        for fcurve in anim.drivers:
            known[fcurve.data_path] = fcurve

    for bone, con_ik, con_fk in limb.blend_pairs(rig):
        for con, inverted in ((con_ik, False), (con_fk, True)):
            if con is None:
                out.append(Finding(ERROR, "CON_THIEU",
                                   "%s thieu constraint %s" % (bone.name,
                                                               "IK" if not inverted else "FK")))
                continue
            path = limb.con_path(bone.name, con.name)
            fcurve = known.get(path)
            if fcurve is None:
                out.append(Finding(
                    ERROR, "DRIVER_THIEU",
                    "%s / %s không có driver (influence đứng im ở %.2f)"
                    % (bone.name, con.name, con.influence),
                    "Bam 'Ap lai rig logic'"))
                continue
            driver = fcurve.driver
            want = "1.0 - switch" if inverted else "switch"
            if not driver.is_valid:
                out.append(Finding(ERROR, "DRIVER_HONG",
                                   "%s / %s: driver bao invalid" % (bone.name, con.name)))
            elif driver.expression.replace(" ", "") not in (want.replace(" ", ""),
                                                            want.replace("1.0", "1").replace(" ", "")):
                out.append(Finding(WARN, "DRIVER_LA",
                                   "%s / %s: expression %r, cho doi %r"
                                   % (bone.name, con.name, driver.expression, want)))
            if fcurve.mute:
                out.append(Finding(WARN, "DRIVER_TAT",
                                   "%s / %s: driver dang bi mute" % (bone.name, con.name)))

            # Sau khi append vao file da co san nhan vat nay, driver co the
            # con tro ve ban cu — rig moi trong nhu chay dung nhung thuc ra
            # dang nghe cong tac cua mot object khac.
            for var in driver.variables:
                for target in var.targets:
                    if target.id is not None and target.id is not rig:
                        out.append(Finding(
                            ERROR, "DRIVER_LAC",
                            "%s / %s: driver trỏ sang %r chứ không phải %r"
                            % (bone.name, con.name, target.id.name, rig.name),
                            "Bam 'Ap lai rig logic'"))


def check_constraint_names(rig, limb, out):
    for bone, con_ik, con_fk in limb.blend_pairs(rig):
        for con, want in ((con_ik, rigdef.CON_IK), (con_fk, rigdef.CON_FK)):
            if con is not None and con.name != want:
                out.append(Finding(
                    WARN, "TEN_CON",
                    "%s: constraint ten %r, chuan la %r" % (bone.name, con.name, want),
                    "Tên mặc định phân biệt IK/FK bằng thứ tự — đổi thứ tự là "
                    "sai câm lặng"))


def check_prop(rig, limb, out):
    bone = rig.pose.bones.get(rigdef.PROP_BONE)
    if bone is None:
        out.append(Finding(ERROR, "PROP_BONE", "Khong tim thay bone %r" % rigdef.PROP_BONE))
        return
    if limb.prop not in bone.keys():
        out.append(Finding(ERROR, "PROP_THIEU", "Thieu prop %r" % limb.prop))
        return
    try:
        ui = bone.id_properties_ui(limb.prop).as_dict()
    except TypeError:
        return
    if ui.get('min') != 0.0 or ui.get('max') != 1.0:
        out.append(Finding(INFO, "PROP_RANGE",
                           "%r chua gioi han 0..1 (dang %s..%s)"
                           % (limb.prop, ui.get('min'), ui.get('max'))))


def check_collections(rig, limb, out):
    """Collection control co bat/tat theo cong tac khong.

    Loi nay khong lam sai bien dang nen khong ai thay khi render — animator
    chi thay minh keo mot control ma nhan vat khong nhuc nhich.
    """
    armature = rig.data
    anim = armature.animation_data
    driven = {fcurve.data_path: fcurve for fcurve in (anim.drivers if anim else ())}
    switch = limb.switch(rig)

    for name, expression in limb.collections():
        spellings = ['%s["%s"].is_visible' % (attr, name)
                     for attr in ("collections", "collections_all")]
        if len([p for p in spellings if p in driven]) > 1:
            out.append(Finding(
                ERROR, "COL_TRUNG",
                "%r co 2 driver visibility cung luc" % name,
                "collections[...] và collections_all[...] là cùng một thuộc "
                "tính nhưng Blender lưu thành 2 F-curve — chúng tranh nhau"))

        path = rigdef.collection_path(armature, name)
        if path is None:
            out.append(Finding(WARN, "COL_THIEU",
                               "%s: không có bone collection %r" % (limb.label, name)))
            continue

        fcurve = driven.get(path)
        if fcurve is None:
            visible = armature.collections_all[name].is_visible
            note = ""
            if switch is not None:
                want = (switch > 0.0 if expression == rigdef.COLLECTION_IK_EXPR
                        else switch < 1.0)
                if bool(visible) != bool(want):
                    note = ("— đang %s trong khi công tắc ở %.2f, đáng lẽ phải "
                            "%s"
                            % ("hien" if visible else "an", switch,
                               "hien" if want else "an"))
            out.append(Finding(
                ERROR, "COL_TINH",
                "%r không có driver visibility%s" % (name, note),
                "Bam 'Ap lai rig logic'"))
            continue

        if fcurve.driver.expression.replace(" ", "") != expression.replace(" ", ""):
            out.append(Finding(WARN, "COL_LA",
                               "%r: expression %r, cho doi %r"
                               % (name, fcurve.driver.expression, expression)))


def check_ik(context, rig, limbs, out):
    by_kind = {}
    for limb in limbs:
        con = limb.ik_constraint(rig)
        if con is None:
            out.append(Finding(ERROR, "IK_THIEU", "%s: khong thay constraint IK" % limb.label))
            continue
        by_kind.setdefault(limb.kind, {})[limb.side] = (limb, con)

        if con.use_stretch:
            bone = rig.pose.bones.get(limb.solver)
            locked = bone is not None and (bone.lock_ik_x or bone.lock_ik_y or bone.lock_ik_z
                                           or bone.use_ik_limit_x or bone.use_ik_limit_y
                                           or bone.use_ik_limit_z)
            if not locked:
                out.append(Finding(
                    WARN, "IK_GIAN",
                    "%s: use_stretch bat, khong khoa truc nao, stiffness 0" % limb.label,
                    "Chi giãn được và khớp gập ngược được. Bấm 'Tắt IK stretch' "
                    "nếu không có chủ ý"))

    # KHONG so pole_angle trai/phai nua. Hai ben chi guong nhau nen roll doi
    # chieu, va `pole_angle` lech dung 180 do la KET QUA DUNG — do duoc tren
    # rig sinh moi: sau khi hieu chuan, tay ra -180 va 0 do, ca hai deu chuan
    # den 0.001 mm. So goc kieu cu bao dong nham suot.
    # Phep kiem that: o rest, loi giai IK phai tai tao dung rest pose.
    from . import snap
    for limb in limbs:
        if limb.ik_constraint(rig) is None:
            continue
        gap = snap.rest_ik_gap(context, rig, limb)
        if gap is not None and gap > 0.002:
            out.append(Finding(
                ERROR, "POLE_SAI",
                "%s: ở rest, IK giải ra khớp giữa lệch %.1f mm so với rest pose"
                % (limb.label, gap * 1000.0),
                "pole_angle đang sai — bấm 'Đo lại pole angle'. LƯU Ý: sửa nó "
                "là đổi kết quả solve của mọi action đã bake"))


# --------------------------------------------------- kiem tra action

def _switch_values(action, limb, slot):
    values = []
    for fcurve in compat.action_fcurves(action, slot):
        if fcurve.data_path == limb.prop_path:
            values.extend(point.co[1] for point in fcurve.keyframe_points)
    return values


def _amplitude(action, limb, slot):
    fk_amp = ik_amp = 0.0
    fk_set, ctrl_set = set(limb.fk), {limb.ctrl, limb.pole}
    for fcurve in compat.action_fcurves(action, slot):
        bone = compat.bone_of(fcurve.data_path)
        if bone is None:
            continue
        span = compat.curve_amplitude(fcurve)
        if bone in fk_set and "rotation" in fcurve.data_path:
            fk_amp = max(fk_amp, span)
        elif bone in ctrl_set and fcurve.data_path.endswith("location"):
            ik_amp = max(ik_amp, span)
    return fk_amp, ik_amp


def check_actions(rig, limbs, actions, out):
    for action in actions:
        slot = compat.action_slot_for(action, rig)
        if len(action.slots) > 1:
            out.append(Finding(
                INFO, "NHIEU_SLOT",
                "%s có %d slot — dùng chung với nhân vật khác" % (action.name, len(action.slots)),
                "Chọn đúng slot trước khi sửa, nếu không là sửa nhầm nhân vật"))

        names = {bone.name for bone in rig.data.bones}
        orphan = set()
        for fcurve in compat.action_fcurves(action, slot):
            bone = compat.bone_of(fcurve.data_path)
            if bone is not None and bone not in names:
                orphan.add(bone)
        if orphan:
            out.append(Finding(
                INFO, "CHANNEL_RAC",
                "%s: %d bone không tồn tại trong rig" % (action.name, len(orphan)),
                "vd: " + ", ".join(sorted(orphan)[:4])))

        for limb in limbs:
            fk_amp, ik_amp = _amplitude(action, limb, slot)
            keyed = _switch_values(action, limb, slot)
            static = limb.switch(rig)
            if keyed:
                mode_ik = max(keyed) > 0.5
                mixed = min(keyed) < 0.5 < max(keyed)
            else:
                mode_ik = static is not None and static > 0.5
                mixed = False
            if mixed:
                continue      # action co chuyen che do giua chung, bo qua

            if not mode_ik and ik_amp > MOVE_EPS and fk_amp < DEAD_EPS:
                out.append(Finding(
                    ERROR, "CHI_DON",
                    "%s / %s: công tắc để FK nhưng chuyển động nằm hết trên %s "
                    "(biên độ %.3f)"
                    % (action.name, limb.label, limb.ctrl, ik_amp),
                    "Chi này đang đứng im khi phát. Lật công tắc sang IK hoặc "
                    "snap lại"))
            elif mode_ik and fk_amp > ROT_EPS and ik_amp < DEAD_EPS:
                out.append(Finding(
                    ERROR, "CHI_DON",
                    "%s / %s: công tắc để IK nhưng chuyển động nằm hết trên "
                    "chuỗi FK (biên độ %.3f)"
                    % (action.name, limb.label, fk_amp),
                    "Lat cong tac sang FK hoac snap lai"))


# ------------------------------------------------------------------ api

def run(context, rig, actions=None):
    out = []
    limbs = rigdef.limbs_for(rig)
    if not limbs:
        out.append(Finding(ERROR, "KHONG_KHOP", "Rig không khớp convention nào "
                                                "của addon"))
        return out

    for limb in limbs:
        missing = limb.missing(rig)
        if missing:
            out.append(Finding(WARN, "BONE_THIEU",
                               "%s thieu bone: %s" % (limb.label, ", ".join(missing))))
        check_prop(rig, limb, out)
        check_constraint_names(rig, limb, out)
        check_drivers(rig, limb, out)
        check_collections(rig, limb, out)
    check_ik(context, rig, limbs, out)

    if actions is None:
        actions = _actions_of(rig)
    check_actions(rig, limbs, actions, out)

    out.sort(key=lambda f: (_RANK[f.level], f.code))
    return out


def _actions_of(rig):
    """Action thuoc rig nay — chon rig KHOP NHAT, khong phai vuot nguong.

    Mot file co the chua nhieu rig dung chung he ten xuong: ban rut gon 109
    xuong va ban day du 216 xuong co them xuong mat. Lay nguong 50% thi action
    cua ban day du bi gan nham sang ban rut gon, roi bao "channel rac" cho ca
    dong xuong mat hoan toan hop le. Da mac dung loi nay mot lan.
    """
    names = {bone.name for bone in rig.data.bones}
    others = [(o, {b.name for b in o.data.bones}) for o in bpy.data.objects
              if o.type == 'ARMATURE' and o is not rig]
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
        if score <= 0.5:
            continue
        if any(len(bones & other) / len(bones) > score for _obj, other in others):
            continue        # co rig khac khop hon, action khong phai cua rig nay
        found.append(action)
    return found


TEXT_NAME = "RigTamHanh_KhamRig"


def write_report(rig, findings):
    lines = ["=" * 72,
             "KHAM RIG: %s" % rig.name,
             "=" * 72, ""]
    counts = {ERROR: 0, WARN: 0, INFO: 0}
    for finding in findings:
        counts[finding.level] += 1
    lines.append("Loi: %d   Canh bao: %d   Ghi chu: %d"
                 % (counts[ERROR], counts[WARN], counts[INFO]))
    lines.append("")
    if not findings:
        lines.append("Không tìm thấy vấn đề nào.")
    for finding in findings:
        lines.append(finding.line())

    text = bpy.data.texts.get(TEXT_NAME) or bpy.data.texts.new(TEXT_NAME)
    text.clear()
    text.write("\n".join(lines))
    return text, counts


# ------------------------------------------------- tu phat hien khi mo file

# Ket qua quet nhanh gan nhat: {ten rig: (so loi, so canh bao)}
STATUS = {}


def quick_scan(context):
    """Quet NHE, chi doc, khong dung vao pose hay du lieu.

    Co y bo qua `rest_ik_gap` va phan quet action: hai cai do dua ca rig ve
    rest roi tra lai, va duyet toan bo thu vien action. Chay tu dong nhung
    thu do moi lan mo file la vua cham vua dam vao pose nguoi ta dang lam.
    Cai can bat tu dong chi la: driver con khong, constraint con khong.
    """
    STATUS.clear()
    for rig in rigdef.managed_rigs(context):
        out = []
        for limb in rigdef.limbs_for(rig):
            check_prop(rig, limb, out)
            check_drivers(rig, limb, out)
            check_collections(rig, limb, out)
        errors = sum(1 for f in out if f.level == ERROR)
        warns = sum(1 for f in out if f.level == WARN)
        if errors or warns:
            STATUS[rig.name] = (errors, warns)
    return STATUS


def broken_rigs():
    return [name for name, (errors, _w) in STATUS.items() if errors]


def _scan_after_load():
    """Chay tre mot nhip — luc `load_post` ban ra thi depsgraph chua san sang."""
    try:
        context = bpy.context
        quick_scan(context)
        broken = broken_rigs()
        if broken:
            prefs.log("[Rig Tẩm Hành] %d rig thieu driver/constraint: %s"
                  % (len(broken), ", ".join(broken)))
            # Ten rieng, KHONG dat `prefs`: gan `prefs = ...` trong ham bien
            # `prefs` thanh bien cuc bo cho CA ham, va `prefs.log()` o tren nem
            # UnboundLocalError — `except` ben duoi nuot mat, tu sua khong bao
            # gio chay.
            addon_prefs = _preferences()
            if addon_prefs is not None and addon_prefs.auto_fix:
                from . import build
                for name in broken:
                    rig = bpy.data.objects.get(name)
                    if rig is not None:
                        build.apply_logic(context, rig)
                prefs.log("[Rig Tẩm Hành] đã tự sửa %d rig (bật trong Preferences)" % len(broken))
                quick_scan(context)
    except Exception as error:               # khong bao gio duoc lam vo file load
        print("[Rig Tẩm Hành] quet tu dong that bai:", error)
    return None


def _preferences():
    addon = bpy.context.preferences.addons.get(__package__)
    return getattr(addon, "preferences", None) if addon else None


@persistent
def on_load(_dummy):
    STATUS.clear()
    bpy.app.timers.register(_scan_after_load, first_interval=0.4)


class SRP_OT_quick_scan(bpy.types.Operator):
    "Quét lại nhanh (driver, constraint, collection)"
    bl_idname = "srp.quick_scan"
    bl_label = "Quét lại"
    bl_options = {'REGISTER'}

    def execute(self, context):
        quick_scan(context)
        broken = broken_rigs()
        self.report({'WARNING'} if broken else {'INFO'},
                    "%d rig có vấn đề" % len(STATUS) if STATUS else "Moi rig deu on")
        return {'FINISHED'}


class SRP_OT_health(bpy.types.Operator):
    "Khám rig và ghi báo cáo ra text block"
    bl_idname = "srp.health"
    bl_label = "Khám rig"
    bl_options = {'REGISTER'}

    all_actions: bpy.props.BoolProperty(
        name="Quét cả thư viện action", default=True,
        description="Tắt đi thì chỉ kiểm tra action đang gắn")

    @classmethod
    def poll(cls, context):
        return rigdef.active_rig(context) is not None

    def execute(self, context):
        rig = rigdef.active_rig(context)
        actions = None
        if not self.all_actions:
            anim = rig.animation_data
            actions = [anim.action] if anim and anim.action else []
        findings = run(context, rig, actions)
        _text, counts = write_report(rig, findings)
        level = 'ERROR' if counts[ERROR] else ('WARNING' if counts[WARN] else 'INFO')
        self.report({level}, "%d loi, %d canh bao — xem text %r"
                    % (counts[ERROR], counts[WARN], TEXT_NAME))
        return {'FINISHED'}


def register_extra():
    if on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(on_load)


def unregister_extra():
    if on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(on_load)
    STATUS.clear()


CLASSES = (SRP_OT_quick_scan, SRP_OT_health)
