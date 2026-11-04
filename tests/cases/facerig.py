"""Build face shape keys from Kid's Rig Tẩm Hành face rig and measure them."""
import bpy
import addon_utils
from mathutils import Vector, Matrix

addon_utils.enable("rig_tam_hanh", default_set=False)
from rig_tam_hanh import face as FC, facerig

ctx = bpy.context
body = bpy.data.objects["body"]
brow = bpy.data.objects["eyebrow"]
kid = bpy.data.objects["Kid_Rig.001"]
st = ctx.scene.face_shapes
st.face, st.rig, st.mode = body, kid, 'AUTO'

# a hand-made key that must survive
body.shape_key_add(name="Basis", from_mix=False)
mine = body.shape_key_add(name="MyHandKey", from_mix=False)
mine.data[0].co.z += 0.01
mine.value = 0.7
# a posed arm that must not leak into keys and must come back
kid.pose.bones["Forearm.L"].rotation_quaternion = (0.9, 0.3, 0, 0)
before = {pb.name: pb.matrix_basis.copy() for pb in kid.pose.bones}

print("has_face_rig", facerig.has_face_rig(kid), "find_rig", FC.find_rig(ctx, body).name)
r = bpy.ops.face_shapes.build()
print("build:", r)
after = {pb.name: pb.matrix_basis.copy() for pb in kid.pose.bones}
print("pose restored:", all((before[n] - after[n]).to_3x3().is_identity or
      max(abs(x) for row in (before[n] - after[n]) for x in row) < 1e-6 for n in before))
print("hand key kept:", "MyHandKey" in body.data.shape_keys.key_blocks,
      round(body.data.shape_keys.key_blocks["MyHandKey"].value, 2))
print("jaw_max", st.jaw_max)

kb = body.data.shape_keys.key_blocks
basis = kb["Basis"]
names = [k.name for k in kb if k.name not in ("Basis", "MyHandKey")]
print("keys on body (%d):" % len(names), names)
bk = brow.data.shape_keys
print("keys on eyebrow:", len(bk.key_blocks) - 1 if bk else 0,
      "drivers:", len(bk.animation_data.drivers) if bk and bk.animation_data else 0)

neck_z = (kid.matrix_world @ kid.data.bones["Head"].head_local).z - 0.10
M3 = body.matrix_world.to_3x3()
rows, bad = [], []
for n in names:
    k = kb[n]
    d = [(M3 @ (k.data[i].co - basis.data[i].co)).length for i in range(len(basis.data))]
    moved = [i for i, x in enumerate(d) if x > 2e-5]
    lowest = min(((body.matrix_world @ basis.data[i].co).z for i in moved), default=9)
    rows.append((n, max(d), len(moved), lowest))
    if lowest < neck_z:
        bad.append(n)
for n, mx, cnt, low in rows:
    print("  %-15s max %.4f  verts %4d  minz %.3f" % (n, mx, cnt, low))
print("below head:", bad)

# symmetry
for n in names:
    if n.endswith("L") and n[:-1] + "R" in names:
        a = next(r for r in rows if r[0] == n)
        b = next(r for r in rows if r[0] == n[:-1] + "R")
        if abs(a[1] - b[1]) > 1e-3 or a[2] != b[2]:
            print("  ASYM", n, a[1:3], b[1:3])

# eye penetration + exposure for blink
eye = bpy.data.objects["eyes_L"]
pts = [eye.matrix_world @ v.co for v in eye.data.vertices]
c = sum(pts, Vector()) / len(pts)
rad = max((p - c).length for p in pts)
def inside(key):
    for k in kb:
        k.value = 0.0
    if key:
        kb[key].value = 1.0
    ctx.view_layer.update()
    dg = ctx.evaluated_depsgraph_get()
    me = body.evaluated_get(dg).data
    return sum(1 for v in me.vertices if (body.matrix_world @ v.co - c).length < rad * 0.98)
for key in (None, "EYE_BlinkL", "EYE_SquintL", "EYE_WideL"):
    n_in = inside(key)
    print("eye L | %-12s skin verts inside eyeball: %d | exposure %.2f%%" % (key, n_in, FC.eyeball_exposure(eye, n=30)))

# corner stretch at JAW_Open and VIS_AA
F = facerig.Frame(kid)
for k in kb:
    k.value = 0.0
ctx.view_layer.update()
rest = facerig.eval_co(body)
edges, ln = facerig.corner_edges(F, kid, body, rest)
for key in ("JAW_Open", "VIS_AA", "VIS_OH", "MTH_SmileL"):
    for k in kb:
        k.value = 0.0
    kb[key].value = 1.0
    ctx.view_layer.update()
    print("stretch %-10s %.2f" % (key, facerig.stretch(body, edges, ln)))
for k in kb:
    k.value = 0.0

# rebuild is idempotent
r2 = bpy.ops.face_shapes.build()
print("rebuild:", r2, len(body.data.shape_keys.key_blocks), "keys (expect %d)" % (len(names) + 2))
print("qc:", bpy.ops.face_shapes.qc())
print(bpy.data.texts["FaceShapes_QC"].as_string().split("CẢNH BÁO")[-1][:600])
print("expr Lè lưỡi:", bpy.ops.face_shapes.test_expr(expr="Lè lưỡi"),
      round(kb["TNG_Out"].value, 2), round(kb["JAW_Open"].value, 2))
for k in kb:
    k.value = 0.0
bpy.ops.wm.save_as_mainfile(filepath=bpy.path.abspath("//kid_facekeys.blend"), copy=True)
print("clear:", bpy.ops.face_shapes.clear(),
      "body left:", [k.name for k in body.data.shape_keys.key_blocks],
      "eyebrow left:", len(brow.data.shape_keys.key_blocks) if brow.data.shape_keys else 0,
      "eyebrow drivers:", len(brow.data.shape_keys.animation_data.drivers)
      if brow.data.shape_keys and brow.data.shape_keys.animation_data else 0)
