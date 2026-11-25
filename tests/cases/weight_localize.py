"""Khu trú weight: mesh tạm có thân, mắt rời sát gốc râu, râu rời. argv: -- outdir"""
import bpy, sys, os
import addon_utils
from mathutils import Vector

OUT = sys.argv[sys.argv.index("--") + 1]
os.makedirs(OUT, exist_ok=True)
addon_utils.enable("rig_tam_hanh", default_set=False)
from rig_tam_hanh import markers as MK, refrig, weightfence as F, cloth

ctx = bpy.context
sc = ctx.scene
results = []


def rep(name, ok, detail=""):
    results.append(bool(ok))
    print("[%s] %s %s" % ("ĐẠT" if ok else "HỎNG", name, detail))


bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0.9))
guide = ctx.object
guide.scale = (0.5, 0.3, 1.8)
bpy.ops.object.transform_apply(scale=True)
sc.srp_generate.target_mesh = guide
sc.srp_generate.rig_name = "Loc_Rig"
sc.srp_ref.fingers = 3
bpy.ops.srp.marker_start()
ref = refrig.find_ref(ctx)
E = MK.end_map(ref)
hip = E[("Hips", 'H')].location.copy()     # dựng rig xong marker bị dọn
top = E[("Head", 'T')].location.copy()
root = top + Vector((.05, -.03, -.03))
ear = [root, root + Vector((.05, -.01, .10)), root + Vector((.12, -.02, .18))]
made, why = MK.add_chain(ctx, ref, "Ear", ear, guide, True, kinds=MK.CHAIN_PRESETS[0][3])
wing_root = E[("Spine.002", 'H')].location + Vector((.03, .08, 0))
up = [wing_root, wing_root + Vector((.25, .03, .12)), wing_root + Vector((.5, .05, .2))]
MK.add_chain(ctx, ref, "Wing", up, guide, True, kinds=MK.CHAIN_PRESETS[2][3])
low = [wing_root, wing_root + Vector((.22, .03, -.14)), wing_root + Vector((.42, .05, -.3))]
MK.add_chain(ctx, ref, "Wing_B", low, guide, True, attach=MK.end_map(ref)[("Wing.L", 'H')].name)
tail = [hip + Vector((0, .15 + .1 * i, -.02 * i)) for i in range(4)]
MK.add_chain(ctx, ref, "Tail", tail, guide, True, root_only=True, parent="Hips")
assert bpy.ops.srp.generate() == {'FINISHED'}
rig = bpy.data.objects["Loc_Rig"]
R = rig.matrix_world
bones = rig.data.bones
hd = R @ bones["Head"].head_local
spine = R @ bones["Spine.001"].head_local
thigh = (R @ bones["Thigh.L"].head_local).lerp(R @ bones["Thigh.L"].tail_local, .5)
ear_d = (ear[1] - ear[0]).normalized()

verts, faces, parts = [], [], {}


def add_box(key, c, size):
    base = len(verts)
    for x in (-1, 1):
        for y in (-1, 1):
            for z in (-1, 1):
                verts.append(tuple(Vector(c) + Vector((x * size[0], y * size[1], z * size[2]))))
    faces.extend([(base + a, base + b, base + d, base + e) for a, b, d, e in
                  ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3))])
    parts[key] = list(range(base, base + 8))


def add_strip(key, pts, width):
    base = len(verts)
    for p in pts:
        verts.append(tuple(p + Vector((0, width, 0))))
        verts.append(tuple(p - Vector((0, width, 0))))
    for i in range(len(pts) - 1):
        a = base + i * 2
        faces.append((a, a + 1, a + 3, a + 2))
    parts[key] = list(range(base, base + len(pts) * 2))


add_box("torso", spine, (.12, .1, .12))
add_box("thigh", thigh, (.05, .05, .08))
add_box("eye", root - ear_d * .05 + Vector((.01, -.02, 0)), (.022, .022, .022))
add_strip("ear", [ear[0].lerp(ear[1], t) for t in (.15, .5, .95)] + [ear[1].lerp(ear[2], t) for t in (.5, .95)], .012)
add_strip("wing", [up[0].lerp(up[2], t) for t in (.1, .35, .6, .85)] + [low[0].lerp(low[2], t) for t in (.85, .6, .35)], .02)
add_box("hipskin", hip, (.10, .1, .08))
me = bpy.data.meshes.new("LocBody")
me.from_pydata(verts, [], faces)
me.update()
ob = bpy.data.objects.new("LocBody", me)
sc.collection.objects.link(ob)
ob.modifiers.new("Armature", 'ARMATURE').object = rig
for n in [b.name for b in bones if b.use_deform]:
    ob.vertex_groups.new(name=n)
keep_g = ob.vertex_groups.new(name="FS_Keep")


def setw(idx, table):
    for k, x in table.items():
        ob.vertex_groups[k].add(idx, x, 'REPLACE')


# weight "automatic" xấu, đúng các lỗi đo được trên Mothman
setw(parts["torso"], {"Spine.001": .55, "Spine.002": .25, "Ear.L": .1, "Thigh.R": .1})
setw(parts["thigh"], {"Thigh.L": .6, "Thigh.R": .4})
setw(parts["eye"], {"Ear.L": .83, "Head": .17})
setw(parts["ear"], {"Ear.L": .4, "Ear.L.001": .3, "Ear.R": .15, "Head": .15})
setw(parts["wing"][:8], {"Wing.L": .6, "Wing.L.001": .2, "Bicep.L": .2})
setw(parts["wing"][8:], {"Wing_B.L": .6, "Wing_B.L.001": .2, "Thigh.L": .2})
setw(parts["hipskin"], {"Spine": .6, "Pelvis.L": .4})
keep_g.add(parts["eye"], .7, 'REPLACE')
hand_i = parts["torso"][0]
ob[cloth.HAND_KEY] = [hand_i]
ctx.view_layer.update()

changed, kept = F.localize(ob, rig)
rows = F.weights(ob)
deform = {b.name for b in bones if b.use_deform}


def dw(i):
    return {k: x for k, x in rows[i].items() if k in deform}


rep("có sửa weight", changed > 0, str(changed))
rep("mắt sát gốc râu trả hết về đầu", all(set(dw(i)) == {"Head"} for i in parts["eye"]), str(dw(parts["eye"][0])))
rep("râu chỉ còn xương của chính nó", all(all(k.startswith("Ear.L") for k in dw(i)) for i in parts["ear"]), str(dw(parts["ear"][0])))
rep("thân không còn dính râu", not any("Ear" in k for i in parts["torso"][1:] for k in dw(i)))
rep("đảo cánh giữ cả hai nhánh", any("Wing.L" in dw(i) for i in parts["wing"]) and any("Wing_B.L" in dw(i) for i in parts["wing"]))
rep("cánh không ăn tay, chân", not any(k in ("Bicep.L", "Thigh.L") for i in parts["wing"] for k in dw(i)))
rep("đùi trái không ăn đùi phải", all("Thigh.R" not in dw(i) for i in parts["thigh"]))
rep("vertex vẽ tay giữ nguyên", abs(dw(hand_i).get("Ear.L", 0) - .1) < 1e-4 and abs(dw(hand_i).get("Thigh.R", 0) - .1) < 1e-4, str(dw(hand_i)))
rep("nhóm không phải xương còn nguyên", all(abs(rows[i].get("FS_Keep", 0) - .7) < 1e-4 for i in parts["eye"]))
rep("tổng weight = 1, tối đa 4 xương", all(abs(sum(dw(i).values()) - 1) < 1e-3 and len(dw(i)) <= 4 for i in range(len(rows)) if i != hand_i))
print("TỔNG %d/%d" % (sum(results), len(results)))
