'use strict';

/**
 * Content script — runs on Amazon product pages.
 *
 * Detects whether the current page is a product listing and notifies
 * the extension so the popup can enable the "Add Current Page" button
 * immediately on open.
 *
 * This script is injected automatically on matching Amazon URLs
 * (see manifest.json content_scripts).
 */

(function () {
  const url   = window.location.href;
  const title = document.getElementById('productTitle')?.textContent?.trim()
    ?? document.title;

  // A product page has /dp/ followed by a 10-character ASIN
  const isProductPage = /\/dp\/[A-Z0-9]{10}/i.test(url);

  // Broadcast to the extension background so it can cache this info
  chrome.runtime.sendMessage({
    type: 'PAGE_DETECTED',
    url,
    title,
    isProductPage,
  });
})();
