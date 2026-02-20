#!/usr/bin/env python3
"""
My AI Hub - AI 뉴스 자동 수집 & 요약 스크립트

sources.json에 등록된 소스에서 뉴스를 수집하고,
Gemini 2.5 Flash로 요약/분류하여 HTML 페이지를 생성한다.
"""

import feedparser
import google.generativeai as genai
from dotenv import load_dotenv
import os
import json
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))


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


def fetch_articles(sources):
    """RSS 피드가 있는 소스에서 기사 수집"""
    articles = []
    for src in sources:
        try:
            feed = feedparser.parse(src["feed_url"])
            count = min(len(feed.entries), 10)
            for entry in feed.entries[:10]:
                articles.append({
                    "title": entry.get("title", ""),
                    "link": entry.get("link", ""),
                    "source": src["name"],
                    "trust": src.get("trust", 3),
                    "description": entry.get("summary", entry.get("description", ""))[:500],
                })
            print(f"  OK {src['name']}: {count}개")
        except Exception as e:
            print(f"  FAIL {src['name']}: {e}")
    return articles


def process_with_gemini(articles, all_sources):
    """Gemini로 기사를 요약/분류. 소스 정보도 함께 전달."""
    model = genai.GenerativeModel("gemini-2.5-flash")

    # 소스 맥락 생성
    source_context = "\n".join(
        f"- {s['name']} (신뢰도 {s.get('trust',3)}/5): {s.get('note','')}"
        for s in all_sources
    )

    articles_text = ""
    for i, a in enumerate(articles):
        articles_text += (
            f"\n---\n[{i}] 제목: {a['title']}\n"
            f"출처: {a['source']} (신뢰도: {a['trust']}/5)\n"
            f"링크: {a['link']}\n"
            f"내용: {a['description'][:300]}\n"
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
2. 각 기사를 한국어로 3-5줄 요약
3. 카테고리 분류: model(모델/빅3), dev(개발), content(콘텐츠 생성), insight(인사이트), tip(팁)
   - insight = 깊은 분석, 미래 전망, 산업의 의미 있는 해석. 단순 펀딩/주가 뉴스는 제외.
4. 신뢰도가 높은 소스의 기사를 우선 배치
5. 중요도 순으로 정렬

## 출력 (JSON만, 다른 텍스트 없이)
```json
[
  {{
    "index": 0,
    "title_ko": "한국어 제목",
    "summary_ko": "한국어 3-5줄 요약",
    "category": "model"
  }}
]
```

## 기사 목록
{articles_text}
"""

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


def generate_html(processed_articles, all_sources):
    """HTML 페이지 생성. 소스 신뢰도 표시 포함."""
    today = datetime.now().strftime("%Y년 %m월 %d일")
    weekday = ["월","화","수","목","금","토","일"][datetime.now().weekday()]

    tag_classes = {
        "model": ("tag-model", "모델/빅3"),
        "dev": ("tag-dev", "개발"),
        "content": ("tag-content", "콘텐츠 생성"),
        "insight": ("tag-insight", "인사이트"),
        "tip": ("tag-tip", "팁"),
    }

    # 뉴스 항목 HTML
    news_items = ""
    for i, a in enumerate(processed_articles, 1):
        cat = a.get("category", "model")
        tag_class, tag_label = tag_classes.get(cat, ("tag-model", cat))
        trust = a.get("trust", 3)
        trust_stars = "★" * trust + "☆" * (5 - trust)

        news_items += f"""
      <li class="news-item" data-category="{cat}">
        <span class="news-num">{i}</span>
        <div class="news-content">
          <div class="news-title">
            <a href="{a.get('link','#')}" target="_blank">{a.get('title_ko','')}</a>
            <span class="news-source">({a.get('source','')})</span>
          </div>
          <div class="news-summary">{a.get('summary_ko','')}</div>
          <div class="news-meta">
            <span class="news-tag {tag_class}">{tag_label}</span>
            <span class="trust" title="소스 신뢰도">{trust_stars}</span>
          </div>
        </div>
      </li>"""

    # 소스 목록 HTML
    source_items = ""
    for s in sorted(all_sources, key=lambda x: x.get("trust", 3), reverse=True):
        trust = s.get("trust", 3)
        stars = "★" * trust + "☆" * (5 - trust)
        has_feed = "auto" if s.get("feed_url") else "manual"
        focus_tags = ", ".join(s.get("focus", []))
        source_items += f"""
      <div class="source-item">
        <div class="source-header">
          <strong><a href="{s['url']}" target="_blank">{s['name']}</a></strong>
          <span class="trust">{stars}</span>
          <span class="source-badge badge-{has_feed}">{has_feed}</span>
        </div>
        <div class="source-note">{s.get('note','')}</div>
        <div class="source-focus">{focus_tags}</div>
      </div>"""

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>My AI Hub</title>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
      background: #f6f6ef; color: #333; line-height: 1.5;
    }}
    header {{
      background: #6b4ce6; padding: 8px 16px;
      display: flex; align-items: center; gap: 16px;
    }}
    header h1 {{ color: #fff; font-size: 16px; font-weight: bold; white-space: nowrap; }}
    nav {{ display: flex; gap: 12px; }}
    nav a {{
      color: rgba(255,255,255,0.85); text-decoration: none;
      font-size: 13px; padding: 4px 8px; border-radius: 4px; transition: background 0.15s;
    }}
    nav a:hover {{ background: rgba(255,255,255,0.15); }}
    nav a.active {{ color: #fff; font-weight: 600; background: rgba(255,255,255,0.2); }}
    .date-bar {{
      background: #f0edf8; padding: 6px 16px;
      font-size: 12px; color: #666; border-bottom: 1px solid #e0dce8;
    }}
    main {{ max-width: 900px; margin: 0 auto; padding: 8px 16px; }}
    .filters {{ display: flex; gap: 8px; padding: 12px 0; flex-wrap: wrap; }}
    .filter-btn {{
      background: #fff; border: 1px solid #ddd; padding: 4px 12px;
      border-radius: 16px; font-size: 12px; color: #555;
      cursor: pointer; transition: all 0.15s;
    }}
    .filter-btn:hover {{ border-color: #6b4ce6; color: #6b4ce6; }}
    .filter-btn.active {{ background: #6b4ce6; color: #fff; border-color: #6b4ce6; }}
    .news-list {{ list-style: none; }}
    .news-item {{
      display: flex; gap: 12px; padding: 12px 0; border-bottom: 1px solid #eee;
    }}
    .news-num {{
      color: #999; font-size: 14px; min-width: 28px;
      text-align: right; padding-top: 2px; font-weight: 500;
    }}
    .news-content {{ flex: 1; }}
    .news-title {{ font-size: 15px; font-weight: 600; margin-bottom: 2px; }}
    .news-title a {{ color: #333; text-decoration: none; }}
    .news-title a:hover {{ color: #6b4ce6; }}
    .news-source {{ font-size: 12px; color: #999; margin-left: 6px; font-weight: 400; }}
    .news-summary {{ font-size: 13px; color: #666; margin: 4px 0; line-height: 1.6; }}
    .news-meta {{ font-size: 11px; color: #999; display: flex; gap: 12px; margin-top: 4px; align-items: center; }}
    .news-tag {{
      display: inline-block; font-size: 11px; padding: 1px 8px;
      border-radius: 10px; font-weight: 500;
    }}
    .trust {{ font-size: 11px; color: #e8b84b; letter-spacing: -1px; }}
    .tag-model {{ background: #eef; color: #55c; }}
    .tag-dev {{ background: #efe; color: #5a5; }}
    .tag-content {{ background: #fef; color: #a5a; }}
    .tag-tip {{ background: #ffe; color: #a85; }}
    .tag-insight {{ background: #f0f0ff; color: #669; }}
    .tab-content {{ display: none; }}
    .tab-content.active {{ display: block; }}
    .empty-state {{ text-align: center; padding: 60px 20px; color: #999; }}
    .empty-state .icon {{ font-size: 48px; margin-bottom: 12px; }}
    .empty-state p {{ font-size: 14px; }}
    /* 소스 목록 */
    .source-item {{
      background: #fff; border: 1px solid #eee; border-radius: 8px;
      padding: 12px 16px; margin: 8px 0;
    }}
    .source-header {{ display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }}
    .source-header a {{ color: #333; text-decoration: none; }}
    .source-header a:hover {{ color: #6b4ce6; }}
    .source-note {{ font-size: 13px; color: #666; }}
    .source-focus {{ font-size: 11px; color: #999; margin-top: 4px; }}
    .source-badge {{
      font-size: 10px; padding: 1px 6px; border-radius: 8px; font-weight: 500;
    }}
    .badge-auto {{ background: #e8f5e9; color: #4a7; }}
    .badge-manual {{ background: #fff3e0; color: #a85; }}
    footer {{
      text-align: center; padding: 24px; font-size: 11px;
      color: #aaa; border-top: 1px solid #eee; margin-top: 24px;
    }}
  </style>
</head>
<body>
<header>
  <h1>My AI Hub</h1>
  <nav>
    <a href="#" class="active" data-tab="news">뉴스 피드</a>
    <a href="#" data-tab="sources">소스 ({len(all_sources)}개)</a>
    <a href="#" data-tab="tips">팁 모음</a>
    <a href="#" data-tab="knowledge">에센셜 지식</a>
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

<div id="tab-tips" class="tab-content">
  <main>
    <div class="empty-state">
      <div class="icon">💡</div>
      <p>아직 저장된 팁이 없습니다.</p>
    </div>
  </main>
</div>

<div id="tab-knowledge" class="tab-content">
  <main>
    <div class="empty-state">
      <div class="icon">📚</div>
      <p>아직 정리된 지식이 없습니다.</p>
    </div>
  </main>
</div>

<footer>My AI Hub — 자동 생성됨 · {today} · 소스 {len(all_sources)}개</footer>

<script>
  document.querySelectorAll('nav a').forEach(link => {{
    link.addEventListener('click', e => {{
      e.preventDefault();
      document.querySelectorAll('nav a').forEach(l => l.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
      link.classList.add('active');
      document.getElementById('tab-' + link.dataset.tab).classList.add('active');
    }});
  }});
  document.querySelectorAll('.filter-btn').forEach(btn => {{
    btn.addEventListener('click', () => {{
      document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const filter = btn.dataset.filter;
      let num = 1;
      document.querySelectorAll('.news-item').forEach(item => {{
        if (filter === 'all' || item.dataset.category === filter) {{
          item.style.display = 'flex';
          item.querySelector('.news-num').textContent = num++;
        }} else {{
          item.style.display = 'none';
        }}
      }});
    }});
  }});
</script>
</body>
</html>"""
    return html


if __name__ == "__main__":
    print("📋 소스 로딩...")
    feedable, unfeedable, source_data = load_sources()
    all_sources = source_data["trusted"]
    print(f"  자동 수집 가능: {len(feedable)}개 | 수동 확인 필요: {len(unfeedable)}개\n")

    print("🔍 뉴스 수집 중...")
    articles = fetch_articles(feedable)
    print(f"  총 {len(articles)}개 기사\n")

    print("🤖 Gemini로 요약 & 분류 중...")
    processed = process_with_gemini(articles, all_sources)
    print(f"  {len(processed)}개 선별 완료\n")

    print("📄 HTML 생성 중...")
    html = generate_html(processed, all_sources)
    output = BASE_DIR / "index.html"
    output.write_text(html, encoding="utf-8")
    print(f"  저장: {output}")

    print("\n✅ 완료!")
