#!/usr/bin/env python3
"""
My AI Hub - AI 뉴스 자동 수집 & 요약 스크립트

sources.json에 등록된 소스에서 뉴스를 수집하고,
Gemini 2.5 Flash로 요약/분류하여 HTML 페이지를 생성한다.
"""

from __future__ import annotations

import feedparser
from google import genai
from dotenv import load_dotenv
import os
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
import time

# ---------------------------------------------------------------------------
# 경로 상수
# ---------------------------------------------------------------------------
KST = timezone(timedelta(hours=9))
BASE_DIR = Path(__file__).parent
ARCHIVE_DIR = BASE_DIR / "archive"
STATIC_DIR = BASE_DIR / "static"

# ---------------------------------------------------------------------------
# 설정 (수정이 필요하면 여기만 바꾸세요)
# ---------------------------------------------------------------------------
CONFIG = {
    # 수집
    "max_entries_per_feed": 10,
    "description_max_chars": 500,
    "full_text_max_chars": 3000,
    "max_per_source": 3,

    # Gemini 처리
    "gemini_model": "gemini-2.5-flash",
    "gemini_max_retries": 2,
    "gemini_retry_delay": 2,
    "content_max_chars": 1500,
    "description_fallback_chars": 300,
    "max_selected_articles": 15,

    # 신뢰도
    "default_trust": 3,
    "max_trust": 5,

    # 카테고리
    "categories": {
        "model": ("tag-model", "모델/빅3"),
        "dev": ("tag-dev", "개발"),
        "content": ("tag-content", "콘텐츠 생성"),
        "insight": ("tag-insight", "인사이트"),
        "tip": ("tag-tip", "팁"),
    },
}


# ---------------------------------------------------------------------------
# 헬퍼 함수
# ---------------------------------------------------------------------------

def _trust_stars(trust: int) -> str:
    """신뢰도를 별점 문자열로 변환 (예: ★★★☆☆)"""
    t = min(trust, CONFIG["max_trust"])
    return "★" * t + "☆" * (CONFIG["max_trust"] - t)


def _load_asset(filename: str) -> str:
    """static/ 폴더에서 CSS/JS 파일을 읽어 반환"""
    asset_path = STATIC_DIR / filename
    if not asset_path.exists():
        print(f"  경고: {asset_path} 파일을 찾을 수 없습니다.")
        return ""
    return asset_path.read_text(encoding="utf-8")


def _build_filter_buttons() -> str:
    """카테고리 필터 버튼 HTML 생성 (뉴스 피드 + 아카이브 공통)"""
    buttons = '      <button class="filter-btn active" data-filter="all">전체</button>\n'
    for cat_id, (_, label) in CONFIG["categories"].items():
        buttons += f'      <button class="filter-btn" data-filter="{cat_id}">{label}</button>\n'
    return buttons


# ---------------------------------------------------------------------------
# 소스 로딩
# ---------------------------------------------------------------------------

def load_sources() -> tuple[list[dict], list[dict], dict]:
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
# 원문 크롤링 + 유튜브 자막 추출
# ---------------------------------------------------------------------------

def fetch_full_article(url: str) -> str | None:
    """trafilatura로 기사 본문 추출"""
    try:
        import trafilatura
        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            text = trafilatura.extract(downloaded)
            if text:
                return text[:CONFIG["full_text_max_chars"]]
    except Exception as e:
        print(f"    원문 크롤링 실패: {e}")
    return None


def fetch_youtube_transcript(url: str) -> str | None:
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
                return text[:CONFIG["full_text_max_chars"]] if text else None
            except Exception:
                continue
        return None
    except Exception as e:
        print(f"    자막 추출 실패: {e}")
        return None


# ---------------------------------------------------------------------------
# 블로그 크롤링 (RSS 없는 소스)
# ---------------------------------------------------------------------------

def _scrape_anthropic(src: dict) -> list[dict]:
    """Anthropic News 페이지 크롤링 (SSR, BeautifulSoup)"""
    from bs4 import BeautifulSoup
    import requests as _req

    resp = _req.get(src["url"], headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    soup = BeautifulSoup(resp.text, "html.parser")

    articles = []
    for item in soup.select('a[class*="PublicationList"][class*="listItem"]'):
        title_el = item.select_one('span[class*="title"]')
        if not title_el:
            continue
        href = item.get("href", "")
        articles.append({
            "title": title_el.get_text(strip=True),
            "link": f"https://www.anthropic.com{href}" if href.startswith("/") else href,
            "source": src["name"],
            "trust": src.get("trust", CONFIG["default_trust"]),
            "description": "",
            "full_text": None,
        })
    return articles[:CONFIG["max_entries_per_feed"]]


def _scrape_stability(src: dict) -> list[dict]:
    """Stability AI News 크롤링 (Squarespace JSON API)"""
    import requests as _req

    resp = _req.get(
        "https://stability.ai/news",
        params={"format": "json"},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=15,
    )
    data = resp.json()

    articles = []
    for item in data.get("items", [])[:CONFIG["max_entries_per_feed"]]:
        articles.append({
            "title": item.get("title", ""),
            "link": "https://stability.ai" + item.get("fullUrl", ""),
            "source": src["name"],
            "trust": src.get("trust", CONFIG["default_trust"]),
            "description": item.get("excerpt", "")[:CONFIG["description_max_chars"]],
            "full_text": None,
        })
    return articles


def _scrape_suno(src: dict) -> list[dict]:
    """Suno Blog 크롤링 (Next.js __NEXT_DATA__ JSON)"""
    from bs4 import BeautifulSoup
    import requests as _req

    resp = _req.get(src["url"], headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    soup = BeautifulSoup(resp.text, "html.parser")

    script = soup.find("script", id="__NEXT_DATA__")
    if not script or not script.string:
        return []

    data = json.loads(script.string)
    posts = data.get("props", {}).get("pageProps", {}).get("allPosts", [])

    articles = []
    for post in posts[:CONFIG["max_entries_per_feed"]]:
        articles.append({
            "title": post.get("title", ""),
            "link": f"https://suno.com/blog/{post.get('slug', '')}",
            "source": src["name"],
            "trust": src.get("trust", CONFIG["default_trust"]),
            "description": post.get("summary", "")[:CONFIG["description_max_chars"]],
            "full_text": None,
        })
    return articles


def _scrape_upstage(src: dict) -> list[dict]:
    """업스테이지 블로그 크롤링 (SSR, BeautifulSoup)"""
    from bs4 import BeautifulSoup
    import requests as _req

    resp = _req.get(src["url"], headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    soup = BeautifulSoup(resp.text, "html.parser")

    articles = []
    for card in soup.select("a.all-blog-card-v2:not(.w-condition-invisible)"):
        title_el = card.select_one("h3.text-size-large")
        if not title_el:
            continue
        href = card.get("href", "")
        link = f"https://www.upstage.ai{href}" if href.startswith("/") else href
        articles.append({
            "title": title_el.get_text(strip=True),
            "link": link,
            "source": src["name"],
            "trust": src.get("trust", CONFIG["default_trust"]),
            "description": "",
            "full_text": None,
        })
    return articles[:CONFIG["max_entries_per_feed"]]


# 소스 이름 → 크롤러 매핑
_SCRAPERS: dict[str, callable] = {
    "Anthropic News": _scrape_anthropic,
    "Stability AI": _scrape_stability,
    "Suno": _scrape_suno,
    "업스테이지 AI 블로그": _scrape_upstage,
}


def fetch_blog_articles(unfeedable: list[dict]) -> list[dict]:
    """RSS 없는 블로그 소스에서 크롤링으로 기사 수집"""
    articles = []
    for src in unfeedable:
        scraper = _SCRAPERS.get(src["name"])
        if not scraper:
            continue
        try:
            result = scraper(src)
            # 원문 크롤링 시도
            for article in result:
                full = fetch_full_article(article["link"])
                if full:
                    article["full_text"] = full
            articles.extend(result)
            print(f"  OK {src['name']}: {len(result)}개 (크롤링)")
        except Exception as e:
            print(f"  FAIL {src['name']}: {e}")
    return articles


# ---------------------------------------------------------------------------
# 기사 수집 (RSS)
# ---------------------------------------------------------------------------

def fetch_articles(sources: list[dict]) -> list[dict]:
    """RSS 피드가 있는 소스에서 기사 수집 + 원문/자막 추출"""
    articles = []
    max_entries = CONFIG["max_entries_per_feed"]
    for src in sources:
        try:
            feed = feedparser.parse(src["feed_url"])
            count = min(len(feed.entries), max_entries)
            for entry in feed.entries[:max_entries]:
                article = {
                    "title": entry.get("title", ""),
                    "link": entry.get("link", ""),
                    "source": src["name"],
                    "trust": src.get("trust", CONFIG["default_trust"]),
                    "description": entry.get(
                        "summary", entry.get("description", "")
                    )[:CONFIG["description_max_chars"]],
                    "full_text": None,
                }

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
# 소스 다양성 보장
# ---------------------------------------------------------------------------

def ensure_source_diversity(
    articles: list[dict],
    max_per_source: int | None = None,
) -> list[dict]:
    """소스당 최대 N개로 제한하여 다양성 보장"""
    limit = max_per_source or CONFIG["max_per_source"]
    source_counts: dict[str, int] = {}
    filtered = []
    for article in articles:
        source = article["source"]
        source_counts[source] = source_counts.get(source, 0) + 1
        if source_counts[source] <= limit:
            filtered.append(article)
    return filtered


# ---------------------------------------------------------------------------
# Gemini 처리
# ---------------------------------------------------------------------------

def _build_gemini_prompt(articles: list[dict], all_sources: list[dict]) -> str:
    """Gemini에 보낼 프롬프트 구성"""
    source_context = "\n".join(
        f"- {s['name']} (신뢰도 {s.get('trust', CONFIG['default_trust'])}/5): {s.get('note', '')}"
        for s in all_sources
    )

    articles_text = ""
    for i, a in enumerate(articles):
        content = a.get("full_text") or a.get("description", "")[:CONFIG["description_fallback_chars"]]
        articles_text += (
            f"\n---\n[{i}] 제목: {a['title']}\n"
            f"출처: {a['source']} (신뢰도: {a['trust']}/5)\n"
            f"링크: {a['link']}\n"
            f"내용:\n{content[:CONFIG['content_max_chars']]}\n"
        )

    return f"""당신은 AI 뉴스 큐레이터입니다.

## 사용자가 신뢰하는 소스 목록
{source_context}

## 사용자 프로필
- 비개발자. AI 도구를 활용해 업무 자동화를 배우는 중.
- 콘텐츠 제작(영상, 이미지, 음악)에 AI를 쓰고 싶음.
- 관심 분야:
  - 거대 모델 3사 (Google, Anthropic, OpenAI) 동향
  - AI 코딩 도구 (Claude Code, Cursor, Copilot 등)
  - 콘텐츠 생성 AI (이미지, 영상, 음악, 3D)
  - 비개발자도 따라할 수 있는 AI 실용 팁
  - AI/기술의 미래 전망, 깊은 분석
- 필요 없는 것:
  - 논문 수준의 기술적 디테일
  - 단순 펀딩/주가/인수합병 뉴스
  - 이미 알려진 기본 개념 반복

## 작업
1. AI와 관련된 기사만 선별 (최대 {CONFIG['max_selected_articles']}개). 양보다 질.
2. 각 기사를 **개조식 명사구(-음, -임 등)**로 간결하게 정리:
   - title_ko: 한국어 제목 (간결하게)
   - summary_ko: 핵심 사실 1문장 (-음/-임 체)
   - key_points: 핵심 사실 3개 (개조식 명사구, 각각 1문장 이내)
   - my_impact: 이 사용자에게 미치는 실질적 영향 1문장. 기사 내용을 반복하지 말 것. "이 뉴스 때문에 내가 당장/조만간 할 수 있는 것, 또는 주의할 것"의 관점에서 작성.
3. 카테고리: model(모델/빅3), dev(개발), content(콘텐츠 생성), insight(인사이트), tip(팁)
   - 카테고리 균형: content 최소 3개, 모든 카테고리 최소 1개, insight 40% 이하.
4. 신뢰도 높은 소스 우선, 중요도 순 정렬

## 개조식 작성 예시
- BAD: "OpenAI가 새로운 모델을 발표했습니다. 이 모델은 기존보다 성능이 크게 향상되었습니다."
- GOOD: "OpenAI 신규 모델 발표. 기존 대비 성능 대폭 향상됨."
- BAD my_impact: "이는 AI 기술의 발전을 보여주며 산업에 큰 영향을 미칠 것입니다."
- GOOD my_impact: "Claude Code 사용 시 더 빠른 응답과 정확한 코드 생성 기대 가능."

## 출력 (JSON만, 다른 텍스트 없이)
```json
[
  {{
    "index": 0,
    "title_ko": "한국어 제목",
    "summary_ko": "핵심 사실 1문장 (-음/-임 체)",
    "key_points": ["사실 1", "사실 2", "사실 3"],
    "my_impact": "나에게 미치는 실질적 영향 1문장",
    "category": "model"
  }}
]
```

## 기사 목록
{articles_text}"""


def _call_gemini_with_retry(
    client: genai.Client,
    prompt: str,
    max_retries: int | None = None,
) -> str | None:
    """Gemini API 호출 + 재시도. 성공 시 응답 텍스트, 실패 시 None 반환."""
    retries = max_retries if max_retries is not None else CONFIG["gemini_max_retries"]
    for attempt in range(retries + 1):
        try:
            response = client.models.generate_content(
                model=CONFIG["gemini_model"], contents=prompt
            )
            return response.text
        except json.JSONDecodeError as e:
            print(f"  JSON 파싱 실패 (시도 {attempt + 1}/{retries + 1}): {e}")
            if attempt < retries:
                time.sleep(CONFIG["gemini_retry_delay"])
        except Exception as e:
            print(f"  Gemini 오류 (시도 {attempt + 1}/{retries + 1}): {e}")
            if attempt < retries:
                time.sleep(CONFIG["gemini_retry_delay"])
    return None


def _parse_gemini_response(text: str, articles: list[dict]) -> list[dict]:
    """Gemini 응답 텍스트에서 JSON 파싱 + 원본 데이터 매핑"""
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]

    processed = json.loads(text.strip())

    for item in processed:
        idx = item.get("index")
        if idx is not None and 0 <= idx < len(articles):
            item["link"] = articles[idx]["link"]
            item["source"] = articles[idx]["source"]
            item["trust"] = articles[idx].get("trust", CONFIG["default_trust"])
        else:
            item.setdefault("link", "#")
            item.setdefault("source", "알 수 없음")
            item.setdefault("trust", CONFIG["default_trust"])

    return processed


def process_with_gemini(
    articles: list[dict],
    all_sources: list[dict],
    client: genai.Client,
    max_retries: int | None = None,
) -> list[dict]:
    """Gemini로 기사를 요약/분류. 실패 시 이전 아카이브 fallback."""
    prompt = _build_gemini_prompt(articles, all_sources)
    retries = max_retries if max_retries is not None else CONFIG["gemini_max_retries"]

    for attempt in range(retries + 1):
        raw_text = _call_gemini_with_retry(client, prompt, max_retries=0)
        if raw_text is None:
            if attempt < retries:
                time.sleep(CONFIG["gemini_retry_delay"])
            continue
        try:
            return _parse_gemini_response(raw_text, articles)
        except json.JSONDecodeError as e:
            print(f"  JSON 파싱 실패 (시도 {attempt + 1}/{retries + 1}): {e}")
            if attempt < retries:
                time.sleep(CONFIG["gemini_retry_delay"])

    print("  Gemini 완전 실패. 이전 아카이브에서 로드 시도...")
    return load_latest_archive()


# ---------------------------------------------------------------------------
# 아카이브 시스템
# ---------------------------------------------------------------------------

def save_archive(processed_articles: list[dict]) -> dict:
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


def update_archive_index() -> None:
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


def load_latest_archive() -> list[dict]:
    """가장 최근 아카이브에서 기사 로드 (Gemini 실패 시 fallback)"""
    if not ARCHIVE_DIR.exists():
        return []

    archive_files = sorted(ARCHIVE_DIR.glob("*.json"), reverse=True)
    for f in archive_files:
        if f.stem == "archive_index":
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            print(f"  이전 아카이브 로드: {f.name} ({data['article_count']}개)")
            return data.get("articles", [])
        except Exception as e:
            print(f"  아카이브 파일 읽기 실패 ({f.name}): {e}")
            continue
    return []


# ---------------------------------------------------------------------------
# HTML 생성
# ---------------------------------------------------------------------------

def _build_news_items(processed_articles: list[dict]) -> str:
    """뉴스 항목 HTML 생성"""
    items = ""
    for i, article in enumerate(processed_articles, 1):
        cat = article.get("category", "model")
        tag_class, tag_label = CONFIG["categories"].get(cat, ("tag-model", cat))
        trust = article.get("trust", CONFIG["default_trust"])
        trust_display = _trust_stars(trust)

        key_points = article.get("key_points", [])
        my_impact = article.get("my_impact", "") or article.get("significance", "")

        kp_html = ""
        if key_points:
            kp_items = "".join(f"<li>{kp}</li>" for kp in key_points)
            kp_html = f"""
          <details class="news-details">
            <summary>자세히 보기</summary>
            <ul class="key-points">{kp_items}</ul>
          </details>"""

        impact_html = ""
        if my_impact:
            impact_html = f'\n          <div class="news-impact">{my_impact}</div>'

        details_html = impact_html + kp_html

        items += f"""
      <li class="news-item" data-category="{cat}">
        <span class="news-num">{i}</span>
        <div class="news-content">
          <div class="news-title">
            <a href="{article.get('link', '#')}" target="_blank">{article.get('title_ko', '')}</a>
            <span class="news-source">({article.get('source', '')})</span>
          </div>
          <div class="news-summary">{article.get('summary_ko', '')}</div>{details_html}
          <div class="news-meta">
            <span class="news-tag {tag_class}">{tag_label}</span>
            <span class="trust" title="소스 신뢰도">{trust_display}</span>
          </div>
        </div>
      </li>"""

    return items


def _build_source_items(all_sources: list[dict]) -> str:
    """소스 목록 HTML 생성"""
    items = ""
    for source in sorted(all_sources, key=lambda x: x.get("trust", CONFIG["default_trust"]), reverse=True):
        trust = source.get("trust", CONFIG["default_trust"])
        stars = _trust_stars(trust)
        has_feed = "auto" if source.get("feed_url") else "manual"
        focus_tags = ", ".join(source.get("focus", []))
        items += f"""
      <div class="source-item">
        <div class="source-header">
          <strong><a href="{source['url']}" target="_blank">{source['name']}</a></strong>
          <span class="trust">{stars}</span>
          <span class="source-badge badge-{has_feed}">{has_feed}</span>
        </div>
        <div class="source-note">{source.get('note', '')}</div>
        <div class="source-focus">{focus_tags}</div>
      </div>"""
    return items


def generate_html(processed_articles: list[dict], all_sources: list[dict]) -> str:
    """HTML 페이지 생성"""
    today = datetime.now(KST).strftime("%Y년 %m월 %d일")
    weekday = ["월", "화", "수", "목", "금", "토", "일"][datetime.now(KST).weekday()]

    css = _load_asset("styles.css")
    js = _load_asset("app.js")
    news_items = _build_news_items(processed_articles)
    source_items = _build_source_items(all_sources)
    source_count = len(all_sources)
    filter_buttons = _build_filter_buttons()

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>My AI Hub</title>
  <style>
{css}
  </style>
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
{filter_buttons}
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
    <div class="filters archive-filters">
{filter_buttons}
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

<script>
{js}
</script>
</body>
</html>"""
    return html


# ---------------------------------------------------------------------------
# 메인 실행
# ---------------------------------------------------------------------------

def main() -> None:
    """메인 파이프라인: 소스 로딩 → 수집 → 요약 → 아카이브 → HTML 생성"""
    load_dotenv(BASE_DIR / ".env")
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

    print("소스 로딩...")
    feedable, unfeedable, source_data = load_sources()
    all_sources = source_data["trusted"]
    print(f"  자동 수집 가능: {len(feedable)}개 | 수동 확인 필요: {len(unfeedable)}개\n")

    print("뉴스 수집 중 (원문 크롤링 + 자막 추출 포함)...")
    articles = fetch_articles(feedable)
    print(f"  RSS 소스: {len(articles)}개 기사")

    print("블로그 크롤링 중 (RSS 없는 소스)...")
    blog_articles = fetch_blog_articles(unfeedable)
    articles.extend(blog_articles)
    print(f"  총 {len(articles)}개 기사 (RSS {len(articles) - len(blog_articles)} + 크롤링 {len(blog_articles)})\n")

    print("소스 다양성 필터 적용...")
    articles = ensure_source_diversity(articles)
    print(f"  필터 후 {len(articles)}개 기사\n")

    print("Gemini로 요약 & 분류 중...")
    processed = process_with_gemini(articles, all_sources, client=client)
    print(f"  {len(processed)}개 선별 완료\n")

    print("아카이브 저장 중...")
    save_archive(processed)

    print("HTML 생성 중...")
    html = generate_html(processed, all_sources)
    output = BASE_DIR / "index.html"
    output.write_text(html, encoding="utf-8")
    print(f"  저장: {output}")

    print("\n완료!")


if __name__ == "__main__":
    main()
