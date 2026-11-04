"""Dựng một nhân vật MỚI có tỉ lệ khác bằng đúng quy trình addon, rồi kiểm tra.

Nhân vật mới = Kid biến dạng liên tục (chân/thân/đầu/tay co giãn khác nhau).
Cùng một phép biến dạng áp cho lưới VÀ bộ xương ref, nên ref khớp lưới như
người dùng kéo tay cho khớp. Rig cũ bị gỡ hẳn, rig mới dựng từ ref.

argv: -- <tên> <leg> <torso> <head> <wleg> <wtorso> <arm> <outdir>
"""
import bpy, math, os, sys
import addon_utils
from mathutils import Vector, Matrix, Euler

a = sys.argv[sys.argv.index("--") + 1:]
NAME = a[0]
LEG, TORSO, HEAD, WLEG, WTORSO, ARM = (float(x) for x in a[1:7])
OUT = a[7]
os.makedirs(OUT, exist_ok=True)

addon_utils.enable("rig_tam_hanh", default_set=False)
from rig_tam_hanh import build, rigdef, compat, health, unityexport, refrig, facerig

ctx = bpy.context
kid = bpy.data.objects["Kid_Rig.001"]
body = bpy.data.objects["body"]
brow = bpy.data.objects["eyebrow"]
eyes = (bpy.data.objects["eyes_L"], bpy.data.objects["eyes_R"])
ZH, ZN = 0.631, 1.09            # hông, gốc cổ của Kid


def sstep(a, b, x):
    t = min(1.0, max(0.0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


def zmap(z):
    if z < ZH:
        return z * LEG
    if z < ZN:
        return ZH * LEG + (z - ZH) * TORSO
    return ZH * LEG + (ZN - ZH) * TORSO + (z - ZN) * HEAD


def f(p):
    x, y, z = p
    w1 = sstep(ZH - 0.03, ZH + 0.03, z)      # chân -> thân
    w2 = sstep(ZN - 0.03, ZN + 0.03, z)      # thân -> đầu
    sxy = WLEG + (WTORSO - WLEG) * w1
    sxy = sxy + (HEAD - sxy) * w2
    ax = abs(x)
    warm = sstep(0.14, 0.18, ax) * sstep(0.80, 0.86, z) * (1 - sstep(1.03, 1.07, z))
    x2 = x * sxy + math.copysign(1, x) * warm * max(0.0, ax - 0.14) * (ARM - sxy)
    return Vector((x2, y * sxy, zmap(z)))


def jac(p, v, eps=1e-3):
    return (f(p + v * eps) - f(p)).normalized()


def run(op, **kw):
    try:
        r = op(**kw)
    except Exception as e:
        r = "EXC " + str(e)[:150]
    print("  ", op.idname_py(), r)
    return r


# ---------------------------------------------------------- 1. ref từ Kid
for o in ctx.selected_objects:
    o.select_set(False)
ctx.view_layer.objects.active = kid
kid.select_set(True)
ctx.scene.srp_generate.target_mesh = body
run(bpy.ops.srp.ref_from_rig)
ref = refrig.find_ref(ctx)

# ---------------------------------------------------------- 2. gỡ rig cũ, tách răng/lưỡi
def split(names, new_name):
    idx = [body.vertex_groups[n].index for n in names]
    for o in ctx.selected_objects:
        o.select_set(False)
    body.select_set(True)
    ctx.view_layer.objects.active = body
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='DESELECT')
    bpy.ops.object.mode_set(mode='OBJECT')
    for v in body.data.vertices:
        v.select = any(g.group in idx and g.weight > 0.5 for g in v.groups)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_linked()
    bpy.ops.mesh.separate(type='SELECTED')
    bpy.ops.object.mode_set(mode='OBJECT')
    new = [o for o in ctx.selected_objects if o is not body][0]
    new.name = new_name
    return new

for o in (body, brow):
    if o.data.shape_keys:
        o.shape_key_clear()
teeth = split(["Teeth_Upper", "Teeth_Lower"], "teeth")
tongue = split(["Tongue", "Tongue.001", "Tongue.002", "Tongue.003"], "tongue")
CLOTH = tuple(bpy.data.objects[n] for n in ("hoodie", "short", "shoes"))
HAIR = bpy.data.objects["hair"]
meshes = (body, brow, teeth, tongue) + CLOTH + (HAIR,)
for o in meshes + eyes:
    w = o.matrix_world.copy()
    o.parent = None
    o.matrix_world = w
    for m in [m for m in o.modifiers if m.type == 'ARMATURE']:
        o.modifiers.remove(m)
    o.vertex_groups.clear()
bpy.data.objects.remove(kid, do_unlink=True)
for a_ in list(bpy.data.actions):
    bpy.data.actions.remove(a_)

# ---------------------------------------------------------- 3. biến dạng lưới + ref
for o in meshes:
    mw, inv = o.matrix_world, o.matrix_world.inverted()
    for v in o.data.vertices:
        v.co = inv @ f(mw @ v.co)
    o.data.update()
for e in eyes:
    pts = [e.matrix_world @ v.co for v in e.data.vertices]
    c = sum(pts, Vector()) / len(pts)
    nc = f(c)
    e.matrix_world = (Matrix.Translation(nc) @ Matrix.Scale(HEAD, 4)
                      @ Matrix.Translation(-c) @ e.matrix_world)

for o in ctx.selected_objects:
    o.select_set(False)
ref.hide_set(False)
ref.hide_viewport = False
ctx.view_layer.objects.active = ref
ref.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
R, Ri = ref.matrix_world, ref.matrix_world.inverted()
R3, Ri3 = R.to_3x3(), Ri.to_3x3()
plan = []
for eb in ref.data.edit_bones:
    h, t = R @ eb.head, R @ eb.tail
    z = (R3 @ eb.z_axis).normalized()
    plan.append((eb.name, f(h), f(t), jac(h, z)))
for name, h, t, z in plan:
    eb = ref.data.edit_bones[name]
    eb.head, eb.tail = Ri @ h, Ri @ t
    eb.align_roll(Ri3 @ z)
bpy.ops.object.mode_set(mode='OBJECT')
top = max((o.matrix_world @ Vector(b)).z for o in (body,) for b in o.bound_box)
print("chiều cao mới %.3f m (Kid ~1.37 m)" % top)

# ---------------------------------------------------------- 4. dựng + bind
st = ctx.scene.srp_generate
st.target_mesh = body
st.rig_name = NAME + "_Rig"
st.eyes.clear()
for side, o in (("L", eyes[0]), ("R", eyes[1])):
    en = st.eyes.add(); en.side = side; en.mesh = o
st.face_meshes.clear()
for role, o in (("TEETH", teeth), ("TONGUE", tongue), ("BROW", brow)):
    en = st.face_meshes.add(); en.role = role; en.mesh = o
for o in ctx.selected_objects:
    o.select_set(False)
ctx.view_layer.objects.active = ref
r_gen = run(bpy.ops.srp.generate)
rig = bpy.data.objects.get(NAME + "_Rig")
ctx.view_layer.objects.active = rig
r_bind = run(bpy.ops.srp.bind, drop_ref=True)

# Quần áo / tóc: addon chưa có chỗ bind -> bind tay như người dùng sẽ làm
bpy.ops.object.mode_set(mode='OBJECT')
for c in CLOTH:
    for o in ctx.selected_objects:
        o.select_set(False)
    c.select_set(True); rig.select_set(True)
    ctx.view_layer.objects.active = rig
    bpy.ops.object.parent_set(type='ARMATURE_AUTO')
mw = HAIR.matrix_world.copy()
HAIR.parent, HAIR.parent_type, HAIR.parent_bone = rig, 'BONE', "Head"
HAIR.matrix_world = mw
ctx.view_layer.objects.active = rig

res = []
def rep(n, p, d=""):
    res.append(p)
    print("[%s] %s %s" % ("ĐẠT" if p else "HỎNG", n, d))

rep("dựng rig + bind", r_gen == {'FINISHED'} and r_bind == {'FINISHED'} and rig is not None,
    "%d bone, %d chi" % (len(rig.data.bones), len(rigdef.limbs_for(rig))) if rig else "")

# ---------------------------------------------------------- 5. kiểm tra
bpy.ops.srp.health()
t = bpy.data.texts.get(health.TEXT_NAME).as_string()
rep("khám rig", t.count("[LOI ]") == 0, "%d lỗi, %d cảnh báo" % (t.count("[LOI ]"), t.count("[canh]")))
v = build.verify_switching(ctx, rig)
rep("công tắc FK/IK", not v, v or "")

deform = {b.name for b in rig.data.bones if b.use_deform}
idx = {g.index: g.name for g in body.vertex_groups}
bare = sum(1 for vv in body.data.vertices if not any(idx[g.group] in deform and g.weight > 1e-4 for g in vv.groups))
rep("mọi vertex có trọng số", bare == 0, "%d/%d vertex trống" % (bare, len(body.data.vertices)))

# độ khớp xương: đầu xương deform so với vị trí đã biến dạng
B = rig.data.bones
worst = max(((rig.matrix_world @ B[n].head_local) - h).length for n, h, _t, _z in plan if n in B)
rep("xương khớp ref đã biến dạng", worst < 1e-3, "lệch tối đa %.3f mm" % (worst * 1000))

# snap 4 chi
bpy.ops.object.mode_set(mode='POSE')
P = rig.pose.bones
prop = P[rigdef.PROP_BONE]
def W(n):
    ctx.view_layer.update()
    return (rig.matrix_world @ P[n].matrix).copy()
for limb in rigdef.limbs_for(rig):
    end = limb.deform[-1]
    prop[limb.prop] = rigdef.FK_VALUE; compat.refresh(ctx, rig)
    for n in limb.fk[:2]:
        P[n].rotation_mode = 'XYZ'
        P[n].rotation_euler = Euler((math.radians(25), math.radians(10), math.radians(35)))
    b0 = W(end)
    bpy.ops.srp.snap(direction='TO_IK', scope='ONE', limb_name=limb.name)
    prop[limb.prop] = rigdef.IK_VALUE; compat.refresh(ctx, rig)
    d = (W(end).translation - b0.translation).length * 1000
    rep("snap %s" % limb.label, d < 1.0, "lệch %.3f mm" % d)
    bpy.ops.srp.reset(whole_rig=True)

# biến dạng khi pose: giơ tay 70°, không vertex nào văng xa
P["BicepFK.L"].rotation_mode = 'XYZ'
prop[rigdef.limbs_for(rig)[0].prop] = rigdef.FK_VALUE; compat.refresh(ctx, rig)
rest = [body.matrix_world @ vv.co for vv in body.evaluated_get(ctx.evaluated_depsgraph_get()).data.vertices]
P["BicepFK.L"].rotation_euler = Euler((0, 0, math.radians(70)))
ctx.view_layer.update()
posed = [body.matrix_world @ vv.co for vv in body.evaluated_get(ctx.evaluated_depsgraph_get()).data.vertices]
arm_len = (B["Hand_Master.L"].tail_local - B["Bicep.L"].head_local).length
mx = max((p - q).length for p, q in zip(posed, rest))
rep("pose tay 70° không văng lưới", mx < arm_len * 1.5, "dời tối đa %.3f m, tay dài %.3f m" % (mx, arm_len))
bpy.ops.srp.reset(whole_rig=True)
bpy.ops.object.mode_set(mode='OBJECT')

# shape key mặt
fs = ctx.scene.face_shapes
fs.face, fs.rig, fs.mode = body, rig, 'AUTO'
r = run(bpy.ops.face_shapes.build)
n_keys = len(body.data.shape_keys.key_blocks) - 1 if body.data.shape_keys else 0
bpy.ops.face_shapes.qc()
qc = bpy.data.texts["FaceShapes_QC"].as_string().split("CẢNH BÁO")[-1].strip()
rep("shape key mặt", r == {'FINISHED'} and n_keys > 40, "%d key | QC: %s" % (n_keys, qc[:150].replace("\n", " | ")))

# Unity
e, w, n, m = unityexport.check(rig)
rep("kiểm tra Humanoid", not e, "%d bone, lỗi %s, cảnh báo %s" % (len(m), e, w))
files, _l = unityexport.export(ctx, rig, os.path.join(OUT, NAME), NAME, which='NONE')
rep("xuất FBX", os.path.exists(files[0]), ", ".join(os.path.basename(x) for x in files))

# ảnh chụp trước mặt (workbench) để mắt người xem
sc = ctx.scene
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
sc.collection.objects.link(cam)
cam.data.type = 'ORTHO'
cam.data.ortho_scale = max(top, 1.0) * 1.15
cam.location = (0, -6, top / 2)
cam.rotation_euler = (math.radians(90), 0, 0)
sc.camera = cam
sc.render.engine = 'BLENDER_WORKBENCH'
sc.render.resolution_x, sc.render.resolution_y = 520, 640
sc.render.filepath = os.path.join(OUT, NAME + "_front.png")
rig.hide_render = True
try:
    bpy.ops.render.render(write_still=True)
except Exception as ex:
    print("render lỗi", ex)
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, NAME + ".blend"), copy=True)
print("\nTỔNG %s: %d/%d đạt | cao %.2f m" % (NAME, sum(res), len(res), top))
