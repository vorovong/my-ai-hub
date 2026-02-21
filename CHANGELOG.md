# Changelog

## v3.2 — 코드 리팩토링 (2026-02-21)

### 구조 개선
- **CSS/JS 분리**: 인라인 280줄 → `static/styles.css` + `static/app.js` 외부 파일로 추출
- **CONFIG 딕셔너리**: 매직 넘버 13개를 파일 상단 1곳으로 통합
- **함수 분리**: `process_with_gemini` (109줄) → `_build_gemini_prompt` + `_call_gemini_with_retry` + `_parse_gemini_response` 3개로 분리
- **전역 상태 제거**: `gemini_client` 전역 변수 → `main()`에서 생성 후 인자 전달
- **헬퍼 함수 추가**: `_trust_stars()`, `_load_asset()`, `_build_filter_buttons()` — 중복 코드 제거
- **타입 힌트**: 모든 public 함수에 타입 힌트 추가

### 파일 변경
| 파일 | 변경 |
|------|------|
| `collect_news.py` | 809줄 → 616줄 (-24%) |
| `static/styles.css` | 신규 (148줄, CSS 추출) |
| `static/app.js` | 신규 (131줄, JS 추출 + 유니코드→한국어) |
| `daily-update.yml` | exclude_assets에 static/ 추가 |

### 테스트 결과
- Import + 기본 함수: 통과
- 19/19 RSS 피드 파싱: 통과
- HTML 생성 + 구조 비교: 통과 (리팩토링 전후 동일)

---

## v3.1 — 공식 소스 확장 (2026-02-21)

### 소스 추가 (6개)
- **Anthropic News** — 빅3 중 유일하게 누락되었던 Claude 개발사 (RSS 없음, 수동)
- **Midjourney Updates** — 이미지 생성 AI 대표 (`updates.midjourney.com/rss/`)
- **Kling AI** — 영상 생성 AI, Kuaishou (RSS 없음, 수동)
- **Suno** — 음악 생성 AI (RSS 없음, 수동)
- **Figma Blog** — AI 디자인 도구 (`figma.com/blog/feed/atom.xml`)
- **ElevenLabs** — 음성/TTS AI (`elevenlabs.io/docs/changelog.rss`)

### 현황
- 총 27개 소스 (19개 RSS 자동, 8개 수동)
- 콘텐츠 생성(content_creation) 카테고리 소스 대폭 강화
- 19개 RSS 전체 파싱 테스트 통과 (실패 0, 느린 소스 0)

---

## v3.0 — 피드백 전면 반영 + 마이그레이션 (2026-02-21)

### 콘텐츠 구조 재설계
- "왜 중요한가?" → **"나에게 미치는 영향" (my_impact)** 으로 교체
  - 기사 반복이 아닌, "내가 당장 할 수 있는 것/주의할 것" 관점
  - 보라색 화살표(→)로 요약 바로 아래 노출
- 핵심 포인트는 "자세히 보기" 접기 안으로 이동
- 모든 텍스트 개조식 명사구(-음/-임)로 변경

### 모바일 UX (업계 표준 적용)
- 본문 16px, 제목 17px, 보조 텍스트 15px (Apple HIG 기준)
- 터치 타겟 44px 최소 높이 (네비, 필터 버튼, 셀렉트)
- iOS 자동 확대 방지, 더블탭 줌 딜레이 제거

### 아카이브 필터
- 아카이브 탭에 카테고리 필터 버튼 추가
- 날짜 변경 시 필터 자동 리셋

### 기술 부채 해소
- google-generativeai → **google-genai** SDK 마이그레이션 (기존 SDK 2025-11 지원 종료)

---

## v2.2 — 타임존 버그 수정 (2026-02-21)

- GitHub Actions UTC 기준 → KST 변환 (datetime.now(KST))
- 사이트에 하루 전 날짜로 표시되던 버그 해결

---

## v2.1 — UX 개선 (2026-02-21)

- 요약 2-3문장으로 복원 (너무 짧았음)
- 핵심 포인트 기본 노출 (접기 제거)
- "자세히 보기" → "왜 중요한가?" 라벨 변경
- 카테고리 균형 규칙 (content 최소 3개, insight 40% 이하)
- 모바일 반응형 CSS 기초 추가

---

## v2.0 — 안정성 + 아카이브 + 깊이 (2026-02-21)

### 안정성
- Gemini JSON 파싱 에러 시 최대 2회 재시도
- 소스당 최대 3개 제한 (다양성 보장)
- Gemini 완전 실패 시 이전 아카이브에서 자동 복구

### 아카이브
- 날짜별 뉴스 자동 저장 (archive/날짜.json)
- 아카이브 탭에서 지난 뉴스 열람 가능

### 콘텐츠 깊이
- 기사 원문 크롤링 (trafilatura, 최대 3000자)
- 유튜브 자막 추출 (한국어 우선, 영어 fallback)
- Gemini 프롬프트 개선: 요약 + 핵심 포인트 3개 + 의미/전망

### 소스 확장
- GeekNews RSS 복구
- Hugging Face Blog, Matt Wolfe, The Rundown AI, Stability AI 추가
- 총 21개 소스 (16개 자동, 5개 수동)

---

## v1.0 — 첫 번째 버전 (2026-02-20)

- RSS 피드에서 AI 뉴스 자동 수집
- Gemini 2.5 Flash로 요약/분류
- GitHub Actions로 매일 KST 08시 자동 실행
- GitHub Pages에 자동 배포
- 17개 소스 등록 (12개 자동 수집)
- 카테고리: 모델/빅3, 개발, 콘텐츠 생성, 인사이트, 팁
