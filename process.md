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

## 현재 상태 (v2.2)

- 21개 소스에서 자동 수집 (16개 RSS, 5개 수동)
- 원문 크롤링 + 유튜브 자막 추출로 깊이 있는 요약
- 날짜별 아카이브 축적 중 (현재 2일분)
- 모바일 반응형 대응
- KST 기준 날짜 표시

### 알려진 제한사항
- 일부 사이트(TechCrunch 등) 봇 차단으로 원문 크롤링 실패 → RSS description fallback
- `google.generativeai` 패키지 deprecated 경고 → `google.genai`로 마이그레이션 필요
- Stability AI 등 RSS 없는 소스는 자동 수집 불가

---

## 향후 개선 후보
- [ ] `google.genai` 패키지 마이그레이션
- [ ] 주간 요약 자동 생성
- [ ] 소스별 수집 성공/실패 통계 대시보드
- [ ] Reddit r/StableDiffusion 연동 (API 키 필요)
