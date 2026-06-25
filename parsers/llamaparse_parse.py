import os
import sys
import traceback


def main():
    try:
        from llama_cloud import Client
    except ImportError as e:
        print(f"오류: llama-cloud 패키지를 찾을 수 없습니다.")
        print(f"설치 명령: pip install llama-cloud")
        print(f"상세: {e}")
        return

    # API 키 설정
    try:
        api_key = os.environ["LLAMAPARSE_API_KEY"]
    except KeyError:
        print("오류: LLAMAPARSE_API_KEY 환경 변수가 설정되지 않았습니다.")
        print('설정 명령: setx LLAMAPARSE_API_KEY "your-api-key"')
        return

    client = Client(api_key=api_key)

    # 지원 형식 (LlamaParse는 130+ 포맷 지원)
    SUPPORTED_EXTS = {
        '.pdf', '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif',
        '.docx', '.doc', '.pptx', '.ppt', '.xlsx', '.xls',
        '.html', '.htm', '.txt', '.csv', '.rtf', '.epub',
    }

    TIERS = ['fast', 'cost_effective', 'agentic', 'agentic_plus']

    def get_output_filename(input_file):
        """입력 파일 경로를 기반으로 출력 파일 경로 생성"""
        dir_path = os.path.dirname(input_file)
        base_name = os.path.splitext(os.path.basename(input_file))[0]
        output_name = f"{base_name}_llamaparse.md"
        if dir_path:
            return os.path.join(dir_path, output_name)
        return output_name

    def estimate_credits(input_file, tier):
        """파일 페이지 수 추정 및 크레딧 계산"""
        credits_per_page = {'fast': 1, 'cost_effective': 3, 'agentic': 10, 'agentic_plus': 45}
        try:
            import fitz
            doc = fitz.open(input_file)
            pages = len(doc)
            doc.close()
        except Exception:
            pages = None
        if pages:
            cost = pages * credits_per_page.get(tier, 10)
            return pages, cost
        return None, None

    def process_file(input_file, tier='agentic', language='ko', custom_prompt=None):
        """단일 파일 문서 파싱 (LlamaParse API v2)"""
        print(f"입력 파일: {input_file}")

        # 파일 크기 확인
        file_size = os.path.getsize(input_file)
        file_size_mb = file_size / (1024 * 1024)
        print(f"파일 크기: {file_size_mb:.1f} MB")
        print(f"파싱 티어: {tier} / 언어: {language}")
        if custom_prompt:
            preview = custom_prompt.replace('\n', ' ')[:80]
            print(f"커스텀 지시: {preview}...")

        # 크레딧 추정
        pages, cost = estimate_credits(input_file, tier)
        if pages:
            print(f"페이지 수: {pages} / 예상 크레딧: {cost}")

        print("변환 중...")

        # v2 최적 옵션 구성
        processing_options = {
            'ocr_parameters': {
                'languages': [language]
            }
        }
        output_options = {
            'markdown': {
                'annotate_links': True,
                'tables': {
                    'output_tables_as_markdown': True,
                    'merge_continued_tables': True,
                }
            }
        }

        # 커스텀 지시 (agentic·agentic_plus 티어에서만 유효)
        parse_kwargs = {}
        if custom_prompt:
            if tier in ('agentic', 'agentic_plus'):
                parse_kwargs['agentic_options'] = {'custom_prompt': custom_prompt}
            else:
                print(f"[경고] --instructions는 agentic/agentic_plus 티어에서만 적용됩니다. 현재 티어({tier})에서는 무시됩니다.")

        # 파일 업로드 및 파싱 (동기, 완료까지 폴링)
        with open(input_file, "rb") as f:
            result = client.parsing.parse(
                tier=tier,
                version="latest",
                upload_file=f,
                expand=["markdown_full", "text_full"],
                verbose=True,
                processing_options=processing_options,
                output_options=output_options,
                **parse_kwargs,
            )

        # 결과 추출
        markdown_content = getattr(result, 'markdown_full', None) or getattr(result, 'text_full', None) or "(내용 없음)"

        # 결과 저장
        output_file = get_output_filename(input_file)
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(markdown_content)

        print(f"변환 완료! {len(markdown_content)}글자가 저장되었습니다.")
        print(f"출력 파일: {output_file}")

    # 명령줄 인수 처리
    print(f"인수: {sys.argv}")

    # 옵션 파싱
    tier = 'agentic'
    language = 'ko'
    check_credits = False
    custom_prompt = None
    files_to_process = []

    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == '--tier' and i + 1 < len(sys.argv):
            tier = sys.argv[i + 1]
            if tier not in TIERS:
                print(f"오류: 지원하지 않는 파싱 티어: {tier}")
                print(f"지원 티어: {', '.join(TIERS)}")
                return
            i += 2
        elif arg == '--lang' and i + 1 < len(sys.argv):
            language = sys.argv[i + 1]
            i += 2
        elif arg == '--credits':
            check_credits = True
            i += 1
        elif arg == '--instructions' and i + 1 < len(sys.argv):
            instr_path = sys.argv[i + 1]
            if not os.path.exists(instr_path):
                print(f"오류: --instructions 파일을 찾을 수 없습니다: {instr_path}")
                return
            with open(instr_path, 'r', encoding='utf-8') as f:
                custom_prompt = f.read().strip()
            if not custom_prompt:
                print(f"오류: --instructions 파일이 비어 있습니다: {instr_path}")
                return
            i += 2
        elif arg in ('--help', '-h'):
            print("사용법: python llamaparse_parse.py [옵션] [파일경로]")
            print()
            print("옵션:")
            print("  --tier TIER          파싱 티어 (fast, cost_effective, agentic, agentic_plus)")
            print(f"                       기본값: agentic (10크레딧/페이지)")
            print("  --lang LANG          OCR 언어 코드 (예: ko, en, ja, zh)")
            print(f"                       기본값: ko")
            print("  --instructions FILE  자연어 파싱 지시(custom_prompt) 파일 경로")
            print("                       agentic·agentic_plus 티어에서만 적용")
            print("                       예: 이미지 alt text 한국어 상세화, 헤딩 중복 억제 등")
            print("  --credits            남은 크레딧 및 갱신일 확인")
            print()
            print("v2 기본 옵션: OCR 언어 자동 설정, 연속 표 병합, 링크 주석")
            print("티어별 크레딧: fast(1) / cost_effective(3) / agentic(10) / agentic_plus(45)")
            print("지원 형식: PDF, JPG, PNG, DOCX, PPTX, XLSX, HTML, TXT 등 130+")
            print("환경변수: LLAMAPARSE_API_KEY")
            print("무료: 월 10,000 크레딧 (cloud.llamaindex.ai)")
            print()
            print("예시:")
            print("  python llamaparse_parse.py document.pdf")
            print("  python llamaparse_parse.py --tier cost_effective report.pdf")
            print("  python llamaparse_parse.py --instructions accessible.txt manual.pdf")
            print("  python llamaparse_parse.py --credits")
            print("  python llamaparse_parse.py  (현재 폴더에서 자동 탐색)")
            return
        else:
            files_to_process.append(arg)
            i += 1

    if check_credits:
        try:
            import httpx
            headers = {'Authorization': f'Bearer {api_key}'}
            r = httpx.get('https://api.cloud.llamaindex.ai/api/v1/projects', headers=headers, timeout=10)
            org_id = r.json()[0]['organization_id']
            r = httpx.get(f'https://api.cloud.llamaindex.ai/api/v1/organizations/{org_id}/usage', headers=headers, timeout=10)
            data = r.json()
            plan = data['plan']
            usage = data['usage']
            print(f"플랜: {plan['name']}")
            print(f"빌링 기간: {plan['current_billing_period']['start_date'][:10]} ~ {plan['current_billing_period']['end_date'][:10]}")
            for grant in usage.get('active_free_credits_usage', []):
                print(f"크레딧: {grant['remaining_balance']:,} / {grant['starting_balance']:,} (갱신: {grant['expires_at'][:10]})")
        except Exception as e:
            print(f"크레딧 조회 실패: {e}")
        if not files_to_process:
            return

    if files_to_process:
        for input_file in files_to_process:
            ext = os.path.splitext(input_file)[1].lower()
            if ext not in SUPPORTED_EXTS:
                print(f"오류: 지원하지 않는 파일 형식입니다: {ext}")
                print(f"지원 형식: {', '.join(sorted(SUPPORTED_EXTS))}")
                continue
            if not os.path.exists(input_file):
                print(f"오류: 파일을 찾을 수 없습니다: {input_file}")
                continue
            process_file(input_file, tier, language, custom_prompt)
    else:
        # 현재 디렉토리에서 지원되는 파일 찾기
        supported_files = sorted([
            f for f in os.listdir('.')
            if os.path.isfile(f) and os.path.splitext(f)[1].lower() in SUPPORTED_EXTS
        ])
        if not supported_files:
            print("오류: 현재 디렉토리에 지원되는 파일이 없습니다.")
            print(f"지원 형식: {', '.join(sorted(SUPPORTED_EXTS))}")
            return
        if len(supported_files) == 1:
            process_file(supported_files[0], tier, language, custom_prompt)
        else:
            print(f"지원되는 파일 {len(supported_files)}개 발견:")
            for idx, f in enumerate(supported_files, 1):
                print(f"  {idx}. {f}")
            print()
            print("1) 하나씩 선택하여 변환")
            print("2) 모두 변환")
            choice = input("선택 (1/2): ").strip()
            print()

            if choice == "2":
                for idx, f in enumerate(supported_files, 1):
                    print(f"[{idx}/{len(supported_files)}] {f}")
                    try:
                        process_file(f, tier, language, custom_prompt)
                    except Exception as e:
                        print(f"오류 발생: {e}")
                    print()
            else:
                for idx, f in enumerate(supported_files, 1):
                    yn = input(f"[{idx}/{len(supported_files)}] {f} 변환? (Y/N): ").strip().upper()
                    if yn == "Y":
                        try:
                            process_file(f, tier, language, custom_prompt)
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
