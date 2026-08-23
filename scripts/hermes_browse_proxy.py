"""
Hermes Browse Proxy — two-step governed-cloud chat with optional web research.

Step 1: Ask the governed DeepSeek lane if the question needs web browsing.
Step 2: If yes, use Playwright headless Chromium to fetch real data.
Step 3: Pass fetched context + original question to the governed DeepSeek lane.
"""

import json
import urllib.parse
import re
import os
from pathlib import Path

CHROME_PATH = None

# Find Chromium
for candidate in [
    os.environ.get("AGENT_BROWSER_EXECUTABLE_PATH", ""),
    str(Path.home() / ".cache/ms-playwright/chromium-1223/chrome-linux64/chrome"),
    str(Path.home() / ".cache/ms-playwright/chromium-1217/chrome-linux64/chrome"),
]:
    if candidate and Path(candidate).exists():
        CHROME_PATH = candidate
        break


def _governed_chat(messages, num_predict=200, temperature=0.3, format_json=False):
    """Send a bounded request through the governed DeepSeek lane."""
    del num_predict, temperature, format_json
    from llm_lane import generate
    prompt = "\n\n".join(
        f"{str(message.get('role') or 'user').upper()}: {message.get('content') or ''}"
        for message in messages
    )
    return generate(
        prompt,
        lane="deepseek-flash",
        timeout=120,
        process_id="hermes_browse_proxy",
    )


def _classify_question(user_message):
    """Step 1: Determine if the question needs web browsing."""
    prompt = f"""You are a question classifier. Given the user's question, determine:
1. Does this question require current/real-time information from the internet? (news, scores, prices, weather, current events)
2. If yes, what search query would find the answer?

User question: {user_message}

Reply ONLY with JSON: {{"needs_browse": true/false, "search_query": "...", "reason": "..."}}
If the question is about general knowledge you're confident about, set needs_browse to false.
If the question involves current events, live data, recent news, or anything after your training cutoff, set needs_browse to true."""

    try:
        raw = _governed_chat([{"role": "user", "content": prompt}],
                           num_predict=150, temperature=0.1, format_json=True)
        result = json.loads(raw)
        return result
    except Exception:
        # Default to browsing if classification fails
        return {"needs_browse": True, "search_query": user_message, "reason": "classification failed"}


def _browse_search(query, max_results=5):
    """Use Playwright to search DuckDuckGo and extract results + page content."""
    if not CHROME_PATH:
        return None, "Chromium not found"

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None, "Playwright not installed"

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                executable_path=CHROME_PATH,
                args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"]
            )
            page = browser.new_page(
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
            )

            # Search DuckDuckGo HTML (no JS needed)
            search_url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
            page.goto(search_url, timeout=15000)

            # Extract search results
            results = []
            links = page.query_selector_all(".result__body")
            for link in links[:max_results]:
                title_el = link.query_selector(".result__a")
                snippet_el = link.query_selector(".result__snippet")
                url_el = link.query_selector(".result__url")
                title = title_el.inner_text() if title_el else ""
                snippet = snippet_el.inner_text() if snippet_el else ""
                url = url_el.inner_text().strip() if url_el else ""
                if title:
                    results.append({"title": title, "snippet": snippet, "url": url})

            # Fetch up to 2 result pages for deeper context
            page_contents = []
            for r in results[:2]:
                url = r.get("url", "")
                if not url:
                    continue
                try:
                    if not url.startswith("http"):
                        url = "https://" + url
                    page.goto(url, timeout=10000)
                    content = page.evaluate("""
                        () => {
                            const body = document.body;
                            if (!body) return '';
                            ['script','style','nav','footer','header','aside','iframe'].forEach(tag => {
                                body.querySelectorAll(tag).forEach(el => el.remove());
                            });
                            return body.innerText.substring(0, 2000);
                        }
                    """)
                    if content and len(content.strip()) > 100:
                        page_contents.append({"url": url, "content": content.strip()[:2000]})
                except Exception:
                    pass

            browser.close()

            return {
                "search_results": results,
                "page_contents": page_contents,
                "query": query,
            }, None

    except Exception as e:
        return None, f"Browse error: {str(e)[:200]}"


def chat_with_browsing(messages, system_prompt=""):
    """Main entry point: two-step chat with optional browsing."""
    # Get the latest user message
    user_msg = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            user_msg = m["content"]
            break

    if not user_msg:
        return {"content": "No question provided.", "browsed": False}

    # Step 1: Classify
    classification = _classify_question(user_msg)
    needs_browse = classification.get("needs_browse", False)
    search_query = classification.get("search_query", user_msg)

    browse_context = ""
    browsed = False
    browse_error = None

    if needs_browse and CHROME_PATH:
        # Step 2: Browse
        result, error = _browse_search(search_query)
        if result and not error:
            browsed = True
            # Format browse results as context
            parts = [f"WEB SEARCH RESULTS for: {search_query}\n"]
            for i, r in enumerate(result.get("search_results", []), 1):
                parts.append(f"{i}. {r['title']}")
                if r.get("snippet"):
                    parts.append(f"   {r['snippet']}")
                if r.get("url"):
                    parts.append(f"   URL: {r['url']}")
                parts.append("")

            for pc in result.get("page_contents", []):
                parts.append(f"PAGE CONTENT from {pc['url']}:")
                parts.append(pc["content"][:2000])
                parts.append("")

            browse_context = "\n".join(parts)
        else:
            browse_error = error

    # Step 3: Final answer with context
    final_messages = []

    # System prompt
    sys_content = system_prompt or (
        "You are Hermes, Trade AI's research desk and independent challenger. "
        "Use the current system date supplied by the runtime. "
        "You are advisory only — you do not execute trades or mutate production data. "
        "Be direct and evidence-backed."
    )

    if browsed and browse_context:
        sys_content += (
            "\n\nIMPORTANT: You have web search results below. "
            "Use ONLY the provided web data to answer. "
            "Cite your sources. Do not make up information beyond what the search results show."
            f"\n\n{browse_context}"
        )
    elif needs_browse and not browsed:
        sys_content += (
            "\n\nNOTE: This question may require current information but web browsing "
            f"{'failed: ' + (browse_error or 'unknown error') if browse_error else 'is not available'}. "
            "Say 'I don\'t have access to current data for this question' rather than guessing."
        )
    else:
        sys_content += (
            "\n\nIf you are not confident about current/real-time information, "
            "say 'I don\'t have current data for this' rather than guessing."
        )

    final_messages.append({"role": "system", "content": sys_content})

    # Include conversation history
    for m in messages:
        final_messages.append({"role": m["role"], "content": m["content"]})

    # Get final response
    content = _governed_chat(final_messages, num_predict=1500, temperature=0.4)

    # Add source attribution if browsed
    if browsed:
        content += "\n\n_[Source: web search via Hermes browser]_"

    return {
        "content": content,
        "browsed": browsed,
        "search_query": search_query if needs_browse else None,
        "classification": classification,
    }


if __name__ == "__main__":
    # Quick test
    result = chat_with_browsing([{"role": "user", "content": "Who is in the NBA finals 2026?"}])
    print(f"Browsed: {result['browsed']}")
    print(f"Classification: {result.get('classification')}")
    print(f"Answer: {result['content'][:500]}")
