from fastapi import FastAPI, File, UploadFile, HTTPException, Header
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from azure.storage.blob import BlobServiceClient, ContentSettings
from azure.core.exceptions import ResourceNotFoundError
from datetime import datetime
from typing import Optional
import os
import mimetypes
import uuid
import json
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()

app = FastAPI(title="Media Upload & Streaming API")

# -------------------- CORS --------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------- CONFIG --------------------
AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
CONTAINER_NAME = os.getenv("AZURE_CONTAINER_NAME", "media-files")
INDEX_BLOB = "media_index.json"

ALLOWED_EXTENSIONS = {
    "video": [".mp4", ".avi", ".mov", ".wmv", ".flv", ".webm", ".mkv"],
    "audio": [".mp3", ".wav", ".ogg", ".m4a", ".flac"],
    "image": [".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"],
}

# -------------------- AZURE INIT --------------------
blob_service_client = BlobServiceClient.from_connection_string(
    AZURE_STORAGE_CONNECTION_STRING
)
container_client = blob_service_client.get_container_client(CONTAINER_NAME)

try:
    container_client.create_container()
except Exception:
    pass  # already exists

# -------------------- MODELS --------------------
class MediaInfo(BaseModel):
    media_id: str
    filename: str
    content_type: str
    size: int
    upload_time: str
    media_type: str


class UploadResponse(BaseModel):
    success: bool
    media_id: str
    filename: str
    size: int
    content_type: str
    stream_url: str


# -------------------- HELPERS --------------------
def get_media_type(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    for media_type, extensions in ALLOWED_EXTENSIONS.items():
        if ext in extensions:
            return media_type
    return "unknown"


def is_allowed_file(filename: str) -> bool:
    ext = os.path.splitext(filename)[1].lower()
    return any(ext in exts for exts in ALLOWED_EXTENSIONS.values())


def find_blob_by_media_id(media_id: str) -> str:
    for exts in ALLOWED_EXTENSIONS.values():
        for ext in exts:
            name = f"{media_id}{ext}"
            if container_client.get_blob_client(name).exists():
                return name
    raise HTTPException(status_code=404, detail="Media not found")


def get_media_index():
    blob = container_client.get_blob_client(INDEX_BLOB)
    if not blob.exists():
        return []
    return json.loads(blob.download_blob().readall())


def save_media_index(index):
    blob = container_client.get_blob_client(INDEX_BLOB)
    blob.upload_blob(
        json.dumps(index),
        overwrite=True,
        content_settings=ContentSettings(content_type="application/json"),
    )


# -------------------- ROUTES --------------------
@app.get("/")
async def root():
    return {
        "message": "Media Upload & Streaming API",
        "endpoints": [
            "/upload",
            "/stream/{media_id}",
            "/media/{media_id}",
            "/media/list",
            "/media/{media_id} [DELETE]",
        ],
    }


@app.post("/upload", response_model=UploadResponse)
async def upload_media(file: UploadFile = File(...)):
    if not is_allowed_file(file.filename):
        raise HTTPException(status_code=400, detail="File type not allowed")

    media_id = str(uuid.uuid4())
    extension = os.path.splitext(file.filename)[1]
    blob_name = f"{media_id}{extension}"

    content_type = (
        file.content_type
        or mimetypes.guess_type(file.filename)[0]
        or "application/octet-stream"
    )

    upload_time = datetime.utcnow().isoformat()

    metadata = {
        "original_filename": file.filename,
        "media_id": media_id,
        "upload_time": upload_time,
        "media_type": get_media_type(file.filename),
    }

    try:
        blob_client = container_client.get_blob_client(blob_name)

        blob_client.upload_blob(
            file.file,
            overwrite=True,
            metadata=metadata,
            content_settings=ContentSettings(
                content_type=content_type,
                content_disposition="inline",
                cache_control="no-cache",
            ),
        )

        size = blob_client.get_blob_properties().size

        # ✅ update index
        index = get_media_index()
        index.append(
            {
                "media_id": media_id,
                "filename": file.filename,
                "size": size,
                "upload_time": upload_time,
                "media_type": metadata["media_type"],
                "stream_url": f"/stream/{media_id}",
            }
        )
        save_media_index(index)

        return UploadResponse(
            success=True,
            media_id=media_id,
            filename=file.filename,
            size=size,
            content_type=content_type,
            stream_url=f"/stream/{media_id}",
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@app.get("/stream/{media_id}")
async def stream_media(media_id: str, range: Optional[str] = Header(None)):
    try:
        blob_name = find_blob_by_media_id(media_id)
        blob_client = container_client.get_blob_client(blob_name)
        props = blob_client.get_blob_properties()

        file_size = props.size
        content_type = props.content_settings.content_type

        start, end = 0, file_size - 1
        status_code = 200

        if range:
            start_str, end_str = range.replace("bytes=", "").split("-")
            start = int(start_str) if start_str else 0
            end = int(end_str) if end_str else end
            status_code = 206

        length = end - start + 1
        stream = blob_client.download_blob(offset=start, length=length)

        headers = {
            "Accept-Ranges": "bytes",
            "Content-Disposition": "inline",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        }

        if status_code == 206:
            headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
            headers["Content-Length"] = str(length)

        return StreamingResponse(
            stream.chunks(),
            status_code=status_code,
            media_type=content_type,
            headers=headers,
        )

    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Media not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/media/list")
async def list_media():
    index = get_media_index()
    return {"total": len(index), "media": index}


@app.get("/media/{media_id}", response_model=MediaInfo)
async def get_media_info(media_id: str):
    blob_name = find_blob_by_media_id(media_id)
    blob_client = container_client.get_blob_client(blob_name)
    props = blob_client.get_blob_properties()

    return MediaInfo(
        media_id=media_id,
        filename=props.metadata.get("original_filename", "unknown"),
        content_type=props.content_settings.content_type,
        size=props.size,
        upload_time=props.metadata.get("upload_time", "unknown"),
        media_type=props.metadata.get("media_type", "unknown"),
    )


@app.delete("/media/{media_id}")
async def delete_media(media_id: str):
    blob_name = find_blob_by_media_id(media_id)
    container_client.get_blob_client(blob_name).delete_blob()

    index = [
        item for item in get_media_index() if item["media_id"] != media_id
    ]
    save_media_index(index)

    return {"success": True, "message": "Media deleted successfully"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)