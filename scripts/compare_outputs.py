"""파서 출력 비교: heading 커버리지, 표 수, 줄 수를 비교하여 갭 리포트 생성.

Usage:
    python compare_outputs.py <primary.md> [secondary.md ...]

Output (stdout, JSON):
    {
        "primary": { "file": "...", "lines": 1850, "headings": 90, "tables": 45 },
        "secondaries": [ ... ],
        "gaps": [
            { "heading": "## 3. 단계별 도입 절차", "in_primary": false, "in": ["upstage", "llamaparse"] }
        ],
        "recommendation": "primary_only" | "patch_needed" | "full_fusion",
        "reasons": ["..."]     # 추천 근거(표 개수·실제 글자 수·heading 갭·줄 수)
    }

종료 코드: Primary 파일이 없으면 1.
"""

import json
import os
import re
import sys


def analyze_md(file_path: str) -> dict:
    """마크다운 파일의 메타데이터 추출."""
    if not os.path.exists(file_path):
        return {"file": file_path, "exists": False}

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    lines = content.split("\n")
    headings = []
    table_count = 0
    in_table = False

    for line in lines:
        # heading 추출
        m = re.match(r"^(#{1,6})\s+(.+)", line)
        if m:
            level = len(m.group(1))
            title = m.group(2).strip()
            # 노이즈 heading 필터링 (페이지 번호, 빈 제목)
            if title and not re.match(r"^\d+$", title) and len(title) > 1:
                headings.append({"level": level, "title": title})

        # 표 카운트 (| 시작하는 행 그룹)
        if line.strip().startswith("|"):
            if not in_table:
                table_count += 1
                in_table = True
        else:
            in_table = False

    # 표 기호·공백을 뺀 실제 글자 수(빈 표 뼈대가 글자 수를 채우는 함정 대응, gotchas.md)
    content_chars = len(re.sub(r"[\s|\-:#>*`_<!\[\]()]", "", content))

    return {
        "file": os.path.basename(file_path),
        "exists": True,
        "lines": len(lines),
        "chars": len(content),
        "content_chars": content_chars,
        "headings": len(headings),
        "heading_titles": [h["title"] for h in headings],
        "tables": table_count,
    }


def find_gaps(primary: dict, secondaries: list[dict]) -> list[dict]:
    """Primary에 없지만 secondary에 있는 heading을 찾음."""
    if not primary.get("exists"):
        return []

    primary_titles = set(primary["heading_titles"])
    gaps = []

    for sec in secondaries:
        if not sec.get("exists"):
            continue
        for title in sec["heading_titles"]:
            if title not in primary_titles:
                # 이미 gap으로 등록되었는지 확인
                existing = next((g for g in gaps if g["heading"] == title), None)
                if existing:
                    existing["in"].append(sec["file"])
                else:
                    gaps.append({
                        "heading": title,
                        "in_primary": False,
                        "in": [sec["file"]],
                    })

    return gaps


def recommend(primary: dict, secondaries: list[dict], gaps: list[dict]) -> tuple[str, list[str]]:
    """퓨전 전략 추천과 그 근거 목록.

    표 개수·실제 글자 수를 판정에 쓴다(2026-08-31). 종전에는 heading 갭과 줄 수
    130%만 봐서, Primary에서 표 하나가 통째로 빠져도 줄 수 차이가 작으면
    primary_only가 나왔다. 여기서 잡히지 않는 누락(같은 개수의 표 안에서 행이
    빠진 경우)은 Step 5 셀 위치 비교와 Step 6b 구간 대조가 담당한다.
    """
    if not primary.get("exists"):
        return "full_fusion", ["Primary 파일 없음"]

    valid_secondaries = [s for s in secondaries if s.get("exists")]
    if not valid_secondaries:
        return "primary_only", ["보조 파서 출력 없음(교차 검증 불가)"]

    reasons = []
    # 갭이 전체 heading의 10% 이상이면 full fusion
    if primary["headings"] > 0 and len(gaps) > primary["headings"] * 0.1:
        reasons.append(f"heading 갭 {len(gaps)}건 > Primary heading {primary['headings']}의 10%")
        return "full_fusion", reasons

    if gaps:
        reasons.append(f"heading 갭 {len(gaps)}건")

    for sec in valid_secondaries:
        if sec["tables"] > primary["tables"]:
            reasons.append(f"{sec['file']} 표 {sec['tables']}개 > Primary {primary['tables']}개")
        if sec["content_chars"] > primary["content_chars"] * 1.15:
            reasons.append(
                f"{sec['file']} 실제 글자 {sec['content_chars']:,} > Primary {primary['content_chars']:,}의 115%"
            )
        # 줄 수 차이가 30% 이상이면 patch (content gap 가능성)
        if sec["lines"] > primary["lines"] * 1.3:
            reasons.append(f"{sec['file']} 줄 수 {sec['lines']} > Primary {primary['lines']}의 130%")

    if reasons:
        return "patch_needed", reasons
    return "primary_only", ["heading·표 개수·글자 수·줄 수 모두 Primary가 열세 아님"]


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python compare_outputs.py <primary.md> [secondary.md ...]", file=sys.stderr)
        sys.exit(1)

    primary_path = sys.argv[1]
    secondary_paths = sys.argv[2:] if len(sys.argv) > 2 else []

    primary = analyze_md(primary_path)
    secondaries = [analyze_md(p) for p in secondary_paths]
    gaps = find_gaps(primary, secondaries)
    rec, reasons = recommend(primary, secondaries, gaps)

    # heading_titles는 출력에서 제외 (너무 김)
    primary_out = {k: v for k, v in primary.items() if k != "heading_titles"}
    sec_out = [{k: v for k, v in s.items() if k != "heading_titles"} for s in secondaries]

    result = {
        "primary": primary_out,
        "secondaries": sec_out,
        "gap_count": len(gaps),
        "gaps_sample": gaps[:10],  # 처음 10개만
        "recommendation": rec,
        "reasons": reasons,
    }

    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if primary.get("exists") else 1)
