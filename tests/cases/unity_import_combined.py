"""Import ngược FBX GỘP, so từng take với số đo tham chiếu."""
import bpy, json, os, sys
from mathutils import Vector
T = lambda p: Vector((-p[0], -p[1], p[2]))
OUT = sys.argv[sys.argv.index("--") + 1]
ref = json.load(open(os.path.join(OUT, "ref.json")))
mp = json.load(open(os.path.join(OUT, "Kid.humanoid.json"), encoding="utf-8"))
print("json combined", mp["combined"], "| clips", [(c["name"], c["start"], c["first"], c["last"], c["loop"]) for c in mp["clips"]])
print("files", sorted(os.listdir(OUT)))
bpy.ops.wm.read_homefile(use_empty=True)
bpy.ops.import_scene.fbx(filepath=os.path.join(OUT, "Kid.fbx"), use_anim=True, anim_offset=0.0)
arm = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
body = next(o for o in bpy.data.objects if o.name == "body")
B = arm.data.bones
print("actions", sorted((a.name, tuple(a.frame_range)) for a in bpy.data.actions))
err = max((arm.matrix_world @ B[n].head_local - T(p)).length for n, p in ref["rest"].items() if n in B)
print("rest pose error %.2e" % err, "| bones", len(B), "| shape keys", len(body.data.shape_keys.key_blocks))
sc = bpy.context.scene
for c in mp["clips"]:
    act = next(a for a in bpy.data.actions if a.name == "Kid|" + c["name"])
    arm.animation_data.action = act
    if arm.animation_data.action_slot is None and len(act.slots):
        arm.animation_data.action_slot = act.slots[0]
    kact = next((a for a in bpy.data.actions if a.name == "Key|" + c["name"]), None)
    k = body.data.shape_keys
    if kact is not None:
        k.animation_data_create(); k.animation_data.action = kact
        if k.animation_data.action_slot is None and len(kact.slots):
            k.animation_data.action_slot = kact.slots[0]
    worst, se = 0.0, 0.0
    for f, bones in ref["bones"][c["name"]].items():
        sc.frame_set(int(f) - c["first"])
        for n, p in bones.items():
            worst = max(worst, (arm.matrix_world @ arm.pose.bones[n].head - T(p)).length)
        if c["name"] == "Wave":
            se = max(se, abs(k.key_blocks["MTH_SmileL"].value - ref["smile"][f]))
    print("%s: %s %s | worst bone error %.2e m | smile err %.3f | key action %s" % (
        c["name"], act.name, tuple(act.frame_range), worst, se, kact.name if kact else None))
