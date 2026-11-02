import json
import os
import re
import urllib.parse
import urllib.request

DEFAULT_BASE_URL = "https://kurse.example.invalid"


def base_url() -> str:
    return os.environ.get("NOCHECKTOOL_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def fetch_items(query: str):
    url = base_url() + "/items?" + urllib.parse.urlencode({"q": query})
    with urllib.request.urlopen(url, timeout=20) as response:
        data = json.load(response)
    needle = query.casefold()
    return [item for item in data if needle in item.get("name", "").casefold()]


def post_form(fields) -> str:
    body = urllib.parse.urlencode(fields).encode("utf-8")
    request = urllib.request.Request(base_url() + "/form", data=body, method="POST")
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8", "replace")


def extract_fid(html: str):
    pattern = (
        r'<input[^>]*name=["\']fid["\'][^>]*value=["\']([^"\']+)["\']'
    )
    match = re.search(pattern, html, re.IGNORECASE)
    if match:
        return match.group(1)
    pattern = (
        r'<input[^>]*value=["\']([^"\']+)["\'][^>]*name=["\']fid["\']'
    )
    match = re.search(pattern, html, re.IGNORECASE)
    return match.group(1) if match else None
