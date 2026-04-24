# ShopSmart Comparison — User Guide

> Compare products on Amazon before you buy — without opening twenty tabs.

---

## What is this?

ShopSmart Comparison is a **Chrome browser extension** that lets you collect Amazon products as you browse and then generate a detailed, AI-powered side-by-side comparison with a single click.

Instead of jumping back and forth between product pages, copying specs into a notes app, and trying to remember which reviewer said what — you just add the products you're considering, click **View Comparison**, and get a full report. And if you're still not satisfied, the built-in **AI discovery agent** can search Amazon on your behalf and surface three better-fitting options — automatically.

For a youtube demo please watch the following video :

YOUTUBE DEMO LINK : [YOUTUBE DEMO](https://youtu.be/zvlUJTe-xXg)

---

## What do you get?

When you trigger a comparison you get a full-page report with six sections:

| Section | What it tells you |
|---|---|
| **Find Your Best Match** | Answer 5 quick questions about your priorities and the tool highlights which product suits *you* specifically |
| **Comparison Summary** | A plain-English overview of how the products differ — the key trade-offs explained |
| **Recommendation** | A clear conclusion: which product wins and for which kind of buyer |
| **Pros & Cons** | One card per product with strengths, weaknesses, and real customer quotes |
| **Specifications** | A side-by-side table of technical specs so you can compare numbers at a glance |
| **Smarter Product Finder** | After answering the questionnaire, the AI agent searches Amazon for 3 products that fit your criteria *better* than what you've already seen |

You can also **save the whole report as a PDF** to read later or share with someone.

---

## Before you start — one-time setup

The tool has two parts: a small program that runs on your computer (the "backend") and the Chrome extension you use while browsing.

### What you need

- A Mac or Windows computer with Python installed (version 3.11 or newer)
- Google Chrome
- A free Gemini AI key from Google
- *(Optional but recommended)* A ScraperAPI key if Amazon keeps blocking the tool

### Step 1 — Download and set up

Open a terminal and run:

```bash
cd Assignments/Assignment_1
uv sync
```

This installs all the software the tool needs. Takes about 30 seconds.

### Step 2 — Add your API key

Open the file called `.env` (it's in the `Assignments/Assignment_1` folder) and fill in your key:

```
GEMINI_API_KEY=paste_your_key_here
```

Get a free Gemini key at [aistudio.google.com](https://aistudio.google.com/).

> **Getting blocked by Amazon?** Add a ScraperAPI key too — it routes requests through different IPs so Amazon doesn't block them.
> ```
> SCRAPER_API_KEY=paste_your_scraperapi_key_here
> ```
> Get a free ScraperAPI key (1,000 requests/month) at [scraperapi.com](https://www.scraperapi.com/).

### Step 3 — Start the backend program

Every time you want to use the tool, open a terminal and run:

```bash
cd Assignments/Assignment_1
uv run uvicorn backend.api:app --reload --port 8000
```

You'll see a message like `Uvicorn running on http://127.0.0.1:8000`. **Leave this window open** while you use the extension — it's doing all the work in the background.

### Step 4 — Install the extension in Chrome

1. Open Chrome and go to `chrome://extensions`
2. Turn on **Developer mode** using the toggle in the top-right corner
3. Click **Load unpacked**
4. Navigate to the `Assignments/Assignment_1/extension/` folder and select it
5. The extension icon appears in your toolbar (click the puzzle piece 🧩 to pin it)

You only need to do steps 1–4 once. After that, just remember to start the backend (Step 3) each time.

---

## Using it day-to-day

### Adding products

1. Go to an Amazon product page (e.g. a laptop you're considering)
2. Click the extension icon in your Chrome toolbar
3. On the **Add Product** tab, click **"Add Current Page"**
4. The product is saved to your list — nothing is downloaded yet

Repeat for every product you want to compare (you need at least 2, up to 5).

### Organising into lists

You can have multiple named lists — for example:
- "MacBooks" for laptops you're deciding between
- "Headphones" for a separate shopping decision

Create a new list from the **My Lists** tab by clicking "Create new list" and giving it a name.

### Running a comparison

1. Switch to the **My Lists** tab
2. Tick the checkboxes next to the products you want to compare (at least 2)
3. Click **"View Comparison (N selected)"**

A new tab opens showing a loading screen. It typically takes **30–90 seconds** — the tool is reading each product page and then thinking through the comparison. You'll see live progress:

```
✓ Scraping product data
✓ Generating product profiles
⟳ Writing comparison, recommendation & questionnaire
```

### Reading the results

**Best Match questionnaire** — at the top of the page you'll see 5 questions tailored to the specific products you're comparing. They're not generic — if one laptop has more RAM and another has longer battery life, the questions will ask which matters more *to you*. Answer all 5 and click **"Find My Best Match"** — the product that suits your answers best gets highlighted with a gold star badge.

**Comparison Summary** — a written explanation of the key differences between the products. Good for understanding the bigger picture before diving into specs.

**Recommendation** — a direct conclusion. If one product is a clear winner, it says so. If it depends on your use case, it explains the trade-offs.

**Pros & Cons cards** — one card per product. Each shows the price, a sentiment score based on real customer reviews, a list of pros, a list of cons, and a few direct quotes from reviewers.

**Specifications table** — a grid showing technical specs side-by-side. Only specs that appear for at least two products are shown, keeping it clean.

### Using the Smarter Product Finder

After you submit the questionnaire and see your Best Match, a new section appears at the bottom of the page: **"Search for Better Options"**.

Click the button to launch the AI discovery agent. It will:

1. Read your questionnaire answers and the products you already compared
2. Infer your budget range automatically from the prices of those products
3. Search Amazon India for candidates that better match your stated priorities
4. Evaluate up to 10 products in detail, then output the 3 best fits as suggestion cards

Each suggestion card shows:
- The product title, price, and star rating
- A **"Why this fits you"** explanation written specifically for your answers
- A **"View on Amazon"** button to open the listing directly
- An **"Add to comparison"** button to save it to one of your lists so you can run a fresh comparison including the new product

The agent uses Google Gemini with automatic model fallback (Flash → Pro → Flash-Lite) so it keeps working even when one model is busy.

> The search typically takes **30–60 seconds**. Live progress is shown while the agent works.

### Saving as PDF

Click **"Save as PDF"** in the top-right corner of the results page. Your browser's print dialog opens — choose **"Save as PDF"** as the destination. The saved file is clean and print-ready (no buttons, spinners, or the discovery section).

---

## Changing the colour theme

Click the **sun / moon icon** in the top-right corner of either the popup or the results page to switch between dark mode (default) and light mode. Your preference is saved and remembered.

---

## Frequently asked questions

**Do I need the internet?**
Yes — the tool needs internet access to read Amazon pages and to use the Gemini AI service.

**Does it store my data anywhere?**
No. Everything runs on your own computer. Product URLs are held only in your browser's session memory and cleared when you close Chrome. The backend has no database.

**Why does it sometimes say a product was "skipped"?**
Amazon occasionally blocks automated requests. When that happens for a specific product, the tool skips it and runs the comparison with the remaining products. You'll see a warning at the top of the results page explaining which products were skipped and why. Adding a ScraperAPI key (see setup) prevents most skips.

**The comparison seems to have got a detail wrong. What should I do?**
AI summaries are based on the information available on the product page. If a spec is missing on the Amazon listing, the AI won't know about it. Always verify critical specifications directly on the product page before buying.

**Can I compare products from different websites?**
Not yet — currently only Amazon is supported. Other platforms are planned for a future update.

**The tool says "Cannot connect to backend". What do I do?**
The backend program isn't running. Open a terminal and run the command from Step 3 again.

**The Smarter Product Finder says the session expired. What happened?**
The discovery agent stores its job in the backend's memory. If you restart the backend while the agent is running (or was recently finished), the job ID is lost. Click **"Search for Better Options"** again to start a new search.

**The agent says it couldn't find any products. What should I try?**
The agent infers its search from your questionnaire answers. Try giving more specific answers (e.g. name a concrete use case rather than "general use") and run the search again. You can also check that the backend server is still running in the terminal.

---

## Colour themes

The tool comes with a "Sage & Slate" colour palette — a calm, low-eye-strain design with green accents and muted backgrounds.

- **Dark mode** (default) — slate background, soft text, green and peach accents
- **Light mode** — white/cream background, same accent colours

Toggle between them using the sun/moon icon in the header.

---

*For technical documentation, see [product_comparison.md](product_comparison.md).*
