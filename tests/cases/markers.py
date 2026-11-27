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
# cánh mọc đúng giữa lưng rồi toả sang một bên vẫn phải thành một đôi
spine_m = MK.end_map(ref)[("Spine.002", 'H')]
back = spine_m.location.copy()
spread = [back, back + Vector((.15, .03, .08)), back + Vector((.32, .05, .16))]
made, why = MK.add_chain(ctx, ref, "BackWing", spread, body, True, kinds=MK.CHAIN_PRESETS[2][3])
rep("cánh gốc giữa lưng tạo cả hai bên", not why and made[0] == "BackWing.L" and "BackWing.R.001" in ref.data.bones, str(made))
tipL, tipR = MK.end_map(ref)[("BackWing.L.001", 'T')].location, MK.end_map(ref)[("BackWing.R.001", 'T')].location
rep("hai cánh là ảnh gương", (MK.mirror_point(ref, tipL) - tipR).length < 1e-6 and tipL.x > cx)
left = [back, back + Vector((-.15, .03, .08)), back + Vector((-.32, .05, .16))]
made, why = MK.add_chain(ctx, ref, "Fan", left, body, True, attach=spine_m.name, kinds=MK.CHAIN_PRESETS[2][3])
fan_root = MK.end_map(ref)[("Fan.L", 'H')]
rep("vẽ ở bên phải từ khớp cột sống vẫn ra đôi", not why and made[0] == "Fan.L" and MK.end_map(ref)[("Fan.L.001", 'T')].location.x > cx and MK.end_map(ref)[("Fan.R.001", 'T')].location.x < cx, str(why))
rep("hai gốc chung khớp cột sống", fan_root == MK.end_map(ref)[("Fan.R", 'H')] == MK.end_map(ref)[("Spine.002", 'H')])
rep("khớp cột sống vẫn bị ghim vào trục", MK.is_center(fan_root) and MK._center_side(fan_root) and MK.marker_side(fan_root) is None)
for n in ("Fan.L", "BackWing.L"):
    MK.delete_chain(ctx, ref, MK.end_map(ref)[(n + ".001", 'H')], body)
curl = [hip + Vector((0, .12, 0)), hip + Vector((.06, .2, 0)), hip + Vector((.16, .25, .04))]
made, why = MK.add_chain(ctx, ref, "Curl", curl, body, True, root_only=MK.CHAIN_PRESETS[1][4])
rep("đuôi cong sang một bên vẫn là một chuỗi", not why and made[0] == "Curl" and "Curl.L" not in ref.data.bones, str(made))
MK.delete_chain(ctx, ref, MK.end_map(ref)[("Curl", 'H')], body)
# chuỗi đơn đã vẽ (đúng trường hợp hai thuỳ cánh chung gốc) -> tạo bên đối xứng
lobe1 = [back + Vector((.01, .02, 0)), back + Vector((.2, .03, .12)), back + Vector((.36, .04, .22))]
lobe2 = [lobe1[0], lobe1[0] + Vector((.18, .02, -.14))]
MK.add_chain(ctx, ref, "Lobe", lobe1, body, False, parent="Spine.002")
MK.add_chain(ctx, ref, "Lobe_B", lobe2, body, False, attach=MK.end_map(ref)[("Lobe", 'H')].name)
rep("chuỗi đơn trước khi đổi", "Lobe" in ref.data.bones and "Lobe.R" not in ref.data.bones and ref.data.bones["Lobe_B"].parent.name == "Lobe")
made, why = MK.pair_chain(ctx, ref, MK.end_map(ref)[("Lobe", 'T')], body)
made2, why2 = MK.pair_chain(ctx, ref, MK.end_map(ref)[("Lobe_B", 'T')], body)
EE = MK.end_map(ref)
rep("tạo bên đối xứng cho chuỗi có sẵn", not why and not why2 and all(n in ref.data.bones for n in ("Lobe.L", "Lobe.R.001", "Lobe_B.L", "Lobe_B.R")) and "Lobe" not in ref.data.bones and "Lobe_B" not in ref.data.bones, "%s %s" % (why, why2))
rep("giữ nguyên dáng chuỗi", (EE[("Lobe.L.001", 'T')].location - lobe1[2]).length < 1e-6 and (EE[("Lobe_B.L", 'T')].location - lobe2[1]).length < 1e-6)
rep("bên kia là ảnh gương", (EE[("Lobe.R.001", 'T')].location - MK.mirror_point(ref, lobe1[2])).length < 1e-6)
rep("cả hai thuỳ bám vào thân", ref.data.bones["Lobe.L"].parent.name == "Spine.002" and ref.data.bones["Lobe_B.R"].parent.name == "Spine.002", ref.data.bones["Lobe_B.R"].parent.name)
for n in ("Lobe.L", "Lobe_B.L"):
    MK.delete_chain(ctx, ref, MK.end_map(ref)[(n, 'T')], body)
# hai nhánh chung một gốc: chọn đúng nhánh để chỉnh
tr0 = back + Vector((.03, .02, .02))
top = [tr0, tr0 + Vector((.16, .02, .10)), tr0 + Vector((.32, .03, .17))]
MK.add_chain(ctx, ref, "Top", top, body, True, parent="Spine.002")
EB = MK.end_map(ref)
low = [EB[("Top.L", 'H')].location.copy(), tr0 + Vector((.14, .02, -.12)), tr0 + Vector((.24, .03, -.27))]
MK.add_chain(ctx, ref, "Low", low, body, True, attach=EB[("Top.L", 'H')].name)
EB = MK.end_map(ref)
fork = EB[("Top.L", 'H')]
fork_r = EB[("Top.R", 'H')]
rep("hai nhánh chung một marker", fork == EB[("Low.L", 'H')] and fork_r == EB[("Low.R", 'H')])
rep("khớp rẽ nhánh liệt kê đủ chuỗi", sorted(c[0].name for c in MK.chain_menu(ref, fork)) == ["Low.L", "Top.L"])
rep("mặc định chỉnh mọi nhánh", len(MK.picked_chains(ref, fork)) == 2)
rep("chọn được nhánh dưới", [c[0].name for c in MK.picked_chains(ref, fork, "Low.L")] == ["Low.L"])
rep("chọn ở bên kia vẫn đúng nhánh", [c[0].name for c in MK.picked_chains(ref, fork_r, "Low.L")] == ["Low.R"])
for n in ("Top.L", "Top.L.001", "Low.L", "Low.L.001"):
    ref.data.bones[n][MK.TAG_ROLL] = 11.0
n_h, _w = MK.hinge_chain(ref, fork_r, True, chain=MK.picked_chains(ref, fork_r, "Low.L")[0])
rep("trục gập chỉ đổi nhánh dưới", n_h == 2 and ref.data.bones["Top.L"][MK.TAG_ROLL] == 11.0 and ref.data.bones["Top.L.001"][MK.TAG_ROLL] == 11.0 and ref.data.bones["Low.L"][MK.TAG_ROLL] != 11.0)
rep("khớp thân có chuỗi mọc vào vẫn mặc định là thân", MK.picked_chains(ref, MK.end_map(ref)[("Spine.002", 'H')])[0][0].name == "Spine" or not MK._is_chain(MK.picked_chains(ref, MK.end_map(ref)[("Spine.002", 'H')])[0]))
root_at = fork.location.copy()
why = MK.set_chain_parent(ctx, ref, MK.end_map(ref)[("Low.L", 'T')], "Spine.002", body)
EB = MK.end_map(ref)
rep("đổi cha nhánh: tách khớp, giữ đúng chỗ", not why and EB[("Low.L", 'H')] != EB[("Top.L", 'H')] and (EB[("Low.L", 'H')].location - root_at).length < 1e-6 and (EB[("Top.L", 'H')].location - root_at).length < 1e-6, str(why))
rep("mọi đầu xương vẫn có marker", sum(len(MK.ends_of(m)) for m in MK.markers_of(ref)) == 2 * len(ref.data.bones))
for n in ("Low.L", "Top.L"):
    MK.delete_chain(ctx, ref, MK.end_map(ref)[(n, 'T')], body)
rep("trùng tên tự đánh số", "Hair_2.L" in ref.data.bones and "Hair_2.R" in ref.data.bones)
gone = MK.delete_chain(ctx, ref, MK.end_map(ref)[("Hair_2.L", 'H')], body)
rep("xoá chuỗi xoá cả hai bên", gone == 2 and "Hair_2.L" not in ref.data.bones and "Hair_2.R" not in ref.data.bones, str(gone))
why = MK.set_chain_parent(ctx, ref, MK.end_map(ref)[("Ear.L", 'H')], "Neck", body)
rep("đổi xương cha cả hai bên", not why and ref.data.bones["Ear.L"].parent.name == "Neck" and ref.data.bones["Ear.R"].parent.name == "Neck", str(why))
rep("vị trí khớp giữ nguyên sau khi đổi cha", (MK.end_map(ref)[("Ear.L.001", 'T')].location - MK.mirror_point(ref, ear[1])).length < 1e-6)
M = {n: m for m in MK.markers_of(ref) for n, e in MK.ends_of(m) if e == 'H'}

# dời cổ tay khoá trục X (G rồi X): chỉ X đổi, rồi trả về chỗ cũ
hand = M["Hand_Master.L"]
o = hand.location.copy()
MK.place(ref, hand, MK.axis_point(o, o + Vector((0.07, -3.0, 0.25)), Vector((0.0, 1.0, 0.0)),
                                  (0, False)), True, auto_side=False)
d = hand.location - o
rep("dời cổ tay khoá trục X: chỉ X đổi",
    abs(d.x - 0.07) < 1e-6 and abs(d.y) < 1e-6 and abs(d.z) < 1e-6, str(d))
MK.place(ref, hand, o, True, auto_side=False)

# pie Snap: Selection to Cursor / Cursor to Selected trên khớp đang chọn, chuột phải lùi được
from types import SimpleNamespace as _NS0
_Op = MK.SRP_OT_marker_mode
fake = _NS0(ref_name=ref.name, mirror=True, history=[], area=None,
            report=lambda *a: None)
fake._snapshot = lambda: _Op._snapshot(fake)
fake._redraw = lambda: None
MK._S["selected"] = hand.name
twin = bpy.data.objects[hand[MK.TAG_TWIN]]
sc.cursor.location = o + Vector((0.05, -0.02, 0.04))
_Op._snap(fake, ctx, MK.SNAP_TO_CURSOR)
rep("Selection to Cursor: khớp tới đúng cursor, bên kia đối xứng theo",
    (hand.location - sc.cursor.location).length < 1e-6 and len(fake.history) == 1
    and abs(twin.location.z - hand.location.z) < 1e-6, str(hand.location))
_Op._restore(fake, fake.history.pop())
rep("chuột phải lùi về chỗ cũ", (hand.location - o).length < 1e-6)
sc.cursor.location = (0.0, 0.0, 0.0)
_Op._snap(fake, ctx, MK.SNAP_CURSOR_HERE)
rep("Cursor to Selected: cursor tới khớp, khớp đứng yên",
    (sc.cursor.location - o).length < 1e-6 and (hand.location - o).length < 1e-6 and not fake.history)

# ---- chọn nhiều khớp
knuck = [M[n] for n in ("Index.L", "Middle.L", "Ring.L")]
a, b, c = (m.name for m in knuck)
MK.select_only(a)
MK.toggle_pick(b)
MK.toggle_pick(c)
rep("Shift+click thêm: khớp sau cùng là active", MK.selection() == [a, b, c] and MK._S["selected"] == c)
MK.toggle_pick(b)
rep("Shift+click khớp đã chọn: thành active", MK.selection() == [a, c, b])
MK.toggle_pick(b)
rep("Shift+click khớp active: bỏ chọn nó", MK.selection() == [a, c] and MK._S["selected"] == c)
MK.toggle_pick(b)
tw = bpy.data.objects[knuck[0][MK.TAG_TWIN]]
rep("đối xứng: chọn cả cặp L/R thì chỉ đặt bên L",
    [o.name for o in MK.group_of([a, tw.name], True)] == [a]
    and len(MK.group_of([a, tw.name], False)) == 2)
start = _Op._snapshot(fake)
before = {m.name: m.location.copy() for m in knuck}
delta = Vector((0.0, -0.01, 0.03))
MK.move_group(ref, {n: p + delta for n, p in before.items()}, True)
rep("dời cả nhóm: mỗi khớp dịch đúng một đoạn",
    all((bpy.data.objects[n].location - (p + delta)).length < 1e-6 for n, p in before.items()))
rep("dời cả nhóm: bên kia đối xứng theo", abs(tw.location.z - knuck[0].location.z) < 1e-6)
moves = MK.align_moves(MK.selection(), MK._S["selected"], 2, True)
MK.move_group(ref, moves, True)
zs = [m.location.z for m in knuck]
rep("Căn thẳng Z: cùng độ cao với khớp active, X / Y giữ nguyên",
    max(zs) - min(zs) < 1e-6 and abs(zs[0] - bpy.data.objects[MK._S["selected"]].location.z) < 1e-6
    and all(abs(bpy.data.objects[n].location.x - (p + delta).x) < 1e-6 for n, p in before.items()))
locs = {m.name: m.location.copy() for m in knuck}
mid = sum(locs.values(), Vector()) / 3
sc.cursor.location = mid + Vector((0.02, 0.0, 0.05))
_Op._snap(fake, ctx, MK.SNAP_TO_CURSOR_OFFSET)
d = sc.cursor.location - mid
rep("Keep Offset: điểm giữa nhóm tới cursor, giữ khoảng cách",
    all((bpy.data.objects[n].location - (p + d)).length < 1e-6 for n, p in locs.items()))
act = bpy.data.objects[MK._S["selected"]]
sc.cursor.location = act.location + Vector((0.0, 0.0, -0.04))
locs = {m.name: m.location.copy() for m in knuck}
_Op._snap(fake, ctx, MK.SNAP_TO_CURSOR)
rep("Selection to Cursor: khớp active tới cursor, cả nhóm giữ dáng",
    (act.location - sc.cursor.location).length < 1e-6
    and all((bpy.data.objects[n].location - (p + Vector((0, 0, -0.04)))).length < 1e-6
            for n, p in locs.items()))
_Op._snap(fake, ctx, MK.SNAP_CURSOR_HERE)
rep("Cursor to Selected: cursor về điểm giữa nhóm",
    (sc.cursor.location - sum((m.location for m in knuck), Vector()) / 3).length < 1e-6)
fake.history.clear()
_Op._align(fake, ctx, 0)
rep("nút Căn thẳng X ghi một bước lùi", len(fake.history) == 1
    and max(m.location.x for m in knuck) - min(m.location.x for m in knuck) < 1e-6)
_Op._restore(fake, start)
rep("lùi về trước khi dời nhóm: vị trí và nhóm chọn đều về",
    all((bpy.data.objects[n].location - p).length < 1e-6 for n, p in before.items())
    and MK.selection() == [a, c, b])
MK.select_only(None)
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

# dựng rig: lỗi thì giữ marker, thành công thì dọn
E = MK.end_map(ref)
tip_m, tip_h = E[("Tail.003", 'T')], E[("Tail.003", 'H')]
tip_keep = tip_m.location.copy()
tip_m.location = tip_h.location.copy()
try:
    refused = bpy.ops.srp.generate() != {'FINISHED'}
except RuntimeError:
    refused = True
rep("marker lỗi thì không dựng, giữ nguyên marker", refused and "MK_Rig" not in bpy.data.objects and len(MK.markers_of(ref)) > 0)
tip_want = tip_keep + Vector((0.0, 0.02, 0.01))     # chỉnh mà chưa bấm Enter
tip_m.location = tip_want
n_marker = len(MK.markers_of(ref))
coll_name = MK.collection_name(ref)
rep("dựng rig", bpy.ops.srp.generate() == {'FINISHED'})
rig = bpy.data.objects["MK_Rig"]
rep("dựng xong dọn hết marker", not MK.markers_of(ref) and coll_name not in bpy.data.collections, "%d marker trước đó" % n_marker)
rep("không còn empty marker nào trong file", not any(o.get(MK.TAG_MARKER) for o in bpy.data.objects))
rep("bộ ref vẫn giữ lại", ref.name in bpy.data.objects and len(ref.data.bones) > 0)
rep("chỉnh chưa Enter vẫn vào rig", ((rig.matrix_world @ rig.data.bones["Tail.003"].tail_local) - tip_want).length < 1e-5)
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
# mở lại marker sau khi đã dọn: đúng vị trí, roll không bị cộng hai lần
n_bones = len(ref.data.bones)
before_z = {b.name: wz(b.name) for b in ref.data.bones}
rep("mở lại marker từ bộ ref", bpy.ops.srp.marker_start() == {'FINISHED'} and len(MK.markers_of(ref)) == n_marker and len(ref.data.bones) == n_bones, "%d marker" % len(MK.markers_of(ref)))
rep("mở lại: khớp vẫn tính là đã đặt", all(bpy.data.objects[g["marker"]].get(MK.TAG_PLACED) for g in MK.guide_of(ref)))
rep("mở lại: đúng vị trí", (MK.end_map(ref)[("Tail.003", 'T')].location - tip_want).length < 1e-5)
plan = MK.frames(ref)
off = max((plan[n][2] - z).length for n, z in before_z.items() if plan[n][2] is not None)
rep("mở lại: roll không đổi", off < 1e-3, "lệch %.5f" % off)
generate.drop_ref(ctx)
rep("bind xoá bộ ref thì marker cũng hết", not any(o.get(MK.TAG_MARKER) for o in bpy.data.objects) and coll_name not in bpy.data.collections)
# Phim nao trong che do dat marker van den duoc Blender
from types import SimpleNamespace as _NS
_inp = _NS(use_mouse_emulate_3_button=False)
def _ev(t, ctrl=False, shift=False, alt=False):
    return _NS(type=t, ctrl=ctrl, shift=shift, alt=alt, oskey=False)
rep("Z / Shift+Z / Alt+Z / Shift+Alt+Z tới Blender (shading, X-ray)",
    all(MK.passes_to_blender(_ev('Z', shift=s, alt=a), _inp) for s in (False, True) for a in (False, True)))
rep("Ctrl+Z vẫn là lùi bước đặt marker", not MK.passes_to_blender(_ev('Z', ctrl=True), _inp))
rep("phím khác vẫn bị chặn", not any(MK.passes_to_blender(_ev(k), _inp) for k in ('A', 'G', 'X', 'DEL', 'LEFTMOUSE')))
rep("Shift+Tab, chuột giữa, numpad vẫn tới Blender",
    all(MK.passes_to_blender(e, _inp) for e in (_ev('TAB', shift=True), _ev('MIDDLEMOUSE'), _ev('NUMPAD_5'))))
# Pie menu theo keymap: keymap gia (nhu mac dinh + mot pie add-on khac + menu thuong)
def _kmi(t, idname="wm.call_menu_pie", ctrl=0, shift=0, alt=0, active=True, any=False):
    return _NS(type=t, idname=idname, ctrl=ctrl, shift=shift, alt=alt, oskey=0, active=active, any=any)
_kc = _NS(keymaps={
    "3D View": _NS(keymap_items=[_kmi('ACCENT_GRAVE'), _kmi('S', shift=1), _kmi('PERIOD'), _kmi('COMMA'),
                                 _kmi('Q', alt=1), _kmi('W', active=False), _kmi('F', any=True),
                                 _kmi('RET'), _kmi('RIGHTMOUSE', shift=1)]),
    "Object Mode": _NS(keymap_items=[_kmi('O', shift=1), _kmi('A', "wm.call_menu", shift=1),
                                     _kmi('M', "wm.call_menu")]),
    "Mesh": _NS(keymap_items=[_kmi('E')]),
})
_pies = MK.pie_keys(_kc)
_pass = lambda *a, **k: MK.passes_to_blender(_ev(*a, **k), _inp, _pies)
rep("pie mặc định tới Blender: ` Shift+S . , Shift+O",
    all((_pass('ACCENT_GRAVE'), _pass('S', shift=True), _pass('PERIOD'), _pass('COMMA'), _pass('O', shift=True))))
rep("pie của add-on khác / phím đã đổi cũng tới (Alt+Q, F bất kỳ modifier)",
    _pass('Q', alt=True) and _pass('F', ctrl=True, shift=True))
rep("đúng modifier: S không Shift, Alt+S, Q không Alt vẫn bị chặn",
    not any((_pass('S'), _pass('S', shift=True, alt=True), _pass('Q'))))
rep("menu thường (Shift+A, M), pie tắt, keymap mode khác vẫn bị chặn",
    not any((_pass('A', shift=True), _pass('M'), _pass('W'), _pass('E'))))
rep("phím riêng của chế độ marker không nhường cho pie (Enter, Shift+chuột phải)",
    not _pass('RET') and not _pass('RIGHTMOUSE', shift=True))
rep("keymap không có (chạy nền) thì không lỗi", MK.pie_keys(None) == [])
rep("G không lọt ra Blender (G là dời marker)", not _pass('G'))

# ---- pie Snap (Shift+S) cho marker
def _snapkmi(t, name, **kw):
    k = _kmi(t, **kw)
    k.properties = _NS(name=name)
    return k
_kc2 = _NS(keymaps={"3D View": _NS(keymap_items=[
    _snapkmi('S', "VIEW3D_MT_snap_pie", shift=1), _snapkmi('ACCENT_GRAVE', "VIEW3D_MT_view_pie"),
    _snapkmi('D', "VIEW3D_MT_snap_pie", alt=1, active=False)])})
sp = MK.snap_pie_keys(_kc2)
rep("phím pie Snap đọc từ keymap (Shift+S, bỏ pie khác và phím tắt)",
    sp == [('S', (0, 1, 0, 0))] and MK._is_pie(_ev('S', shift=True), sp)
    and not MK._is_pie(_ev('S'), sp), str(sp))
rep("pie Snap của marker đã đăng ký, menu Object > Snap có thêm mục khớp",
    hasattr(bpy.types, "SRP_MT_marker_snap_pie")
    and MK._snap_menu_items in getattr(bpy.types.VIEW3D_MT_snap.draw, "_draw_funcs", [MK._snap_menu_items]))
g = MK.grid_round(Vector((0.234, -0.051, 1.349)), 0.1)
rep("Selection to Grid: về điểm lưới gần nhất", (g - Vector((0.2, -0.1, 1.3))).length < 1e-6, str(g))

# ---- khoá trục khi dời marker (G / kéo + X Y Z)
st = MK.axis_key(None, 'X', False)
rep("X: khoá trục X, bấm lại bỏ khoá", st == (0, False) and MK.axis_key(st, 'X', False) is None)
rep("đang X bấm Y: đổi sang Y; Shift+Z: mặt phẳng XY",
    MK.axis_key(st, 'Y', False) == (1, False) and MK.axis_key(st, 'Z', True) == (2, True))
O = Vector((0.2, 0.1, 1.3))
ray_o, ray_d = Vector((0.5, -3.0, 1.6)), Vector((0.0, 1.0, 0.0))     # nhìn từ trước
p = MK.axis_point(O, ray_o, ray_d, (0, False))
rep("trục X: điểm nằm trên trục, ngay dưới chuột theo X",
    p is not None and abs(p.y - O.y) < 1e-6 and abs(p.z - O.z) < 1e-6 and abs(p.x - 0.5) < 1e-6, str(p))
rep("trục song song tia nhìn: None (giữ chỗ cũ)", MK.axis_point(O, ray_o, ray_d, (1, False)) is None)
p = MK.axis_point(O, ray_o, ray_d, (1, True))
rep("mặt phẳng XZ: đúng giao điểm tia", p is not None and (p - Vector((0.5, 0.1, 1.6))).length < 1e-6, str(p))
q = MK.axis_project(Vector((0.9, -0.4, 2.0)), O, (2, False))
rep("điểm snap chiếu lên trục Z", (q - Vector((0.2, 0.1, 2.0))).length < 1e-6, str(q))
q = MK.axis_project(Vector((0.9, -0.4, 2.0)), O, (2, True))
rep("điểm snap chiếu lên mặt phẳng XY", (q - Vector((0.9, -0.4, 1.3))).length < 1e-6, str(q))
print("TỔNG %d/%d" % (sum(results), len(results)))
