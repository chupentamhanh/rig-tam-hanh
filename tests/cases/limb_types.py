"""Kiểu chân (người / chó / dê) và số ngón tay. Dựng từ bộ ref trên mesh tạm. argv: -- outdir"""
import bpy, sys, os, math, json
import addon_utils
from mathutils import Matrix, Vector

OUT = sys.argv[sys.argv.index("--") + 1]
os.makedirs(OUT, exist_ok=True)
addon_utils.enable("rig_tam_hanh", default_set=False)
from rig_tam_hanh import refrig, generate, build, snap, rigdef, retarget as RT, unityexport as UE, refsync

ctx = bpy.context
sc = ctx.scene
results = []


def rep(name, ok, detail=""):
    results.append(bool(ok))
    print("[%s] %s %s" % ("ĐẠT" if ok else "HỎNG", name, detail))


bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0.9))
body = ctx.object
body.name = "Body"
body.scale = (0.5, 0.3, 1.8)
bpy.ops.object.transform_apply(scale=True)


def make(name, leg, fingers, thumb=True):
    ref = refrig.ensure_ref(ctx, name + "_Ref", body)
    refrig.add_part(ctx, ref, 'HIPS', mesh_object=body)
    refrig.add_part(ctx, ref, 'SPINE', socket="Hips", mesh_object=body)
    for side in 'LR':
        refrig.add_part(ctx, ref, 'ARM', side=side, inst=1, socket="Spine.003", mesh_object=body)
        refrig.add_part(ctx, ref, 'HAND', side=side, socket=refrig.bone_name("Hand_Master", 1, side),
                        mesh_object=body, fingers=fingers, thumb=thumb)
        refrig.add_part(ctx, ref, 'LEG', side=side, inst=1, socket="Hips", mesh_object=body, leg_type=leg)
    plan, err = generate.build_plan(generate.snapshot(ref), {
        k: {b: g.name for b, g in v.items()} for k, v in refrig.parts_in(ref).items()})
    assert err is None, err
    rig = generate.build_skeleton(ctx, plan, name)
    build.apply_logic(ctx, rig)
    for l in rigdef.limbs_for(rig):
        snap.calibrate_pole(ctx, rig, l)
    return ref, rig


def head(rig, n):
    ctx.view_layer.update()
    return (rig.matrix_world @ rig.evaluated_get(ctx.evaluated_depsgraph_get()).pose.bones[n].head).copy()


def rot(rig, n):
    return rig.evaluated_get(ctx.evaluated_depsgraph_get()).pose.bones[n].matrix.to_quaternion()


def reset(rig):
    for pb in rig.pose.bones:
        pb.matrix_basis = Matrix()
    ctx.view_layer.update()


def rest_err(rig):
    reset(rig)
    ev = rig.evaluated_get(ctx.evaluated_depsgraph_get())
    worst = 0.0
    for b in rig.data.bones:
        if b.use_deform:
            worst = max(worst, (ev.pose.bones[b.name].matrix.translation - b.matrix_local.translation).length,
                        max((ev.pose.bones[b.name].matrix.col[i].xyz - b.matrix_local.col[i].xyz).length for i in range(3)) * b.length)
    return worst * 1000


# ---- số ngón
for n, thumb, want in ((5, True, {"Thumb", "Index", "Middle", "Ring", "Pinky"}), (4, True, {"Thumb", "Index", "Middle", "Ring"}),
                       (3, True, {"Thumb", "Index", "Middle"}), (3, False, {"Index", "Middle", "Ring"}), (1, True, {"Index"})):
    rows = {r[0] for r in refrig.hand_layout(n, thumb)}
    got = {x for x in rows if not x.startswith("Palm") and "." not in x}
    rep("bàn tay %d ngón%s" % (n, "" if thumb else " không ngón cái"),
        got == want and len(rows) == 4 * len(want), str(sorted(got)))
a = {r[0]: r for r in refrig.hand_layout(3, False)}
mid = (a["Index"][1][1] + a["Ring"][1][1]) / 2
rep("3 ngón giãn đều trên bàn tay", abs(a["Middle"][1][1] - mid) < 0.02 and a["Index"][1][1] > 0.2 and a["Ring"][1][1] < -0.1)

results_rigs = {}
for leg, fingers in (('HUMAN', 5), ('PAW', 4), ('HOOF', 3)):
    ref, rig = make("Rig_" + leg, leg, fingers)
    results_rigs[leg] = (ref, rig)
    limbs = rigdef.limbs_for(rig)
    L = next(l for l in limbs if l.kind == 'LEG' and l.side == 'L')
    rep("%s: đủ 4 chi" % leg, len(limbs) == 4, str(len(limbs)))
    rep("%s: rest không lệch" % leg, rest_err(rig) < 0.1, "%.4f mm" % rest_err(rig))
    n = sum(1 for f in ("Thumb", "Index", "Middle", "Ring", "Pinky") if rigdef.bone_name(f, 1, 'L') in rig.data.bones)
    rep("%s: rig có %d ngón" % (leg, fingers), n == fingers, str(n))
    rep("%s: kiểu chân ghi trên rig" % leg, L.leg_type(rig) == leg, L.leg_type(rig))
    if leg == 'HUMAN':
        continue

    B = rig.data.bones
    rep("%s: control IK ở chỗ chạm đất" % leg, (B[L.ctrl].head_local - B[L.toe].head_local).length < 1e-5)
    rep("%s: gối ra trước, hock ra sau" % leg,
        B[L.deform[1]].head_local.y < B[L.deform[0]].head_local.y < B[L.deform[2]].head_local.y)
    # kéo control: chân theo, hock theo
    reset(rig)
    L.set_switch(rig, 1.0)
    h0 = head(rig, L.deform[2])
    t0 = head(rig, L.toe)
    rig.pose.bones[L.ctrl].location = rig.pose.bones[L.ctrl].bone.matrix_local.to_3x3().inverted() @ Vector((0, -0.08, 0.10))
    d = head(rig, L.toe) - t0
    rep("%s: kéo control thì bàn chân theo" % leg, (d - Vector((0, -0.08, 0.10))).length < 1e-3, "%.3f mm" % ((d - Vector((0, -0.08, 0.10))).length * 1000))
    rep("%s: IK tới đúng hock" % leg, (head(rig, L.deform[2]) - h0 - Vector((0, -0.08, 0.10))).length < 2e-3)
    # nhấc hock: xoay Ball, móng đứng yên trên đất
    reset(rig)
    L.set_switch(rig, 1.0)
    ball = L.roll[2]
    q0, p0, hk0 = rot(rig, L.toe), head(rig, L.toe), head(rig, L.deform[2])
    pb = rig.pose.bones[ball]
    pb.rotation_quaternion = (Matrix.Rotation(math.radians(25), 3, pb.bone.matrix_local.to_3x3().inverted() @ Vector((1, 0, 0)))).to_quaternion()
    ctx.view_layer.update()
    turned = math.degrees(q0.rotation_difference(rot(rig, L.toe)).angle)
    rep("%s: nhấc hock (Ball 25°) thì hock di chuyển" % leg, (head(rig, L.deform[2]) - hk0).length > 0.01,
        "%.1f mm" % ((head(rig, L.deform[2]) - hk0).length * 1000))
    rep("%s: bàn / móng giữ yên trên đất" % leg, turned < 0.5 and (head(rig, L.toe) - p0).length < 1e-3,
        "xoay %.2f°, dịch %.2f mm" % (turned, (head(rig, L.toe) - p0).length * 1000))
    # FK -> IK khớp
    reset(rig)
    L.set_switch(rig, 0.0)
    for name, ax, deg in ((L.fk[0], 'X', 30), (L.fk[1], 'X', -35), (L.fk[2], 'X', 20)):
        rig.pose.bones[name].rotation_quaternion = Matrix.Rotation(math.radians(deg), 3, ax).to_quaternion()
    ctx.view_layer.update()
    want = {n: (head(rig, n), rot(rig, n)) for n in L.deform + (L.toe,)}
    snap.snap_ik_to_fk(ctx, rig, L)
    L.set_switch(rig, 1.0)
    ctx.view_layer.update()
    dp = max((head(rig, n) - want[n][0]).length for n in want) * 1000
    da = max(math.degrees(want[n][1].rotation_difference(rot(rig, n)).angle) for n in (L.deform[2], L.toe))
    rep("%s: snap IK theo FK khớp" % leg, dp < 1.0 and da < 1.0, "lệch %.3f mm, %.3f°" % (dp, da))
    reset(rig)
    L.set_switch(rig, 1.0)

# ---- dựng lại bộ ref từ rig giữ kiểu chân
rig = results_rigs['HOOF'][1]
r2, _n = refsync.ref_from_rig(ctx, rig, "Hoof_Again")
rep("dựng lại ref từ rig: giữ kiểu chân", r2.data.bones["Thigh.L"].get(refrig.TAG_LEG) == 'HOOF'
    and "Pinky.L" not in r2.data.bones and "ToeMch.L" not in r2.data.bones)

# ---- Humanoid + xuất
m = UE.humanoid_map(rig)
rep("Humanoid: Foot = đoạn bàn, Toes = móng", m.get("LeftFoot") == "Foot.L" and m.get("LeftToes") == "Toe.L")

# ---- retarget từ chân người sang chân dê: giữ dáng chữ Z
src = results_rigs['HUMAN'][1]
act = bpy.data.actions.new("Step")
src.animation_data_create().action = act
reset(src)
LS = next(l for l in rigdef.limbs_for(src) if l.kind == 'LEG' and l.side == 'L')
LS.set_switch(src, 0.0)
pb = src.pose.bones[LS.fk[0]]
for f, deg in ((1, 0), (12, 35)):
    pb.rotation_quaternion = Matrix.Rotation(math.radians(deg), 3, 'X').to_quaternion()
    pb.keyframe_insert("rotation_quaternion", frame=f)
reset(rig)
new, info = RT.retarget(ctx, src, act, rig, name="Step_Hoof")
sc.frame_set(1)
LT = next(l for l in rigdef.limbs_for(rig) if l.kind == 'LEG' and l.side == 'L')
b = rig.data.bones
kn = head(rig, LT.deform[1]) - (rig.matrix_world @ b[LT.deform[1]].head_local)
hk = head(rig, LT.deform[2]) - (rig.matrix_world @ b[LT.deform[2]].head_local)
rep("retarget frame đầu: chân dê giữ nguyên dáng nghỉ", kn.length < 2e-3 and hk.length < 2e-3,
    "gối %.2f mm, hock %.2f mm" % (kn.length * 1000, hk.length * 1000))
sc.frame_set(12)
rep("retarget: đùi chuyển động", (head(rig, LT.deform[2]) - (rig.matrix_world @ b[LT.deform[2]].head_local)).length > 0.02)
print("TỔNG %d/%d" % (sum(results), len(results)))
