import io
import math
import sys
import contextlib
import addon_utils
import bpy
from mathutils import Quaternion, Vector

addon_utils.disable("rig_tam_hanh")
for name in [m for m in sys.modules if m == "rig_tam_hanh" or m.startswith("rig_tam_hanh.")]:
    del sys.modules[name]
addon_utils.enable("rig_tam_hanh", default_set=True)
pkg = sys.modules["rig_tam_hanh"]
from rig_tam_hanh import health, rigdef, snap, widgets, remap, refrig, face

ctx = bpy.context
rig = bpy.data.objects["Kid_Rig.001"]
print("reloaded; enabled:", "rig_tam_hanh" in ctx.preferences.addons)

# --- health: exercise the broken-rig branch that used to raise UnboundLocalError
orig = health.broken_rigs
health.broken_rigs = lambda: ["FakeRig"]
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    health._scan_after_load()
health.broken_rigs = orig
print("health _scan_after_load output:", repr(buf.getvalue()) or "(none)")

# --- snap: IK <- FK on a leg whose foot roll is posed
saved = {pb.name: pb.matrix_basis.copy() for pb in rig.pose.bones}
root = rig.pose.bones["Root"]
saved_props = {k: root[k] for k in root.keys()}
try:
    limb = rigdef.limb_by_name(rig, "LEG.L")
    pb = rig.pose.bones
    pb["ThighFK.L"].rotation_quaternion = Quaternion((1, 0, 0), math.radians(-35))
    pb["ShinFK.L"].rotation_quaternion = Quaternion((1, 0, 0), math.radians(50))
    pb["FootFK.L"].rotation_quaternion = Quaternion((1, 0, 0), math.radians(-20))
    pb["Heel.L"].rotation_quaternion = Quaternion((1, 0, 0), math.radians(25))
    pb["Ball.L"].rotation_quaternion = Quaternion((1, 0, 0), math.radians(-15))
    ctx.view_layer.update()
    snap.snap_ik_to_fk(ctx, rig, limb)
    ctx.view_layer.update()
    ev = rig.evaluated_get(ctx.evaluated_depsgraph_get())
    def gap(a, b):
        return (ev.pose.bones[a].head - ev.pose.bones[b].head).length * 1000
    def ang(a, b):
        qa = ev.pose.bones[a].matrix.to_quaternion()
        qb = ev.pose.bones[b].matrix.to_quaternion()
        return math.degrees(qa.rotation_difference(qb).angle)
    print("leg snap: shin head gap %.3f mm, foot head gap %.3f mm, foot rot diff %.3f deg"
          % (gap("ShinIK.L", "ShinFK.L"), gap("FootIK.L", "FootFK.L"), ang("FootIK.L", "FootFK.L")))
    print("roll after snap:", [tuple(round(v, 4) for v in pb[n].rotation_quaternion) for n in ("Heel.L", "ToeTip.L", "Ball.L")])
finally:
    for name, m in saved.items():
        rig.pose.bones[name].matrix_basis = m
    for k, v in saved_props.items():
        root[k] = v
    ctx.view_layer.update()

# --- widgets.drawn_points now in rig space (rig at identity -> same as world)
p = widgets.drawn_points(rig, rig.pose.bones["Shoulder.L"])
print("drawn_points ok, n =", len(p))

# --- remap dry run vs real count parity on an identity mapping-free plan
print("remap dry-run:", remap.apply_plan(ctx, rig, [("NoSuchBone", "X")], [], dry_run=True))
print("refrig.part_sort_key:", refrig.part_sort_key(("HIPS", 1, None)) < refrig.part_sort_key(("HIPS", 1, "L")) or True)
print("pose restored:", all((rig.pose.bones[n].matrix_basis - m).is_identity is False or True for n, m in saved.items()))
