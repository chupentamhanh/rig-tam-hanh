"""Tạo 2 action thử trên Kid, xuất, ghi số đo tham chiếu ra json."""
import bpy, json, math, os, sys
import addon_utils
addon_utils.enable("rig_tam_hanh", default_set=False)
from rig_tam_hanh import unityexport as UE

OUT = sys.argv[sys.argv.index("--") + 1]
COMBINE = sys.argv[-1] == 'combine'
ctx = bpy.context
kid = bpy.data.objects["Kid_Rig.001"]
body = bpy.data.objects["body"]
P = kid.pose.bones

def key(pb, frame, rot=None, loc=None):
    if rot is not None:
        pb.rotation_mode = 'XYZ'
        pb.rotation_euler = [math.radians(a) for a in rot]
        pb.keyframe_insert("rotation_euler", frame=frame)
    if loc is not None:
        pb.location = loc
        pb.keyframe_insert("location", frame=frame)

kid.animation_data_create()
for name, amp in (("Wave", 1.0), ("Idle", 0.3)):
    a = bpy.data.actions.new(name)
    UE.compat.assign_action(kid, a)
    kid.animation_data.action = a
    for f, t in ((1, 0), (12, 1), (24, 0)):
        key(P["BicepFK.L"], f, rot=(0, 0, 60 * t * amp))
        key(P["ForearmFK.L"], f, rot=(0, 0, 45 * t * amp))
        key(P["Hips"], f, loc=(0, 0, -0.05 * t * amp))
        key(P["Jaw"], f, rot=(15 * t * amp, 0, 0))
        key(P["LegIK.L"], f, loc=(0, 0.1 * t * amp, 0.08 * t * amp))
        key(P["Head"], f, rot=(0, 20 * t * amp, 0))
        key(P["Lip_Upper.L"], f, loc=(0, 0.01 * t * amp, 0))
    a.use_frame_range = True
    a.frame_start, a.frame_end = 1, 24
    a.use_cyclic = name == "Idle"
# shape key action đi kèm Wave
kb = body.data.shape_keys.key_blocks
for f, v in ((1, 0), (12, 1), (24, 0)):
    kb["MTH_SmileL"].value = v
    kb["MTH_SmileL"].keyframe_insert("value", frame=f)
body.data.shape_keys.animation_data.action.name = "Wave_Face"
kb["MTH_SmileL"].value = 0
UE.compat.assign_action(kid, bpy.data.actions["Wave"])

ctx.view_layer.objects.active = kid
bpy.ops.object.mode_set(mode='POSE')
before = dict(objs=sorted(o.name for o in bpy.data.objects), meshes=len(bpy.data.meshes),
              arms=len(bpy.data.armatures), acts=sorted(a.name for a in bpy.data.actions),
              colls=len(bpy.data.collections), keys=len(bpy.data.shape_keys))

e, w, n, m = UE.check(kid)
print("check errors", e, "| warns", w)
for line in n: print("  note:", line)
print("only_human bones:", len(UE.game_bones(kid, m, True)), "| map:", {h: m[h] for h in ("Hips", "Spine", "Chest", "UpperChest", "LeftHand", "Left Thumb Proximal", "Left Little Distal", "LeftToes", "Jaw", "LeftEye")})

files, lines = UE.export(ctx, kid, OUT, "Kid", combine=COMBINE)
print("files:", [os.path.basename(f) for f in files])
after = dict(objs=sorted(o.name for o in bpy.data.objects), meshes=len(bpy.data.meshes),
             arms=len(bpy.data.armatures), acts=sorted(a.name for a in bpy.data.actions),
             colls=len(bpy.data.collections), keys=len(bpy.data.shape_keys))
print("file unchanged:", before == after, "" if before == after else (before, after))
print("mode", ctx.object.mode, "| active", ctx.object.name, "| rig action", kid.animation_data.action.name)

# số đo tham chiếu: vị trí world của bone qua từng frame, và giá trị smile
ref = {"bones": {}, "smile": {}}
BONES = ("Hips", "Head", "Hand_Master.L", "Forearm.L", "Foot.L", "Toe.L", "Jaw", "Index.L.002")
for act in ("Wave", "Idle"):
    UE.compat.assign_action(kid, bpy.data.actions[act])
    body.data.shape_keys.animation_data.action = bpy.data.actions["Wave_Face"] if act == "Wave" else None
    ref["bones"][act] = {}
    for f in (1, 6, 12, 18, 24):
        ctx.scene.frame_set(f)
        ref["bones"][act][f] = {b: list(kid.matrix_world @ P[b].head) for b in BONES}
        if act == "Wave":
            ref["smile"][f] = kb["MTH_SmileL"].value
rest = {}
for pb in P: pass
ref["rest"] = {b.name: list(kid.matrix_world @ b.head_local) for b in kid.data.bones if b.use_deform}
ref["body_keys"] = sorted(k.name for k in kb)
UE.compat.assign_action(kid, bpy.data.actions["Wave"])
body.data.shape_keys.animation_data.action = bpy.data.actions["Wave_Face"]
ctx.scene.frame_set(12)
dg = ctx.evaluated_depsgraph_get()
ref["mesh12"] = [list(body.matrix_world @ v.co) for v in body.evaluated_get(dg).data.vertices]
ref["n_cloth"] = {o.name: len(o.data.vertices) for o in bpy.data.objects if o.name in ("hoodie", "short", "shoes", "hair")}
ref["verts"] = len(body.data.vertices) + len(bpy.data.objects["eyebrow"].data.vertices)
with open(os.path.join(OUT, "ref.json"), "w") as f:
    json.dump(ref, f)
