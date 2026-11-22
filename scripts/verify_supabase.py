"""
Supabase Account & Project Verification Script
Verify and test new Supabase credentials and optionally update Antigravity MCP config.
"""

import argparse
import json
import os
import sys
from pathlib import Path

try:
    import urllib.request
    import urllib.error
except ImportError:
    pass

MCP_CONFIG_PATH = Path.home() / ".gemini" / "antigravity" / "mcp_config.json"


def verify_management_token(token: str):
    """Verify Supabase Personal Access Token via Management API."""
    print(f"\n[*] Verifying Supabase Management Token (starts with {token[:7]}...)...")
    url = "https://api.supabase.com/v1/projects"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "Supabase-Verifier/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print(" [SUCCESS] Token is valid and authenticated!")
            print(f" [INFO] Found {len(data)} project(s) in this account:\n")
            for p in data:
                print(f"  - Project Name : {p.get('name')}")
                print(f"    Project Ref  : {p.get('id') or p.get('ref')}")
                print(f"    Status       : {p.get('status')}")
                print(f"    Region       : {p.get('region')}")
                print(f"    Postgres Ver : {p.get('database', {}).get('version', 'N/A')}")
                print("-" * 50)
            return data
    except urllib.error.HTTPError as e:
        print(f" [ERROR] HTTP {e.code}: {e.reason}")
        try:
            err_body = e.read().decode("utf-8")
            print(f"  Details: {err_body}")
        except Exception:
            pass
        return None
    except Exception as e:
        print(f" [ERROR] Connection failed: {e}")
        return None


def verify_project_rest(project_ref: str, anon_or_service_key: str):
    """Verify project connection via PostgREST endpoint."""
    print(f"\n[*] Testing Project REST API for ref: {project_ref}...")
    url = f"https://{project_ref}.supabase.co/rest/v1/"
    req = urllib.request.Request(
        url,
        headers={
            "apikey": anon_or_service_key,
            "Authorization": f"Bearer {anon_or_service_key}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            print(" [SUCCESS] Project REST API is accessible and responding (HTTP 200)!")
            return True
    except urllib.error.HTTPError as e:
        print(f" [ERROR] REST check returned HTTP {e.code}: {e.reason}")
        return False
    except Exception as e:
        print(f" [ERROR] Could not connect to project endpoint: {e}")
        return False


def update_mcp_config(project_ref: str, token: str):
    """Update Antigravity MCP configuration file."""
    if not MCP_CONFIG_PATH.exists():
        print(f"[-] Config file not found at: {MCP_CONFIG_PATH}")
        return False

    try:
        with open(MCP_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)

        mcp_url = (
            f"https://mcp.supabase.com/mcp?project_ref={project_ref}"
            f"&features=docs%2Caccount%2Cdatabase%2Cdebugging%2Cdevelopment%2Cfunctions%2Cbranching%2Cfeedback%2Cnotebooks"
        )
        auth_header = f"Bearer {token}"

        if "mcpServers" not in cfg:
            cfg["mcpServers"] = {}

        for server_name in ["supabase", "superbase"]:
            cfg["mcpServers"][server_name] = {
                "url": mcp_url,
                "serverUrl": mcp_url,
                "headers": {"Authorization": auth_header},
            }

        with open(MCP_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)

        print(f"\n[SUCCESS] Updated {MCP_CONFIG_PATH}")
        print(f"  - Active Project: {project_ref}")
        print(f"  - Active Token  : {token[:7]}...")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to update config: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Supabase Account & MCP Verifier")
    parser.add_argument("--token", help="Personal Access Token (sbp_...)")
    parser.add_argument("--ref", help="Project Reference ID")
    parser.add_argument("--key", help="Anon or Service Role API Key (optional)")
    parser.add_argument(
        "--update-mcp", action="store_true", help="Update mcp_config.json with new credentials"
    )

    args = parser.parse_args()

    if not args.token and not args.ref:
        print("Usage:")
        print("  python scripts/verify_supabase.py --token <sbp_token> [--ref <project_ref>] [--update-mcp]")
        print("  python scripts/verify_supabase.py --ref <project_ref> --key <anon_or_service_key>")
        sys.exit(1)

    if args.token:
        projects = verify_management_token(args.token)
        if projects and args.update_mcp:
            target_ref = args.ref or (projects[0].get("id") or projects[0].get("ref"))
            if target_ref:
                update_mcp_config(target_ref, args.token)

    if args.ref and args.key:
        verify_project_rest(args.ref, args.key)


if __name__ == "__main__":
    main()
