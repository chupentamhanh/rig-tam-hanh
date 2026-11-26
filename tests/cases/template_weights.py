"""Chép weight nhân vật mẫu (kiểu Mixamo). Fixture kid_live.blend (weight automatic);
mẫu là Adult đã vẽ tay, nạp từ tests/fixtures/adult_final.blend (chỉ đọc), đặt
lệch sang bên 3 m như khi người dùng để mẫu cạnh nhân vật."""
import os

import addon_utils
import bpy
import numpy as np

addon_utils.enable("rig_tam_hanh", default_set=False)
from rig_tam_hanh import templateweights as TPL, topoweights as TW, weightauto as WA, weightfence as WF

HERE = os.path.dirname(os.path.abspath(__file__))
ADULT = os.path.join(HERE, "..", "fixtures", "adult_final.blend")
ctx = bpy.context
rig = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
body = ctx.scene.srp_generate.target_mesh
ctx.view_layer.objects.active = rig
st = ctx.scene.srp_generate
results = []


def rep(name, ok, detail=""):
    results.append(bool(ok))
    print("[%s] %s %s" % ("ĐẠT" if ok else "HỎNG", name, detail))


lay = WF.Layout(rig)
R = WF.regions_for(body, rig, lay)
orig = WA._rows(body)
s0 = WA.score(body, rig, lay, R)

# chưa chọn mẫu: hai bước mẫu bỏ qua, có lý do
out = WA.autofix(ctx, body, rig, skip={'TOPO', 'LOCALIZE', 'FENCE', 'JOINTS', 'BAKE', 'FENCE2', 'FILL', 'TIDY'})
stt = {k: s for k, _l, s, _n in out["steps"]}
rep("chưa chọn mẫu: bỏ qua có lý do", stt['TPL_BONE'] == 'NOTPL' and stt['TPL_FIT'] == 'NOTPL', str(stt))
WA._restore(body, orig)

with bpy.data.libraries.load(ADULT) as (src, dst):
    dst.objects = ["Adult_Rig", "Adult_body"]
for o in dst.objects:
    ctx.scene.collection.objects.link(o)
trig, tmesh = dst.objects
trig.location.x += 3
st.template_rig, st.template_mesh = trig, tmesh
rep("đọc được mẫu", TPL.template(ctx) == (trig, tmesh))

names, W, used = TPL.by_bone(body, rig, trig, tmesh)
rep("theo xương: phần lớn vertex lấy từ mẫu", used > 0.5 * len(W), "%d/%d" % (used, len(W)))
nz = (W > 0).sum(1)
rep("theo xương: tối đa 4 xương, không vụn, tổng 1",
    nz.max() <= 4 and (W[W > 0] >= TW.MIN_W).all() and np.allclose(W.sum(1), 1, atol=1e-6))
_n, _W, info = TW.compute(body, rig)
isl, bl = info["islands_of"], info["boneless"]
rigid = all(np.allclose(W[(isl == r) & bl], W[(isl == r) & bl][0])
            for r in np.unique(isl[bl]))
rep("đảo không xương (mắt) đi cứng theo da", bl.any() and rigid, "%d vertex" % int(bl.sum()))
C = WF.rest_co(body, rig)
col = {n: j for j, n in enumerate(names)}
leak = 0
for i, r in enumerate(R):
    if r in ('Leg.L', 'Leg.R') and not (lay.mid and abs(C[i].x - lay.mid[0]) < lay.mid[1]):
        o = 'R' if r == 'Leg.L' else 'L'
        leak += sum(W[i, col[n]] > 0.05 for n in ("Thigh." + o, "Shin." + o, "Foot." + o) if n in col)
rep("theo xương: chân không ăn sang chân kia", leak == 0, "%d" % leak)
TW.apply(body, rig, names, W)
s1 = WA.score(body, rig, lay, R)
rep("theo xương: khám tư thế tốt hơn automatic", WA.better(s1, s0), "%s -> %s" % (s0, s1))

WA._restore(body, orig)
loc = trig.matrix_world.copy()
TPL.rebuild_by_fit(ctx, body, rig)
s2 = WA.score(body, rig, lay, R)
rep("uốn lưới: mẫu đặt lệch vẫn khớp, tốt hơn automatic", WA.better(s2, s0), "%s -> %s" % (s0, s2))
rep("uốn lưới: mẫu về đúng chỗ cũ", (trig.matrix_world.translation - loc.translation).length < 1e-6)

WA._restore(body, orig)
out = WA.autofix(ctx, body, rig, skip={'TPL_FIT', 'JOINTS', 'BAKE'})
stt = {k: s for k, _l, s, _n in out["steps"]}
rep("nút Sửa weight thử bước mẫu", stt['TPL_BONE'] in ('KEPT', 'UNDONE'), str(stt))
rep("nút Sửa weight: kết quả tốt hơn automatic", WA.better(out["after"], s0), "%s -> %s" % (s0, out["after"]))
st.template_mesh = body
rep("mẫu trùng chính nhân vật thì không dùng",
    {k: s for k, _l, s, _n in WA.autofix(ctx, body, rig, skip={k for k, _l, _a in WA.STEPS if not k.startswith('TPL')})["steps"]}['TPL_BONE'] == 'NOTPL')
print("TỔNG %d/%d" % (sum(results), len(results)))
