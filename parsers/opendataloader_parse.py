"""OpenDataLoader PDF 파서 (docparse, 로컬·Java 필요).

  python opendataloader_parse.py "<파일.pdf>"   → <파일>_opendataloader.md

실패 계약(2026-08-31): 마크다운이 생성되지 않거나 표 기호·공백을 제외한 실제
글자가 0이면 출력 파일을 만들지 않고 종료 코드 1. 실행 시작 시 같은 이름의
이전 출력을 지운다.
"""
import os
import re
import sys
import shutil
import tempfile
import traceback

# Windows 콘솔(cp949)에서 직접 호출되어도 print가 en-dash 등으로 깨지지 않도록
# stdout/stderr를 UTF-8 + errors=replace 로 강제. PYTHONIOENCODING 미설정 환경
# (writing_kb_convert.py 같은 외부 wrapper 없이 단독 호출) 대비.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 표 기호·페이지 구분자·공백을 뺀 "실제 글자"(gotchas.md의 빈 표 뼈대 함정 대응)
_NON_CONTENT = re.compile(r"[\s|\-:#>*`_<!\[\]()]")


def main():
    """반환값이 종료 코드다(0 성공 / 1 실패)."""
    try:
        import opendataloader_pdf
    except ImportError as e:
        print("오류: opendataloader-pdf 패키지를 찾을 수 없습니다.")
        print("설치 명령: pip install -U opendataloader-pdf")
        print(f"상세: {e}")
        return 1

    # Java 설치 확인 (opendataloader-pdf는 Java 필요)
    if not shutil.which("java"):
        print("오류: Java가 설치되어 있지 않거나 PATH에 등록되지 않았습니다.")
        print("opendataloader-pdf는 Java Runtime Environment(JRE)가 필요합니다.")
        print("설치: https://adoptium.net/ 에서 JDK/JRE를 다운로드하세요.")
        return 1

    # 지원 파일 확장자 (PDF만 지원)
    SUPPORTED_EXTENSIONS = ['.pdf']

    def get_output_filename(input_file):
        """입력 파일 경로를 기반으로 출력 파일 경로 생성"""
        dir_path = os.path.dirname(input_file)
        base_name = os.path.splitext(os.path.basename(input_file))[0]
        output_name = f"{base_name}_opendataloader.md"
        if dir_path:
            return os.path.join(dir_path, output_name)
        return output_name

    def clear_stale_output(output_file):
        if os.path.exists(output_file):
            os.remove(output_file)
            print(f"기존 출력 제거: {output_file}")

    def process_file(input_file):
        """단일 파일 문서 파싱. 출력 파일을 만들었으면 True."""
        print(f"입력 파일: {input_file}")
        output_file = get_output_filename(input_file)
        clear_stale_output(output_file)

        # 파일 크기 확인
        file_size = os.path.getsize(input_file)
        file_size_mb = file_size / (1024 * 1024)
        print(f"파일 크기: {file_size_mb:.1f} MB")

        print("변환 중... (로컬 처리, GPU 불필요)")

        # JVM은 Windows에서 명령행 인자를 cp949로 디코드한다. 경로에 cp949
        # 외 문자(en-dash 등)가 있으면 ODL 내부 Java 호출이 빈 출력으로
        # 떨어진다. 항상 ASCII-safe 임시 폴더에 input.pdf로 staging.
        with tempfile.TemporaryDirectory() as temp_dir:
            staged_input = os.path.join(temp_dir, "input.pdf")
            shutil.copy2(input_file, staged_input)

            # OpenDataLoader PDF 변환 (v2.2.0+)
            opendataloader_pdf.convert(
                input_path=staged_input,
                output_dir=temp_dir,
                format="markdown",
                use_struct_tree=True,
                table_method="cluster",
                markdown_page_separator="\n\n---\n<!-- Page %page-number% -->\n\n",
                image_output="off",
            )

            # 생성된 마크다운 파일 찾기 (input.pdf가 들어가 있으므로 제외)
            md_files = [f for f in os.listdir(temp_dir) if f.endswith('.md')]
            if not md_files:
                print("오류: 마크다운 파일이 생성되지 않았습니다. 출력 파일을 만들지 않았습니다.")
                return False

            # 마크다운 내용 읽기
            temp_md_path = os.path.join(temp_dir, md_files[0])
            with open(temp_md_path, "r", encoding="utf-8") as f:
                markdown_content = f.read()

        content_chars = len(_NON_CONTENT.sub("", markdown_content))
        if content_chars == 0:
            print("오류: 표 기호·공백을 제외한 실제 글자가 0입니다(스캔본이거나 텍스트 레이어 없음).")
            print("→ 출력 파일을 만들지 않았습니다. OCR 파서(Upstage·LlamaParse)로 승격하세요.")
            return False

        # 결과 저장
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(markdown_content)

        print(f"변환 완료! {len(markdown_content)}글자(실제 글자 {content_chars})가 저장되었습니다.")
        print(f"출력 파일: {output_file}")
        return True

    # 명령줄 인수로 파일 경로 받기
    print(f"인수: {sys.argv}")

    if len(sys.argv) > 1:
        input_file = sys.argv[1]
        print(f"입력 경로: {input_file}")

        ext = os.path.splitext(input_file)[1].lower()
        if ext not in SUPPORTED_EXTENSIONS:
            print(f"오류: 지원하지 않는 파일 형식입니다: {ext}")
            print(f"지원 형식: {', '.join(SUPPORTED_EXTENSIONS)}")
            return 1
        if not os.path.exists(input_file):
            print(f"오류: 파일을 찾을 수 없습니다: {input_file}")
            return 1
        return 0 if process_file(input_file) else 1

    # 현재 디렉토리에서 지원되는 파일 찾기
    supported_files = sorted([f for f in os.listdir('.') if os.path.isfile(f) and os.path.splitext(f)[1].lower() in SUPPORTED_EXTENSIONS])
    if not supported_files:
        print("오류: 현재 디렉토리에 지원되는 파일이 없습니다.")
        print(f"지원 형식: {', '.join(SUPPORTED_EXTENSIONS)}")
        return 1
    if len(supported_files) == 1:
        return 0 if process_file(supported_files[0]) else 1

    print(f"지원되는 파일 {len(supported_files)}개 발견:")
    for i, f in enumerate(supported_files, 1):
        print(f"  {i}. {f}")
    print()
    print("1) 하나씩 선택하여 변환")
    print("2) 모두 변환")
    choice = input("선택 (1/2): ").strip()
    print()

    all_ok = True
    for i, f in enumerate(supported_files, 1):
        if choice != "2":
            yn = input(f"[{i}/{len(supported_files)}] {f} 변환? (Y/N): ").strip().upper()
            if yn != "Y":
                print("건너뜀.")
                print()
                continue
        else:
            print(f"[{i}/{len(supported_files)}] {f}")
        try:
            all_ok = process_file(f) and all_ok
        except Exception as e:
            print(f"오류 발생: {e}")
            all_ok = False
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

    # 대화형 터미널에서 수동 실행할 때만 종료 전 일시정지. AI 에이전트·
    # 백그라운드·파이프 등 비-TTY 실행에서는 stdin이 EOF로 닫히지 않아
    # input()이 무한 블록되므로 isatty()로 가드 (2026-05-19).
    if sys.stdin is not None and sys.stdin.isatty():
        try:
            input("\nEnter를 눌러 종료...")
        except EOFError:
            pass
    sys.exit(exit_code)
