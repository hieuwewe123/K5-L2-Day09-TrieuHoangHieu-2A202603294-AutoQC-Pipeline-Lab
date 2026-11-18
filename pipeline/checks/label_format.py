"""CHECK 2 — Dòng nhãn YOLO: sai định dạng, ID lớp lạ, box tràn ảnh, box rỗng, box lặp.   (Script 2 trong slide)   ★★

Test:  pytest tests/test_label_format.py -q

Mỗi dòng nhãn: `id cx cy w h` (5 số, toạ độ 0–1). Trả về list[Issue]; `Issue.line` = số dòng (đếm từ 1).

| code             | severity | khi nào                                                                  |
|------------------|----------|--------------------------------------------------------------------------|
| BAD_FORMAT       | ERROR    | không đúng 5 cột số (dùng `parse_yolo_line`, bắt `ValueError`)           |
| BAD_CLASS_ID     | ERROR    | id lớp ngoài 0..len(ds.classes)-1                                        |
| BOX_ZERO         | ERROR    | w <= 0 hoặc h <= 0                                                       |
| BOX_OUT_OF_IMAGE | ERROR    | mép box vượt [0,1] quá `cfg["label_format"]["overflow_tol"]`; extra={"overflow": mức tràn} |
| DUP_BOX          | ERROR    | cùng lớp với một dòng TRƯỚC ĐÓ và IoU > `dup_box_iou`; báo ở dòng SAU    |
| BOX_TINY         | WARN     | cạnh ngắn của box (px) < `min_box_px`  (cần `ds.image_size(stem)`)       |
| BOX_HUGE         | WARN     | w*h > `max_box_frac`                                                     |

Gợi ý
- Mép trái = x - w/2, mép phải = x + w/2 (xem câu hỏi "dòng YOLO nào lỗi?" trong slide).
- Một dòng hỏng (BAD_FORMAT, BAD_CLASS_ID, BOX_ZERO) thì `continue`, đừng kiểm tiếp hình học của dòng đó.
- Dòng thiếu cột làm script của slide dừng giữa chừng: đây là lý do phải `try/except`.
- `iou_xywh(a, b)` có sẵn trong common.py.
- Ngưỡng nằm trong `cfg["label_format"]` — đừng viết cứng số vào code.
"""
from ..common import ERROR, WARN, Issue, iou_xywh, parse_yolo_line


def run(ds, cfg):
    issues = []
    lf_cfg = cfg.get("label_format", {})
    overflow_tol = lf_cfg.get("overflow_tol", 0.002)
    dup_box_iou = lf_cfg.get("dup_box_iou", 0.9)
    min_box_px = lf_cfg.get("min_box_px", 12)
    max_box_frac = lf_cfg.get("max_box_frac", 0.95)

    for p in ds.image_files():
        stem = p.stem
        lines = ds.read_label_lines(stem)
        if lines is None:
            continue

        size = ds.image_size(stem)
        valid_boxes_seen = []

        for line_num, text in lines:
            try:
                c, cx, cy, w, h = parse_yolo_line(text)
            except ValueError:
                issues.append(
                    Issue(
                        check="label_format",
                        severity=ERROR,
                        code="BAD_FORMAT",
                        image=stem,
                        line=line_num,
                        message=f"dòng sai định dạng: {text}",
                    )
                )
                continue

            if not (0 <= c < len(ds.classes)):
                issues.append(
                    Issue(
                        check="label_format",
                        severity=ERROR,
                        code="BAD_CLASS_ID",
                        image=stem,
                        line=line_num,
                        message=f"id lớp lạ {c}",
                    )
                )
                continue

            if w <= 0 or h <= 0:
                issues.append(
                    Issue(
                        check="label_format",
                        severity=ERROR,
                        code="BOX_ZERO",
                        image=stem,
                        line=line_num,
                        message=f"box rộng/cao <= 0 ({w}, {h})",
                    )
                )
                continue

            # Kiểm tra tràn ảnh
            left = cx - w / 2.0
            right = cx + w / 2.0
            top = cy - h / 2.0
            bottom = cy + h / 2.0
            overflow = max(0.0, -left, -top, right - 1.0, bottom - 1.0)
            if overflow > overflow_tol:
                issues.append(
                    Issue(
                        check="label_format",
                        severity=ERROR,
                        code="BOX_OUT_OF_IMAGE",
                        image=stem,
                        line=line_num,
                        message=f"box tràn ảnh (mức tràn {overflow:.4f})",
                        extra={"overflow": overflow},
                    )
                )

            # Kiểm tra box lặp
            curr_box = (cx, cy, w, h)
            for prev_line, prev_c, prev_box in valid_boxes_seen:
                if prev_c == c and iou_xywh(curr_box, prev_box) > dup_box_iou:
                    issues.append(
                        Issue(
                            check="label_format",
                            severity=ERROR,
                            code="DUP_BOX",
                            image=stem,
                            line=line_num,
                            message=f"trùng box với dòng {prev_line}",
                        )
                    )
                    break
            valid_boxes_seen.append((line_num, c, curr_box))

            # Cảnh báo box quá nhỏ (WARN)
            if size is not None:
                img_w, img_h = size
                short_side = min(w * img_w, h * img_h)
                if short_side < min_box_px:
                    issues.append(
                        Issue(
                            check="label_format",
                            severity=WARN,
                            code="BOX_TINY",
                            image=stem,
                            line=line_num,
                            message=f"box quá nhỏ ({short_side:.1f}px < {min_box_px}px)",
                            extra={"min_side_px": short_side},
                        )
                    )

            # Cảnh báo box quá to (WARN)
            if w * h > max_box_frac:
                issues.append(
                    Issue(
                        check="label_format",
                        severity=WARN,
                        code="BOX_HUGE",
                        image=stem,
                        line=line_num,
                        message=f"box chiếm {w*h:.2f} > {max_box_frac} ảnh",
                    )
                )

    return issues
