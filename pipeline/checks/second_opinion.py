"""CHECK 6 — Ý kiến thứ hai: so nhãn với một model LỚN HƠN (yolo26l).   ★★★ (khó nhất, đáng điểm nhất)

Test:  pytest tests/test_second_opinion.py -q

Máy kiểm quy tắc, người kiểm ý nghĩa (slide). Các lỗi như thiếu nhãn / gán nhầm lớp hợp lệ / box lỏng
KHÔNG bắt được bằng quy tắc cú pháp. Ta nhờ một model mạnh hơn "nhìn lại" và CHỈ CẢNH BÁO (model cũng có thể sai):
những ảnh bị cờ sẽ vào hàng đợi cho NGƯỜI duyệt.

`preds[stem]` = list `[id_lớp, conf, cx, cy, w, h]` của model (lấy qua `get_preds(ds, cfg, "checker")` nếu preds=None).
`L = ds.valid_boxes(stem)` = list `(id_lớp, cx, cy, w, h)` của nhãn (đã bỏ dòng hỏng).
Ngưỡng ở `cfg["second_opinion"]`: conf, min_area_px, fp_conf, iou_missing, iou_match, iou_loose.

Thuật toán gợi ý, với từng ảnh (bỏ qua ảnh không có trong preds hoặc không có file nhãn):
  P = dự đoán có conf >= conf  VÀ diện tích px (w*W * h*H) >= min_area_px
  Với mỗi dự đoán r trong P: lấy các nhãn có IoU(r, nhãn) >= iou_missing  (cands)
   - không có cands                            -> POSSIBLE_MISSING     (model thấy vật mà nhãn không có box)
   - có cands cùng lớp, tốt nhất IoU < iou_loose -> POSSIBLE_LOOSE_BOX  (đúng vật, box lỏng/lệch)
   - không có cands cùng lớp, nhưng cands tốt nhất IoU >= iou_match (khác lớp) -> POSSIBLE_WRONG_CLASS
  Với mỗi dòng nhãn hợp lệ: nếu IoU với MỌI dự đoán (conf >= fp_conf, không lọc diện tích) đều < iou_missing
                                             -> POSSIBLE_FALSE_POS  (box nhãn không khớp vật nào model thấy; Issue.line = số dòng)

Chi tiết các ca biên (test kiểm đúng các ca này)
- `cands` gồm nhãn MỌI lớp có IoU >= iou_missing; "tốt nhất cùng lớp" = cands cùng lớp có IoU lớn nhất; "tốt nhất khác lớp" tương tự với cands khác lớp.
- Thứ tự quyết định cho mỗi dự đoán: (1) cands rỗng -> MISSING. (2) có cands cùng lớp: IoU tốt nhất < iou_loose -> LOOSE_BOX, ngược lại KHÔNG cờ
  (nhãn đúng lớp đã phủ vật này, kể cả khi còn nhãn khác lớp chồng lên). (3) không có cands cùng lớp: nếu IoU tốt nhất khác lớp >= iou_match -> WRONG_CLASS;
  nếu chỉ có khác lớp với IoU trong [iou_missing, iou_match) -> không cờ gì (mơ hồ: để cho FALSE_POS / lần duyệt khác).
- Một dự đoán sinh tối đa MỘT issue (MISSING / LOOSE_BOX / WRONG_CLASS); một ảnh có thể có nhiều issue.
- Thứ tự issue: theo `ds.image_files()` rồi theo thứ tự dự đoán trong `preds[stem]`, cuối cùng là các FALSE_POS theo số dòng; `Issue.image` = stem, `Issue.line` chỉ đặt cho FALSE_POS.

Lưu ý số dòng: dùng `ds.read_label_lines(stem)` (giữ số dòng gốc, kể cả dòng hỏng/trống) để lấy `Issue.line`; `valid_boxes` KHÔNG giữ số dòng.

Tất cả severity WARN; `Issue.extra` nên có {"conf": ...} hoặc {"iou": ...} (hàng đợi duyệt dùng conf để xếp ưu tiên).

Gợi ý
- `iou_xywh` có sẵn. Dòng nhãn hỏng không được làm script chết (dùng `ds.valid_boxes` và `parse_yolo_line` trong try).
- Kết quả phụ thuộc mạnh vào ngưỡng: calibrate chúng ở Bước 3 thay vì đoán.
"""
from ..common import WARN, Issue, iou_xywh, parse_yolo_line
from ..model_cache import get_preds


def run(ds, cfg, preds=None):
    if preds is None:
        preds = get_preds(ds, cfg, "checker")
    if preds is None:
        preds = {}

    so_cfg = cfg.get("second_opinion", {})
    conf_thresh = so_cfg.get("conf", 0.25)
    min_area_px = so_cfg.get("min_area_px", 600)
    fp_conf = so_cfg.get("fp_conf", 0.1)
    iou_missing = so_cfg.get("iou_missing", 0.3)
    iou_match = so_cfg.get("iou_match", 0.5)
    iou_loose = so_cfg.get("iou_loose", 0.5)

    issues = []

    for p in ds.image_files():
        stem = p.stem
        if stem not in preds or not ds.label_path(stem).exists():
            continue

        size = ds.image_size(stem)
        W, H = size if size else (1, 1)

        raw_preds = preds.get(stem, [])
        label_lines = ds.read_label_lines(stem)
        if label_lines is None:
            continue

        # Đọc các nhãn hợp lệ kèm số dòng gốc
        valid_labels = []
        for line_num, line_str in label_lines:
            try:
                c, cx, cy, w, h = parse_yolo_line(line_str)
                if 0 <= c < len(ds.classes):
                    valid_labels.append((line_num, c, cx, cy, w, h))
            except ValueError:
                continue

        L_boxes = [(c, cx, cy, w, h) for (_, c, cx, cy, w, h) in valid_labels]

        # Lọc dự đoán của model cho MISSING / LOOSE_BOX / WRONG_CLASS
        P = [
            r
            for r in raw_preds
            if r[1] >= conf_thresh and (r[4] * W) * (r[5] * H) >= min_area_px
        ]

        pred_issues = []
        for r in P:
            r_cls, r_conf, r_cx, r_cy, r_w, r_h = r
            r_box = (r_cx, r_cy, r_w, r_h)

            # Tìm các box nhãn có IoU >= iou_missing
            cands = []
            for lc, lx, ly, lw, lh in L_boxes:
                iou = iou_xywh(r_box, (lx, ly, lw, lh))
                if iou >= iou_missing:
                    cands.append((lc, iou))

            if not cands:
                pred_issues.append(
                    Issue(
                        check="second_opinion",
                        severity=WARN,
                        code="POSSIBLE_MISSING",
                        image=stem,
                        line=None,
                        message=f"model thấy lớp {ds.classes[r_cls]} (conf {r_conf:.2f}) nhưng nhãn thiếu",
                        extra={"conf": r_conf, "class": r_cls},
                    )
                )
            else:
                same_class_cands = [iou for (lc, iou) in cands if lc == r_cls]
                if same_class_cands:
                    best_same_iou = max(same_class_cands)
                    if best_same_iou < iou_loose:
                        pred_issues.append(
                            Issue(
                                check="second_opinion",
                                severity=WARN,
                                code="POSSIBLE_LOOSE_BOX",
                                image=stem,
                                line=None,
                                message=f"box lớp {ds.classes[r_cls]} lỏng/lệch (IoU {best_same_iou:.2f} < {iou_loose})",
                                extra={"conf": r_conf, "iou": best_same_iou, "class": r_cls},
                            )
                        )
                else:
                    diff_class_cands = [iou for (lc, iou) in cands if lc != r_cls]
                    if diff_class_cands:
                        best_diff_iou = max(diff_class_cands)
                        if best_diff_iou >= iou_match:
                            pred_issues.append(
                                Issue(
                                    check="second_opinion",
                                    severity=WARN,
                                    code="POSSIBLE_WRONG_CLASS",
                                    image=stem,
                                    line=None,
                                    message=f"model đoán lớp {ds.classes[r_cls]} (conf {r_conf:.2f}) nhưng nhãn gán khác (IoU {best_diff_iou:.2f})",
                                    extra={"conf": r_conf, "iou": best_diff_iou, "class": r_cls},
                                )
                            )

        # Kiểm tra POSSIBLE_FALSE_POS
        # Dự đoán dùng để đối chiếu false positive chỉ lọc conf >= fp_conf, không lọc diện tích
        fp_preds = [r for r in raw_preds if r[1] >= fp_conf]
        fp_issues = []
        for line_num, lc, lx, ly, lw, lh in valid_labels:
            l_box = (lx, ly, lw, lh)
            matches_any = any(
                iou_xywh(l_box, (r[2], r[3], r[4], r[5])) >= iou_missing
                for r in fp_preds
            )
            if not matches_any:
                fp_issues.append(
                    Issue(
                        check="second_opinion",
                        severity=WARN,
                        code="POSSIBLE_FALSE_POS",
                        image=stem,
                        line=line_num,
                        message="box nhãn không khớp dự đoán nào của model",
                        extra={"class": lc},
                    )
                )

        issues.extend(pred_issues)
        issues.extend(fp_issues)

    return issues
