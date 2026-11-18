"""Rào weight theo vùng + Khám weight. Fixture adult_final.blend.

Cấy đúng ba lỗi đã gặp trên con mèo: vai ăn lên má, hàm ăn ra sau gáy, đùi
bên này ăn sang chân bên kia. Khám phải thấy, Rào phải gỡ, vertex vẽ tay giữ."""
import bpy
import numpy as np
import addon_utils
from mathutils import Vector

addon_utils.enable("rig_tam_hanh", default_set=False)
from rig_tam_hanh import weightfence as WF, cloth, bakeweights

ctx = bpy.context
rig = bpy.data.objects["Adult_Rig"]
body = bpy.data.objects["Adult_body"]
results = []


def rep(name, ok, detail=""):
    results.append(ok)
    print("[%s] %s %s" % ("ĐẠT" if ok else "HỎNG", name, detail))


lay = WF.Layout(rig)
rep("vùng xương theo cấu trúc rig",
    lay.region.get("Shoulder.L") == "Arm.L" and lay.region.get("Jaw") == "Head"
    and lay.region.get("Thigh.R") == "Leg.R" and lay.region.get("Spine.002") == "Torso"
    and "Neck" in lay.neck, "Shoulder.L=%s Jaw=%s neck=%s" % (lay.region.get("Shoulder.L"), lay.region.get("Jaw"), lay.neck))

body.data.attributes.get(WF.ATTR) and body.data.attributes.remove(body.data.attributes[WF.ATTR])
R = WF.build_regions(body, rig, lay)
rep("vùng vertex có đủ 6 vùng", set(R) == set(WF.REGIONS), str(sorted(set(R))))

C = WF.rest_co(body, rig)
B = rig.data.bones
Wc = WF.weights(body)
n0, k0 = WF.fence(body, rig)                      # mesh đã sửa tay sạch: gần như không đụng
Wd = WF.weights(body)
moved0 = max((abs(Wd[i].get(k, 0) - Wc[i].get(k, 0)) for i in range(len(Wc)) for k in set(Wc[i]) | set(Wd[i])), default=0)
rep("mesh sạch: rào gần như không đụng", n0 <= 10 and moved0 < 0.02 and k0 > 0,
    "%d vertex, lệch tối đa %.3f, giữ %d vertex vẽ tay" % (n0, moved0, k0))
W0 = WF.weights(body)
base_static, _l = WF.check_static(body, rig, lay, R)
base_leak = len(base_static.get("xương lấn sai vùng", ()))

# ---- cấy lỗi
J = B["Jaw"]
eye = B["Eye.L"].head_local
cheek = [i for i, c in enumerate(C) if R[i] == 'Head' and c.x > 0.03 and c.y < eye.y + 0.02
         and J.head_local.z - 0.03 < c.z < eye.z - 0.01]
back = [i for i, c in enumerate(C) if R[i] == 'Head' and c.y > J.head_local.y + 0.09 and c.z > J.head_local.z + 0.04]
thl = B["Thigh.R"].head_local
legr = [i for i, c in enumerate(C) if R[i] == 'Leg.R' and c.x < thl.x - 0.02 and c.z < thl.z - 0.1]
cheek, back, legr = cheek[:40], back[:60], legr[:40]
rep("chọn được chỗ cấy lỗi", len(cheek) >= 10 and len(back) >= 20 and len(legr) >= 20,
    "má %d, sau gáy %d, chân phải %d" % (len(cheek), len(back), len(legr)))


def inject(idx, bone, x):
    vg = body.vertex_groups
    g = vg.get(bone) or vg.new(name=bone)
    for i in idx:
        for gg in body.data.vertices[i].groups:
            gg.weight *= (1 - x)
        g.add([i], x, 'ADD')


inject(cheek, "Shoulder.L", 0.4)
inject(back, "Jaw", 0.4)
inject(legr, "Thigh.L", 0.3)
hand_i = cheek[0]
body[cloth.HAND_KEY] = [hand_i]          # một vertex má đánh dấu vẽ tay
W1 = WF.weights(body)

bad, leak = WF.check_static(body, rig, lay, R)
n_leak = len(bad.get("xương lấn sai vùng", ()))
n_jaw = len(bad.get("hàm ăn ra sau gáy / lên đỉnh đầu", ()))
rep("khám tĩnh thấy vai lên má + đùi sang chân kia", leak[("Shoulder.L", "Head")] >= len(cheek)
    and leak[("Thigh.L", "Leg.R")] >= len(legr), "vai->đầu %d, đùi trái->chân phải %d"
    % (leak[("Shoulder.L", "Head")], leak[("Thigh.L", "Leg.R")]))
rep("khám tĩnh thấy hàm ra sau gáy", n_jaw >= len(back) * 0.8, "%d / %d" % (n_jaw, len(back)))


def pose_by(label_start):
    for label, leaks, worst, jb in WF.check_poses(body, rig, lay, R):
        if label.startswith(label_start):
            yield label, leaks, jb


sh = [l for l in pose_by("chi / lưng / cổ") if "Shoulder.L" in l[0]]
rep("khám tư thế: nhún vai kéo má", any(l[1].get("Head", 0) > 0 for l in sh), str([(l[0][-22:], l[1]) for l in sh]))
jaw = list(pose_by("há miệng"))
rep("khám tư thế: há miệng kéo sau gáy", jaw and jaw[0][2] > 0, str(jaw[:1]))

# ---- rào
n, kept = WF.fence(body, rig)
W2 = WF.weights(body)
rep("rào: có sửa, giữ vertex vẽ tay", n > 0 and kept == 1 and W2[hand_i] == W1[hand_i], "%d vertex, giữ %d" % (n, kept))
rep("má không còn xương vai", all("Shoulder.L" not in W2[i] for i in cheek if i != hand_i))
rep("sau gáy không còn hàm", all(W2[i].get("Jaw", 0) < 0.02 for i in back))
rep("chân phải không còn đùi trái", all("Thigh.L" not in W2[i] for i in legr))
changed = [i for i in range(len(W2)) if W2[i] != W1[i]]
rep("mỗi vertex đã sửa: tối đa 4 xương, tổng 1", all(len(W2[i]) <= 4 and abs(sum(W2[i].values()) - 1) < 1e-3
                                                      for i in changed))
far = [i for i, c in enumerate(C) if R[i] in ('Arm.L', 'Arm.R') and abs(c.x) > 0.5]
rep("vùng xa không bị đụng (bàn tay)", all(W2[i] == W1[i] for i in far), "%d vertex" % len(far))
bad2, _l = WF.check_static(body, rig, lay, R)
left = len(bad2.get("xương lấn sai vùng", ()))
rep("sau rào: lấn vùng không nhiều hơn lúc đầu (trừ vertex vẽ tay)", left <= base_leak + 1, "đầu %d, cấy %d, sau rào %d"
    % (base_leak, n_leak, left))

# ---- chuyển động thật: nhún vai -> má đứng yên, há miệng -> sau gáy đứng yên
def moved(idx, ops):
    deform = lay.deform
    di = {n: j for j, n in enumerate(deform)}
    W = WF.weights(body)
    S = bakeweights.skin_mats(rig, deform, ops)
    out = 0.0
    for i in idx:
        v = np.array(tuple(C[i]) + (1.0,))
        s = sum(x for k, x in W[i].items() if k in di)
        p = sum(x / s * (S[di[k]] @ v) for k, x in W[i].items() if k in di)
        out = max(out, float(np.linalg.norm(p[:3] - v[:3])))
    return out * 1000

cheek2 = [i for i in cheek if i != hand_i]
m_sh = moved(cheek2, [("Shoulder.L", "Y", -20)])
m_jaw = moved(back, [("Jaw", "X", 20)])
rep("nhún vai: má đứng yên", m_sh < 0.5, "%.2f mm" % m_sh)
rep("há miệng: sau gáy đứng yên", m_jaw < 0.5, "%.2f mm" % m_jaw)

# ---- toán tử + báo cáo
for o in list(ctx.selected_objects):
    o.select_set(False)
ctx.view_layer.objects.active = body
body.select_set(True)
r = bpy.ops.srp.weight_check()
t = bpy.data.texts.get(WF.REPORT)
rep("nút Khám weight ghi báo cáo", r == {'FINISHED'} and t is not None and "KIỂM BẰNG TƯ THẾ" in t.as_string())
r = bpy.ops.srp.weights_fix('EXEC_DEFAULT', task='FENCE')
rep("Sửa weight… → Rào weight theo vùng chạy được", r == {'FINISHED'})
print("TỔNG %d/%d" % (sum(results), len(results)))
