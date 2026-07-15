"""Mama Bima insurance scraper → insuranceiq schema.

Phase 1: mamabima.com/plans/* — httpx + BeautifulSoup (SSR pages)
  Extracts: description, who_is_it_for, who_can_be_covered, eligibility,
            key_benefits, benefit_options, exclusions, waiting periods, FAQs

Phase 2: client.mamabima.com/* — Playwright (JS SPA, multi-step)
  Extracts: quote flow questions step-by-step

Writes into:
  insuranceiq.insurers
  insuranceiq.products
  insuranceiq.quote_questions
  (insuranceiq.rate_tables — only if the page publishes clean premium data)

Run standalone:
    python -m ganji_mtaani_agent.scrapers.mamabima
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from bs4 import BeautifulSoup, Tag
from playwright.sync_api import sync_playwright

from ganji_mtaani_agent.db.postgres import get_postgres_connection

MAMABIMA_BASE = "https://mamabima.com"
CLIENT_BASE   = "https://client.mamabima.com"
INSURER_SLUG  = "mamabima"
INSURER_NAME  = "Mama Bima"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )
}

# ---------------------------------------------------------------------------
# Product catalogue
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _Product:
    slug:         str
    name:         str
    product_type: str   # life / health / motor / travel
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

# ---------------------------------------------------------------------------
# Section keyword maps for rich content extraction
# ---------------------------------------------------------------------------

_WHO_FOR_KW     = re.compile(r"who (is this|should|it's|can i)\b|ideal for|designed for|suited for|this (plan|policy|cover) is for", re.I)
_WHO_COVERED_KW = re.compile(r"who can be covered|who (is|can be) (covered|insured)|covered (members|persons|individuals)", re.I)
_BENEFIT_KW     = re.compile(r"benefit|what (you|we|is) (get|cover|offer|include)|cover(age)?s?|features", re.I)
_EXCLUSION_KW   = re.compile(r"exclusion|not covered|what (is|we don.t|isn.t)|exception", re.I)
_WAITING_KW     = re.compile(r"waiting period|wait(ing)? time|waiting", re.I)
_FAQ_KW         = re.compile(r"faq|frequently asked|common question|question", re.I)
_SKIP_HEADINGS  = re.compile(r"^(get (a )?quote|apply|contact|sign up|register|login|home|menu|nav)", re.I)


# ---------------------------------------------------------------------------
# Phase 1: product pages — httpx + BeautifulSoup
# ---------------------------------------------------------------------------

def fetch_product_page(product: _Product) -> dict[str, Any]:
    url = MAMABIMA_BASE + product.source_path
    try:
        r = httpx.get(url, headers=_HEADERS, timeout=30, follow_redirects=True)
        r.raise_for_status()
    except Exception as exc:
        return {"error": str(exc)}

    soup = BeautifulSoup(r.text, "html.parser")
    sections = _parse_sections(soup)

    return {
        "description":          _extract_description(soup),
        "tagline":              _extract_tagline(soup),
        "min_age":              _extract_ages(soup).get("min"),
        "max_age":              _extract_ages(soup).get("max"),
        "who_is_it_for":       _join_section(sections, _WHO_FOR_KW),
        "who_can_be_covered":  _join_section(sections, _WHO_COVERED_KW),
        "eligibility_notes":   _extract_eligibility(soup),
        "key_benefits":        _extract_benefits(soup, sections),
        "benefit_options":     _extract_benefit_options(soup),
        "exclusions":          _extract_exclusions(soup, sections),
        "waiting_period_days": _extract_waiting_days(soup),
        "waiting_period_notes":_join_section(sections, _WAITING_KW),
        "faqs":                _extract_faqs(soup, sections),
        "quote_url":           (CLIENT_BASE + product.quote_path) if product.quote_path else None,
    }


def _parse_sections(soup: BeautifulSoup) -> list[dict]:
    """Walk headings and collect the text content that follows each one."""
    sections = []
    for heading in soup.find_all(["h1", "h2", "h3", "h4"]):
        title = heading.get_text(strip=True)
        if not title or _SKIP_HEADINGS.match(title):
            continue
        body_parts = []
        for sibling in heading.find_next_siblings():
            if sibling.name in ("h1", "h2", "h3", "h4"):
                break
            text = sibling.get_text(separator=" ", strip=True)
            if text:
                body_parts.append(text)
        sections.append({"heading": title, "body": " ".join(body_parts)})
    return sections


def _join_section(sections: list[dict], pattern: re.Pattern) -> str | None:
    matched = [s["body"] for s in sections if pattern.search(s["heading"])]
    return " ".join(matched) if matched else None


def _extract_description(soup: BeautifulSoup) -> str:
    chunks = []
    for tag in soup.find_all(["h1", "p"]):
        t = tag.get_text(strip=True)
        if len(t) > 60:
            chunks.append(t)
        if len(chunks) >= 3:
            break
    return " ".join(chunks)


def _extract_tagline(soup: BeautifulSoup) -> str | None:
    for tag in soup.find_all(["h2", "h3", "p"]):
        t = tag.get_text(strip=True)
        if 20 < len(t) < 120:
            return t
    return None


def _extract_ages(soup: BeautifulSoup) -> dict:
    text = soup.get_text(separator=" ")
    m = re.search(r"(?:ages?\s+)?(\d{1,2})\s*(?:to|[-–])\s*(\d{2,3})\s+years?", text, re.I)
    return {"min": int(m.group(1)), "max": int(m.group(2))} if m else {"min": None, "max": None}


def _extract_eligibility(soup: BeautifulSoup) -> str | None:
    text = soup.get_text(separator=" ")
    m = re.search(r"(eligible.{0,300})", text, re.I | re.S)
    return m.group(1).strip()[:500] if m else None


def _extract_benefits(soup: BeautifulSoup, sections: list[dict]) -> list[dict]:
    benefits: list[dict] = []

    # From sections with benefit-related headings
    for s in sections:
        if _BENEFIT_KW.search(s["heading"]) and not _EXCLUSION_KW.search(s["heading"]):
            benefits.append({"title": s["heading"], "description": s["body"][:400]})

    # From <ul>/<ol> lists in the page
    for ul in soup.find_all(["ul", "ol"]):
        prev = ul.find_previous(["h2", "h3", "h4", "p"])
        heading_text = prev.get_text(strip=True) if prev else ""
        if _EXCLUSION_KW.search(heading_text):
            continue
        items = [li.get_text(strip=True) for li in ul.find_all("li") if li.get_text(strip=True)]
        if 2 <= len(items) <= 20:
            benefits.append({"title": heading_text or "Benefits", "items": items})

    return benefits[:15]


def _extract_benefit_options(soup: BeautifulSoup) -> list[dict] | None:
    """Extract plan tiers / cover level tables."""
    options = []
    for tbl in soup.find_all("table"):
        headers = [th.get_text(strip=True) for th in tbl.find_all("th")]
        rows = []
        for tr in tbl.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all("td")]
            if cells:
                rows.append(cells)
        if headers and rows:
            options.append({"headers": headers, "rows": rows})
    return options if options else None


def _extract_exclusions(soup: BeautifulSoup, sections: list[dict]) -> list[dict]:
    exclusions: list[dict] = []

    for s in sections:
        if _EXCLUSION_KW.search(s["heading"]):
            exclusions.append({"title": s["heading"], "description": s["body"][:500]})

    for ul in soup.find_all(["ul", "ol"]):
        prev = ul.find_previous(["h2", "h3", "h4", "p"])
        heading_text = prev.get_text(strip=True) if prev else ""
        if _EXCLUSION_KW.search(heading_text):
            items = [li.get_text(strip=True) for li in ul.find_all("li") if li.get_text(strip=True)]
            if items:
                exclusions.append({"title": heading_text, "items": items})

    return exclusions


def _extract_waiting_days(soup: BeautifulSoup) -> int | None:
    text = soup.get_text(separator=" ")
    m = re.search(r"(\d+)\s*(?:-|\s)?\s*(?:day|month)s?\s+waiting", text, re.I)
    if m:
        val = int(m.group(1))
        # convert months to days if needed
        if "month" in m.group(0).lower():
            val *= 30
        return val
    return None


def _extract_faqs(soup: BeautifulSoup, sections: list[dict]) -> list[dict]:
    faqs: list[dict] = []

    # From sections with FAQ headings
    for s in sections:
        if _FAQ_KW.search(s["heading"]):
            faqs.append({"question": s["heading"], "answer": s["body"][:600]})

    # From accordion / details elements
    for details in soup.find_all(["details", "[class*='accordion']", "[class*='faq']"]):
        summary = details.find("summary")
        if summary:
            q = summary.get_text(strip=True)
            a_parts = [t for t in details.find_all(text=True) if t.strip() and t != summary.get_text()]
            a = " ".join(a_parts).strip()[:600]
            if q and a:
                faqs.append({"question": q, "answer": a})

    # Fallback: look for Q&A patterns in text
    if not faqs:
        text = soup.get_text(separator="\n")
        for m in re.finditer(r"Q[:\.]?\s+(.{10,120})\nA[:\.]?\s+(.{10,400})", text):
            faqs.append({"question": m.group(1).strip(), "answer": m.group(2).strip()})

    return faqs[:20]


# ---------------------------------------------------------------------------
# Phase 2: quote questions — Playwright
# ---------------------------------------------------------------------------

_STEPPER_RE = re.compile(r"^[−\-+]$")
_NAV_RE     = re.compile(r"^(next|back|cancel|prev|submit|continue|proceed)$", re.I)


def scrape_quote_questions(product: _Product, *, max_steps: int = 15) -> list[dict]:
    if not product.quote_path:
        return []

    url = CLIENT_BASE + product.quote_path
    questions: list[dict] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(3_000)

            seen_questions: dict[str, int] = {}
            for step_num in range(1, max_steps + 1):
                step = _extract_step(page, step_num)
                if not step:
                    break
                q_text = step["question_text"]

                if q_text in seen_questions:
                    print(f"    loop detected at step {step_num} (same as step {seen_questions[q_text]}), stopping", flush=True)
                    break
                seen_questions[q_text] = step_num

                questions.append(step)
                print(f"    step {step_num}: {q_text[:70]}", flush=True)

                if not _fill_and_advance(page, step):
                    break
                page.wait_for_timeout(2_500)

        except Exception as exc:
            print(f"    stopped at step {len(questions)+1}: {ascii(str(exc))[:120]}", flush=True)
        finally:
            browser.close()

    return questions


def _extract_step(page, step_num: int) -> dict | None:
    total    = _read_total_steps(page)
    question = _read_question(page)
    if not question:
        return None
    return {"step_number": step_num, "total_steps": total, "question_text": question, **_detect_field(page)}


def _read_total_steps(page) -> int | None:
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


def _read_question(page) -> str:
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


def _is_stepper(page) -> bool:
    try:
        btns = [b.inner_text().strip() for b in page.get_by_role("button").all() if b.is_visible()]
        return sum(1 for b in btns if _STEPPER_RE.match(b)) >= 1
    except Exception:
        return False


def _detect_field(page) -> dict:
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


def _fill_and_advance(page, step: dict) -> bool:
    ft = step.get("field_type", "unknown")
    q  = step.get("question_text", "").lower()
    try:
        if ft == "stepper":
            plus_btn = page.get_by_role("button", name="+").first
            if plus_btn.count() > 0 and plus_btn.is_enabled():
                plus_btn.click()
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
# DB helpers — write into insuranceiq schema
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
                %s,%s,%s,%s,
                %s,%s,
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
                    INSURER_SLUG, product.slug, q["step_number"], q.get("total_steps"), q["question_text"],
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
        print(f"  [{product.slug}] fetching product page...", flush=True)
        row: dict[str, Any] = {"slug": product.slug, "questions": 0}

        try:
            data = fetch_product_page(product)
            if "error" in data:
                raise RuntimeError(data["error"])

            _upsert_product(connection, product, data)

            if scrape_quotes and product.quote_path:
                print(f"  [{product.slug}] scraping quote flow...", flush=True)
                qs = scrape_quote_questions(product)
                row["questions"] = _upsert_quote_questions(connection, product, qs)

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
