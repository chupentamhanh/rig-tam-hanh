"""Retarget animation. Fixture adult_final.blend (Adult_Rig + Kid_Rig). argv: -- outdir

Nguồn: bộ xương kiểu Mixamo dựng tại chỗ (mixamorig:*, T-pose, cm, scale 0.01),
cùng bộ đó qua file BVH và FBX (nút Nhập), và rig Rig Tẩm Hành khác (Adult).
Đo: hướng từng xương của đích (sau khi chạy action mới, qua FK / IK) so với
hướng xương nguồn cùng frame."""
import bpy, sys, os, math
import addon_utils
from mathutils import Vector, Quaternion, Euler

OUT = sys.argv[sys.argv.index("--") + 1]
os.makedirs(OUT, exist_ok=True)
addon_utils.enable("rig_tam_hanh", default_set=False)
from rig_tam_hanh import retarget as RT, unityexport as UE, rigdef

ctx = bpy.context
sc = ctx.scene
results = []


def rep(name, ok, detail=""):
    results.append(ok)
    print("[%s] %s %s" % ("ĐẠT" if ok else "HỎNG", name, detail))


# ---------------------------------------------------------------- nguồn Mixamo
J = {  # tên: (đầu, đuôi, cha) -- cm, nhìn -Y, bên trái +X, T-pose
    "Hips": ((0, 0, 100), (0, 0, 110), None), "Spine": ((0, 0, 110), (0, 0, 120), "Hips"),
    "Spine1": ((0, 0, 120), (0, 0, 130), "Spine"), "Spine2": ((0, 0, 130), (0, 0, 140), "Spine1"),
    "Neck": ((0, 0, 140), (0, 0, 150), "Spine2"), "Head": ((0, 0, 150), (0, 0, 168), "Neck"),
}
for s, x in (("Left", 1), ("Right", -1)):
    J.update({
        s + "Shoulder": ((5 * x, 0, 138), (15 * x, 0, 138), "Spine2"),
        s + "Arm": ((15 * x, 0, 138), (42 * x, 0, 138), s + "Shoulder"),
        s + "ForeArm": ((42 * x, 0, 138), (67 * x, 0, 138), s + "Arm"),
        s + "Hand": ((67 * x, 0, 138), (75 * x, 0, 138), s + "ForeArm"),
        s + "HandMiddle1": ((75 * x, 0, 138), (79 * x, 0, 138), s + "Hand"),
        s + "UpLeg": ((9 * x, 0, 100), (9 * x, 0, 55), "Hips"),
        s + "Leg": ((9 * x, 0, 55), (9 * x, 0, 10), s + "UpLeg"),
        s + "Foot": ((9 * x, 0, 10), (9 * x, -12, 2), s + "Leg"),
        s + "ToeBase": ((9 * x, -12, 2), (9 * x, -18, 2), s + "Foot"),
    })
data = bpy.data.armatures.new("Mixamo")
src = bpy.data.objects.new("Mixamo", data)
sc.collection.objects.link(src)
src.scale = (0.01, 0.01, 0.01)
src.location = (2.0, 0, 0)
ctx.view_layer.objects.active = src
bpy.ops.object.mode_set(mode='EDIT')
for n, (h, t, p) in J.items():
    e = data.edit_bones.new("mixamorig:" + n)
    e.head, e.tail = h, t
for n, (h, t, p) in J.items():
    if p:
        e = data.edit_bones["mixamorig:" + n]
        e.parent = data.edit_bones["mixamorig:" + p]
        e.use_connect = (Vector(h) - Vector(J[p][1])).length < 1e-6
bpy.ops.object.mode_set(mode='OBJECT')
act = bpy.data.actions.new("Walkish")
src.animation_data_create().action = act
P = src.pose.bones
KEYS = {  # bone: [(frame, euler độ)]
    "LeftArm": [(1, (0, 0, 0)), (20, (0, 40, -50))],
    "LeftForeArm": [(1, (0, 0, 0)), (20, (0, 0, -60))],
    "RightArm": [(1, (0, 0, 0)), (20, (30, 0, 45))],
    "Spine2": [(1, (0, 0, 0)), (20, (10, 20, 0))],
    "Neck": [(1, (0, 0, 0)), (20, (-15, 0, 10))],
    "LeftUpLeg": [(1, (0, 0, 0)), (20, (-40, 0, 0))],
    "LeftLeg": [(1, (0, 0, 0)), (20, (50, 0, 0))],
    "RightUpLeg": [(1, (0, 0, 0)), (20, (25, 0, 10))],
}
for n, ks in KEYS.items():
    pb = P["mixamorig:" + n]
    pb.rotation_mode = 'QUATERNION'
    for f, e in ks:
        pb.rotation_quaternion = Euler([math.radians(a) for a in e]).to_quaternion()
        pb.keyframe_insert("rotation_quaternion", frame=f)
hp = P["mixamorig:Hips"]
for f, loc in ((1, (0, 0, 0)), (20, (0, 0, -40))):       # hông: tiến 40 cm (trục Y bone = Z thế giới… xem dưới)
    hp.location = loc
    hp.keyframe_insert("location", frame=f)


def angle_report(s_arm, t_arm, frames, sm=None):
    """Góc lệch lớn nhất (độ) giữa hướng xương nguồn và đích, mỗi Humanoid."""
    sm = sm or RT.source_map(s_arm)
    tm = UE.humanoid_map(t_arm)
    worst = {}
    for f in frames:
        sc.frame_set(f)
        es = s_arm.evaluated_get(ctx.evaluated_depsgraph_get())
        et = t_arm.evaluated_get(ctx.evaluated_depsgraph_get())
        for h, child in (("LeftUpperArm", "LeftLowerArm"), ("LeftLowerArm", "LeftHand"), ("RightUpperArm", "RightLowerArm"),
                         ("LeftUpperLeg", "LeftLowerLeg"), ("LeftLowerLeg", "LeftFoot"), ("RightUpperLeg", "RightLowerLeg"),
                         ("RightLowerLeg", "RightFoot"), ("Spine", "Neck"), ("Neck", "Head")):
            if not all(k in sm and k in tm for k in (h, child)):
                continue
            ds = (s_arm.matrix_world @ es.pose.bones[sm[child]].head) - (s_arm.matrix_world @ es.pose.bones[sm[h]].head)
            dt = (t_arm.matrix_world @ et.pose.bones[tm[child]].head) - (t_arm.matrix_world @ et.pose.bones[tm[h]].head)
            # hướng lúc nghỉ hai bên khác nhau: so phần XOAY so với lúc nghỉ
            if h in RT.AXIAL:
                # thân / cổ: giữ dáng nghỉ riêng của đích, so ĐỘ XOAY so với lúc nghỉ
                qs = (s_arm.matrix_world @ es.pose.bones[sm[h]].matrix).to_3x3().normalized().to_quaternion() @                      (s_arm.matrix_world @ s_arm.data.bones[sm[h]].matrix_local).to_3x3().normalized().to_quaternion().inverted()
                ds = qs @ _rest_dir(t_arm, tm, h, child)
            worst[h] = max(worst.get(h, 0.0), _delta_angle(s_arm, t_arm, sm, tm, h, child, ds, dt))
        for a, b in (("LeftUpperArm", "RightUpperArm"), ("LeftUpperLeg", "RightUpperLeg")):
            if all(k in sm and k in tm for k in (a, b)):
                ls = (s_arm.matrix_world @ es.pose.bones[sm[a]].head) - (s_arm.matrix_world @ es.pose.bones[sm[b]].head)
                lt = (t_arm.matrix_world @ et.pose.bones[tm[a]].head) - (t_arm.matrix_world @ et.pose.bones[tm[b]].head)
                key = "đường " + ("vai" if "Arm" in a else "hông")
                worst[key] = max(worst.get(key, 0.0), math.degrees(ls.normalized().angle(lt.normalized())))
    return worst


def _rest_dir(arm, m, a, b):
    B = arm.data.bones
    return ((arm.matrix_world @ B[m[b]].head_local) - (arm.matrix_world @ B[m[a]].head_local)).normalized()


def _delta_angle(s_arm, t_arm, sm, tm, h, child, ds, dt):
    rs, rt = _rest_dir(s_arm, sm, h, child), _rest_dir(t_arm, tm, h, child)
    # đích lẽ ra = A·(Δ nguồn)·…: hướng đích = Δ_nguồn · hướng_nguồn_nghỉ (A đưa đích về hướng nguồn)
    # nên so trực tiếp hướng hiện tại của hai bên (cùng hướng nhìn -Y)
    return math.degrees(ds.normalized().angle(dt.normalized()))


kid = bpy.data.objects["Kid_Rig"]
adult = bpy.data.objects["Adult_Rig"]
if kid.name not in ctx.view_layer.objects:
    sc.collection.objects.link(kid)          # fixture: Kid nằm trong collection bị loại khỏi view layer
kid.hide_set(False)

# ---- ghép xương
pr = RT.pairs(src, kid)
names = {h for h, _s, _t in pr}
rep("ghép Mixamo -> Kid", {"Hips", "Spine", "Neck", "Head", "LeftUpperArm", "LeftHand", "RightUpperLeg", "RightFoot"} <= names,
    "%d cặp" % len(pr))

# ---- retarget Mixamo -> Kid
legs_before = [l.switch(kid) for l in rigdef.limbs_for(kid) if l.kind == 'LEG']
new, info = RT.retarget(ctx, src, act, kid)
rep("ra action mới có slot cho rig", new.name == "Walkish_Kid_Rig" and kid.animation_data.action is new
    and any(s.name_display == kid.name for s in new.slots), new.name)
rep("bù tỉ lệ hông", 0.2 < info['scale'] < 1.5, "%.3f" % info['scale'])
src.animation_data.action = act
w = angle_report(src, kid, (1, 10, 20))
bad = {h: round(a, 1) for h, a in w.items() if a > 3.0}
rep("Mixamo -> Kid: hướng xương khớp (< 3°)", not bad and len(w) >= 7, "lệch nhất %.2f° %s" % (max(w.values()), {h: round(a, 2) for h, a in w.items()}))
rep("chân để IK vẫn khớp (qua snap IK)", all(v >= 0.5 for v in legs_before) and w.get("LeftLowerLeg", 99) < 3.0,
    "cẳng chân trái %.2f°" % w.get("LeftLowerLeg", 99))
# hông tiến theo tỉ lệ
sc.frame_set(1)
h1 = (kid.matrix_world @ kid.pose.bones["Hips"].head).copy()
sc.frame_set(20)
h20 = (kid.matrix_world @ kid.pose.bones["Hips"].head).copy()
es = src
sc.frame_set(1)
s1 = (src.matrix_world @ src.pose.bones["mixamorig:Hips"].head).copy()
sc.frame_set(20)
s20 = (src.matrix_world @ src.pose.bones["mixamorig:Hips"].head).copy()
ratio = (h20 - h1).length / max((s20 - s1).length, 1e-6)
rep("hông dịch đúng tỉ lệ", abs(ratio - info['scale']) < 0.02, "đích/nguồn %.3f, tỉ lệ %.3f" % (ratio, info['scale']))

# ---- đứng tại chỗ
new2, info2 = RT.retarget(ctx, src, act, kid, in_place=True, name="InPlace")
sc.frame_set(1)
a1 = (kid.matrix_world @ kid.pose.bones["Hips"].head).copy()
sc.frame_set(20)
a20 = (kid.matrix_world @ kid.pose.bones["Hips"].head).copy()
rep("đứng tại chỗ: hông không đi ngang", math.hypot(a20.x - a1.x, a20.y - a1.y) < 1e-4, "%.5f" % math.hypot(a20.x - a1.x, a20.y - a1.y))

# ---- BVH và FBX qua nút Nhập
for ext in ("bvh", "fbx"):
    p = os.path.join(OUT, "src." + ext)
    for o in ctx.view_layer.objects:
        o.select_set(o is src)
    ctx.view_layer.objects.active = src
    src.animation_data.action = act
    sc.frame_start, sc.frame_end = 1, 20
    if ext == "bvh":
        bpy.ops.export_anim.bvh(filepath=p, frame_start=1, frame_end=20, root_transform_only=False)
    else:
        bpy.ops.export_scene.fbx(filepath=p, use_selection=True, object_types={'ARMATURE'}, bake_anim=True,
                                 bake_anim_use_all_actions=False, bake_anim_use_nla_strips=False, add_leaf_bones=False)
    r = bpy.ops.srp.retarget_import(filepath=p)
    s2 = sc.srp_retarget.source
    ok = r == {'FINISHED'} and s2 is not None and s2 is not src
    a2 = sc.srp_retarget.action
    rep("nhập %s" % ext.upper(), ok and a2 is not None, "%s / %s" % (s2.name if s2 else None, a2.name if a2 else None))
    if not ok or a2 is None:
        continue
    new3, info3 = RT.retarget(ctx, s2, a2, kid, name="From_" + ext)
    s2.animation_data.action = a2
    f0, f1 = (int(round(x)) for x in a2.frame_range)
    w = angle_report(s2, kid, (f0, (f0 + f1) // 2, f1))
    bad = {h: round(a, 1) for h, a in w.items() if a > 4.0}
    rep("%s -> Kid: hướng xương khớp (< 4°)" % ext.upper(), not bad and len(w) >= 7,
        "lệch nhất %.2f° %s" % (max(w.values()) if w else -1, bad))

# ---- rig Rig Tẩm Hành khác: Adult -> Kid
src.animation_data.action = act
new_a, _i = RT.retarget(ctx, src, act, adult, name="OnAdult")
ad_act = adult.animation_data.action
new4, info4 = RT.retarget(ctx, adult, ad_act, kid, name="AdultToKid")
adult.animation_data.action = ad_act
w = angle_report(adult, kid, (1, 10, 20), sm=UE.humanoid_map(adult))
bad = {h: round(a, 1) for h, a in w.items() if a > 3.0}
rep("Adult -> Kid (rig Tẩm Hành): hướng xương khớp (< 3°)", not bad and len(w) >= 7,
    "lệch nhất %.2f° %s" % (max(w.values()) if w else -1, bad))

# ---- nút + bảng ghép sửa tay
sc.srp_retarget.source = src
bpy.ops.srp.retarget_map()
t = bpy.data.texts[RT.MAP_TEXT]
txt = t.as_string().replace("LeftToes = mixamorig:LeftToeBase", "LeftToes = ")
t.clear()
t.write(txt)
rep("sửa bảng ghép: bỏ một bone", "LeftToes" not in {h for h, _s, _t in RT.pairs(src, kid)})
t.clear()
sc.srp_retarget.action = act
ctx.view_layer.objects.active = kid
r = bpy.ops.srp.retarget()
rep("nút Retarget chạy được", r == {'FINISHED'})
print("TỔNG %d/%d" % (sum(results), len(results)))
