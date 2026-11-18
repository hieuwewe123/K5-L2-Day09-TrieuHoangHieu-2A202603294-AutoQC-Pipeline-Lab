"""BƯỚC 2/4 — Sửa tự động những lỗi bắt buộc mà máy sửa được AN TOÀN.   ★★

Test:  pytest tests/test_autofix.py -q

`fix(ds, issues, cfg) -> list[dict]`: duyệt `issues` (chỉ lỗi severity ERROR), sửa thẳng vào thư mục `ds`,
và trả về danh sách thay đổi; mỗi phần tử có khoá: image, line, action, before, after
(đây chính là file `03_fixes.csv` — bằng chứng pipeline đã làm gì, người có thể kiểm lại).

| code lỗi                                       | cách sửa                                    | action           |
|------------------------------------------------|---------------------------------------------|------------------|
| BAD_FORMAT, BAD_CLASS_ID, BOX_ZERO, DUP_BOX    | xoá dòng đó khỏi file nhãn                  | "drop_line"      |
| BOX_OUT_OF_IMAGE                               | cắt box về trong [0,1] (giữ nguyên lớp)     | "clip_box"       |
| MISSING_LABEL_FILE                             | KHÔNG sửa file (máy không thể bịa nhãn): ghi 1 dòng fix, before="(không có file)", after="chuyển người gán" | "needs_label" |
| BAD_CLASS_NAME                                 | ghi lại `names` trong data.yaml đúng `cfg["classes"]` | "rename_classes" |
| DUP_IMAGE_*, LEAK_TEST, CORRUPT_IMAGE, BAD_SIZE| xoá ảnh + nhãn khỏi `ds`                    | "remove_image"   |

Bẫy cần nghĩ tới (có test cho từng cái)
- Một file có NHIỀU dòng lỗi: số dòng trong `issues` là số dòng GỐC. Nếu xoá từng dòng một thì số dòng lệch.
  Gom theo file, rồi ghi lại MỘT lần.
- Sau khi cắt, box có thể không còn diện tích (nằm hẳn ngoài ảnh): lúc đó xoá dòng thay vì ghi box rỗng.
- Một dòng có 2 lỗi (vd. BOX_OUT_OF_IMAGE + DUP_BOX): xoá dòng thắng, chỉ ghi 1 fix `drop_line`, không ghi thêm `clip_box`. Dòng trống ở giữa file vẫn đếm vào số dòng gốc.
- Ảnh vừa bị xoá (DUP_IMAGE_*...) mà còn issue dòng của chính nó: bỏ qua êm, không được báo lỗi/chết.
- Không động tới lỗi WARN (cảnh báo là việc của người). Không sửa file ở `data/raw/` — chỉ sửa `ds`.
- Chạy lần 2 trên dữ liệu đã sửa phải không làm gì thêm (idempotent) — NGOẠI LỆ duy nhất: `needs_label` được ghi lại mỗi lần còn lỗi `MISSING_LABEL_FILE` (vì ảnh vẫn chưa có nhãn).

- `needs_label` KHÔNG tạo file nhãn rỗng (rỗng = "ảnh nền", khác với "chưa gán"). `review_queue` sẽ đẩy ảnh này lên đầu hàng đợi cho người.

Gợi ý: `yaml.safe_load / safe_dump`.
"""
from collections import defaultdict

import yaml

from ..common import ERROR, parse_yolo_line

REMOVE_CODES = {
    "DUP_IMAGE_EXACT",
    "DUP_IMAGE_PHASH",
    "LEAK_TEST",
    "CORRUPT_IMAGE",
    "BAD_SIZE",
}
DROP_CODES = {"BAD_FORMAT", "BAD_CLASS_ID", "BOX_ZERO", "DUP_BOX"}


def fix(ds, issues, cfg):
    fixes = []
    # Chỉ xử lý lỗi có mức độ nghiêm trọng ERROR
    err_issues = [i for i in issues if i.severity == ERROR]
    if not err_issues:
        return []

    # 1. BAD_CLASS_NAME: sửa tên lớp trong data.yaml
    if any(i.code == "BAD_CLASS_NAME" for i in err_issues):
        if ds.yaml_path.exists():
            d = yaml.safe_load(ds.yaml_path.read_text(encoding="utf-8")) or {}
        else:
            d = {}
        old_names = d.get("names", {})
        d["names"] = {i: c for i, c in enumerate(cfg["classes"])}
        ds.yaml_path.write_text(
            yaml.safe_dump(d, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )
        fixes.append(
            {
                "image": "data.yaml",
                "line": None,
                "action": "rename_classes",
                "before": str(old_names),
                "after": str(cfg["classes"]),
            }
        )

    # 2. Xoá ảnh + nhãn bị lỗi đầu vào
    removed_images = set()
    for i in err_issues:
        if i.code in REMOVE_CODES or i.code.startswith("DUP_IMAGE_"):
            if i.image not in removed_images:
                removed_images.add(i.image)
                p = ds.image_path(i.image)
                if p and p.exists():
                    p.unlink()
                lp = ds.label_path(i.image)
                if lp.exists():
                    lp.unlink()
                fixes.append(
                    {
                        "image": i.image,
                        "line": None,
                        "action": "remove_image",
                        "before": i.image,
                        "after": "(đã xoá)",
                    }
                )

    # 3. MISSING_LABEL_FILE: ghi nhận cần người gán nhãn, không tạo file nhãn
    handled_missing = set()
    for i in err_issues:
        if i.code == "MISSING_LABEL_FILE":
            if i.image in removed_images or i.image in handled_missing:
                continue
            handled_missing.add(i.image)
            if not ds.label_path(i.image).exists():
                fixes.append(
                    {
                        "image": i.image,
                        "line": None,
                        "action": "needs_label",
                        "before": "(không có file)",
                        "after": "chuyển người gán",
                    }
                )

    # 4. Sửa các lỗi ở từng dòng nhãn
    line_issues_by_image = defaultdict(lambda: defaultdict(list))
    for i in err_issues:
        if i.line is not None and i.image not in removed_images:
            line_issues_by_image[i.image][i.line].append(i)

    # Duyệt theo từng ảnh
    for stem, line_map in line_issues_by_image.items():
        lp = ds.label_path(stem)
        if not lp.exists():
            continue

        orig_lines = lp.read_text(encoding="utf-8", errors="replace").splitlines()
        new_lines = []

        for line_idx, line_str in enumerate(orig_lines, 1):
            if line_idx not in line_map:
                new_lines.append(line_str)
                continue

            issues_on_line = line_map[line_idx]
            has_drop = any(iss.code in DROP_CODES for iss in issues_on_line)
            has_clip = any(iss.code == "BOX_OUT_OF_IMAGE" for iss in issues_on_line)

            if has_drop:
                # Xoá dòng
                fixes.append(
                    {
                        "image": stem,
                        "line": line_idx,
                        "action": "drop_line",
                        "before": line_str,
                        "after": "",
                    }
                )
            elif has_clip:
                # Cắt box
                drop_clipped = False
                clipped_str = ""
                try:
                    c, cx, cy, w, h = parse_yolo_line(line_str)
                    x1 = max(0.0, min(1.0, cx - w / 2.0))
                    x2 = max(0.0, min(1.0, cx + w / 2.0))
                    y1 = max(0.0, min(1.0, cy - h / 2.0))
                    y2 = max(0.0, min(1.0, cy + h / 2.0))
                    new_w = x2 - x1
                    new_h = y2 - y1
                    if new_w <= 0.0 or new_h <= 0.0:
                        drop_clipped = True
                    else:
                        new_cx = x1 + new_w / 2.0
                        new_cy = y1 + new_h / 2.0
                        clipped_str = f"{c} {round(new_cx, 6):g} {round(new_cy, 6):g} {round(new_w, 6):g} {round(new_h, 6):g}"
                except Exception:
                    drop_clipped = True

                if drop_clipped:
                    fixes.append(
                        {
                            "image": stem,
                            "line": line_idx,
                            "action": "drop_line",
                            "before": line_str,
                            "after": "",
                        }
                    )
                else:
                    fixes.append(
                        {
                            "image": stem,
                            "line": line_idx,
                            "action": "clip_box",
                            "before": line_str,
                            "after": clipped_str,
                        }
                    )
                    new_lines.append(clipped_str)
            else:
                new_lines.append(line_str)

        content = "\n".join(new_lines)
        if new_lines:
            content += "\n"
        lp.write_text(content, encoding="utf-8")

    return fixes
