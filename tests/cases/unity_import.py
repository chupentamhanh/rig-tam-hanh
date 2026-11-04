"""Import ngược các FBX đã xuất vào file trống, so với số đo tham chiếu."""
import bpy, json, os, sys
from mathutils import Vector
T = lambda p: Vector((-p[0], -p[1], p[2]))   # bản xuất xoay 180 quanh Z

OUT = sys.argv[sys.argv.index("--") + 1]
ref = json.load(open(os.path.join(OUT, "ref.json")))
mp = json.load(open(os.path.join(OUT, "Kid.humanoid.json"), encoding="utf-8"))

def load(path):
    bpy.ops.wm.read_homefile(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=path, use_anim=True, ignore_leaf_bones=False,
                             automatic_bone_orientation=False, anim_offset=0.0)
    arm = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
    meshes = [o for o in bpy.data.objects if o.type == 'MESH']
    return arm, meshes

arm, meshes = load(os.path.join(OUT, "Kid.fbx"))
B = arm.data.bones
print("base: armature", arm.name, "| bones", len(B), "| meshes", sorted(m.name for m in meshes))
print("human bones present:", all(p["bone"] in B for p in mp["human"]), len(mp["human"]))
print("bone names:", sorted(b.name for b in B)[:6], "...", "| Hips parent:", B["Hips"].parent.name if B["Hips"].parent else None,
      "| Spine parent:", B["Spine"].parent.name, "| Thigh.L parent:", B["Thigh.L"].parent.name)
err = max((arm.matrix_world @ B[n].head_local - T(p)).length for n, p in ref["rest"].items() if n in B)
print("rest pose error vs Blender: %.2e m" % err)
body = next(m for m in meshes if m.name == "body")
keys = sorted(k.name for k in body.data.shape_keys.key_blocks)
print("body verts", len(body.data.vertices), "(expect %d)" % ref["verts"],
      "| shape keys", len(keys), "same names:", keys == ref["body_keys"])
mx = max(sum(1 for g in v.groups if g.weight > 1e-4) for v in body.data.vertices)
print("max influences", mx, "| eyes skinned:",
      [(m.name, [g.name for g in m.vertex_groups]) for m in meshes if m.name.startswith("eyes")])
print("meshes:", sorted((m.name, len(m.data.vertices)) for m in meshes))
print("object scale/rot:", [(o.name, tuple(round(x, 3) for x in o.matrix_world.to_scale())) for o in [arm] + meshes])

for act in ("Wave", "Idle"):
    arm, meshes = load(os.path.join(OUT, "Kid@%s.fbx" % act))
    sc = bpy.context.scene
    a = arm.animation_data.action if arm.animation_data else None
    worst = 0.0
    for f, bones in ref["bones"][act].items():
        sc.frame_set(int(f))
        for n, p in bones.items():
            worst = max(worst, (arm.matrix_world @ arm.pose.bones[n].head - T(p)).length)
    line = "%s: action %s | frames %s | worst bone error %.2e m" % (
        act, a.name if a else None, tuple(a.frame_range) if a else None, worst)
    if act == "Wave":
        body = next(m for m in meshes if m.name == "body")
        k = body.data.shape_keys
        se = 0.0
        for f, v in ref["smile"].items():
            sc.frame_set(int(f))
            se = max(se, abs(k.key_blocks["MTH_SmileL"].value - v))
        line += " | smile curve %s, error %.3f" % (bool(k.animation_data and k.animation_data.action), se)
        sc.frame_set(12)
        dg = bpy.context.evaluated_depsgraph_get()
        mv = [body.matrix_world @ v.co for v in body.evaluated_get(dg).data.vertices][:len(ref["mesh12"])]
        dd = [((a - T(b)).length, tuple(round(x, 2) for x in T(b))) for a, b in zip(mv, ref["mesh12"])]
        big = sorted(dd, reverse=True)
        print("   lệch > 2 mm: %d vertex | z các vertex đó: %s" % (sum(1 for d, _p in dd if d > .002), sorted(set(p[2] for d, p in dd if d > .002))))
        ds = sorted(d for d, _p in dd)
        line += " | lưới body f12 lệch TB %.2f mm, p99 %.2f mm, max %.2f mm" % (sum(ds) / len(ds) * 1000, ds[int(len(ds) * .99)] * 1000, ds[-1] * 1000)
    print(line)
