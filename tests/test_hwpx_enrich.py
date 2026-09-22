"""hwpx_enrich.assign_pages 회귀 테스트(PDF 없이 쪽 텍스트를 흉내 낸다).

불변식: 1차 정렬(LIS)은 쪽이 문서 순서대로 비감소, 2차 정렬(빈 쪽 채우기)은 1차가 건너뛴 쪽만 채우며 그 순서를 깨지 않는다.
"""
import importlib.util
import pathlib
import re

spec = importlib.util.spec_from_file_location("hwpx_enrich", pathlib.Path(__file__).resolve().parents[1] / "scripts" / "hwpx_enrich.py")
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)


def page(n, text):
    return {"pdf": n, "printed": n, "key": re.sub(r"[\W_]+", "", text)}


def printed(result, pages):
    return [pages[r]["printed"] if r is not None else None for r in result]


def test_first_pass_monotonic_and_gap_fill_uses_only_skipped_pages():
    lines = [
        "첫째 쪽에만 있는 긴 문장입니다 하나둘셋넷다섯여섯",   # 1쪽(16자 키로 1차 정렬)
        "| 둘째쪽 표의 첫 칸 내용이 길게 이어지는 문장 | 다른 칸 |",  # 2쪽: 표라 -layout에서 칸이 섞여 1차 키(16자 연속)가 안 잡힌다고 가정
        "셋째 쪽에만 있는 긴 문장입니다 가나다라마바사아",   # 3쪽
    ]
    pages = [
        page(1, "첫째 쪽에만 있는 긴 문장입니다 하나둘셋넷다섯여섯 바닥글"),
        page(2, "섞인 칸 둘째쪽 표의 첫 칸 내용 다른 칸 바닥글"),
        page(3, "셋째 쪽에만 있는 긴 문장입니다 가나다라마바사아 바닥글"),
    ]
    # 2쪽 키를 일부러 1차 키(16자 연속)와 어긋나게: 8자 조각은 이어지되 16자 연속은 끊기게 다른 칸 글자를 끼운다
    k = re.sub(r"[\W_]+", "", "둘째쪽 표의 첫 칸 내용이 길게 이어지는 문장")
    pages[1]["key"] = k[:8] + "섞임" + k[8:16] + "섞임" + k[16:] + "바닥글"
    report = {}
    result = printed(E.assign_pages(lines, pages, report), pages)
    assert result == [1, 2, 3], result
    assert report["pages"]["gap_filled"] == 1
    assigned = [r for r in result if r is not None]
    assert assigned == sorted(assigned)


def test_gap_fill_skips_when_chunks_also_match_neighbor_pages():
    lines = [
        "첫째 쪽에만 있는 긴 문장입니다 하나둘셋넷다섯여섯",
        "| 공통 문구 장애인교원 지원 내용 | 칸 |",  # 앞 쪽에도 같은 조각이 있으면 창 안으로 끌어오지 않는다
        "셋째 쪽에만 있는 긴 문장입니다 가나다라마바사아",
    ]
    common = "공통 문구 장애인교원 지원 내용"
    pages = [
        page(1, "첫째 쪽에만 있는 긴 문장입니다 하나둘셋넷다섯여섯 " + common),
        page(2, "다른 " + common[:9] + " 섞임 " + common[9:]),
        page(3, "셋째 쪽에만 있는 긴 문장입니다 가나다라마바사아"),
    ]
    report = {}
    result = printed(E.assign_pages(lines, pages, report), pages)
    assert result[0] == 1 and result[2] == 3
    assert report["pages"]["gap_filled"] == 0


def test_heading_seen_on_more_than_three_pages_is_not_a_locator():
    lines = ["부록 신청 서식 제목", "본문 문장이 충분히 길어서 키가 됩니다 하나둘셋"]
    pages = [page(n, "부록 신청 서식 제목 옆탭") for n in (1, 2, 3, 4)] + [page(5, "본문 문장이 충분히 길어서 키가 됩니다 하나둘셋")]
    result = printed(E.assign_pages(lines, pages, {}, heading_idx={0}), pages)
    assert result == [5, 5], result  # 제목은 자기 매칭 대신 뒤 본문 쪽을 물려받는다
