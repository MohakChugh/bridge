"""Code Review Engine — adapter checkout + static diff + parallel AI analysis.

Phase 1: Adapter (wasabi/kiro) checks out CR via CrCheckout → static git diff → parse → return files
Phase 2: Parallel sessions for auto-review, fetch comments, build check
Each user comment spawns its own session for independent parallel execution.
"""

from __future__ import annotations
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from typing import Optional

from event_bus import get_event_bus

log = logging.getLogger("code_review")


# ---- Phase 1: Checkout + Static Diff ----

def pull_cr(cr_id: str, tool: str, config: dict, session_manager) -> dict:
    """Find or create CR workspace, extract diff. Always pulls latest revision."""
    cr_num = cr_id.upper().replace("CR-", "")
    workspace = _find_workspace(cr_num)

    if workspace:
        log.info(f"Existing workspace at {workspace}, updating to latest revision")
        get_event_bus().publish("cr.phase", {"cr_id": cr_id, "phase": "pulling", "message": "Updating workspace to latest revision..."})
        _update_workspace_to_latest(cr_id, workspace)
    else:
        log.info(f"No existing workspace for {cr_id}, running cr-pull -w")
        get_event_bus().publish("cr.phase", {"cr_id": cr_id, "phase": "pulling", "message": "Running cr-pull to create workspace..."})
        workspace, pull_err = _auto_pull_cr(cr_id)
        if pull_err:
            return {"error": pull_err}

    if not workspace:
        return {"error": f"cr-pull finished but workspace not found for {cr_id}. Check cr-pull output in logs."}

    log.info(f"Found CR workspace: {workspace}")
    get_event_bus().publish("cr.phase", {"cr_id": cr_id, "phase": "extracting_diff", "workspace": workspace})

    packages, diff_text = _extract_diff_static(workspace)

    if not diff_text:
        return {
            "error": f"Workspace found at {workspace} but diff is empty. The CR branch may not have changes vs mainline.",
            "workspace": workspace,
            "packages": packages,
        }

    files = parse_unified_diff(diff_text)

    return {
        "workspace": workspace,
        "packages": packages,
        "files": files,
        "raw_diff": diff_text,
        "cr_id": cr_id,
    }


def _auto_pull_cr(cr_id: str) -> tuple[Optional[str], Optional[str]]:
    """Run cr-pull -w to create workspace. Returns (workspace_path, error_msg)."""
    from adapters.base import get_login_shell_env
    env = get_login_shell_env()
    cr_num = cr_id.upper().replace("CR-", "")

    try:
        r = subprocess.run(
            ["cr-pull", "-w", "-b", "overwrite", cr_id],
            capture_output=True, text=True, timeout=300, env=env,
        )
        log.info(f"cr-pull stdout: {r.stdout[-500:] if r.stdout else '(empty)'}")
        if r.stderr:
            log.warning(f"cr-pull stderr: {r.stderr[-500:]}")

        if r.returncode != 0:
            err_detail = r.stderr.strip() or r.stdout.strip() or "(no output)"
            return None, f"cr-pull failed (exit {r.returncode}):\n{err_detail[-500:]}"

        workspace = _find_workspace(cr_num)
        if workspace:
            return workspace, None

        ws_path = _parse_workspace_from_output(r.stdout)
        if ws_path and os.path.isdir(ws_path):
            return ws_path, None

        return None, f"cr-pull succeeded but workspace not found. Output:\n{r.stdout[-300:]}"

    except subprocess.TimeoutExpired:
        return None, "cr-pull timed out after 5 minutes. The CR may be very large."
    except FileNotFoundError:
        return None, "cr-pull command not found. Install toolbox: toolbox install cr"
    except Exception as e:
        return None, f"cr-pull error: {e}"


def _update_workspace_to_latest(cr_id: str, workspace: str) -> None:
    """Re-pull latest revision into existing workspace."""
    from adapters.base import get_login_shell_env
    env = get_login_shell_env()
    src_dir = os.path.join(workspace, "src")
    if not os.path.isdir(src_dir):
        return
    for pkg in os.listdir(src_dir):
        pkg_dir = os.path.join(src_dir, pkg)
        if not os.path.isdir(os.path.join(pkg_dir, ".git")):
            continue
        try:
            subprocess.run(
                ["cr-pull", "-b", "overwrite", cr_id],
                capture_output=True, text=True, timeout=120, cwd=pkg_dir, env=env,
            )
            log.info(f"Updated {pkg} to latest revision of {cr_id}")
        except Exception as e:
            log.warning(f"Failed to update {pkg}: {e}")


def _parse_workspace_from_output(stdout: str) -> Optional[str]:
    """Try to extract workspace path from cr-pull output."""
    for line in stdout.split("\n"):
        line = line.strip()
        if "workspace" in line.lower() and ("/" in line):
            for word in line.split():
                if word.startswith("/") and os.path.isdir(word):
                    return word
    return None


def _find_workspace(cr_num: str) -> Optional[str]:
    """Search common locations for a CR workspace. Fast exact-path checks only."""
    names = [f"CR-{cr_num}", f"cr-{cr_num}", f"cr-review-{cr_num}"]
    bridge_dir = os.path.dirname(os.path.abspath(__file__))
    bases = [
        "/tmp",
        "/private/tmp",
        bridge_dir,
        os.path.join(bridge_dir, "web"),
        os.path.expanduser("~"),
        os.getcwd(),
        "/Volumes/workspace",
    ]
    for env_key in ("BRAZIL_WORKSPACE_ROOT", "CR_WORKSPACE_DIR"):
        v = os.environ.get(env_key)
        if v and os.path.isdir(v):
            bases.insert(0, v)

    # Fast pass: exact name matches only (no directory listing)
    for base in bases:
        if not os.path.isdir(base):
            continue
        for name in names:
            candidate = os.path.join(base, name)
            if os.path.isdir(candidate) and _workspace_has_packages(candidate):
                return candidate

    # Slow pass: partial matches only on small dirs (/tmp, bridge_dir)
    small_bases = ["/tmp", "/private/tmp", bridge_dir, os.path.join(bridge_dir, "web")]
    for base in small_bases:
        if not os.path.isdir(base):
            continue
        try:
            for d in os.listdir(base):
                if cr_num in d.upper():
                    p = os.path.join(base, d)
                    if os.path.isdir(p) and _workspace_has_packages(p):
                        return p
        except (PermissionError, OSError):
            continue

    return None


def _workspace_has_packages(workspace: str) -> bool:
    src_dir = os.path.join(workspace, "src")
    if not os.path.isdir(src_dir):
        return False
    return any(os.path.isdir(os.path.join(src_dir, d)) and not d.startswith(".")
               for d in os.listdir(src_dir))


def _extract_diff_static(workspace: str) -> tuple[list[str], str]:
    """Run git diff in workspace packages. No LLM needed.

    Detects CRUX branches (cr-pull convention) and diffs against merge-base.
    """
    from adapters.base import get_login_shell_env
    env = get_login_shell_env()

    packages = []
    src_dir = os.path.join(workspace, "src")
    if os.path.isdir(src_dir):
        packages = [d for d in os.listdir(src_dir)
                    if os.path.isdir(os.path.join(src_dir, d)) and not d.startswith(".")]

    diff_text = ""

    for pkg in packages:
        pkg_dir = os.path.join(src_dir, pkg)
        if not os.path.isdir(os.path.join(pkg_dir, ".git")):
            continue

        cr_branch = _find_cr_branch(pkg_dir, env)

        if cr_branch:
            # Use merge-base for correct CR diff (mainline may have diverged)
            merge_base = _get_merge_base(pkg_dir, "mainline", cr_branch, env)
            if merge_base:
                diff_cmds = [["git", "diff", f"{merge_base}..{cr_branch}"]]
            else:
                diff_cmds = [["git", "diff", f"mainline...{cr_branch}"]]
        else:
            diff_cmds = [
                ["git", "diff", "mainline...HEAD"],
                ["git", "diff", "HEAD~1...HEAD"],
                ["git", "diff", "HEAD~1"],
            ]

        for cmd in diff_cmds:
            try:
                r = subprocess.run(cmd, capture_output=True, text=True,
                                   timeout=30, cwd=pkg_dir, env=env)
                if r.stdout.strip():
                    # Prefix file paths with package name so tree groups correctly
                    prefixed = re.sub(
                        r'(diff --git a/)(.*?)( b/)(.*)',
                        rf'\g<1>{pkg}/\2\g<3>{pkg}/\4',
                        r.stdout,
                    )
                    prefixed = re.sub(r'(--- a/)(.*)', rf'\g<1>{pkg}/\2', prefixed)
                    prefixed = re.sub(r'(\+\+\+ b/)(.*)', rf'\g<1>{pkg}/\2', prefixed)
                    diff_text += prefixed
                    log.info(f"Diff for {pkg}: {' '.join(cmd)} → {len(r.stdout)} bytes")
                    break
            except Exception:
                continue

    return packages, diff_text


def _get_merge_base(pkg_dir: str, base: str, branch: str, env: dict) -> Optional[str]:
    """Get merge-base commit between two refs."""
    try:
        r = subprocess.run(
            ["git", "merge-base", base, branch],
            capture_output=True, text=True, timeout=10, cwd=pkg_dir, env=env,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return None


def _find_cr_branch(pkg_dir: str, env: dict) -> Optional[str]:
    """Find CRUX/CR-*/r*/mainline branch in a package repo."""
    try:
        r = subprocess.run(
            ["git", "branch", "-a"],
            capture_output=True, text=True, timeout=10, cwd=pkg_dir, env=env,
        )
        for line in r.stdout.split("\n"):
            line = line.strip().lstrip("* ")
            if line.startswith("CRUX/CR-") and "/r" in line:
                return line
    except Exception:
        pass
    return None


# ---- Phase 2: Parallel AI Analysis ----

def start_analysis(cr_id: str, workspace: str, raw_diff: str, packages: list[str],
                   tool: str, config: dict, session_manager) -> dict:
    """Spawn parallel sessions for auto-review, comment fetch, and build check."""
    sessions = {}

    def _cwd():
        if packages:
            src_dir = os.path.join(workspace, "src", packages[0])
            if os.path.isdir(src_dir):
                return src_dir
        return workspace

    # 1. Auto AI Review — include exact file paths so AI uses them
    diff_files = re.findall(r'diff --git a/(.*?) b/', raw_diff)
    file_list = "\n".join(f"- {f}" for f in diff_files) if diff_files else "(see diff below)"

    # Build KB context from shared memory — search by package names + file paths
    kb_context = ""
    try:
        from shared_memory import get_shared_memory
        mem = get_shared_memory()
        search_query = " ".join(packages) + " " + " ".join(
            os.path.splitext(os.path.basename(f))[0] for f in diff_files[:5]
        )
        results = mem.search(search_query, limit=10)
        if results:
            kb_parts = []
            total_chars = 0
            for r in results:
                if r.get("score", 0) < 0.15:
                    continue
                chunk = f"[{r.get('collection', 'unknown')}] {r.get('text', '')[:500]}"
                if total_chars + len(chunk) > 4000:
                    break
                kb_parts.append(chunk)
                total_chars += len(chunk)
            if kb_parts:
                kb_context = (
                    "KNOWLEDGE BASE CONTEXT (from team's documentation, design docs, past reviews):\n"
                    + "\n---\n".join(kb_parts)
                    + "\n\nUse this context to give more informed, team-specific review feedback.\n\n"
                )
    except Exception as e:
        log.debug(f"KB context injection skipped: {e}")

    review_prompt = (
        "You are an expert code reviewer. Review this diff and find issues.\n\n"
        f"{kb_context}"
        f"Changed files:\n{file_list}\n\n"
        "INSTRUCTIONS:\n"
        "1. Find bugs, security issues, performance problems, error handling gaps\n"
        "2. For each issue, identify the exact file path and line number\n"
        "3. Use knowledge base context to understand team conventions and flag deviations\n"
        "4. Respond with ONLY a JSON object in this exact format (no other text):\n\n"
        "```json\n"
        "{\"reviews\": [\n"
        "  {\"file\": \"exact/file/path.java\", \"line\": 42, \"severity\": \"error\", "
        "\"comment\": \"Description of the issue\", \"suggestion\": \"How to fix it\"}\n"
        "]}\n"
        "```\n\n"
        "Use file paths EXACTLY as listed above. severity must be error, warning, or info.\n"
        "If no issues found, return: {\"reviews\": []}\n\n"
        f"DIFF:\n{raw_diff[:20000]}"
    )
    s1 = session_manager.create(tool=tool, cwd=_cwd(), title=f"CR {cr_id}: Auto Review",
                                meta={"preserve_output": True})
    session_manager.execute(s1.id, review_prompt)
    sessions["auto_review"] = s1.id

    # 2. CR comment fetching now handled by dedicated fetch_cr_comments() auto-trigger
    # 3. Build check removed — cr-pull workspaces lack full dependency setup,
    #    causing false failures. Build status is available on code.amazon.com.

    get_event_bus().publish("cr.analysis.started", {"cr_id": cr_id, "sessions": sessions})
    return sessions


def fetch_cr_comments(cr_id: str, tool: str, workspace: str, packages: list[str],
                      config: dict, session_manager) -> str:
    """Fetch existing CR comments via wasabi ReadInternalWebsites. Returns session_id."""
    cwd = workspace
    if packages:
        src_dir = os.path.join(workspace, "src", packages[0])
        if os.path.isdir(src_dir):
            cwd = src_dir

    s = session_manager.create(tool=tool, cwd=cwd, title=f"CR {cr_id}: Fetch Comments",
                               meta={"preserve_output": True})

    prompt = (
        f"Read the code review page at code.amazon.com/reviews/{cr_id}?include-all-comments=true "
        f"using ReadInternalWebsites.\n\n"
        f"IMPORTANT: Find the HIGHEST revision number on this CR. Only extract comments "
        f"that belong to that latest revision. Ignore all comments from older revisions.\n\n"
        f"Skip automated bot comments (CoverlayWorker, AutoSDE, GoodCopWorker) — "
        f"only include human reviewer comments.\n\n"
        f"Return this EXACT JSON format:\n"
        f'{{"comments": [\n'
        f'  {{\n'
        f'    "author": "user_alias",\n'
        f'    "content": "the comment body (markdown)",\n'
        f'    "created_at": "ISO-8601 timestamp",\n'
        f'    "fixed": false,\n'
        f'    "location": "v4:PackageName:path/to/file.java::startLine::endLine:",\n'
        f'    "revision": 3\n'
        f'  }}\n'
        f']}}\n\n'
        f"RULES:\n"
        f"- author: the user alias string (e.g. \"chumohak\", \"lakshmu\")\n"
        f"- location: EXACTLY as in the CR data. \"TOP\" for general comments, "
        f"\"v4:<Package>:<filePath>::<startLine>::<endLine>:\" for inline\n"
        f"- ONLY latest revision — check revision numbers, pick highest\n"
        f"- ONLY human comments — skip CoverlayWorker, AutoSDE, GoodCopWorker\n"
        f"- Include ALL human comments for that revision (not just a summary)\n"
        f"- Return ONLY the JSON object, nothing else"
    )

    session_manager.execute(s.id, prompt)
    return s.id


def parse_cr_comments_structured(output: str, diff_files: list[str]) -> list[dict]:
    """Parse structured CR comments from wasabi output into UI-ready format.

    Handles multiple response formats robustly:
    - {"comments": [...]} wrapper
    - Raw JSON array [...]
    - Comments embedded in markdown code blocks
    - Mixed text + JSON
    """
    if not output or not output.strip():
        return []

    comments_raw = []

    # Try 1: standard JSON extraction
    data = _extract_json(output)
    if data:
        if isinstance(data, dict):
            comments_raw = data.get("comments", data.get("data", []))
        elif isinstance(data, list):
            comments_raw = data

    # Try 2: find JSON array directly
    if not comments_raw:
        arr_start = output.find("[")
        arr_end = output.rfind("]")
        if arr_start >= 0 and arr_end > arr_start:
            try:
                comments_raw = json.loads(output[arr_start:arr_end + 1])
            except (json.JSONDecodeError, ValueError):
                pass

    # Try 3: extract from markdown code block
    if not comments_raw:
        m = re.search(r'```(?:json)?\s*\n(.*?)\n```', output, re.DOTALL)
        if m:
            try:
                parsed = json.loads(m.group(1))
                if isinstance(parsed, list):
                    comments_raw = parsed
                elif isinstance(parsed, dict):
                    comments_raw = parsed.get("comments", [])
            except (json.JSONDecodeError, ValueError):
                pass

    if not comments_raw:
        log.warning(f"Could not parse CR comments from output ({len(output)} chars)")
        return []

    parsed = []
    for c in comments_raw:
        location = c.get("location", "TOP")
        file_path = ""
        line_num = 0

        if location and location != "TOP" and location.startswith("v4:"):
            parts = location.split("::")
            if len(parts) >= 2:
                try:
                    line_num = int(parts[1])
                except (ValueError, IndexError):
                    pass
            # Extract file path: v4:Package:path/to/file → path/to/file
            loc_prefix = parts[0] if parts else location
            segments = loc_prefix.split(":", 2)
            if len(segments) >= 3:
                file_path = segments[2]

        # Normalize file path to match diff files
        matched = None
        if file_path:
            for df in diff_files:
                if df == file_path or df.endswith(file_path) or file_path.endswith(df):
                    matched = df
                    break
                fname = file_path.split("/")[-1] if "/" in file_path else file_path
                if fname and df.endswith(fname):
                    matched = df
                    break

        parsed.append({
            "author": c.get("author", "unknown"),
            "content": c.get("content", ""),
            "file": matched or file_path,
            "line": line_num,
            "fixed": c.get("fixed", False),
            "importance": c.get("importance", 0),
            "location_raw": location,
            "parent": c.get("parent"),
            "post": c.get("post"),
            "revision": c.get("revision"),
        })

    return parsed


def spawn_comment_session(cr_id: str, workspace: str, packages: list[str],
                          tool: str, file_path: str, line_num: int,
                          line_content: str, question: str,
                          config: dict, session_manager) -> str:
    """Each user comment gets its own independent session."""
    cwd = workspace
    if packages:
        src_dir = os.path.join(workspace, "src", packages[0])
        if os.path.isdir(src_dir):
            cwd = src_dir

    s = session_manager.create(
        tool=tool, cwd=cwd,
        title=f"CR {cr_id}: Q on {os.path.basename(file_path)}:{line_num}",
        meta={"preserve_output": True},
    )

    prompt = (
        f"Question about code in this workspace.\n"
        f"File: {file_path}\nLine {line_num}: {line_content}\n\n"
        f"Question: {question}\n\n"
        f"Full workspace access. Read files as needed. Thorough answer."
    )

    session_manager.execute(s.id, prompt)
    return s.id


def spawn_chat_session(cr_id: str, workspace: str, packages: list[str],
                       tool: str, question: str,
                       config: dict, session_manager) -> str:
    """General question about the CR — own session."""
    cwd = workspace
    if packages:
        src_dir = os.path.join(workspace, "src", packages[0])
        if os.path.isdir(src_dir):
            cwd = src_dir

    s = session_manager.create(tool=tool, cwd=cwd, title=f"CR {cr_id}: Chat",
                               meta={"preserve_output": True})
    session_manager.execute(s.id, question)
    return s.id


def get_session_result(session_id: str, session_manager) -> dict:
    """Poll a session for its result."""
    s = session_manager.get(session_id)
    if not s:
        return {"status": "not_found"}
    return {"status": s.status, "output": s.last_output, "error": s.last_error}


def parse_auto_review(output: str) -> list[dict]:
    data = _extract_json(output)
    return data.get("reviews", []) if data else []


def parse_cr_comments(output: str) -> list[dict]:
    data = _extract_json(output)
    return data.get("comments", []) if data else []


# ---- Cleanup ----

def cleanup_cr(workspace: str, session_ids: list[str], session_manager):
    for sid in session_ids:
        try:
            session_manager.delete(sid)
        except Exception:
            pass
    if workspace and workspace.startswith("/tmp/cr-") and os.path.isdir(workspace):
        shutil.rmtree(workspace, ignore_errors=True)


# ---- Helpers ----

def _extract_json(text: str) -> Optional[dict]:
    if not text:
        return None

    # Strip wasabi pipe-prefix code fences (│ json)
    cleaned = re.sub(r'^[│|]\s*json\s*$', '', text, flags=re.MULTILINE)

    for pat in [r'```json\s*\n(.*?)\n```', r'```\s*\n(\{.*?\})\n```']:
        m = re.search(pat, cleaned, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except (json.JSONDecodeError, ValueError):
                continue

    start = cleaned.find('{')
    end = cleaned.rfind('}')
    if start >= 0 and end > start:
        raw = cleaned[start:end + 1]
        # Try direct parse first
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            pass
        # Fix line-wrapped JSON: collapse newlines inside strings
        # Replace unescaped newlines with \\n to make valid JSON
        fixed = re.sub(r'(?<=": ")(.*?)(?=")', lambda m: m.group(0).replace('\n', '\\n'), raw, flags=re.DOTALL)
        try:
            return json.loads(fixed)
        except (json.JSONDecodeError, ValueError):
            pass
        # Last resort: join all lines and normalize whitespace
        joined = re.sub(r'\n\s*', ' ', raw)
        joined = re.sub(r',\s*}', '}', joined)
        joined = re.sub(r',\s*]', ']', joined)
        try:
            return json.loads(joined)
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def parse_unified_diff(diff_text: str) -> list[dict]:
    if not diff_text:
        return []

    files: list[dict] = []
    current_file: Optional[dict] = None
    current_hunk: Optional[dict] = None

    for line in diff_text.split('\n'):
        if line.startswith('diff --git'):
            if current_file:
                if current_hunk:
                    current_file["hunks"].append(current_hunk)
                files.append(current_file)
            m = re.match(r'diff --git a/(.*?) b/(.*)', line)
            path = m.group(2) if m else line
            ext = os.path.splitext(path)[1].lstrip('.')
            current_file = {
                "path": path, "ext": ext, "language": _ext_to_language(ext),
                "hunks": [], "additions": 0, "deletions": 0, "status": "modified",
            }
            current_hunk = None

        elif line.startswith('new file') and current_file:
            current_file["status"] = "added"
        elif line.startswith('deleted file') and current_file:
            current_file["status"] = "deleted"
        elif line.startswith('rename from') and current_file:
            current_file["status"] = "renamed"
            current_file["old_path"] = line[len("rename from "):]

        elif line.startswith('@@'):
            if current_file and current_hunk:
                current_file["hunks"].append(current_hunk)
            m = re.match(r'@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)', line)
            current_hunk = {
                "header": line,
                "old_start": int(m.group(1)) if m else 1,
                "new_start": int(m.group(2)) if m else 1,
                "context": m.group(3).strip() if m else "",
                "lines": [],
            }

        elif current_hunk is not None:
            if line.startswith('+') and not line.startswith('+++'):
                current_hunk["lines"].append({"type": "add", "content": line[1:]})
                if current_file:
                    current_file["additions"] += 1
            elif line.startswith('-') and not line.startswith('---'):
                current_hunk["lines"].append({"type": "del", "content": line[1:]})
                if current_file:
                    current_file["deletions"] += 1
            elif line.startswith('\\'):
                continue
            else:
                content = line[1:] if line.startswith(' ') else line
                current_hunk["lines"].append({"type": "ctx", "content": content})

    if current_file:
        if current_hunk:
            current_file["hunks"].append(current_hunk)
        files.append(current_file)

    for f in files:
        for hunk in f["hunks"]:
            old_num, new_num = hunk["old_start"], hunk["new_start"]
            for ln in hunk["lines"]:
                if ln["type"] == "add":
                    ln["new_num"] = new_num
                    ln["old_num"] = None
                    new_num += 1
                elif ln["type"] == "del":
                    ln["old_num"] = old_num
                    ln["new_num"] = None
                    old_num += 1
                else:
                    ln["old_num"] = old_num
                    ln["new_num"] = new_num
                    old_num += 1
                    new_num += 1

    return files


def _ext_to_language(ext: str) -> str:
    return {
        "py": "python", "js": "javascript", "ts": "typescript",
        "tsx": "tsx", "jsx": "jsx", "java": "java", "kt": "kotlin",
        "go": "go", "rs": "rust", "rb": "ruby", "sh": "bash",
        "yml": "yaml", "yaml": "yaml", "json": "json", "xml": "xml",
        "html": "html", "css": "css", "scss": "scss", "md": "markdown",
        "sql": "sql", "tf": "hcl", "ion": "ion", "toml": "toml",
        "gradle": "groovy", "smithy": "smithy", "cfg": "ini",
    }.get(ext, ext or "plaintext")
