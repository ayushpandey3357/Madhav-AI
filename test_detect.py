"""
Comprehensive test for detect_tool_request(), allowlist validation, and tools.
Run with:  uv run test_detect.py
"""
import sys
sys.path.insert(0, ".")

from main import detect_tool_request, TOOLS

# (input_text, expected_tool_or_None, description)
TEST_CASES = [
    # --- Ordinary questions & statements (MUST NOT trigger any tool) ---
    ("Who is Stella Cox?",                          None,              "question about a person"),
    ("I think Stella Cox is an actress",            None,              "statement about a person"),
    ("Tell me about Virat Kohli",                   None,              "tell-me about a person"),
    ("Explain neural networks",                     None,              "explain a topic"),
    ("What is machine learning?",                   None,              "what-is question"),
    ("Who is the owner of Facebook?",               None,              "who-is question"),
    ("Who is Madison Ivy?",                         None,              "who-is about a name"),
    ("",                                            None,              "empty input"),
    ("aadat",                                       None,              "bare song name"),

    # --- YouTube searches ---
    ("Search YouTube for Python tutorials",         "search_youtube",  "explicit youtube search"),
    ("Find a YouTube video about machine learning", "search_youtube",  "find youtube video"),
    ("youtube tutorial for React",                  "search_youtube",  "youtube tutorial for"),
    ("play on youtube lo-fi music",                 "search_youtube",  "play on youtube"),
    ("play aadat on yt",                            "search_youtube",  "play X on yt"),

    # --- Spotify searches ---
    ("Search Spotify for Arijit Singh",             "search_spotify",  "explicit spotify search"),
    ("play on spotify aadat",                       "search_spotify",  "play on spotify"),
    ("play aadat",                                  "search_spotify",  "natural play -- Spotify"),
    ("play lo-fi hip hop",                          "search_spotify",  "natural play -- genre"),

    # --- Spotify playback controls ---
    ("Pause the music",                             "control_spotify", "pause"),
    ("Next song",                                   "control_spotify", "next song"),
    ("Previous track",                              "control_spotify", "previous"),
    ("Volume up",                                   "control_spotify", "volume up"),
    ("Turn down the volume",                        "control_spotify", "volume down"),

    # --- Web searches ---
    ("Search the web for Python tutorials",         "search_web",      "search the web for"),
    ("Search internet for latest AI news",          "search_web",      "search internet for"),
    ("Look up on the internet quantum computing",   "search_web",      "look up on internet"),
    ("Search google for space exploration",         "search_web",      "search google for"),
    ("Search for Dani Daniels on the web",          "search_web",      "search X on the web"),

    # --- Wake phrase regression tests ---
    ("Hey Madhav, search the web for the latest AI news.", "search_web", "wake phrase: Hey Madhav, search the web"),
    ("Madhav, search the web for OpenAI news.",            "search_web", "wake phrase: Madhav, search the web"),
    ("Hey Madhav, search for local LLM developments.",     "search_web", "wake phrase: Hey Madhav, search for"),
    ("Search the web for the latest AI news",              "search_web", "no wake phrase: search the web for latest AI news"),
    ("Search for local LLM developments",                  "search_web", "no wake phrase: search for local LLM developments"),

    # --- Queries where 'Madhav' is part of the actual search topic ---
    ("Search the web for Madhav Gadgil",                   "search_web", "topic has Madhav: search the web for Madhav Gadgil"),
    ("Hey Madhav, search the web for Madhav Gadgil.",      "search_web", "wake phrase + topic has Madhav"),
    ("Search for Madhav Sheth on the web",                 "search_web", "topic has Madhav: Search for Madhav Sheth on the web"),
    ("Hey Madhav, check Git status.",                       "git_status", "git status command"),
    ("Show me my changed files.",                          "git_changed_files", "git changed files command"),
    ("Add all my changes to Git.",                        "git_stage", "git stage command"),
    ("Commit my changes with message fixed login bug.",   "git_commit", "git commit message extraction"),
    ("Push my changes to GitHub.",                        "git_push", "git push command"),
    ("Commit and push my changes.",                       "git_add_commit_push", "git workflow command"),
    ("Show my last five commits.",                        "git_recent_commits", "git recent commits count"),
    ("What is git commit?",                               None,         "git question does not trigger action"),
    ("Who is Madhav Gadgil?",                              None,         "topic has Madhav: Who is Madhav Gadgil?"),
    ("Tell me about Madhav Sharma",                        None,         "topic has Madhav: Tell me about Madhav Sharma"),
    ("What is Madhav National Park?",                      None,         "topic has Madhav: What is Madhav National Park?"),
    ("Madhav Gadgil biography",                            None,         "topic has Madhav: Madhav Gadgil biography"),
]

passed = 0
failed = 0

print("--- Testing detect_tool_request() ---")
for text, expected_tool, desc in TEST_CASES:
    result = detect_tool_request(text)
    actual_tool = result.get("tool") if result else None

    ok = (actual_tool == expected_tool)
    status = "PASS" if ok else "FAIL"

    if ok:
        passed += 1
    else:
        failed += 1

    tag = f"[{status}]"
    print(f"{tag:<7} {desc}")
    if not ok:
        print(f"         Input:    {repr(text)}")
        print(f"         Expected: {expected_tool}")
        print(f"         Got:      {actual_tool}  (full result: {result})")

print("\n--- Testing Tool Allowlist Security ---")
# 1. Verify all expected tools exist in TOOLS allowlist
expected_tools = {
    "search_spotify", "search_youtube", "control_spotify", "search_web",
    "git_status", "git_changed_files", "git_branch", "git_recent_commits",
    "git_stage", "git_commit", "git_push", "git_add_commit_push",
}
if set(TOOLS.keys()) == expected_tools:
    print("[PASS]   Allowlist contains exact expected tools:", set(TOOLS.keys()))
    passed += 1
else:
    print("[FAIL]   Allowlist mismatch:", set(TOOLS.keys()))
    failed += 1

# 2. Verify unknown tools are rejected
unknown_tool = "rm_rf_system"
if unknown_tool not in TOOLS:
    print(f"[PASS]   Unknown tool '{unknown_tool}' is correctly blocked by allowlist.")
    passed += 1
else:
    print(f"[FAIL]   Unknown tool '{unknown_tool}' unexpectedly allowed!")
    failed += 1

print("\n--- Testing Extracted Query Cleanliness & Wake Phrase Stripping ---")
query_tests = [
    ("Hey Madhav, search the web for the latest AI news.", "the latest ai news", "Wake phrase 'Hey Madhav' cleanly removed from query"),
    ("Madhav, search the web for OpenAI news.",            "openai news",         "Wake phrase 'Madhav,' cleanly removed from query"),
    ("Hey Madhav, search for local LLM developments.",     "local llm developments", "Wake phrase 'Hey Madhav' removed from 'search for' query"),
    ("Search the web for Madhav Gadgil",                   "madhav gadgil",       "Madhav preserved when part of search topic"),
    ("Hey Madhav, search the web for Madhav Gadgil.",      "madhav gadgil",       "Wake phrase removed and Madhav preserved as topic"),
    ("Search for Madhav Sheth on the web",                 "madhav sheth",        "Madhav preserved in suffix search query"),
]
for text, expected_query, desc in query_tests:
    res = detect_tool_request(text)
    actual_q = res.get("query") if res else None
    ok = (actual_q == expected_query)
    status = "PASS" if ok else "FAIL"
    if ok:
        passed += 1
    else:
        failed += 1
    tag = f"[{status}]"
    print(f"{tag:<7} {desc}")
    if not ok:
        print(f"         Input:    {repr(text)}")
        print(f"         Expected: {repr(expected_query)}")
        print(f"         Got:      {repr(actual_q)}")

print()
print(f"Results: {passed} passed, {failed} failed out of {len(TEST_CASES) + 2 + len(query_tests)} tests.")
if failed == 0:
    print("All tests passed successfully!")
else:
    sys.exit(1)
