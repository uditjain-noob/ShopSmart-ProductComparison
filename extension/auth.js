'use strict';

async function getAuthState() {
  const { auth_token, auth_email } = await chrome.storage.local.get(['auth_token', 'auth_email']);
  return { token: auth_token || null, email: auth_email || null };
}

async function setAuthState(token, email) {
  await chrome.storage.local.set({ auth_token: token, auth_email: email });
}

async function clearAuthState() {
  await chrome.storage.local.remove(['auth_token', 'auth_email']);
}

async function authHeaders(extra = {}) {
  const { token } = await getAuthState();
  return {
    ...extra,
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

async function apiFetch(path, options = {}) {
  const headers = await authHeaders(options.headers || {});
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (response.status === 401) {
    await clearAuthState();
    chrome.tabs.create({ url: chrome.runtime.getURL('login.html') });
  }
  return response;
}

async function requireAuth() {
  const auth = await getAuthState();
  if (!auth.token) {
    chrome.tabs.create({ url: chrome.runtime.getURL('login.html') });
    return null;
  }
  return auth;
}
