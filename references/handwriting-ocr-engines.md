# 손글씨(HTR)·충실 전사용 OCR 엔진 레퍼런스

손글씨 위주 스캔 문서를 **충실 전사(diplomatic transcription)**할 때의 엔진 선택 자료. tier-rules.md "손글씨 위주 스캔 문서" 섹션의 보충. 2026-06 deep-research 서베이 + 한 학급 22장 실측 + 확립된 API 사실을 종합.

> **신뢰도 주의**: 일부 출처는 deep-research 워크플로우에서 수집됐으나 적대적 검증 단계가 rate limit으로 무력화됐다(미검증·미반박). confidence score 제공 여부·로컬 가능 여부·언어 지원은 **확립된 API 기능 사실**이고, 정확도 수치·가격은 **변동성이 있어 도입 직전 재확인** 필요. 한 학급 한국어 학생 손글씨 실측(Tesseract·Google Vision)만 본 환경 직접 검증분이다.

## 평가 6기준

1. **충실성(fidelity)**: 오기·비표준 철자를 매끄럽게 교정하지 않고 원형 출력하는가. 환각(없는 단어/인명 생성) 위험.
2. **confidence score**: 단어·글자 단위 신뢰도를 제공해 시각 확인 표적을 자동 생성하는가. (후처리 공수 절감의 핵심)
3. **손글씨(HTR) 정확도**: 자유 서술 손글씨에서의 실측 정확도(CER/WER).
4. **언어 지원**: 영어 손글씨 + 한국어 손글씨.
5. **개인정보/로컬**: 온프레미스·오프라인 처리 가능 여부, 클라우드의 데이터 보존·학습 정책.
6. **통합 난이도·비용**.

## 엔진 비교 매트릭스

| 엔진 | 유형 | 단어별 conf | 영어 손글씨 | 한글 손글씨 | 오기 보존(충실성) | 로컬/PII 안전 | 비용(재확인) |
|------|------|:---:|:---:|:---:|:---:|:---:|------|
| **Google Cloud Vision** (DOCUMENT_TEXT_DETECTION) | 클라우드 OCR | **O (글자·단어·블록)** | **상** (답안지 1위급) | 중상 | 상(LM 약함) | ✗ 클라우드 | ~$1.5/1000p, 1000p/월 무료 |
| **Azure AI Vision Read / Document Intelligence** | 클라우드 OCR | **O (단어·줄)** | **상** (3사 중 손글씨 최강) | 중 | 상 | ✗ 클라우드 | ~$1.5/1000p, F0 500p/월 |
| **Amazon Textract** | 클라우드 OCR | **O (단어 0~100)** | 중상 | 중(약함) | 상 | ✗ 클라우드 | ~$1.5/1000p |
| **Naver CLOVA OCR** | 클라우드 OCR | **O (inferConfidence)** | **✗ 영어는 인쇄체만** | **상** (한·일 손글씨 특화) | 상 | ✗ 클라우드(국내) | 호출당 과금 |
| **TrOCR** (Microsoft) | 로컬 Transformer HTR | △ (logit 직접 계산) | **상** (IAM CER~3%) | ✗ (한글 모델 없음) | 중(약한 LM 정규화) | **O 완전 로컬** | 무료 |
| **PaddleOCR** | 로컬 OCR | **O (줄 단위)** | 중(인쇄 위주) | 중(ko 모델, 인쇄 위주) | 상 | **O 완전 로컬** | 무료 |
| **EasyOCR** | 로컬 OCR | **O (검출 단위)** | 중 | 중(인쇄 위주) | 상 | **O 완전 로컬** | 무료 |
| **docTR** | 로컬 OCR | O | 중 | 제한 | 상 | **O 완전 로컬** | 무료 |
| **Tesseract 5** (LSTM) | 로컬 OCR | O (`image_to_data`) | **하 (~38%)** | 하 | 상 | **O 완전 로컬** | 무료 |
| **Transkribus** (PyLaia/HTR+/Titan) | HTR 플랫폼(클라우드) | △ (CER 측정, 예측 conf 약함) | 상(모델 학습 시) | 미명시 | 중(LM 정규화) | △ EU호스팅·48h삭제, 온프렘 예정/요청 | 무료 50p/월, ~0.24€/p |
| **kraken / Calamari / PyLaia / OCRopus** | 로컬 HTR(디지털 인문학) | 부분 | 상(학습 시) | 제한 | 상 | **O 완전 로컬** | 무료(학습·셋업 부담 큼) |
| **ABBYY FineReader / Cloud OCR SDK** | 상용(ICR) | O | 중상 | 제한 | △(온프렘 제품 있음) | 상용 라이선스 |
| **MyScript iink** | 상용(필기 인식) | O | 상(잉크 기반) | 상 | SDK | 상용 |
| 참고: LlamaParse v2 / Upstage / Mistral / Gemini | LLM 파서 | **✗ 없음** | N/A | N/A | **하(자동교정·환각)** | ✗ 클라우드 | 기존 |

## 기준별 핵심 발견

### 충실성 (오기 보존)
- **전통 OCR(글자 인식 모델)은 강한 생성형 LM이 없어** 오기를 사전형으로 고치지 않는다. 오인식이 나도 *깨진 글자·저신뢰*로 드러나 잡기 쉽다(*그럴듯한 가짜*가 아님).
- **언어모델을 붙인 HTR(TrOCR·Transkribus LM)은 정확도는 오르나 표준 철자·약어로 정규화**된다([PMC12202554](https://pmc.ncbi.nlm.nih.gov/articles/PMC12202554/)) → 충실 전사에는 LM 보정을 끄는 게 유리(정확도↑가 충실성↓일 수 있음).
- **LLM 비전모델은 "고치지 말라"고 해도 저신뢰 단어를 의미가 가까운 다른 단어로 조용히 치환**([handwritingocr.com](https://www.handwritingocr.com/blog/best-ai-handwriting-ocr)). 관측된 `Dear me→Mr. Han` 사례와 동일 계열.

### confidence score
- Google Vision(글자·단어·블록), Azure(단어·줄), Textract(단어 0~100), CLOVA(inferConfidence), Tesseract(`image_to_data`), PaddleOCR·EasyOCR(검출 단위) 모두 제공. **TrOCR는 native 미제공**(logit에서 직접 계산 필요). **LLM 파서는 보정된 단어 confidence 없음**, 이게 결정적 차이.
- 단, **calibration 품질이 다르다**: 한 학급 실측에서 Tesseract conf는 손글씨에서 0.35~0.59로 뭉쳐 과다 flag(무용), **Google Vision은 0.91~0.99·저신뢰 중앙 ~7%로 잘 calibrated**.

### 손글씨 정확도
- Tesseract 손글씨 ~38%로 사실상 부적합([eklavvya](https://www.eklavvya.com/blog/best-ocr-answersheet-evaluation/)), Tesseract는 인쇄체 도구.
- 클라우드 3사 80~95%, 답안지 평가에서 Google Vision 1위(eklavvya). 손글씨 한정 우열 Microsoft(Azure) > Google > Amazon([dataturks](https://dataturks.com/blog/compare-image-text-recognition-apis.php), 2020 기준·재확인 필요).
- TrOCR는 단일 라인 손글씨(IAM) CER~3%로 강하나 줄 분할 선행 + conf 없음(통합 부담).
- Transkribus는 자기 데이터로 모델 학습 시 강함(역사 필사 특화).

### 언어 지원 (영어 + 한국어 손글씨)
- **한글 손글씨 최강: Naver CLOVA**(한·일 손글씨 특화). 단 **영어는 인쇄체만** 손글씨 미지원 → 영어 본문엔 못 씀, 한글 이름 필드 전용([CLOVA OCR](https://www.ncloud.com/product/aiService/ocr)).
- Google Vision: 영어 손글씨 상 + 한글 지원(중상). 한 학급 실측에서 한글 인쇄 양식 정상, 한글 손글씨 이름은 오독 가능하나 **저신뢰로 flag**(예: 3글자 한글 이름 오독을 conf 0.16으로 표시).
- TrOCR·kraken 등은 한글 손글씨 사전학습 모델이 사실상 없음.

### 개인정보/로컬
- 완전 로컬·오프라인·PII 안전: Tesseract·PaddleOCR·EasyOCR·docTR·TrOCR·kraken/Calamari/PyLaia.
- 클라우드(Google/Azure/AWS): 데이터 전송. 3사 모두 "고객 데이터로 모델 학습 안 함" 엔터프라이즈 약관 제공(도입 시 약관 확인). 단 전송 자체가 민감정보(학생·환자) 정책과 충돌할 수 있음.
- Transkribus: EU(오스트리아) 호스팅·GDPR, Metagrapho API 48h 내 삭제, 온프렘은 "예정/요청"([transkribus privacy](https://legal.transkribus.org/privacy)).

## 시나리오별 추천

| 상황 | 1순위 | 비고 |
|------|-------|------|
| 영어 손글씨 본문 + 충실성 + 표적 검증 | **Google Vision** 또는 Azure Read | 정확도+calibrated conf. `gcloud` 보유 시 Vision이 마찰 최소 |
| 한글 손글씨 이름·필드 직접 인식 | **Naver CLOVA** | 영어 손글씨 미지원. 명부 대조로 대체 가능하면 불필요 |
| 완전 로컬·PII 절대조건(영어) | **TrOCR**(정확) 또는 PaddleOCR/EasyOCR(간편) | TrOCR는 줄 분할+conf 부재, 통합 부담. Tesseract는 손글씨 부적합 |
| 역사 필사·대량 동일 필체(커스텀 학습 가능) | **Transkribus**(PyLaia/Titan) | 자기 데이터 학습 전제. 클라우드 |
| 요지만 필요(충실성 비-critical) | 기존 LLM 파서 | 매끄러운 출력이 오히려 편리 |

## 본 환경 실측 결론 (한 학급 22장)

- **Google Vision**: 영어 손글씨 충실 보존 + ~7% 저신뢰가 실제 쟁점에 정확 안착 → docparse 손글씨 파이프라인 ②번 엔진으로 채택(`parsers/gvision_parse.py`).
- **Tesseract**: 충실성은 OK이나 손글씨 conf calibration 무용 → 완전 로컬·PII 절대조건의 폴백으로만(③ diff 신호 의존).
- 미실측(향후 후보): Azure Read(손글씨 최강 후보), Naver CLOVA(한글 이름), TrOCR(로컬 정확). 필요 시 추가 PoC.

## 출처

- [PMC12202554: HTR 엔진 CER·LM 정규화](https://pmc.ncbi.nlm.nih.gov/articles/PMC12202554/)
- [handwritingocr.com: LLM 자동교정/환각](https://www.handwritingocr.com/blog/best-ai-handwriting-ocr)
- [eklavvya: 답안지 OCR 정확도(Tesseract~38%, Google Vision 1위)](https://www.eklavvya.com/blog/best-ocr-answersheet-evaluation/)
- [dataturks: Google/Azure/Amazon 손글씨 비교(2020)](https://dataturks.com/blog/compare-image-text-recognition-apis.php) · [aimultiple OCR 정확도](https://aimultiple.com/ocr-accuracy)
- [Naver CLOVA OCR(한·일 손글씨)](https://www.ncloud.com/product/aiService/ocr) · [API 가이드](https://api.ncloud-docs.com/docs/ai-application-service-ocr)
- [Transkribus 비교·요금·개인정보](https://www.transkribus.org/text-recognition-api-comparison) · [plans](https://www.transkribus.org/plans) · [privacy](https://legal.transkribus.org/privacy)
