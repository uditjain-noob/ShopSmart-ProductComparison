'use strict';

const POLL_MS  = 3000;

// ── Theme ─────────────────────────────────────────────────────────────────────

async function initTheme() {
  const { theme } = await chrome.storage.local.get(['theme']);
  if (theme === 'light') document.documentElement.setAttribute('data-theme', 'light');
}

function toggleTheme() {
  const isLight = document.documentElement.getAttribute('data-theme') === 'light';
  if (isLight) {
    document.documentElement.removeAttribute('data-theme');
    chrome.storage.local.set({ theme: 'dark' });
  } else {
    document.documentElement.setAttribute('data-theme', 'light');
    chrome.storage.local.set({ theme: 'light' });
  }
}

// ── Background messaging ──────────────────────────────────────────────────────

function bg(message) {
  return new Promise((res, rej) => {
    chrome.runtime.sendMessage(message, r => {
      if (chrome.runtime.lastError) return rej(chrome.runtime.lastError);
      res(r);
    });
  });
}

const _getLists   = ()              => bg({ type: 'GET_LISTS' }).then(r => r.lists);
const _addProduct = (listId, url)   => bg({ type: 'ADD_PRODUCT', listId, url, platform: 'Amazon' });

// ── State ─────────────────────────────────────────────────────────────────────

let _currentJobId  = null;  // set once job_id is read from storage
let _currentAnswers = null; // stored when questionnaire is submitted; reused for discover-better
let _currentSavedListId = null;
let _savedComparisonId = null;

// ── Utility ───────────────────────────────────────────────────────────────────

function show(id)  { document.getElementById(id).classList.remove('hidden'); }
function hide(id)  { document.getElementById(id).classList.add('hidden'); }

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function textToParagraphs(text) {
  return text
    .split(/\n{2,}/)
    .filter(Boolean)
    .map(p => `<p>${p.trim()}</p>`)
    .join('');
}

function sentimentClass(score) {
  return 'sentiment-' + score.toLowerCase().replace(/\s+/g, '-');
}

// ── Step tracker ─────────────────────────────────────────────────────────────

function updateSteps(progress) {
  const p = (progress || '').toLowerCase();
  const scrapeEl  = document.getElementById('step-scrape');
  const profileEl = document.getElementById('step-profile');
  const compareEl = document.getElementById('step-compare');

  if (p.includes('scraping')) {
    scrapeEl.className  = 'step active';
    profileEl.className = 'step pending';
    compareEl.className = 'step pending';
  } else if (p.includes('analys') || p.includes('profil')) {
    scrapeEl.className  = 'step done';
    profileEl.className = 'step active';
    compareEl.className = 'step pending';
  } else if (p.includes('generat') || p.includes('compar') || p.includes('recommend')) {
    scrapeEl.className  = 'step done';
    profileEl.className = 'step done';
    compareEl.className = 'step active';
  } else if (p === 'done') {
    scrapeEl.className  = 'step done';
    profileEl.className = 'step done';
    compareEl.className = 'step done';
  }
}

// ── Render results ────────────────────────────────────────────────────────────

function renderSpecTable(products) {
  const table = document.getElementById('spec-table');

  // Collect all unique spec keys in order of first appearance
  const allKeys = [];
  const seen = new Set();
  for (const p of products) {
    for (const k of Object.keys(p.specs || {})) {
      if (!seen.has(k)) { allKeys.push(k); seen.add(k); }
    }
  }

  // Only rows where ≥2 products have a value
  const sharedKeys = allKeys.filter(k => {
    const count = products.filter(p => p.specs?.[k]).length;
    return count >= 2;
  });

  if (sharedKeys.length === 0) {
    document.getElementById('section-specs').classList.add('hidden');
    return;
  }

  // Header row
  const headerCells = ['<th>Specification</th>',
    ...products.map(p => `<th>${p.title.slice(0, 50)}${p.title.length > 50 ? '…' : ''}</th>`)
  ].join('');
  let html = `<thead><tr>${headerCells}</tr></thead><tbody>`;

  for (const key of sharedKeys) {
    const cells = products.map(p => {
      const val = p.specs?.[key] || '—';
      return `<td>${val}</td>`;
    }).join('');
    html += `<tr><td>${key}</td>${cells}</tr>`;
  }

  html += '</tbody>';
  table.innerHTML = html;
}

function renderProductCards(products) {
  const grid = document.getElementById('product-cards');
  grid.innerHTML = products.map(p => {
    const sentClass = sentimentClass(p.sentiment_score || 'Mixed');

    const prosList = (p.pros || []).map(pro => `<li>${pro}</li>`).join('');
    const consList = (p.cons || []).map(con => `<li>${con}</li>`).join('');
    const quotesList = (p.notable_quotes || []).map(q => `<div class="quote">${q}</div>`).join('');

    return `
      <div class="product-card" data-title="${escapeHtml(p.title)}">
        <div class="product-card-header">
          <div class="product-card-platform">${p.platform}</div>
          <div class="product-card-title">${p.title}</div>
          <div class="product-card-price">${p.price || 'Price not available'}</div>
        </div>
        <div class="product-card-body">
          <span class="sentiment-badge ${sentClass}">${p.sentiment_score || 'Unknown'}</span>
          <p class="product-card-summary">${p.description_summary || ''}</p>
          <div class="pros-cons-grid">
            <div class="pros-cons-box">
              <div class="pros-cons-label pros">Pros</div>
              <ul class="pros-cons-list pros-list">${prosList}</ul>
            </div>
            <div class="pros-cons-box">
              <div class="pros-cons-label cons">Cons</div>
              <ul class="pros-cons-list cons-list">${consList}</ul>
            </div>
          </div>
          ${quotesList ? `<div class="quotes-section"><div class="quotes-label">Notable Reviews</div>${quotesList}</div>` : ''}
        </div>
      </div>
    `;
  }).join('');
}

function renderResults(result) {
  // Header subtitle
  const titles = result.products.map(p => p.title.split(' ').slice(0, 5).join(' ')).join(' vs ');
  document.getElementById('results-subtitle').textContent = titles;

  renderSpecTable(result.products);
  renderProductCards(result.products);
  renderQuestionnaire(result.questionnaire);

  document.getElementById('summary-text').innerHTML = textToParagraphs(result.summary);
  document.getElementById('recommendation-text').innerHTML = textToParagraphs(result.recommendation);

  // Show skipped-product warning if any URLs could not be scraped/profiled
  if (result.skipped_products && result.skipped_products.length > 0) {
    const banner = document.createElement('div');
    banner.className = 'skipped-banner';
    banner.innerHTML = `
      <svg viewBox="0 0 20 20" fill="currentColor">
        <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/>
      </svg>
      <div>
        <strong>${result.skipped_products.length} product${result.skipped_products.length > 1 ? 's' : ''} skipped</strong> — could not be scraped or analysed and were excluded from the comparison.
        <ul class="skipped-list">${result.skipped_products.map(r => `<li>${r}</li>`).join('')}</ul>
      </div>`;
    document.querySelector('.results-main').prepend(banner);
  }

  // Save as PDF — uses the browser's native print-to-PDF dialog
  document.getElementById('download-btn').addEventListener('click', () => {
    window.print();
  });

  const saveBtn = document.getElementById('save-comparison-btn');
  saveBtn.textContent = _savedComparisonId ? 'Saved' : 'Save Comparison';
  saveBtn.disabled = Boolean(_savedComparisonId);
  saveBtn.addEventListener('click', saveCurrentComparison);

  hide('view-loading');
  show('view-results');
}

async function saveCurrentComparison() {
  const btn = document.getElementById('save-comparison-btn');
  btn.disabled = true;
  btn.textContent = 'Saving...';

  try {
    let listId = _currentSavedListId;
    if (!listId) {
      const listsResponse = await apiFetch('/lists');
      const lists = await listsResponse.json();
      if (!listsResponse.ok) throw new Error(lists.detail || 'Could not load saved lists.');
      if (!lists.length) throw new Error('Save a list from the popup first, then save this comparison.');
      const options = lists.map((l, i) => `${i + 1}. ${l.name}`).join('\n');
      const choice = window.prompt(`Save comparison to which list?\n${options}`);
      const index = Number(choice) - 1;
      if (!Number.isInteger(index) || !lists[index]) throw new Error('Save cancelled.');
      listId = lists[index].id;
    }

    const response = await apiFetch(`/lists/${listId}/comparisons`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_id: _currentJobId }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Could not save comparison.');
    _savedComparisonId = data.comparison_id;
    btn.textContent = 'Saved';
  } catch (err) {
    btn.disabled = false;
    btn.textContent = 'Save Comparison';
    alert(err.message);
  }
}

// ── Questionnaire ─────────────────────────────────────────────────────────────

function renderQuestionnaire(questionnaire) {
  const questions = (questionnaire && questionnaire.questions) || [];

  if (questions.length === 0) {
    document.getElementById('section-questionnaire').classList.add('hidden');
    return;
  }

  const container  = document.getElementById('questionnaire-questions');
  const submitBtn  = document.getElementById('questionnaire-submit');
  const progressEl = document.getElementById('questionnaire-progress');
  const total      = questions.length;
  const answered   = new Set();

  progressEl.textContent = `0 / ${total} answered`;

  container.innerHTML = questions.map(q => `
    <div class="question-block" data-qid="${escapeHtml(q.id)}">
      <p class="question-text">${escapeHtml(q.text)}</p>
      <div class="question-options">
        ${(q.options || []).map(opt => `
          <label class="option-label">
            <input type="radio" name="${escapeHtml(q.id)}" value="${escapeHtml(opt)}" class="option-radio" />
            <span class="option-check"></span>
            <span class="option-text">${escapeHtml(opt)}</span>
          </label>
        `).join('')}
        <label class="option-label option-other-label">
          <input type="radio" name="${escapeHtml(q.id)}" value="__other__" class="option-radio" />
          <span class="option-check"></span>
          <span class="option-text option-other-prefix">Other:&nbsp;</span>
          <input type="text" class="option-other-input" placeholder="describe your answer…" />
        </label>
      </div>
    </div>
  `).join('');

  // Track answered count and enable submit when all done
  container.querySelectorAll('.option-radio').forEach(radio => {
    radio.addEventListener('change', () => {
      answered.add(radio.name);
      progressEl.textContent = `${answered.size} / ${total} answered`;
      submitBtn.disabled = answered.size < total;
    });
  });

  // Clicking into the free-text field selects its "Other" radio automatically
  container.querySelectorAll('.option-other-input').forEach(input => {
    input.addEventListener('focus', () => {
      const otherRadio = input.closest('.option-other-label').querySelector('.option-radio');
      if (!otherRadio.checked) otherRadio.click();
    });
  });

  submitBtn.addEventListener('click', submitQuestionnaire);
}

async function submitQuestionnaire() {
  const container = document.getElementById('questionnaire-questions');
  const submitBtn = document.getElementById('questionnaire-submit');

  // Collect answers
  const answers = {};
  container.querySelectorAll('.question-block').forEach(block => {
    const qid     = block.dataset.qid;
    const checked = block.querySelector('.option-radio:checked');
    if (!checked) return;
    if (checked.value === '__other__') {
      const text = block.querySelector('.option-other-input').value.trim();
      answers[qid] = text || 'Other';
    } else {
      answers[qid] = checked.value;
    }
  });

  // Store answers for potential discover-better call later
  _currentAnswers = answers;

  // Loading state
  submitBtn.disabled = true;
  submitBtn.innerHTML = `Finding your best match… <span class="btn-spin"></span>`;

  try {
    const res = await apiFetch(`/compare/${_currentJobId}/recommend`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ answers }),
    });
    if (!res.ok) throw new Error(`Server error ${res.status}`);
    const data = await res.json();
    showBestMatch(data);
    collapseQuestionnaire();
  } catch {
    submitBtn.disabled = false;
    submitBtn.innerHTML = `Find My Best Match <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M10.293 3.293a1 1 0 011.414 0l6 6a1 1 0 010 1.414l-6 6a1 1 0 01-1.414-1.414L14.586 11H3a1 1 0 110-2h11.586l-4.293-4.293a1 1 0 010-1.414z" clip-rule="evenodd"/></svg>`;
  }
}

function showBestMatch(recommendation) {
  document.getElementById('best-match-title').textContent    = recommendation.recommended_title || '';
  document.getElementById('best-match-reasoning').textContent = recommendation.reasoning || '';

  const banner = document.getElementById('best-match-banner');
  banner.classList.remove('hidden');

  // Highlight the matching product card (exact match, with partial fallback)
  const cards = document.querySelectorAll('.product-card');
  let matched = false;

  cards.forEach(card => {
    if (card.dataset.title === recommendation.recommended_title) {
      _applyBestMatchHighlight(card);
      matched = true;
    }
  });

  // Fallback: first 40-char prefix match in case the LLM slightly truncated the title
  if (!matched) {
    const prefix = (recommendation.recommended_title || '').slice(0, 40).toLowerCase();
    cards.forEach(card => {
      if (!matched && card.dataset.title.toLowerCase().startsWith(prefix.slice(0, 30))) {
        _applyBestMatchHighlight(card);
        matched = true;
      }
    });
  }

  banner.scrollIntoView({ behavior: 'smooth', block: 'center' });

  // Reveal the "Find Better Products" section now that the user has their match
  show('section-discover-better');
}

function _applyBestMatchHighlight(card) {
  card.classList.add('best-match');
  const badge = document.createElement('div');
  badge.className   = 'best-match-badge';
  badge.textContent = '★ Best for You';
  card.querySelector('.product-card-header').prepend(badge);
}

function collapseQuestionnaire() {
  const section = document.getElementById('section-questionnaire');
  section.className = 'card questionnaire-card questionnaire-done';
  section.innerHTML = `
    <div class="questionnaire-done-msg">
      <svg viewBox="0 0 20 20" fill="currentColor">
        <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/>
      </svg>
      Questionnaire complete — your best match is highlighted below
    </div>
  `;
}

// ── Discover Better Products ──────────────────────────────────────────────────

async function startDiscoverBetter() {
  const btn = document.getElementById('discover-better-btn');
  btn.disabled = true;
  btn.innerHTML = `Searching… <span class="btn-spin-discover"></span>`;
  hide('discover-better-btn');
  show('discover-better-loading');

  try {
    const res = await apiFetch(`/compare/${_currentJobId}/discover-better`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ answers: _currentAnswers }),
    });
    if (!res.ok) throw new Error(`Server error ${res.status}`);
    const { discover_job_id } = await res.json();
    pollDiscoverJob(discover_job_id);
  } catch (err) {
    hide('discover-better-loading');
    show('discover-better-btn');
    btn.disabled = false;
    btn.innerHTML = `
      <svg viewBox="0 0 20 20" fill="currentColor">
        <path fill-rule="evenodd" d="M8 4a4 4 0 100 8 4 4 0 000-8zM2 8a6 6 0 1110.89 3.476l4.817 4.817a1 1 0 01-1.414 1.414l-4.816-4.816A6 6 0 012 8z" clip-rule="evenodd"/>
      </svg>
      Search for Better Options`;
    document.getElementById('discover-better-results').innerHTML =
      `<p class="discover-error">Could not start search: ${escapeHtml(err.message)}. Make sure the backend is running.</p>`;
    show('discover-better-results');
  }
}

function pollDiscoverJob(discoverJobId) {
  let interval;

  async function check() {
    try {
      const res  = await apiFetch(`/discover/${discoverJobId}`);

      if (!res.ok) {
        clearInterval(interval);
        hide('discover-better-loading');
        _showDiscoverError(
          res.status === 404
            ? 'Search session expired (server restarted). Please click "Search for Better Options" again.'
            : `Server error ${res.status}. Please try again.`
        );
        return;
      }

      const data = await res.json();

      document.getElementById('discover-progress-text').textContent =
        data.progress || 'Searching…';

      if (data.status === 'complete') {
        clearInterval(interval);
        hide('discover-better-loading');
        renderSuggestions(data.suggestions || []);
        show('discover-better-results');
        document.getElementById('discover-better-results')
          .scrollIntoView({ behavior: 'smooth', block: 'start' });
      } else if (data.status === 'error') {
        clearInterval(interval);
        hide('discover-better-loading');
        _showDiscoverError(data.error || 'Unknown error.');
      }
    } catch {
      clearInterval(interval);
      hide('discover-better-loading');
      _showDiscoverError('Lost connection to the backend. Make sure the server is still running.');
    }
  }

  check();
  interval = setInterval(check, 3000);
}

function _showDiscoverError(message) {
  const results = document.getElementById('discover-better-results');
  results.innerHTML = `
    <div class="discover-error-card">
      <div class="discover-error-icon">
        <svg viewBox="0 0 20 20" fill="currentColor">
          <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/>
        </svg>
      </div>
      <div class="discover-error-body">
        <div class="discover-error-title">Search failed</div>
        <p class="discover-error-message">${escapeHtml(message)}</p>
        <button class="btn btn-discover btn-discover-retry" onclick="retryDiscoverBetter()">
          <svg viewBox="0 0 20 20" fill="currentColor">
            <path fill-rule="evenodd" d="M4 2a1 1 0 011 1v2.101a7.002 7.002 0 0111.601 2.566 1 1 0 11-1.885.666A5.002 5.002 0 005.999 7H9a1 1 0 010 2H4a1 1 0 01-1-1V3a1 1 0 011-1zm.008 9.057a1 1 0 011.276.61A5.002 5.002 0 0014.001 13H11a1 1 0 110-2h5a1 1 0 011 1v5a1 1 0 11-2 0v-2.101a7.002 7.002 0 01-11.601-2.566 1 1 0 01.61-1.276z" clip-rule="evenodd"/>
          </svg>
          Try Again
        </button>
      </div>
    </div>
  `;
  show('discover-better-results');
}

function retryDiscoverBetter() {
  hide('discover-better-results');
  document.getElementById('discover-better-results').innerHTML = '';
  show('discover-better-btn');
  const btn = document.getElementById('discover-better-btn');
  btn.disabled = false;
  btn.innerHTML = `
    <svg viewBox="0 0 20 20" fill="currentColor">
      <path fill-rule="evenodd" d="M8 4a4 4 0 100 8 4 4 0 000-8zM2 8a6 6 0 1110.89 3.476l4.817 4.817a1 1 0 01-1.414 1.414l-4.816-4.816A6 6 0 012 8z" clip-rule="evenodd"/>
    </svg>
    Search for Better Options`;
}

// ── Add suggestion to list ────────────────────────────────────────────────────

async function addSuggestionToList(btn, url) {
  btn.disabled = true;
  btn.innerHTML = '<span class="btn-spinner"></span> Checking…';

  try {
    const lists = await _getLists();

    if (!lists.length) {
      btn.disabled = false;
      btn.innerHTML = '⚠ No lists — open popup first';
      return;
    }

    if (lists.length === 1) {
      const res = await _addProduct(lists[0].id, url);
      if (res.success) {
        btn.className = 'btn btn-added';
        btn.innerHTML = `<svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg> Added to "${escapeHtml(lists[0].name)}"`;
      } else {
        btn.disabled = false;
        btn.innerHTML = `⚠ ${escapeHtml(res.error)}`;
      }
      return;
    }

    // Multiple lists — show an inline picker
    const picker = document.createElement('div');
    picker.className = 'list-picker';
    picker.innerHTML = `
      <span class="list-picker-label">Add to which list?</span>
      <div class="list-picker-options">
        ${lists.map(l => `<button class="list-picker-option" data-id="${l.id}">${escapeHtml(l.name)}</button>`).join('')}
      </div>
      <button class="list-picker-cancel">Cancel</button>
    `;

    btn.replaceWith(picker);

    picker.querySelectorAll('.list-picker-option').forEach(opt => {
      opt.addEventListener('click', async () => {
        const listId = parseInt(opt.dataset.id, 10);
        const list   = lists.find(l => l.id === listId);
        const res    = await _addProduct(listId, url);

        const replacement = document.createElement('button');
        if (res.success) {
          replacement.className = 'btn btn-added';
          replacement.innerHTML = `<svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg> Added to "${escapeHtml(list.name)}"`;
          replacement.disabled = true;
        } else {
          replacement.className = 'btn btn-add-to-list';
          replacement.dataset.url = url;
          replacement.innerHTML = `⚠ ${escapeHtml(res.error)} — try again`;
          replacement.addEventListener('click', () => addSuggestionToList(replacement, url));
        }
        picker.replaceWith(replacement);
      });
    });

    picker.querySelector('.list-picker-cancel').addEventListener('click', () => {
      const replacement = document.createElement('button');
      replacement.className = 'btn btn-add-to-list';
      replacement.dataset.url = url;
      replacement.innerHTML = `<svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z" clip-rule="evenodd"/></svg> Add to comparison`;
      replacement.addEventListener('click', () => addSuggestionToList(replacement, url));
      picker.replaceWith(replacement);
    });

  } catch (err) {
    btn.disabled = false;
    btn.innerHTML = `<svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z" clip-rule="evenodd"/></svg> Add to comparison`;
  }
}

function renderSuggestions(suggestions) {
  const container = document.getElementById('discover-better-results');

  if (!suggestions.length) {
    _showDiscoverError('The agent could not find better matching products. Try adjusting your questionnaire answers.');
    return;
  }

  const stars = (rating) => {
    if (rating == null) return '';
    const full  = Math.floor(rating);
    const half  = rating - full >= 0.5 ? 1 : 0;
    const empty = 5 - full - half;
    return '★'.repeat(full) + (half ? '½' : '') + '☆'.repeat(empty) + ` ${rating.toFixed(1)}`;
  };

  container.innerHTML = `
    <div class="discover-success-banner">
      <div class="discover-success-icon">
        <svg viewBox="0 0 20 20" fill="currentColor">
          <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/>
        </svg>
      </div>
      <div>
        <div class="discover-success-title">Found ${suggestions.length} better option${suggestions.length !== 1 ? 's' : ''} for you</div>
        <div class="discover-success-sub">Each pick is based on your questionnaire answers and budget range.</div>
      </div>
    </div>
    ${suggestions.map((s, i) => `
      <div class="suggestion-card" data-suggestion-index="${i}">
        <div class="suggestion-body">
          <div class="suggestion-title">${escapeHtml(s.title)}</div>
          <div class="suggestion-meta">
            ${s.price ? `<span class="suggestion-price">${escapeHtml(s.price)}</span>` : ''}
            ${s.rating != null ? `<span class="suggestion-rating">${stars(s.rating)}</span>` : ''}
          </div>
          <div class="suggestion-reason">
            <div class="suggestion-reason-label">Why this fits you</div>
            <p>${escapeHtml(s.reason)}</p>
          </div>
          <div class="suggestion-actions">
            <a href="${escapeHtml(s.url)}" target="_blank" rel="noopener noreferrer" class="btn btn-amazon">
              View on Amazon
              <svg viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M10.293 3.293a1 1 0 011.414 0l6 6a1 1 0 010 1.414l-6 6a1 1 0 01-1.414-1.414L14.586 11H3a1 1 0 110-2h11.586l-4.293-4.293a1 1 0 010-1.414z" clip-rule="evenodd"/>
              </svg>
            </a>
            <button class="btn btn-add-to-list" data-url="${escapeHtml(s.url)}">
              <svg viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z" clip-rule="evenodd"/>
              </svg>
              Add to comparison
            </button>
          </div>
        </div>
      </div>
    `).join('')}
  `;

  container.querySelectorAll('.btn-add-to-list').forEach(btn => {
    btn.addEventListener('click', () => addSuggestionToList(btn, btn.dataset.url));
  });
}

// ── Polling ───────────────────────────────────────────────────────────────────

async function pollJob(jobId) {
  let interval;

  async function check() {
    try {
      const res  = await apiFetch(`/compare/${jobId}`);
      const data = await res.json();

      document.getElementById('progress-text').textContent = data.progress || '…';
      updateSteps(data.progress);

      if (data.status === 'complete') {
        clearInterval(interval);
        _savedComparisonId = data.saved_comparison_id || null;
        renderResults(data.result);
      } else if (data.status === 'error') {
        clearInterval(interval);
        document.getElementById('error-text').textContent = data.error || 'Unknown error.';
        hide('view-loading');
        show('view-error');
      }
    } catch (err) {
      // Network error — backend may have gone away
      clearInterval(interval);
      document.getElementById('error-text').textContent =
        'Lost connection to the backend. Make sure the server is still running.';
      hide('view-loading');
      show('view-error');
    }
  }

  await check(); // immediate first check
  interval = setInterval(check, POLL_MS);
}

// ── Init ──────────────────────────────────────────────────────────────────────

async function init() {
  await initTheme();
  document.getElementById('theme-toggle').addEventListener('click', toggleTheme);
  const auth = await requireAuth();
  if (!auth) {
    document.getElementById('error-text').textContent = 'Please sign in before viewing comparisons.';
    hide('view-loading');
    show('view-error');
    return;
  }

  const { current_job_id: jobId, current_saved_list_id: savedListId } =
    await chrome.storage.session.get(['current_job_id', 'current_saved_list_id']);
  _currentJobId = jobId;
  _currentSavedListId = savedListId || null;

  if (!jobId) {
    document.getElementById('error-text').textContent =
      'No comparison job found. Go back to the extension popup and click "View Comparison".';
    hide('view-loading');
    show('view-error');
    return;
  }

  pollJob(jobId);

  document.getElementById('discover-better-btn').addEventListener('click', startDiscoverBetter);
}

document.addEventListener('DOMContentLoaded', init);
