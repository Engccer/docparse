import os
import sys
import traceback

def main():
    try:
        from google import genai
        from google.genai import types
    except ImportError as e:
        print(f"오류: google-genai 패키지를 찾을 수 없습니다.")
        print(f"설치 명령: pip install google-genai")
        print(f"상세: {e}")
        return

    # API 키 설정
    try:
        api_key = os.environ["GEMINI_API_KEY"]
    except KeyError:
        print("오류: GEMINI_API_KEY 환경 변수가 설정되지 않았습니다.")
        print("설정 명령: export GEMINI_API_KEY=\"your-api-key\"  (Windows: setx GEMINI_API_KEY \"your-api-key\")")
        return

    client = genai.Client(api_key=api_key)

    # MIME 타입 매핑 (Gemini는 PDF, 이미지만 지원)
    MIME_TYPES = {
        '.pdf': 'application/pdf',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png'
    }

    def get_output_filename(input_file):
        """입력 파일 경로를 기반으로 출력 파일 경로 생성"""
        dir_path = os.path.dirname(input_file)
        base_name = os.path.splitext(os.path.basename(input_file))[0]
        output_name = f"{base_name}_gemini.md"
        if dir_path:
            return os.path.join(dir_path, output_name)
        return output_name

    def process_file(input_file):
        """단일 파일 문서 파싱"""
        ext = os.path.splitext(input_file)[1].lower()
        mime_type = MIME_TYPES[ext]

        print(f"입력 파일: {input_file} ({mime_type})")

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

        # Gemini API 호출
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                types.Part.from_bytes(data=file_data, mime_type=mime_type),
                prompt
            ]
        )

        # 결과 저장
        markdown_content = response.text
        output_file = get_output_filename(input_file)

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(markdown_content)

        print(f"변환 완료! {len(markdown_content)}글자가 저장되었습니다.")
        print(f"출력 파일: {output_file}")

    # 명령줄 인수로 파일 경로 받기
    print(f"인수: {sys.argv}")

    if len(sys.argv) > 1:
        input_file = sys.argv[1]
        print(f"입력 경로: {input_file}")

        ext = os.path.splitext(input_file)[1].lower()
        if ext not in MIME_TYPES:
            print(f"오류: 지원하지 않는 파일 형식입니다: {ext}")
            print(f"지원 형식: {', '.join(MIME_TYPES.keys())}")
            return
        if not os.path.exists(input_file):
            print(f"오류: 파일을 찾을 수 없습니다: {input_file}")
            return
        process_file(input_file)
    else:
        # 현재 디렉토리에서 지원되는 파일 찾기
        supported_files = sorted([f for f in os.listdir('.') if os.path.isfile(f) and os.path.splitext(f)[1].lower() in MIME_TYPES])
        if not supported_files:
            print("오류: 현재 디렉토리에 지원되는 파일이 없습니다.")
            print(f"지원 형식: {', '.join(MIME_TYPES.keys())}")
            return
        if len(supported_files) == 1:
            process_file(supported_files[0])
        else:
            print(f"지원되는 파일 {len(supported_files)}개 발견:")
            for i, f in enumerate(supported_files, 1):
                print(f"  {i}. {f}")
            print()
            print("1) 하나씩 선택하여 변환")
            print("2) 모두 변환")
            choice = input("선택 (1/2): ").strip()
            print()

            if choice == "2":
                for i, f in enumerate(supported_files, 1):
                    print(f"[{i}/{len(supported_files)}] {f}")
                    try:
                        process_file(f)
                    except Exception as e:
                        print(f"오류 발생: {e}")
                    print()
            else:
                for i, f in enumerate(supported_files, 1):
                    yn = input(f"[{i}/{len(supported_files)}] {f} 변환? (Y/N): ").strip().upper()
                    if yn == "Y":
                        try:
                            process_file(f)
                        except Exception as e:
                            print(f"오류 발생: {e}")
                    else:
                        print("건너뜀.")
                    print()


if __name__ == "__main__":
    try:
        main()
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
