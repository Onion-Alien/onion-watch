"""Where "Send feedback" and "Report a problem" go.

Both only open a page in the user's browser: nothing is sent by the app, and the
user decides what to type and whether to submit. The feedback form needs no
account (a GitHub issue does). It's the same form as Onion Board's, so the version
it gets in the address says "Onion Watch" too."""
from __future__ import annotations

from urllib.parse import quote, urlencode

from onionwatch.updates import REPO

# the no-account feedback form (shared with Onion Board); empty = GitHub issues
FORM_URL = "https://tally.so/r/rjxjyM"
ISSUE_URL = f"https://github.com/{REPO}/issues/new"


def feedback_url(version: str) -> str:
    if FORM_URL:
        return f"{FORM_URL}?{urlencode({'version': f'Onion Watch {version}'})}"
    return problem_url(version)


def problem_url(version: str) -> str:
    """A new bug report with the version filled in."""
    body = (f"**Onion Watch version:** {version}\n"
            "\n**What happened?**\n\n\n"
            "**What did you expect?**\n\n")
    return f"{ISSUE_URL}?labels=bug&body={quote(body)}"
