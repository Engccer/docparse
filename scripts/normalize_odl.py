"""OpenDataLoader 출력 자동 정리 스크립트 (범용)

ODL Primary 출력에서 자동화 가능한 항목을 일괄 처리:
1. 페이지 구분자/코멘트 제거
2. 이미지 placeholder 제거
3. h6 heading → 번호 패턴 기반 계층화
4. plain-text heading 승격 (standalone 번호 패턴)
5. 챕터 표지 페이지 제거 (감지 시에만)
6. 빈 줄 압축

사용법:
  python normalize_odl.py <input_odl.md> [output.md]
  - output 생략 시 [파일명]_fused.md로 저장
"""
import re
import sys
import os


def classify_h6(content):
    """h6 heading 텍스트를 번호 패턴에 따라 적절한 heading level로 분류.

    한국 학술/행정 문서의 표준 번호 체계:
    Ⅰ~Ⅵ (로마숫자) → H1, N. → H2, N) → H3, (N) → H4, ①② → H5
    """
    # 목차 항목 (점선 포함): heading으로 유지하되 level 변경 안 함
    if "·" * 4 in content or "…" * 4 in content or "·····" in content:
        return None  # 원본 유지

    # 로마숫자 Ⅰ~Ⅵ → H1
    if re.match(r"^(Ⅰ|Ⅱ|Ⅲ|Ⅳ|Ⅴ|Ⅵ|Ⅶ|Ⅷ|Ⅸ|Ⅹ)[.\s]", content):
        return 1
    # 목차, 표 목차, 그림 목차
    if content in ("목차",):
        return 1
    # 부록
    if re.match(r"^[\[〔]?부록", content):
        return 1
    # 참고문헌
    if content.startswith("참고문헌"):
        return 1
    # 표 목차, 그림 목차
    if re.match(r"^[<〈]?(표|그림)\s*목차", content):
        return 2
    # N. 제목 → H2
    if re.match(r"^\d+\.\s", content):
        return 2
    # N) 제목 → H3
    if re.match(r"^\d+\)\s", content):
        return 3
    # (N) 제목 → H4
    if re.match(r"^\(\d+\)\s", content):
        return 4
    # ①②③ 등 → H5
    if re.match(r"^[①②③④⑤⑥⑦⑧⑨⑩]", content):
        return 5
    # 가. 나. 다. → H5
    if re.match(r"^[가나다라마바사아자차카타파하]\.\s", content):
        return 5
    # 기본값: H3 (ODL h6의 대부분은 중간 수준 소제목)
    return 3


def is_chapter_cover(lines, i):
    """챕터 표지 페이지 패턴 감지.

    패턴: `# [로마숫자]` 단독 → 다음 줄 제목 텍스트 → mini-TOC
    이후에 `###### [로마숫자]. [제목]`이 존재해야 진짜 표지로 판정.
    """
    line = lines[i].strip()
    m = re.match(r"^#\s+(Ⅰ|Ⅱ|Ⅲ|Ⅳ|Ⅴ|Ⅵ|Ⅶ|Ⅷ|Ⅸ|Ⅹ|부록)\s*$", line)
    if not m:
        return False
    roman = m.group(1)
    # 이후에 동일 로마숫자의 ###### heading이 있는지 확인 (표지가 아닌 실제 시작점)
    pattern = f"###### {roman}."
    for j in range(i + 1, min(i + 50, len(lines))):
        if lines[j].strip().startswith(pattern):
            return True
    return False


def normalize_odl(input_path, output_path=None):
    if output_path is None:
        base = os.path.splitext(input_path)[0]
        # _opendataloader 접미사 제거
        base = re.sub(r"_opendataloader$", "", base)
        output_path = base + "_fused.md"

    with open(input_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    out = []
    stats = {
        "page_sep": 0,
        "page_comment": 0,
        "h6_promoted": 0,
        "plaintext_promoted": 0,
        "cover_removed": 0,
        "image_removed": 0,
        "blank_compressed": 0,
        "title_repeat_removed": 0,
    }

    # 문서 제목 감지 (첫 번째 ## heading의 텍스트)
    doc_title = None
    for line in lines:
        m = re.match(r"^##\s+(.*)", line)
        if m:
            doc_title = m.group(1).strip()
            break

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # 1. 페이지 구분자 제거
        if stripped == "---":
            stats["page_sep"] += 1
            i += 1
            continue

        # 2. 페이지 코멘트 제거
        if re.match(r"^<!--\s*Page\s+\d+", stripped):
            stats["page_comment"] += 1
            i += 1
            continue

        # 3. 이미지 placeholder 제거
        if re.match(r"^!\[", stripped) or re.match(r"^<fig(ure|caption)", stripped):
            stats["image_removed"] += 1
            i += 1
            continue

        # 4. 챕터 표지 페이지 제거
        if is_chapter_cover(lines, i):
            stats["cover_removed"] += 1
            i += 1
            # 표지 내용 스킵 (다음 --- 또는 heading까지)
            while i < len(lines):
                s = lines[i].strip()
                if s == "---" or re.match(r"^#{1,6}\s", s):
                    break
                i += 1
            continue

        # 5. 반복 문서 제목 제거 (표지 페이지 잔재)
        if doc_title and stripped == doc_title:
            # 앞뒤가 빈 줄이면 반복 제목으로 판단
            prev_blank = (len(out) == 0 or out[-1].strip() == "")
            next_blank = (i + 1 >= len(lines) or lines[i + 1].strip() == "")
            if prev_blank and next_blank:
                stats["title_repeat_removed"] += 1
                i += 1
                continue

        # 6. h6 heading 정규화
        m_h6 = re.match(r"^######\s+(.*)", line)
        if m_h6:
            content = m_h6.group(1).strip()
            new_level = classify_h6(content)
            if new_level is not None:
                out.append(f"{'#' * new_level} {content}\n")
                stats["h6_promoted"] += 1
                i += 1
                continue

        # 7. plain-text heading 승격 (standalone 번호 패턴)
        if not stripped.startswith("#") and not stripped.startswith("|") and stripped:
            prev_blank = (len(out) == 0 or out[-1].strip() == "")
            next_blank = (i + 1 >= len(lines) or lines[i + 1].strip() == "")

            if prev_blank and next_blank and len(stripped) < 80:
                promoted = None
                # N) pattern → H3
                if re.match(r"^\d+\)\s+\S", stripped):
                    promoted = 3
                # (N) pattern → H4
                elif re.match(r"^\(\d+\)\s+\S", stripped):
                    promoted = 4
                # ①②③ → H5
                elif re.match(r"^[①②③④⑤⑥⑦⑧⑨⑩]\s", stripped) and len(stripped) < 60:
                    promoted = 5
                # 가. 나. 다. → H5
                elif re.match(r"^[가나다라마바사아자차카타파하]\.\s", stripped) and len(stripped) < 60:
                    promoted = 5

                if promoted:
                    out.append(f"{'#' * promoted} {stripped}\n")
                    stats["plaintext_promoted"] += 1
                    i += 1
                    continue

        out.append(line)
        i += 1

    # 8. 빈 줄 압축 (3줄 이상 → 2줄)
    final = []
    blank_count = 0
    for line in out:
        if line.strip() == "":
            blank_count += 1
            if blank_count <= 2:
                final.append(line)
            else:
                stats["blank_compressed"] += 1
        else:
            blank_count = 0
            final.append(line)

    # 선행 빈 줄 제거
    while final and final[0].strip() == "":
        final.pop(0)

    with open(output_path, "w", encoding="utf-8") as f:
        f.writelines(final)

    return output_path, len(lines), len(final), stats


def main():
    if len(sys.argv) < 2:
        print("사용법: python normalize_odl.py <input_odl.md> [output.md]")
        print("  output 생략 시 [파일명]_fused.md로 저장")
        return

    input_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None

    if not os.path.exists(input_path):
        print(f"오류: 파일을 찾을 수 없습니다: {input_path}")
        return

    output_path, in_lines, out_lines, stats = normalize_odl(input_path, output_path)

    print("=== ODL 자동 정리 완료 ===")
    for k, v in stats.items():
        if v > 0:
            print(f"  {k}: {v}")
    print(f"  입력: {in_lines} 줄")
    print(f"  출력: {out_lines} 줄")
    print(f"  저장: {output_path}")


if __name__ == "__main__":
    main()
