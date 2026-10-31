"""
End-to-end integration test for Madhav.
Tests model responses, biographical answering, web search fallback,
explicit web search, YouTube, Spotify, and error handling.
"""
import json
import sys
from main import (
    detect_tool_request,
    ask_madhav,
    search_web,
    summarize_search_results,
    is_uncertain_or_refusal,
    TOOLS,
    SYSTEM_PROMPT,
)

print("=" * 50)
print("MADHAV AI ASSISTANT - INTEGRATION TEST SUITE")
print("=" * 50)

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

# 1. Test local answering on ordinary factual query
print("\n--- 1. Testing Local Model on Ordinary Questions ---")
try:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "What is machine learning?"}
    ]
    raw = ask_madhav(messages)
    data = json.loads(raw)
    msg = data.get("message", "")
    check("learning" in msg.lower() or "data" in msg.lower() or "ai" in msg.lower(),
          "Machine learning question answered locally", f"Got: {msg[:100]}")
except Exception as e:
    check(False, "Machine learning question", f"Error: {e}")

# 2. Test biographical question (Mia Khalifa) without refusal
print("\n--- 2. Testing Biographical Question (Mia Khalifa) ---")
try:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "Who is Mia Khalifa?"}
    ]
    raw = ask_madhav(messages)
    data = json.loads(raw)
    msg = data.get("message", "")
    is_refusal = is_uncertain_or_refusal(msg)
    check(not is_refusal and ("khalifa" in msg.lower() or "actress" in msg.lower() or "media" in msg.lower()),
          "Mia Khalifa biographical question answered without refusal", f"Got: {msg}")
except Exception as e:
    check(False, "Biographical question Mia Khalifa", f"Error: {e}")

# 3. Test biographical fallback on lesser-known / uncertain subject (Stella Cox)
print("\n--- 3. Testing Web Search Fallback for Stella Cox ---")
try:
    # First check what local model says
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "Who is Stella Cox?"}
    ]
    raw = ask_madhav(messages)
    data = json.loads(raw)
    msg = data.get("message", "")
    if is_uncertain_or_refusal(msg):
        # Fallback triggers
        facts = search_web("Stella Cox")
        summary = summarize_search_results("Who is Stella Cox?", facts)
        check("stella" in summary.lower() or "actress" in summary.lower(),
              "Stella Cox answered using web search fallback", f"Summary: {summary}")
    else:
        check("stella" in msg.lower() or "actress" in msg.lower(),
              "Stella Cox answered directly by model", f"Got: {msg}")
except Exception as e:
    check(False, "Stella Cox fallback", f"Error: {e}")

# 4. Test explicit web search tool detection and execution
print("\n--- 4. Testing Explicit Web Search ---")
tool_req = detect_tool_request("Search the web for Python programming language")
check(tool_req is not None and tool_req.get("tool") == "search_web",
      "Explicit web search detected properly", f"Got: {tool_req}")

if tool_req and tool_req.get("tool") == "search_web":
    facts = TOOLS["search_web"](tool_req["query"])
    summary = summarize_search_results("Python programming language", facts)
    check("python" in summary.lower() and ("language" in summary.lower() or "programming" in summary.lower()),
          "Web search results retrieved and summarized into natural answer", f"Summary: {summary[:120]}")

# 5. Test explicit Spotify and YouTube commands
print("\n--- 5. Testing Spotify & YouTube Explicit Detection ---")
req_sp = detect_tool_request("Search Spotify for Arijit Singh")
check(req_sp is not None and req_sp.get("tool") == "search_spotify" and req_sp.get("query") == "arijit singh",
      "Spotify search detected with clean query", f"Got: {req_sp}")

req_yt = detect_tool_request("Search YouTube for Python tutorials")
check(req_yt is not None and req_yt.get("tool") == "search_youtube" and req_yt.get("query") == "python tutorials",
      "YouTube search detected with clean query", f"Got: {req_yt}")

req_ctrl = detect_tool_request("Pause the music")
check(req_ctrl is not None and req_ctrl.get("tool") == "control_spotify" and req_ctrl.get("query") == "play_pause",
      "Music control detected", f"Got: {req_ctrl}")

# 6. Test allowlist security
print("\n--- 6. Testing Tool Allowlist Security ---")
check("search_web" in TOOLS, "search_web registered in allowlist")
check("fake_malicious_tool" not in TOOLS, "Unknown tool blocked by allowlist")

# 7. Test Wake Phrase Handling & Regression Cases
print("\n--- 7. Testing Wake Phrase Handling & Regression Cases ---")
# 7a: "Hey Madhav, search the web for the latest AI news."
wake_ai = detect_tool_request("Hey Madhav, search the web for the latest AI news.")
check(wake_ai is not None and wake_ai.get("tool") == "search_web" and wake_ai.get("query") == "the latest ai news",
      "Hey Madhav stripped and query correctly extracted as 'the latest ai news'", f"Got: {wake_ai}")

if wake_ai and wake_ai.get("tool") == "search_web":
    facts = TOOLS["search_web"](wake_ai["query"])
    check("url: http" in facts.lower() and "publisher:" in facts.lower(),
          "Web search for latest AI news returns real articles with URLs and publishers")
    check("hey ai" not in facts.lower(),
          "Web search for latest AI news does not return irrelevant 'hey ai' article")

# 7b: "Madhav, search the web for OpenAI news."
wake_openai = detect_tool_request("Madhav, search the web for OpenAI news.")
check(wake_openai is not None and wake_openai.get("tool") == "search_web" and wake_openai.get("query") == "openai news",
      "Madhav, wake phrase stripped and query correctly extracted as 'openai news'", f"Got: {wake_openai}")

# 7c: "Hey Madhav, search for local LLM developments."
wake_local = detect_tool_request("Hey Madhav, search for local LLM developments.")
check(wake_local is not None and wake_local.get("tool") == "search_web" and wake_local.get("query") == "local llm developments",
      "Hey Madhav search for query correctly extracted as 'local llm developments'", f"Got: {wake_local}")

# 7d: Queries without wake phrase
no_wake = detect_tool_request("Search the web for the latest AI news")
check(no_wake is not None and no_wake.get("tool") == "search_web" and no_wake.get("query") == "the latest ai news",
      "Query without wake phrase extracted correctly", f"Got: {no_wake}")

# 7e: Queries where 'Madhav' is part of the actual search topic
topic_madhav = detect_tool_request("Search the web for Madhav Gadgil")
check(topic_madhav is not None and topic_madhav.get("tool") == "search_web" and topic_madhav.get("query") == "madhav gadgil",
      "Search topic containing 'Madhav' preserved completely", f"Got: {topic_madhav}")

wake_topic_madhav = detect_tool_request("Hey Madhav, search the web for Madhav Gadgil.")
check(wake_topic_madhav is not None and wake_topic_madhav.get("tool") == "search_web" and wake_topic_madhav.get("query") == "madhav gadgil",
      "Wake phrase removed while topic 'Madhav Gadgil' is fully preserved", f"Got: {wake_topic_madhav}")

topic_question = detect_tool_request("Who is Madhav Gadgil?")
check(topic_question is None,
      "Question where Madhav is the subject correctly routes to local answering without tool trigger")

print("\n" + "=" * 50)
print(f"Integration Summary: {passed} passed, {failed} failed out of {passed + failed} tests.")
print("=" * 50)

if failed > 0:
    sys.exit(1)
