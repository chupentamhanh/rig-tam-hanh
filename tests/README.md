# Bài test Rig Tẩm Hành

Chạy cả bộ (mỗi bài một tiến trình Blender nền, trên bản sao file):

```
python tests/run_tests.py
```

- Chỉ vài bài: `python tests/run_tests.py overall weights`
- Danh sách bài: `python tests/run_tests.py --list`
- Blender ở chỗ khác: `--blender "D:\Blender\blender.exe"` hoặc biến môi trường `SRP_BLENDER`
- Giữ log và file xuất: `--keep` (tự giữ khi có bài hỏng)

Python nào cũng được, kể cả python đi kèm Blender
(`<thư mục Blender>\5.2\python\bin\python.exe`). Thoát mã 1 nếu có bài HỎNG / LỖI.

## Fixtures

`tests/fixtures/` chứa file .blend của Kid và Adult ở các trạng thái cần cho từng bài.
Đó là tài sản nhân vật nên **không commit** (xem `.gitignore`). Máy khác thiếu file thì
bài đó báo BỎ QUA.

| File | Dùng cho |
|---|---|
| `kid_live.blend` | overall, cloth, proportions |
| `adult_start.blend` | adult (dựng Adult từ đầu theo mẫu Kid) |
| `adult_final.blend` | weights (Adult đã vẽ tay: bảo vệ weight vẽ tay, cập nhật từ thân, Delta Mush) |
| `kid_facekeys.blend` | unity_*, posekey, mirrorkey |
| `kid_copy.blend` | generate, fixes |
| `kid_sync.blend`, `kid_sync2.blend` | refsync, refsync_add |
| `kid_face.blend`, `kid_fk.blend` | face_parts, facerig |

## Loại bài

- **CHECK**: tự in `[ĐẠT]` / `[HỎNG]` từng mục. Mục hỏng đã biết ghi trong `TESTS`
  của `run_tests.py` (hiện có: bài cloth, áo hoodie Kid "chép từ thân tốt hơn
  automatic" — đâm xuyên 7 vs 5, có từ trước 1.17).
- **SMOKE**: script dò / đo cũ, không tự kết luận — chỉ kiểm tra chạy hết không lỗi.
  Muốn biết số đo thì đọc `log.txt` của bài đó (`--keep`).
