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
        "recommendation": "primary_only" | "patch_needed" | "full_fusion"
    }
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

    return {
        "file": os.path.basename(file_path),
        "exists": True,
        "lines": len(lines),
        "chars": len(content),
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


def recommend(primary: dict, secondaries: list[dict], gaps: list[dict]) -> str:
    """퓨전 전략 추천."""
    if not primary.get("exists"):
        return "full_fusion"

    valid_secondaries = [s for s in secondaries if s.get("exists")]
    if not valid_secondaries:
        return "primary_only"

    # 갭이 전체 heading의 10% 이상이면 full fusion
    if primary["headings"] > 0 and len(gaps) > primary["headings"] * 0.1:
        return "full_fusion"

    # 갭이 있으면 patch
    if gaps:
        return "patch_needed"

    # 줄 수 차이가 30% 이상이면 patch (content gap 가능성)
    for sec in valid_secondaries:
        if sec["lines"] > primary["lines"] * 1.3:
            return "patch_needed"

    return "primary_only"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python compare_outputs.py <primary.md> [secondary.md ...]", file=sys.stderr)
        sys.exit(1)

    primary_path = sys.argv[1]
    secondary_paths = sys.argv[2:] if len(sys.argv) > 2 else []

    primary = analyze_md(primary_path)
    secondaries = [analyze_md(p) for p in secondary_paths]
    gaps = find_gaps(primary, secondaries)
    rec = recommend(primary, secondaries, gaps)

    # heading_titles는 출력에서 제외 (너무 김)
    primary_out = {k: v for k, v in primary.items() if k != "heading_titles"}
    sec_out = [{k: v for k, v in s.items() if k != "heading_titles"} for s in secondaries]

    result = {
        "primary": primary_out,
        "secondaries": sec_out,
        "gap_count": len(gaps),
        "gaps_sample": gaps[:10],  # 처음 10개만
        "recommendation": rec,
    }

    print(json.dumps(result, ensure_ascii=False, indent=2))
