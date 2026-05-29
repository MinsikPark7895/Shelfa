import cv2
import numpy as np
from pathlib import Path
import shutil
import yaml


def seg_label_to_obb(label_path: Path, img_w: int, img_h: int) -> list[str]:
    obb_lines = []

    with open(label_path, "r") as f:
        lines = f.read().strip().splitlines()

    for line in lines:
        if not line.strip():
            continue

        parts = list(map(float, line.split()))
        cls = int(parts[0])
        coords = parts[1:]

        # polygon은 최소 3점 이상 필요
        if len(coords) < 6:
            continue

        pts = []
        for i in range(0, len(coords), 2):
            px = coords[i] * img_w
            py = coords[i + 1] * img_h
            pts.append([px, py])

        pts = np.array(pts, dtype=np.float32)

        # segmentation polygon -> 최소 외접 회전 사각형
        rect = cv2.minAreaRect(pts)

        # 회전 사각형 -> 4개 꼭짓점
        box = cv2.boxPoints(rect)

        # 픽셀 좌표 -> 정규화 좌표
        box[:, 0] = box[:, 0] / img_w
        box[:, 1] = box[:, 1] / img_h
        box = np.clip(box, 0.0, 1.0)

        flat = box.reshape(-1)

        # YOLO OBB 형식:
        # class x1 y1 x2 y2 x3 y3 x4 y4
        obb_line = f"{cls} " + " ".join([f"{v:.6f}" for v in flat])
        obb_lines.append(obb_line)

    return obb_lines


def find_image_path(img_dir: Path, stem: str):
    for ext in [".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG"]:
        img_path = img_dir / f"{stem}{ext}"
        if img_path.exists():
            return img_path
    return None


def count_files(path: Path):
    if not path.exists():
        return 0
    return len([p for p in path.rglob("*") if p.is_file()])


def convert_all_labels(seg_dir: str, obb_dir: str):
    seg_dir = Path(seg_dir)
    obb_dir = Path(obb_dir)

    splits = ["train", "valid", "test"]

    print("=== 원본 데이터 개수 ===")
    for split in splits:
        print(f"{split}/images:", count_files(seg_dir / split / "images"))
        print(f"{split}/labels:", count_files(seg_dir / split / "labels"))

    for split in splits:
        img_dir = seg_dir / split / "images"
        lbl_dir = seg_dir / split / "labels"

        out_img_dir = obb_dir / split / "images"
        out_lbl_dir = obb_dir / split / "labels"

        out_img_dir.mkdir(parents=True, exist_ok=True)
        out_lbl_dir.mkdir(parents=True, exist_ok=True)

        label_files = list(lbl_dir.glob("*.txt"))

        print(f"\n[{split}] {len(label_files)}개 라벨 변환 중...")

        success = 0
        skip_no_image = 0
        skip_empty = 0

        for lbl_path in label_files:
            img_path = find_image_path(img_dir, lbl_path.stem)

            if img_path is None:
                print(f"이미지 없음: {lbl_path.name}")
                skip_no_image += 1
                continue

            img = cv2.imread(str(img_path))

            if img is None:
                print(f"이미지 읽기 실패: {img_path}")
                skip_no_image += 1
                continue

            img_h, img_w = img.shape[:2]

            obb_lines = seg_label_to_obb(lbl_path, img_w, img_h)

            if not obb_lines:
                skip_empty += 1
                continue

            out_lbl_path = out_lbl_dir / lbl_path.name

            with open(out_lbl_path, "w") as f:
                f.write("\n".join(obb_lines))

            shutil.copy(img_path, out_img_dir / img_path.name)

            success += 1

        print(f"[{split}] 완료: {success}개")
        print(f"[{split}] 이미지 없음 스킵: {skip_no_image}개")
        print(f"[{split}] 라벨 없음 스킵: {skip_empty}개")

    yaml_content = {
        "path": str(obb_dir.absolute()),
        "train": "train/images",
        "val": "valid/images",
        "test": "test/images",
        "nc": 1,
        "names": ["book_spine"],
    }

    with open(obb_dir / "data.yaml", "w") as f:
        yaml.dump(yaml_content, f, default_flow_style=False)

    print("\n=== 변환된 OBB 데이터 개수 ===")
    for split in splits:
        print(f"{split}/images:", count_files(obb_dir / split / "images"))
        print(f"{split}/labels:", count_files(obb_dir / split / "labels"))

    print("\nOBB 변환 완료")
    print(f"저장 위치: {obb_dir}")


if __name__ == "__main__":
    convert_all_labels(
        seg_dir=".",
        obb_dir="./dataset_obb"
    )
