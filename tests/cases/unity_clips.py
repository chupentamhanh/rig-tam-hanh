"""Xuất Unity: danh sách clip theo slot + ô tích chọn clip. Fixture kid_facekeys.blend. argv: -- outdir"""
import bpy, sys, os, json
import addon_utils

OUT = sys.argv[sys.argv.index("--") + 1]
addon_utils.enable("rig_tam_hanh", default_set=False)
from rig_tam_hanh import unityexport as UE, compat

ctx = bpy.context
rig = bpy.data.objects["Kid_Rig.001"]
body = bpy.data.objects["body"]
results = []


def rep(name, ok, detail=""):
    results.append(ok)
    print("[%s] %s %s" % ("ĐẠT" if ok else "HỎNG", name, detail))


for a in list(bpy.data.actions):
    bpy.data.actions.remove(a)


def make(name, slot_name, bone, target='OBJECT'):
    act = bpy.data.actions.new(name)
    slot = act.slots.new(target, slot_name)
    bag = compat.action_channelbag(act, slot, create=True)
    path = 'pose.bones["%s"].rotation_quaternion' % bone if bone else 'location'
    for i in range(4 if bone else 3):
        fc = bag.fcurves.new(path, index=i)
        fc.keyframe_points.insert(1, 1.0 if (bone and i == 0) else 0.0)
        fc.keyframe_points.insert(12, 0.9 if (bone and i == 0) else 0.1)
    return act, slot

used, s_used = make("Clip_Used", "Whatever", "Spine")          # slot rig đang dùng
named, _s = make("Clip_Named", rig.name, None)                 # slot trùng tên rig (kênh object)
bones, _s = make("Clip_Bones", "Other", "Neck")                # slot lạ nhưng kênh trỏ vào bone rig
other, _s = make("Clip_Other", "Camera", None)                 # slot của object khác
anim = rig.animation_data or rig.animation_data_create()
anim.action = used
anim.action_slot = s_used

found = [a.name for a, _s in UE.rig_clips(rig)]
rep("danh sách theo slot", found == ["Clip_Bones", "Clip_Named", "Clip_Used"], str(found))
rep("mặc định mọi clip được tích", all(a.srp_unity_export for a in bpy.data.actions))

named.srp_unity_export = False
rep("bỏ tích -> không nằm trong danh sách xuất", [a.name for a in UE.picked_actions(rig)] == ["Clip_Bones", "Clip_Used"])

folder = os.path.join(OUT, "sep")
files, lines = UE.export(ctx, rig, folder, "Kid", which='ALL', combine=False, only_human=True)
names = sorted(os.path.basename(f) for f in files if f.endswith(".fbx"))
rep("chỉ xuất clip được tích (file riêng)", names == ["Kid.fbx", "Kid@Clip_Bones.fbx", "Kid@Clip_Used.fbx"], str(names))
js = json.load(open(os.path.join(folder, "Kid.humanoid.json"), encoding="utf-8"))
rep("json chỉ ghi clip được tích", sorted(c["name"] for c in js["clips"]) == ["Clip_Bones", "Clip_Used"])

folder = os.path.join(OUT, "comb")
files, lines = UE.export(ctx, rig, folder, "Kid", which='ALL', combine=True, only_human=True)
js = json.load(open(os.path.join(folder, "Kid.humanoid.json"), encoding="utf-8"))
rep("gộp: chỉ take của clip được tích", sorted(c["name"] for c in js["clips"]) == ["Clip_Bones", "Clip_Used"],
    str([c["name"] for c in js["clips"]]))
rep("rig trả lại action đang gán", rig.animation_data.action is used and rig.animation_data.action_slot == s_used)

for a in bpy.data.actions:
    a.srp_unity_export = False
folder = os.path.join(OUT, "none")
files, lines = UE.export(ctx, rig, folder, "Kid", which='ALL', combine=False, only_human=True)
rep("bỏ tích hết -> chỉ mô hình", sorted(os.path.basename(f) for f in files if f.endswith(".fbx")) == ["Kid.fbx"])

_e, _w, notes, _m = UE.check(rig)
rep("Kiểm tra Humanoid báo clip bị bỏ", any(n.startswith("Bỏ không xuất") for n in notes))

for a in bpy.data.actions:
    a.srp_unity_export = True
r = bpy.ops.srp.unity_clips(value=False)
rep("nút bỏ tích hết", all(not a.srp_unity_export for a, _s in UE.rig_clips(rig)) and other.srp_unity_export)
print("TỔNG %d/%d" % (sum(results), len(results)))
