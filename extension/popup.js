'use strict';

const API = 'http://localhost:8000';
const MIN = 2;

// ── Theme ─────────────────────────────────────────────────────────────────────

async function initTheme() {
  const { theme } = await chrome.storage.local.get(['theme']);
  // :root is dark by default; only set attribute when switching to light
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

// ── Platform detection ────────────────────────────────────────────────────────

const PLATFORMS = [
  { name: 'Amazon', re: /amazon\.(com|co\.uk|co\.jp|de|fr|ca|in|com\.au)/i },
];

function detectPlatform(url) {
  for (const p of PLATFORMS) { if (p.re.test(url)) return p.name; }
  return null;
}

function isProductPage(url) { return /\/dp\/[A-Z0-9]{10}/i.test(url); }

function truncate(str, n) { return str.length > n ? str.slice(0, n - 1) + '…' : str; }

// ── Background messaging ──────────────────────────────────────────────────────

function bg(message) {
  return new Promise((res, rej) => {
    chrome.runtime.sendMessage(message, r => {
      if (chrome.runtime.lastError) return rej(chrome.runtime.lastError);
      res(r);
    });
  });
}

const getLists       = ()          => bg({ type: 'GET_LISTS' }).then(r => r.lists);
const createList     = name        => bg({ type: 'CREATE_LIST', name });
const renameList     = (id, name)  => bg({ type: 'RENAME_LIST', listId: id, name });
const deleteList     = id          => bg({ type: 'DELETE_LIST', listId: id });
const addProduct     = (id, url, platform) => bg({ type: 'ADD_PRODUCT', listId: id, url, platform });
const removeProduct  = (id, idx)   => bg({ type: 'REMOVE_PRODUCT', listId: id, index: idx });
const toggleProduct  = (id, idx)   => bg({ type: 'TOGGLE_PRODUCT', listId: id, index: idx });
const selectAll      = id          => bg({ type: 'SELECT_ALL', listId: id });

// ── Toast ─────────────────────────────────────────────────────────────────────

let _toastTimer;
function toast(msg, type = 'success') {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = `toast toast-${type} show`;
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => { el.className = 'toast'; }, 2600);
}

// ── Modal ─────────────────────────────────────────────────────────────────────

function openModal(title, placeholder, initial = '') {
  return new Promise(resolve => {
    document.getElementById('modal-title').textContent = title;
    const input = document.getElementById('modal-input');
    input.placeholder = placeholder;
    input.value = initial;
    document.getElementById('modal-overlay').classList.remove('hidden');
    input.focus();

    const confirm = document.getElementById('modal-confirm');
    const cancel  = document.getElementById('modal-cancel');

    function cleanup(value) {
      document.getElementById('modal-overlay').classList.add('hidden');
      confirm.replaceWith(confirm.cloneNode(true));
      cancel.replaceWith(cancel.cloneNode(true));
      resolve(value);
    }

    document.getElementById('modal-confirm').addEventListener('click', () => {
      cleanup(document.getElementById('modal-input').value.trim() || null);
    });
    document.getElementById('modal-cancel').addEventListener('click', () => cleanup(null));
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter') cleanup(document.getElementById('modal-input').value.trim() || null);
      if (e.key === 'Escape') cleanup(null);
    });
  });
}

// ── List-select dropdowns ─────────────────────────────────────────────────────

function populateSelects(lists) {
  ['list-select-current', 'list-select-url'].forEach(id => {
    const sel = document.getElementById(id);
    const prev = sel.value;
    sel.innerHTML = '<option value="">— select a list —</option>';
    lists.forEach(l => {
      const opt = document.createElement('option');
      opt.value = l.id;
      opt.textContent = l.name;
      sel.appendChild(opt);
    });
    // Restore previous selection if still valid
    if (lists.some(l => String(l.id) === prev)) sel.value = prev;
    else if (lists.length === 1) sel.value = lists[0].id;
  });
}

// ── Compare button ────────────────────────────────────────────────────────────

function refreshCompareBtn(lists) {
  const btn   = document.getElementById('compare-btn');
  const label = document.getElementById('compare-btn-label');
  const badge = document.getElementById('tab-badge');

  const selected = lists.flatMap(l => l.products.filter(p => p.selected));
  const count    = selected.length;
  const total    = lists.flatMap(l => l.products).length;

  btn.disabled = count < MIN;
  label.textContent = count >= MIN ? `View Comparison (${count} selected)` : 'View Comparison';

  // Badge on Lists tab shows total products across all lists
  badge.textContent = total;
  badge.classList.toggle('hidden', total === 0);

  // Selected count label inside lists tab
  const countLbl = document.getElementById('selected-count-label');
  countLbl.textContent = count > 0 ? `${count} product${count > 1 ? 's' : ''} selected` : '';
}

// ── Render lists ──────────────────────────────────────────────────────────────

function renderLists(lists) {
  const container = document.getElementById('lists-container');
  const empty     = document.getElementById('lists-empty');

  container.innerHTML = '';
  if (lists.length === 0) { empty.classList.remove('hidden'); return; }
  empty.classList.add('hidden');

  lists.forEach(list => {
    const selectedInList = list.products.filter(p => p.selected).length;
    const allSelected    = list.products.length > 0 && selectedInList === list.products.length;

    const group = document.createElement('div');
    group.className = 'list-group';
    group.innerHTML = `
      <div class="list-group-header">
        <span class="list-group-name">${list.name}</span>
        <span class="list-group-count">${list.products.length}/5 products</span>
        <div class="list-group-actions">
          <button class="icon-btn rename-btn" title="Rename list" data-id="${list.id}">
            <svg viewBox="0 0 20 20" fill="currentColor"><path d="M13.586 3.586a2 2 0 112.828 2.828l-.793.793-2.828-2.828.793-.793zm-2.207 2.207L3 14.172V17h2.828l8.38-8.379-2.83-2.828z"/></svg>
          </button>
          <button class="icon-btn danger delete-btn" title="Delete list" data-id="${list.id}">
            <svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm4 0a1 1 0 012 0v6a1 1 0 11-2 0V8z" clip-rule="evenodd"/></svg>
          </button>
        </div>
      </div>

      ${list.products.length > 0 ? `
        <div class="select-all-row" data-id="${list.id}">
          <input type="checkbox" class="product-checkbox" ${allSelected ? 'checked' : ''} readonly />
          <span>${allSelected ? 'Deselect all' : 'Select all'}</span>
          <span style="flex:1"></span>
          <span style="font-size:10px;color:var(--primary)">${selectedInList} selected</span>
        </div>
        ${list.products.map((p, i) => `
          <div class="product-item">
            <input type="checkbox" class="product-checkbox product-toggle" data-list="${list.id}" data-index="${i}" ${p.selected ? 'checked' : ''} />
            <div class="product-item-info product-toggle" data-list="${list.id}" data-index="${i}">
              <div class="product-item-platform">${p.platform}</div>
              <div class="product-item-url">${truncate(p.url, 48)}</div>
            </div>
            <button class="remove-btn" data-list="${list.id}" data-index="${i}" title="Remove">×</button>
          </div>
        `).join('')}
      ` : `<div class="list-empty">No products — add some from the Add tab</div>`}
    `;

    // ── Event listeners ──

    // Rename
    group.querySelector('.rename-btn').addEventListener('click', async e => {
      e.stopPropagation();
      const name = await openModal('Rename List', 'New name…', list.name);
      if (!name) return;
      const res = await renameList(list.id, name);
      renderLists(res.lists);
      populateSelects(res.lists);
      refreshCompareBtn(res.lists);
    });

    // Delete
    group.querySelector('.delete-btn').addEventListener('click', async e => {
      e.stopPropagation();
      const res = await deleteList(list.id);
      renderLists(res.lists);
      populateSelects(res.lists);
      refreshCompareBtn(res.lists);
      toast('List deleted', 'warning');
    });

    // Select all toggle
    const selectAllRow = group.querySelector('.select-all-row');
    if (selectAllRow) {
      selectAllRow.addEventListener('click', async () => {
        const res = await selectAll(list.id);
        renderLists(res.lists);
        refreshCompareBtn(res.lists);
      });
    }

    // Individual product toggle
    group.querySelectorAll('.product-toggle').forEach(el => {
      el.addEventListener('click', async () => {
        const listId = parseInt(el.dataset.list, 10);
        const idx    = parseInt(el.dataset.index, 10);
        const res    = await toggleProduct(listId, idx);
        renderLists(res.lists);
        refreshCompareBtn(res.lists);
      });
    });

    // Remove product
    group.querySelectorAll('.remove-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        const listId = parseInt(btn.dataset.list, 10);
        const idx    = parseInt(btn.dataset.index, 10);
        const res    = await removeProduct(listId, idx);
        renderLists(res.lists);
        populateSelects(res.lists);
        refreshCompareBtn(res.lists);
      });
    });

    container.appendChild(group);
  });

  refreshCompareBtn(lists);
}

// ── Tab switching ─────────────────────────────────────────────────────────────

function setupTabs() {
  document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(c => c.classList.add('hidden'));
      tab.classList.add('active');
      document.getElementById(`tab-${tab.dataset.tab}`).classList.remove('hidden');
    });
  });
}

// ── API health check ──────────────────────────────────────────────────────────

async function checkApi() {
  try {
    const r = await fetch(`${API}/health`, { signal: AbortSignal.timeout(2000) });
    return r.ok;
  } catch { return false; }
}

// ── Main ──────────────────────────────────────────────────────────────────────

async function init() {
  await initTheme();
  document.getElementById('theme-toggle').addEventListener('click', toggleTheme);

  setupTabs();

  // Load initial state
  let lists = await getLists();

  // Detect current page
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const url  = tab?.url || '';
  const platform = detectPlatform(url);
  const onProduct = platform && isProductPage(url);

  const titleEl    = document.getElementById('page-title');
  const urlEl      = document.getElementById('page-url');
  const platformEl = document.getElementById('page-platform');
  const addCurBtn  = document.getElementById('add-current-btn');

  if (onProduct) {
    platformEl.textContent = platform;
    platformEl.classList.remove('hidden');
    titleEl.textContent = truncate(
      tab.title?.replace(/[:\|–—-]\s*Amazon.*$/i, '').trim() || 'Product page', 80
    );
    urlEl.textContent = truncate(url, 55);
    addCurBtn.disabled = false;
  } else if (platform) {
    titleEl.textContent = 'Not a product listing';
    urlEl.textContent = 'Navigate to a specific product page to add it.';
  } else {
    titleEl.textContent = 'Not on a supported platform';
    urlEl.textContent = 'Supported: Amazon (.com .in .co.uk .de .ca)';
  }

  // Populate selects and render
  populateSelects(lists);
  renderLists(lists);
  refreshCompareBtn(lists);

  // ── Add current page ──
  addCurBtn.addEventListener('click', async () => {
    const listId = parseInt(document.getElementById('list-select-current').value, 10);
    if (!listId) { toast('Select a list first', 'warning'); return; }
    addCurBtn.disabled = true;
    const res = await addProduct(listId, url, platform);
    if (res.success) {
      lists = res.lists;
      renderLists(lists);
      populateSelects(lists);
      refreshCompareBtn(lists);
      toast('Added!');
    } else {
      toast(res.error, 'error');
      addCurBtn.disabled = false;
    }
  });

  // ── Add by URL ──
  const urlInput  = document.getElementById('url-input');
  const addUrlBtn = document.getElementById('add-url-btn');

  async function handleAddUrl() {
    const raw = urlInput.value.trim();
    if (!raw) return;
    const p = detectPlatform(raw);
    if (!p) { toast('Only Amazon URLs are supported', 'error'); return; }
    const listId = parseInt(document.getElementById('list-select-url').value, 10);
    if (!listId) { toast('Select a list first', 'warning'); return; }
    const res = await addProduct(listId, raw, p);
    if (res.success) {
      urlInput.value = '';
      lists = res.lists;
      renderLists(lists);
      populateSelects(lists);
      refreshCompareBtn(lists);
      toast('Added!');
    } else {
      toast(res.error, 'error');
    }
  }

  addUrlBtn.addEventListener('click', handleAddUrl);
  urlInput.addEventListener('keydown', e => { if (e.key === 'Enter') handleAddUrl(); });

  // ── New list (toolbar) ──
  document.getElementById('new-list-btn').addEventListener('click', async () => {
    const name = await openModal('New List', 'e.g. Laptops, Headphones…');
    if (!name) return;
    const res = await createList(name);
    lists = res.lists;
    renderLists(lists);
    populateSelects(lists);
    refreshCompareBtn(lists);
    toast(`"${name}" created`);
    // Switch to lists tab
    document.querySelector('[data-tab="lists"]').click();
  });

  // ── Quick new list (Add tab) ──
  document.getElementById('quick-new-list-btn').addEventListener('click', async () => {
    const name = await openModal('New List', 'e.g. Laptops, Headphones…');
    if (!name) return;
    const res = await createList(name);
    lists = res.lists;
    populateSelects(lists);
    renderLists(lists);
    refreshCompareBtn(lists);
    toast(`"${name}" created`);
  });

  // ── View Comparison ──
  document.getElementById('compare-btn').addEventListener('click', async () => {
    const alive = await checkApi();
    if (!alive) { toast('Backend not running — start it first', 'error'); return; }

    const current = await getLists();
    const selected = current.flatMap(l => l.products.filter(p => p.selected).map(p => p.url));
    if (selected.length < MIN) { toast(`Select at least ${MIN} products`, 'warning'); return; }

    const btn = document.getElementById('compare-btn');
    btn.disabled = true;
    document.getElementById('compare-btn-label').textContent = 'Starting…';

    try {
      const res = await fetch(`${API}/compare`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ urls: selected }),
      });
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Server error'); }
      const { job_id } = await res.json();
      await chrome.storage.session.set({ current_job_id: job_id });
      chrome.tabs.create({ url: chrome.runtime.getURL('results.html') });
    } catch (err) {
      toast(err.message, 'error');
      btn.disabled = false;
      document.getElementById('compare-btn-label').textContent = 'View Comparison';
    }
  });
}

document.addEventListener('DOMContentLoaded', init);
