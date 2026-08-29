"""Mistral OCR 파서 (docparse).

  python mistral_parse.py "<파일>"   → <파일>_mistral.md

실패 계약(2026-08-31): 전체 결과가 비거나, PDF 페이지 수(PyMuPDF)와 응답 페이지
수가 다르면 출력 파일을 만들지 않고 종료 코드 1(일부 쪽이 빠진 파일을 완료본으로
남기지 않는다). 실행 시작 시 같은 이름의 이전 출력을 지운다.
"""
import os
import sys
import base64
import traceback


def main():
    """반환값이 종료 코드다(0 성공 / 1 실패)."""
    try:
        from mistralai.client import Mistral
    except ImportError as e:
        print("오류: mistralai 패키지를 찾을 수 없습니다.")
        print("설치 명령: pip install mistralai")
        print(f"상세: {e}")
        return 1

    # API 키 설정
    try:
        api_key = os.environ["MISTRAL_API_KEY"]
    except KeyError:
        print("오류: MISTRAL_API_KEY 환경 변수가 설정되지 않았습니다.")
        print("설정 명령: export MISTRAL_API_KEY=\"your-api-key\"  (Windows: setx MISTRAL_API_KEY \"your-api-key\")")
        return 1

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

    def clear_stale_output(output_file):
        if os.path.exists(output_file):
            os.remove(output_file)
            print(f"기존 출력 제거: {output_file}")

    def pdf_page_count(path):
        """PyMuPDF로 원본 PDF 쪽수. 미가용이면 None."""
        try:
            try:
                import pymupdf as fitz
            except ImportError:
                import fitz
            with fitz.open(path) as doc:
                return len(doc)
        except Exception:
            return None

    def process_file(input_path):
        """단일 파일 문서 파싱. 출력 파일을 만들었으면 True."""
        print(f"입력 파일: {input_path}")
        output_file = get_output_filename(input_path)
        clear_stale_output(output_file)
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
        if total_pages == 0:
            print("오류: 응답에 페이지가 없습니다. 출력 파일을 만들지 않았습니다.")
            return False
        if input_path.lower().endswith(".pdf"):
            expected = pdf_page_count(input_path)
            if expected is not None and expected != total_pages:
                print(f"오류: 원본 {expected}쪽인데 응답은 {total_pages}쪽입니다. 부분 결과를 저장하지 않습니다.")
                return False

        markdown_parts = []
        empty_pages = []
        for i, page in enumerate(ocr_response.pages, 1):
            body = page.markdown or ""
            if not body.strip():
                empty_pages.append(i)
            markdown_parts.append(f"<!-- Page {i}/{total_pages} -->\n\n{body}")
        markdown_content = "\n\n---\n\n".join(markdown_parts)
        if len(empty_pages) == total_pages:
            print("오류: 모든 페이지의 결과가 비어 있습니다. 출력 파일을 만들지 않았습니다.")
            return False

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(markdown_content)

        print(f"변환 완료! {total_pages}페이지, {len(markdown_content)}글자가 저장되었습니다.")
        if empty_pages:
            shown = ", ".join(str(p) for p in empty_pages[:20])
            print(f"경고: 내용이 빈 페이지 {len(empty_pages)}쪽: {shown}{' ...' if len(empty_pages) > 20 else ''}")
            print("  (백지·그림 전용 쪽이면 정상. 본문이 있는 쪽이면 다른 파서로 그 쪽을 보완할 것)")
        print(f"출력 파일: {output_file}")
        return True

    # 명령줄 인수로 파일 경로 받기
    if len(sys.argv) > 1:
        input_path = sys.argv[1]
        ext = os.path.splitext(input_path)[1].lower()
        if ext not in MIME_TYPES:
            print(f"오류: 지원하지 않는 파일 형식입니다: {ext}")
            print(f"지원 형식: {', '.join(MIME_TYPES.keys())}")
            return 1
        if not os.path.exists(input_path):
            print(f"오류: 파일을 찾을 수 없습니다: {input_path}")
            return 1
        return 0 if process_file(input_path) else 1

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
