"""Mama Bima insurance scraper.

Writes into the existing BOB insurance schema:
  - products      (insurer_slug='mamabima')
  - rate_tables   (coverage/premium tiers per product)
  - quote_questions (quote-flow steps, Phase 15 new table)

Two scraping phases:
  Phase 1 — mamabima.com/plans/* : httpx + BeautifulSoup  (SSR pages)
  Phase 2 — client.mamabima.com/* : Playwright            (JS SPA, multi-step)

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
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from ganji_mtaani_agent.db.postgres import get_postgres_connection

MAMABIMA_BASE = "https://mamabima.com"
CLIENT_BASE   = "https://client.mamabima.com"
INSURER_SLUG  = "mamabima"

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
    slug:        str
    name:        str
    product_type: str  # life / health / motor / travel
    source_path: str   # relative to MAMABIMA_BASE
    quote_path:  str   # relative to CLIENT_BASE; "" = no quote flow


CATALOGUE: tuple[_Product, ...] = (
    _Product("mb-last-expense",      "Last Expense Cover",      "life",   "/plans/life/last-expense",      "/life/last-expense"),
    _Product("mb-whole-life",        "Whole Life Insurance",    "life",   "/plans/life/whole-life",        "/life/whole-life"),
    _Product("mb-endowment-savings", "Endowment Savings",       "life",   "/plans/life/endowment",         "/life/endowment-savings"),
    _Product("mb-education-savings", "Education Savings Plan",  "life",   "/plans/life/education",         "/life/education-savings"),
    _Product("mb-critical-illness",  "Critical Illness Cover",  "life",   "/plans/life/critical-illness",  "/life/critical-illness"),
    _Product("mb-medical",           "Medical Insurance",       "health", "/plans/medical",                "/medical"),
    _Product("mb-motor",             "Motor Insurance",         "motor",  "/plans/motor",                  "/motor"),
    _Product("mb-travel",            "Travel Insurance",        "travel", "/plans/travel",                 "/travel"),
    _Product("mb-retirement",        "Retirement Planning",     "life",   "/plans/retirement",             "/life/retirement"),
    _Product("mb-estate-planning",   "Estate Planning",         "life",   "/plans/estate-planning",        ""),
)


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
    text = soup.get_text(separator="\n", strip=True)

    return {
        "description": _extract_description(soup),
        "min_age":     _extract_ages(text).get("min"),
        "max_age":     _extract_ages(text).get("max"),
        "key_benefits": _extract_lists(soup)[:20],
        "tables":      _extract_tables(soup),
        "coverage":    _extract_coverage(text),
        "premiums":    _extract_premiums(text),
        "quote_url":   (CLIENT_BASE + product.quote_path) if product.quote_path else None,
    }


def _extract_description(soup: BeautifulSoup) -> str:
    chunks = []
    for tag in soup.find_all(["h1", "h2", "p"]):
        t = tag.get_text(strip=True)
        if len(t) > 40:
            chunks.append(t)
        if len(chunks) >= 4:
            break
    return " ".join(chunks)


def _extract_tables(soup: BeautifulSoup) -> list[dict]:
    tables = []
    for tbl in soup.find_all("table"):
        headers = [th.get_text(strip=True) for th in tbl.find_all("th")]
        rows = []
        for tr in tbl.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all("td")]
            if cells:
                rows.append(cells)
        if rows:
            tables.append({"headers": headers, "rows": rows})
    return tables


def _extract_lists(soup: BeautifulSoup) -> list[str]:
    items: list[str] = []
    for ul in soup.find_all(["ul", "ol"]):
        for li in ul.find_all("li"):
            t = li.get_text(strip=True)
            if len(t) > 10:
                items.append(t)
    return items


def _find_kes(text: str) -> list[float]:
    amounts: list[float] = []
    for m in re.finditer(r"(?:Kshs?\.?|KES)\s*([\d,]+)", text, re.IGNORECASE):
        try:
            amounts.append(float(m.group(1).replace(",", "")))
        except ValueError:
            pass
    return amounts


def _extract_coverage(text: str) -> dict:
    large = [a for a in _find_kes(text) if a >= 100_000]
    return {"min": min(large) if large else None, "max": max(large) if large else None}


def _extract_premiums(text: str) -> dict:
    small = [a for a in _find_kes(text) if a < 100_000]
    return {"min": min(small) if small else None, "max": max(small) if small else None}


def _extract_ages(text: str) -> dict:
    m = re.search(r"(?:ages?\s+)?(\d{1,2})\s*(?:to|[-–])\s*(\d{2,3})\s+years?", text, re.IGNORECASE)
    return {"min": int(m.group(1)), "max": int(m.group(2))} if m else {"min": None, "max": None}


def _parse_kes(text: str) -> float | None:
    clean = re.sub(r"[^\d.]", "", (text or "").replace(",", ""))
    try:
        return float(clean) if clean else None
    except ValueError:
        return None


def _find_col(headers: list[str], keywords: list[str]) -> int | None:
    for i, h in enumerate(headers):
        if any(k in h.lower() for k in keywords):
            return i
    return None


# ---------------------------------------------------------------------------
# Phase 2: quote questions — Playwright
# ---------------------------------------------------------------------------

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

            seen_questions: dict[str, int] = {}  # text -> first step it appeared
            for step_num in range(1, max_steps + 1):
                step = _extract_step(page, step_num)
                if not step:
                    break
                q_text = step["question_text"]

                # Stop if we're looping on the same question
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
            print(f"    stopped at step {len(questions)+1}: {exc}", flush=True)
        finally:
            browser.close()

    return questions


def _extract_step(page, step_num: int) -> dict | None:
    total = _read_total_steps(page)
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


_STEPPER_RE = re.compile(r"^[−\-+]$")
_NAV_RE     = re.compile(r"^(next|back|cancel|prev|submit|continue|proceed)$", re.I)


def _read_question(page) -> str:
    # Prefer elements closer to the form field rather than top-level headings
    for sel in [
        "[class*='question']", "[class*='label']",
        "label", "h3", "h2",
        "[class*='title']", "[class*='heading']",
        "p", "h1",
    ]:
        try:
            for el in page.locator(sel).all()[:5]:
                if el.is_visible():
                    t = el.inner_text().strip()
                    # Skip if it looks like navigation or is very short
                    if len(t) > 6 and not _NAV_RE.match(t):
                        return t
        except Exception:
            pass
    return ""


def _is_stepper(page) -> bool:
    """Detect the +/− stepper widget used by Mama Bima quote flows."""
    try:
        btns = [b.inner_text().strip() for b in page.get_by_role("button").all()
                if b.is_visible()]
        stepper_chars = sum(1 for b in btns if _STEPPER_RE.match(b))
        return stepper_chars >= 1
    except Exception:
        return False


def _detect_field(page) -> dict:
    # Stepper widget (+/− buttons) — check before generic choice_buttons
    if _is_stepper(page):
        try:
            # Try to read current value from a read-only input or span next to the buttons
            val_el = page.locator('[class*="count"], [class*="value"], [class*="number"], input[readonly]').first
            cur_val = "0"
            if val_el.count() > 0 and val_el.is_visible():
                cur_val = val_el.inner_text().strip() or val_el.input_value()
        except Exception:
            cur_val = "0"
        return {"field_type": "stepper", "min_value": "0", "max_value": None,
                "default_value": cur_val, "options": None}

    # number input
    for sel in ['input[type="number"]', 'input[inputmode="numeric"]']:
        try:
            el = page.locator(sel).first
            if el.count() > 0 and el.is_visible():
                return {"field_type": "number", "min_value": el.get_attribute("min") or "",
                        "max_value": el.get_attribute("max") or "", "default_value": el.input_value(), "options": None}
        except Exception:
            pass

    # select
    try:
        el = page.locator("select").first
        if el.count() > 0 and el.is_visible():
            opts = [{"value": o.get_attribute("value") or "", "label": o.inner_text().strip()}
                    for o in page.locator("select option").all() if o.inner_text().strip()]
            return {"field_type": "select", "min_value": None, "max_value": None, "default_value": None, "options": opts}
    except Exception:
        pass

    # radio
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

    # choice buttons / cards (exclude stepper chars)
    try:
        opts = []
        for btn in page.get_by_role("button").all():
            if btn.is_visible():
                t = btn.inner_text().strip()
                if t and len(t) < 60 and not _NAV_RE.search(t) and not _STEPPER_RE.match(t):
                    opts.append({"value": t, "label": t})
        if len(opts) >= 2:
            return {"field_type": "choice_buttons", "min_value": None, "max_value": None, "default_value": None, "options": opts}
    except Exception:
        pass

    # text
    try:
        el = page.locator('input[type="text"], input:not([type])').first
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
            # Click "+" to increment from 0 to 1 (or leave at 0 for members)
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
                # Some flows auto-advance; others still need an explicit Next
                for name in ("Next", "Continue", "Proceed"):
                    btn = page.get_by_role("button", name=name)
                    if btn.count() > 0 and btn.first.is_visible():
                        btn.first.click()
                        break
                return True
        elif ft == "text":
            page.locator('input[type="text"], input:not([type])').first.fill("Test")

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
        print(f"      fill error: {exc}", flush=True)
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
# DB helpers — write into existing BOB insurance schema
# ---------------------------------------------------------------------------

def _upsert_product(conn, product: _Product, data: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO products (
                product_slug, product_name, product_type, insurer_slug,
                description, min_age, max_age,
                key_benefits, product_url, quotable, active,
                created_at, updated_at
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,true,NOW(),NOW())
            ON CONFLICT (product_slug) DO UPDATE SET
                product_name  = EXCLUDED.product_name,
                product_type  = EXCLUDED.product_type,
                description   = EXCLUDED.description,
                min_age       = EXCLUDED.min_age,
                max_age       = EXCLUDED.max_age,
                key_benefits  = EXCLUDED.key_benefits,
                product_url   = EXCLUDED.product_url,
                quotable      = EXCLUDED.quotable,
                updated_at    = NOW()
            """,
            (
                product.slug, product.name, product.product_type, INSURER_SLUG,
                data.get("description"), data.get("min_age"), data.get("max_age"),
                json.dumps(data.get("key_benefits", []), default=str),
                MAMABIMA_BASE + product.source_path,
                bool(product.quote_path),
            ),
        )


def _upsert_rate_tiers(conn, product: _Product, tables: list[dict]) -> int:
    # Mama Bima product pages don't publish clean rate tables — skip to avoid polluting rate_tables
    return 0


def _upsert_quote_questions(conn, product: _Product, questions: list[dict]) -> int:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM quote_questions WHERE product_slug = %s", (product.slug,))
        for q in questions:
            cur.execute(
                """
                INSERT INTO quote_questions
                    (product_slug, step_number, total_steps, question_text,
                     field_type, min_value, max_value, default_value, options)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                ON CONFLICT (product_slug, step_number) DO NOTHING
                """,
                (
                    product.slug, q["step_number"], q.get("total_steps"), q["question_text"],
                    q.get("field_type"), q.get("min_value"), q.get("max_value"), q.get("default_value"),
                    json.dumps(q["options"]) if q.get("options") else None,
                ),
            )
    return len(questions)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_mamabima_scrape(connection, *, scrape_quotes: bool = True) -> dict[str, Any]:
    """Scrape all Mama Bima products and quote questions into the BOB DB."""
    started_at = datetime.now(UTC)
    results: list[dict] = []

    for product in CATALOGUE:
        print(f"  [{product.slug}] fetching product page...", flush=True)
        row: dict[str, Any] = {"slug": product.slug, "tiers": 0, "questions": 0}

        try:
            data = fetch_product_page(product)
            if "error" in data:
                raise RuntimeError(data["error"])

            _upsert_product(connection, product, data)
            row["tiers"] = _upsert_rate_tiers(connection, product, data.get("tables", []))

            if scrape_quotes and product.quote_path:
                print(f"  [{product.slug}] scraping quote flow...", flush=True)
                qs = scrape_quote_questions(product)
                row["questions"] = _upsert_quote_questions(connection, product, qs)

        except Exception as exc:
            row["error"] = str(exc)
            print(f"  [{product.slug}] ERROR: {ascii(str(exc))}", flush=True)

        results.append(row)

    duration = round((datetime.now(UTC) - started_at).total_seconds(), 1)
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
    print("=== Mama Bima scraper ===", flush=True)
    # Apply quote_questions table if it doesn't exist yet
    from pathlib import Path
    schema_sql = Path(__file__).resolve().parents[2] / "db" / "schema_phase15.sql"
    with get_postgres_connection(autocommit=True) as conn:
        if schema_sql.exists():
            no_comments = re.sub(r"--[^\n]*", "", schema_sql.read_text())
            with conn.cursor() as cur:
                for stmt in (s.strip() for s in no_comments.split(";") if s.strip()):
                    try:
                        cur.execute(stmt)
                    except Exception:
                        pass
        summary = run_mamabima_scrape(conn, scrape_quotes=True)
    print(json.dumps(summary, indent=2, default=str))
    sys.exit(0 if summary["status"] in ("success", "partial_success") else 1)
