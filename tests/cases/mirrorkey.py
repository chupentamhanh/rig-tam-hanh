import bpy, math
import addon_utils
from mathutils import Matrix

addon_utils.enable("rig_tam_hanh", default_set=False)
from rig_tam_hanh import mirrorkey as MK

ctx = bpy.context
body = bpy.data.objects["body"]
brow = bpy.data.objects["eyebrow"]
kid = bpy.data.objects["Kid_Rig.001"]
st = ctx.scene.face_shapes
st.face, st.rig = body, kid
ctx.view_layer.objects.active = kid
kb = body.data.shape_keys.key_blocks

for n in ("EYE_BlinkL", "MTH_SmileR", "Pose_001", "Smile.L", "Brow_L.001", "MTH_Left",
          "VIS_L", "JAW_Open", "lip_left_up"):
    print("swap %-12s -> %s" % (n, MK.swap_side(n)))

def op(name, *a, **k):
    try:
        return getattr(bpy.ops.face_shapes, name)(*a, **k)
    except RuntimeError as e:
        return 'ERR ' + str(e)[:90]

mr = MK.Mirror(body, kid)
print("body pairs off-tol: %d / %d | tol %.4g" % (mr.off, mr.n, mr.tol))
print("brow pairs off-tol: %d / %d" % (MK.Mirror(brow, kid).off, len(brow.data.vertices)))

def cmp(obj, a, b):
    da, db = MK.key_delta(obj, a), MK.key_delta(obj, b)
    return max((x - y).length for x, y in zip(da, db)), max(x.length for x in db)

# addon builds L/R pairs symmetrically: flipping L must reproduce R
for src in ("MTH_SmileL", "EYE_BlinkL", "BRW_AngryL", "MTH_StretchL"):
    dst = "T_" + src
    r = op("mirror_key", 'EXEC_DEFAULT', source=src, action='FLIP', dest='NEW', key_name=dst)
    e, m = cmp(body, dst, src[:-1] + "R")
    line = "flip %-12s %s | body err %.4f of %.4f" % (src, r, e, m)
    if brow.data.shape_keys and dst in brow.data.shape_keys.key_blocks:
        e2, m2 = cmp(brow, dst, src[:-1] + "R")
        line += " | eyebrow err %.4f of %.4f" % (e2, m2)
    print(line)

# pose -> key with mirror
P = kid.pose.bones
P["Lip_Upper.L"].location = (0, 0.01, 0)
P["Eyebrow.L.001"].location = (0, 0.01, 0)
ctx.view_layer.update()
r = op("pose_to_key", 'EXEC_DEFAULT', mode='NEW', key_name='Sneer.L', mirror_too=True)
print("pose+mirror", r, "| R exists", "Sneer.R" in kb, "| eyebrow R", "Sneer.R" in brow.data.shape_keys.key_blocks,
      "| driver", any('Sneer.R' in f.data_path for f in brow.data.shape_keys.animation_data.drivers))
# both-sides key = L + R; symmetrize L->R of a one-sided key should equal it when the other side is empty
both = [a + b for a, b in zip(MK.key_delta(body, "Sneer.L"), MK.key_delta(body, "Sneer.R"))]
r = op("mirror_key", 'EXEC_DEFAULT', source='Sneer.L', action='SYMM', keep='L')
s = MK.key_delta(body, "Sneer.L")
print("symm", r, "| vs L+R err %.4f of %.4f" % (max((a - b).length for a, b in zip(s, both)), max(v.length for v in both)))
f = mr.flipped(s)
print("symm self-mirror err %.5f" % max((a - b).length for a, b in zip(s, f)))
print("dup ->", op("mirror_key", 'EXEC_DEFAULT', source='MTH_SmileL', action='FLIP', dest='NEW', key_name='MTH_SmileR'))
print("overwrite ->", op("mirror_key", 'EXEC_DEFAULT', source='MTH_SmileL', action='FLIP', dest='OVERWRITE', target='MTH_SmileR'))
