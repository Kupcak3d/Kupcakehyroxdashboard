"""One-time: get a Strava refresh token with read access to all your activities.

1. Create an app at https://www.strava.com/settings/api (Authorization Callback Domain: localhost).
2. Run: python scripts/strava_auth.py <client_id> <client_secret>
3. Open the printed URL, approve, then paste the full URL you land on (it won't load; that's fine).
"""
import sys
from urllib.parse import parse_qs, urlparse

import requests

client_id, client_secret = sys.argv[1], sys.argv[2]
print("Open this URL and approve:\n")
print(f"https://www.strava.com/oauth/authorize?client_id={client_id}&response_type=code"
      "&redirect_uri=http://localhost/exchange_token&approval_prompt=force&scope=read,activity:read_all\n")
redirected = input("Paste the URL you were redirected to: ").strip()
code = parse_qs(urlparse(redirected).query)["code"][0]
r = requests.post("https://www.strava.com/oauth/token", data={
    "client_id": client_id, "client_secret": client_secret, "code": code, "grant_type": "authorization_code"}, timeout=30)
r.raise_for_status()
print("\nAdd these as repository secrets (Settings → Secrets and variables → Actions):")
print(f"  STRAVA_CLIENT_ID      = {client_id}")
print(f"  STRAVA_CLIENT_SECRET  = {client_secret}")
print(f"  STRAVA_REFRESH_TOKEN  = {r.json()['refresh_token']}")
