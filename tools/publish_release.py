#!/usr/bin/env python3
"""Publish a release: push main + tag v<VERSION>, create the GitHub release, upload the installer.

    python tools/publish_release.py [--draft]

Needs dist/FalconMods-Setup-<VERSION>.exe (tools/build_release.py) and GitHub credentials:
GITHUB_TOKEN, or whatever `git credential fill` returns for github.com (Git Credential Manager).
The token is never printed.
"""
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def git(*args, inp=None):
    return subprocess.run(["git", *args], cwd=ROOT, input=inp, capture_output=True, text=True, check=True).stdout


def version():
    with open(os.path.join(ROOT, "tools", "patcher.py"), encoding="utf-8") as f:
        return re.search(r'VERSION = "([^"]+)"', f.read()).group(1)


def changelog(ver):
    with open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8") as f:
        text = f.read()
    m = re.search(r"^## " + re.escape(ver) + r".*?$(.*?)(?=^## |\Z)", text, re.S | re.M)
    return m.group(1).strip() if m else ""


def token():
    if os.environ.get("GITHUB_TOKEN"):
        return os.environ["GITHUB_TOKEN"]
    env = dict(os.environ, GCM_INTERACTIVE="never", GIT_TERMINAL_PROMPT="0")
    out = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n",
                         capture_output=True, text=True, env=env).stdout
    for line in out.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1]
    sys.exit("no GitHub credentials (set GITHUB_TOKEN)")


def api(method, url, tok, data=None, content_type="application/json"):
    body = json.dumps(data).encode() if isinstance(data, dict) else data
    req = urllib.request.Request(url, data=body, method=method, headers={
        "Authorization": "Bearer " + tok, "Accept": "application/vnd.github+json",
        "Content-Type": content_type, "User-Agent": "falconmods-release"})
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        sys.exit(f"GitHub API {method} {url.split('?')[0]} failed: {e.code} {e.read()[:300]!r}")


def main():
    ver = version()
    tag = "v" + ver
    asset = os.path.join(ROOT, "dist", f"FalconMods-Setup-{ver}.exe")
    if not os.path.isfile(asset):
        sys.exit(f"missing {asset} - run tools/build_release.py first")
    if git("status", "--porcelain").strip():
        sys.exit("working tree not clean - commit first")
    m = re.search(r"github\.com[:/]([^/]+)/([^/.]+)", git("remote", "get-url", "origin"))
    owner, repo = m.group(1), m.group(2)
    if tag not in git("tag", "--list", tag):
        git("tag", "-a", tag, "-m", f"FalconMods {ver}")
    print(git("push", "origin", "HEAD:main", "--follow-tags") or "pushed")
    git("push", "origin", tag)
    tok = token()
    base = f"https://api.github.com/repos/{owner}/{repo}"
    rel = api("POST", base + "/releases", tok, {
        "tag_name": tag, "name": f"FalconMods {ver}", "body": changelog(ver),
        "draft": "--draft" in sys.argv, "prerelease": False})
    with open(asset, "rb") as f:
        data = f.read()
    up = rel["upload_url"].split("{")[0] + "?name=" + os.path.basename(asset)
    api("POST", up, tok, data, "application/octet-stream")
    print("release:", rel["html_url"])


if __name__ == "__main__":
    main()
