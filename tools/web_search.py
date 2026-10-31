import email.utils
import html
import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
import requests


def parse_rss_date(date_str: str) -> tuple[datetime | None, str]:
    """
    Safely parse an RSS publication date string.
    Returns (datetime_obj_or_None, display_string).
    Never invents or guesses a date.
    """
    if not date_str or not isinstance(date_str, str):
        return None, "Date not provided"

    clean_str = date_str.strip()
    if not clean_str:
        return None, "Date not provided"

    try:
        dt = email.utils.parsedate_to_datetime(clean_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt, clean_str
    except (TypeError, ValueError, AttributeError, IndexError):
        return None, "Date not provided"


def clean_url(url_str: str | None) -> str:
    """Validate and clean URL string. Returns 'Not available' if invalid or missing."""
    if not url_str or not isinstance(url_str, str):
        return "Not available"
    url_str = url_str.strip()
    if url_str.startswith("http://") or url_str.startswith("https://"):
        return url_str
    return "Not available"


def is_relevant(query: str, title: str, snippet: str = "") -> bool:
    """
    Check if a search result's title or snippet meaningfully matches the user query.
    Prevents unrelated articles (e.g. '15.ai' for 'latest AI news') from polluting results.
    """
    stopwords = {
        "the", "a", "an", "and", "or", "of", "for", "in", "on", "with",
        "at", "by", "to", "from", "is", "are", "was", "were", "who", "what",
        "where", "when", "why", "how", "about", "search", "web", "internet",
        "tell", "me", "find", "give", "show", "some", "any", "look", "up",
        "please",
        # Conversational greetings / fillers that should never act as query topics
        "hey", "hi", "hello", "ok", "okay",
        # News-intent words: describe recency intent, not the topic itself.
        # Without this, "latest ai news" would require "latest" and "news"
        # to appear in article titles, incorrectly rejecting real news.
        "latest", "recent", "new", "news", "breaking", "today", "current",
        "this", "week",
    }

    token_pattern = r"\b[a-zA-Z0-9]+(?:\.[a-zA-Z0-9]+)*\b"
    raw_q_words = re.findall(token_pattern, query.lower())
    q_tokens = [w for w in raw_q_words if w not in stopwords and len(w) > 1]
    if not q_tokens:
        q_tokens = [w for w in raw_q_words if len(w) > 1]

    if not q_tokens:
        return True

    clean_title = title.lower()
    clean_snippet = snippet.lower()
    combined_text = f"{clean_title} {clean_snippet}"

    # Tokenize title and combined text into words for accurate word-level matching.
    # Preserving dots inside terms (e.g. "15.ai") prevents false positives like "ai" matching inside "15.ai".
    title_words = re.findall(token_pattern, clean_title)
    target_words = set(re.findall(token_pattern, combined_text))

    # Reject conversational clickbait headlines that start with "Hey <topic>"
    # unless the user explicitly searched for "hey"
    if re.match(r"^hey\b", clean_title) and "hey" not in raw_q_words:
        return False

    # Exact phrase in title (as contiguous tokens)
    if any(title_words[i : i + len(q_tokens)] == q_tokens for i in range(len(title_words) - len(q_tokens) + 1)):
        return True

    # For queries focusing on "ai" as the core subject, verify substantive AI context
    if q_tokens == ["ai"]:
        if "ai" not in title_words and not any(w.startswith("ai-") or w.endswith("-ai") for w in clean_title.split()):
            return False
        ai_context_words = {
            "model", "models", "intelligence", "tech", "technology", "technologies",
            "system", "systems", "chip", "chips", "research", "algorithm", "algorithms",
            "learning", "machine", "gpt", "llm", "llms", "agent", "agents", "data",
            "compute", "software", "robot", "robotics", "science", "neural", "network",
            "networks", "tool", "tools", "platform", "platforms", "hack", "exploit",
            "development", "developments", "update", "updates", "release", "releases",
            "announces", "announce", "unveils", "unveil", "launch", "launches",
            "security", "synthetic", "clone", "generate", "generative", "code", "coding",
            "automation", "automated", "assistant", "assistants", "quest", "brain",
            "breakthrough", "flaw", "flaws", "startup", "labs", "lab", "reasoning",
            "inference", "accelerator", "semiconductor", "server", "servers", "firmware",
        }
        has_context = (
            any(w in target_words for w in ai_context_words)
            or "artificial intelligence" in combined_text
            or any("-" in w and "ai" in w for w in clean_title.split())
        )
        return has_context

    matches = sum(1 for t in q_tokens if t in target_words)

    # For short queries (1 or 2 core words, e.g. "Stella Cox" or "Python tutorial"),
    # require all core tokens to be present.
    if len(q_tokens) <= 2:
        return matches == len(q_tokens)

    # For longer queries, require at least 60% of core tokens
    return matches >= max(2, int(len(q_tokens) * 0.6 + 0.5))


def search_news(query: str, max_results: int = 5) -> list[str]:
    """
    Retrieve recent, dated news articles from Google News RSS.
    Does not require any API key.
    Safely handles malformed entries, missing dates, and sorts newest first,
    prioritizing actual development news.
    """
    items_collected = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    encoded_query = urllib.parse.quote(query)
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"

    try:
        resp = requests.get(rss_url, headers=headers, timeout=10)
        if resp.status_code == 200:
            root = ET.fromstring(resp.content)
            items = root.findall(".//item")
            for item in items:
                title_elem = item.find("title")
                pub_date_elem = item.find("pubDate")
                source_elem = item.find("source")
                link_elem = item.find("link")

                # Skip entries with missing or empty titles
                if title_elem is None or not title_elem.text or not title_elem.text.strip():
                    continue

                title = title_elem.text.strip()
                source = source_elem.text.strip() if source_elem is not None and source_elem.text else ""

                # Parse publisher from title if needed (e.g. "Headline - Publisher")
                if " - " in title and not source:
                    parts = title.rsplit(" - ", 1)
                    title = parts[0].strip()
                    source = parts[1].strip()

                publisher = source if source else "News Source"

                # Parse publication date safely
                pub_date_raw = pub_date_elem.text.strip() if pub_date_elem is not None and pub_date_elem.text else ""
                dt, pub_date_str = parse_rss_date(pub_date_raw)

                # Distinguish older background articles from recent news
                if dt is not None:
                    try:
                        now = datetime.now(timezone.utc)
                        age_days = (now - dt).days
                        if age_days > 60:
                            pub_date_display = f"{pub_date_str} (Older background)"
                        else:
                            pub_date_display = pub_date_str
                    except Exception:
                        pub_date_display = pub_date_str
                else:
                    pub_date_display = pub_date_str

                # Parse and validate URL.
                # Google News RSS can put the URL in <link> text, <link> tail,
                # <source url="...">, or <guid>. Try each in priority order.
                link_raw = ""
                if link_elem is not None:
                    link_raw = (link_elem.text or "").strip()
                    if not link_raw:
                        link_raw = (link_elem.tail or "").strip()
                if not link_raw and source_elem is not None:
                    link_raw = (source_elem.get("url") or "").strip()
                if not link_raw:
                    guid_elem = item.find("guid")
                    if guid_elem is not None:
                        link_raw = (guid_elem.text or "").strip()
                url = clean_url(link_raw)

                # Relevance check
                if is_relevant(query, title, publisher):
                    items_collected.append({
                        "dt": dt,
                        "title": title,
                        "publisher": publisher,
                        "pub_date": pub_date_display,
                        "url": url,
                    })
    except Exception:
        pass

    if not items_collected:
        return []

    # Sort newer articles first for current news queries,
    # prioritizing articles about actual developments within the recent window.
    def _news_sort_key(item):
        dt = item["dt"]
        ts = dt.timestamp() if dt is not None else 0
        if dt is None:
            return (0, 0, 0)
        try:
            now = datetime.now(timezone.utc)
            age_days = (now - dt).days
        except Exception:
            age_days = 999
        is_recent = 1 if age_days <= 60 else 0
        dev_boost = 0
        if is_recent:
            title_lower = item["title"].lower()
            dev_words = (
                "model", "models", "intelligence", "research", "developments",
                "development", "breakthrough", "chip", "chips", "system",
                "launch", "launches", "unveils", "unveil", "release", "releases",
                "announces", "announce", "update", "updates", "quest", "brain",
                "learning", "security", "flaw", "flaws", "robot", "robotics",
                "generative", "reasoning", "inference", "accelerator"
            )
            if any(w in title_lower for w in dev_words):
                dev_boost = 1
        return (is_recent, dev_boost, ts)

    items_collected.sort(key=_news_sort_key, reverse=True)

    formatted_results = []
    for it in items_collected[:max_results]:
        formatted_results.append(
            f"- Headline: {it['title']}\n"
            f"  Publisher: {it['publisher']}\n"
            f"  Published: {it['pub_date']}\n"
            f"  URL: {it['url']}"
        )

    return formatted_results


def search_web(query: str) -> str:
    """
    Search the web using free providers:
    - Google News RSS for news / recent queries.
    - Wikipedia & Wikidata for biographical and conceptual entities.
    - DuckDuckGo Instant Answer API for quick definitions and technical docs.
    Preserves URLs, publishers, and publication dates without requiring a paid API key.
    """
    query = query.strip()
    if not query:
        return "Please specify what you want to search for."

    headers = {
        "User-Agent": "MadhavAI/1.0 (Personal AI Assistant; contact@madhav.ai)",
        "Accept": "application/json",
    }

    lowered = query.lower()

    # Distinguish technical research / tutorial queries from breaking news
    technical_terms = {
        "tutorial", "tutorials", "documentation", "docs", "guide",
        "how to", "learn", "course", "example", "examples", "reference"
    }
    is_technical_query = any(re.search(r"\b" + re.escape(w) + r"\b", lowered) for w in technical_terms)

    news_terms = {"latest", "recent", "today", "this week", "news", "current", "breaking"}
    is_news_query = any(re.search(r"\b" + re.escape(w) + r"\b", lowered) for w in news_terms)

    # ------------------------------------------------------------------
    # 1. If query is for news/recency (and not a pure technical tutorial/docs query),
    # prioritize dated news sources
    # ------------------------------------------------------------------
    if is_news_query and not is_technical_query:
        news_items = search_news(query, max_results=5)
        if not news_items:
            stripped_q = re.sub(r"\b(the|latest|recent|today|breaking|news|current)\b", "", query, flags=re.I).strip()
            if stripped_q:
                news_items = search_news(stripped_q, max_results=5)
        if news_items:
            header = f"Recent news results for '{query}':\n"
            return header + "\n\n".join(news_items)
        return f"I searched the web, but could not find sufficiently relevant or recent information for '{query}'."

    # ------------------------------------------------------------------
    # 2. General entity / biographical / technical definition / tutorial lookup
    # ------------------------------------------------------------------
    clean_query = query
    for prefix in (
        "who is ", "who was ", "who are ", "what is ", "what are ",
        "tell me about ", "search for ", "information about ", "info on ",
        "search the web for ", "search web for ", "search internet for "
    ):
        if clean_query.lower().startswith(prefix):
            clean_query = clean_query[len(prefix):].strip(" ?.!/")
            break

    results = []

    # Check Wikidata for accurate entity descriptions and URLs
    try:
        wd_url = "https://www.wikidata.org/w/api.php"
        wd_params = {
            "action": "wbsearchentities",
            "search": clean_query,
            "language": "en",
            "format": "json",
            "limit": 5,
        }
        resp = requests.get(wd_url, params=wd_params, headers=headers, timeout=5)
        if resp.status_code == 200:
            entities = resp.json().get("search", [])
            for ent in entities:
                label = ent.get("label", "")
                desc = ent.get("description", "")
                ent_id = ent.get("id", "")
                if label and desc and is_relevant(clean_query, label, desc):
                    article_url = f"https://www.wikidata.org/wiki/{ent_id}" if ent_id else "Not available"
                    results.append(
                        f"- Entity: {label}\n"
                        f"  Description: {desc}\n"
                        f"  URL: {article_url}"
                    )
                    if len(results) >= 2:
                        break
    except Exception:
        pass

    # Check Wikipedia Summary & Search API
    try:
        title_slug = urllib.parse.quote(clean_query.replace(" ", "_"))
        wp_summary_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{title_slug}"
        resp = requests.get(wp_summary_url, headers=headers, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("type") != "disambiguation" and data.get("extract"):
                wp_title = data.get("title", "")
                extract = data["extract"]
                if is_relevant(clean_query, wp_title, extract):
                    wp_page_url = f"https://en.wikipedia.org/wiki/{urllib.parse.quote(wp_title.replace(' ', '_'))}"
                    results.append(
                        f"- Topic: {wp_title}\n"
                        f"  Source: Wikipedia\n"
                        f"  Summary: {extract}\n"
                        f"  URL: {wp_page_url}"
                    )
        else:
            # Search Wikipedia, filtering each hit for relevance
            wp_search_url = "https://en.wikipedia.org/w/api.php"
            wp_params = {
                "action": "query",
                "list": "search",
                "srsearch": clean_query,
                "format": "json",
                "utf8": 1,
            }
            s_resp = requests.get(wp_search_url, params=wp_params, headers=headers, timeout=5)
            if s_resp.status_code == 200:
                search_hits = s_resp.json().get("query", {}).get("search", [])
                for hit in search_hits[:4]:
                    hit_title = hit.get("title", "")
                    raw_snippet = hit.get("snippet", "")
                    clean_snippet = re.sub(r"<[^>]+>", "", raw_snippet)
                    clean_snippet = html.unescape(clean_snippet).strip()

                    # Only accept hit if it is strictly relevant to clean_query
                    if is_relevant(clean_query, hit_title, clean_snippet):
                        top_slug = urllib.parse.quote(hit_title.replace(" ", "_"))
                        top_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{top_slug}"
                        top_resp = requests.get(top_url, headers=headers, timeout=5)
                        if top_resp.status_code == 200:
                            top_data = top_resp.json()
                            ext = top_data.get("extract")
                            if ext:
                                wp_page_url = f"https://en.wikipedia.org/wiki/{top_slug}"
                                results.append(
                                    f"- Topic: {hit_title}\n"
                                    f"  Source: Wikipedia\n"
                                    f"  Summary: {ext}\n"
                                    f"  URL: {wp_page_url}"
                                )
                                break
                        elif clean_snippet:
                            wp_page_url = f"https://en.wikipedia.org/wiki/{top_slug}"
                            results.append(
                                f"- Topic: {hit_title}\n"
                                f"  Source: Wikipedia\n"
                                f"  Summary: {clean_snippet}\n"
                                f"  URL: {wp_page_url}"
                            )
                            break
    except Exception:
        pass

    # Check DuckDuckGo Instant Answer API for quick reference and documentation
    try:
        ddg_url = "https://api.duckduckgo.com/"
        ddg_params = {"q": clean_query, "format": "json", "no_html": 1}
        resp = requests.get(ddg_url, params=ddg_params, headers=headers, timeout=5)
        if resp.status_code == 200:
            ddg_data = resp.json()
            abstract = ddg_data.get("AbstractText")
            heading = ddg_data.get("Heading", clean_query)
            abstract_url = clean_url(ddg_data.get("AbstractURL"))
            if abstract and is_relevant(clean_query, heading, abstract):
                results.append(
                    f"- Topic: {heading}\n"
                    f"  Source: DuckDuckGo Reference\n"
                    f"  Summary: {abstract}\n"
                    f"  URL: {abstract_url}"
                )
    except Exception:
        pass

    # Fallback to news search if general search produced no results
    if not results and not is_news_query:
        fallback_news = search_news(query, max_results=3)
        if fallback_news:
            return f"Recent mentions for '{query}':\n\n" + "\n\n".join(fallback_news)

    if not results:
        return f"I searched the web, but could not find sufficiently relevant or recent information for '{query}'."

    return "\n\n".join(results[:4])
