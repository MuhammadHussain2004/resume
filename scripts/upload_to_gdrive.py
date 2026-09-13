import os
import sys
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

path = Path(sys.argv[1])
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
query = "name = 'Muhammad_Hussain_Resume.pdf' and trashed = false and '" + folder_id + "' in parents"
results = service.files().list(q=query, spaces="drive", fields="files(id,name)", pageSize=10).execute()
media = MediaFileUpload(str(path), mimetype="application/pdf", resumable=True)
files = results.get("files", [])
if files:
    service.files().update(fileId=files[0]["id"], media_body=media).execute()
    print("Updated existing Google Drive resume file")
else:
    service.files().create(body={"name": path.name, "parents": [folder_id]}, media_body=media, fields="id").execute()
    print("Created Google Drive resume file")
