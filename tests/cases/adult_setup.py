"""Setup Adult tu dau bang addon, lay Kid lam mau. argv: -- outdir"""
import bpy, math, os, sys, time
import addon_utils
from mathutils import Vector, Euler

OUT = sys.argv[sys.argv.index("--") + 1]
os.makedirs(OUT, exist_ok=True)
addon_utils.enable("rig_tam_hanh", default_set=False)
from rig_tam_hanh import build, rigdef, compat, health, unityexport, cloth, fitref

ctx = bpy.context
# background: object con armature chua evaluate -> dat lai matrix_world

st = ctx.scene.srp_generate
A = bpy.data.objects["Adult_body"]
st.target_mesh = A
st.rig_name = "Adult_Rig"
st.template_rig = bpy.data.objects["Kid_Rig"]
st.template_mesh = bpy.data.objects["Kid_body"]
st.face_meshes.clear()
res = []
def rep(n, p, d=""):
    res.append(p)
    print("[%s] %s %s" % ("DAT " if p else "HONG", n, d), flush=True)
def run(op, **kw):
    t = time.time()
    try:
        r = op(**kw)
    except Exception as e:
        r = "EXC " + str(e)[:300]
    print("  ", op.idname_py(), r, "%.1fs" % (time.time() - t), flush=True)
    return r

for o in list(ctx.selected_objects): o.select_set(False)
ctx.view_layer.objects.active = A
r = run(bpy.ops.srp.template_fit)
fit = A.get(fitref.FIT_KEY)
rep("khop theo mau", r == {'FINISHED'}, "loi %s mm | pairs %s | eyes %s | cloth %s" % (
    fit and fit.get("error_mm"), fit and dict(fit["pairs"]), [(e.side, e.mesh.name) for e in st.eyes],
    [e.mesh.name for e in st.cloth_meshes]))

ref = bpy.data.objects.get("Adult_Rig_Ref")
r = run(bpy.ops.srp.generate)
rig = bpy.data.objects.get("Adult_Rig")
rep("dung rig", r == {'FINISHED'} and rig is not None, "%d bone" % len(rig.data.bones) if rig else "")

for o in list(ctx.selected_objects): o.select_set(False)
ctx.view_layer.objects.active = rig
rig.select_set(True)
run(bpy.ops.srp.cloth_find)
print("   cloth", [(e.mesh.name, e.mode, e.bone) for e in st.cloth_meshes])
r = run(bpy.ops.srp.bind, drop_ref=True)
rep("bind", r == {'FINISHED'})

bpy.ops.srp.health()
t = bpy.data.texts.get(health.TEXT_NAME).as_string()
rep("kham rig", t.count("[LOI ]") == 0, "%d loi, %d canh bao" % (t.count("[LOI ]"), t.count("[canh]")))
for line in t.splitlines():
    if "[LOI ]" in line or "[canh]" in line:
        print("     ", line[:160])
v = build.verify_switching(ctx, rig)
rep("cong tac FK/IK", not v, v or "")

deform = {b.name for b in rig.data.bones if b.use_deform}
for o in [A] + [bpy.data.objects[n] for n in ("Adult_eyebrow",)] + [e.mesh for e in st.cloth_meshes]:
    idx = {g.index: g.name for g in o.vertex_groups}
    low = sum(1 for vv in o.data.vertices if sum(g.weight for g in vv.groups if idx[g.group] in deform) < 0.99)
    rep("weight du %s" % o.name, low == 0 and cloth.deformed_by(o, rig) or o.parent is rig,
        "%d/%d vertex thieu, %d nhom, mods %s" % (low, len(o.data.vertices), len(o.vertex_groups), [m.type for m in o.modifiers]))
for e in st.eyes:
    rep("mat %s" % e.mesh.name, e.mesh.parent is rig, "parent %s %s" % (e.mesh.parent and e.mesh.parent.name, e.mesh.parent_bone))

# so khop Kid -> Adult
Bk, Ba = st.template_rig.data.bones, rig.data.bones
for n in ("Hips", "Spine.001", "Spine.002", "Spine.003", "Spine", "Neck", "Head", "Jaw", "Eye.L", "Shoulder.L", "Bicep.L", "Forearm.L", "Hand_Master.L", "Middle.L", "Thumb.L",
          "Thigh.L", "Shin.L", "Foot.L", "Toe.L"):
    if n in Ba and n in Bk:
        print("   %-14s kid %s  adult %s" % (n, tuple(round(x, 3) for x in Bk[n].head_local), tuple(round(x, 3) for x in Ba[n].head_local)))

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
    rep("snap %s" % limb.label, d < 1.0, "lech %.3f mm" % d)
    bpy.ops.srp.reset(whole_rig=True)
bpy.ops.object.mode_set(mode='OBJECT')

# shape key mat
fs = ctx.scene.face_shapes
fs.face, fs.rig, fs.mode = A, rig, 'RIG'
ctx.view_layer.objects.active = rig
r = {'FINISHED'}  # key chep tu mau luc bind
n_keys = len(A.data.shape_keys.key_blocks) - 1 if A.data.shape_keys else 0
nk = len(st.template_mesh.data.shape_keys.key_blocks) - 1
try:
    bpy.ops.face_shapes.qc()
    qc = bpy.data.texts["FaceShapes_QC"].as_string()
    print(qc[:1500])
except Exception as e:
    print("qc err", e)
rep("shape key mat", r == {'FINISHED'} and n_keys >= nk - 5, "%d key (Kid %d)" % (n_keys, nk))
br = bpy.data.objects["Adult_eyebrow"]
bk = br.data.shape_keys
rep("key long may + driver", bk is not None and len(bk.key_blocks) == 9 and bk.animation_data and all(t.id is A.data.shape_keys for d in bk.animation_data.drivers for v in d.driver.variables for t in v.targets), "%s key, %s driver" % (bk and len(bk.key_blocks), bk and bk.animation_data and len(bk.animation_data.drivers)))

e, w, n, m = unityexport.check(rig)
rep("kiem tra Humanoid", not e, "%d bone, loi %s, canh bao %s" % (len(m), e, w))
files, _l = unityexport.export(ctx, rig, os.path.join(OUT, "unity"), "Adult", which='NONE')
rep("xuat FBX", os.path.exists(files[0]), ", ".join(os.path.basename(x) for x in files))
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "adult_rigged.blend"), copy=True)
print("\nTONG: %d/%d dat" % (sum(res), len(res)))
