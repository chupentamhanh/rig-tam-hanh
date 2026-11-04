import bpy
import addon_utils

addon_utils.enable("rig_tam_hanh", default_set=False)
from rig_tam_hanh import build, refrig

ctx = bpy.context
rig = bpy.data.objects["Kid_Rig.001"]
ctx.view_layer.objects.active = rig
rig.select_set(True)
ctx.scene.srp_generate.target_mesh = bpy.data.objects["body"]
n0 = len(rig.data.bones)
print(bpy.ops.srp.ref_from_rig())
print(bpy.ops.srp.ref_add(kind='CHAIN', socket="Head", chain_name="Antenna", chain_count=3))
ctx.view_layer.objects.active = rig
print(bpy.ops.srp.ref_apply())
new = [b for b in rig.data.bones if b.name.startswith("Antenna")]
print("bones", n0, "->", len(rig.data.bones))
for b in new:
    pb = rig.pose.bones[b.name]
    print(b.name, "parent", b.parent and b.parent.name, "deform", b.use_deform,
          "colls", [c.name for c in b.collections], "widget", pb.custom_shape and pb.custom_shape.name)
print("FK/IK:", build.verify_switching(ctx, rig) or "OK")
# Rebind path should refuse nothing and keep ref
print(bpy.ops.srp.ref_apply(rebind=True))
print("ref still there:", refrig.find_ref(ctx) is not None,
      "| body has Antenna groups:", [g.name for g in bpy.data.objects["body"].vertex_groups if g.name.startswith("Antenna")])
