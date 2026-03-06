"""
SharePoint Cookie Helper
─────────────────────────
Reads SharePoint session cookies directly from your Chrome/Edge browser
database on Windows. Nothing is sent anywhere — cookies stay on your machine.

Usage (run once from Anaconda Prompt inside backend folder):
    python utils/cookie_helper.py https://citi.sharepoint.com/sites/cc-ee

It will print the exact lines to add to your .env file.
"""

import sys
import os
import shutil
import sqlite3
import json
import tempfile


def get_cookies_from_chrome(url: str, browser: str = "chrome") -> dict:
    """Read cookies for a URL from Chrome or Edge local database."""

    # Locate cookie database
    appdata = os.environ.get("LOCALAPPDATA", "")
    paths = {
        "chrome": os.path.join(appdata, "Google", "Chrome", "User Data", "Default", "Cookies"),
        "edge":   os.path.join(appdata, "Microsoft", "Edge",  "User Data", "Default", "Cookies"),
    }

    # Chrome moved cookies to "Network/Cookies" in newer versions
    alt_paths = {
        "chrome": os.path.join(appdata, "Google", "Chrome", "User Data", "Default", "Network", "Cookies"),
        "edge":   os.path.join(appdata, "Microsoft", "Edge",  "User Data", "Default", "Network", "Cookies"),
    }

    db_path = paths.get(browser)
    if not db_path or not os.path.exists(db_path):
        db_path = alt_paths.get(browser)

    if not db_path or not os.path.exists(db_path):
        return {}

    # Copy DB — Chrome locks the file while open
    tmp = tempfile.mktemp(suffix=".db")
    shutil.copy2(db_path, tmp)

    # Extract hostname from URL
    from urllib.parse import urlparse
    hostname = urlparse(url).hostname  # e.g. citi.sharepoint.com

    cookies = {}
    try:
        conn = sqlite3.connect(tmp)
        cur  = conn.cursor()

        # Try both column layouts (Chrome versions differ)
        try:
            cur.execute(
                "SELECT name, encrypted_value FROM cookies WHERE host_key LIKE ?",
                (f"%{hostname}%",)
            )
        except Exception:
            cur.execute(
                "SELECT name, encrypted_value FROM cookies WHERE host_key LIKE ?",
                (f"%{hostname}%",)
            )

        rows = cur.fetchall()
        conn.close()

        if not rows:
            return {}

        # Decrypt cookies using Windows DPAPI
        try:
            import win32crypt
            for name, encrypted_value in rows:
                try:
                    decrypted = win32crypt.CryptUnprotectData(encrypted_value, None, None, None, 0)[1]
                    value = decrypted.decode("utf-8", errors="ignore")
                    if value:
                        cookies[name] = value
                except Exception:
                    pass
        except ImportError:
            # Try newer Chrome AES-GCM decryption
            try:
                import win32crypt
                import base64
                from Crypto.Cipher import AES

                # Get encryption key from Local State
                local_state_path = os.path.join(
                    appdata, "Google", "Chrome", "User Data", "Local State"
                )
                with open(local_state_path, "r") as f:
                    local_state = json.load(f)

                encrypted_key = base64.b64decode(
                    local_state["os_crypt"]["encrypted_key"]
                )[5:]  # Remove DPAPI prefix
                key = win32crypt.CryptUnprotectData(encrypted_key, None, None, None, 0)[1]

                for name, encrypted_value in rows:
                    try:
                        if encrypted_value[:3] == b"v10":
                            iv   = encrypted_value[3:15]
                            data = encrypted_value[15:]
                            cipher = AES.new(key, AES.MODE_GCM, iv)
                            value = cipher.decrypt(data)[:-16].decode("utf-8", errors="ignore")
                        else:
                            value = win32crypt.CryptUnprotectData(
                                encrypted_value, None, None, None, 0
                            )[1].decode("utf-8", errors="ignore")
                        if value:
                            cookies[name] = value
                    except Exception:
                        pass
            except Exception as e:
                print(f"Decryption failed: {e}")

    except Exception as e:
        print(f"DB read failed: {e}")
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass

    return cookies


def build_cookie_header(cookies: dict) -> str:
    """Build a Cookie header string from a dict."""
    return "; ".join(f"{k}={v}" for k, v in cookies.items() if v)


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "https://citi.sharepoint.com"
    print(f"\nReading SharePoint cookies from Chrome for: {url}\n")

    cookies = {}

    # Try Chrome first, then Edge
    for browser in ("chrome", "edge"):
        cookies = get_cookies_from_chrome(url, browser)
        if cookies:
            print(f"Found {len(cookies)} cookies in {browser}")
            break

    if not cookies:
        print("Could not read cookies automatically.")
        print("\nManual option:")
        print("1. Open SharePoint in browser → F12 → Console")
        print("2. Run:  document.cookie")
        print("3. Add to .env as:  SHAREPOINT_ALL_COOKIES=<paste here>")
        sys.exit(1)

    # Show which cookies were found
    sp_cookies = {k: v for k, v in cookies.items()
                  if k in ("FedAuth", "rtFa", "WSS_FullScreenMode",
                           "MicrosoftApplicationsTelemetryDeviceId",
                           "SIMI", "StickyLCID", "RpsContextCookie")}

    print(f"\nSharePoint-relevant cookies found: {list(sp_cookies.keys())}")

    cookie_header = build_cookie_header(cookies)

    print("\n" + "="*60)
    print("Add this line to your .env file:")
    print("="*60)
    print(f"SHAREPOINT_ALL_COOKIES={cookie_header}")
    print("="*60)
