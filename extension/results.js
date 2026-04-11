'use strict';

const API      = 'http://localhost:8000';
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

// ── State ─────────────────────────────────────────────────────────────────────

let _currentJobId = null;  // set once job_id is read from storage

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

  hide('view-loading');
  show('view-results');
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

  // Loading state
  submitBtn.disabled = true;
  submitBtn.innerHTML = `Finding your best match… <span class="btn-spin"></span>`;

  try {
    const res = await fetch(`${API}/compare/${_currentJobId}/recommend`, {
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

// ── Polling ───────────────────────────────────────────────────────────────────

async function pollJob(jobId) {
  let interval;

  async function check() {
    try {
      const res  = await fetch(`${API}/compare/${jobId}`);
      const data = await res.json();

      document.getElementById('progress-text').textContent = data.progress || '…';
      updateSteps(data.progress);

      if (data.status === 'complete') {
        clearInterval(interval);
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

  const { current_job_id: jobId } = await chrome.storage.session.get(['current_job_id']);
  _currentJobId = jobId;

  if (!jobId) {
    document.getElementById('error-text').textContent =
      'No comparison job found. Go back to the extension popup and click "View Comparison".';
    hide('view-loading');
    show('view-error');
    return;
  }

  pollJob(jobId);
}

document.addEventListener('DOMContentLoaded', init);
