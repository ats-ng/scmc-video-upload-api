from fastapi import FastAPI, File, UploadFile, HTTPException, Header, Response
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob import ContentSettings
from datetime import datetime, timedelta
from typing import Optional
import os
import mimetypes
from pydantic import BaseModel
import uuid
from dotenv import load_dotenv
load_dotenv()


app = FastAPI(title="Media Upload & Streaming API")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration
AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
CONTAINER_NAME = os.getenv("AZURE_CONTAINER_NAME", "media-files")
ALLOWED_EXTENSIONS = {
    'video': ['.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm', '.mkv'],
    'audio': ['.mp3', '.wav', '.ogg', '.m4a', '.flac'],
    'image': ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp']
}

# Initialize Azure Blob Service Client
blob_service_client = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)
container_client = blob_service_client.get_container_client(CONTAINER_NAME)

# Ensure container exists
try:
    container_client.create_container()
except Exception:
    pass  # Container already exists


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


def get_media_type(filename: str) -> str:
    """Determine media type from file extension"""
    ext = os.path.splitext(filename)[1].lower()
    for media_type, extensions in ALLOWED_EXTENSIONS.items():
        if ext in extensions:
            return media_type
    return "unknown"


def is_allowed_file(filename: str) -> bool:
    """Check if file extension is allowed"""
    ext = os.path.splitext(filename)[1].lower()
    for extensions in ALLOWED_EXTENSIONS.values():
        if ext in extensions:
            return True
    return False


@app.get("/")
async def root():
    return {
        "message": "Media Upload & Streaming API",
        "endpoints": {
            "upload": "/upload",
            "stream": "/stream/{media_id}",
            "info": "/media/{media_id}",
            "list": "/media/list"
        }
    }


@app.post("/upload", response_model=UploadResponse)
async def upload_media(file: UploadFile = File(...)):
    """
    Upload media file to Azure Blob Storage
    
    - Accepts video, audio, and image files
    - Returns media_id and streaming URL
    - Files are stored with unique IDs
    """
    
    # Validate file type
    if not is_allowed_file(file.filename):
        raise HTTPException(
            status_code=400,
            detail=f"File type not allowed. Allowed types: {', '.join(sum(ALLOWED_EXTENSIONS.values(), []))}"
        )
    
    # Generate unique media ID
    media_id = str(uuid.uuid4())
    file_extension = os.path.splitext(file.filename)[1]
    blob_name = f"{media_id}{file_extension}"
    
    # Get content type
    content_type = file.content_type or mimetypes.guess_type(file.filename)[0] or "application/octet-stream"
    
    try:
        # Upload to Azure Blob Storage
        blob_client = container_client.get_blob_client(blob_name)
        
        # Read file content
        file_content = await file.read()
        file_size = len(file_content)
        
        # Upload with metadata
        metadata = {
            "original_filename": file.filename,
            "media_id": media_id,
            "upload_time": datetime.utcnow().isoformat(),
            "media_type": get_media_type(file.filename)
        }
        
        blob_client.upload_blob(
            file_content,
            blob_client.upload_blob(
                file_content,
                content_settings=ContentSettings(
                    content_type=content_type,
                    content_disposition="inline",
                    cache_control="no-cache"
                ),
                metadata=metadata,
                overwrite=True
            ), 
            metadata=metadata,
            overwrite=True
        )
        
        return UploadResponse(
            success=True,
            media_id=media_id,
            filename=file.filename,
            size=file_size,
            content_type=content_type,
            stream_url=f"/stream/{media_id}"
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@app.get("/stream/{media_id}")
async def stream_media(
    media_id: str,
    range: Optional[str] = Header(None)
):
    """
    Stream media file with range support (for video seeking)
    
    - Supports HTTP Range requests for video players
    - Prevents download by setting appropriate headers
    - Streams content directly from Azure Blob Storage
    """
    
    try:
        # Find blob with this media_id
        blobs = container_client.list_blobs()
        blob_name = None
        
        for blob in blobs:
            if blob.metadata and blob.metadata.get("media_id") == media_id:
                blob_name = blob.name
                break
        
        if not blob_name:
            raise HTTPException(status_code=404, detail="Media not found")
        
        blob_client = container_client.get_blob_client(blob_name)
        blob_properties = blob_client.get_blob_properties()
        
        file_size = blob_properties.size
        content_type = blob_properties.content_settings.content_type
        
        # Handle range requests for video seeking
        start = 0
        end = file_size - 1
        status_code = 200
        
        if range:
            # Parse range header
            range_match = range.replace("bytes=", "").split("-")
            start = int(range_match[0]) if range_match[0] else 0
            end = int(range_match[1]) if range_match[1] else file_size - 1
            status_code = 206
        
        # Calculate content length
        content_length = end - start + 1
        
        # Download blob data with range
        blob_data = blob_client.download_blob(offset=start, length=content_length)
        
        # Headers to prevent download and enable streaming
        headers = {
            "Content-Type": content_type,
            "Accept-Ranges": "bytes",
            "Content-Disposition": "inline",  # Prevent download dialog
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        }
        
        if status_code == 206:
            headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
            headers["Content-Length"] = str(content_length)
        else:
            headers["Content-Length"] = str(file_size)
        
        # Stream the content
        return StreamingResponse(
            blob_data.chunks(),
            status_code=status_code,
            headers=headers,
            media_type=content_type
        )
        
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Media not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Streaming failed: {str(e)}")


@app.get("/media/{media_id}", response_model=MediaInfo)
async def get_media_info(media_id: str):
    """
    Get information about a media file
    
    - Returns metadata without streaming the actual file
    """
    
    try:
        # Find blob with this media_id
        blobs = container_client.list_blobs()
        
        for blob in blobs:
            if blob.metadata and blob.metadata.get("media_id") == media_id:
                blob_client = container_client.get_blob_client(blob.name)
                properties = blob_client.get_blob_properties()
                
                return MediaInfo(
                    media_id=media_id,
                    filename=blob.metadata.get("original_filename", "unknown"),
                    content_type=properties.content_settings.content_type,
                    size=properties.size,
                    upload_time=blob.metadata.get("upload_time", "unknown"),
                    media_type=blob.metadata.get("media_type", "unknown")
                )
        
        raise HTTPException(status_code=404, detail="Media not found")
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/media/list")
async def list_media():
    """
    List all uploaded media files
    
    - Returns basic information about all media files
    """
    
    try:
        blobs = container_client.list_blobs()
        media_list = []
        
        for blob in blobs:
            if blob.metadata and blob.metadata.get("media_id"):
                media_list.append({
                    "media_id": blob.metadata.get("media_id"),
                    "filename": blob.metadata.get("original_filename", "unknown"),
                    "size": blob.size,
                    "upload_time": blob.metadata.get("upload_time", "unknown"),
                    "media_type": blob.metadata.get("media_type", "unknown"),
                    "stream_url": f"/stream/{blob.metadata.get('media_id')}"
                })
        
        return {
            "total": len(media_list),
            "media": media_list
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/media/{media_id}")
async def delete_media(media_id: str):
    """
    Delete a media file from storage
    """
    
    try:
        # Find blob with this media_id
        blobs = container_client.list_blobs()
        
        for blob in blobs:
            if blob.metadata and blob.metadata.get("media_id") == media_id:
                blob_client = container_client.get_blob_client(blob.name)
                blob_client.delete_blob()
                
                return {
                    "success": True,
                    "message": f"Media {media_id} deleted successfully"
                }
        
        raise HTTPException(status_code=404, detail="Media not found")
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
