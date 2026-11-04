"""Background test: rebuild Kid with Rig Tẩm Hành defaults on a COPY of the file and compare."""
import sys
import traceback
import bpy
import addon_utils
from mathutils import Vector

addon_utils.enable("rig_tam_hanh", default_set=False)
from rig_tam_hanh import generate, rigdef

ctx = bpy.context
kid = bpy.data.objects["Kid_Rig.001"]
body = bpy.data.objects["body"]

RENAME = {"Eyebrow_001.R": "Eyebrow.R.001", "Eyebrow_002.R": "Eyebrow.R.002", "Eyebrow_003.R": "Eyebrow.R.003",
          "Eyebrow.L_5": "Eyebrow.L", "Eyebrow.L_5.001": "Eyebrow.L.001", "Eyebrow.L_5.002": "Eyebrow.L.002",
          "Eyebrow.L_5.003": "Eyebrow.L.003", "Nose_6": "Nose"}
for s in ("L", "R"):
    for lip in ("Upper", "Lower"):
        RENAME["Lip_%s_%s" % (lip, s)] = "Lip_%s.%s" % (lip, s)
        for d in (".001", ".002"):
            RENAME["Lip_%s_%s%s" % (lip, s, d)] = "Lip_%s.%s%s" % (lip, s, d)

# --- snapshot Kid
ref_bones = {}
for b in kid.data.bones:
    ref_bones[RENAME.get(b.name, b.name)] = (kid.matrix_world @ b.head_local, kid.matrix_world @ b.tail_local,
                                             RENAME.get(b.parent.name, b.parent.name) if b.parent else None, b.use_deform,
                                             (kid.matrix_world.to_3x3() @ b.matrix_local.to_3x3().col[2]).normalized())

# --- split teeth / tongue islands out of body into their own meshes
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

teeth = split(["Teeth_Upper", "Teeth_Lower"], "teeth")
tongue = split(["Tongue", "Tongue.001", "Tongue.002", "Tongue.003"], "tongue")
brow = bpy.data.objects["eyebrow"]
eyes = (bpy.data.objects["eyes_L"], bpy.data.objects["eyes_R"])

# --- strip the old rig
for o in (body, brow, teeth, tongue) + eyes:
    w = o.matrix_world.copy()
    o.parent = None
    o.matrix_world = w
    for m in [m for m in o.modifiers if m.type == 'ARMATURE']:
        o.modifiers.remove(m)
    o.vertex_groups.clear()
bpy.data.objects.remove(kid, do_unlink=True)
print("split: teeth %d verts, tongue %d verts, body %d verts" % (len(teeth.data.vertices), len(tongue.data.vertices), len(body.data.vertices)))

# --- Rig Tẩm Hành flow
st = ctx.scene.srp_generate
st.target_mesh = body
st.rig_name = "Kid_Gen"
st.eyes.clear()
for side, o in (("L", eyes[0]), ("R", eyes[1])):
    e = st.eyes.add(); e.side = side; e.mesh = o
st.face_meshes.clear()
for role, o in (("TEETH", teeth), ("TONGUE", tongue), ("BROW", brow)):
    e = st.face_meshes.add(); e.role = role; e.mesh = o

def run(op, **kw):
    r = op(**kw)
    print("  ", op.idname_py(), kw or "", r)

run(bpy.ops.srp.ref_start)
run(bpy.ops.srp.ref_add, kind='SPINE', socket="")
run(bpy.ops.srp.ref_add, kind='ARM', side='BOTH', socket="", with_hand=True)
run(bpy.ops.srp.ref_add, kind='LEG', side='BOTH', socket="")
run(bpy.ops.srp.ref_add, kind='FACE', socket="")
run(bpy.ops.srp.generate)
rig = bpy.data.objects.get("Kid_Gen")
ctx.view_layer.objects.active = rig
run(bpy.ops.srp.bind, drop_ref=True)

# --- compare against Kid
print("\n== BONE COMPARE (generated vs Kid, mm) ==")
gen = {b.name: b for b in rig.data.bones}
missing = sorted(set(ref_bones) - set(gen))
extra = sorted(set(gen) - set(ref_bones))
print("missing vs Kid:", missing)
print("extra vs Kid:", extra)
worst, parent_diff, deform_diff, roll_diff = [], [], [], []
for name, (h, t, par, deform, z) in ref_bones.items():
    b = gen.get(name)
    if b is None:
        continue
    gh, gt = rig.matrix_world @ b.head_local, rig.matrix_world @ b.tail_local
    worst.append((max((gh - h).length, (gt - t).length) * 1000, name))
    gp = b.parent.name if b.parent else None
    if gp != par:
        parent_diff.append((name, gp, par))
    if b.use_deform != deform:
        deform_diff.append((name, b.use_deform, deform))
    gz = (rig.matrix_world.to_3x3() @ b.matrix_local.to_3x3().col[2]).normalized()
    if gz.dot(z) < 0.99:
        roll_diff.append((name, round(gz.dot(z), 3)))
worst.sort(reverse=True)
print("max head/tail offset: %s" % [("%.2f" % d, n) for d, n in worst[:8]])
for n in ("Hand_Master.L", "Palm.L.004", "Thumb.L", "Thumb.L.002", "Index.L"):
    b = gen[n]
    h, t = ref_bones[n][0], ref_bones[n][1]
    print("  %s gen head %s tail %s | kid head %s tail %s" % (n, tuple(round(v, 4) for v in rig.matrix_world @ b.head_local),
          tuple(round(v, 4) for v in rig.matrix_world @ b.tail_local), tuple(round(v, 4) for v in h), tuple(round(v, 4) for v in t)))
print("parent differs:", parent_diff)
print("deform differs:", deform_diff)
print("roll differs (z dot < .99):", roll_diff)

print("\n== WEIGHTS ==")
def groups(o):
    idx = {g.index: g.name for g in o.vertex_groups}
    c = {}
    for v in o.data.vertices:
        for g in v.groups:
            if g.weight > 1e-3:
                c[idx[g.group]] = c.get(idx[g.group], 0) + 1
    return c
for o in (teeth, tongue, brow):
    print(o.name, "parent", o.parent and o.parent.name, "mods", [(m.type, m.object and m.object.name) for m in o.modifiers], groups(o))
bg = groups(body)
print("body groups:", len(bg), "teeth/tongue on body:", {k: v for k, v in bg.items() if k.startswith(("Teeth", "Tongue"))},
      "Eyebrow on body:", {k: v for k, v in bg.items() if k.startswith("Eyebrow")})
print("eyes parent:", [(e.name, e.parent and e.parent.name, e.parent_bone) for e in eyes])
print("limbs:", [l.name for l in rigdef.limbs_for(rig)])
from rig_tam_hanh import build
print("FK/IK verify:", build.verify_switching(ctx, rig) or "OK")
