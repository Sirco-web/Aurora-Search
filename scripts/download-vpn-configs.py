#!/usr/bin/env python3
"""
Aurora Search OpenVPN Config Downloader
Downloads free OpenVPN configs directly from GitHub file listings
and creates auth files automatically when credentials are available.
"""

from pathlib import Path

import os
import requests

from vpn_manager import get_vpn_configs_dir

GITHUB_SOURCES = [
    {
        "name": "Zoult Free OpenVPN (USA configs)",
        "owner": "Zoult",
        "repo": ".ovpn",
        "branch": "main",
        "path": "USA",
    },
    {
        "name": "DesertSun35 Free OpenVPN Configs",
        "owner": "DesertSun35",
        "repo": "Free-Openvpn-Configs",
        "branch": "main",
        "path": "",
    },
]

VPNBOOK_DEFAULT_USERNAME = "vpnbook"
VPNBOOK_DEFAULT_PASSWORD = "939pxfv"


def print_banner():
    print(
        """
╔════════════════════════════════════════════════════════════════════╗
║         OPENVPN CONFIG DOWNLOADER FOR AURORA SEARCH               ║
╚════════════════════════════════════════════════════════════════════╝
"""
    )


def extract_password_from_url_file(content):
    try:
        credentials = {}
        for line in content.decode("utf-8", errors="ignore").splitlines():
            text = line.strip()
            if "=" not in text:
                continue
            key, value = text.split("=", 1)
            lowered = key.lower().strip()
            if "username" in lowered or lowered == "user":
                credentials["username"] = value.strip()
            elif "password" in lowered or lowered == "pass":
                credentials["password"] = value.strip()

        if "username" in credentials and "password" in credentials:
            return credentials
        return None
    except Exception as exc:
        print(f"      Could not parse auth file: {exc}")
        return None


def create_auth_file(auth_path, username, password):
    try:
        os.makedirs(os.path.dirname(auth_path), exist_ok=True)
        with open(auth_path, "w", encoding="utf-8") as handle:
            handle.write(f"{username}\n{password}\n")
        return True
    except OSError as exc:
        print(f"      Failed to create auth file: {exc}")
        return False


def github_api_headers():
    return {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Aurora-Search-Downloader",
    }


def list_github_contents(owner, repo, branch, path):
    relative_path = path.strip("/")
    if relative_path:
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{relative_path}"
    else:
        url = f"https://api.github.com/repos/{owner}/{repo}/contents"

    response = requests.get(url, params={"ref": branch}, headers=github_api_headers(), timeout=30)
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, list) else [payload]


def collect_repo_files(owner, repo, branch, path):
    stack = [path.strip("/")]
    discovered = []

    while stack:
        current_path = stack.pop()
        for entry in list_github_contents(owner, repo, branch, current_path):
            if entry.get("type") == "dir":
                stack.append(entry["path"])
            elif entry.get("type") == "file":
                discovered.append(entry)

    return discovered


def match_credentials(password_files, file_path):
    current = Path(file_path).parent
    while True:
        key = current.as_posix()
        if key in password_files:
            return password_files[key]
        if key in {"", "."}:
            break
        current = current.parent
    return None


def download_from_github(source, local_path):
    print(f"\nDownloading from {source['name']}")
    try:
        files = collect_repo_files(
            source["owner"],
            source["repo"],
            source["branch"],
            source["path"],
        )

        password_files = {}
        for entry in files:
            path_lower = entry["path"].lower()
            if "password.url" not in path_lower:
                continue

            content = requests.get(entry["download_url"], headers=github_api_headers(), timeout=30).content
            creds = extract_password_from_url_file(content)
            if not creds:
                continue

            directory_key = Path(entry["path"]).parent.as_posix()
            password_files[directory_key] = creds
            print(f"   Found credentials in {entry['path']}")

        downloaded_count = 0
        for entry in files:
            if not entry["name"].endswith(".ovpn"):
                continue

            response = requests.get(entry["download_url"], headers=github_api_headers(), timeout=30)
            response.raise_for_status()

            filename = entry["name"]
            filepath = os.path.join(local_path, filename)
            os.makedirs(local_path, exist_ok=True)
            with open(filepath, "wb") as handle:
                handle.write(response.content)

            downloaded_count += 1
            print(f"   Saved {filename}")

            creds = match_credentials(password_files, entry["path"])
            if creds:
                auth_file = os.path.join(local_path, f".auth_{filename}.txt")
                if create_auth_file(auth_file, creds["username"], creds["password"]):
                    print(f"      Created auth file for {filename}")

        return downloaded_count
    except Exception as exc:
        print(f"   Download failed: {exc}")
        return 0


def create_vpnbook_config(server, protocol, username, password, local_path):
    print(f"   Skipped VPNBook config for {server} {protocol}: required cert/key bundle is not available locally.")
    return False


def get_vpnbook_credentials(local_path):
    shared_auth = os.path.join(local_path, "auth.txt")
    if os.path.exists(shared_auth):
        try:
            with open(shared_auth, "r", encoding="utf-8") as handle:
                lines = [line.strip() for line in handle.readlines() if line.strip()]
            if len(lines) >= 2:
                return lines[0], lines[1]
        except OSError:
            pass

    return VPNBOOK_DEFAULT_USERNAME, VPNBOOK_DEFAULT_PASSWORD


def count_configs(local_path):
    if not os.path.exists(local_path):
        return 0
    return len([name for name in os.listdir(local_path) if name.endswith(".ovpn")])


def main():
    print_banner()
    vpn_dir = get_vpn_configs_dir()

    print(
        f"""
VPN config destination:
  {vpn_dir}

Sources:
1. All sources
2. GitHub repos only
3. VPNBook only
0. Skip
"""
    )

    choice = input("Download which source set? ").strip()
    if choice == "0":
        print("Skipped VPN config download.")
        return

    total_downloaded = 0

    if choice in {"1", "2"}:
        for source in GITHUB_SOURCES:
            total_downloaded += download_from_github(source, vpn_dir)

    if choice in {"1", "3"}:
        username, password = get_vpnbook_credentials(vpn_dir)
        vpnbook_servers = [
            ("us16.vpnbook.com", "US Server 1"),
            ("us178.vpnbook.com", "US Server 2"),
            ("ca149.vpnbook.com", "Canada Server 1"),
            ("uk205.vpnbook.com", "UK Server 1"),
            ("de20.vpnbook.com", "Germany Server 1"),
            ("fr200.vpnbook.com", "France Server 1"),
        ]

        print("\nCreating VPNBook configs with automatic credentials...")
        for server, server_name in vpnbook_servers:
            print(f"   {server_name}")
            for protocol in ["tcp_443", "tcp_80", "udp_53"]:
                if create_vpnbook_config(server, protocol, username, password, vpn_dir):
                    total_downloaded += 1

    final_count = count_configs(vpn_dir)
    print(
        f"""
Download complete.

New files fetched or created: {total_downloaded}
Total VPN configs available: {final_count}
Saved in: {vpn_dir}

Next steps:
  python3 scripts/vpn-manager.py
  python3 app.py
"""
    )


if __name__ == "__main__":
    main()
