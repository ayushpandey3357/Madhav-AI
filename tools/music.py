import os
import webbrowser
from urllib.parse import quote
import pyautogui
import time

import yt_dlp


def search_spotify(query: str) -> str:
    """Search Spotify and attempt to play the first result."""

    query = query.strip()

    if not query:
        return "Please specify a song or artist."

    spotify_uri = f"spotify:search:{quote(query)}"

    try:
        if os.name == "nt":
            os.startfile(spotify_uri)
        else:
            webbrowser.open(spotify_uri)

        # Wait for Spotify search results to load.
        time.sleep(5)

        # Attempt to select the first search result and play it.
        pyautogui.press("tab", presses=3, interval=0.3)
        pyautogui.press("enter")

        time.sleep(2)

        # Send the system media play/pause key.
        pyautogui.press("playpause")

        return (
            f"I searched Spotify for '{query}' and attempted "
            "to start playback. Please check Spotify to confirm."
        )

    except Exception as error:
        return f"I couldn't start Spotify playback: {error}"

def start_spotify_playback():
    """
    Attempt to start playback in the Spotify desktop app.

    Spotify must be open, and its interface must be ready.
    """

    try:
        time.sleep(3)

        # Activate Spotify's play/pause keyboard shortcut.
        pyautogui.press("playpause")

        return "I sent a playback command to your computer."

    except Exception as error:
        return f"I couldn't control playback: {error}"

def control_spotify(action: str) -> str:
    """Control media playback and system volume using keyboard media keys."""

    actions = {
        "play_pause": "playpause",
        "next": "nexttrack",
        "previous": "prevtrack",
        "volume_up": "volumeup",
        "volume_down": "volumedown",
        "mute": "volumemute",
    }

    if action not in actions:
        return "Sorry, I don't recognize that music command."

    try:
        pyautogui.press(actions[action])

        messages = {
            "play_pause": "Toggled music playback.",
            "next": "Skipped to the next track.",
            "previous": "Went to the previous track.",
            "volume_up": "Increased system volume.",
            "volume_down": "Decreased system volume.",
            "mute": "Toggled system mute.",
        }

        return messages[action]

    except Exception as error:
        return f"I couldn't control the music: {error}"

def search_youtube(query: str) -> str:
    """
    Search YouTube for a video and open the first matching
    video's watch page. Does not download the video.
    """

    query = query.strip()

    if not query:
        return "Please specify which video you want to watch."

    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "extract_flat": True,
        "skip_download": True,
    }

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            results = ydl.extract_info(
                f"ytsearch1:{query}",
                download=False
            )

        videos = results.get("entries", [])
        video = next(
            (item for item in videos if item),
            None
        )

        if not video:
            return f"I couldn't find a video for {query}."

        video_id = video.get("id")

        if not video_id:
            return "I found a result but couldn't retrieve its video ID."

        video_url = f"https://www.youtube.com/watch?v={video_id}"

        webbrowser.open(video_url)

        title = video.get("title", query)

        return (
            f"I found '{title}' and opened its YouTube watch page. "
            "Playback may depend on your browser and YouTube settings."
        )

    except Exception as error:
        return (
            f"I couldn't search YouTube right now. "
            f"Error: {error}"
        )
