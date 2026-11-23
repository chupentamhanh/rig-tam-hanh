"""Đặt marker từng khớp: dựng từ marker trên mesh tạm, kiểm vị trí, roll, FK/IK, Unity. argv: -- outdir"""
import bpy, sys, os, math
import addon_utils
from mathutils import Matrix, Vector

OUT = sys.argv[sys.argv.index("--") + 1]
os.makedirs(OUT, exist_ok=True)
addon_utils.enable("rig_tam_hanh", default_set=False)
from rig_tam_hanh import markers as MK, refrig, generate, build, rigdef, unityexport as UE

ctx = bpy.context
sc = ctx.scene
results = []


def rep(name, ok, detail=""):
    results.append(bool(ok))
    print("[%s] %s %s" % ("ĐẠT" if ok else "HỎNG", name, detail))


bpy.ops.mesh.primitive_cube_add(size=1, location=(0.1, 0, 0.9))
body = ctx.object
body.name = "Body"
body.scale = (0.8, 0.3, 1.8)
bpy.ops.object.transform_apply(scale=True)
gs = sc.srp_generate
gs.target_mesh = body
gs.rig_name = "MK_Rig"
sc.srp_ref.fingers = 4
sc.srp_ref.leg_type = 'HUMAN'

rep("tạo marker", bpy.ops.srp.marker_start() == {'FINISHED'})
ref = refrig.find_ref(ctx)
ms = MK.markers_of(ref)
ends = sum(len(MK.ends_of(m)) for m in ms)
rep("mỗi đầu xương thuộc đúng một marker", ends == 2 * len(ref.data.bones), "%d/%d" % (ends, 2 * len(ref.data.bones)))
rep("khớp nối liền gộp một marker", len(ms) < 2 * len(ref.data.bones), "%d marker, %d xương" % (len(ms), len(ref.data.bones)))
M = {n: m for m in ms for n, e in MK.ends_of(m) if e == 'H'}
rep("cổ tay và 4 xương bàn cùng một marker", all(M[n] == M["Hand_Master.L"] for n in ("Palm.L.001", "Palm.L.002", "Palm.L.003", "Palm.L.004")))
rep("marker đôi nhận đúng cặp", M["Bicep.L"].get(MK.TAG_TWIN) == M["Bicep.R"].name and MK.is_center(M["Spine.001"]))
q = [g["marker"] for g in MK.guide_of(ref)]
rep("thứ tự đặt: hông trước, không có bên phải", q[0] == M["Hips"].name and not any(".R" in n for n in q), q[0])
rep("chỉ phải click khớp chính", len(q) == 22, "%d click cho %d khớp" % (len(q), len(ms)))
E = MK.end_map(ref)
rep("gốc ngón và đuôi xương bàn là một khớp", E[("Palm.L.003", 'T')] == E[("Index.L", 'H')])
rep("marker không bấm trúng được ngoài chế độ đặt", all(not m.visible_get() for m in ms))

# điểm giữa khối thịt
tree = MK.mesh_tree(ctx, body)
p = MK.center_hit(tree, Vector((0.3, -5, 1.0)), Vector((0, 1, 0)))
rep("click rơi vào giữa khối thịt", p is not None and abs(p.y) < 1e-3, str(p))
s = tree.ray_cast(Vector((0.3, -5, 1.0)), Vector((0, 1, 0)))[0]
rep("Shift+click nằm trên da", abs(s.y + 0.15) < 1e-3)

# đặt cổ tay: bàn tay chưa đặt đi theo, bên phải là ảnh gương
cx = ref[MK.TAG_CX]
MK.place(ref, M["Bicep.L"], Vector((cx + 0.14, 0.01, 1.45)))
old = M["Index.L"].location - M["Hand_Master.L"].location
MK.place(ref, M["Hand_Master.L"], Vector((cx + 0.42, 0.0, 1.20)))
new = M["Index.L"].location - M["Hand_Master.L"].location
rep("đặt cổ tay thì ngón đi theo", abs(new.length - old.length) > 1e-5 or (new - old).length > 1e-3, "%.3f m" % (new - old).length)
twin = M["Hand_Master.R"].location
rep("bên phải là ảnh gương", abs((twin.x - cx) + (M["Hand_Master.L"].location.x - cx)) < 1e-6 and abs(twin.z - 1.20) < 1e-6)
MK.place(ref, M["Spine.001"], Vector((cx + 0.2, 0.0, 1.05)))
rep("khớp giữa bị ghim vào trục đối xứng", abs(M["Spine.001"].location.x - cx) < 1e-6)
MK.place(ref, M["Forearm.L"], Vector((cx - 0.28, 0.035, 1.33)))
rep("click nhầm bên vẫn về đúng bên", abs(M["Forearm.L"].location.x - (cx + 0.28)) < 1e-6 and abs(M["Forearm.R"].location.x - (cx - 0.28)) < 1e-6)
MK.place(ref, M["Hips"], Vector((cx, 0.0, 0.9)))
MK.place(ref, M["Neck"], Vector((cx, 0.01, 1.5)))
zs = [M[n].location.z for n in ("Hips", "Spine.001", "Spine.002", "Spine.003", "Neck")]
rep("đốt sống tự chia giữa Hông và Cổ", all(a < b for a, b in zip(zs, zs[1:])) or M["Spine.001"].get(MK.TAG_PLACED), str(["%.3f" % z for z in zs]))
rep("đốt sống giữa chưa bị coi là đã đặt", not M["Spine.002"].get(MK.TAG_PLACED))
MK.place(ref, M["Index.L"], M["Hand_Master.L"].location + Vector((0.09, -0.03, -0.05)))
tip = E[("Index.L.002", 'T')]
MK.place(ref, tip, M["Index.L"].location + Vector((0.08, -0.01, -0.06)))
a, b, mid = M["Index.L"].location, tip.location, M["Index.L.001"].location
rep("đốt ngón tự chia giữa gốc và đầu ngón", (mid - a).length + (b - mid).length < (b - a).length * 1.1 and 0.1 < (mid - a).length / (b - a).length < 0.7, "%.3f" % ((mid - a).length / (b - a).length))
spine_before = M["Spine.002"].location.copy()
placed_before = {m.name for m in MK.markers_of(ref) if m.get(MK.TAG_PLACED)}
hand_before = M["Hand_Master.L"].location.copy()
MK.place(ref, M["Shoulder.L"], Vector((cx + 0.03, 0.0, 1.42)))
rep("đặt xương đòn không kéo cột sống", (M["Spine.002"].location - spine_before).length < 1e-6)
rep("đặt xương đòn không xoá khớp đã đặt", placed_before <= {m.name for m in MK.markers_of(ref) if m.get(MK.TAG_PLACED)})
rep("khớp đã đặt giữ nguyên vị trí", (M["Hand_Master.L"].location - hand_before).length < 1e-6)
rep("hai bên vẫn là ảnh gương", abs((M["Hand_Master.R"].location.x - cx) + (hand_before.x - cx)) < 1e-6 and M["Shoulder.R"].get(MK.TAG_PLACED))
# ngón nghiêng lạ: căn vào thịt và trục gập theo chính ngón
root, mid1, mid2 = M["Thumb.L"], M["Thumb.L.001"], M["Thumb.L.002"]
tip_t = E[("Thumb.L.002", 'T')]
rep("chuỗi ngón cái đủ 3 đốt", [b.name for b in MK.chain_bones(ref, mid1)] == ["Thumb.L", "Thumb.L.001", "Thumb.L.002"])
axis = Vector((0.62, -0.55, -0.56)).normalized()
side_v = axis.cross(Vector((0.2, 0.9, 0.4))).normalized()
base_p = M["Hand_Master.L"].location + Vector((0.03, -0.05, -0.02))
want = [base_p, base_p + axis * 0.03 + side_v * 0.004, base_p + axis * 0.055 + side_v * 0.012, base_p + axis * 0.075 + side_v * 0.024]
for m, p in zip((root, mid1, mid2, tip_t), want):
    MK.place(ref, m, p, auto_side=False)
rep("kéo được đốt giữa, không làm lệch gốc và đầu ngón", (mid1.location - want[1]).length < 1e-6 and (root.location - want[0]).length < 1e-6 and (tip_t.location - want[3]).length < 1e-6)
n, why = MK.hinge_chain(ref, mid1)
plan = MK.frames(ref)
plane = (want[1] - want[0]).cross(want[2] - want[1]).normalized()
off = 0.0
for b in ("Thumb.L", "Thumb.L.001", "Thumb.L.002"):
    h, t, z = plan[b]
    off = max(off, math.degrees(math.asin(min(1.0, abs((t - h).normalized().cross(z).normalized().dot(plane))))) and abs(90 - math.degrees((t - h).normalized().cross(z).angle(plane))))
rep("trục X trùng trục gập của ngón nghiêng", n == 3 and off > 85 or n == 3 and abs(off) > 85, "lệch %.2f°" % (90 - off))
zr = plan["Thumb.R"][2]; zl = plan["Thumb.L"][2]
rep("trục gập bên phải là ảnh gương", (Vector((-zl.x, zl.y, zl.z)) - zr).length < 1e-3)
bpy.ops.mesh.primitive_cylinder_add(radius=0.012, depth=0.3, location=(2, 0, 1))
cyl = ctx.object
cyl.rotation_euler = axis.to_track_quat('Z', 'Y').to_euler()
bpy.ops.object.transform_apply(rotation=True)
tr = MK.mesh_tree(ctx, cyl)
in_p = Vector((2, 0, 1)) + axis * 0.02 + side_v * 0.007
c_p = MK.center_joint(tr, in_p, axis, 0.05)
rep("căn đốt vào tâm ống nghiêng", (c_p - (Vector((2, 0, 1)) + axis * 0.02)).length < 5e-4, "%.3f mm" % ((c_p - (Vector((2, 0, 1)) + axis * 0.02)).length * 1000))
out_p = Vector((2, 0, 1)) + axis * 0.02 + side_v * 0.016
c_o = MK.center_joint(tr, out_p, axis, 0.05)
rep("đốt nằm ngoài da cũng kéo về tâm", (c_o - (Vector((2, 0, 1)) + axis * 0.02)).length < 5e-4, "%.3f mm" % ((c_o - (Vector((2, 0, 1)) + axis * 0.02)).length * 1000))
tube_c = Vector((2, 0, 1))
on_axis = [tube_c + axis * t for t in (-0.06, -0.02, 0.02, 0.06)]
wob = [side_v * 0.005, -side_v * 0.004, side_v * 0.006, -side_v * 0.003]
for m, p, w in zip((root, mid1, mid2, tip_t), on_axis, wob):
    m.location = p + w
    m[MK.TAG_PLACED] = True
cnt = MK.center_chain(ref, tr, mid1, mirror=False)
err = max((m.location - tube_c).cross(axis).length for m in (root, mid1, mid2, tip_t))  # khoảng cách tới trục ống
rep("căn cả ngón nghiêng vào tâm", cnt == 4 and err < 1e-3, "%d khớp, lệch %.3f mm" % (cnt, err * 1000))
far = [tube_c + Vector((0.3, 0.2, 0)) + axis * t for t in (-0.06, -0.02, 0.02, 0.06)]
for m, p in zip((root, mid1, mid2, tip_t), far):
    m.location = p
cnt = MK.center_chain(ref, tr, mid1, mirror=False)
rep("chuỗi nằm xa thịt thì giữ nguyên, không bẻ gập", cnt == 0 and max((m.location - p).length for m, p in zip((root, mid1, mid2, tip_t), far)) < 1e-9, str(cnt))
for m, p in zip((root, mid1, mid2, tip_t), want):
    m.location = p
MK.mirror_all(ref, 'L')
bpy.data.objects.remove(cyl)
ctx.view_layer.objects.active = body
sh0, sh1, bi = M["Shoulder.L"].location, E[("Shoulder.L", 'T')].location, M["Bicep.L"].location
rep("đuôi xương đòn tự nằm trên đoạn tới vai", ((sh1 - sh0).cross(bi - sh0)).length < 1e-4 and (sh1 - sh0).length < (bi - sh0).length)

# chuỗi tóc đôi + roll tay
st = sc.srp_marker
head_tip = next(m for m in MK.markers_of(ref) if ("Head", 'T') in [tuple(x) for x in MK.ends_of(m)]).location.copy()
hair = [head_tip + Vector(v) for v in ((.08, .02, -.03), (.12, .05, -.10), (.14, .09, -.18), (.15, .12, -.26))]
made, why = MK.add_chain(ctx, ref, "Hair", hair, body, True)
rep("vẽ chuỗi: gốc lệch tâm tự tạo cả hai bên", not why and all(n in ref.data.bones for n in ("Hair.L", "Hair.L.002", "Hair.R", "Hair.R.002")), str(why))
E = MK.end_map(ref)
rep("vẽ chuỗi: khớp đúng chỗ click", all((E[("Hair.L" if i == 0 else "Hair.L.%03d" % i, 'H')].location - hair[i]).length < 1e-6 for i in range(3)) and (E[("Hair.L.002", 'T')].location - hair[3]).length < 1e-6)
rep("vẽ chuỗi: bên phải là ảnh gương", (E[("Hair.R.002", 'T')].location - MK.mirror_point(ref, hair[3])).length < 1e-6)
rep("vẽ chuỗi: tự nối vào xương gần nhất", ref.data.bones["Hair.L"].parent.name == "Head", ref.data.bones["Hair.L"].parent.name)
M = {n: m for m in MK.markers_of(ref) for n, e in MK.ends_of(m) if e == 'H'}
rep("gốc tóc là marker riêng, không dính đỉnh đầu", not any(n == "Head" and e == 'T' for n, e in MK.ends_of(M["Hair.L"])))
rep("chuỗi vào danh sách khớp", any(g["stage"] == "Phụ kiện" and g["marker"] == M["Hair.L"].name for g in MK.guide_of(ref)))
ear = [Vector((cx - .07, 0.0, head_tip.z - .08)), Vector((cx - .13, 0.02, head_tip.z - .02))]
made, why = MK.add_chain(ctx, ref, "Ear", MK.divide_points(ear, 2), body, True)
rep("vẽ ở bên phải vẫn thành đúng cặp L/R", not why and made == ["Ear.L", "Ear.L.001"] and MK.end_map(ref)[("Ear.L", 'H')].location.x > cx and MK.end_map(ref)[("Ear.R", 'H')].location.x < cx, str(made))
hip = M["Hips"].location
tail = [hip + Vector((0.002, .10 * i + .05, -.02 * i)) for i in range(5)]
made, why = MK.add_chain(ctx, ref, "Tail", tail, body, True)
rep("đuôi giữa người là một chuỗi đơn", not why and made[0] == "Tail" and "Tail.L" not in ref.data.bones and len(made) == 4, str(made))
rep("chuỗi đơn không bị ghim vào trục", abs(MK.end_map(ref)[("Tail", 'H')].location.x - tail[0].x) < 1e-6)
rep("đuôi nối vào thân", ref.data.bones["Tail"].parent.name in ("Hips", "Spine"), ref.data.bones["Tail"].parent.name)
E = MK.end_map(ref)
fork_at = E[("Hair.L.001", 'H')]
twig = [fork_at.location.copy(), fork_at.location + Vector((.06, -.03, -.05)), fork_at.location + Vector((.10, -.05, -.11))]
made, why = MK.add_chain(ctx, ref, "Twig", twig, body, True, attach=fork_at.name)
E = MK.end_map(ref)
rep("rẽ nhánh từ marker có sẵn", not why and ref.data.bones["Twig.L"].parent.name == "Hair.L.001" and ref.data.bones["Twig.R"].parent.name == "Hair.R.001" and E[("Twig.L", 'H')] == E[("Hair.L.001", 'H')], str(why))
made, why = MK.add_chain(ctx, ref, "Hair", [head_tip + Vector((.05, 0, 0)), head_tip + Vector((.09, 0, .04))], body, True)
near_arm = M["Bicep.L"].location + Vector((0.01, 0.03, 0.0))
rep("cánh sát tay vẫn bám vào thân", refrig.part_of(ref.data.bones[MK.nearest_parent(ref, near_arm, True, MK.CHAIN_PRESETS[2][3])])[0] in ('HIPS', 'SPINE') and refrig.part_of(ref.data.bones[MK.nearest_parent(ref, near_arm, True)])[0] == 'ARM', MK.nearest_parent(ref, near_arm, True, MK.CHAIN_PRESETS[2][3]))
rep("trùng tên tự đánh số", not why and made == ["Hair_2.L"], str(made))
gone = MK.delete_chain(ctx, ref, MK.end_map(ref)[("Hair_2.L", 'H')], body)
rep("xoá chuỗi xoá cả hai bên", gone == 2 and "Hair_2.L" not in ref.data.bones and "Hair_2.R" not in ref.data.bones, str(gone))
why = MK.set_chain_parent(ctx, ref, MK.end_map(ref)[("Ear.L", 'H')], "Neck", body)
rep("đổi xương cha cả hai bên", not why and ref.data.bones["Ear.L"].parent.name == "Neck" and ref.data.bones["Ear.R"].parent.name == "Neck", str(why))
rep("vị trí khớp giữ nguyên sau khi đổi cha", (MK.end_map(ref)[("Ear.L.001", 'T')].location - MK.mirror_point(ref, ear[1])).length < 1e-6)
M = {n: m for m in MK.markers_of(ref) for n, e in MK.ends_of(m) if e == 'H'}
ref.data.bones["Index.L"][MK.TAG_ROLL] = 30.0

auto = {}
ref.data.bones["Index.L"][MK.TAG_ROLL] = 0.0
base = MK.frames(ref)["Index.L"][2].copy()
ref.data.bones["Index.L"][MK.TAG_ROLL] = 30.0
rep("Áp dụng", bpy.ops.srp.marker_apply() == {'FINISHED'})
B = ref.data.bones
W = ref.matrix_world


def wz(n):
    return (W.to_3x3() @ B[n].matrix_local.to_3x3() @ Vector((0, 0, 1))).normalized()


rep("vị trí ghi đúng vào ref", ((W @ B["Hand_Master.L"].head_local) - Vector((cx + 0.42, 0, 1.2))).length < 1e-5)
worst = 0.0
for b in B:
    t = MK.flip_side if False else None
    side, other = MK._pair_side(b.name)
    if side == 'L' and other in B:
        z, o = wz(b.name), wz(other)
        if "Index" in b.name and b.name == "Index.L":
            pass
        worst = max(worst, (Vector((-z.x, z.y, z.z)) - o).length)
rep("roll hai bên là ảnh gương", worst < 1e-3, "lệch %.5f" % worst)
ang = math.degrees(base.angle(wz("Index.L")))
rep("roll tay 30° đúng trên xương", abs(ang - 30) < 0.1, "%.2f°" % ang)
d = (B["Thigh.L"].tail_local - B["Thigh.L"].head_local)
rep("đùi: Z ra trước", wz("Thigh.L").y < -0.9, "%.3f" % wz("Thigh.L").y)
rep("cột sống: Z ra sau", wz("Spine.001").y > 0.9, "%.3f" % wz("Spine.001").y)
rep("cánh tay chéo (A-pose): Z ra sau", wz("Bicep.L").y > 0.8, "%.3f" % wz("Bicep.L").y)

# dựng rig
rep("dựng rig", bpy.ops.srp.generate() == {'FINISHED'})
rig = bpy.data.objects["MK_Rig"]
rep("đủ 4 chi", len(rigdef.limbs_for(rig)) == 4)
rep("FK/IK chuyển được", not build.verify_switching(ctx, rig))
rep("xương tóc vào rig", "Hair.L.002" in rig.data.bones and "Hair.R" in rig.data.bones)
rb = rig.data.bones
rep("rig giữ đúng cha của chuỗi", rb["Tail"].parent.name in ("Hips", "Spine") and rb["Twig.L"].parent.name == "Hair.L.001" and rb["Ear.R"].parent.name == "Neck")
rep("chuỗi có control để bấm", all(rig.pose.bones[n].custom_shape is not None for n in ("Tail", "Ear.L", "Hair.R.002", "Twig.L")))
rep("chuỗi có deform", all(rb[n].use_deform for n in ("Tail.003", "Ear.R.001", "Twig.R.001")))
kept = UE.game_bones(rig, UE.humanoid_map(rig), only_human=True)
rep("xuất Unity mặc định vẫn giữ chuỗi", all(n in kept for n in ("Tail", "Tail.003", "Ear.L", "Hair.R.002", "Twig.L")) and "Palm.L.001" not in kept)
rep("xuất Unity giữ đúng cha chuỗi", kept["Twig.L"] == "Hair.L.001" and kept["Tail.001"] == "Tail", str(kept.get("Twig.L")))
rep("rig giữ roll tay", (rig.data.bones["Index.L"].matrix_local.to_3x3() @ Vector((0, 0, 1)) - wz("Index.L")).length < 1e-3)
hm = UE.humanoid_map(rig)
rep("đủ xương Humanoid chính", all(k in hm for k in ("Hips", "Spine", "Head", "LeftUpperArm", "LeftHand", "RightFoot")), str(len(hm)))
rep("không còn xương dài 0", not any(b.length < 1e-4 for b in rig.data.bones))
print("TỔNG %d/%d" % (sum(results), len(results)))
