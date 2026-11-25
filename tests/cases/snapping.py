"""Snapping trong che do dat marker: moi kieu Snap To cua Blender tren khoi lap phuong.

Viewport gia: nhin chinh dien (ortho, nhin theo +Y), 400x400 px, 100 px moi met.
argv: -- outdir
"""
import math
import sys
from types import SimpleNamespace as NS

import addon_utils
import bpy
from bpy_extras import view3d_utils
from mathutils import Euler, Matrix, Vector

addon_utils.enable("rig_tam_hanh", default_set=False)
from rig_tam_hanh import snapping as SN

ctx = bpy.context
ts = ctx.scene.tool_settings
results = []


def rep(name, ok, detail=""):
    results.append(bool(ok))
    print("[%s] %s %s" % ("ĐẠT" if ok else "HỎNG", name, detail))


for ob in list(bpy.data.objects):
    bpy.data.objects.remove(ob)
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0))
cube = ctx.object

W = H = 400
view = (Matrix.Translation((0, -10, 0)) @ Euler((math.pi / 2, 0, 0)).to_matrix().to_4x4()).inverted()
near, far = 0.01, 100.0
win = Matrix(((2 / 4, 0, 0, 0), (0, 2 / 4, 0, 0),
              (0, 0, -2 / (far - near), -(far + near) / (far - near)), (0, 0, 0, 1)))
rv3d = NS(view_matrix=view, perspective_matrix=win @ view, window_matrix=win,
          is_perspective=False, view_perspective='ORTHO')
region = NS(width=W, height=H)
space = NS(region_3d=rv3d, overlay=NS(grid_scale=1.0, grid_subdivisions=10),
           shading=NS(type='SOLID', show_xray=False, show_xray_wireframe=True))
snapper = SN.Snapper()


def px(p):
    return view3d_utils.location_3d_to_region_2d(region, rv3d, Vector(p))


def snap(elements, xy, **kw):
    ts.use_snap = kw.pop("on", True)
    ts.snap_elements = elements
    return snapper.snap(ctx, space, region, tuple(xy), **kw)


def near_to(p, q, tol=1e-4):
    return p is not None and (Vector(p) - Vector(q)).length < tol


c = px((0.5, 0, 0.5))
rep("chiếu đúng: góc trên phải ở (250, 250)", (c - Vector((250, 250))).length < 1e-3, str(c))

p, k = snap({'VERTEX'}, c + Vector((8, 6)), on=False)
rep("tắt nam châm thì không snap", p is None)
p, k = snap({'VERTEX'}, c + Vector((8, 6)), on=False, invert=True)
rep("Ctrl đảo: tắt thành bật", k == 'VERTEX')
p, k = snap({'VERTEX'}, c + Vector((8, 6)), invert=True)
rep("Ctrl đảo: bật thành tắt", p is None)

p, k = snap({'VERTEX'}, c + Vector((8, 6)))
rep("Vertex: bắt đỉnh mặt trước, không bắt đỉnh bị che", near_to(p, (0.5, -0.5, 0.5)), str(p))
space.shading.show_xray = True
p, k = snap({'VERTEX'}, c + Vector((8, 6)))
rep("X-ray: đỉnh trước / sau trùng nhau thì lấy đỉnh gần mắt", near_to(p, (0.5, -0.5, 0.5)), str(p))
p, k = snap({'EDGE'}, px((0.2, -0.5, 0.5)) + Vector((0, 6)))
rep("X-ray: cạnh trước / sau trùng nhau thì lấy cạnh gần mắt",
    near_to(p, (0.2, -0.5, 0.5), 2e-3), str(p))
space.shading.show_xray = False
p, k = snap({'VERTEX'}, c + Vector((40, 0)))
rep("Vertex: xa quá 30 px thì thôi", p is None)

e = px((0.2, -0.5, 0.5))
p, k = snap({'EDGE'}, e + Vector((0, 6)))
rep("Edge: điểm trên cạnh dưới chuột", k == 'EDGE' and near_to(p, (0.2, -0.5, 0.5), 2e-3), str(p))
p, k = snap({'EDGE_MIDPOINT'}, px((0.05, -0.5, 0.5)) + Vector((0, 5)))
rep("Edge Center: giữa cạnh", near_to(p, (0, -0.5, 0.5)), str(p))
p, k = snap({'EDGE_PERPENDICULAR'}, px((0.3, -0.5, 0.5)) + Vector((3, 4)),
            base=Vector((0.3, -0.5, 1.5)))
rep("Edge Perpendicular: chân đường vuông góc từ gốc", k == 'EDGE_PERPENDICULAR'
    and near_to(p, (0.3, -0.5, 0.5)), str(p))
p, k = snap({'FACE_MIDPOINT'}, px((0.1, 0, 0.1)))
rep("Face Center: tâm mặt trước", near_to(p, (0, -0.5, 0)), str(p))
p, k = snap({'FACE'}, px((0.2, 0, 0.1)))
rep("Face: điểm chạm mặt trước", near_to(p, (0.2, -0.5, 0.1), 1e-3), str(p))
p, k = snap({'VOLUME'}, px((0.2, 0, 0.1)))
rep("Volume: giữa khối", near_to(p, (0.2, 0, 0.1), 1e-3), str(p))
p, k = snap({'VERTEX', 'FACE'}, px((0.2, 0, 0.1)))
rep("Vertex + Face: xa đỉnh thì rơi về mặt", k == 'FACE', str(k))
p, k = snap({'VERTEX', 'FACE'}, c + Vector((-5, -5)))
rep("Vertex + Face: gần đỉnh thì đỉnh thắng", k == 'VERTEX', str(k))
p, k = snap({'FACE_NEAREST'}, px((0.2, 0, 0.1)), free=Vector((0.2, -1.2, 0.1)))
rep("Face Nearest: kéo về mặt gần nhất", near_to(p, (0.2, -0.5, 0.1), 1e-3), str(p))

base, free = Vector((0.13, 0, 0.07)), Vector((1.4, 0, 0.6))
outside = (390, 390)
p, k = snap({'INCREMENT'}, outside, base=base, free=free)
rep("Increment: bước 1 m tính từ chỗ cũ", near_to(p, (1.13, 0, 1.07)), str(p))
p, k = snap({'INCREMENT'}, outside, base=base, free=free, precise=True)
rep("Increment + Shift: bước 0.1 m", near_to(p, (1.43, 0, 0.57)), str(p))
ts.use_snap_grid_absolute = True
p, k = snap({'INCREMENT'}, outside, base=base, free=free)
rep("Absolute Grid Snap: tròn theo lưới thế giới", near_to(p, (1, 0, 1)), str(p))
ts.use_snap_grid_absolute = False
p, k = snap({'GRID'}, outside, base=base, free=free)
rep("Grid: tròn theo lưới thế giới", near_to(p, (1, 0, 1)), str(p))
p, k = snap({'VERTEX', 'INCREMENT'}, c + Vector((3, 3)), base=base, free=free)
rep("Vertex + Increment: bắt được đỉnh thì không làm tròn", k == 'VERTEX', str(k))
rv3d.perspective_matrix = Matrix.Diagonal((4, 4, 1, 1)) @ win @ view
step = SN.Snapper.grid_step(ctx, space, region, rv3d, Vector((0, 0, 0)))
rep("Increment theo zoom: phóng 4 lần thì bước 0.1 m", abs(step - 0.1) < 1e-6, str(step))
rv3d.perspective_matrix = win @ view

cube.hide_select = True
ts.use_snap_selectable = True
p, k = snap({'VERTEX'}, c + Vector((8, 6)))
rep("Chỉ snap object chọn được: bỏ qua object khoá chọn", p is None)
ts.use_snap_selectable = False
p, k = snap({'VERTEX'}, c + Vector((8, 6)))
rep("Mặc định vẫn snap object khoá chọn", k == 'VERTEX')

# Backface culling: mat phang quay lung ve camera nam truoc khoi lap phuong
bpy.ops.mesh.primitive_plane_add(size=0.6, location=(0.2, -1.0, 0.1), rotation=(-math.pi / 2, 0, 0))
plane = ctx.object
normal = plane.matrix_world.to_3x3() @ plane.data.polygons[0].normal
snapper = SN.Snapper()
p, k = snap({'FACE'}, px((0.2, 0, 0.1)))
rep("Face: mặt phẳng phía trước che khối", near_to(p, (0.2, -1.0, 0.1), 1e-3), str(p))
ts.use_snap_backface_culling = True
p, k = snap({'FACE'}, px((0.2, 0, 0.1)))
rep("Backface Culling: xuyên qua mặt quay lưng" if normal.y > 0 else "Backface Culling: mặt quay mặt vẫn bắt",
    near_to(p, (0.2, -0.5, 0.1) if normal.y > 0 else (0.2, -1.0, 0.1), 1e-3), "%s n=%s" % (p, normal))
ts.use_snap_backface_culling = False

# Che do dat marker dung module snapping
from rig_tam_hanh import markers as MK
rep("chế độ đặt marker gọi snapping", "snapper" in MK.SRP_OT_marker_mode._click_point.__code__.co_names)
print("TỔNG %d/%d" % (sum(results), len(results)))
if not all(results):
    sys.exit(1)
