#!/usr/bin/env python3
"""Validate Wapliss WhatsApp for Grok (Grok Build plugin).

Mirrors what Grok Build and xai-org/plugin-marketplace check (manifest name rule, .mcp.json
transport fields, skills) plus the marketplace review guidance (brand-scoped keywords, no secrets,
no hooks). Created by netdigitaltech.

  python3 scripts/validate.py          # static checks
  python3 scripts/validate.py --live   # + public endpoint and OAuth metadata
"""
import json, pathlib, re, struct, sys, urllib.error, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
FAIL = []
# Grok Build manifest rule (xai-grok-agent/src/plugins/manifest.rs): 1-64 chars, lowercase
# alphanumeric + hyphens, no leading/trailing hyphens.
NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")
# Known keys of an MCP server entry (xai-grok-config/src/mcp_server_config.rs).
MCP_KEYS = {"type", "url", "enabled", "headers", "oauth", "startup_timeout_sec", "tool_timeout_sec", "tool_timeouts"}
GENERIC = {"whatsapp", "mcp", "chat", "messages", "messaging", "sms", "api", "ai"}
TOOLS = {"send_text_message", "send_image", "send_document", "send_audio", "send_video", "send_location",
         "send_contact", "send_poll", "forward_messages", "get_chats", "get_chat_history", "get_message",
         "get_last_incoming_messages", "get_last_outgoing_messages", "get_group", "get_account_status"}


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond or extra == "" else f"  -> {extra}"))
    if not cond:
        FAIL.append(name)


def static():
    mp = ROOT / ".grok-plugin" / "plugin.json"
    check(".grok-plugin/plugin.json present", mp.is_file())
    check("no competing root plugin.json", not (ROOT / "plugin.json").exists())
    m = json.loads(mp.read_text(encoding="utf-8"))
    name = m.get("name", "")
    check("name: 1-64 chars, lowercase, hyphens, no leading/trailing hyphen", bool(NAME_RE.match(name)), name)
    check("version is SemVer", bool(SEMVER.match(m.get("version", ""))), m.get("version"))
    check("description is clear (>= 80 chars)", len(m.get("description", "").strip()) >= 80)
    a = m.get("author", {})
    check("author.name netdigitaltech, no email", a.get("name") == "netdigitaltech" and "email" not in a, a)
    check("homepage on wapliss.com", str(m.get("homepage", "")).startswith("https://wapliss.com/"))
    check("repository is the public GitHub repo", m.get("repository") == "https://github.com/proteuscrypto/wapliss-for-grok")
    check("license MIT + LICENSE file", m.get("license") == "MIT" and (ROOT / "LICENSE").is_file())
    kw = m.get("keywords", [])
    check("keywords are brand-scoped (all contain 'wapliss')", bool(kw) and all("wapliss" in k for k in kw), kw)
    check("no generic keywords", not (set(kw) & GENERIC), set(kw) & GENERIC)
    check("no inline mcpServers/hooks in the manifest", "mcpServers" not in m and "hooks" not in m)
    logo = m.get("logo")
    check("logo points to an existing file", bool(logo) and (ROOT / logo).is_file(), logo)

    mc = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
    servers = mc.get("mcpServers", {})
    check(".mcp.json has exactly one server: wapliss", list(servers) == ["wapliss"], list(servers))
    srv = servers.get("wapliss", {})
    check("wapliss: type http, url https://wapliss.com/mcp/v1",
          srv.get("type") == "http" and srv.get("url") == "https://wapliss.com/mcp/v1", srv)
    check("wapliss: only known keys", set(srv) <= MCP_KEYS, set(srv) - MCP_KEYS)
    check("wapliss: no headers or tokens (OAuth handled by Grok)", not ({"headers", "bearer_token_env_var", "bearer_token_file"} & set(srv)))
    check("no hooks, commands, agents or LSP servers shipped",
          not any((ROOT / p).exists() for p in ("hooks", "commands", "agents", ".lsp.json")))

    icon = ROOT / "assets" / "icon.png"
    b = icon.read_bytes() if icon.is_file() else b""
    ok = b[:8] == b"\x89PNG\r\n\x1a\n"
    w, h = struct.unpack(">II", b[16:24]) if ok else (0, 0)
    check("assets/icon.png is a square PNG >= 256 px", ok and w == h and w >= 256, f"{w}x{h}")

    skills = [d for d in (ROOT / "skills").iterdir() if (d / "SKILL.md").is_file()]
    check("one skill in skills/", len(skills) == 1, [d.name for d in skills])
    for d in skills:
        text = (d / "SKILL.md").read_text(encoding="utf-8")
        fm = re.match(r"^---\n(.*?)\n---\n", text, re.S)
        check(f"{d.name}: YAML frontmatter", bool(fm))
        if fm:
            name_m = re.search(r"^name:\s*(\S+)", fm.group(1), re.M)
            check(f"{d.name}: name matches directory", bool(name_m) and name_m.group(1) == d.name)
            check(f"{d.name}: description present", "description:" in fm.group(1))
        missing = [t for t in TOOLS if f"`{t}`" not in text]
        check(f"{d.name}: documents all 16 tools", not missing, missing)
        check(f"{d.name}: tells Grok users how to authenticate", "/mcps" in text)

    blob = "".join(p.read_text(encoding="utf-8", errors="ignore") for p in ROOT.rglob("*")
                   if p.is_file() and ".git" not in p.parts and p.suffix in {".json", ".md", ".py"} and p.name != "validate.py")
    check("no secrets or API keys in the package", not re.search(r"wp_live_[A-Za-z0-9]{8,}|sk-[A-Za-z0-9]{16,}|xai-[A-Za-z0-9]{16,}", blob))
    check("no curl|bash or remote code execution", not re.search(r"curl[^\n]*\|\s*(ba)?sh|iex\s*\(", blob))
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    check("README: install command and creator",
          "grok plugin install proteuscrypto/wapliss-for-grok --trust" in readme and "netdigitaltech" in readme)
    check("README declares the network endpoint", "https://wapliss.com/mcp/v1" in readme)
    check("CHANGELOG mentions the current version", m.get("version", "?") in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))


def live():
    url = "https://wapliss.com/mcp/v1"
    req = urllib.request.Request(url, data=b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}', method="POST",
                                 headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
    try:
        urllib.request.urlopen(req, timeout=30)
        check("live: unauthenticated -> 401", False, "200")
    except urllib.error.HTTPError as e:
        www = e.headers.get("WWW-Authenticate", "")
        check("live: unauthenticated -> 401", e.code == 401, e.code)
        check("live: WWW-Authenticate resource_metadata for /mcp/v1", "oauth-protected-resource/mcp/v1" in www, www)
    with urllib.request.urlopen("https://wapliss.com/.well-known/oauth-authorization-server", timeout=30) as r:
        meta = json.loads(r.read())
    check("live: dynamic client registration endpoint", bool(meta.get("registration_endpoint")))
    check("live: PKCE S256", "S256" in meta.get("code_challenge_methods_supported", []))


if __name__ == "__main__":
    static()
    if "--live" in sys.argv:
        live()
    print("\nRESULT:", "ALL PASS" if not FAIL else f"{len(FAIL)} FAILED")
    sys.exit(1 if FAIL else 0)
