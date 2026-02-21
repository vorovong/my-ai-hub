#!/usr/bin/env python3
"""
My AI Hub - AI 뉴스 자동 수집 & 요약 스크립트

sources.json에 등록된 소스에서 뉴스를 수집하고,
Gemini 2.5 Flash로 요약/분류하여 HTML 페이지를 생성한다.

개선사항:
- Phase A: Gemini JSON 파싱 에러 핸들링 + 재시도, 소스 다양성 보장
- Phase B: 날짜별 아카이브 저장, 아카이브 탭
- Phase C: 원문 크롤링(trafilatura), 유튜브 자막 추출, 깊이 있는 요약
- Phase D: 소스 확장 (sources.json)
"""

import feedparser
import google.generativeai as genai
from dotenv import load_dotenv
import os
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
import time

KST = timezone(timedelta(hours=9))

BASE_DIR = Path(__file__).parent
ARCHIVE_DIR = BASE_DIR / "archive"

load_dotenv(BASE_DIR / ".env")
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))


# ---------------------------------------------------------------------------
# 소스 로딩
# ---------------------------------------------------------------------------

def load_sources():
    """sources.json에서 trusted 소스 중 feed_url이 있는 것만 반환"""
    with open(BASE_DIR / "sources.json", encoding="utf-8") as f:
        data = json.load(f)

    feedable = []
    unfeedable = []
    for src in data["trusted"]:
        if src.get("feed_url"):
            feedable.append(src)
        else:
            unfeedable.append(src)

    return feedable, unfeedable, data


# ---------------------------------------------------------------------------
# Phase C: 원문 크롤링 + 유튜브 자막 추출
# ---------------------------------------------------------------------------

def fetch_full_article(url):
    """trafilatura로 기사 본문 추출 (최대 3000자)"""
    try:
        import trafilatura
        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            text = trafilatura.extract(downloaded)
            if text:
                return text[:3000]
    except Exception as e:
        print(f"    원문 크롤링 실패: {e}")
    return None


def fetch_youtube_transcript(url):
    """유튜브 영상 자막 추출 (한국어 우선, 영어 fallback)"""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        video_id = None
        if "v=" in url:
            video_id = url.split("v=")[1].split("&")[0]
        elif "youtu.be/" in url:
            video_id = url.split("youtu.be/")[1].split("?")[0]
        if not video_id:
            return None

        api = YouTubeTranscriptApi()
        for langs in [("ko",), ("en",)]:
            try:
                transcript = api.fetch(video_id, languages=langs)
                text = " ".join([snippet.text for snippet in transcript])
                return text[:3000] if text else None
            except Exception:
                continue
        return None
    except Exception as e:
        print(f"    자막 추출 실패: {e}")
        return None


# ---------------------------------------------------------------------------
# 기사 수집
# ---------------------------------------------------------------------------

def fetch_articles(sources):
    """RSS 피드가 있는 소스에서 기사 수집 + 원문/자막 추출"""
    articles = []
    for src in sources:
        try:
            feed = feedparser.parse(src["feed_url"])
            count = min(len(feed.entries), 10)
            for entry in feed.entries[:10]:
                article = {
                    "title": entry.get("title", ""),
                    "link": entry.get("link", ""),
                    "source": src["name"],
                    "trust": src.get("trust", 3),
                    "description": entry.get(
                        "summary", entry.get("description", "")
                    )[:500],
                    "full_text": None,
                }

                # 소스 타입에 따라 원문/자막 추출
                if src.get("type") == "youtube":
                    transcript = fetch_youtube_transcript(article["link"])
                    if transcript:
                        article["full_text"] = transcript
                        print(f"    자막 OK: {article['title'][:40]}")
                else:
                    full = fetch_full_article(article["link"])
                    if full:
                        article["full_text"] = full

                articles.append(article)
            print(f"  OK {src['name']}: {count}개")
        except Exception as e:
            print(f"  FAIL {src['name']}: {e}")
    return articles


# ---------------------------------------------------------------------------
# Phase A: 소스 다양성 보장
# ---------------------------------------------------------------------------

def ensure_source_diversity(articles, max_per_source=3):
    """소스당 최대 max_per_source개로 제한하여 다양성 보장"""
    source_counts = {}
    diverse = []
    for a in articles:
        source = a["source"]
        source_counts[source] = source_counts.get(source, 0) + 1
        if source_counts[source] <= max_per_source:
            diverse.append(a)
    return diverse


# ---------------------------------------------------------------------------
# Phase A: Gemini 처리 (에러 핸들링 + 재시도)
# ---------------------------------------------------------------------------

def process_with_gemini(articles, all_sources, max_retries=2):
    """Gemini로 기사를 요약/분류. JSON 파싱 에러 시 최대 2회 재시도."""
    model = genai.GenerativeModel("gemini-2.5-flash")

    # 소스 맥락 생성
    source_context = "\n".join(
        f"- {s['name']} (신뢰도 {s.get('trust',3)}/5): {s.get('note','')}"
        for s in all_sources
    )

    # 기사 텍스트 구성 — 원문이 있으면 원문 사용
    articles_text = ""
    for i, a in enumerate(articles):
        content = a.get("full_text") or a.get("description", "")[:300]
        articles_text += (
            f"\n---\n[{i}] 제목: {a['title']}\n"
            f"출처: {a['source']} (신뢰도: {a['trust']}/5)\n"
            f"링크: {a['link']}\n"
            f"내용:\n{content[:1500]}\n"
        )

    prompt = f"""당신은 AI 뉴스 큐레이터입니다.

## 사용자가 신뢰하는 소스 목록
{source_context}

## 사용자 관심 분야
- 거대 모델 3사 (Google, Anthropic, OpenAI) 뉴스
- AI 코딩 도구 (Claude Code, Cursor, Copilot 등)
- 콘텐츠 생성 AI (이미지, 영상, 음악, 3D)
- AI 실용 팁과 활용법
- AI 기초 이론과 논문
- AI/기술의 미래 전망, 깊은 분석, 의미 있는 해석

## 작업
1. AI와 관련된 기사만 선별 (최대 20개)
2. 각 기사를 구조적으로 정리:
   - title_ko: 한국어 제목
   - summary_ko: 핵심 요약 (2-3문장, 무슨 일이 일어났는지 + 왜 중요한지)
   - key_points: 핵심 포인트 3개 (개조식, 각각 1-2문장)
   - significance: 이 뉴스가 왜 중요한지, 어떤 의미/전망이 있는지 (2-3문장)
3. 카테고리 분류: model(모델/빅3), dev(개발), content(콘텐츠 생성), insight(인사이트), tip(팁)
   - insight = 깊은 분석, 미래 전망, 산업의 의미 있는 해석. 단순 펀딩/주가 뉴스는 제외.
   - 카테고리 균형: content(콘텐츠 생성)를 최소 3개 이상 포함. 모든 카테고리에서 최소 1개 이상 선별. insight가 전체의 40%를 넘지 않도록.
4. 신뢰도가 높은 소스의 기사를 우선 배치
5. 중요도 순으로 정렬

## 출력 (JSON만, 다른 텍스트 없이)
```json
[
  {{
    "index": 0,
    "title_ko": "한국어 제목",
    "summary_ko": "한 줄 핵심 요약",
    "key_points": ["포인트 1", "포인트 2", "포인트 3"],
    "significance": "이 뉴스의 의미와 전망",
    "category": "model"
  }}
]
```

## 기사 목록
{articles_text}"""

    for attempt in range(max_retries + 1):
        try:
            response = model.generate_content(prompt)
            text = response.text
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]

            processed = json.loads(text.strip())

            for item in processed:
                idx = item["index"]
                if idx < len(articles):
                    item["link"] = articles[idx]["link"]
                    item["source"] = articles[idx]["source"]
                    item["trust"] = articles[idx]["trust"]

            return processed
        except json.JSONDecodeError as e:
            print(
                f"  JSON 파싱 실패 (시도 {attempt + 1}/{max_retries + 1}): {e}"
            )
            if attempt < max_retries:
                time.sleep(2)
        except Exception as e:
            print(
                f"  Gemini 오류 (시도 {attempt + 1}/{max_retries + 1}): {e}"
            )
            if attempt < max_retries:
                time.sleep(2)

    # 모든 재시도 실패 → 이전 아카이브에서 로드
    print("  Gemini 완전 실패. 이전 아카이브에서 로드 시도...")
    return load_latest_archive()


# ---------------------------------------------------------------------------
# Phase B: 아카이브 시스템
# ---------------------------------------------------------------------------

def save_archive(processed_articles):
    """날짜별 아카이브 JSON 저장 + 인덱스 업데이트"""
    ARCHIVE_DIR.mkdir(exist_ok=True)
    today = datetime.now(KST).strftime("%Y-%m-%d")

    archive_data = {
        "date": today,
        "generated_at": datetime.now(KST).isoformat(),
        "article_count": len(processed_articles),
        "articles": processed_articles,
    }

    archive_file = ARCHIVE_DIR / f"{today}.json"
    archive_file.write_text(
        json.dumps(archive_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  아카이브 저장: {archive_file}")

    update_archive_index()
    return archive_data


def update_archive_index():
    """archive_index.json 업데이트 — 사용 가능한 날짜 목록"""
    dates = sorted(
        [f.stem for f in ARCHIVE_DIR.glob("*.json") if f.stem != "archive_index"],
        reverse=True,
    )
    index_data = {"dates": dates, "count": len(dates)}
    index_file = ARCHIVE_DIR / "archive_index.json"
    index_file.write_text(
        json.dumps(index_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  아카이브 인덱스 업데이트: {len(dates)}개 날짜")


def load_latest_archive():
    """가장 최근 아카이브에서 기사 로드 (Gemini 실패 시 fallback)"""
    if not ARCHIVE_DIR.exists():
        return []

    archives = sorted(ARCHIVE_DIR.glob("*.json"), reverse=True)
    for f in archives:
        if f.stem == "archive_index":
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            print(f"  이전 아카이브 로드: {f.name} ({data['article_count']}개)")
            return data.get("articles", [])
        except Exception:
            continue
    return []


# ---------------------------------------------------------------------------
# HTML 생성 헬퍼
# ---------------------------------------------------------------------------

def _build_news_items(processed_articles):
    """뉴스 항목 HTML 생성 (key_points, significance 포함)"""
    tag_classes = {
        "model": ("tag-model", "모델/빅3"),
        "dev": ("tag-dev", "개발"),
        "content": ("tag-content", "콘텐츠 생성"),
        "insight": ("tag-insight", "인사이트"),
        "tip": ("tag-tip", "팁"),
    }

    items = ""
    for i, a in enumerate(processed_articles, 1):
        cat = a.get("category", "model")
        tag_class, tag_label = tag_classes.get(cat, ("tag-model", cat))
        trust = a.get("trust", 3)
        trust_stars = "★" * trust + "☆" * (5 - trust)

        # key_points & significance (Phase C)
        key_points = a.get("key_points", [])
        significance = a.get("significance", "")

        # key_points는 기본 노출, significance만 접기
        kp_html = ""
        if key_points:
            kp_items = "".join(f"<li>{kp}</li>" for kp in key_points)
            kp_html = f'\n          <ul class="key-points">{kp_items}</ul>'
        sig_html = ""
        if significance:
            sig_html = f"""
          <details class="news-details">
            <summary>왜 중요한가?</summary>
            <div class="news-significance">{significance}</div>
          </details>"""
        details_html = kp_html + sig_html

        items += f"""
      <li class="news-item" data-category="{cat}">
        <span class="news-num">{i}</span>
        <div class="news-content">
          <div class="news-title">
            <a href="{a.get('link', '#')}" target="_blank">{a.get('title_ko', '')}</a>
            <span class="news-source">({a.get('source', '')})</span>
          </div>
          <div class="news-summary">{a.get('summary_ko', '')}</div>{details_html}
          <div class="news-meta">
            <span class="news-tag {tag_class}">{tag_label}</span>
            <span class="trust" title="소스 신뢰도">{trust_stars}</span>
          </div>
        </div>
      </li>"""

    return items


def _build_source_items(all_sources):
    """소스 목록 HTML 생성"""
    items = ""
    for s in sorted(all_sources, key=lambda x: x.get("trust", 3), reverse=True):
        trust = s.get("trust", 3)
        stars = "★" * trust + "☆" * (5 - trust)
        has_feed = "auto" if s.get("feed_url") else "manual"
        focus_tags = ", ".join(s.get("focus", []))
        items += f"""
      <div class="source-item">
        <div class="source-header">
          <strong><a href="{s['url']}" target="_blank">{s['name']}</a></strong>
          <span class="trust">{stars}</span>
          <span class="source-badge badge-{has_feed}">{has_feed}</span>
        </div>
        <div class="source-note">{s.get('note', '')}</div>
        <div class="source-focus">{focus_tags}</div>
      </div>"""
    return items


# CSS와 JS는 f-string 밖에서 정의 (중괄호 이스케이프 불필요)
CSS = """
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
      background: #f6f6ef; color: #333; line-height: 1.5;
    }
    header {
      background: #6b4ce6; padding: 8px 16px;
      display: flex; align-items: center; gap: 16px;
    }
    header h1 { color: #fff; font-size: 16px; font-weight: bold; white-space: nowrap; }
    nav { display: flex; gap: 12px; }
    nav a {
      color: rgba(255,255,255,0.85); text-decoration: none;
      font-size: 13px; padding: 4px 8px; border-radius: 4px; transition: background 0.15s;
    }
    nav a:hover { background: rgba(255,255,255,0.15); }
    nav a.active { color: #fff; font-weight: 600; background: rgba(255,255,255,0.2); }
    .date-bar {
      background: #f0edf8; padding: 6px 16px;
      font-size: 12px; color: #666; border-bottom: 1px solid #e0dce8;
    }
    main { max-width: 900px; margin: 0 auto; padding: 8px 16px; }
    .filters { display: flex; gap: 8px; padding: 12px 0; flex-wrap: wrap; }
    .filter-btn {
      background: #fff; border: 1px solid #ddd; padding: 4px 12px;
      border-radius: 16px; font-size: 12px; color: #555;
      cursor: pointer; transition: all 0.15s;
    }
    .filter-btn:hover { border-color: #6b4ce6; color: #6b4ce6; }
    .filter-btn.active { background: #6b4ce6; color: #fff; border-color: #6b4ce6; }
    .news-list { list-style: none; }
    .news-item {
      display: flex; gap: 12px; padding: 12px 0; border-bottom: 1px solid #eee;
    }
    .news-num {
      color: #999; font-size: 14px; min-width: 28px;
      text-align: right; padding-top: 2px; font-weight: 500;
    }
    .news-content { flex: 1; }
    .news-title { font-size: 15px; font-weight: 600; margin-bottom: 2px; }
    .news-title a { color: #333; text-decoration: none; }
    .news-title a:hover { color: #6b4ce6; }
    .news-source { font-size: 12px; color: #999; margin-left: 6px; font-weight: 400; }
    .news-summary { font-size: 13px; color: #666; margin: 4px 0; line-height: 1.6; }
    .news-meta { font-size: 11px; color: #999; display: flex; gap: 12px; margin-top: 4px; align-items: center; }
    .news-tag {
      display: inline-block; font-size: 11px; padding: 1px 8px;
      border-radius: 10px; font-weight: 500;
    }
    .trust { font-size: 11px; color: #e8b84b; letter-spacing: -1px; }
    .tag-model { background: #eef; color: #55c; }
    .tag-dev { background: #efe; color: #5a5; }
    .tag-content { background: #fef; color: #a5a; }
    .tag-tip { background: #ffe; color: #a85; }
    .tag-insight { background: #f0f0ff; color: #669; }
    .tab-content { display: none; }
    .tab-content.active { display: block; }
    .empty-state { text-align: center; padding: 60px 20px; color: #999; }
    .empty-state p { font-size: 14px; }
    /* 소스 목록 */
    .source-item {
      background: #fff; border: 1px solid #eee; border-radius: 8px;
      padding: 12px 16px; margin: 8px 0;
    }
    .source-header { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
    .source-header a { color: #333; text-decoration: none; }
    .source-header a:hover { color: #6b4ce6; }
    .source-note { font-size: 13px; color: #666; }
    .source-focus { font-size: 11px; color: #999; margin-top: 4px; }
    .source-badge {
      font-size: 10px; padding: 1px 6px; border-radius: 8px; font-weight: 500;
    }
    .badge-auto { background: #e8f5e9; color: #4a7; }
    .badge-manual { background: #fff3e0; color: #a85; }
    /* Phase C: 상세 보기 (details/summary) */
    .news-details { margin: 6px 0 2px 0; }
    .news-details summary {
      font-size: 12px; color: #6b4ce6; cursor: pointer;
      user-select: none; font-weight: 500;
    }
    .news-details summary:hover { text-decoration: underline; }
    .key-points {
      margin: 8px 0 8px 20px; font-size: 13px; color: #444;
      line-height: 1.7;
    }
    .key-points li { margin-bottom: 4px; }
    .news-significance {
      font-size: 13px; color: #555; background: #f8f7ff;
      padding: 8px 12px; border-radius: 6px; margin: 6px 0;
      border-left: 3px solid #6b4ce6; line-height: 1.6;
    }
    /* Phase B: 아카이브 탭 */
    .archive-header {
      display: flex; align-items: center; gap: 12px;
      padding: 12px 0; border-bottom: 1px solid #eee;
    }
    .archive-header label { font-size: 13px; color: #666; }
    #archive-date-select {
      padding: 6px 12px; border: 1px solid #ddd; border-radius: 8px;
      font-size: 13px; background: #fff; color: #333; cursor: pointer;
    }
    footer {
      text-align: center; padding: 24px; font-size: 11px;
      color: #aaa; border-top: 1px solid #eee; margin-top: 24px;
    }
    /* 모바일 반응형 */
    @media (max-width: 600px) {
      header { flex-direction: column; gap: 6px; padding: 8px 12px; }
      nav { flex-wrap: wrap; gap: 6px; }
      nav a { font-size: 12px; padding: 6px 10px; }
      .date-bar { font-size: 11px; padding: 4px 12px; }
      main { padding: 6px 12px; }
      .filter-btn { padding: 6px 14px; font-size: 12px; min-height: 36px; }
      .news-item { gap: 8px; padding: 10px 0; }
      .news-num { min-width: 22px; font-size: 13px; }
      .news-title { font-size: 14px; }
      .news-summary { font-size: 12px; }
      .key-points { font-size: 12px; margin-left: 16px; }
      .news-significance { font-size: 12px; }
      .archive-header { flex-direction: column; gap: 6px; }
      #archive-date-select { width: 100%; }
    }
"""

JS = """
  // 탭 전환
  document.querySelectorAll('nav a').forEach(link => {
    link.addEventListener('click', e => {
      e.preventDefault();
      document.querySelectorAll('nav a').forEach(l => l.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
      link.classList.add('active');
      document.getElementById('tab-' + link.dataset.tab).classList.add('active');
      // 아카이브 탭 첫 진입 시 인덱스 로드
      if (link.dataset.tab === 'archive' && !window._archiveLoaded) {
        loadArchiveIndex();
        window._archiveLoaded = true;
      }
    });
  });

  // 카테고리 필터
  document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const filter = btn.dataset.filter;
      let num = 1;
      document.querySelectorAll('#tab-news .news-item').forEach(item => {
        if (filter === 'all' || item.dataset.category === filter) {
          item.style.display = 'flex';
          item.querySelector('.news-num').textContent = num++;
        } else {
          item.style.display = 'none';
        }
      });
    });
  });

  // 아카이브 기능
  async function loadArchiveIndex() {
    try {
      const res = await fetch('archive/archive_index.json');
      if (!res.ok) throw new Error('not found');
      const data = await res.json();
      const select = document.getElementById('archive-date-select');
      data.dates.forEach(d => {
        const opt = document.createElement('option');
        opt.value = d;
        opt.textContent = d;
        select.appendChild(opt);
      });
      if (data.dates.length > 0) {
        select.value = data.dates[0];
        loadArchiveDate(data.dates[0]);
      }
    } catch (e) {
      document.getElementById('archive-empty').innerHTML =
        '<p>아카이브 데이터를 불러올 수 없습니다.</p>';
    }
  }

  document.getElementById('archive-date-select').addEventListener('change', e => {
    if (e.target.value) loadArchiveDate(e.target.value);
  });

  async function loadArchiveDate(date) {
    const list = document.getElementById('archive-list');
    const empty = document.getElementById('archive-empty');
    list.innerHTML = '<li style="padding:20px;color:#999;">불러오는 중...</li>';
    empty.style.display = 'none';
    try {
      const res = await fetch('archive/' + date + '.json');
      if (!res.ok) throw new Error('not found');
      const data = await res.json();
      renderArchiveArticles(data.articles);
    } catch (e) {
      list.innerHTML = '';
      empty.style.display = 'block';
      empty.innerHTML = '<p>해당 날짜의 데이터를 불러올 수 없습니다.</p>';
    }
  }

  function renderArchiveArticles(articles) {
    const list = document.getElementById('archive-list');
    const empty = document.getElementById('archive-empty');
    list.innerHTML = '';
    if (!articles || articles.length === 0) {
      empty.style.display = 'block';
      empty.innerHTML = '<p>해당 날짜에 수집된 뉴스가 없습니다.</p>';
      return;
    }
    empty.style.display = 'none';
    const tagMap = {
      model: ['tag-model', '\\ubaa8\\ub378/\\ube453'],
      dev: ['tag-dev', '\\uac1c\\ubc1c'],
      content: ['tag-content', '\\ucf58\\ud150\\uce20 \\uc0dd\\uc131'],
      insight: ['tag-insight', '\\uc778\\uc0ac\\uc774\\ud2b8'],
      tip: ['tag-tip', '\\ud301']
    };
    articles.forEach((a, i) => {
      const cat = a.category || 'model';
      const [tc, tl] = tagMap[cat] || ['tag-model', cat];
      const trust = a.trust || 3;
      const stars = '\\u2605'.repeat(trust) + '\\u2606'.repeat(5 - trust);
      const kps = (a.key_points || []).map(k => '<li>' + k + '</li>').join('');
      const sig = a.significance || '';
      let det = '';
      if (kps) det += '<ul class="key-points">' + kps + '</ul>';
      if (sig) det += '<details class="news-details"><summary>\\uc65c \\uc911\\uc694\\ud55c\\uac00?</summary><div class="news-significance">' + sig + '</div></details>';
      const li = document.createElement('li');
      li.className = 'news-item';
      li.dataset.category = cat;
      li.innerHTML =
        '<span class="news-num">' + (i+1) + '</span>' +
        '<div class="news-content">' +
        '<div class="news-title"><a href="' + (a.link||'#') + '" target="_blank">' + (a.title_ko||'') + '</a>' +
        '<span class="news-source">(' + (a.source||'') + ')</span></div>' +
        '<div class="news-summary">' + (a.summary_ko||'') + '</div>' +
        det +
        '<div class="news-meta"><span class="news-tag ' + tc + '">' + tl + '</span>' +
        '<span class="trust" title="\\uc18c\\uc2a4 \\uc2e0\\ub8b0\\ub3c4">' + stars + '</span></div>' +
        '</div>';
      list.appendChild(li);
    });
  }
"""


def generate_html(processed_articles, all_sources):
    """HTML 페이지 생성. 아카이브 탭 + 상세 보기 포함."""
    today = datetime.now(KST).strftime("%Y년 %m월 %d일")
    weekday = ["월", "화", "수", "목", "금", "토", "일"][datetime.now(KST).weekday()]

    news_items = _build_news_items(processed_articles)
    source_items = _build_source_items(all_sources)
    source_count = len(all_sources)

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>My AI Hub</title>
  <style>{CSS}</style>
</head>
<body>
<header>
  <h1>My AI Hub</h1>
  <nav>
    <a href="#" class="active" data-tab="news">뉴스 피드</a>
    <a href="#" data-tab="archive">아카이브</a>
    <a href="#" data-tab="sources">소스 ({source_count}개)</a>
  </nav>
</header>
<div class="date-bar">{today} ({weekday}) — 자동 수집</div>

<div id="tab-news" class="tab-content active">
  <main>
    <div class="filters">
      <button class="filter-btn active" data-filter="all">전체</button>
      <button class="filter-btn" data-filter="model">모델/빅3</button>
      <button class="filter-btn" data-filter="dev">개발</button>
      <button class="filter-btn" data-filter="content">콘텐츠 생성</button>
      <button class="filter-btn" data-filter="insight">인사이트</button>
      <button class="filter-btn" data-filter="tip">팁</button>
    </div>
    <ol class="news-list">
{news_items}
    </ol>
  </main>
</div>

<div id="tab-archive" class="tab-content">
  <main>
    <div class="archive-header">
      <label for="archive-date-select">날짜 선택:</label>
      <select id="archive-date-select">
        <option value="">날짜를 선택하세요</option>
      </select>
    </div>
    <ol id="archive-list" class="news-list"></ol>
    <div id="archive-empty" class="empty-state">
      <p>날짜를 선택하면 해당 날짜의 뉴스를 볼 수 있습니다.</p>
    </div>
  </main>
</div>

<div id="tab-sources" class="tab-content">
  <main>
    <p style="font-size:13px; color:#666; padding:12px 0;">
      ★ = 내가 매긴 신뢰도 &nbsp;|&nbsp;
      <span class="source-badge badge-auto">auto</span> = RSS 자동 수집 &nbsp;
      <span class="source-badge badge-manual">manual</span> = 수동 확인 필요
    </p>
{source_items}
  </main>
</div>

<footer>My AI Hub — 자동 생성됨 · {today} · 소스 {source_count}개</footer>

<script>{JS}</script>
</body>
</html>"""
    return html


# ---------------------------------------------------------------------------
# 메인 실행
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("소스 로딩...")
    feedable, unfeedable, source_data = load_sources()
    all_sources = source_data["trusted"]
    print(f"  자동 수집 가능: {len(feedable)}개 | 수동 확인 필요: {len(unfeedable)}개\n")

    print("뉴스 수집 중 (원문 크롤링 + 자막 추출 포함)...")
    articles = fetch_articles(feedable)
    print(f"  총 {len(articles)}개 기사\n")

    print("소스 다양성 필터 적용...")
    articles = ensure_source_diversity(articles, max_per_source=3)
    print(f"  필터 후 {len(articles)}개 기사\n")

    print("Gemini로 요약 & 분류 중...")
    processed = process_with_gemini(articles, all_sources)
    print(f"  {len(processed)}개 선별 완료\n")

    print("아카이브 저장 중...")
    save_archive(processed)

    print("HTML 생성 중...")
    html = generate_html(processed, all_sources)
    output = BASE_DIR / "index.html"
    output.write_text(html, encoding="utf-8")
    print(f"  저장: {output}")

    print("\n완료!")
