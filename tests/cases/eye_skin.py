"""Nhãn cầu skin cứng vào xương mắt (như răng) thay cho parent BONE.
Fixture adult_final.blend: Adult_eyes_L/R đang gắn kiểu parent BONE cũ."""
import math

import addon_utils
import bpy
import numpy as np

addon_utils.enable("rig_tam_hanh", default_set=False)
from rig_tam_hanh import face as F, facebendy as FB, generate as G, unityexport as UE

ctx = bpy.context
arm = bpy.data.objects["Adult_Rig"]
eyes = {"L": bpy.data.objects["Adult_eyes_L"], "R": bpy.data.objects["Adult_eyes_R"]}
hair = bpy.data.objects["Adult_HAIR"]
P = arm.pose.bones
results = []


def rep(name, ok, detail=""):
    results.append(bool(ok))
    print("[%s] %s %s" % ("ĐẠT" if ok else "HỎNG", name, detail))


def world(o):
    dg = ctx.evaluated_depsgraph_get()
    e = o.evaluated_get(dg)
    m = e.to_mesh()
    out = np.array([tuple(e.matrix_world @ v.co) for v in m.vertices])
    e.to_mesh_clear()
    return out


def pose(on):
    for pb in P:
        pb.matrix_basis.identity()
    if on:
        for n, axis, deg in (("Eye.L", 2, 25), ("Eye.R", 0, -15), ("Head", 2, 30), ("Neck", 0, 12)):
            pb = P[n]
            pb.rotation_mode = 'XYZ'
            e = [0.0, 0.0, 0.0]
            e[axis] = math.radians(deg)
            pb.rotation_euler = e
    ctx.view_layer.update()


rep("kiểu cũ (parent BONE) vẫn nhận ra",
    F.rigid_bone(eyes["L"], arm) == "Eye.L" and FB.eyeball_for(arm, "L") is eyes["L"])
rep("tóc skin cứng vào Head không bị coi là cõng phụ kiện",
    F.rigid_bone(hair, arm) == "Head" and "Head" not in G.mount_bones(arm))

pose(False)
rest0 = {s: world(o) for s, o in eyes.items()}
pose(True)
posed0 = {s: world(o) for s, o in eyes.items()}

# gắn lại TRONG LÚC rig đang pose: không được nướng tư thế vào chỗ đứng
for s, o in eyes.items():
    F.attach_eye(o, arm, "Eye." + s)
ctx.view_layer.update()

for s, o in eyes.items():
    mods = [m for m in o.modifiers if m.type == 'ARMATURE']
    groups = [g.name for g in o.vertex_groups]
    w = [g.weight for v in o.data.vertices for g in v.groups]
    rep("%s: armature modifier + một nhóm Eye.%s weight 1" % (o.name, s),
        len(mods) == 1 and mods[0].object is arm and groups == ["Eye." + s]
        and len(w) == len(o.data.vertices) and min(w) > 0.999,
        "%s %s" % ([m.name for m in mods], groups))
    rep("%s: parent rig kiểu OBJECT" % o.name, o.parent is arm and o.parent_type == 'OBJECT')
    rep("%s: rigid_bone = Eye.%s" % (o.name, s), F.rigid_bone(o, arm) == "Eye." + s)
    d = np.abs(world(o) - posed0[s]).max()
    rep("%s: đang pose vẫn đúng chỗ như kiểu cũ" % o.name, d < 1e-4, "%.6f m" % d)

pose(False)
for s, o in eyes.items():
    d = np.abs(world(o) - rest0[s]).max()
    rep("%s: tư thế nghỉ không xê dịch" % o.name, d < 1e-5, "%.7f m" % d)

mb = G.mount_bones(arm)
rep("xương mắt vẫn là xương cõng nhãn cầu",
    mb.get("Eye.L") == ["Adult_eyes_L"] and mb.get("Eye.R") == ["Adult_eyes_R"], str(mb))
stray = [(o.name, n) for o, n, _c in G.stray_mounts(ctx, arm)]
rep("nút gỡ trọng số không động vào chính nhãn cầu",
    not any(o in ("Adult_eyes_L", "Adult_eyes_R") for o, _n in stray), str(stray))
rep("mặt bendy tìm thấy nhãn cầu", FB.eyeball_for(arm, "R") is eyes["R"])
skinned, attached = UE.rig_meshes(arm)
rep("xuất Unity: nhãn cầu là mesh skin", eyes["L"] in skinned and not attached)

# bind tay ra 100% một xương (Ctrl+P automatic) cũng nhận ra
o = eyes["L"]
g = o.vertex_groups.new(name="Head")
rep("nhóm rỗng của xương khác (bind tay) vẫn nhận ra", F.rigid_bone(o, arm) == "Eye.L")
g.add([0], 0.5, 'REPLACE')
rep("mesh ăn hai xương thì không phải gắn cứng", F.rigid_bone(o, arm) is None)
o.vertex_groups.remove(g)
print("TỔNG %d/%d" % (sum(results), len(results)))
