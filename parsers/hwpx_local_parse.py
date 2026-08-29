"""HWPX 로컬 파서 (docparse): hwpx-tomd 패키지로 외부 API 없이 변환.

다른 *_parse.py와 동일한 인터페이스:
  python hwpx_local_parse.py "<파일.hwpx>"        → <파일>_hwpxlocal.md
  python hwpx_local_parse.py "<파일.hwpx>" --cell-br [--merge-fill]

특징(무료·오프라인): 글상자(drawText) reading-order 수집, <hp:t> tail 보존(객관식
선택지 ②③⑤ 누락 방지), 표 cellAddr/cellSpan 그리드 배치(세로·가로 병합 보존).
변환 후 자가검증 3종(단어 recall + 글자 멀티셋 recall + 객관식 마커 보존 가드)과
이미지 존재 경고를 출력한다.

경고의 두 계급(2026-08-31): 엔진 경고를 **텍스트 손실 경고**(단어/글자 recall 미달,
객관식 마커 누락)와 **안내 경고**(이미지 존재, 제어문자 제거)로 나눈다. 텍스트
손실 경고가 하나라도 있으면 다른 로컬 파서(pdfplumber·docx·xlsx)와 같은 정책으로
**출력 파일을 만들지 않고 종료 코드 1**로 끝낸다 — 누락된 파일이 작업 폴더에
남아 퓨전에 편입되는 것을 막는다. 안내 경고는 출력을 유지한다(이미지 내 텍스트는
OCR 영역이라 원래 범위 밖).

한계: 이미지 안의 텍스트(제목·도표·캡션)는 추출 범위 밖이다. 본문에 이미지가
있으면 경고하며, 이때는 Upstage(upstage_parse.py)로 교차검증/대체할 것.
HWP(구형 바이너리)는 먼저 hwpx-automation의 hwp2hwpx.bat(Windows)/hwp2hwpx.sh(macOS/Linux)로
HWPX 변환 후 입력한다.

종료 코드: 0 = 출력 파일 생성, 1 = 오류·텍스트 손실 경고(출력 없음).
"""
import os
import sys
import traceback

SUPPORTED_EXTENSIONS = [".hwpx"]
# 엔진 경고 문구 중 "텍스트가 실제로 빠졌을 수 있다"는 계급. 접두로 판별한다
# (이미지 안내 경고 본문에도 "self-recall"이라는 단어가 들어 있어 부분 문자열 매칭은 오거부).
LOSS_PREFIXES = ("원본 단어 recall", "문자 recall", "객관식 선택지 마커")


def get_output_filename(input_file):
    """입력 파일 경로 기반 출력 경로(<base>_hwpxlocal.md) 생성."""
    dir_path = os.path.dirname(input_file)
    base_name = os.path.splitext(os.path.basename(input_file))[0]
    output_name = f"{base_name}_hwpxlocal.md"
    return os.path.join(dir_path, output_name) if dir_path else output_name


def clear_stale_output(output_file):
    """같은 이름의 이전 출력이 있으면 지운다.

    실행이 실패했을 때 어제 만든 파일이 오늘 결과로 오인되는 것을 막는다.
    """
    if os.path.exists(output_file):
        os.remove(output_file)
        print(f"기존 출력 제거: {output_file}")


def main():
    """반환값이 종료 코드다(0 성공 / 1 실패)."""
    try:
        from hwpx_tomd import convert, HwpxEncryptedError, HwpxError
    except ImportError as e:
        print("오류: hwpx-tomd 패키지를 찾을 수 없습니다.")
        print("설치 명령: pip install hwpx-tomd")
        print("  (엔진 소스 수정 시: pip install -e path/to/hwpx-tomd)")
        print(f"상세: {e}")
        return 1

    cell_br = "--cell-br" in sys.argv
    merge_fill = "--merge-fill" in sys.argv
    positional = [a for a in sys.argv[1:] if not a.startswith("--")]

    def process_file(filename):
        """출력 파일을 만들었으면 True."""
        print(f"입력 파일: {filename}")
        ext = os.path.splitext(filename)[1].lower()
        if ext == ".hwp":
            print("오류: HWP(구형 바이너리)는 직접 처리할 수 없습니다.")
            print("  hwpx-automation의 convert/hwp2hwpx.bat(Windows)/hwp2hwpx.sh(macOS/Linux)로 HWPX 변환 후 입력하세요.")
            return False
        if ext not in SUPPORTED_EXTENSIONS:
            print(f"오류: 지원하지 않는 파일 형식입니다: {ext}")
            print(f"지원 형식: {', '.join(SUPPORTED_EXTENSIONS)}")
            return False
        if not os.path.exists(filename):
            print(f"오류: 파일을 찾을 수 없습니다: {filename}")
            return False

        output_file = get_output_filename(filename)
        clear_stale_output(output_file)

        opts = []
        if cell_br:
            opts.append("--cell-br")
        if merge_fill:
            opts.append("--merge-fill")
        print(f"변환 중... (hwpx-tomd 엔진{', ' + ' '.join(opts) if opts else ''})")

        try:
            result = convert(filename, cell_br=cell_br, merge_fill=merge_fill)
        except HwpxEncryptedError as e:
            print("오류: 암호화된 HWPX입니다(파싱 불가).")
            print(str(e))
            print("한컴에서 암호를 제거해 다시 저장한 뒤 변환하거나, OCR이 필요한 경우 Upstage를 사용하세요.")
            return False
        except HwpxError as e:
            print(f"오류: HWPX 처리 실패: {e}")
            return False

        loss_warnings = [w for w in result.warnings if w.startswith(LOSS_PREFIXES)]
        info_warnings = [w for w in result.warnings if w not in loss_warnings]

        print(f"자가검증 recall: 단어 {result.recall:.1%} · 글자 {result.char_recall:.1%}")
        if loss_warnings:
            print(f"경고: 텍스트 손실 의심 {len(loss_warnings)}건")
            for w in loss_warnings:
                print(f"  - {w}")
            print("→ 검증 실패: 출력 파일을 만들지 않았습니다. Upstage로 교차검증하거나,")
            print("  손실을 감수하고 강제 변환하려면 hwpx-tomd CLI(hwpx-tomd <파일>)를 직접 쓰세요.")
            return False

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(result.markdown)

        print(f"변환 완료! {len(result.markdown)}글자가 저장되었습니다.")
        print(f"출력 파일: {output_file}")
        if result.image_count:
            print(f"경고: 본문 이미지 {result.image_count}개. 이미지 내 텍스트는 추출 범위 밖입니다.")
            print("  이미지 내 텍스트가 중요하면 Upstage(upstage_parse.py)로 교차검증하세요.")
        for w in info_warnings:
            if "이미지" in w and result.image_count:
                continue  # 위 한 줄로 이미 안내
            print(f"[알림] {w}")
        print("=== PASS: 단어·글자 recall 및 마커 보존 가드 통과 ===")
        return True

    if positional:
        return 0 if process_file(positional[0]) else 1

    supported_files = sorted(
        f for f in os.listdir(".")
        if os.path.isfile(f) and os.path.splitext(f)[1].lower() in SUPPORTED_EXTENSIONS
    )
    if not supported_files:
        print("오류: 현재 디렉토리에 지원되는 HWPX 파일이 없습니다.")
        print(f"지원 형식: {', '.join(SUPPORTED_EXTENSIONS)}")
        return 1
    if len(supported_files) == 1:
        return 0 if process_file(supported_files[0]) else 1
    print(f"HWPX 파일 {len(supported_files)}개 발견:")
    for i, f in enumerate(supported_files, 1):
        print(f"  {i}. {f}")
    print()
    all_ok = True
    for f in supported_files:
        all_ok = process_file(f) and all_ok
        print()
    return 0 if all_ok else 1


if __name__ == "__main__":
    exit_code = 1
    try:
        exit_code = main()
    except Exception as e:
        print(f"\n오류 발생: {e}")
        print("\n상세 정보:")
        traceback.print_exc()

    # 비-TTY(AI 에이전트·파이프·백그라운드)에서는 stdin이 EOF로 닫히지 않아
    # input()이 무한 블록되므로 isatty()로 가드 (다른 *_parse.py와 동일 패턴).
    if sys.stdin is not None and sys.stdin.isatty():
        try:
            input("\nEnter를 눌러 종료...")
        except EOFError:
            pass
    sys.exit(exit_code)
