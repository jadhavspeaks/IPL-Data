"""
Run this to diagnose exactly what SharePoint auth endpoints are reachable.
Usage: python utils/sp_auth_probe.py

Run from Anaconda Prompt inside backend folder.
It will tell us exactly which auth method will work.
"""

import requests
import urllib3
import sys
urllib3.disable_warnings()

SITE_URL = "https://citi.sharepoint.com/sites/cc-ee"
USERNAME  = ""  # fill in if you want to test
PASSWORD  = ""  # fill in if you want to test

def probe(label, url, method="GET", data=None, headers=None):
    try:
        fn = requests.post if method == "POST" else requests.get
        r  = fn(url, data=data, headers=headers or {}, verify=False, timeout=10, allow_redirects=False)
        print(f"  ✓ {label}: {r.status_code}")
        # Show auth-relevant headers
        for h in ["WWW-Authenticate","Location","X-Forms_Based_Auth_Required","X-MSDAVEXT_Error"]:
            if h in r.headers:
                print(f"      {h}: {r.headers[h][:120]}")
        return r
    except Exception as e:
        print(f"  ✗ {label}: {type(e).__name__}: {str(e)[:100]}")
        return None

print("\n=== SharePoint Auth Probe ===\n")

print("1. SharePoint REST API reachability:")
probe("/_api/web/Title", f"{SITE_URL}/_api/web/Title")
probe("/_api/v2.1",      f"{SITE_URL}/_api/v2.1")

print("\n2. Microsoft auth endpoints:")
probe("GetUserRealm",    "https://login.microsoftonline.com/GetUserRealm.srf?login=test@citi.com&xml=1")
probe("extSTS.srf",      "https://login.microsoftonline.com/extSTS.srf", "POST")
probe("openid-config",   "https://login.microsoftonline.com/citi.com/.well-known/openid-configuration")

print("\n3. Citi ADFS discovery (common patterns):")
probe("sts.citi.com",           "https://sts.citi.com/adfs/ls/")
probe("adfs.citi.com",          "https://adfs.citi.com/adfs/ls/")
probe("fs.citi.com",            "https://fs.citi.com/adfs/ls/")
probe("login.citi.com",         "https://login.citi.com/")
probe("sso.citi.com",           "https://sso.citi.com/")

print("\n4. SharePoint built-in auth endpoints:")
probe("/_vti_bin/Authentication.asmx", f"{SITE_URL}/_vti_bin/Authentication.asmx")
probe("/_layouts/15/authenticate.aspx", f"{SITE_URL}/_layouts/15/authenticate.aspx")
probe("/_forms/default.aspx",  f"{SITE_URL}/_forms/default.aspx")

print("\n=== Done — share these results ===\n")
