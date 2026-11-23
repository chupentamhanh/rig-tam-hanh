"""Chạy toàn bộ bài test của Rig Tẩm Hành trong Blender nền.

    python tests/run_tests.py                 # mọi bài
    python tests/run_tests.py overall cloth   # chỉ vài bài
    python tests/run_tests.py --list

Python nào cũng được (kể cả python đi kèm Blender). Đường dẫn blender.exe lấy
theo thứ tự: --blender, biến môi trường SRP_BLENDER, rồi BLENDER_DEFAULT.

Mỗi bài chạy trên BẢN SAO của file trong tests/fixtures/ (không commit -- file
nhân vật). Thiếu file thì bài đó báo BỎ QUA, không tính là hỏng.

Hai loại bài:
- CHECK: tự in [ĐẠT] / [HỎNG] từng mục (hoặc [DAT ] / [HONG]); có mục HỎNG
  ngoài danh sách đã biết là hỏng.
- SMOKE: script dò / đo cũ, không tự kết luận: chỉ cần chạy hết, không lỗi.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CASES = os.path.join(HERE, "cases")
FIX = os.path.join(HERE, "fixtures")
BLENDER_DEFAULT = r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"

# (tên, script, fixture hoặc None, args -- {out}: thư mục riêng, {shared}: chung cả lượt, loại, mục hỏng đã biết)
TESTS = [
    ("overall", "overall.py", "kid_live.blend", [], "CHECK", []),
    ("cloth", "cloth_bind.py", "kid_live.blend", ["{out}"], "CHECK",
     ["áo: chép từ thân tốt hơn automatic"]),      # hỏng từ trước 1.17: đâm xuyên 7 vs 5
    ("adult", "adult_setup.py", "adult_start.blend", ["{out}"], "CHECK", []),
    ("proportions", "proportions.py", "kid_live.blend",
     ["Tall", "1.55", "1.25", "0.85", "1.0", "1.1", "1.45", "{out}"], "CHECK", []),
    ("weights", "weights_tools.py", "adult_final.blend", ["{out}"], "CHECK", []),
    ("ux", "ux_tools.py", "adult_final.blend", [], "CHECK", []),
    ("face_bendy", "face_bendy.py", "adult_final.blend", ["{out}"], "CHECK", []),
    ("face_bendy_remove", "face_bendy_remove.py", "adult_final.blend", [], "CHECK", []),
    ("weight_fence", "weight_fence.py", "adult_final.blend", [], "CHECK", []),
    ("retarget", "retarget.py", "adult_final.blend", ["{out}"], "CHECK", []),
    ("limb_types", "limb_types.py", None, ["{out}"], "CHECK", []),
    ("markers", "markers.py", None, ["{out}"], "CHECK", []),
    ("unity_export", "unity_export.py", "kid_facekeys.blend", ["{shared}/unity"], "SMOKE", []),
    ("unity_import", "unity_import.py", None, ["{shared}/unity"], "SMOKE", []),
    ("unity_export_combined", "unity_export.py", "kid_facekeys.blend", ["{shared}/unity_c", "combine"], "SMOKE", []),
    ("unity_import_combined", "unity_import_combined.py", None, ["{shared}/unity_c"], "SMOKE", []),
    ("unity_clips", "unity_clips.py", "kid_facekeys.blend", ["{out}"], "CHECK", []),
    ("unity_sets", "unity_sets.py", "kid_facekeys.blend", ["{out}"], "CHECK", []),
    ("generate", "generate.py", "kid_copy.blend", [], "SMOKE", []),
    ("refsync", "refsync.py", "kid_sync.blend", [], "SMOKE", []),
    ("refsync_add", "refsync_add.py", "kid_sync2.blend", [], "SMOKE", []),
    ("face_parts", "face_parts.py", "kid_face.blend", [], "SMOKE", []),
    ("facerig", "facerig.py", "kid_fk.blend", [], "SMOKE", []),
    ("posekey_split", "posekey_split.py", "kid_facekeys.blend", [], "CHECK", []),
    ("follow_skin", "follow_skin.py", "adult_final.blend", [], "CHECK", []),
    ("posekey", "posekey.py", "kid_facekeys.blend", [], "SMOKE", []),
    ("mirrorkey", "mirrorkey.py", "kid_facekeys.blend", [], "SMOKE", []),
    ("fixes", "fixes.py", "kid_copy.blend", [], "SMOKE", []),
]

PASS = re.compile(r"^\[(ĐẠT|DAT ?|OK ?)\]\s*(.*)")
FAIL = re.compile(r"^\[(HỎNG|HONG|BAD)\]\s*(.*)")


def blender_path(arg):
    for p in (arg, os.environ.get("SRP_BLENDER"), BLENDER_DEFAULT):
        if p and os.path.isfile(p):
            return p
    sys.exit("Không tìm thấy blender.exe -- dùng --blender <đường dẫn> hoặc đặt SRP_BLENDER")


def run_one(blender, test, work, shared, timeout):
    name, script, fixture, args, kind, known = test
    out = os.path.join(work, name)
    os.makedirs(out, exist_ok=True)
    cmd = [blender, "-b"]
    if fixture:
        src = os.path.join(FIX, fixture)
        if not os.path.isfile(src):
            return "BỎ QUA", "thiếu fixture %s" % fixture, ""
        dst = os.path.join(out, fixture)
        shutil.copyfile(src, dst)
        cmd.append(dst)
    a = [x.replace("{out}", out).replace("{shared}", shared) for x in args]
    for x in a:
        if "/" in x and x.startswith(shared):
            os.makedirs(x, exist_ok=True)
    cmd += ["--factory-startup", "--python-exit-code", "1", "--python", os.path.join(CASES, script)]
    if a:
        cmd += ["--"] + a
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    t = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout, env=env, cwd=out)
    except subprocess.TimeoutExpired:
        return "LỖI", "quá %ds" % timeout, ""
    text = (p.stdout or b"").decode("utf-8", "replace") + (p.stderr or b"").decode("utf-8", "replace")
    with open(os.path.join(out, "log.txt"), "w", encoding="utf-8") as f:
        f.write(text)
    dt = time.time() - t
    if p.returncode != 0 or "Traceback (most recent call last)" in text:
        tb = [ln for ln in text.splitlines() if "Error" in ln or "Exception" in ln][-1:] or ["exit %d" % p.returncode]
        return "LỖI", "%s (%.0fs)" % (tb[0].strip()[:160], dt), text
    if kind == "SMOKE":
        return "ĐẠT", "chạy hết (%.0fs)" % dt, text
    ok = [m.group(2) for m in map(PASS.match, text.splitlines()) if m]
    bad = [m.group(2) for m in map(FAIL.match, text.splitlines()) if m]
    new_bad = [b for b in bad if not any(b.startswith(k) for k in known)]
    if not ok and not bad:
        return "LỖI", "không thấy mục [ĐẠT]/[HỎNG] nào (%.0fs)" % dt, text
    detail = "%d/%d mục (%.0fs)" % (len(ok), len(ok) + len(bad), dt)
    if len(bad) > len(new_bad):
        detail += ", %d hỏng đã biết" % (len(bad) - len(new_bad))
    if new_bad:
        return "HỎNG", detail + " | " + " ; ".join(b[:90] for b in new_bad), text
    return "ĐẠT", detail, text


def main():
    # console Windows (cp1258, cp1252...) không in được tiếng Việt: luôn ra UTF-8
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*")
    ap.add_argument("--blender")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--keep", action="store_true", help="giữ thư mục làm việc (log, file xuất)")
    ap.add_argument("--timeout", type=int, default=900)
    o = ap.parse_args()
    if o.list:
        for t in TESTS:
            print("%-24s %-6s %s" % (t[0], t[4], t[2] or "-"))
        return 0
    tests = [t for t in TESTS if not o.names or t[0] in o.names]
    if not tests:
        sys.exit("Không có bài nào tên: %s" % ", ".join(o.names))
    blender = blender_path(o.blender)
    work = tempfile.mkdtemp(prefix="rth_tests_")
    shared = os.path.join(work, "_shared").replace("\\", "/")
    os.makedirs(shared, exist_ok=True)
    print("Blender: %s\nThư mục làm việc: %s\n" % (blender, work))
    tally = {}
    for t in tests:
        status, detail, _text = run_one(blender, t, work, shared, o.timeout)
        tally[status] = tally.get(status, 0) + 1
        print("%-6s %-24s %s" % (status, t[0], detail), flush=True)
    print("\n" + " | ".join("%s %d" % kv for kv in tally.items()))
    if not o.keep and not tally.get("HỎNG") and not tally.get("LỖI"):
        shutil.rmtree(work, ignore_errors=True)
    else:
        print("Log từng bài: %s\\<tên bài>\\log.txt" % work)
    return 1 if tally.get("HỎNG") or tally.get("LỖI") else 0


if __name__ == "__main__":
    sys.exit(main())
