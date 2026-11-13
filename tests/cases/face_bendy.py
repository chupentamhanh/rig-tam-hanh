"""Face rig bằng bendy bone trên Adult: dựng, điều khiển, gỡ, xuất Unity. argv: -- outdir
Fixture adult_final.blend (Adult đã rig + skin)."""
import bpy, sys, os, math
import addon_utils
from mathutils import Matrix, Vector

OUT = sys.argv[sys.argv.index("--") + 1]
addon_utils.enable("rig_tam_hanh", default_set=False)
from rig_tam_hanh import facebendy as FB, unityexport as UE, compat

ctx = bpy.context
arm = bpy.data.objects["Adult_Rig"]
body = bpy.data.objects["Adult_body"]
results = []


def rep(name, ok, detail=""):
    results.append(ok)
    print("[%s] %s %s" % ("ĐẠT" if ok else "HỎNG", name, detail))


MM = 1000.0 * max(arm.matrix_world.to_scale())
weights0 = {v.index: tuple((g.group, round(g.weight, 6)) for g in v.groups) for v in body.data.vertices}
rest0 = {b.name: b.matrix_local.copy() for b in arm.data.bones}
if body.data.shape_keys:
    for kb in body.data.shape_keys.key_blocks:
        kb.value = 0.0

nc, nd, err = FB.build(ctx, arm)
rep("dựng xong", nc > 0 and nd > 0, "%d control, %d xương mặt" % (nc, nd))
rep("tư thế nghỉ không đổi", err < 0.01, "%.4f mm" % err)
rep("weight không đổi", {v.index: tuple((g.group, round(g.weight, 6)) for g in v.groups)
                          for v in body.data.vertices} == weights0)
P = arm.pose.bones
for pb in P:
    pb.matrix_basis = Matrix()
ctx.view_layer.update()


def head(n):
    return (arm.matrix_world @ P[n].head).copy()


B = arm.data.bones
lipsL = [n for n in B.keys() if n.startswith("Lip_Upper.L")]
near = min(lipsL, key=lambda n: (B[n].head_local - B["Lip_Upper_Mid"].head_local).length)
far = max(lipsL, key=lambda n: (B[n].head_local - B["Lip_Upper_Mid"].head_local).length)
r0 = {n: head(n) for n in ("Lip_Upper_Mid", near, far, "Eyebrow.L", "Lip_Lower_Mid")}
up = Vector((0, 0, 0.003 / max(arm.matrix_world.to_scale())))
P[FB.CTRL + "Lip_Upper_Mid"].location = (P[FB.CTRL + "Lip_Upper_Mid"].bone.matrix_local.to_3x3().inverted() @ up)
ctx.view_layer.update()
d = {n: (head(n) - r0[n]).length * MM for n in r0}
rep("kéo giữa môi trên 3 mm -> xương giữa môi lên ~3 mm", abs(d["Lip_Upper_Mid"] - 3.0) < 0.3, "%.2f mm" % d["Lip_Upper_Mid"])
rep("xương cạnh giữa theo đường cong, xa hơn thì ít hơn", d["Lip_Upper_Mid"] > d[near] > d[far] >= 0 and d[near] > 0.3,
    "%s %.2f mm, %s %.2f mm" % (near, d[near], far, d[far]))
rep("lông mày và môi dưới đứng yên", d["Eyebrow.L"] < 1e-3 and d["Lip_Lower_Mid"] < 1e-3)
for pb in P:
    pb.matrix_basis = Matrix()
P["Jaw"].rotation_mode = 'XYZ'
P["Jaw"].rotation_euler = (math.radians(15), 0, 0)
ctx.view_layer.update()
jl, jc = (head("Lip_Lower_Mid") - r0["Lip_Lower_Mid"]).length * MM, (head(FB.CTRL + "Lip_Corner.L") - (arm.matrix_world @ arm.data.bones[FB.CTRL + "Lip_Corner.L"].head_local)).length * MM
rep("mở hàm: môi dưới theo hàm, khoé miệng theo một phần", jl > 1.0 and 0.1 * jl < jc < 0.9 * jl, "môi dưới %.2f mm, khoé %.2f mm" % (jl, jc))

# ---- nhắm mắt: mí trên xuống hết khe, mí dưới lên 1/4 -- nhãn cầu không được lòi qua da
def lid_poke():
    """Số vertex da (trước mắt) lọt vào trong nhãn cầu sâu hơn 1 mm mà lúc nghỉ không lọt."""
    eye = FB.eyeball_for(arm, "L")
    C = arm.matrix_world @ FB.eye_center(arm, "L")
    R = max((eye.matrix_world @ v.co - C).length for v in eye.data.vertices)
    fwd = (arm.matrix_world.to_3x3() @ (B["Eyelid_Upper.L"].head_local - FB.eye_center(arm, "L"))).normalized()

    def pos():
        ctx.view_layer.update()
        ev = body.evaluated_get(ctx.evaluated_depsgraph_get())
        me = ev.to_mesh()
        out = [body.matrix_world @ v.co for v in me.vertices]
        ev.to_mesh_clear()
        return out
    saved = {pb.name: pb.matrix_basis.copy() for pb in P}
    for pb in P:
        pb.matrix_basis = Matrix()
    p0 = pos()
    for pb in P:
        pb.matrix_basis = saved[pb.name]
    p1 = pos()
    n = 0
    for a, b in zip(p0, p1):
        if (b - C).length < R - 0.001 / MM * 1000 and (a - C).length >= R - 0.001 / MM * 1000 and (b - C).dot(fwd) > 0:
            n += 1
    return n


for pb in P:
    pb.matrix_basis = Matrix()
g = B[FB.CTRL + "Lid_Lower.L"].head_local - B[FB.CTRL + "Lid_Upper.L"].head_local
for cn, f in (("Lid_Upper.L", 1.0), ("Lid_Lower.L", -0.25)):
    pb = P[FB.CTRL + cn]
    pb.location = pb.bone.matrix_local.to_3x3().inverted() @ (g * f)
ctx.view_layer.update()
closed = (head("Eyelid_Upper.L") - arm.matrix_world @ B["Eyelid_Upper.L"].head_local).length * MM
poke = lid_poke()
rep("nhắm mắt: mí trên xuống, nhãn cầu không lòi qua da", closed > 0.5 * g.length * MM and poke <= 2,
    "mí đi %.1f mm, %d vertex lọt vào mắt" % (closed, poke))
for pb in P:
    pb.matrix_basis = Matrix()
ctx.view_layer.update()

# ---- xuất Unity với xương mặt
act = bpy.data.actions.new("Smile")
slot = act.slots.new('OBJECT', arm.name)
bag = compat.action_channelbag(act, slot, create=True)
ctl = FB.CTRL + "Lip_Upper_Mid"
loc = P[ctl].bone.matrix_local.to_3x3().inverted() @ up
for i in range(3):
    fc = bag.fcurves.new('pose.bones["%s"].location' % ctl, index=i)
    fc.keyframe_points.insert(1, 0.0); fc.keyframe_points.insert(10, loc[i])
anim = arm.animation_data or arm.animation_data_create()
anim.action, anim.action_slot = act, slot
folder = os.path.join(OUT, "unity")
files, lines = UE.export(ctx, arm, folder, "Adult", which='ALL', combine=False, only_human=False)
anim.action = None
rep("xuất FBX chạy xong", any(f.endswith("Adult@Smile.fbx") for f in files))
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
bpy.ops.import_scene.fbx(filepath=os.path.join(folder, "Adult@Smile.fbx"), use_anim=True)
ga = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
has = "Lip_Upper_Mid" in ga.data.bones and ga.data.bones["Lip_Upper_Mid"].parent is not None
rep("FBX có xương mặt (con của Head)", has and ga.data.bones["Lip_Upper_Mid"].parent.name == "Head")
sc = ctx.scene
sc.frame_set(1); p1 = (ga.matrix_world @ ga.pose.bones["Lip_Upper_Mid"].head).copy()
sc.frame_set(10); p10 = (ga.matrix_world @ ga.pose.bones["Lip_Upper_Mid"].head).copy()
moved = (p10 - p1).length * 1000.0
rep("animation trong FBX: xương giữa môi lên ~3 mm", abs(moved - 3.0) < 0.5, "%.2f mm" % moved)
rep("FBX không có bendy / control mặt", not any(b.name.startswith(FB.PREFIXES) for b in ga.data.bones))
print("TỔNG %d/%d" % (sum(results), len(results)))
