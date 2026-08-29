"""Gemini 문서 파서 (docparse).

  python gemini_parse.py "<파일.pdf|.jpg|.png>" [--thinking]   → <파일>_gemini.md

실패 계약(2026-08-31): 응답 text가 None이거나 finish_reason이 MAX_TOKENS(출력이
잘림)면 출력 파일을 만들지 않고 종료 코드 1. 종전에는 잘린 결과를 경고만 찍고
완료본으로 저장해, 뒷부분이 없는 파일이 퓨전에 편입될 수 있었다. 실행 시작 시
같은 이름의 이전 출력을 지운다.
"""
import os
import sys
import traceback


def main():
    """반환값이 종료 코드다(0 성공 / 1 실패)."""
    try:
        from google import genai
        from google.genai import types
    except ImportError as e:
        print("오류: google-genai 패키지를 찾을 수 없습니다.")
        print("설치 명령: pip install google-genai")
        print(f"상세: {e}")
        return 1

    # API 키 설정
    try:
        api_key = os.environ["GEMINI_API_KEY"]
    except KeyError:
        print("오류: GEMINI_API_KEY 환경 변수가 설정되지 않았습니다.")
        print("설정 명령: export GEMINI_API_KEY=\"your-api-key\"  (Windows: setx GEMINI_API_KEY \"your-api-key\")")
        return 1

    client = genai.Client(api_key=api_key)

    # MIME 타입 매핑 (Gemini는 PDF, 이미지만 지원)
    MIME_TYPES = {
        '.pdf': 'application/pdf',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png'
    }

    # 명령줄 인수 파싱 (--thinking 옵션 분리)
    use_thinking = "--thinking" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--thinking"]

    def get_output_filename(input_file):
        """입력 파일 경로를 기반으로 출력 파일 경로 생성"""
        dir_path = os.path.dirname(input_file)
        base_name = os.path.splitext(os.path.basename(input_file))[0]
        output_name = f"{base_name}_gemini.md"
        if dir_path:
            return os.path.join(dir_path, output_name)
        return output_name

    def clear_stale_output(output_file):
        if os.path.exists(output_file):
            os.remove(output_file)
            print(f"기존 출력 제거: {output_file}")

    def process_file(input_file):
        """단일 파일 문서 파싱. 출력 파일을 만들었으면 True."""
        ext = os.path.splitext(input_file)[1].lower()
        mime_type = MIME_TYPES[ext]

        print(f"입력 파일: {input_file} ({mime_type})")
        output_file = get_output_filename(input_file)
        clear_stale_output(output_file)

        # 파일 크기 확인
        file_size = os.path.getsize(input_file)
        file_size_mb = file_size / (1024 * 1024)
        print(f"파일 크기: {file_size_mb:.1f} MB")

        # 파일 읽기
        with open(input_file, "rb") as f:
            file_data = f.read()

        # 프롬프트 설정
        prompt = """당신은 문서에서 데이터를 정밀하게 추출하는 전문 문서 파싱 엔지니어입니다. 다음 지침을 준수하여 이 문서의 모든 내용을 마크다운으로 변환하세요.

[텍스트 추출 원칙]
- 텍스트를 임의로 요약하거나 생략하지 말고, 원본 그대로 보존하세요.
- 제목, 본문, 목록 등 문서 구조를 마크다운으로 표현하세요.
- 이미지는 [이미지: 설명] 형식으로 표시하세요.

[표 처리]
- 표가 있다면 마크다운 표로 변환하세요.
- 병합된 셀은 해당되는 모든 행에 반복 기재하세요.
- 빈 셀은 '-'로 표기하여 누락과 구분하세요.
- 셀 내부의 텍스트와 숫자를 있는 그대로 보존하세요.

[요약 통계]
- 문서에 요약 통계(합계, 일수, 시수 등)가 있다면 별도 섹션으로 분리하여 빠짐없이 기재하세요.

[참고사항]
- 문서 하단의 범례, 주석, 각주도 누락 없이 추출하세요.
- 식별이 불확실한 텍스트는 추측하지 말고 '(식별 불확실)' 표기를 하세요."""

        print("변환 중...")

        # gemini-flash-latest는 서버측 최상위 stable flash 별칭이라 세대가 자동으로 따라온다
        # (2026-06-28 확인 시 gemini-3.5-flash, 2026-08-26 확인 시 gemini-3.7-flash). 전부 thinking 모델.
        # 기본은 thinking 비활성화: thinking을 켜면 장문(≳20p)에서 전사 대신 "요약"으로 빠져
        # 본문 대부분을 조용히 버리고 완결된 문서처럼 위장하는 부작용이 있다(187p 실측). max_output_tokens도
        # 상향해 truncation을 줄인다. --thinking 옵션으로 켜면 수기 체크박스·한글이름 판독 정밀도가
        # 올라가나(소형 문서 보조 패치용), 장문 전사 Primary로는 끄고 쓴다.
        gen_config = types.GenerateContentConfig(max_output_tokens=65536)
        if not use_thinking:
            gen_config.thinking_config = types.ThinkingConfig(thinking_budget=0)

        def _call():
            return client.models.generate_content(
                model="gemini-flash-latest",
                contents=[
                    types.Part.from_bytes(data=file_data, mime_type=mime_type),
                    prompt
                ],
                config=gen_config,
            )

        # Gemini API 호출 (thinking 모델은 간헐적으로 text=None 응답을 반환 → 1회 재시도)
        response = _call()
        markdown_content = response.text
        if markdown_content is None:
            print("경고: 빈 응답(text=None) 수신, 1회 재시도합니다...")
            response = _call()
            markdown_content = response.text
        if markdown_content is None:
            fr = response.candidates[0].finish_reason if response.candidates else "?"
            print(f"오류: 텍스트 추출 실패 (finish_reason={fr}). 출력 파일을 생성하지 않습니다.")
            return False
        # 장문 truncation: 잘린 결과는 완료본이 아니다(뒷부분이 조용히 빠진 채 퓨전에 편입 방지)
        if response.candidates and "MAX_TOKENS" in str(response.candidates[0].finish_reason):
            print("오류: 출력이 max_output_tokens(65536)에 도달해 잘렸습니다. 출력 파일을 만들지 않았습니다.")
            print("  장문 문서는 Gemini 부적합 — LlamaParse v2/Mistral를 Primary로 쓰세요.")
            return False
        if not markdown_content.strip():
            print("오류: 응답 본문이 비어 있습니다. 출력 파일을 만들지 않았습니다.")
            return False

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(markdown_content)

        print(f"변환 완료! {len(markdown_content)}글자가 저장되었습니다.")
        print(f"출력 파일: {output_file}")
        return True

    print(f"인수: {sys.argv} (thinking={'ON' if use_thinking else 'OFF'})")

    if len(args) > 0:
        input_file = args[0]
        print(f"입력 경로: {input_file}")

        ext = os.path.splitext(input_file)[1].lower()
        if ext not in MIME_TYPES:
            print(f"오류: 지원하지 않는 파일 형식입니다: {ext}")
            print(f"지원 형식: {', '.join(MIME_TYPES.keys())}")
            return 1
        if not os.path.exists(input_file):
            print(f"오류: 파일을 찾을 수 없습니다: {input_file}")
            return 1
        return 0 if process_file(input_file) else 1

    # 현재 디렉토리에서 지원되는 파일 찾기
    supported_files = sorted([f for f in os.listdir('.') if os.path.isfile(f) and os.path.splitext(f)[1].lower() in MIME_TYPES])
    if not supported_files:
        print("오류: 현재 디렉토리에 지원되는 파일이 없습니다.")
        print(f"지원 형식: {', '.join(MIME_TYPES.keys())}")
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
