#!/usr/bin/env python3
"""One-time installer for iMessage Bridge."""

import json
import os
import shutil
import subprocess
import sys

HOME = os.path.expanduser("~")
BASE_DIR = os.path.join(HOME, ".claude", "imessage-bridge")
PLIST_DST = os.path.join(HOME, "Library", "LaunchAgents", "com.claude.imessage-bridge.plist")
MCP_JSON = os.path.join(HOME, ".claude", ".mcp.json")
ZSHRC = os.path.join(HOME, ".zshrc")
CLAUDE_MD = os.path.join(HOME, ".claude", "CLAUDE.md")

ALIAS_LINE = "alias claude='tmux new-session -A -s claude-session -- command claude'"
ALIAS_COMMENT = "# iMessage Bridge — Claude Code in tmux for iMessage injection"

CLAUDE_MD_SECTION = """
## iMessage Bridge

When you see a prompt prefixed with `[iMessage]`, it came from the user's phone
via iMessage. After completing the task, call the `imessage_reply` MCP tool with
a 2-3 line summary of what you did and the outcome (success/failure). Keep the
reply concise — it's read on a phone screen.

For `claude -p` spawned sessions: the daemon captures your output and sends a
summary automatically. You may ALSO call imessage_reply if you want to send a
richer summary.

Do NOT call imessage_reply for prompts that don't have the [iMessage] prefix —
those are normal terminal interactions.
"""


def check_prerequisites():
    """Check that tmux and pip packages are available."""
    errors = []
    if shutil.which("tmux") is None:
        errors.append("tmux not found. Install with: brew install tmux")
    if shutil.which("claude") is None:
        errors.append("claude CLI not found in PATH")
    try:
        import mcp  # noqa: F401
    except ImportError:
        errors.append("mcp package not found. Install with: pip3 install --break-system-packages mcp")
    return errors


def create_directories():
    os.makedirs(BASE_DIR, mode=0o700, exist_ok=True)
    os.makedirs(os.path.join(BASE_DIR, "logs"), mode=0o700, exist_ok=True)
    os.makedirs(os.path.join(BASE_DIR, "tests"), exist_ok=True)


def install_plist():
    """Write the launchd plist from template and load it."""
    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.claude.imessage-bridge</string>
    <key>ProgramArguments</key>
    <array>
        <string>/opt/homebrew/bin/python3</string>
        <string>{BASE_DIR}/daemon.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{BASE_DIR}/logs/daemon.log</string>
    <key>StandardErrorPath</key>
    <string>{BASE_DIR}/logs/daemon.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>HOME</key>
        <string>{HOME}</string>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
        <key>CLAUDE_CODE_USE_BEDROCK</key>
        <string>1</string>
        <key>AWS_REGION</key>
        <string>us-east-1</string>
        <key>AWS_PROFILE</key>
        <string>BedrockProfile</string>
        <key>ANTHROPIC_MODEL</key>
        <string>us.anthropic.claude-opus-4-6-v1[1m]</string>
    </dict>
</dict>
</plist>"""
    # Unload first if already loaded
    subprocess.run(["launchctl", "unload", PLIST_DST], capture_output=True)
    with open(PLIST_DST, "w") as f:
        f.write(plist_content)
    subprocess.run(["launchctl", "load", PLIST_DST], check=True)
    print(f"  Loaded launchd plist: {PLIST_DST}")


def install_mcp_json():
    """Create or update .mcp.json with imessage-bridge server."""
    mcp_entry = {
        "command": "python3",
        "args": [os.path.join(BASE_DIR, "mcp_server.py")],
    }
    if os.path.exists(MCP_JSON):
        with open(MCP_JSON) as f:
            data = json.load(f)
    else:
        data = {"mcpServers": {}}

    data.setdefault("mcpServers", {})
    data["mcpServers"]["imessage-bridge"] = mcp_entry

    with open(MCP_JSON, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    print(f"  Registered MCP server in {MCP_JSON}")


def install_alias():
    """Add tmux alias to .zshrc if not already present."""
    if os.path.exists(ZSHRC):
        with open(ZSHRC) as f:
            content = f.read()
        if ALIAS_LINE in content:
            print("  Alias already in .zshrc")
            return
    with open(ZSHRC, "a") as f:
        f.write(f"\n{ALIAS_COMMENT}\n{ALIAS_LINE}\n")
    print(f"  Added alias to {ZSHRC}")


def install_claude_md():
    """Add iMessage Bridge section to CLAUDE.md if not present."""
    if os.path.exists(CLAUDE_MD):
        with open(CLAUDE_MD) as f:
            content = f.read()
        if "iMessage Bridge" in content:
            print("  CLAUDE.md already has iMessage Bridge section")
            return
    with open(CLAUDE_MD, "a") as f:
        f.write(CLAUDE_MD_SECTION)
    print(f"  Added iMessage Bridge section to {CLAUDE_MD}")


def main():
    print("iMessage Bridge Installer")
    print("=" * 40)

    errors = check_prerequisites()
    if errors:
        print("\nPrerequisite errors:")
        for e in errors:
            print(f"  - {e}")
        print("\nFix these and re-run the installer.")
        sys.exit(1)

    print("\n1. Creating directories...")
    create_directories()

    print("2. Installing launchd plist...")
    install_plist()

    print("3. Registering MCP server...")
    install_mcp_json()

    print("4. Adding shell alias...")
    install_alias()

    print("5. Updating CLAUDE.md...")
    install_claude_md()

    print("\n" + "=" * 40)
    print("Installation complete!")
    print("\nNext steps:")
    print("  1. Grant Full Disk Access to Terminal (System Settings > Privacy & Security)")
    print("  2. Restart your terminal (to pick up the alias)")
    print("  3. Type 'claude' to start a session")
    print("  4. Text yourself from your phone to test")


if __name__ == "__main__":
    main()
