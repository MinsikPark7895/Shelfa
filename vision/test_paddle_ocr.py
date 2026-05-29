from paddleocr import PaddleOCR
from pathlib import Path
import json
import os


# 테스트할 이미지 경로
# title_crops 안의 실제 파일명으로 바꾸셔도 됩니다.
IMAGE_PATH = "crop_results_130324/title_crops/130324_26_3_book_00_title_crop.jpg"

OUTPUT_DIR = "paddle_ocr_output"


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    if not Path(IMAGE_PATH).exists():
        raise FileNotFoundError(f"이미지를 찾을 수 없습니다: {IMAGE_PATH}")

    # PaddleOCR 3.x 방식
    ocr = PaddleOCR(
        lang="korean",
        use_textline_orientation=True,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False
    )

    # 구버전: ocr.ocr(IMAGE_PATH, cls=True)
    # 신버전: ocr.predict(IMAGE_PATH)
    results = ocr.predict(IMAGE_PATH)

    print("\n=== PaddleOCR 원본 출력 ===")
    all_texts = []

    for idx, res in enumerate(results):
        # PaddleOCR 자체 출력
        res.print()

        # 결과 이미지/JSON 저장
        res.save_to_img(OUTPUT_DIR)
        res.save_to_json(OUTPUT_DIR)

        # dict처럼 접근 가능한 경우 텍스트만 추출
        try:
            rec_texts = res.get("rec_texts", [])
            rec_scores = res.get("rec_scores", [])

            print("\n=== 텍스트만 출력 ===")
            for text, score in zip(rec_texts, rec_scores):
                print(f"{text} / score={score:.3f}")
                all_texts.append(text)

        except Exception as e:
            print("텍스트 직접 추출 실패:", e)
            print("대신 저장된 JSON을 확인하세요.")

    one_line = " ".join(all_texts)

    print("\n=== 한 줄 정리 ===")
    print(one_line)

    print(f"\n저장 폴더: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
