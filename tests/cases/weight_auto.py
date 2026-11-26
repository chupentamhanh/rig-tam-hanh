"""Sửa weight một nút (srp.weights_auto). Fixture adult_final.blend.

Cấy lỗi lên mesh thân (đùi trái sang chân phải, weight vụn, quá 4 xương, thiếu
weight), bấm nút: lỗi hết, vertex vẽ tay y nguyên, khám tư thế không xấu đi.
Bước THỬ mà làm xấu đi phải bị trả lại."""
import bpy
import addon_utils

addon_utils.enable("rig_tam_hanh", default_set=False)
from rig_tam_hanh import cloth, weightauto as WA, weightfence as WF

ctx = bpy.context
rig = bpy.data.objects["Adult_Rig"]
body = bpy.data.objects["Adult_body"]
ctx.view_layer.objects.active = rig
results = []


def rep(name, ok, detail=""):
    results.append(bool(ok))
    print("[%s] %s %s" % ("ĐẠT" if ok else "HỎNG", name, detail))


rep("nút có trong addon", hasattr(bpy.types, "SRP_OT_weights_auto"))
hand = cloth.hand_painted(body)
rep("fixture có vertex vẽ tay", len(hand) > 0, str(len(hand)))
hand_rows = {i: r for i, r in enumerate(cloth._rows_of(body, exact=True)) if i in hand}

# --- cấy lỗi (không đụng vertex vẽ tay)
lay = WF.Layout(rig)
R = WF.regions_for(body, rig, lay)
C = WF.rest_co(body, rig)
vg = body.vertex_groups
free = [i for i in range(len(C)) if i not in hand]
leg_l = [i for i in free if R[i] == 'Leg.L' and C[i].z < 0.6][:40]
for i in leg_l:                                     # đùi phải ăn sang chân trái
    vg["Thigh.R"].add([i], 0.4, 'REPLACE')
spine = [i for i in free if R[i] == 'Torso'][:60]
for i in spine[:30]:                                # vụn + quá 4 xương
    for n in ("Hand.L", "Hand.R", "Foot.L", "Foot.R", "Neck"):
        if n in vg:
            vg[n].add([i], 0.004, 'REPLACE')
for i in spine[30:]:                                # thiếu weight: nhân 0.5
    for g in body.data.vertices[i].groups:
        g.weight *= 0.5
bad0, _ = WF.check_static(body, rig, lay, R)
rep("lỗi cấy được", bad0.get("xương lấn sai vùng") and bad0.get("quá 4 xương") and bad0.get("chưa normalize"),
    ", ".join("%s=%d" % (k, len(v)) for k, v in bad0.items()))
before = WA.score(body, rig, lay, R)

res = bpy.ops.srp.weights_auto('EXEC_DEFAULT')
rep("nút chạy xong", res == {'FINISHED'}, str(res))
bad1, _ = WF.check_static(body, rig, lay, R)
rows = cloth._rows_of(body, exact=True)
inj = set(leg_l) | set(spine)
rep("hết lấn vùng ở chỗ cấy", not any(t[0] in inj for t in bad1.get("xương lấn sai vùng", ())),
    str(len(bad1.get("xương lấn sai vùng", ()))))
deform = {b.name for b in rig.data.bones if b.use_deform}
def _bad_row(r):
    d = [w for n, w in r.items() if n in deform]
    return len(d) > 4 or any(w < WA.MIN_W for w in d) or abs(sum(d) - 1) > 1e-3


print("   chỗ cấy còn lỗi:", [(i, {n: round(w, 3) for n, w in rows[i].items()}) for i in inj if _bad_row(rows[i])][:5])
print("   vẽ tay bị đổi:", [i for i, r in hand_rows.items() if rows[i] != r][:10])
rep("chỗ cấy: tối đa 4 xương, không vụn, tổng 1",
    all(len([w for n, w in rows[i].items() if n in deform]) <= 4
        and all(w >= WA.MIN_W for n, w in rows[i].items() if n in deform)
        and abs(sum(w for n, w in rows[i].items() if n in deform) - 1) < 1e-3 for i in inj))
rep("vertex vẽ tay y nguyên", all(rows[i] == r for i, r in hand_rows.items()))
after = WA.score(body, rig, lay, R)
rep("khám tư thế không xấu đi", not WA.better(before, after), "%s -> %s" % (before, after))

# --- bước THỬ làm xấu đi thì bị trả lại
rep("so điểm: ít tư thế lỗi hơn là tốt hơn", WA.better((2, 0.9), (3, 0.1)) and not WA.better((3, 0.1), (2, 0.9)))
rep("so điểm: hoà thì giãn ít hơn là tốt hơn", WA.better((2, 0.5), (2, 0.6)) and not WA.better((2, 0.6), (2, 0.6)))
orig = WA._joints


def _ruin(b, r):                                    # bước "sửa" phá hỏng chân
    for v in b.data.vertices:
        if v.index not in hand and R[v.index] == 'Leg.L':
            for g in list(v.groups):
                b.vertex_groups[g.group].remove([v.index])
            b.vertex_groups["Spine"].add([v.index], 1.0, 'REPLACE')


WA._joints = _ruin
try:
    out = WA.autofix(ctx, body, rig, skip={'BAKE'})
finally:
    WA._joints = orig
st = {k: s for k, _l, s, _n in out["steps"]}
rep("bước thử làm hỏng thì bị trả lại", st.get('JOINTS') == 'UNDONE', str(st))
legs = [i for i in range(len(R)) if R[i] == 'Leg.L' and i not in hand]
now = cloth._rows_of(body, exact=True)
ruined = sum(1 for i in legs if now[i].get("Spine", 0) > 0.5)
rep("chỗ bị phá đã được trả lại", legs and not ruined, "%d/%d vertex chân còn dính Spine" % (ruined, len(legs)))
rep("báo cáo đủ dòng", len(WA.lines(out)) == len(WA.STEPS) + 1)
print("TỔNG %d/%d" % (sum(results), len(results)))
