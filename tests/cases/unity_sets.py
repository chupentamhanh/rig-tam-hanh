"""Xuất Unity: phạm vi mesh (đang chọn / đang hiện / collection) + bộ action.
Fixture kid_facekeys.blend. argv: -- outdir"""
import bpy, sys, os, json
import addon_utils

OUT = sys.argv[sys.argv.index("--") + 1]
addon_utils.enable("rig_tam_hanh", default_set=False)
from rig_tam_hanh import unityexport as UE, compat

ctx = bpy.context
rig = bpy.data.objects["Kid_Rig.001"]
results = []


def rep(name, ok, detail=""):
    results.append(ok)
    print("[%s] %s %s" % ("ĐẠT" if ok else "HỎNG", name, detail))


for a in list(bpy.data.actions):
    bpy.data.actions.remove(a)


def make(name, bone, last=12):
    act = bpy.data.actions.new(name)
    slot = act.slots.new('OBJECT', rig.name)
    bag = compat.action_channelbag(act, slot, create=True)
    for i in range(4):
        fc = bag.fcurves.new('pose.bones["%s"].rotation_quaternion' % bone, index=i)
        fc.keyframe_points.insert(1, 1.0 if i == 0 else 0.0)
        fc.keyframe_points.insert(last, 0.9 if i == 0 else 0.1)
    return act


walk, run, idle = make("Walk", "Spine"), make("Run", "Neck", 20), make("Idle", "Head", 30)


def fbx_content(path):
    """(tên mesh, tên action) trong một FBX -- import vào scene tạm rồi xoá."""
    before_o, before_a = set(bpy.data.objects), set(bpy.data.actions)
    bpy.ops.import_scene.fbx(filepath=path, use_anim=True)
    objs = [o for o in bpy.data.objects if o not in before_o]
    acts = [a for a in bpy.data.actions if a not in before_a]
    import re
    meshes = sorted(re.sub(r"\.\d{3}$", "", o.name) for o in objs if o.type == 'MESH')
    takes = sorted({a.name.split("|")[-1] for a in acts})
    for o in objs:
        bpy.data.objects.remove(o, do_unlink=True)
    for a in acts:
        bpy.data.actions.remove(a)
    return meshes, takes


skinned, attached = UE.rig_meshes(rig)
allm = skinned + attached
rep("fixture có nhiều mesh", len(allm) >= 2, str([o.name for o in allm]))
body = max(skinned, key=lambda o: len(o.data.vertices))

# ---- phạm vi: đang chọn
for o in ctx.view_layer.objects:
    o.select_set(False)
body.select_set(True)
folder = os.path.join(OUT, "sel")
files, _l = UE.export(ctx, rig, folder, "Kid", which='NONE', scope='SELECTED')
rep("xuất xong vẫn giữ lựa chọn cũ", body.select_get() and not rig.select_get())
meshes, _t = fbx_content(os.path.join(folder, "Kid.fbx"))
rep("đang chọn: chỉ mesh đang chọn", meshes == [body.name], str(meshes))

# ---- phạm vi: đang hiện
hidden = [o for o in allm if o is not body][0]
hidden.hide_set(True)
folder = os.path.join(OUT, "vis")
UE.export(ctx, rig, folder, "Kid", which='NONE', scope='VISIBLE')
meshes, _t = fbx_content(os.path.join(folder, "Kid.fbx"))
rep("đang hiện: bỏ mesh đang ẩn", hidden.name not in meshes and body.name in meshes, str(meshes))
hidden.hide_set(False)

# ---- phạm vi: collection
coll = bpy.data.collections.new("XuatThu")
ctx.scene.collection.children.link(coll)
coll.objects.link(hidden)
folder = os.path.join(OUT, "coll")
UE.export(ctx, rig, folder, "Kid", which='NONE', scope='COLLECTION', scope_coll=coll)
meshes, _t = fbx_content(os.path.join(folder, "Kid.fbx"))
rep("collection: chỉ mesh trong collection", meshes == [hidden.name], str(meshes))

for o in ctx.view_layer.objects:
    o.select_set(False)
try:
    UE.export(ctx, rig, os.path.join(OUT, "empty"), "Kid", which='NONE', scope='SELECTED')
    rep("không mesh nào trong phạm vi -> báo lỗi", False)
except ValueError as e:
    rep("không mesh nào trong phạm vi -> báo lỗi", "phạm vi" in str(e), str(e))

# ---- bộ action
ctx.view_layer.objects.active = rig
rig.select_set(True)
ctx.scene.srp_unity.rig = rig
bpy.ops.srp.action_set(op='ADD_SET')
bpy.ops.srp.action_set(op='ADD_SET')
sets = rig.srp_action_sets
sets[0].name, sets[1].name = "Locomotion", "Rest"
rig.srp_action_sets_index = 0
idle.srp_unity_export = False
bpy.ops.srp.action_set(op='ADD_CHECKED')                 # Run + Walk
rig.srp_action_sets_index = 1
bpy.ops.srp.action_set(op='ADD', pick="Idle")
bpy.ops.srp.action_set(op='ADD', pick="Idle")            # trùng: không thêm lần hai
rep("nút thêm action vào bộ", [r.action.name for r in sets[0].actions] == ["Run", "Walk"]
    and [r.action.name for r in sets[1].actions] == ["Idle"])

folder = os.path.join(OUT, "sets")
files, lines = UE.export(ctx, rig, folder, "Kid", which='SETS', scope='RIG')
names = sorted(os.path.basename(f) for f in files if f.endswith(".fbx"))
rep("mỗi bộ một file", names == ["Kid.fbx", "Kid@Locomotion.fbx", "Kid@Rest.fbx"], str(names))
_m, takes = fbx_content(os.path.join(folder, "Kid@Locomotion.fbx"))
rep("file bộ có đủ take, đúng tên", takes == ["Run", "Walk"], str(takes))
_m, takes = fbx_content(os.path.join(folder, "Kid@Rest.fbx"))
rep("bộ thứ hai không lẫn take bộ trước", takes == ["Idle"], str(takes))
js = json.load(open(os.path.join(folder, "Kid.humanoid.json"), encoding="utf-8"))
rep("json ghi bộ và file của từng clip", js["sets"] == ["Locomotion", "Rest"]
    and {(c["name"], c.get("file")) for c in js["clips"]} == {("Walk", "Locomotion"), ("Run", "Locomotion"), ("Idle", "Rest")},
    str(js["sets"]))
first = min(os.path.getmtime(os.path.join(folder, n)) for n in names)
rep("json ghi trước mọi FBX", os.path.getmtime(os.path.join(folder, "Kid.humanoid.json")) <= first)

sets[1].use = False
folder = os.path.join(OUT, "sets2")
files, lines = UE.export(ctx, rig, folder, "Kid", which='SETS')
rep("bỏ tích bộ -> không xuất bộ đó", sorted(os.path.basename(f) for f in files if f.endswith(".fbx"))
    == ["Kid.fbx", "Kid@Locomotion.fbx"])
sets[0].use = False
try:
    UE.export(ctx, rig, os.path.join(OUT, "sets3"), "Kid", which='SETS')
    rep("không bộ nào -> báo lỗi", False)
except ValueError as e:
    rep("không bộ nào -> báo lỗi", True, str(e))
rep("rig không bị để lại NLA", not rig.animation_data or not len(rig.animation_data.nla_tracks))
print("TỔNG %d/%d" % (sum(results), len(results)))
