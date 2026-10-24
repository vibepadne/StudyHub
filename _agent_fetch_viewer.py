import pathlib
import re

import requests

base = "http://127.0.0.1:8000"
session = requests.Session()
login = session.get(f"{base}/accounts/login/")
match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', login.text)
assert match, "no csrf"
response = session.post(
    f"{base}/accounts/login/",
    data={
        "username": "mobileqa",
        "password": "mobileqa123",
        "csrfmiddlewaretoken": match.group(1),
    },
    headers={"Referer": f"{base}/accounts/login/"},
)
print("login_status", response.status_code, response.url)
viewer = session.get(f"{base}/viewer/subject/81/")
print("viewer_status", viewer.status_code, viewer.url)
text = viewer.text
needles = [
    "viewer-toc-backdrop",
    "viewer-toc-reopen",
    "viewer-main",
    "Ask AI",
    "style.css?v=103",
    "viewer.js?v=13",
]
for needle in needles:
    print(needle, needle in text)
out = pathlib.Path("static/_agent_viewer.html")
out.write_text(text, encoding="utf-8")
print("wrote", out, "bytes", out.stat().st_size)
