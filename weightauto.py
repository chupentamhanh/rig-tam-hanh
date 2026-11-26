"""Sửa weight một nút: chạy mọi bước sửa weight của mesh thân, bước nào đổi hình
khi pose thì giữ hay bỏ theo phép khám tư thế.

Thứ tự (vertex vẽ tay giữ nguyên ở mọi bước):
0. Tính lại weight theo lưới (topoweights) -- THỬ: weight hiện có tốt hơn (vd.
   đã vẽ tay) thì giữ weight hiện có.
1. Khu trú weight (weightfence.localize) -- luôn làm: sửa xương ăn sai bộ phận.
2. Rào weight theo vùng (weightfence.fence) -- luôn làm: sửa xương lấn vùng.
3. Sửa hông, gối, khuỷu (cloth.hip_band + joint_band) -- THỬ: dải chuyển đo trên
   người; trên nhân vật khác dáng (Hotdog: giãn x3.13 -> x5.14) nó làm xấu đi.
4. Tự làm mượt weight các khớp (bakeweights) -- THỬ.
5. Rào lại (bước 4 có thể làm lấn vùng), lấp vertex thiếu weight, rồi dọn: bỏ
   weight < 0.01, tối đa 4 xương, normalize.

THỬ = làm, khám ~40 tư thế (weightfence.check_poses), tốt hơn thì giữ, không thì
trả lại weight trước bước đó. Điểm: số tư thế có lỗi (kéo sai vùng, hàm ra sau
gáy, giãn > x2.5), hoà thì độ giãn trung bình.
"""

import time

import numpy as np

from . import bakeweights, cloth, topoweights, weightfence as WF

MAX_INF = WF.MAX_INF
MIN_W = WF.MIN_W


def _rows(body):
    return cloth._rows_of(body, exact=True)


def _restore(body, rows):
    vg = body.vertex_groups
    for v, row in zip(body.data.vertices, rows):
        now = {vg[g.group].name: g.weight for g in v.groups}
        if now == row:
            continue
        for g in list(v.groups):
            vg[g.group].remove([v.index])
        for n, w in row.items():
            (vg.get(n) or vg.new(name=n)).add([v.index], w, 'REPLACE')


def changed(a, b, tol=1e-4):
    """Số vertex có weight khác nhau giữa hai bản `_rows`."""
    n = 0
    for x, y in zip(a, b):
        if any(abs(x.get(k, 0) - y.get(k, 0)) > tol for k in set(x) | set(y)):
            n += 1
    return n


def score(body, rig, lay, R):
    """(số tư thế có lỗi, độ giãn trung bình) -- càng nhỏ càng tốt."""
    poses = WF.check_poses(body, rig, lay, R)
    bad = 0
    worst = []
    for label, leaks, w, jaw in poses:
        mouth = label.startswith("há miệng")
        bad += bool(leaks or jaw or (w > WF.STRETCH and not mouth))
        if not mouth:
            worst.append(w)
    return bad, float(np.mean(worst)) if worst else 0.0


def better(new, old):
    return new[0] < old[0] or (new[0] == old[0] and new[1] < old[1] - 1e-4)


def tidy(body, rig, keep=()):
    """Bỏ weight < MIN_W, giữ MAX_INF xương nặng nhất, normalize. Trả về số vertex sửa."""
    deform = {b.name for b in rig.data.bones if b.use_deform}
    vg = body.vertex_groups
    n = 0
    for v in body.data.vertices:
        if v.index in keep:
            continue
        row = sorted(((vg[g.group], g.weight) for g in v.groups if vg[g.group].name in deform),
                     key=lambda t: -t[1])
        if not row:
            continue
        good = [(g, w) for g, w in row[:MAX_INF] if w >= MIN_W] or row[:1]
        s = sum(w for _g, w in good)
        if len(good) == len(row) and abs(s - 1) < 1e-4:
            continue
        for g, _w in row:
            g.remove([v.index])
        for g, w in good:
            g.add([v.index], w / s, 'REPLACE')
        n += 1
    return n


def _joints(body, rig):
    with cloth.keep_hand([body]):
        cloth.hip_band(body, rig)
        cloth.joint_band(body, rig, limit=8)


def _bake(context, body, rig):
    keep = cloth.hand_painted(body)
    deform, W, W0 = bakeweights.bake(context, body, rig, limit=MAX_INF, keep=keep)
    bakeweights.write(body, deform, W, W0, keep)


STEPS = (
    # (khoá, tên, luôn làm?)
    ('TOPO', "Tính lại weight theo lưới", False),
    ('LOCALIZE', "Khu trú weight", True),
    ('FENCE', "Rào weight theo vùng", True),
    ('JOINTS', "Sửa hông, gối, khuỷu", False),
    ('BAKE', "Tự làm mượt weight các khớp", False),
    ('FENCE2', "Rào lại sau khi làm mượt", True),
    ('FILL', "Lấp chỗ thiếu weight", True),
    ('TIDY', "Dọn weight vụn, tối đa 4 xương, normalize", True),
)


def autofix(context, body, rig, skip=()):
    """Chạy STEPS trên `body`. Trả về dict: steps [(khoá, tên, trạng thái, số vertex)],
    before / after (điểm tư thế), changed (tổng vertex đổi), seconds."""
    t0 = time.time()
    lay = WF.Layout(rig)
    R = WF.regions_for(body, rig, lay)
    keep = cloth.hand_painted(body)
    start = _rows(body)
    cur = score(body, rig, lay, R)
    before = cur
    run = {
        'TOPO': lambda: topoweights.rebuild(body, rig),
        'LOCALIZE': lambda: WF.localize(body, rig),
        'FENCE': lambda: WF.fence(body, rig),
        'JOINTS': lambda: _joints(body, rig),
        'BAKE': lambda: _bake(context, body, rig),
        'FENCE2': lambda: WF.fence(body, rig),
        'TIDY': lambda: tidy(body, rig, keep),
        'FILL': lambda: cloth.fill_weights(body, rig),
    }
    out = []
    for key, label, always in STEPS:
        if key in skip:
            out.append((key, label, 'SKIP', 0))
            continue
        old = _rows(body)
        try:
            with cloth.keep_hand([body]):   # bước nào quên giữ vertex vẽ tay cũng không sao
                run[key]()
        except Exception as error:         # một bước hỏng không được làm hỏng cả lượt
            _restore(body, old)
            out.append((key, label, 'ERROR: %s' % error, 0))
            continue
        new = _rows(body)
        n = changed(old, new)
        if not n:
            out.append((key, label, 'SAME', 0))
            continue
        s = score(body, rig, lay, R)
        if always or better(s, cur):
            out.append((key, label, 'KEPT', n))
            cur = s
        else:
            _restore(body, old)
            out.append((key, label, 'UNDONE', n))
    total = changed(start, _rows(body))
    if total:
        cloth._forget_skin(body, range(len(body.data.vertices)))
        body[cloth.STAMP_KEY] = body.get(cloth.STAMP_KEY, 0) + 1   # quần áo cần cập nhật
    return dict(steps=out, before=before, after=cur, changed=total, seconds=time.time() - t0)


STATUS = {'KEPT': "giữ", 'UNDONE': "thử rồi bỏ (không tốt hơn)", 'SAME': "không cần sửa",
          'SKIP': "bỏ qua"}


def lines(result):
    """Các dòng báo cáo cho người dùng."""
    out = []
    for _k, label, status, n in result["steps"]:
        s = STATUS.get(status, status)
        out.append("%s: %s%s" % (label, s, " (%d vertex)" % n if n and status == 'KEPT' else ""))
    b, a = result["before"], result["after"]
    out.append("Khám tư thế: %d -> %d tư thế có lỗi, giãn trung bình x%.2f -> x%.2f"
               % (b[0], a[0], 1 + b[1], 1 + a[1]))
    return out
