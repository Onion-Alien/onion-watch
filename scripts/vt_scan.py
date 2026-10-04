"""Scan a file on VirusTotal and print the result: how many engines flagged it,
which ones and what they called it, and the link for the release notes.

    python scripts/vt_scan.py dist\\OnionWatch-Installer.exe            # scan, wait, report
    python scripts/vt_scan.py FILE --cached                        # an earlier result if VT has one
    python scripts/vt_scan.py FILE --markdown                      # also the release-notes line

Needs a (free) VirusTotal API key: the VT_API_KEY environment variable, or a line
`VT_API_KEY=<key>` in ~/.secrets/virustotal.env (outside any repo). It's never printed
or written anywhere. The free key allows 4 requests a minute, so the wait
between checks is 20 s. Standard library only.

Exit code: 0 no engine flagged it, 1 some did, 2 it couldn't scan.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

API = "https://www.virustotal.com/api/v3"
GUI = "https://www.virustotal.com/gui/file/"
POLL_S = 20
TIMEOUT_S = 30 * 60
KEY_FILE = Path.home() / ".secrets" / "virustotal.env"   # outside any repo


class VTError(Exception):
    pass


def _key() -> str:
    key = os.environ.get("VT_API_KEY", "").strip()
    if not key and KEY_FILE.is_file():
        for line in KEY_FILE.read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "VT_API_KEY":
                key = value.strip().strip('"').strip("'")
    if not key:
        raise VTError(f"no VirusTotal API key: get a free one from your VirusTotal profile "
                      f"(avatar -> API key) and put it in {KEY_FILE} as  VT_API_KEY=<key>  "
                      f"(or set the VT_API_KEY environment variable).")
    return key


def _call(method: str, url: str, body: bytes | None = None,
          headers: dict[str, str] | None = None) -> dict:
    req = urllib.request.Request(url if url.startswith("http") else API + url, data=body,
                                 method=method, headers={"x-apikey": _key(), **(headers or {})})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {}
            if e.code == 429 and attempt < 4:          # the free key's 4 a minute
                time.sleep(POLL_S * (attempt + 1))
                continue
            detail = e.read().decode("utf-8", "replace")[:300]
            raise VTError(f"VirusTotal said {e.code}: {detail}") from None
        except urllib.error.URLError as e:
            raise VTError(f"couldn't reach VirusTotal: {e.reason}") from None
    raise VTError("VirusTotal kept saying 'too many requests'")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def upload(path: Path) -> str:
    """Send the file; the analysis id. Files over 32 MB go to a one-off upload URL."""
    url = "/files"
    if path.stat().st_size > 32 * 1024 * 1024:
        url = _call("GET", "/files/upload_url")["data"]
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"{path.name}\"\r\nContent-Type: application/octet-stream\r\n\r\n"
            ).encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    r = _call("POST", url, body, {"Content-Type": f"multipart/form-data; boundary={boundary}"})
    return r["data"]["id"]


def wait(analysis_id: str) -> None:
    end = time.monotonic() + TIMEOUT_S
    while time.monotonic() < end:
        a = _call("GET", f"/analyses/{analysis_id}")["data"]["attributes"]
        if a.get("status") == "completed":
            return
        print(f"  {a.get('status', '?')}...", flush=True)
        time.sleep(POLL_S)
    raise VTError("the scan didn't finish in 30 minutes; run again with --cached later")


def report(digest: str) -> dict:
    a = _call("GET", f"/files/{digest}").get("data", {}).get("attributes")
    if not a:
        raise VTError("VirusTotal has no result for this file yet")
    return a


def summary(a: dict) -> tuple[int, int, list[str]]:
    """(flagged, engines that gave a verdict, 'Engine: name' for each flag)."""
    results = a.get("last_analysis_results", {})
    flagged = sorted(f"{k}: {v.get('result')}" for k, v in results.items()
                     if v.get("category") in ("malicious", "suspicious"))
    judged = sum(1 for v in results.values()
                 if v.get("category") in ("malicious", "suspicious", "undetected", "harmless"))
    return len(flagged), judged, flagged


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("file", type=Path)
    ap.add_argument("--cached", action="store_true",
                    help="use VirusTotal's earlier result for this file if it has one")
    ap.add_argument("--markdown", action="store_true", help="print the release-notes line")
    args = ap.parse_args(argv)
    try:
        digest = sha256(args.file)
        print(f"{args.file.name}  sha256 {digest}")
        if not (args.cached and _call("GET", f"/files/{digest}")):
            print("uploading to VirusTotal...", flush=True)
            wait(upload(args.file))
        n, total, flagged = summary(report(digest))
    except VTError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(f"{total - n} of {total} engines clean" + (": flagged by" if n else ""))
    for line in flagged:
        print(f"  {line}")
    print(GUI + digest)
    if args.markdown:
        print(f"\n[VirusTotal scan]({GUI}{digest}): {total - n} of {total} engines clean")
    return 1 if n else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
