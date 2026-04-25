'use strict';

/**
 * Background service worker — multi-list state management.
 *
 * State shape (stored in chrome.storage.session):
 * {
 *   lists: [
 *     { id, savedListId, name, products: [{ url, platform, selected }] }
 *   ]
 * }
 *
 * Session storage clears automatically when the browser is closed (per spec).
 */

function nextId(lists) {
  return lists.length === 0 ? 1 : Math.max(...lists.map(l => l.id)) + 1;
}

async function getLists() {
  return new Promise(resolve => {
    chrome.storage.session.get(['lists'], result => {
      resolve(result.lists || []);
    });
  });
}

async function saveLists(lists) {
  return new Promise(resolve => {
    chrome.storage.session.set({ lists }, resolve);
  });
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  (async () => {
    const lists = await getLists();

    switch (msg.type) {

      case 'GET_LISTS':
        sendResponse({ lists });
        break;

      // ── List CRUD ──────────────────────────────────────────────────────────

      case 'CREATE_LIST': {
        const name = (msg.name || 'New List').trim().slice(0, 40);
        const newList = { id: nextId(lists), name, products: [] };
        lists.push(newList);
        await saveLists(lists);
        sendResponse({ success: true, lists, newId: newList.id });
        break;
      }

      case 'RENAME_LIST': {
        const list = lists.find(l => l.id === msg.listId);
        if (!list) { sendResponse({ success: false, error: 'List not found' }); break; }
        list.name = (msg.name || list.name).trim().slice(0, 40);
        await saveLists(lists);
        sendResponse({ success: true, lists });
        break;
      }

      case 'SET_SAVED_LIST_ID': {
        const list = lists.find(l => l.id === msg.listId);
        if (!list) { sendResponse({ success: false, error: 'List not found' }); break; }
        list.savedListId = msg.savedListId;
        await saveLists(lists);
        sendResponse({ success: true, lists });
        break;
      }

      case 'DELETE_LIST': {
        const idx = lists.findIndex(l => l.id === msg.listId);
        if (idx === -1) { sendResponse({ success: false, error: 'List not found' }); break; }
        lists.splice(idx, 1);
        await saveLists(lists);
        sendResponse({ success: true, lists });
        break;
      }

      // ── Product CRUD ───────────────────────────────────────────────────────

      case 'ADD_PRODUCT': {
        let list = lists.find(l => l.id === msg.listId);
        if (!list) {
          // Auto-create a default list if none exists
          list = { id: nextId(lists), name: 'My List', products: [] };
          lists.push(list);
        }
        if (list.products.some(p => p.url === msg.url)) {
          sendResponse({ success: false, error: 'Already in this list.' });
          break;
        }
        list.products.push({ url: msg.url, platform: msg.platform, selected: true });
        await saveLists(lists);
        sendResponse({ success: true, lists });
        break;
      }

      case 'REMOVE_PRODUCT': {
        const list = lists.find(l => l.id === msg.listId);
        if (!list) { sendResponse({ success: false, error: 'List not found' }); break; }
        list.products.splice(msg.index, 1);
        await saveLists(lists);
        sendResponse({ success: true, lists });
        break;
      }

      case 'TOGGLE_PRODUCT': {
        const list = lists.find(l => l.id === msg.listId);
        if (!list || !list.products[msg.index]) { sendResponse({ success: false }); break; }
        list.products[msg.index].selected = !list.products[msg.index].selected;
        await saveLists(lists);
        sendResponse({ success: true, lists });
        break;
      }

      case 'SELECT_ALL': {
        const list = lists.find(l => l.id === msg.listId);
        if (!list) { sendResponse({ success: false }); break; }
        const allSelected = list.products.every(p => p.selected);
        list.products.forEach(p => { p.selected = !allSelected; });
        await saveLists(lists);
        sendResponse({ success: true, lists });
        break;
      }

      case 'CLEAR_LIST': {
        const list = lists.find(l => l.id === msg.listId);
        if (!list) { sendResponse({ success: false }); break; }
        list.products = [];
        await saveLists(lists);
        sendResponse({ success: true, lists });
        break;
      }

      default:
        sendResponse({ error: `Unknown message type: ${msg.type}` });
    }
  })();

  return true; // keep channel open for async response
});
