# ai-news-hub 개발 프로세스

## 프로젝트 개요
- **목적**: AI 뉴스 자동 수집 + 요약 + 아카이브
- **사이트**: https://vorovong.github.io/my-ai-hub/
- **레포**: https://github.com/vorovong/my-ai-hub
- **자동화**: 매일 KST 08시 GitHub Actions 실행

---

## v1 — 초기 구축 (2026-02-20)

첫 미니 프로젝트로 완성. Python + Gemini 2.5 Flash + GitHub Actions + GitHub Pages.

- sources.json에 17개 소스 등록 (12개 자동 수집, 5개 feed 없음)
- RSS 수집 → Gemini 요약/분류 → index.html 생성 → gh-pages 배포
- 카테고리: model, dev, content, insight, tip
- 탭: 뉴스피드 / 소스 / 팁모음(비어있음) / 에센셜지식(비어있음)

### v1 문제점 (크리틱 결과)
1. **콘텐츠 깊이 부족** — RSS 미리보기 1~2문장만 Gemini에 전달
2. **아카이브 없음** — 매일 index.html 덮어쓰기, 어제 뉴스 소멸
3. **소스 편중** — AI 개발 위주, 창작(이미지/영상/음악) 소스 부족
4. **안정성** — Gemini JSON 파싱 에러 핸들링 없음

---

## v2 — 4단계 대규모 개선 (2026-02-21)

### Phase A: 안정성 기반
- `process_with_gemini()` — JSON 파싱 에러 시 최대 2회 재시도 (`try/except` + `time.sleep(2)`)
- `ensure_source_diversity()` — 소스당 최대 3개 제한 (Gemini 호출 전 적용)
- Gemini 완전 실패 시 `load_latest_archive()`로 이전 아카이브 fallback

### Phase B: 아카이브 시스템
- `archive/{날짜}.json` 형태로 일별 저장
- `archive/archive_index.json` — 날짜 목록 자동 업데이트
- `daily-update.yml`에 `keep_files: true` 추가 → gh-pages에서 아카이브 누적 유지
- 워크플로우에 `git checkout origin/gh-pages -- archive/` 추가 → 기존 아카이브 가져오기
- **탭 구조 정리**: 팁모음/에센셜지식 삭제 → **뉴스피드 / 아카이브 / 소스** 3탭
- 아카이브 탭: 날짜 선택 → fetch()로 JSON 로드 → 렌더링

### Phase C: 콘텐츠 깊이 개선
- **원문 크롤링**: `trafilatura` 라이브러리로 기사 본문 추출 (최대 3000자)
- **유튜브 자막 추출**: `youtube-transcript-api`로 영상 자막 텍스트화 (한국어 우선, 영어 fallback)
- `youtube-transcript-api` v1.2.4 API 변경 대응: `YouTubeTranscriptApi().fetch()` 사용
- `trafilatura` 실행에 `lxml_html_clean` 추가 설치 필요 (의존성 누락 해결)
- **Gemini 프롬프트 개선**: GeekNews 스타일 구조적 정리
  - `summary_ko`: 2-3문장 요약
  - `key_points`: 핵심 포인트 3개 (개조식)
  - `significance`: 의미/전망
- **HTML 상세 보기**: key_points는 기본 노출, significance만 `<details>` 접기

### Phase D: 소스 확장
- **GeekNews RSS 복구**: `https://news.hada.io/rss/news` (기존 null → 동작 확인)
- **새 소스 4개 추가**:
  - Hugging Face Blog (`https://huggingface.co/blog/feed.xml`)
  - Matt Wolfe YouTube (`channel_id=UChpleBmo18P08aKCIgti38g`) — AI 창작 도구 리뷰
  - The Rundown AI (`https://rss.beehiiv.com/feeds/2R3C6Bt5wj.xml`) — 매일 AI 뉴스
  - Stability AI (RSS 없음, 수동) — Stable Diffusion 개발사
- 총 21개 소스 (자동 수집 16개, 수동 5개)

### 수정 파일
| 파일 | 변경 |
|------|------|
| `collect_news.py` | 전면 재작성 (390줄 → 700줄) |
| `.github/workflows/daily-update.yml` | 아카이브, 패키지, keep_files |
| `sources.json` | 소스 4개 추가, GeekNews RSS 복구 |

---

## v2.1 — UX 개선 (2026-02-21)

v2 배포 후 사용자 관점 크리틱으로 발견한 문제 수정.

### 발견한 문제
1. **요약이 한 줄로 너무 짧음** — "자세히 보기" 안 누르면 정보량 부족
2. **"자세히 보기" 발견성 부족** — 작은 파란 텍스트, 클릭 유인 약함
3. **카테고리 편중** — insight 55%, content 10%
4. **모바일 대응 없음**

### 수정 내용
- `summary_ko` 2-3문장으로 복원 (1문장 → 2-3문장)
- `key_points` 기본 노출 (접기 제거), `significance`만 접기로 변경
- "자세히 보기" → **"왜 중요한가?"** 라벨 변경
- 카테고리 균형 규칙: content 최소 3개, insight 최대 40%
- 모바일 반응형 CSS 추가 (`@media max-width: 600px`)

---

## v2.2 — 타임존 버그 수정 (2026-02-21)

### 증상
사이트에 "2월 20일"로 표시 — 사용자는 오전 9시(KST)에 확인했는데 어제 날짜.

### 원인
GitHub Actions 서버가 UTC. cron `0 23 * * *` (UTC 23시 = KST 08시)에 실행하면 `datetime.now()`가 UTC 기준 전날 날짜 반환.

### 수정
`datetime.now()` → `datetime.now(KST)` (모든 곳에 적용)
```python
from datetime import datetime, timezone, timedelta
KST = timezone(timedelta(hours=9))
```

---

---

## v3 — 사용자 피드백 기반 미니 프로젝트 완결 (2026-02-21, 진행 중)

### 사용자 피드백 요약
1. 모바일 글씨 크기 너무 작음
2. 분류 태그가 모바일에서 한 줄 밀림 (아이폰 크롬)
3. 내용을 개조식 명사구(-음, -임)로 간결하게 작성해야 함
4. "왜 중요한가?" 차별성 없음 — 기사 본문 내용의 중언부언
5. 아카이브에 분류별 필터 없음 — 모든 컨텐츠가 섞인 채 날짜별 표시
6. 공식 소스 누락 (Anthropic, Midjourney, Kling, Suno, Figma, ElevenLabs 등)
7. GA 연동으로 사용 습관 파악 가능
8. **핵심**: 데이터 홍수 → "편집장 에이전트" 필요 (독립 프로젝트로 전환 대상)

### 완료된 작업
- [x] **모바일 CSS 개선**: 폰트 사이즈 전반 상향 (12-14px → 14-16px), `.news-source` 모바일에서 별도 줄로 분리, `.news-meta` flex-wrap: nowrap으로 태그 밀림 방지
- [x] **Gemini 프롬프트 재설계**:
  - 사용자 프로필 구체화 (비개발자, AI 도구 활용, 콘텐츠 제작 관심)
  - "필요 없는 것" 명시 (논문 디테일, 펀딩 뉴스, 기본 개념 반복)
  - 모든 텍스트 개조식 명사구(-음/-임 체)로 변경
  - `significance` → `my_impact` — 기사 반복이 아닌 "나에게 미치는 실질적 영향" 1문장
  - 최대 기사 수 20개 → 15개 (양보다 질)
  - 개조식 GOOD/BAD 예시 프롬프트에 포함
- [x] **HTML 구조 변경**:
  - `my_impact`를 기사 요약 바로 아래 "→" 화살표와 함께 보라색으로 즉시 노출
  - `key_points`를 "자세히 보기" 접기 안으로 이동 (이전: 기본 노출)
  - 정보 계층: 제목 → 요약 → 나에게 미치는 영향 → (자세히 보기: 핵심 사실 3개)
- [x] **아카이브 카테고리 필터 추가**: 뉴스 피드와 동일한 필터 버튼, 날짜 변경 시 필터 리셋, 공통 `setupFilters()` 함수로 리팩토링

### 남은 작업
- [x] **공식 소스 확장** — 6개 소스 sources.json 추가 완료
  - Anthropic News (RSS 없음, 수동)
  - Midjourney Updates (`https://updates.midjourney.com/rss/`) — RSS 확인
  - Kling AI (RSS 없음, 수동)
  - Suno (RSS 없음, 수동)
  - Figma Blog (`https://www.figma.com/blog/feed/atom.xml`) — Atom feed 확인
  - ElevenLabs (`https://elevenlabs.io/docs/changelog.rss`) — Changelog RSS만 존재
- [ ] **PRD + Spec 문서** — 편집장 에이전트 아키텍처의 독립 프로젝트 설계 문서
- [ ] **리뷰 문서** — 미니 → 풀 프로젝트 전환 과정을 동료가 이해할 수 있는 문서

---

## v3.2 — 코드 리팩토링 (2026-02-21)

### 동기
- `collect_news.py` 809줄 단일 파일에 CSS 148줄, JS 132줄이 Python 문자열로 인라인
- 매직 넘버 산재, 전역 변수 사용, 109줄짜리 거대 함수 존재
- 핵심 로직 파악이 어려운 구조

### 변경 내용
- **CSS/JS 분리**: `static/styles.css` + `static/app.js`로 외부화, `_load_asset()`로 빌드 시 인라인
- **CONFIG 딕셔너리**: 매직 넘버 13개를 파일 상단에 통합
- **함수 분리**: `process_with_gemini` → `_build_gemini_prompt` + `_call_gemini_with_retry` + `_parse_gemini_response`
- **전역 상태 제거**: `main()` 함수 도입, `gemini_client` 의존성 주입
- **헬퍼 함수**: `_trust_stars()`, `_build_filter_buttons()` — 2곳 이상 중복 제거
- **타입 힌트**: 모든 public 함수에 추가

### 결과
- 809줄 → 616줄 (-24%)
- 기능 동일 (리팩토링 전후 HTML 구조 비교 통과)
- 19/19 RSS 테스트 통과

---

## v3.3 — 블로그 크롤링 + 소스 정리 (2026-02-21)

### 동기
- RSS 없는 수동 소스가 소스 탭에 링크만 표시되고 실제 뉴스 수집을 하지 않음
- 크롤링 불가능한 소스(쓰레드, 뉴스레터) 정리 필요

### 변경 내용
- **블로그 크롤러 4개 추가**: Anthropic(BSoup SSR), Stability AI(Squarespace JSON), Suno(Next.js __NEXT_DATA__), 업스테이지(BSoup SSR)
- **소스 정리**: 최개발/The Batch/AI Journal 삭제 (27→24개), Kling/Suno URL을 블로그로 수정
- **main() 파이프라인**: RSS 수집 후 블로그 크롤링 결과를 합쳐서 Gemini로 전달
- **daily-update.yml**: beautifulsoup4 패키지 추가

### 결과
- 24개 소스 중 23개 자동 수집 (19 RSS + 4 크롤링), 1개(Kling) 링크만 유지

---

## 현재 상태 (v3.3)

- 24개 소스 (19개 RSS + 4개 크롤링 + 1개 링크만)
- 빅3 소스 완성 (Google AI, OpenAI, Anthropic)
- 콘텐츠 생성 카테고리 강화 (Midjourney, Kling, Suno, Figma, ElevenLabs, Stability AI)
- 원문 크롤링 + 유튜브 자막 추출 + 블로그 크롤링으로 깊이 있는 요약
- 날짜별 아카이브 축적 중
- 모바일 반응형 대응
- KST 기준 날짜 표시
- 개조식 명사구 + my_impact 기반 콘텐츠 구조
- 아카이브 카테고리 필터
- 코드 리팩토링 완료 (v3.2)

### 알려진 제한사항
- 일부 사이트(TechCrunch 등) 봇 차단으로 원문 크롤링 실패 → RSS description fallback
- Kling AI — SPA + 봇차단으로 크롤링 불가, 소스 탭 링크만 유지
- **근본적 한계**: 단일 파이프라인 구조로는 "편집장" 수준의 큐레이션 불가 → 독립 프로젝트 전환 완료 (ai-briefing)

---

## 향후 개선 후보 (미니 프로젝트 범위)
- [x] `google.genai` 패키지 마이그레이션 (v3.0에서 완료)
- [x] 코드 리팩토링 (v3.2에서 완료)
- [ ] GA 연동
- [ ] 주간 요약 자동 생성

## 풀 프로젝트 전환 완료 — ai-briefing (2026-02-21)

### 전환 배경
v3.0 사용 중 핵심 한계 도달:
- 15개 기사 중 관심 있는 건 5개 정도 → 개인화 필터링 필요
- 수준 불일치 (너무 기초 or 너무 어려움) → 수준별 요약 필요
- "편집장 에이전트"가 필요하다는 사용자 직접 요청

### 이중 플래닝 패턴 적용
1. ✅ Step 1: 플랜 모드에서 깊은 대화 (컨텍스트 축적)
2. ✅ Step 2: 설계 문서 생성 (`~/projects/ai-briefing/`)
   - `CLAUDE.md` — 프로젝트 세션 기반 문서
   - `prd.md` — 요구사항 정의서
   - `spec.md` — 기술 설계서
3. ⬜ Step 3: 새 세션에서 문서 기반 재계획
4. ⬜ Step 4: 실행

### 아키텍처 변경
- **기존** (v3.0): 단일 스크립트 `collect_news.py` (수집→요약→출력 일체형)
- **신규** (ai-briefing): 5개 에이전트 파이프라인
  - Scout (수집) → Profiler (프로필 매칭) → Editor (편집장) → Writer (브리핑) → Publisher (배포)

### 병행 운영
- ai-news-hub v3.0은 ai-briefing M3 완료 + 2주 안정화까지 계속 운영
- 새 시스템 안정 확인 후 v3.0 GitHub Actions 비활성화 예정
