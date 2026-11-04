"""Background test: ref_from_rig + ref_apply on a copy of the renamed Kid file."""
import bpy
import addon_utils
from mathutils import Vector

addon_utils.enable("rig_tam_hanh", default_set=False)
from rig_tam_hanh import build, generate, refrig, rigdef, refsync

ctx = bpy.context
rig = bpy.data.objects["Kid_Rig.001"]
body = bpy.data.objects["body"]
eyes = [bpy.data.objects["eyes_L"], bpy.data.objects["eyes_R"]]
for o in ctx.selected_objects:
    o.select_set(False)
ctx.view_layer.objects.active = rig
rig.select_set(True)
ctx.scene.srp_generate.target_mesh = body


def rest_verts(ob):
    rig.data.pose_position = 'REST'
    ctx.view_layer.update()
    ev = ob.evaluated_get(ctx.evaluated_depsgraph_get())
    co = [ob.matrix_world @ v.co for v in ev.data.vertices]
    rig.data.pose_position = 'POSE'
    return co


def bone_state():
    return {b.name: (b.head_local.copy(), b.tail_local.copy(),
                     b.matrix_local.to_3x3().col[2].copy()) for b in rig.data.bones}


def weights(ob):
    return sum(g.weight for v in ob.data.vertices for g in v.groups), len(ob.vertex_groups)


def drivers():
    n = len(rig.animation_data.drivers) if rig.animation_data else 0
    sk = body.data.shape_keys
    if sk and sk.animation_data:
        n += len(sk.animation_data.drivers)
    return n


def diff(a, b, eps=1e-6):
    return sorted(n for n in a if n in b and ((a[n][0] - b[n][0]).length > eps
                                              or (a[n][1] - b[n][1]).length > eps
                                              or (a[n][2] - b[n][2]).length > 1e-4))


def run(op, **kw):
    r = op(**kw)
    print("  ", op.idname_py(), kw or "", r)
    return r


body0 = rest_verts(body)
eyes0 = [e.matrix_world.copy() for e in eyes]
w0, d0, s0 = weights(body), drivers(), bone_state()

print("== 1. ref_from_rig ==")
run(bpy.ops.srp.ref_from_rig)
ref = refrig.find_ref(ctx)
parts = refrig.parts_in(ref)
print("ref", ref.name, len(ref.data.bones), "bones | missing core:", refrig.missing_core(ref))
print("parts:", sorted((k, len(v)) for k, v in parts.items()))

# How far is the ban-ve plan from Kid in absolute terms (why we use deltas).
now = generate.snapshot(ref)
plan, err = generate.build_plan(now, {k: {b: x.name for b, x in g.items()} for k, g in parts.items()}, roll=True)
inv = rig.matrix_world.inverted()
off = sorted((((inv @ h) - rig.data.bones[n].head_local).length * 1000, n)
             for n, h, *_r in plan if n in rig.data.bones)[-5:]
print("plan vs Kid abs head offsets (mm, worst 5):", [("%.2f" % d, n) for d, n in off])
print("plan bones not on Kid:", [r[0] for r in plan if r[0] not in rig.data.bones])

print("\n== 2. apply without edits (must be no-op) ==")
ctx.view_layer.objects.active = rig
run(bpy.ops.srp.ref_apply)
print("bones changed:", diff(s0, bone_state()))

print("\n== 3. edit ref: elbow L +2cm back, Eye.L +3mm, Jaw roll ==")
ctx.view_layer.objects.active = ref
for o in ctx.selected_objects:
    o.select_set(False)
ref.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
eb = ref.data.edit_bones
rinv = ref.matrix_world.inverted().to_3x3()
eb["Forearm.L"].head += rinv @ Vector((0, 0.02, 0))   # connected -> Bicep tail follows
eb["Eye.L"].head += rinv @ Vector((0.003, 0, 0))
eb["Eye.L"].tail += rinv @ Vector((0.003, 0, 0))
eb["Jaw"].roll += 0.2
bpy.ops.object.mode_set(mode='OBJECT')
run(bpy.ops.srp.ref_apply)
s1 = bone_state()
ch = diff(s0, s1)
print("rig bones changed (%d):" % len(ch), ch)
fa = rig.data.bones["Forearm.L"].head_local - s0["Forearm.L"][0]
print("Forearm.L head moved (rig local):", tuple(round(v, 4) for v in fa),
      "| FK/IK same:", [(n, round((rig.data.bones[n].head_local - s0[n][0]).length, 4)) for n in ("ForearmFK.L", "ForearmIK.L", "Bicep.L")])
print("Bicep.L tail == Forearm.L head:", (rig.data.bones["Bicep.L"].tail_local - rig.data.bones["Forearm.L"].head_local).length < 1e-6)
jz = rig.matrix_world.to_3x3() @ rig.data.bones["Jaw"].matrix_local.to_3x3().col[2]
rz = ref.matrix_world.to_3x3() @ ref.data.bones["Jaw"].matrix_local.to_3x3().col[2]
print("Jaw z matches ref:", round(jz.normalized().dot(rz.normalized()), 6))

body1 = rest_verts(body)
print("body rest verts max move (mm):", round(max((a - b).length for a, b in zip(body0, body1)) * 1000, 4))
print("eyes stayed:", [max(abs(x) for r in (e.matrix_world - m) for x in r) < 1e-6 for e, m in zip(eyes, eyes0)])
print("weights same:", weights(body) == w0, "| drivers same:", drivers() == d0)
print("FK/IK verify:", build.verify_switching(ctx, rig) or "OK")

print("\n== 4. apply again (no-op) ==")
run(bpy.ops.srp.ref_apply)
print("bones changed since step 3:", diff(s1, bone_state()))

print("\n== 5. undo-style revert: move elbow back ==")
ctx.view_layer.objects.active = ref
ref.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
ref.data.edit_bones["Forearm.L"].head -= rinv @ Vector((0, 0.02, 0))
bpy.ops.object.mode_set(mode='OBJECT')
run(bpy.ops.srp.ref_apply)
back = [n for n in ("Forearm.L", "ForearmFK.L", "ForearmIK.L", "Bicep.L", "BicepFK.L", "ElbowPole.L")
        if n in rig.data.bones and max((rig.data.bones[n].head_local - s0[n][0]).length,
                                      (rig.data.bones[n].tail_local - s0[n][1]).length) > 1e-5]
print("arm bones not back at original:", back)
