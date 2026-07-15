"""Mama Bima insurance scraper → insuranceiq schema.

Uses Playwright for everything (product pages + quote flow) so that
JavaScript-rendered content (FAQ accordions, dynamic sections) is fully captured.

One browser session per product:
  1. Load product page → expand accordions → extract rich data
  2. Navigate to quote flow → step through questions

Writes into:
  insuranceiq.insurers
  insuranceiq.products
  insuranceiq.quote_questions

Run standalone:
    python -m ganji_mtaani_agent.scrapers.mamabima
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from bs4 import BeautifulSoup
from playwright.sync_api import Page, sync_playwright

from ganji_mtaani_agent.db.postgres import get_postgres_connection

MAMABIMA_BASE = "https://mamabima.com"
CLIENT_BASE   = "https://client.mamabima.com"
INSURER_SLUG  = "mamabima"
INSURER_NAME  = "Mama Bima"

# ---------------------------------------------------------------------------
# Product catalogue
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _Product:
    slug:         str
    name:         str
    product_type: str
    source_path:  str   # relative to MAMABIMA_BASE
    quote_path:   str   # relative to CLIENT_BASE; "" = no quote flow


CATALOGUE: tuple[_Product, ...] = (
    _Product("mb-last-expense",      "Last Expense Cover",     "life",   "/plans/life/last-expense",     "/life/last-expense"),
    _Product("mb-whole-life",        "Whole Life Insurance",   "life",   "/plans/life/whole-life",       "/life/whole-life"),
    _Product("mb-endowment-savings", "Endowment Savings",      "life",   "/plans/life/endowment",        "/life/endowment-savings"),
    _Product("mb-education-savings", "Education Savings Plan", "life",   "/plans/life/education",        "/life/education-savings"),
    _Product("mb-critical-illness",  "Critical Illness Cover", "life",   "/plans/life/critical-illness", "/life/critical-illness"),
    _Product("mb-medical",           "Medical Insurance",      "health", "/plans/medical",               "/medical"),
    _Product("mb-motor",             "Motor Insurance",        "motor",  "/plans/motor",                 "/motor"),
    _Product("mb-travel",            "Travel Insurance",       "travel", "/plans/travel",                "/travel"),
    _Product("mb-retirement",        "Retirement Planning",    "life",   "/plans/retirement",            "/life/retirement"),
    _Product("mb-estate-planning",   "Estate Planning",        "life",   "/plans/estate-planning",       ""),
)

_NAV_RE     = re.compile(r"^(next|back|cancel|prev|submit|continue|proceed|get (a )?quote|apply|sign up|login)$", re.I)
_STEPPER_RE = re.compile(r"^[−\-+]$")

# ---------------------------------------------------------------------------
# Phase 1: product page extraction (Playwright)
# ---------------------------------------------------------------------------

def _expand_accordions(page: Page) -> None:
    """
    Mamabima FAQ buttons have no aria-expanded — they're plain buttons.
    We expand them inside _get_faqs() directly. This function handles
    any other standard accordion patterns that might appear on other products.
    Presses Escape afterwards to dismiss any overlay accidentally opened
    (e.g. mobile nav menus that match button[aria-expanded="false"]).
    """
    for sel in [
        'button[aria-expanded="false"]',
        '[data-state="closed"] > button',
        'button[data-state="closed"]',
    ]:
        try:
            for el in page.locator(sel).all():
                try:
                    if el.is_visible(timeout=500):
                        el.click(timeout=1_500)
                        page.wait_for_timeout(250)
                except Exception:
                    pass
        except Exception:
            pass
    # Dismiss any overlay that accordion/nav clicks may have opened
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
    except Exception:
        pass


def _soup(page: Page) -> BeautifulSoup:
    return BeautifulSoup(page.content(), "html.parser")


# ---- specific extractors (based on actual Mamabima DOM structure) ----------

def _get_description(soup: BeautifulSoup) -> str:
    chunks: list[str] = []
    for tag in soup.find_all(["h1", "p"]):
        t = tag.get_text(strip=True)
        if len(t) > 60:
            chunks.append(t)
        if len(chunks) >= 3:
            break
    return " ".join(chunks)


def _get_tagline(soup: BeautifulSoup) -> str | None:
    for tag in soup.find_all(["h2", "h3", "p"]):
        t = tag.get_text(strip=True)
        if 20 < len(t) < 120:
            return t
    return None


def _get_age_range(soup: BeautifulSoup) -> dict:
    text = soup.get_text(separator=" ")
    m = re.search(r"(\d{1,2})\s*[-–to]+\s*(\d{2,3})\s*years?", text, re.I)
    return {"min": int(m.group(1)), "max": int(m.group(2))} if m else {"min": None, "max": None}


def _get_who_for_cards(soup: BeautifulSoup) -> list[dict]:
    """
    Structure: h2 'Who Is This For?' inside div.text-center.mb-8
    Parent of that div is a div.rounded-3xl container.
    Cards inside that container are div.group elements, each with h3 + p.
    """
    h2 = soup.find("h2", string=re.compile(r"who is this for", re.I))
    if not h2:
        return []
    # h2 → title div → rounded-3xl container
    container = h2.find_parent("div", class_=re.compile(r"rounded-3xl"))
    if not container:
        return []
    cards = []
    for card in container.find_all("div", class_=re.compile(r"\bgroup\b")):
        h3 = card.find("h3")
        p  = card.find("p")
        if h3 and p:
            cards.append({"title": h3.get_text(strip=True), "description": p.get_text(strip=True)})
    return cards[:10]


def _get_who_covered(soup: BeautifulSoup) -> str | None:
    h2 = soup.find("h2", string=re.compile(r"who can be covered", re.I))
    if not h2:
        return None
    container = h2.find_parent("div", class_=re.compile(r"rounded-3xl")) or h2.find_parent("div")
    return container.get_text(separator=" ", strip=True)[:600] if container else None


def _get_waiting_periods(soup: BeautifulSoup) -> list[dict]:
    """
    Structure: h2 'Waiting Periods' inside div.text-center.mb-8
    Parent is a div.rounded-3xl container.
    Each card: div.flex.items-start.gap-4 with:
      - div (badge) containing period text e.g. "1 month", "None"
      - p containing description
    """
    h2 = soup.find("h2", string=re.compile(r"waiting period", re.I))
    if not h2:
        return []
    container = h2.find_parent("div", class_=re.compile(r"rounded-3xl"))
    if not container:
        return []

    periods = []
    badge_re = re.compile(r"^(\d+\s+(?:day|week|month|year)s?|None|Immediate|N/A)$", re.I)

    for card in container.find_all("div", class_=re.compile(r"flex items-start gap-4|flex.*items-start.*gap")):
        # First inner div = badge, first p = description
        badge_div = card.find("div")
        desc_p    = card.find("p")
        if badge_div and desc_p:
            period = badge_div.get_text(strip=True)
            desc   = desc_p.get_text(strip=True)
            if badge_re.match(period) and desc:
                periods.append({"period": period, "description": desc})

    return periods[:10]


def _get_min_waiting_days(periods: list[dict]) -> int | None:
    days: list[int] = []
    for p in periods:
        m = re.match(r"(\d+)\s+(day|week|month|year)", p["period"], re.I)
        if m:
            n, unit = int(m.group(1)), m.group(2).lower()
            mult = {"day": 1, "week": 7, "month": 30, "year": 365}.get(unit, 1)
            days.append(n * mult)
    return min(days) if days else None


def _get_key_benefits(soup: BeautifulSoup) -> list[dict]:
    # Mamabima uses h3 cards with icons, not ul/li — extract the h3 + p pairs
    h2 = soup.find("h2", string=re.compile(r"why.*stand|benefit|how it works|what.*cover", re.I))
    if not h2:
        return []
    container = h2.find_parent(["section", "div"])
    if not container:
        return []
    items = []
    for h3 in container.find_all("h3"):
        title = h3.get_text(strip=True)
        p = h3.find_next_sibling("p") or h3.find_parent("div").find("p") if h3.find_parent("div") else None
        desc = p.get_text(strip=True) if p else ""
        if title:
            items.append({"title": title, "description": desc})
    return items[:12]


def _get_benefit_options(soup: BeautifulSoup) -> list[dict] | None:
    options = []
    for tbl in soup.find_all("table"):
        headers = [th.get_text(strip=True) for th in tbl.find_all("th")]
        rows = [[td.get_text(strip=True) for td in tr.find_all("td")]
                for tr in tbl.find_all("tr") if tr.find_all("td")]
        if headers and rows:
            options.append({"headers": headers, "rows": rows})
    return options or None


def _get_exclusions(soup: BeautifulSoup) -> list[str]:
    """
    Structure: h2 'Important Exclusions' inside div[data-slot='card-header']
    which is inside div[data-slot='card'].
    The exclusion items are span.leading-relaxed.text-sm inside
    div[data-slot='card-content'].
    """
    h2 = soup.find("h2", string=re.compile(r"important exclusion|exclusion", re.I))
    if not h2:
        return []
    card_header = h2.find_parent(attrs={"data-slot": "card-header"})
    card = card_header.find_parent(attrs={"data-slot": "card"}) if card_header else None
    if not card:
        return []
    card_content = card.find(attrs={"data-slot": "card-content"})
    if not card_content:
        return []
    # Each exclusion text is in a span with class "leading-relaxed text-sm"
    items = [
        span.get_text(strip=True)
        for span in card_content.find_all("span", class_=re.compile(r"leading-relaxed"))
        if span.get_text(strip=True)
    ]
    return items[:20]


def _get_faqs(page: Page) -> list[dict]:
    """
    FAQ answers are JS-injected on click — not present in initial DOM.
    Structure (inside <section>):
      div.bg-white.border.border-gray-100.rounded-2xl  (one per FAQ item)
        button
          span.font-semibold  ← question text
          svg (chevron)
        [div injected here after click with answer p.text-gray-600]

    Strategy: iterate all <section> tags, find the one with the FAQ h2,
    then click each rounded-2xl button and read the answer.
    """
    faqs: list[dict] = []

    # Find the <section> containing the FAQ h2
    faq_section = None
    for sec in page.locator("section").all():
        try:
            h2s = sec.locator("h2").all()
            for h2 in h2s:
                if re.search(r"Frequently|FAQ", h2.inner_text(timeout=300), re.I):
                    faq_section = sec
                    break
        except Exception:
            pass
        if faq_section:
            break

    if not faq_section:
        return faqs

    seen: set[str] = set()
    for item in faq_section.locator("div.rounded-2xl").all():
        try:
            btn = item.locator("button").first
            if btn.count() == 0:
                continue

            # Get question from the span inside the button (avoids SVG text)
            q_span = btn.locator("span").first
            if q_span.count() == 0:
                continue
            question = q_span.inner_text(timeout=500).strip()
            if not question or len(question) < 8 or question in seen or _NAV_RE.match(question):
                continue
            seen.add(question)

            # Click via JS to inject the answer — bypasses any overlay interception
            btn.evaluate("el => el.click()")
            page.wait_for_timeout(900)  # allow React state + CSS transition

            # The answer is injected as a sibling div to the button inside item
            full_text = item.inner_text(timeout=1_000).strip()
            answer = full_text.replace(question, "", 1).strip()
            # Strip any leftover SVG/icon characters
            answer = re.sub(r"^[\s\n▲▼›‹↑↓]+", "", answer).strip()

            if len(answer) > 8:
                faqs.append({"question": question, "answer": answer[:800]})

        except Exception:
            pass

    return faqs[:20]


def _extract_page_data(page: Page, product: _Product) -> dict[str, Any]:
    """Full product page extraction after accordions have been expanded."""
    s = _soup(page)
    waiting = _get_waiting_periods(s)
    who_for = _get_who_for_cards(s)

    return {
        "description":          _get_description(s),
        "tagline":              _get_tagline(s),
        "min_age":              _get_age_range(s).get("min"),
        "max_age":              _get_age_range(s).get("max"),
        # Stored as JSON string in TEXT column so structure is preserved
        "who_is_it_for":       json.dumps(who_for, ensure_ascii=False) if who_for else None,
        "who_can_be_covered":  _get_who_covered(s),
        "eligibility_notes":   None,
        "key_benefits":        _get_key_benefits(s),
        "benefit_options":     _get_benefit_options(s),
        "exclusions":          _get_exclusions(s),
        "waiting_period_days": _get_min_waiting_days(waiting),
        # Also stored as JSON string for full structured access
        "waiting_period_notes": json.dumps(waiting, ensure_ascii=False) if waiting else None,
        "faqs":                 _get_faqs(page),
        "quote_url":            (CLIENT_BASE + product.quote_path) if product.quote_path else None,
    }


# ---------------------------------------------------------------------------
# Phase 2: quote flow (same Playwright session)
# ---------------------------------------------------------------------------

def _navigate_quote_flow(page: Page, product: _Product, *, max_steps: int = 15) -> list[dict]:
    if not product.quote_path:
        return []

    url = CLIENT_BASE + product.quote_path
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(3_000)
    except Exception as exc:
        print(f"    quote page load failed: {ascii(str(exc))[:80]}", flush=True)
        return []

    questions: list[dict] = []
    seen: dict[str, int] = {}

    for step_num in range(1, max_steps + 1):
        step = _extract_step(page, step_num)
        if not step:
            break
        q_text = step["question_text"]

        if q_text in seen:
            print(f"    loop detected at step {step_num} (same as step {seen[q_text]}), stopping", flush=True)
            break
        seen[q_text] = step_num

        questions.append(step)
        print(f"    step {step_num}: {q_text[:70]}", flush=True)

        if not _fill_and_advance(page, step):
            break
        page.wait_for_timeout(2_500)

    return questions


def _extract_step(page: Page, step_num: int) -> dict | None:
    total    = _read_total_steps(page)
    question = _read_question(page)
    if not question:
        return None
    return {"step_number": step_num, "total_steps": total, "question_text": question, **_detect_field(page)}


def _read_total_steps(page: Page) -> int | None:
    for sel in ["[class*='progress']", "[class*='step']", "p", "span"]:
        try:
            for el in page.locator(sel).all()[:5]:
                if el.is_visible():
                    m = re.search(r"(\d+)\s*of\s*(\d+)", el.inner_text())
                    if m:
                        return int(m.group(2))
        except Exception:
            pass
    return None


def _read_question(page: Page) -> str:
    for sel in ["[class*='question']", "[class*='label']", "label", "h3", "h2",
                "[class*='title']", "[class*='heading']", "p", "h1"]:
        try:
            for el in page.locator(sel).all()[:5]:
                if el.is_visible():
                    t = el.inner_text().strip()
                    if len(t) > 6 and not _NAV_RE.match(t):
                        return t
        except Exception:
            pass
    return ""


def _is_stepper(page: Page) -> bool:
    try:
        btns = [b.inner_text().strip() for b in page.get_by_role("button").all() if b.is_visible()]
        return sum(1 for b in btns if _STEPPER_RE.match(b)) >= 1
    except Exception:
        return False


def _detect_field(page: Page) -> dict:
    if _is_stepper(page):
        try:
            val_el = page.locator('[class*="count"],[class*="value"],[class*="number"],input[readonly]').first
            cur_val = "0"
            if val_el.count() > 0 and val_el.is_visible():
                cur_val = val_el.inner_text().strip() or val_el.input_value()
        except Exception:
            cur_val = "0"
        return {"field_type": "stepper", "min_value": "0", "max_value": None,
                "default_value": cur_val, "options": None}

    for sel in ['input[type="number"]', 'input[inputmode="numeric"]']:
        try:
            el = page.locator(sel).first
            if el.count() > 0 and el.is_visible():
                return {"field_type": "number", "min_value": el.get_attribute("min") or "",
                        "max_value": el.get_attribute("max") or "", "default_value": el.input_value(), "options": None}
        except Exception:
            pass

    try:
        el = page.locator("select").first
        if el.count() > 0 and el.is_visible():
            opts = [{"value": o.get_attribute("value") or "", "label": o.inner_text().strip()}
                    for o in page.locator("select option").all() if o.inner_text().strip()]
            return {"field_type": "select", "min_value": None, "max_value": None, "default_value": None, "options": opts}
    except Exception:
        pass

    try:
        radios = page.locator('input[type="radio"]')
        if radios.count() > 0:
            opts = []
            for r in radios.all():
                val = r.get_attribute("value") or ""
                rid = r.get_attribute("id") or ""
                lbl = page.locator(f'label[for="{rid}"]')
                opts.append({"value": val, "label": lbl.inner_text().strip() if lbl.count() > 0 else val})
            return {"field_type": "radio", "min_value": None, "max_value": None, "default_value": None, "options": opts}
    except Exception:
        pass

    try:
        opts = []
        for btn in page.get_by_role("button").all():
            if btn.is_visible():
                t = btn.inner_text().strip()
                if t and len(t) < 60 and not _NAV_RE.search(t) and not _STEPPER_RE.match(t):
                    opts.append({"value": t, "label": t})
        if len(opts) >= 2:
            return {"field_type": "choice_buttons", "min_value": None, "max_value": None,
                    "default_value": None, "options": opts}
    except Exception:
        pass

    try:
        el = page.locator('input[type="text"],input:not([type])').first
        if el.count() > 0 and el.is_visible():
            return {"field_type": "text", "min_value": None, "max_value": None, "default_value": "", "options": None}
    except Exception:
        pass

    return {"field_type": "unknown", "min_value": None, "max_value": None, "default_value": None, "options": None}


def _fill_and_advance(page: Page, step: dict) -> bool:
    ft = step.get("field_type", "unknown")
    q  = step.get("question_text", "").lower()
    try:
        if ft == "stepper":
            plus = page.get_by_role("button", name="+").first
            if plus.count() > 0 and plus.is_enabled():
                plus.click()
                page.wait_for_timeout(500)
        elif ft == "number":
            val = _pick_number(q, step)
            for sel in ['input[type="number"]', 'input[inputmode="numeric"]']:
                el = page.locator(sel).first
                if el.count() > 0:
                    el.triple_click()
                    el.fill(str(val))
                    break
        elif ft == "select":
            opts = step.get("options") or []
            pick = opts[1]["value"] if len(opts) > 1 else (opts[0]["value"] if opts else "")
            if pick:
                page.locator("select").select_option(value=pick)
        elif ft == "radio":
            page.locator('input[type="radio"]').first.click()
        elif ft == "choice_buttons":
            opts = step.get("options") or []
            if opts:
                page.get_by_role("button", name=opts[0]["label"]).first.click()
                page.wait_for_timeout(1_500)
                for name in ("Next", "Continue", "Proceed"):
                    btn = page.get_by_role("button", name=name)
                    if btn.count() > 0 and btn.first.is_visible():
                        btn.first.click()
                        break
                return True
        elif ft == "text":
            page.locator('input[type="text"],input:not([type])').first.fill("Test")

        for name in ("Next", "Continue", "Proceed"):
            btn = page.get_by_role("button", name=name)
            if btn.count() > 0 and btn.first.is_visible():
                btn.first.click()
                return True

        for sel in ['button[class*="next" i]', 'button:has-text("Next")', 'a:has-text("Next")']:
            el = page.locator(sel).first
            if el.count() > 0 and el.is_visible():
                el.click()
                return True

    except Exception as exc:
        print(f"      fill error: {ascii(str(exc))[:100]}", flush=True)
    return False


def _pick_number(question: str, step: dict) -> int:
    lo = int(step.get("min_value") or 0)
    hi = int(step.get("max_value") or 100)
    if "age" in question:
        return max(lo, min(35, hi))
    if any(w in question for w in ("coverage", "sum", "assured", "benefit", "cover")):
        return max(lo, min(500_000, hi))
    if any(w in question for w in ("term", "year", "duration")):
        return max(lo, min(10, hi))
    if any(w in question for w in ("child", "parent", "sibling", "member")):
        return max(lo, min(0, hi))
    if any(w in question for w in ("vehicle", "car", "value")):
        return max(lo, min(1_000_000, hi))
    return (lo + hi) // 2


# ---------------------------------------------------------------------------
# Per-product scrape (one Playwright session)
# ---------------------------------------------------------------------------

def scrape_product(product: _Product, *, scrape_quotes: bool = True) -> tuple[dict, list[dict]]:
    """Open one browser, scrape product page then quote flow."""
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            print(f"  [{product.slug}] loading product page...", flush=True)
            page.goto(MAMABIMA_BASE + product.source_path,
                      wait_until="networkidle", timeout=60_000)
            page.wait_for_timeout(2_000)

            print(f"  [{product.slug}] expanding accordions...", flush=True)
            _expand_accordions(page)
            page.wait_for_timeout(1_000)

            data = _extract_page_data(page, product)

            questions: list[dict] = []
            if scrape_quotes and product.quote_path:
                print(f"  [{product.slug}] scraping quote flow...", flush=True)
                questions = _navigate_quote_flow(page, product)

        except Exception as exc:
            raise RuntimeError(f"browser error: {ascii(str(exc))[:200]}") from exc
        finally:
            browser.close()

    return data, questions


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _upsert_insurer(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO insuranceiq.insurers (insurer_slug, insurer_name, website)
            VALUES (%s, %s, %s)
            ON CONFLICT (insurer_slug) DO UPDATE SET
                insurer_name = EXCLUDED.insurer_name,
                website      = EXCLUDED.website
            """,
            (INSURER_SLUG, INSURER_NAME, MAMABIMA_BASE),
        )


def _upsert_product(conn, product: _Product, data: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO insuranceiq.products (
                insurer_slug, product_slug, product_name, product_type,
                tagline, description,
                min_age, max_age, who_is_it_for, who_can_be_covered, eligibility_notes,
                key_benefits, benefit_options, exclusions,
                waiting_period_days, waiting_period_notes,
                faqs, product_url, quote_url, quotable,
                created_at, updated_at
            ) VALUES (
                %s,%s,%s,%s, %s,%s,
                %s,%s,%s,%s,%s,
                %s::jsonb,%s::jsonb,%s::jsonb,
                %s,%s,
                %s::jsonb,%s,%s,%s,
                NOW(),NOW()
            )
            ON CONFLICT (insurer_slug, product_slug) DO UPDATE SET
                product_name         = EXCLUDED.product_name,
                tagline              = EXCLUDED.tagline,
                description          = EXCLUDED.description,
                min_age              = EXCLUDED.min_age,
                max_age              = EXCLUDED.max_age,
                who_is_it_for        = EXCLUDED.who_is_it_for,
                who_can_be_covered   = EXCLUDED.who_can_be_covered,
                eligibility_notes    = EXCLUDED.eligibility_notes,
                key_benefits         = EXCLUDED.key_benefits,
                benefit_options      = EXCLUDED.benefit_options,
                exclusions           = EXCLUDED.exclusions,
                waiting_period_days  = EXCLUDED.waiting_period_days,
                waiting_period_notes = EXCLUDED.waiting_period_notes,
                faqs                 = EXCLUDED.faqs,
                product_url          = EXCLUDED.product_url,
                quote_url            = EXCLUDED.quote_url,
                quotable             = EXCLUDED.quotable,
                updated_at           = NOW()
            """,
            (
                INSURER_SLUG, product.slug, product.name, product.product_type,
                data.get("tagline"), data.get("description"),
                data.get("min_age"), data.get("max_age"),
                data.get("who_is_it_for"), data.get("who_can_be_covered"), data.get("eligibility_notes"),
                json.dumps(data.get("key_benefits") or [], default=str),
                json.dumps(data.get("benefit_options") or [], default=str),
                json.dumps(data.get("exclusions") or [], default=str),
                data.get("waiting_period_days"), data.get("waiting_period_notes"),
                json.dumps(data.get("faqs") or [], default=str),
                MAMABIMA_BASE + product.source_path,
                data.get("quote_url"),
                bool(product.quote_path),
            ),
        )


def _upsert_quote_questions(conn, product: _Product, questions: list[dict]) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM insuranceiq.quote_questions WHERE insurer_slug=%s AND product_slug=%s",
            (INSURER_SLUG, product.slug),
        )
        for q in questions:
            cur.execute(
                """
                INSERT INTO insuranceiq.quote_questions
                    (insurer_slug, product_slug, step_number, total_steps, question_text,
                     field_type, min_value, max_value, default_value, options, is_required)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
                ON CONFLICT (insurer_slug, product_slug, step_number) DO NOTHING
                """,
                (
                    INSURER_SLUG, product.slug,
                    q["step_number"], q.get("total_steps"), q["question_text"],
                    q.get("field_type"), q.get("min_value"), q.get("max_value"), q.get("default_value"),
                    json.dumps(q["options"]) if q.get("options") else None,
                    True,
                ),
            )
    return len(questions)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_mamabima_scrape(connection, *, scrape_quotes: bool = True) -> dict[str, Any]:
    started_at = datetime.now(UTC)
    _upsert_insurer(connection)
    results: list[dict] = []

    for product in CATALOGUE:
        row: dict[str, Any] = {"slug": product.slug, "questions": 0}
        try:
            data, questions = scrape_product(product, scrape_quotes=scrape_quotes)
            _upsert_product(connection, product, data)
            row["questions"]     = _upsert_quote_questions(connection, product, questions)
            row["who_for"]       = bool(data.get("who_is_it_for"))
            row["exclusions"]    = len(data.get("exclusions") or [])
            row["waiting"]       = len(json.loads(data.get("waiting_period_notes") or "[]"))
            row["faqs"]          = len(data.get("faqs") or [])
        except Exception as exc:
            row["error"] = ascii(str(exc))[:200]
            print(f"  [{product.slug}] ERROR: {row['error']}", flush=True)

        results.append(row)

    duration  = round((datetime.now(UTC) - started_at).total_seconds(), 1)
    succeeded = sum(1 for r in results if "error" not in r)
    return {
        "status": "success" if succeeded == len(results) else "partial_success",
        "records_found": succeeded,
        "duration_seconds": duration,
        "products": results,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    print("=== Mama Bima scraper → insuranceiq ===", flush=True)
    with get_postgres_connection(autocommit=True) as conn:
        summary = run_mamabima_scrape(conn, scrape_quotes=True)
    print(json.dumps(summary, indent=2, default=str))
    sys.exit(0 if summary["status"] in ("success", "partial_success") else 1)
