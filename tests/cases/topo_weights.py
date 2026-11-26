"""Weight theo lưới (topoweights). Fixture kid_live.blend (weight automatic, chưa vẽ tay)."""
import bpy
import addon_utils
import numpy as np

addon_utils.enable("rig_tam_hanh", default_set=False)
from rig_tam_hanh import cloth, posekey, topoweights as TW, weightauto as WA, weightfence as WF

ctx = bpy.context
rig = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
body = ctx.scene.srp_generate.target_mesh
ctx.view_layer.objects.active = rig
results = []


def rep(name, ok, detail=""):
    results.append(bool(ok))
    print("[%s] %s %s" % ("ĐẠT" if ok else "HỎNG", name, detail))


lay = WF.Layout(rig)
R = WF.regions_for(body, rig, lay)
face = posekey.face_bones(rig) or set()
vg = body.vertex_groups
before_face = [{vg[g.group].name: g.weight for g in v.groups if vg[g.group].name in face}
               for v in body.data.vertices]
s0 = WA.score(body, rig, lay, R)

# vài vertex "vẽ tay" phải giữ y nguyên
hand = [i for i in range(0, len(R), 97)][:20]
body[cloth.HAND_KEY] = hand
hand_rows = {i: r for i, r in enumerate(cloth._rows_of(body, exact=True)) if i in hand}

names, W, info = TW.compute(body, rig)
big = max(info["islands"], key=lambda t: t[0])
rep("đảo thân chứa xương tay, chân, sống",
    {"Thigh.L", "Shin.R", "Bicep.L", "Forearm.R", "Spine.001"} <= set(big[1]), str(big[1][:10]))
rep("đảo không xương (mắt...) vẫn có weight", (W.sum(1) > 0.99).all(),
    "%d vertex trống" % int((W.sum(1) < 0.99).sum()))
nz = (W > 0).sum(1)
rep("tối đa 4 xương, không vụn, tổng 1",
    nz.max() <= 4 and (W[W > 0] >= TW.MIN_W).all() and np.allclose(W.sum(1), 1, atol=1e-6))
col = {n: j for j, n in enumerate(names)}
C = WF.rest_co(body, rig)
leak = 0
for i, r in enumerate(R):
    if lay.mid is not None and abs(C[i].x - lay.mid[0]) < lay.mid[1]:
        continue                                    # dải giữa háng: hai chân được trộn
    if r in ('Leg.L', 'Leg.R'):
        other = 'R' if r == 'Leg.L' else 'L'
        leak += sum(W[i, col[n]] > 0.05 for n in ("Thigh." + other, "Shin." + other, "Foot." + other) if n in col)
rep("chân bên này không ăn sang chân bên kia", leak == 0, "%d vertex" % leak)
arm_leak = sum(1 for i, r in enumerate(R) if r == 'Torso'
               and any(W[i, col[n]] > 0.5 for n in ("Forearm.L", "Forearm.R", "Hand_Master.L", "Hand_Master.R") if n in col))
rep("cẳng tay / bàn tay không ăn vào thân", arm_leak == 0, "%d vertex" % arm_leak)

TW.apply(body, rig, names, W, keep=set(hand))
rows = cloth._rows_of(body, exact=True)
rep("vertex vẽ tay y nguyên", all(rows[i] == r for i, r in hand_rows.items()))
after_face = [{vg[g.group].name: g.weight for g in v.groups if vg[g.group].name in face}
              for v in body.data.vertices]
same = all(abs(a.get(k, 0) - b.get(k, 0)) < 1e-6 for a, b in zip(before_face, after_face) for k in set(a) | set(b))
rep("weight xương mặt giữ nguyên", same)
s1 = WA.score(body, rig, lay, R)
rep("khám tư thế tốt hơn automatic", WA.better(s1, s0), "%s -> %s" % (s0, s1))

# đối xứng: mesh gương hoàn hảo cho weight gương
P = np.array([[0.3, 0, 1], [-0.3, 0, 1], [0.0, 0, 1]])
Wt = np.array([[0.8, 0.2, 0.0], [0.4, 0.0, 0.6], [0.5, 0.25, 0.25]])
S = TW._symmetrize(P, Wt, ["Spine", "Bicep.L", "Bicep.R"], 2.0)
rep("đối xứng: hai bên thành ảnh gương", np.allclose(S[0], [0.6, 0.4, 0.0]) and np.allclose(S[1], [0.6, 0.0, 0.4])
    and np.allclose(S[2], [0.5, 0.25, 0.25]), str(S.round(2).tolist()))

# nút Sửa weight dùng weight theo lưới khi tốt hơn
del body[cloth.HAND_KEY]
WA._restore(body, [dict(r) for r in rows])
print("TỔNG %d/%d" % (sum(results), len(results)))
