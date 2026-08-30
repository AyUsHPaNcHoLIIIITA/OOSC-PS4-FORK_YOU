"""GitHub Ship-Gate integration.

Turns the AgentCI gate verdict into a real GitHub event so a live audience can
SEE the merge gate fire, not just read a YAML snippet:

* posts a **commit status** (context ``agentci/reliability-gate``) — ``success``
  when the gate passes, ``failure`` when it blocks. If the PR's branch has that
  status as a *required check*, GitHub itself locks/unlocks the merge button.
* optionally **merges the PR** directly when the gate passes and
  ``merge_on_pass`` is set (for demos without branch protection).

Security:
* The GitHub token is read from the server env (``GITHUB_TOKEN``) ONLY. It is
  never accepted from the request body and never logged (masked via safe_error).
* owner / repo / sha / branch are user-supplied and land in the URL path, so
  each is validated against a strict allowlist before use.
* All calls go to a single fixed host (api.github.com over https).
"""
import os
import re
from typing import Any, Dict, Optional

from app.llm_utils import httpx, safe_error

GITHUB_API = "https://api.github.com"
STATUS_CONTEXT = "agentci/reliability-gate"

_OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
_REPO_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")


class GitHubGateError(ValueError):
    """A GitHub gate config is invalid, or the GitHub API rejected the call."""


def is_github_configured() -> bool:
    """True when a server-side GITHUB_TOKEN is available to post statuses."""
    return bool(os.environ.get("GITHUB_TOKEN"))


def _validate(owner: str, repo: str, sha: str) -> None:
    if not _OWNER_RE.match(owner or ""):
        raise GitHubGateError("Invalid GitHub owner.")
    if not _REPO_RE.match(repo or ""):
        raise GitHubGateError("Invalid GitHub repo.")
    if not _SHA_RE.match(sha or ""):
        raise GitHubGateError("Invalid commit SHA (expected 7-40 hex chars).")


def _describe(gate: Dict[str, Any], overall: Optional[int], status: Optional[str]) -> str:
    """A short (<=140 char) status description GitHub shows next to the check."""
    if gate.get("pass"):
        base = f"PASS · score {overall}/100 · {status}" if overall is not None else "PASS · merge allowed"
    else:
        reasons = gate.get("blocking_reasons") or []
        first = reasons[0] if reasons else (status or "gate blocked")
        base = f"BLOCK · {first}"
    return base[:140]


async def sync_gate_to_github(
    *,
    owner: str,
    repo: str,
    sha: str,
    gate: Dict[str, Any],
    overall_score: Optional[int] = None,
    safety_status: Optional[str] = None,
    pr_number: Optional[int] = None,
    merge_on_pass: bool = False,
) -> Dict[str, Any]:
    """Post the gate verdict to GitHub as a commit status, optionally merging the
    PR when the gate passes. Returns a secret-free summary of what happened.

    Never raises for a *missing* token — returns ``posted: False`` so a demo can
    degrade gracefully; only raises GitHubGateError for bad input so the caller
    can surface a clean 4xx."""
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return {"posted": False, "reason": "GITHUB_TOKEN is not set on the server."}

    _validate(owner, repo, sha)
    passed = bool(gate.get("pass"))
    state = "success" if passed else "failure"
    description = _describe(gate, overall_score, safety_status)

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    result: Dict[str, Any] = {
        "posted": False,
        "state": state,
        "context": STATUS_CONTEXT,
        "description": description,
        "merged": False,
    }

    # api.github.com is a fixed public host; no SSRF transport needed here.
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
        try:
            status_resp = await client.post(
                f"{GITHUB_API}/repos/{owner}/{repo}/statuses/{sha}",
                headers=headers,
                json={
                    "state": state,
                    "context": STATUS_CONTEXT,
                    "description": description,
                    "target_url": os.environ.get("APP_PUBLIC_URL", ""),
                },
            )
            if status_resp.status_code >= 400:
                raise GitHubGateError(
                    f"GitHub status API returned {status_resp.status_code}: {status_resp.text[:200]}"
                )
            result["posted"] = True

            # Only merge when explicitly asked AND the gate passed AND we have a PR.
            if merge_on_pass and passed and pr_number is not None:
                merge_resp = await client.put(
                    f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{int(pr_number)}/merge",
                    headers=headers,
                    json={"merge_method": "squash",
                          "commit_title": f"AgentCI: reliability gate passed ({description})"},
                )
                if merge_resp.status_code >= 400:
                    result["merge_error"] = (
                        f"GitHub merge API returned {merge_resp.status_code}: {merge_resp.text[:200]}"
                    )
                else:
                    result["merged"] = True
        except GitHubGateError:
            raise
        except Exception as e:  # network / unexpected — mask the token in the message
            raise GitHubGateError(safe_error(e, token))

    return result
