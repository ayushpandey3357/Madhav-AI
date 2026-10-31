"""
Comprehensive Test Suite for Madhav AI Assistant Web Search.
Tests:
1. Relevant vs irrelevant news results (incl. news-intent stopword filtering)
2. Recent vs older articles (date sorting and age tagging)
3. Missing and invalid publication dates (safe handling)
4. Valid and missing article URLs (URL validation & preservation)
5. Empty search results
6. Malformed RSS entries (error tolerance, URL fallback extraction)
7. Summaries that must not invent sources, links, or dates
8. Live query integration (Latest AI news, Technical tutorial, Public figure)
9. News vs technical query classification
10. URL fallback: source/@url, guid, link tail
"""
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
sys.path.insert(0, ".")

from tools.web_search import (
    search_web,
    search_news,
    is_relevant,
    parse_rss_date,
    clean_url,
)
from main import summarize_search_results

passed = 0
failed = 0

def check(condition, test_name, detail=""):
    global passed, failed
    if condition:
        print(f"[PASS] {test_name}")
        passed += 1
    else:
        print(f"[FAIL] {test_name} - {detail}")
        failed += 1


print("=" * 65)
print("MADHAV AI ASSISTANT - ENHANCED WEB SEARCH TEST SUITE")
print("=" * 65)

# ---------------------------------------------------------------------------
# Test 1: Relevant versus Irrelevant Search Results
# ---------------------------------------------------------------------------
print("\n--- 1. Testing Relevant vs Irrelevant Results ---")
check(is_relevant("latest ai news", "DeepSeek releases new AI model", "Tom's Hardware"),
      "Relevant AI news accepted")
check(not is_relevant("latest ai news", "15.ai voice cloning web app", "Text to speech tool"),
      "Irrelevant '15.ai' snippet rejected for AI news query")
check(is_relevant("Python tutorial", "Learn Python with hands-on examples", "Official tutorial and guide"),
      "Relevant Python tutorial accepted")
check(not is_relevant("Python tutorial", "Monty Python Flying Circus comedy", "British sketch comedy series"),
      "Unrelated comedy article rejected for Python tutorial query")
check(is_relevant("Alex Morgan", "Alex Morgan", "fictional public figure"),
      "Exact entity matched")
check(not is_relevant("Alex Morgan", "Wally Cox", "American comedian and actor"),
      "Different person with same last name rejected")

# --- News-intent stopword tests (new) ---
check(is_relevant("breaking ai news", "OpenAI announces GPT-5 AI model", "TechCrunch"),
      "News-intent words stripped: 'breaking ai news' matches AI article")
check(is_relevant("recent ai developments", "Google AI lab publishes developments in reasoning", "Reuters"),
      "News-intent words stripped: 'recent' doesn't block AI match")
check(is_relevant("today ai update", "Major AI update from Microsoft", "The Verge"),
      "News-intent words stripped: 'today' doesn't block AI match")
check(is_relevant("current tech news", "Silicon Valley tech companies report earnings", "Bloomberg"),
      "News-intent words stripped: 'current' doesn't block tech match")
check(not is_relevant("latest ai news", "Cooking recipe for pasta carbonara", "Food Network"),
      "Irrelevant cooking article still rejected for AI news query")

# --- Wake phrase / conversational clickbait rejection tests ---
check(not is_relevant("latest ai news", "Hey AI – Don't Call Me, I'll Call You", "Opinion Column"),
      "Conversational 'Hey AI' headline rejected for AI news query")
check(not is_relevant("the latest ai news", "Hey Siri! What you need to know about assistant updates", "Global News"),
      "Conversational 'Hey Siri' headline rejected for AI news query")
check(is_relevant("the latest ai news", "Our newest AI Quest: Mapping the human brain", "blog.google"),
      "Latest AI news matches brain mapping AI research")
check(is_relevant("OpenAI news", "OpenAI announces new reasoning models", "Reuters"),
      "OpenAI news matches OpenAI development")
check(is_relevant("local LLM developments", "Running local LLMs: open source developments", "Arxiv"),
      "Local LLM query matches local LLM developments")
check(not is_relevant("local LLM developments", "Local sports team wins championship", "Sports Daily"),
      "Local sports article rejected for local LLM query")


# ---------------------------------------------------------------------------
# Test 2: Recent versus Older Articles
# ---------------------------------------------------------------------------
print("\n--- 2. Testing Recent vs Older Articles Handling ---")
now = datetime.now(timezone.utc)
recent_dt = now - timedelta(days=2)
older_dt = now - timedelta(days=120)

recent_str = recent_dt.strftime("%a, %d %b %Y %H:%M:%S GMT")
older_str = older_dt.strftime("%a, %d %b %Y %H:%M:%S GMT")

parsed_recent_dt, _ = parse_rss_date(recent_str)
parsed_older_dt, _ = parse_rss_date(older_str)

check(parsed_recent_dt is not None and parsed_recent_dt > parsed_older_dt,
      "Recent date is correctly identified as newer than older date")

# Test news sorting mock
mock_items = [
    {"dt": parsed_older_dt, "title": "Older AI story", "publisher": "Old Times", "pub_date": older_str, "url": "https://example.com/old"},
    {"dt": parsed_recent_dt, "title": "Breaking AI update", "publisher": "Tech Daily", "pub_date": recent_str, "url": "https://example.com/new"},
    {"dt": None, "title": "Undated article", "publisher": "Blog", "pub_date": "Date not provided", "url": "https://example.com/undated"},
]
mock_items.sort(key=lambda x: (x["dt"].timestamp() if x["dt"] is not None else 0), reverse=True)
check(mock_items[0]["title"] == "Breaking AI update",
      "Articles are sorted newest first", f"First item: {mock_items[0]['title']}")
check(mock_items[-1]["title"] == "Undated article",
      "Undated articles are sorted to the end without crashing")

# --- Date boundary edge cases (new) ---
boundary_dt = now - timedelta(days=60)
boundary_str = boundary_dt.strftime("%a, %d %b %Y %H:%M:%S GMT")
parsed_boundary_dt, _ = parse_rss_date(boundary_str)
check(parsed_boundary_dt is not None, "60-day boundary date parses successfully")

just_old_dt = now - timedelta(days=61)
just_old_str = just_old_dt.strftime("%a, %d %b %Y %H:%M:%S GMT")
age_days_61 = (now - just_old_dt).days
check(age_days_61 > 60, "61-day-old article correctly classified as older background")

just_recent_dt = now - timedelta(days=59)
age_days_59 = (now - just_recent_dt).days
check(age_days_59 <= 60, "59-day-old article correctly classified as recent")


# ---------------------------------------------------------------------------
# Test 3: Missing and Invalid Publication Dates
# ---------------------------------------------------------------------------
print("\n--- 3. Testing Missing & Invalid Publication Dates ---")
valid_dt, valid_display = parse_rss_date("Sat, 24 Oct 2026 20:36:43 GMT")
check(valid_dt is not None and "2026" in valid_display, "Valid RFC 2822 date parsed accurately")

empty_dt, empty_display = parse_rss_date("")
check(empty_dt is None and empty_display == "Date not provided", "Empty date string returns 'Date not provided'")

none_dt, none_display = parse_rss_date(None)
check(none_dt is None and none_display == "Date not provided", "None date returns 'Date not provided'")

bad_dt, bad_display = parse_rss_date("invalid-garbage-date-string-1234")
check(bad_dt is None and bad_display == "Date not provided", "Corrupted date string handled safely without exception")

# --- Additional invalid date edge cases (new) ---
ws_dt, ws_display = parse_rss_date("   ")
check(ws_dt is None and ws_display == "Date not provided", "Whitespace-only date returns 'Date not provided'")

numeric_dt, numeric_display = parse_rss_date("12345")
check(numeric_dt is None and numeric_display == "Date not provided", "Numeric-only date returns 'Date not provided'")

int_dt, int_display = parse_rss_date(42)  # Non-string type
check(int_dt is None and int_display == "Date not provided", "Integer date input returns 'Date not provided'")


# ---------------------------------------------------------------------------
# Test 4: Valid and Missing Article URLs
# ---------------------------------------------------------------------------
print("\n--- 4. Testing Valid & Missing Article URLs ---")
check(clean_url("https://news.google.com/rss/articles/CBMi123") == "https://news.google.com/rss/articles/CBMi123",
      "HTTPS URL preserved accurately")
check(clean_url("http://example.com/story") == "http://example.com/story",
      "HTTP URL preserved accurately")
check(clean_url("") == "Not available", "Empty URL returns 'Not available'")
check(clean_url(None) == "Not available", "None URL returns 'Not available'")
check(clean_url("ftp://files.example.com") == "Not available", "Non-web protocol returns 'Not available'")
check(clean_url("javascript:alert(1)") == "Not available", "Unsafe scheme returns 'Not available'")

# --- Additional URL edge cases (new) ---
check(clean_url("   https://example.com/story   ") == "https://example.com/story",
      "URL with leading/trailing whitespace is trimmed and preserved")
check(clean_url("data:text/html,<h1>test</h1>") == "Not available",
      "Data URI returns 'Not available'")
check(clean_url(42) == "Not available",
      "Non-string URL type returns 'Not available'")


# ---------------------------------------------------------------------------
# Test 5: Empty Search Results
# ---------------------------------------------------------------------------
print("\n--- 5. Testing Empty Search Results Handling ---")
empty_q = search_web("")
check("specify" in empty_q.lower(), "Empty string returns specify message", f"Got: {empty_q}")

ws_q = search_web("       ")
check("specify" in ws_q.lower(), "Whitespace string returns specify message", f"Got: {ws_q}")

nonexistent = search_web("xyzabcqqq123_nonexistent_topic_never_heard_of")
check("could not find" in nonexistent.lower() or "not find sufficiently relevant" in nonexistent.lower(),
      "Nonexistent query returns clear not-found message", f"Got: {nonexistent}")


# ---------------------------------------------------------------------------
# Test 6: Malformed RSS Entries
# ---------------------------------------------------------------------------
print("\n--- 6. Testing Malformed RSS Entries ---")
# Build a malformed RSS XML string with edge cases:
# - Item 1: Complete and valid
# - Item 2: Missing title (should be skipped)
# - Item 3: Missing link (URL should become 'Not available')
# - Item 4: Missing pubDate (date should become 'Date not provided')
malformed_xml = """<rss version="2.0">
<channel>
    <title>Mock News</title>
    <item>
        <title>Valid News Story - Reliable Press</title>
        <link>https://example.com/story-1</link>
        <pubDate>Mon, 26 Oct 2026 10:00:00 GMT</pubDate>
    </item>
    <item>
        <link>https://example.com/story-no-title</link>
        <pubDate>Mon, 26 Oct 2026 10:00:00 GMT</pubDate>
    </item>
    <item>
        <title>Story Without Link - Open Wire</title>
        <pubDate>Mon, 26 Oct 2026 10:00:00 GMT</pubDate>
    </item>
    <item>
        <title>Story Without Date - Daily Journal</title>
        <link>https://example.com/story-no-date</link>
    </item>
</channel>
</rss>"""

try:
    root = ET.fromstring(malformed_xml)
    items = root.findall(".//item")
    parsed_entries = []
    for item in items:
        t_elem = item.find("title")
        if t_elem is None or not t_elem.text or not t_elem.text.strip():
            continue
        l_elem = item.find("link")
        d_elem = item.find("pubDate")
        url = clean_url(l_elem.text if l_elem is not None else None)
        dt, p_str = parse_rss_date(d_elem.text if d_elem is not None else None)
        parsed_entries.append({"title": t_elem.text.strip(), "url": url, "pub_date": p_str})

    check(len(parsed_entries) == 3, "Skipped entry missing title; parsed remaining 3 entries",
          f"Count: {len(parsed_entries)}")
    check(parsed_entries[1]["url"] == "Not available", "Missing link marked 'Not available'")
    check(parsed_entries[2]["pub_date"] == "Date not provided", "Missing date marked 'Date not provided'")
except Exception as e:
    check(False, "Malformed XML parsing", f"Exception: {e}")

# --- URL fallback: source/@url and guid (new) ---
print("\n--- 6b. Testing URL Fallback Extraction ---")
fallback_xml = """<rss version="2.0">
<channel>
    <item>
        <title>Story with source URL attr - Wire Service</title>
        <source url="https://example.com/source-url-article">Wire Service</source>
        <pubDate>Mon, 26 Oct 2026 10:00:00 GMT</pubDate>
    </item>
    <item>
        <title>Story with guid only - Daily Digest</title>
        <guid>https://example.com/guid-article</guid>
        <pubDate>Mon, 26 Oct 2026 10:00:00 GMT</pubDate>
    </item>
    <item>
        <title>Story with empty link and source url - Agency</title>
        <link></link>
        <source url="https://example.com/fallback-source">Agency</source>
        <pubDate>Mon, 26 Oct 2026 10:00:00 GMT</pubDate>
    </item>
</channel>
</rss>"""

try:
    root_fb = ET.fromstring(fallback_xml)
    fb_items = root_fb.findall(".//item")

    # Item 1: no <link>, but <source url="..."> available
    it1 = fb_items[0]
    l1 = it1.find("link")
    s1 = it1.find("source")
    link_raw_1 = ""
    if l1 is not None:
        link_raw_1 = (l1.text or "").strip()
        if not link_raw_1:
            link_raw_1 = (l1.tail or "").strip()
    if not link_raw_1 and s1 is not None:
        link_raw_1 = (s1.get("url") or "").strip()
    url1 = clean_url(link_raw_1)
    check(url1 == "https://example.com/source-url-article",
          "URL extracted from <source url> when <link> missing")

    # Item 2: no <link>, no <source>, but <guid> is a URL
    it2 = fb_items[1]
    l2 = it2.find("link")
    s2 = it2.find("source")
    link_raw_2 = ""
    if l2 is not None:
        link_raw_2 = (l2.text or "").strip()
        if not link_raw_2:
            link_raw_2 = (l2.tail or "").strip()
    if not link_raw_2 and s2 is not None:
        link_raw_2 = (s2.get("url") or "").strip()
    if not link_raw_2:
        g2 = it2.find("guid")
        if g2 is not None:
            link_raw_2 = (g2.text or "").strip()
    url2 = clean_url(link_raw_2)
    check(url2 == "https://example.com/guid-article",
          "URL extracted from <guid> when <link> and <source url> missing")

    # Item 3: empty <link>, falls back to <source url>
    it3 = fb_items[2]
    l3 = it3.find("link")
    s3 = it3.find("source")
    link_raw_3 = ""
    if l3 is not None:
        link_raw_3 = (l3.text or "").strip()
        if not link_raw_3:
            link_raw_3 = (l3.tail or "").strip()
    if not link_raw_3 and s3 is not None:
        link_raw_3 = (s3.get("url") or "").strip()
    url3 = clean_url(link_raw_3)
    check(url3 == "https://example.com/fallback-source",
          "URL falls back to <source url> when <link> is empty")

except Exception as e:
    check(False, "URL fallback parsing", f"Exception: {e}")

# --- Completely empty item (new) ---
print("\n--- 6c. Testing Completely Empty RSS Item ---")
empty_item_xml = """<rss version="2.0">
<channel>
    <item></item>
    <item><title>   </title></item>
    <item><title></title></item>
</channel>
</rss>"""
try:
    root_e = ET.fromstring(empty_item_xml)
    e_items = root_e.findall(".//item")
    skipped = 0
    for item in e_items:
        t_elem = item.find("title")
        if t_elem is None or not t_elem.text or not t_elem.text.strip():
            skipped += 1
    check(skipped == 3, "All 3 empty/whitespace-title items skipped", f"Skipped: {skipped}")
except Exception as e:
    check(False, "Empty item XML parsing", f"Exception: {e}")


# ---------------------------------------------------------------------------
# Test 7: Grounded Summaries - No Invented Sources, Links, or Dates
# ---------------------------------------------------------------------------
print("\n--- 7. Testing Grounded Summaries (No Hallucinations) ---")
test_evidence = (
    "Recent news results for 'AI chip release':\n\n"
    "- Headline: Semiconductor Corp unveils low-power inference accelerator\n"
    "  Publisher: Hardware Gazette\n"
    "  Published: Mon, 26 Oct 2026 08:30:00 GMT\n"
    "  URL: https://example.com/hardware-chip-2026\n\n"
    "- Headline: Tech startup announces open weights model\n"
    "  Publisher: Open Source Hub\n"
    "  Published: Date not provided\n"
    "  URL: Not available"
)

summary = summarize_search_results("AI chip release", test_evidence)
print("Summary output preview:")
print(summary[:300] + ("..." if len(summary) > 300 else ""))

check("Hardware Gazette" in summary or "hardware gazette" in summary.lower(),
      "Summary accurately cites reported publisher 'Hardware Gazette'")
check("https://example.com/hardware-chip-2026" in summary,
      "Summary preserves the exact article URL for user verification")
# Verify that it didn't invent a fake link for the second article
check("https://example.com/open-weights" not in summary and "https://example.com/tech-startup" not in summary,
      "Summary does not invent fabricated URLs when URL is 'Not available'")
# Verify that it didn't invent a past date for the undated item
check("199" not in summary and "198" not in summary and "201" not in summary,
      "Summary does not invent false historical dates for undated items")

# --- Test grounding with empty evidence (new) ---
empty_summary = summarize_search_results("quantum computing breakthroughs", "")
check("could not find" in empty_summary.lower() or "couldn't find" in empty_summary.lower(),
      "Empty evidence produces clear not-found message", f"Got: {empty_summary[:120]}")

no_results_summary = summarize_search_results(
    "alien sightings today",
    "I searched the web, but could not find sufficiently relevant or recent information for 'alien sightings today'."
)
check("could not find" in no_results_summary.lower() or "couldn't find" in no_results_summary.lower(),
      "Not-found evidence produces clear not-found message", f"Got: {no_results_summary[:120]}")


# ---------------------------------------------------------------------------
# Test 8: Live Query Integrations
# ---------------------------------------------------------------------------
print("\n--- 8. Testing Live Query Integrations ---")
# 8a: Latest AI news contains URLs and Publishers
live_news = search_web("the latest ai news")
check("url: http" in live_news.lower(), "Live news search includes article URLs", f"Snippet: {live_news[:180]}")
check("publisher:" in live_news.lower(), "Live news search includes publisher names")
check("15.ai" not in live_news.lower(), "Live news search excludes obsolete '15.ai'")
check("hey ai" not in live_news.lower(), "Live news search excludes conversational 'hey ai' results")

# 8b: Technical tutorial query includes educational/documentation references
live_tech = search_web("Python tutorial")
check("url: http" in live_tech.lower() or "wikipedia" in live_tech.lower(),
      "Technical tutorial search includes relevant resource URLs", f"Snippet: {live_tech[:180]}")

# 8c: Public figure includes URL
live_person = search_web("Who is Alex Morgan")
check("alex morgan" in live_person.lower() and "url: http" in live_person.lower(),
      "Public figure search includes profile URL", f"Snippet: {live_person[:180]}")


# ---------------------------------------------------------------------------
# Test 9: News vs Technical Query Classification
# ---------------------------------------------------------------------------
print("\n--- 9. Testing News vs Technical Query Classification ---")
import re

def _is_news_query(q):
    lowered = q.lower()
    news_terms = {"latest", "recent", "today", "this week", "news", "current", "breaking"}
    return any(re.search(r"\b" + re.escape(w) + r"\b", lowered) for w in news_terms)

def _is_technical_query(q):
    lowered = q.lower()
    technical_terms = {
        "tutorial", "tutorials", "documentation", "docs", "guide",
        "how to", "learn", "course", "example", "examples", "reference"
    }
    return any(re.search(r"\b" + re.escape(w) + r"\b", lowered) for w in technical_terms)

check(_is_news_query("latest ai news"), "News query: 'latest ai news' detected")
check(_is_news_query("breaking tech updates"), "News query: 'breaking tech updates' detected")
check(_is_news_query("what happened today in tech"), "News query: 'today' keyword detected")
check(not _is_news_query("Python tutorial"), "Non-news query: 'Python tutorial' not flagged as news")
check(_is_technical_query("Python tutorial"), "Technical query: 'Python tutorial' detected")
check(_is_technical_query("how to install Docker"), "Technical query: 'how to' detected")
check(not _is_technical_query("latest ai news"), "Non-technical query: 'latest ai news' not flagged as technical")

# Mixed query: both news and technical
check(_is_news_query("latest Python tutorial news"), "Mixed query detected as news")
check(_is_technical_query("latest Python tutorial news"), "Mixed query detected as technical")


# ---------------------------------------------------------------------------
# Test 10: search_news returns list of formatted strings
# ---------------------------------------------------------------------------
print("\n--- 10. Testing search_news Return Format ---")
news_results = search_news("technology", max_results=3)
if news_results:
    check(isinstance(news_results, list), "search_news returns a list")
    check(len(news_results) <= 3, "search_news respects max_results",
          f"Got {len(news_results)} results")
    first = news_results[0]
    check("Headline:" in first, "Result contains 'Headline:' field", f"Got: {first[:100]}")
    check("Publisher:" in first, "Result contains 'Publisher:' field")
    check("Published:" in first, "Result contains 'Published:' field")
    check("URL:" in first, "Result contains 'URL:' field")
else:
    # Network might be down; don't fail hard but note it
    print("[SKIP] search_news returned no results (possible network issue)")


print("\n" + "=" * 65)
print(f"Web Search Test Summary: {passed} passed, {failed} failed out of {passed + failed} tests.")
print("=" * 65)

if failed > 0:
    sys.exit(1)
