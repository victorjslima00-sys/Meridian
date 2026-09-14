"""
Pre-Tool Execution Guardrail for Antigravity (Meridian Nexus Governance)

Enforces non-negotiable safety policies:
1. Git Force Push: Blocks git push --force, -f, --force-with-lease, +refspecs
2. Git Direct Push to Main: Blocks direct push targeting main and refs/heads/main
3. Git Remote Branch Deletion: Blocks remote deletion of main and refs/heads/main (:main, :refs/heads/main, --delete, -d)
4. Git Destructive Reset: Blocks git reset --hard across all target variations
5. Git Destructive Clean: Blocks git clean with force flags (-f, -fdx, --force)
6. Git Protected Branch Deletion: Blocks local branch deletion of main and refs/heads/main
7. Live Broker Activation: Blocks flags/variables triggering real broker trading
8. Unauthorized Production Deploy: Blocks terraform apply, kubectl apply, aws ecs update-service across global flags
9. Fail-Closed Payload Guard: Blocks empty, malformed, or structurally invalid tool payloads
10. Deterministic Secret Guard:
    - view_file: returns force_ask on credential files (.env, .env.*, *.pem, id_rsa, id_ed25519, private keys, secrets/)
    - write_to_file / replace_file_content: returns deny on credential files
    - .env.example: explicitly allowed for view and edit
    - run_command: blocks direct shell access to sensitive secret files
11. Everyday Development Operations: Transparently allows safe testing, feature branch push, and safe non-command tools.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import shlex
import sys

PROHIBITED_PATTERNS = [
    # 1. Force push
    (
        re.compile(
            r"\bgit\b.*?\bpush\b.*(\s--force\b|\s-f\b|\s--force-with-lease\b|\s--force-if-includes\b|\s\+[a-zA-Z0-9_./:]+)",
            re.IGNORECASE,
        ),
        "[NEXUS GUARD] Force push is strictly prohibited by Nexus Directive 000 Git Governance.",
    ),
    # 2. Remote deletion of main
    (
        re.compile(
            r"\bgit\b.*?\bpush\b.*?(?:--delete\b.*?(?:refs/heads/)?main\b|\s-d\b.*?(?:refs/heads/)?main\b|\s:+(?:refs/heads/)?main\b)",
            re.IGNORECASE,
        ),
        "[NEXUS GUARD] Remote deletion of main branch is strictly prohibited.",
    ),
    # 3. Direct push to main
    (
        re.compile(
            r"\bgit\b.*?\bpush\b.*?(?:\s(?:refs/heads/)?main\b|\S+:(?:refs/heads/)?main\b)",
            re.IGNORECASE,
        ),
        "[NEXUS GUARD] Direct push to main branch is strictly prohibited. Work must proceed via dedicated directive branches.",
    ),
    # 4. Destructive git reset --hard
    (
        re.compile(r"\bgit\b.*?\breset\b.*?\s--hard\b", re.IGNORECASE),
        "[NEXUS GUARD] Destructive git reset --hard is strictly prohibited by Nexus Directive 000 Git Governance.",
    ),
    # 5. Destructive git clean
    (
        re.compile(
            r"\bgit\b.*?\bclean\b.*?(?:-[a-zA-Z]*f[a-zA-Z]*\b|--force\b)",
            re.IGNORECASE,
        ),
        "[NEXUS GUARD] Destructive git clean is blocked. Working tree must be preserved.",
    ),
    # 6. Local branch deletion of main
    (
        re.compile(r"\bgit\b.*?\bbranch\b.*?\s-(?:d|D)\s+(?:refs/heads/)?main\b", re.IGNORECASE),
        "[NEXUS GUARD] Deletion of main branch is strictly prohibited.",
    ),
    # 7. Live broker command line triggers
    (
        re.compile(
            r"(--live-broker\b|\bLIVE_BROKER=1\b|\bCEDRO_PRODUCTION=1\b|--broker-live\b|\bMT5_LIVE=1\b)",
            re.IGNORECASE,
        ),
        "[NEXUS GUARD] Live broker operations are blocked. Invariant real_broker_calls == 0 must be preserved.",
    ),
    # 8. Unauthorized production deploy (order-independent flags)
    (
        re.compile(
            r"(\bterraform\b.*?\bapply\b.*(-auto-approve|\bprod|\bproduction)|\bterraform\b.*?\b(prod|\bproduction)\b.*?\bapply\b|\bkubectl\b.*?\bapply\b.*?\b(prod|production)\b|\bkubectl\b.*?\b(prod|production)\b.*?\bapply\b|\baws\b.*?\becs\b.*?\bupdate-service\b.*?\b(prod|production)\b|\baws\b.*?\b(prod|production)\b.*?\becs\b.*?\bupdate-service\b|\b(deploy_prod|deploy_production)\b)",
            re.IGNORECASE,
        ),
        "[NEXUS GUARD] Direct production deploy commands are blocked under Nexus generic directives.",
    ),
]


def classify_file_path(raw_path: str) -> str:
    """Classify a file path as 'example', 'secret', or 'safe'."""
    cleaned = raw_path.strip().replace("\\", "/").strip("'\"")
    if not cleaned:
        return "safe"
    norm_str = cleaned.lower()
    filename = Path(cleaned).name.lower()

    # 1. Safe exception: .env.example
    if filename == ".env.example" or norm_str.endswith(".env.example"):
        return "example"

    # 2. .env and .env.* (e.g., .env.local, .env.production, .env.staging)
    if filename == ".env" or filename.startswith(".env."):
        return "secret"

    # 3. Certificate and key extensions
    if filename.endswith((".pem", ".p12", ".pkcs12", ".key")):
        return "secret"

    # 4. SSH private keys
    if filename in ("id_rsa", "id_ed25519", "id_ecdsa", "id_dsa"):
        return "secret"
    if (filename.startswith(("id_rsa.", "id_ed25519.", "id_ecdsa.", "id_dsa."))
            and not filename.endswith(".pub")):
        return "secret"

    # 5. Explicit secrets directory or private key filenames
    if "/secrets/" in norm_str or norm_str.startswith("secrets/") or norm_str.endswith("/secrets") or norm_str == "secrets":
        return "secret"
    if "private_key" in filename or "privatekey" in filename:
        return "secret"

    return "safe"


def is_protected_main_ref(ref: str) -> bool:
    """Check if a ref targets the protected main branch."""
    clean = ref.strip().lstrip("+")
    return clean == "main" or clean == "refs/heads/main" or clean.startswith("refs/heads/main")


def evaluate_structured_git(tokens: list[str]) -> dict[str, str] | None:
    """Structured semantic analyzer for Git commands to close ref bypasses."""
    # Locate git executable in tokens
    git_idx = -1
    for idx, token in enumerate(tokens):
        norm = token.lower().replace("\\", "/")
        if norm == "git" or norm.endswith("/git") or norm == "git.exe" or norm.endswith("/git.exe"):
            git_idx = idx
            break
    if git_idx == -1:
        return None

    # Parse subcommand after git, skipping global git options
    subcmd = None
    subcmd_idx = -1
    idx = git_idx + 1
    options_with_args = {"-c", "-C", "--git-dir", "--work-tree", "--namespace", "--super-prefix", "--exec-path"}
    while idx < len(tokens):
        tok = tokens[idx]
        if tok in options_with_args:
            idx += 2
            continue
        if any(tok.startswith(f"{opt}=") for opt in options_with_args):
            idx += 1
            continue
        if tok.startswith("-"):
            idx += 1
            continue
        subcmd = tok.lower()
        subcmd_idx = idx
        break

    if not subcmd or subcmd_idx == -1:
        return None

    subcmd_args = tokens[subcmd_idx + 1:]

    # 1. git push analysis
    if subcmd == "push":
        # Check force flags
        for arg in subcmd_args:
            if arg in ("--force", "-f", "--force-with-lease", "--force-if-includes"):
                return {
                    "decision": "deny",
                    "reason": "[NEXUS GUARD] Force push is strictly prohibited by Nexus Directive 000 Git Governance.",
                }
            if arg.startswith("--force-with-lease") or arg.startswith("--force-if-includes"):
                return {
                    "decision": "deny",
                    "reason": "[NEXUS GUARD] Force push is strictly prohibited by Nexus Directive 000 Git Governance.",
                }
            if arg.startswith("+") and len(arg) > 1 and not arg.startswith("++"):
                return {
                    "decision": "deny",
                    "reason": "[NEXUS GUARD] Force push (+refspec) is strictly prohibited by Nexus Directive 000 Git Governance.",
                }

        # Check delete flags
        is_delete = any(arg in ("--delete", "-d") for arg in subcmd_args)
        for arg in subcmd_args:
            if arg in ("--delete", "-d"):
                continue
            # Refspecs with :
            if ":" in arg:
                src, dst = arg.split(":", 1)
                dst_clean = dst.strip().lstrip("+")
                if is_protected_main_ref(dst_clean):
                    if src == "":
                        return {
                            "decision": "deny",
                            "reason": "[NEXUS GUARD] Remote deletion of main branch is strictly prohibited.",
                        }
                    return {
                        "decision": "deny",
                        "reason": "[NEXUS GUARD] Direct push to main branch is strictly prohibited. Work must proceed via dedicated directive branches.",
                    }
            elif is_protected_main_ref(arg):
                if is_delete:
                    return {
                        "decision": "deny",
                        "reason": "[NEXUS GUARD] Remote deletion of main branch is strictly prohibited.",
                    }
                return {
                    "decision": "deny",
                    "reason": "[NEXUS GUARD] Direct push to main branch is strictly prohibited. Work must proceed via dedicated directive branches.",
                }

    # 2. git branch analysis
    if subcmd == "branch":
        is_delete_branch = any(arg in ("-d", "-D", "--delete") for arg in subcmd_args)
        if is_delete_branch:
            for arg in subcmd_args:
                if arg in ("-d", "-D", "--delete"):
                    continue
                if is_protected_main_ref(arg):
                    return {
                        "decision": "deny",
                        "reason": "[NEXUS GUARD] Deletion of main branch is strictly prohibited.",
                    }

    # 3. git reset analysis
    if subcmd == "reset":
        if any(arg == "--hard" for arg in subcmd_args):
            return {
                "decision": "deny",
                "reason": "[NEXUS GUARD] Destructive git reset --hard is strictly prohibited by Nexus Directive 000 Git Governance.",
            }

    # 4. git clean analysis
    if subcmd == "clean":
        for arg in subcmd_args:
            if arg in ("-n", "--dry-run"):
                continue
            if arg == "--force" or re.match(r"^-[a-zA-Z]*f[a-zA-Z]*$", arg):
                return {
                    "decision": "deny",
                    "reason": "[NEXUS GUARD] Destructive git clean is blocked. Working tree must be preserved.",
                }

    return None


def evaluate_command(command_line: str) -> dict[str, str]:
    cmd = command_line.strip()
    if not cmd:
        return {
            "decision": "deny",
            "reason": "[NEXUS GUARD] Empty command string rejected.",
        }

    # First pass: Structured Git analysis
    # Split composite command lines (&&, ||, ;, |)
    subparts = re.split(r"&&|\|\||;|\|", cmd)
    for part in subparts:
        part_str = part.strip()
        if not part_str:
            continue
        try:
            tokens = shlex.split(part_str, posix=False)
        except Exception:
            tokens = part_str.split()
        git_res = evaluate_structured_git(tokens)
        if git_res:
            return git_res

    # Second pass: Regex patterns (defense-in-depth)
    for pattern, reason in PROHIBITED_PATTERNS:
        if pattern.search(cmd):
            return {
                "decision": "deny",
                "reason": reason,
            }

    # Third pass: Shell command secret access check
    shell_file_op = re.compile(
        r"(?:\bcat\b|\btype\b|\bGet-Content\b|\bhead\b|\btail\b|\brm\b|\bdel\b|\bcp\b|\bcopy\b|\bmv\b|\bmove\b|\becho\b.*?>)\s*",
        re.IGNORECASE,
    )
    if shell_file_op.search(cmd):
        tokens = [t.strip("'\"") for t in re.split(r"\s+|[|><;]", cmd) if t.strip("'\"")]
        for tok in tokens:
            cls = classify_file_path(tok)
            if cls == "secret":
                return {
                    "decision": "deny",
                    "reason": f"[NEXUS GUARD] Direct shell access to sensitive credentials ('{tok}') is strictly prohibited.",
                }

    return {
        "decision": "allow",
        "reason": "Standard safe development operation.",
    }


def main() -> None:
    try:
        raw_input = sys.stdin.read()
        if not raw_input or not raw_input.strip():
            print(json.dumps({
                "decision": "deny",
                "reason": "[NEXUS GUARD] Empty input payload rejected. Fail-closed enforced.",
            }))
            return

        payload = json.loads(raw_input)
        if not isinstance(payload, dict):
            print(json.dumps({
                "decision": "deny",
                "reason": "[NEXUS GUARD] Payload must be a JSON object. Fail-closed enforced.",
            }))
            return

        tool_call = payload.get("toolCall")
        if not isinstance(tool_call, dict):
            print(json.dumps({
                "decision": "deny",
                "reason": "[NEXUS GUARD] Missing or invalid toolCall object. Fail-closed enforced.",
            }))
            return

        tool_name = tool_call.get("name", "")
        args = tool_call.get("args")
        if not isinstance(args, dict):
            print(json.dumps({
                "decision": "deny",
                "reason": f"[NEXUS GUARD] Tool '{tool_name}' missing args object. Fail-closed enforced.",
            }))
            return

        # 1. run_command
        if tool_name == "run_command":
            cmd_line = args.get("CommandLine")
            if not isinstance(cmd_line, str):
                print(json.dumps({
                    "decision": "deny",
                    "reason": "[NEXUS GUARD] run_command missing CommandLine argument. Fail-closed enforced.",
                }))
                return
            result = evaluate_command(cmd_line)
            print(json.dumps(result))
            return

        # 2. view_file: Force ask on sensitive secrets; allow example templates
        if tool_name == "view_file":
            target_path = (args.get("AbsolutePath") or args.get("TargetFile") or args.get("path") or "")
            classification = classify_file_path(str(target_path))
            if classification == "secret":
                print(json.dumps({
                    "decision": "force_ask",
                    "reason": f"[NEXUS GUARD] Reading sensitive credential file '{target_path}' requires explicit executive authorization.",
                }))
                return
            print(json.dumps({
                "decision": "allow",
                "reason": "Standard safe file view.",
            }))
            return

        # 3. write_to_file, replace_file_content, multi_replace_file_content
        if tool_name in ("write_to_file", "replace_file_content", "multi_replace_file_content"):
            target_path = (args.get("TargetFile") or args.get("AbsolutePath") or args.get("path") or "")
            classification = classify_file_path(str(target_path))
            if classification == "secret":
                print(json.dumps({
                    "decision": "deny",
                    "reason": f"[NEXUS GUARD] Writing or modifying sensitive credential file '{target_path}' is strictly prohibited.",
                }))
                return
            print(json.dumps({
                "decision": "allow",
                "reason": "Standard safe file edit.",
            }))
            return

        # 4. Other safe non-command tools
        print(json.dumps({
            "decision": "allow",
            "reason": "Non-command tool allowed.",
        }))
    except Exception as exc:
        print(json.dumps({
            "decision": "deny",
            "reason": f"[NEXUS GUARD] Hook error: {exc}",
        }))


if __name__ == "__main__":
    main()
