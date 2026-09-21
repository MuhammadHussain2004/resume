"""Authorize Google Drive and replace the repository refresh-token secret safely."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow


DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"
DEFAULT_REPOSITORY = "MuhammadHussain2004/resume"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a Google OAuth refresh token and store it in GitHub Actions."
    )
    parser.add_argument("credentials", type=Path, help="Downloaded desktop OAuth JSON file")
    parser.add_argument("--repo", default=DEFAULT_REPOSITORY, help="GitHub owner/repository")
    args = parser.parse_args()

    credentials_path = args.credentials.expanduser().resolve()
    if not credentials_path.is_file():
        print(f"Credentials file not found: {credentials_path}", file=sys.stderr)
        return 1

    flow = InstalledAppFlow.from_client_secrets_file(
        str(credentials_path), scopes=[DRIVE_FILE_SCOPE]
    )
    credentials = flow.run_local_server(
        host="localhost",
        port=0,
        access_type="offline",
        prompt="consent",
        open_browser=True,
        authorization_prompt_message=(
            "A browser window has opened. Sign in to Google and allow Drive access."
        ),
        success_message="Authorization complete. You may close this browser window.",
    )

    if not credentials.refresh_token:
        print(
            "Google did not return a refresh token. Revoke the app grant and try again.",
            file=sys.stderr,
        )
        return 1

    subprocess.run(
        [
            "gh",
            "secret",
            "set",
            "GDRIVE_REFRESH_TOKEN",
            "--repo",
            args.repo,
            "--body",
            credentials.refresh_token,
        ],
        check=True,
    )
    print(f"Updated GDRIVE_REFRESH_TOKEN for {args.repo}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
