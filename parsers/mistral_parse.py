import os
import sys
import base64
import traceback

def main():
    try:
        from mistralai.client import Mistral
    except ImportError as e:
        print(f"오류: mistralai 패키지를 찾을 수 없습니다.")
        print(f"설치 명령: pip install mistralai")
        print(f"상세: {e}")
        return

    # API 키 설정
    try:
        api_key = os.environ["MISTRAL_API_KEY"]
    except KeyError:
        print("오류: MISTRAL_API_KEY 환경 변수가 설정되지 않았습니다.")
        print("설정 명령: export MISTRAL_API_KEY=\"your-api-key\"  (Windows: setx MISTRAL_API_KEY \"your-api-key\")")
        return

    client = Mistral(api_key=api_key)

    # MIME 타입 매핑
    MIME_TYPES = {
        '.pdf': 'application/pdf',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    }

    # 파일을 Base64로 인코딩하는 함수
    def encode_file_to_base64(file_path):
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in MIME_TYPES:
            raise ValueError(f"지원하지 않는 파일 형식입니다: {ext}")

        with open(file_path, "rb") as file:
            file_data = file.read()
            base64_encoded = base64.b64encode(file_data).decode('utf-8')
            return f"data:{MIME_TYPES[ext]};base64,{base64_encoded}"

    def get_output_filename(input_file):
        """입력 파일 경로를 기반으로 출력 파일 경로 생성"""
        dir_path = os.path.dirname(input_file)
        base_name = os.path.splitext(os.path.basename(input_file))[0]
        output_name = f"{base_name}_mistral.md"
        if dir_path:
            return os.path.join(dir_path, output_name)
        return output_name

    def process_file(input_path):
        """단일 파일 문서 파싱"""
        print(f"입력 파일: {input_path}")
        encoded_file = encode_file_to_base64(input_path)

        print("변환 중...")

        # 문서 파싱
        ocr_response = client.ocr.process(
            model="mistral-ocr-latest",
            document={
                "type": "document_url",
                "document_url": encoded_file
            },
            include_image_base64=True
        )

        # 모든 페이지를 마크다운으로 저장 (페이지 정보 포함)
        total_pages = len(ocr_response.pages)
        markdown_parts = []
        for i, page in enumerate(ocr_response.pages, 1):
            markdown_parts.append(f"<!-- Page {i}/{total_pages} -->\n\n{page.markdown}")
        markdown_content = "\n\n---\n\n".join(markdown_parts)
        output_file = get_output_filename(input_path)

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(markdown_content)

        print(f"변환 완료! {len(ocr_response.pages)}페이지, {len(markdown_content)}글자가 저장되었습니다.")
        print(f"출력 파일: {output_file}")

    # 명령줄 인수로 파일 경로 받기
    if len(sys.argv) > 1:
        input_path = sys.argv[1]
        ext = os.path.splitext(input_path)[1].lower()
        if ext not in MIME_TYPES:
            print(f"오류: 지원하지 않는 파일 형식입니다: {ext}")
            print(f"지원 형식: {', '.join(MIME_TYPES.keys())}")
            return
        if not os.path.exists(input_path):
            print(f"오류: 파일을 찾을 수 없습니다: {input_path}")
            return
        process_file(input_path)
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
