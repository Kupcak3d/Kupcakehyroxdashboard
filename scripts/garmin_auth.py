"""One-time: sign in to Garmin Connect (handles MFA) and print a token for CI.

Run: python scripts/garmin_auth.py
Store the printed value as the GARMIN_TOKENS repository secret. Tokens last about a
year; rerun this if the dashboard footer shows Garmin as not connected.
"""
import getpass

from garminconnect import Garmin

email = input("Garmin email: ").strip()
password = getpass.getpass("Garmin password: ")
g = Garmin(email, password, prompt_mfa=lambda: input("MFA code: ").strip())
g.login()
print("\nGARMIN_TOKENS =\n")
print(g.client.dumps())
