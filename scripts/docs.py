"""Rebuild the README's and the website's pictures and release line in one go.

    .venv\\Scripts\\python scripts\\docs.py                    # pictures + version line
    .venv\\Scripts\\python scripts\\docs.py --vt <sha256> 68/68 # after a release's VirusTotal scan
    .venv\\Scripts\\python scripts\\docs.py --no-shots         # only the text

Runs screenshots.py (offscreen, made-up data, the Dark theme) and make_art.py
(Hoot, the avatar and docs/art/social-preview.png, which is built from main.png:
upload it in the repo's Settings -> Social preview when it changes; GitHub has no
API for it). The version comes from onionwatch/__init__.py; the VirusTotal scan is
remembered in docs/release.json, so it only needs passing once per release (Onion
Board's site reads it for its Onion Watch tab). The line is rewritten between the
<!-- release --> markers in README.md, and every picture link gets ?v=<hash of the
picture>, so nobody is shown an old cached copy after the pictures change.

The website is Onion Board's (its Onion Watch tab): docs/index.html only sends visitors
there. Copy new pictures into its site/screenshots/watch/ (see its scripts/docs.py).
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RELEASE = ROOT / "docs" / "release.json"
REPO = "https://github.com/Onion-Alien/onion-watch"
PAGES = [ROOT / "README.md"]


def version() -> str:
    text = (ROOT / "onionwatch" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__ = "([^"]+)"', text).group(1)


def vt_link(r: dict) -> str:
    return f"https://www.virustotal.com/gui/file/{r['vt_sha256']}"


def readme_block(r: dict) -> str:
    vt = f"VirusTotal: {r['vt_clean']} of {r['vt_total']} clean"
    return (f"Version **{r['version']}** · Windows 10 / 11 · free, no account, no internet "
            f"needed ·\n[{vt}]({vt_link(r)}) · [what's new]({REPO}/releases/latest)")


def stamp(path: Path, block: str):
    text = path.read_text(encoding="utf-8")
    new, n = re.subn(r"(<!-- release -->\n).*?(\n\s*<!-- /release -->)",
                     lambda m: m.group(1) + block + m.group(2), text, flags=re.S)
    if n != 1:
        raise SystemExit(f"{path.name}: expected one <!-- release --> block, found {n}")
    path.write_text(new, encoding="utf-8")
    print("stamped", path.relative_to(ROOT))


def bust_caches():
    """Give each picture link a ?v=<hash of the picture>, so browsers and GitHub's
    image proxy fetch a changed picture instead of showing the old one they kept."""
    def tag(m):
        pic = ROOT / "docs" / m.group(2) / m.group(3)
        if not pic.exists():
            return m.group(0)
        h = hashlib.sha1(pic.read_bytes()).hexdigest()[:8]
        return f"{m.group(1)}{m.group(2)}/{m.group(3)}?v={h}"
    for page in PAGES:
        text = page.read_text(encoding="utf-8")
        new = re.sub(r"((?:docs/)?)(screenshots|art)/([\w-]+\.png)(?:\?v=\w+)?", tag, text)
        if new != text:
            page.write_text(new, encoding="utf-8")
            print("re-linked pictures in", page.relative_to(ROOT))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vt", nargs=2, metavar=("SHA256", "CLEAN/TOTAL"),
                    help="the release installer's VirusTotal scan, e.g. --vt e241eb49... 68/68")
    ap.add_argument("--no-shots", action="store_true", help="skip the pictures")
    args = ap.parse_args()

    r = json.loads(RELEASE.read_text(encoding="utf-8"))
    if r["version"] != version() and not args.vt:
        print(f"note: VirusTotal scan is for {r['version']}; pass --vt for {version()}'s installer")
    r["version"] = version()
    if args.vt:
        clean, total = args.vt[1].split("/")
        r.update(vt_sha256=args.vt[0].lower(), vt_clean=int(clean), vt_total=int(total))
    RELEASE.write_text(json.dumps(r, indent=2) + "\n", encoding="utf-8")

    stamp(ROOT / "README.md", readme_block(r))
    if not args.no_shots:
        for script in ("screenshots.py", "make_art.py"):
            subprocess.run([sys.executable, str(ROOT / "scripts" / script)], cwd=ROOT, check=True)
    bust_caches()


if __name__ == "__main__":
    main()
