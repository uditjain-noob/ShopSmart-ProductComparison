'use strict';

let mode = 'login';

function setMode(nextMode) {
  mode = nextMode;
  document.getElementById('login-mode').classList.toggle('active', mode === 'login');
  document.getElementById('signup-mode').classList.toggle('active', mode === 'signup');
  document.getElementById('submit-btn').textContent = mode === 'login' ? 'Log in' : 'Create account';
  document.getElementById('message').textContent = '';
}

async function submitAuth() {
  const email = document.getElementById('email').value.trim();
  const password = document.getElementById('password').value;
  const message = document.getElementById('message');
  const button = document.getElementById('submit-btn');

  if (!email || !password) {
    message.textContent = 'Enter both email and password.';
    return;
  }

  button.disabled = true;
  button.textContent = mode === 'login' ? 'Logging in...' : 'Creating account...';

  try {
    const response = await fetch(`${API_BASE}/auth/${mode === 'login' ? 'login' : 'signup'}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Authentication failed.');

    await setAuthState(data.token, data.email);
    message.textContent = 'Signed in. You can close this tab.';
    message.classList.add('success');
  } catch (err) {
    message.classList.remove('success');
    message.textContent = err.message;
  } finally {
    button.disabled = false;
    button.textContent = mode === 'login' ? 'Log in' : 'Create account';
  }
}

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('login-mode').addEventListener('click', () => setMode('login'));
  document.getElementById('signup-mode').addEventListener('click', () => setMode('signup'));
  document.getElementById('submit-btn').addEventListener('click', submitAuth);
  document.getElementById('password').addEventListener('keydown', event => {
    if (event.key === 'Enter') submitAuth();
  });
});
