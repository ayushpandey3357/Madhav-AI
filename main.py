import json
import re
import requests

from tools.music import (
    search_spotify,
    search_youtube,
    control_spotify,
)
from tools.web_search import search_web
from tools.git_tools import (
    GitToolError,
    add_commit_push,
    check_status,
    create_commit,
    current_branch,
    is_sensitive_path,
    list_changed_files,
    push_current_branch,
    recent_commits,
    stage_changes,
)

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "qwen2.5:3b"

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are MADHAV, a helpful, knowledgeable, and neutral personal AI assistant created by Ayush.

Your job is to answer questions and have natural, informative conversations.

IMPORTANT GUIDELINES:
- You must ALWAYS respond with exactly one JSON object.
- You must ALWAYS use the "reply" action -- never use "tool".
- Answer factual and biographical questions neutrally, objectively, and factually.
- When asked about public figures (including actors, actresses, adult entertainment stars, entertainers, athletes, politicians, and media personalities), answer helpfully and neutrally without moral judgments, lectures, or automatic refusals. Provide standard encyclopedic facts such as their profession, nationality, and background.
- Do NOT refuse questions about people simply because they work in adult entertainment or other entertainment fields.
- Do NOT hallucinate or invent facts. If you truly do not know reliable facts about someone or something, state plainly that you do not have enough verified information.
- Do NOT output canned refusals such as "I cannot provide information about specific individuals".

Response format (always use this exact format):
{"action": "reply", "message": "your answer here"}

Examples:
User: "Who is Virat Kohli?"
Response: {"action": "reply", "message": "Virat Kohli is an Indian international cricketer and former captain of the Indian national team, regarded as one of the greatest batsmen in modern cricket."}

User: "What is machine learning?"
Response: {"action": "reply", "message": "Machine learning is a branch of artificial intelligence where algorithms learn patterns from data to make predictions or decisions without explicit programming."}

User: "Who is Mia Khalifa?"
Response: {"action": "reply", "message": "Mia Khalifa is a Lebanese-American media personality and former adult film actress who gained widespread public attention in 2014."}
"""

# ---------------------------------------------------------------------------
# Allowed tools (allowlist -- nothing outside this dict can be called)
# ---------------------------------------------------------------------------
TOOLS = {
    "search_spotify": search_spotify,
    "search_youtube": search_youtube,
    "control_spotify": control_spotify,
    "search_web": search_web,
    "git_status": check_status,
    "git_changed_files": list_changed_files,
    "git_branch": current_branch,
    "git_recent_commits": recent_commits,
    "git_stage": stage_changes,
    "git_commit": create_commit,
    "git_push": push_current_branch,
    "git_add_commit_push": add_commit_push,
}

# ---------------------------------------------------------------------------
# Wake phrase removal & normalization
# ---------------------------------------------------------------------------
def strip_wake_phrase(text: str) -> str:
    """
    Recognize and remove assistant wake phrases (e.g., 'Hey Madhav', 'Madhav,')
    from the beginning of the text, normalizing punctuation and whitespace.
    Preserves meaningful words and queries where 'Madhav' is part of the search topic
    (e.g., 'Search the web for Madhav Gadgil' or 'Madhav National Park').
    """
    if not text or not isinstance(text, str):
        return ""

    cleaned = text.strip()

    # 1. Greeting + Madhav: e.g. "Hey Madhav", "Hi Madhav", "Hello Madhav", "Ok Madhav", "Okay Madhav"
    # Followed by optional punctuation (comma, colon, dash, exclamation, period) and whitespace
    greeting_pattern = r"^(?:hey|hi|hello|ok|okay)\s+madhav\b\s*[,:!\-\.]*\s*"
    match = re.match(greeting_pattern, cleaned, flags=re.IGNORECASE)
    if match:
        cleaned = cleaned[match.end():].strip()
    else:
        # 2. Bare "Madhav" followed by punctuation: e.g. "Madhav,", "Madhav:", "Madhav -", "Madhav!"
        punct_pattern = r"^madhav\s*[,:!\-]\s*"
        match = re.match(punct_pattern, cleaned, flags=re.IGNORECASE)
        if match:
            cleaned = cleaned[match.end():].strip()
        else:
            # 3. Bare "Madhav" directly followed by command verbs, politeness fillers, or question words
            # (e.g. "Madhav search the web...", "Madhav please find...", "Madhav what is...")
            # Does NOT match proper nouns like "Madhav Gadgil" or "Madhav National Park"
            cmd_pattern = (
                r"^madhav\s+(?=(?:please|can you|could you|would you|search|find|look up|"
                r"browse|play|pause|resume|next|skip|previous|volume|mute|unmute|"
                r"who|what|where|when|why|how|tell|explain|describe|show)\b)"
            )
            match = re.match(cmd_pattern, cleaned, flags=re.IGNORECASE)
            if match:
                cleaned = cleaned[match.end():].strip()

    # 4. Strip leading politeness words if any
    politeness_pattern = r"^(?:please\s+|can you\s+|could you\s+|would you\s+)+"
    cleaned = re.sub(politeness_pattern, "", cleaned, flags=re.IGNORECASE).strip()

    # Normalize whitespace
    cleaned = " ".join(cleaned.split())
    return cleaned


# ---------------------------------------------------------------------------
# detect_tool_request()
# ---------------------------------------------------------------------------
def detect_tool_request(text: str):
    """
    Check whether the user explicitly asked to use a tool.

    Returns a tool-dispatch dict, or None if no explicit tool request was made.

    Design rules:
    - Recognize and remove wake phrases (e.g. 'Hey Madhav', 'Madhav,') first.
    - Only complete, explicit command phrases trigger a tool.
    - Mentioning a person, place, or topic does NOT trigger a tool.
    - Matching is done on full phrases, not single keywords like 'play'.
    """
    cleaned = strip_wake_phrase(text)
    lowered = cleaned.lower().strip()

    # ------------------------------------------------------------------
    # Git commands -- only explicit action phrases trigger Git operations.
    # Questions such as "What is git commit?" remain ordinary questions.
    # ------------------------------------------------------------------
    git_request = _detect_git_request(lowered)
    if git_request:
        return git_request

    # ------------------------------------------------------------------
    # 1. Music-control commands (no query extraction needed)
    # ------------------------------------------------------------------
    music_commands = {
        "play_pause": [
            "pause the music",
            "pause music",
            "resume the music",
            "resume music",
            "play the music",
            "continue music",
            "toggle music",
            "play pause",
        ],
        "next": [
            "next song",
            "next track",
            "skip song",
            "skip this song",
            "play next",
            "next music",
        ],
        "previous": [
            "previous song",
            "previous track",
            "last song",
            "go back a song",
            "play previous",
        ],
        "volume_up": [
            "increase volume",
            "increase the volume",
            "volume up",
            "turn up the volume",
            "louder",
        ],
        "volume_down": [
            "decrease volume",
            "decrease the volume",
            "volume down",
            "turn down the volume",
            "quieter",
        ],
        "mute": [
            "mute the sound",
            "mute volume",
            "unmute the sound",
            "toggle mute",
        ],
    }

    for action, phrases in music_commands.items():
        for phrase in phrases:
            if phrase in lowered:
                return {
                    "action": "tool",
                    "tool": "control_spotify",
                    "query": action,
                }

    # ------------------------------------------------------------------
    # 2. Web search -- triggered by explicit web / internet search phrases
    # ------------------------------------------------------------------
    web_triggers = [
        ("search web for ",            ["search web for"]),
        ("search the web for ",        ["search the web for"]),
        ("search on web for ",         ["search on web for"]),
        ("search on the web for ",     ["search on the web for"]),
        ("search internet for ",       ["search internet for"]),
        ("search the internet for ",   ["search the internet for"]),
        ("search on internet for ",    ["search on internet for"]),
        ("search on the internet for ",["search on the internet for"]),
        ("look up on the internet ",   ["look up on the internet"]),
        ("look up on the web ",        ["look up on the web"]),
        ("browse web for ",            ["browse web for"]),
        ("search google for ",         ["search google for"]),
        ("search online for ",         ["search online for"]),
    ]

    for trigger, strip_phrases in web_triggers:
        if lowered.startswith(trigger) or (" " + trigger) in lowered:
            query = _extract_query(lowered, strip_phrases)
            if query:
                return {
                    "action": "tool",
                    "tool": "search_web",
                    "query": query,
                }

    # Also detect phrases ending in "on the internet" or "on the web"
    # e.g., "search for Python tutorials on the web"
    for suffix in (" on the web", " on the internet", " on web", " on internet", " online"):
        if lowered.endswith(suffix):
            prefix_part = lowered[:-len(suffix)].strip()
            for start_phrase in ("search for ", "search ", "look up ", "find information about ", "find info on "):
                if prefix_part.startswith(start_phrase):
                    query = prefix_part[len(start_phrase):].strip(" .,!?")
                    if query:
                        return {
                            "action": "tool",
                            "tool": "search_web",
                            "query": query,
                        }

    # ------------------------------------------------------------------
    # 3. YouTube search -- only triggered by explicit YouTube phrases
    # ------------------------------------------------------------------
    youtube_triggers = [
        ("search youtube for ",         ["search youtube for"]),
        ("search on youtube for ",      ["search on youtube for"]),
        ("search on youtube ",          ["search on youtube"]),
        ("find on youtube for ",        ["find on youtube for"]),
        ("find on youtube ",            ["find on youtube"]),
        ("find a youtube video about ", ["find a youtube video about"]),
        ("youtube video about ",        ["youtube video about"]),
        ("youtube tutorial for ",       ["youtube tutorial for"]),
        ("youtube tutorial on ",        ["youtube tutorial on"]),
        ("watch on youtube ",           ["watch on youtube"]),
        ("play on youtube ",            ["play on youtube"]),
        ("open youtube and search ",    ["open youtube and search"]),
    ]

    for trigger, strip_phrases in youtube_triggers:
        if lowered.startswith(trigger) or (" " + trigger) in lowered:
            query = _extract_query(lowered, strip_phrases)
            if query:
                return {
                    "action": "tool",
                    "tool": "search_youtube",
                    "query": query,
                }

    # ------------------------------------------------------------------
    # 4. Spotify search -- only triggered by explicit Spotify phrases
    # ------------------------------------------------------------------
    spotify_triggers = [
        ("search spotify for ",        ["search spotify for"]),
        ("search on spotify for ",     ["search on spotify for"]),
        ("search on spotify ",         ["search on spotify"]),
        ("play on spotify ",           ["play on spotify"]),
        ("put on spotify ",            ["put on spotify"]),
        ("open spotify and search ",   ["open spotify and search"]),
    ]

    for trigger, strip_phrases in spotify_triggers:
        if lowered.startswith(trigger) or (" " + trigger) in lowered:
            query = _extract_query(lowered, strip_phrases)
            if query:
                return {
                    "action": "tool",
                    "tool": "search_spotify",
                    "query": query,
                }

    # ------------------------------------------------------------------
    # 5. Natural "play X" -- only treat as Spotify if not a question/sentence
    # ------------------------------------------------------------------
    question_words = {
        "who", "what", "where", "when", "why", "how", "is", "are",
        "was", "were", "does", "do", "did", "tell", "explain",
        "describe", "define", "can", "could", "would", "should",
    }
    non_song_words = {
        "music", "the", "a", "an", "next", "previous", "last",
        "pause", "resume",
    }

    if lowered.startswith("play "):
        remaining = lowered[5:].strip()
        words = remaining.split()
        first_word = words[0] if words else ""
        starts_with_question = (
            first_word in question_words
            or any(remaining.startswith(w + " ") or remaining == w
                   for w in question_words)
        )
        if not starts_with_question and first_word not in non_song_words:
            # Check if user specified 'on youtube' or 'on yt' at the end.
            yt_suffixes = (" on youtube", " on yt")
            target_platform = "search_spotify"
            query = remaining
            for suffix in yt_suffixes:
                if query.endswith(suffix):
                    query = query[:-len(suffix)].strip()
                    target_platform = "search_youtube"
                    break
            query = query.strip(" .,!?")
            if query:
                return {
                    "action": "tool",
                    "tool": target_platform,
                    "query": query,
                }

    # ------------------------------------------------------------------
    # 6. General "search for X" (web search fallback for explicit search commands)
    # ------------------------------------------------------------------
    if lowered.startswith("search for ") and "spotify" not in lowered and "youtube" not in lowered and "yt" not in lowered:
        query = _extract_query(lowered, ["search for"])
        if query:
            return {
                "action": "tool",
                "tool": "search_web",
                "query": query,
            }

    # No explicit tool request detected.
    return None


def _detect_git_request(lowered: str):
    """Return a deterministic Git request, or None for Git-related questions."""
    normalized = lowered.strip(" .,!?\t")
    if re.search(r"\b(?:check|show|display|list)\s+(?:the\s+)?git\s+status$", normalized):
        return {"action": "tool", "tool": "git_status", "query": "status"}
    if re.search(r"\b(?:show|list)\s+(?:me\s+)?(?:my\s+)?(?:changed|modified|untracked)\s+files?$", normalized):
        return {"action": "tool", "tool": "git_changed_files", "query": "files"}
    if re.search(r"\b(?:show|display)\s+(?:me\s+)?(?:my\s+)?current\s+branch$", normalized):
        return {"action": "tool", "tool": "git_branch", "query": "branch"}

    commits_match = re.search(
        r"\b(?:show|list)\s+(?:me\s+)?(?:my\s+)?last\s+(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+commits?$",
        normalized,
    )
    if commits_match:
        count_value = commits_match.group(1)
        word_counts = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                       "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
        count = word_counts[count_value] if count_value in word_counts else int(count_value)
        return {"action": "tool", "tool": "git_recent_commits", "query": str(count), "count": count}
    if re.search(r"\b(?:show|list)\s+(?:me\s+)?(?:my\s+)?recent\s+commits?$", normalized):
        return {"action": "tool", "tool": "git_recent_commits", "query": "5", "count": 5}

    if re.search(r"\b(?:add|stage)\s+(?:all\s+)?(?:my\s+)?changes?\s+to\s+git$", normalized):
        return {"action": "tool", "tool": "git_stage", "query": "stage"}

    commit_match = re.search(r"\bcommit\s+(?:all\s+)?(?:my\s+)?changes?\s+with\s+message\s+(.+)$", normalized)
    if commit_match:
        message = commit_match.group(1).strip(" \t.,!?")
        return {"action": "tool", "tool": "git_commit", "query": message, "message": message}
    if re.search(r"\bcommit\s+(?:and\s+)?push\s+(?:all\s+)?(?:my\s+)?changes?$", normalized):
        return {"action": "tool", "tool": "git_add_commit_push", "query": "commit and push", "message": ""}
    if re.search(r"\bpush\s+(?:all\s+)?(?:my\s+)?changes?\s+to\s+github$", normalized):
        return {"action": "tool", "tool": "git_push", "query": "push"}
    if re.search(r"\bpush\s+(?:all\s+)?(?:my\s+)?changes?$", normalized):
        return {"action": "tool", "tool": "git_push", "query": "push"}
    return None


def _extract_query(text: str, phrases_to_remove: list) -> str:
    """Remove trigger phrases from text and return the cleaned query."""
    query = text
    for phrase in phrases_to_remove:
        query = query.replace(phrase, " ")
    # Strip generic noise that is never part of the search query.
    for noise in ("please", "for me", "for me please"):
        query = re.sub(r"\b" + re.escape(noise) + r"\b", " ", query, flags=re.IGNORECASE)
    query = " ".join(query.split()).strip(" .,!?")
    return query


def _format_stage_preview(safe_files, skipped_files):
    lines = ["Git files ready to stage:"]
    lines.extend(f"  + {path}" for path in safe_files)
    if skipped_files:
        lines.append("Skipped possible secret files:")
        lines.extend(f"  ! {path}" for path in skipped_files)
    return "\n".join(lines)


def _format_stage_result(result):
    staged = result.get("staged", [])
    skipped = result.get("skipped_secrets", [])
    lines = [f"Staged {len(staged)} safe file(s):"]
    lines.extend(f"  + {path}" for path in staged)
    if skipped:
        lines.append("Skipped possible secret files:")
        lines.extend(f"  ! {path}" for path in skipped)
    if not staged and result.get("message"):
        lines.append(str(result["message"]))
    return "\n".join(lines)


def is_uncertain_or_refusal(text: str) -> bool:
    """Check if the model's reply is a canned refusal or indicates lack of knowledge."""
    lower = text.lower()
    indicators = [
        "unable to provide information about specific individuals",
        "cannot provide information about specific individuals",
        "unable to provide information about",
        "cannot provide information about",
        "i do not have direct information",
        "i don't have direct information",
        "i do not have information about this person",
        "i don't have information about this person",
        "cannot search for information about specific individuals",
        "cannot search for information",
        "is not a widely recognized public figure",
        "i'm not certain about",
        "i am not certain about",
        "i don't have enough reliable information",
        "i do not have enough reliable information",
        "could you provide more context or details about the person",
        "i don't know who that is",
        "i do not know who that is",
        "no direct information",
    ]
    return any(ind in lower for ind in indicators)


def summarize_search_results(user_query: str, facts: str) -> str:
    """Summarize search results using the local Qwen model to directly answer the user's question."""
    if not facts or "could not find sufficiently relevant" in facts or "could not find relevant" in facts:
        return f"I searched the web, but couldn't find sufficiently relevant or recent information for '{user_query}'."

    prompt_messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"User asked: {user_query}\n\n"
                f"Verified search evidence:\n{facts}\n\n"
                "Instructions for your response:\n"
                "1. Base your answer STRICTLY on the search evidence provided above. "
                "Do not assume or assert facts not present in the evidence.\n"
                "2. When citing news articles, attribute the claims to their publishers "
                "(e.g., 'According to Bloomberg...', 'Mashable reports that...'). "
                "Do not present headlines as independently established facts.\n"
                "3. State the publication date EXACTLY as provided in the evidence. "
                "If marked 'Date not provided' or missing, say so; never guess or invent dates.\n"
                "4. Include the EXACT article URLs from the evidence so the user can verify. "
                "Never fabricate, guess, or modify URLs. If a URL is 'Not available', "
                "state that no link was provided rather than creating one.\n"
                "5. Clearly separate reported facts from any brief neutral synthesis.\n"
                "6. If the search evidence is empty or irrelevant, state that clearly "
                "instead of fabricating an answer.\n"
                "7. For each source mentioned, include: headline, publisher, date, and URL "
                "exactly as given in the evidence."
            ),
        },
    ]

    try:
        raw = ask_madhav(prompt_messages)
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and "message" in parsed:
                return parsed["message"]
        except json.JSONDecodeError:
            pass
        return raw.strip()
    except Exception:
        # Fallback to returning the top facts if Ollama fails
        return facts


# ---------------------------------------------------------------------------
# ask_madhav() -- sends the full message history to Ollama
# ---------------------------------------------------------------------------
def ask_madhav(messages: list) -> str:
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": MODEL,
            "messages": messages,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
        },
        timeout=180,
    )
    response.raise_for_status()
    return response.json()["message"]["content"]


# ---------------------------------------------------------------------------
# chat() -- main conversation loop
# ---------------------------------------------------------------------------
def chat():
    print("\n" + "=" * 45)
    print("          MADHAV AI ASSISTANT")
    print("=" * 45)
    print("Madhav is online. Type 'exit' to quit.\n")

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    while True:
        try:
            user_input = input("You: ").strip()

            # --- Exit ---
            if user_input.lower() in {"exit", "quit", "bye"}:
                print("Madhav: Goodbye!")
                break

            # --- Empty input ---
            if not user_input:
                print("Madhav: Please say something!\n")
                continue

            # ----------------------------------------------------------
            # Step 1: Check for an explicit tool request (deterministic).
            # ----------------------------------------------------------
            tool_dispatch = detect_tool_request(user_input)

            if tool_dispatch is not None:
                tool_name = tool_dispatch.get("tool", "")
                query = tool_dispatch.get("query", "")

                # Safety: only allow tools in the allowlist.
                if tool_name not in TOOLS:
                    answer = f"Sorry, I don't have a tool called '{tool_name}'."
                elif not isinstance(query, str) or not query.strip():
                    answer = "Please specify what you want to search for or do."
                elif tool_name.startswith("git_"):
                    try:
                        if tool_name == "git_status":
                            answer = check_status()
                        elif tool_name == "git_changed_files":
                            files = list_changed_files()
                            changed = files["changed"] or []
                            untracked = files["untracked"] or []
                            answer = (
                                f"Repository: {files['repository']}\n"
                                f"Changed: {', '.join(changed) or 'none'}\n"
                                f"Untracked: {', '.join(untracked) or 'none'}"
                            )
                        elif tool_name == "git_branch":
                            answer = f"Current branch: {current_branch()}"
                        elif tool_name == "git_recent_commits":
                            answer = recent_commits(tool_dispatch.get("count", 5))
                        elif tool_name == "git_stage":
                            staged = stage_changes()
                            answer = _format_stage_result(staged)
                        elif tool_name in {"git_commit", "git_add_commit_push"}:
                            message = tool_dispatch.get("message", "").strip()
                            if not message:
                                message = input("Commit message: ").strip()
                            if not message:
                                answer = "I need a non-empty commit message before committing."
                            else:
                                preview = list_changed_files()
                                candidate_files = (preview["changed"] or []) + (preview["untracked"] or [])
                                safe_files = [path for path in candidate_files if not is_sensitive_path(path)]
                                skipped = [path for path in candidate_files if is_sensitive_path(path)]
                                if not safe_files:
                                    answer = "No safe files are available to stage; secret-like files were skipped."
                                else:
                                    print(_format_stage_preview(safe_files, skipped))
                                    confirmation = input("Commit these files? Type 'yes' to confirm: ").strip().lower()
                                    if confirmation != "yes":
                                        answer = "Commit cancelled; no files were committed."
                                    else:
                                        staged = stage_changes()
                                        commit_output = create_commit(message)
                                        answer = commit_output
                                        if tool_name == "git_add_commit_push":
                                            answer += "\n" + push_current_branch()
                        elif tool_name == "git_push":
                            answer = push_current_branch()
                        else:
                            answer = "Unsupported Git operation."
                    except GitToolError as err:
                        answer = f"Git operation failed: {err}"
                else:
                    if tool_name == "control_spotify":
                        print(f"\nMadhav is controlling music: {query}")
                        try:
                            answer = control_spotify(query)
                        except Exception as err:
                            answer = f"The tool failed with an error: {err}"
                    elif tool_name == "search_web":
                        print(f"\nMadhav is searching the web for: {query}")
                        try:
                            raw_facts = TOOLS["search_web"](query)
                            # Summarize the search results to answer the user
                            clean_query = strip_wake_phrase(user_input) or user_input
                            answer = summarize_search_results(clean_query, raw_facts)
                        except Exception as err:
                            answer = f"Web search failed with an error: {err}"
                    else:
                        print(f"\nMadhav is using {tool_name} to search for: {query}")
                        try:
                            answer = TOOLS[tool_name](query)
                        except Exception as err:
                            answer = f"The tool failed with an error: {err}"

                print(f"Madhav: {answer}\n")

                # Record tool interaction in conversation history so
                # follow-up questions can reference it.
                messages.append({"role": "user", "content": user_input})
                messages.append({
                    "role": "assistant",
                    "content": json.dumps({"action": "reply", "message": answer}),
                })

            else:
                # ----------------------------------------------------------
                # Step 2: No tool detected -- ask the local AI model (local first).
                # ----------------------------------------------------------
                messages.append({"role": "user", "content": user_input})

                raw_response = ask_madhav(messages)

                # Parse the model's JSON response.
                try:
                    result = json.loads(raw_response)
                except json.JSONDecodeError:
                    result = {"action": "reply", "message": raw_response}

                if not isinstance(result, dict):
                    result = {"action": "reply", "message": str(result)}

                action = result.get("action", "reply")
                answer = result.get("message", "Sorry, I couldn't formulate a response.")

                if action == "tool":
                    # Model tried to call a tool despite instructions. Fall back to message.
                    if not answer:
                        answer = "I understood that as a tool request, but please ask me more explicitly."

                # ----------------------------------------------------------
                # Step 3: Check if the model refused or lacks knowledge.
                # If so, activate the web search fallback.
                # ----------------------------------------------------------
                if is_uncertain_or_refusal(answer):
                    print("\nMadhav is checking the web for verified information...")
                    try:
                        clean_query = strip_wake_phrase(user_input) or user_input
                        raw_facts = search_web(clean_query)
                        if raw_facts and "could not find relevant factual information" not in raw_facts:
                            answer = summarize_search_results(clean_query, raw_facts)
                    except Exception as err:
                        # Keep original answer if search fails
                        pass

                print(f"\nMadhav: {answer}\n")

                messages.append({
                    "role": "assistant",
                    "content": json.dumps({"action": "reply", "message": answer}),
                })

        except requests.exceptions.ConnectionError:
            print(
                "\nMadhav: I can't connect to Ollama. "
                "Please make sure Ollama is running.\n"
            )

        except requests.exceptions.Timeout:
            print("\nMadhav: The request took too long. Please try again.\n")

        except requests.exceptions.RequestException as error:
            print(f"\nMadhav: Connection error: {error}\n")

        except KeyboardInterrupt:
            print("\nMadhav: Goodbye!")
            break


if __name__ == "__main__":
    chat()
