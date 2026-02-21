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

// 카테고리 필터 (뉴스 피드 + 아카이브 공통)
function setupFilters(container) {
  container.querySelectorAll('.filter-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      container.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const filter = btn.dataset.filter;
      let num = 1;
      container.querySelectorAll('.news-item').forEach(item => {
        if (filter === 'all' || item.dataset.category === filter) {
          item.style.display = 'flex';
          item.querySelector('.news-num').textContent = num++;
        } else {
          item.style.display = 'none';
        }
      });
    });
  });
}
setupFilters(document.getElementById('tab-news'));
setupFilters(document.getElementById('tab-archive'));

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
  if (e.target.value) {
    // 필터 리셋
    document.querySelectorAll('#tab-archive .filter-btn').forEach(b => b.classList.remove('active'));
    document.querySelector('#tab-archive .filter-btn[data-filter="all"]').classList.add('active');
    loadArchiveDate(e.target.value);
  }
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
    model: ['tag-model', '모델/빅3'],
    dev: ['tag-dev', '개발'],
    content: ['tag-content', '콘텐츠 생성'],
    insight: ['tag-insight', '인사이트'],
    tip: ['tag-tip', '팁']
  };
  articles.forEach((a, i) => {
    const cat = a.category || 'model';
    const [tc, tl] = tagMap[cat] || ['tag-model', cat];
    const trust = a.trust || 3;
    const stars = '★'.repeat(trust) + '☆'.repeat(5 - trust);
    const kps = (a.key_points || []).map(k => '<li>' + k + '</li>').join('');
    const impact = a.my_impact || a.significance || '';
    let det = '';
    if (impact) det += '<div class="news-impact">' + impact + '</div>';
    if (kps) det += '<details class="news-details"><summary>자세히 보기</summary><ul class="key-points">' + kps + '</ul></details>';
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
      '<span class="trust" title="소스 신뢰도">' + stars + '</span></div>' +
      '</div>';
    list.appendChild(li);
  });
}
