import os
import sys
import time
from pathlib import Path

from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from googleapiclient.errors import HttpError
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

REQUIRED_ENV = (
    "GDRIVE_CLIENT_ID",
    "GDRIVE_CLIENT_SECRET",
    "GDRIVE_REFRESH_TOKEN",
    "GDRIVE_FOLDER_ID",
)


def warn(message: str) -> None:
    print(f"::warning::{message}")


def drive_request(description: str, operation):
    for attempt in range(1, 4):
        try:
            return operation().execute()
        except RefreshError as error:
            warn(
                "Google Drive upload skipped because the OAuth refresh token is expired "
                f"or revoked: {error}"
            )
            return None
        except HttpError as error:
            status = getattr(error.resp, "status", None)
            if status in {429, 500, 502, 503, 504} and attempt < 3:
                wait_seconds = attempt * 10
                print(
                    f"{description} failed with HTTP {status}; retrying in "
                    f"{wait_seconds}s ({attempt}/3)"
                )
                time.sleep(wait_seconds)
                continue
            warn(f"Google Drive upload skipped during {description}: {error}")
            return None
        except Exception as error:
            warn(f"Google Drive upload skipped during {description}: {error}")
            return None


def main() -> None:
    if len(sys.argv) < 2:
        warn("Google Drive upload skipped because no PDF path was provided.")
        return

    missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        warn(
            "Google Drive upload skipped because these secrets are missing: "
            + ", ".join(missing)
        )
        return

    path = Path(sys.argv[1])
    if not path.exists():
        warn(f"Google Drive upload skipped because {path} does not exist.")
        return

    folder_id = os.environ["GDRIVE_FOLDER_ID"]
    credentials = Credentials(
        token=None,
        refresh_token=os.environ["GDRIVE_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["GDRIVE_CLIENT_ID"],
        client_secret=os.environ["GDRIVE_CLIENT_SECRET"],
        scopes=["https://www.googleapis.com/auth/drive.file"],
    )
    service = build("drive", "v3", credentials=credentials, cache_discovery=False)
    query = (
        "name = 'Muhammad_Hussain_Resume.pdf' and trashed = false and '"
        + folder_id
        + "' in parents"
    )
    results = drive_request(
        "listing existing resume files",
        lambda: service.files().list(
            q=query, spaces="drive", fields="files(id,name)", pageSize=10
        ),
    )
    if results is None:
        return

    media = MediaFileUpload(str(path), mimetype="application/pdf", resumable=True)
    files = results.get("files", [])
    if files:
        updated = drive_request(
            "updating existing resume file",
            lambda: service.files().update(fileId=files[0]["id"], media_body=media),
        )
        if updated is not None:
            print("Updated existing Google Drive resume file")
        return

    created = drive_request(
        "creating resume file",
        lambda: service.files().create(
            body={"name": path.name, "parents": [folder_id]},
            media_body=media,
            fields="id",
        ),
    )
    if created is not None:
        print("Created Google Drive resume file")


if __name__ == "__main__":
    main()
