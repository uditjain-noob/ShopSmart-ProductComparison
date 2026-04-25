'use strict';

let _lists = [];
let _activeComparisonId = null;

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function formatDate(value) {
  if (!value) return '';
  return new Date(value).toLocaleString();
}

async function loadLists() {
  const response = await apiFetch('/lists');
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || 'Could not load lists.');
  _lists = data;
  renderLists();
}

function renderLists(activeListId = null) {
  const container = document.getElementById('lists');
  container.innerHTML = _lists.length
    ? _lists.map(list => `
        <button class="list-item ${list.id === activeListId ? 'active' : ''}" data-id="${escapeHtml(list.id)}">
          <div class="item-title">${escapeHtml(list.name)}</div>
          <div class="item-meta">${list.product_count || 0} products</div>
        </button>
      `).join('')
    : '<p class="item-meta">No saved lists yet.</p>';

  container.querySelectorAll('.list-item').forEach(button => {
    button.addEventListener('click', () => loadList(button.dataset.id));
  });
}

async function loadAllComparisons() {
  document.getElementById('all-comparisons-btn').classList.add('active');
  renderLists(null);
  document.getElementById('middle-title').textContent = 'All comparisons';
  document.getElementById('products-panel').classList.add('hidden');

  const response = await apiFetch('/comparisons');
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || 'Could not load comparisons.');
  renderComparisons(data);
}

async function loadList(listId) {
  document.getElementById('all-comparisons-btn').classList.remove('active');
  renderLists(listId);

  const [listResponse, comparisonsResponse] = await Promise.all([
    apiFetch(`/lists/${listId}`),
    apiFetch(`/lists/${listId}/comparisons`),
  ]);
  const list = await listResponse.json();
  const comparisons = await comparisonsResponse.json();
  if (!listResponse.ok) throw new Error(list.detail || 'Could not load list.');
  if (!comparisonsResponse.ok) throw new Error(comparisons.detail || 'Could not load comparisons.');

  document.getElementById('middle-title').textContent = list.name;
  renderProducts(list.products || []);
  renderComparisons(comparisons);
}

function renderProducts(products) {
  const panel = document.getElementById('products-panel');
  panel.classList.remove('hidden');
  panel.innerHTML = `
    <strong>${products.length} saved products</strong>
    <ul>
      ${products.map(product => `<li>${escapeHtml(product.title || product.url)}</li>`).join('')}
    </ul>
  `;
}

function renderComparisons(comparisons) {
  const container = document.getElementById('comparisons');
  container.innerHTML = comparisons.length
    ? comparisons.map(item => `
        <button class="comparison-item ${item.id === _activeComparisonId ? 'active' : ''}" data-id="${escapeHtml(item.id)}">
          <div class="item-title">${escapeHtml(item.list_name || 'Saved comparison')}</div>
          <div class="item-meta">${formatDate(item.created_at)} · ${item.product_count || 0} products</div>
        </button>
      `).join('')
    : '<p class="item-meta">No saved comparisons yet.</p>';

  container.querySelectorAll('.comparison-item').forEach(button => {
    button.addEventListener('click', () => loadComparison(button.dataset.id));
  });
}

async function loadComparison(comparisonId) {
  _activeComparisonId = comparisonId;
  const response = await apiFetch(`/comparisons/${comparisonId}`);
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || 'Could not load comparison.');
  renderComparison(data);
}

function renderComparison(comparison) {
  document.getElementById('empty-view').classList.add('hidden');
  const view = document.getElementById('comparison-view');
  view.classList.remove('hidden');

  const questions = comparison.questionnaire?.questions || [];
  view.innerHTML = `
    <section class="report-section">
      <h2>${escapeHtml(comparison.list_name || 'Saved comparison')}</h2>
      <p>${formatDate(comparison.created_at)}</p>
    </section>

    <section class="report-section">
      <h2>Recommendation</h2>
      <p>${escapeHtml(comparison.recommendation || '')}</p>
    </section>

    <section class="report-section">
      <h2>Compared Products</h2>
      <div class="product-grid">
        ${(comparison.products || []).map(product => `
          <article class="product-card">
            <h3>${escapeHtml(product.title)}</h3>
            <p>${escapeHtml(product.price || 'Price not available')}</p>
            <p>${escapeHtml(product.description_summary || '')}</p>
          </article>
        `).join('')}
      </div>
    </section>

    <section class="report-section">
      <h2>Generated Questions</h2>
      ${questions.length ? `
        <ol>
          ${questions.map(q => `<li>${escapeHtml(q.text)}</li>`).join('')}
        </ol>
      ` : '<p>No questions were saved for this comparison.</p>'}
    </section>

    <section class="report-section">
      <h2>Full Markdown Report</h2>
      <div class="markdown-box">${escapeHtml(comparison.markdown || comparison.summary || '')}</div>
    </section>
  `;
}

async function init() {
  const auth = await requireAuth();
  if (!auth) return;
  document.getElementById('account-label').textContent = auth.email;
  document.getElementById('logout-btn').addEventListener('click', async () => {
    await clearAuthState();
    chrome.tabs.create({ url: chrome.runtime.getURL('login.html') });
  });
  document.getElementById('all-comparisons-btn').addEventListener('click', loadAllComparisons);

  try {
    await loadLists();
    await loadAllComparisons();
  } catch (err) {
    document.getElementById('comparisons').innerHTML = `<p class="item-meta">${escapeHtml(err.message)}</p>`;
  }
}

document.addEventListener('DOMContentLoaded', init);
