"""RSS/Atom mini-reader: subscribe in feeds.json, fetch on demand.

xml.etree handles both RSS2 (<item>) and Atom (<entry>); feeds refresh on
the shell executor so a slow feed never touches the GUI thread. Free, no
dependencies, no cloud.
"""
from __future__ import annotations

import os
import re
import time
import urllib.request
import xml.etree.ElementTree as ET

from litebrowser.core.profile_lock import profile_locked
from litebrowser.core.storage_utils import read_json, write_json

_TTL = 30 * 60  # considered fresh for 30 min


def _path(base_dir: str) -> str:
    return os.path.join(base_dir, "feeds.json")


def load_feeds(base_dir: str) -> list[dict]:
    data = read_json(_path(base_dir), {"version": 1, "feeds": []})
    feeds = data.get("feeds") if isinstance(data, dict) else None
    return [f for f in feeds if isinstance(f, dict)] if isinstance(feeds, list) else []


def save_feeds(base_dir: str, feeds: list[dict]) -> None:
    with profile_locked(base_dir):
        write_json(_path(base_dir), {"version": 1, "feeds": feeds})


def add_feed(base_dir: str, url: str, title: str = "") -> dict:
    feeds = load_feeds(base_dir)
    for f in feeds:
        if f.get("url") == url:
            return f
    feed = {"url": url, "title": (title or url)[:100], "items": [], "fetched_at": 0}
    feeds.append(feed)
    save_feeds(base_dir, feeds)
    return feed


def remove_feed(base_dir: str, url: str) -> bool:
    feeds = load_feeds(base_dir)
    kept = [f for f in feeds if f.get("url") != url]
    if len(kept) == len(feeds):
        return False
    save_feeds(base_dir, kept)
    return True


def _fetch(url: str, timeout: float = 15.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mei/6 feed-reader"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(1024 * 1024)


def _parse_entries(xml_bytes: bytes, limit: int = 20) -> list[dict]:
    """RSS2 <item> and Atom <entry>, namespace-agnostic."""
    items = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return items
    for tag in ("item", "entry", "{http://www.w3.org/2005/Atom}entry"):
        for node in root.iter(tag):
            title = link = summary = ""
            for child in node:
                name = child.tag.split("}")[-1].lower()
                if name == "title" and not title:
                    title = (child.text or "").strip()[:200]
                elif name == "link":
                    link = (child.get("href") or (child.text or "").strip()) or link
                elif name in ("description", "summary", "content") and not summary:
                    summary = re.sub(r"<[^>]+>", " ", child.text or "").strip()[:300]
            if title:
                items.append({"title": title, "url": link, "summary": summary})
            if len(items) >= limit:
                return items
    return items


def refresh_feed(base_dir: str, feed_url: str) -> tuple[int, str]:
    """Fetch + parse one feed; persists items. Returns (count, error)."""
    feeds = load_feeds(base_dir)
    for feed in feeds:
        if feed.get("url") != feed_url:
            continue
        if time.time() - int(feed.get("fetched_at", 0) or 0) < _TTL and feed.get("items"):
            return len(feed.get("items", [])), ""
        try:
            items = _parse_entries(_fetch(feed_url))
        except Exception as exc:
            return 0, str(exc)
        feed["items"] = items
        feed["fetched_at"] = int(time.time())
        save_feeds(base_dir, feeds)
        return len(items), ""
    return 0, "feed not found"
