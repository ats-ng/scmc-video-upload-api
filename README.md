# Media Upload & Streaming API with Azure Blob Storage

A FastAPI-based application for secure video, audio, and image upload and streaming using Azure Blob Storage. This solution prevents direct downloads while allowing seamless playback.

## 🎯 Features

- **Secure Upload**: Upload videos, audio files, and images to Azure Blob Storage
- **Streaming Playback**: Stream media with HTTP range support for video seeking
- **Download Prevention**: Content-Disposition headers prevent direct downloads
- **Multiple Media Types**: Support for video (MP4, AVI, MOV, etc.), audio (MP3, WAV, etc.), and images (JPG, PNG, etc.)
- **RESTful API**: Clean, documented API endpoints
- **Web Client**: Beautiful HTML/JS client for testing
- **Scalable Storage**: Uses Azure Blob Storage instead of local VM storage

## 📋 Prerequisites

- Python 3.8+
- Azure Storage Account
- Azure Blob Storage Container

## 🚀 Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Azure Storage

1. Create an Azure Storage Account in the Azure Portal
2. Create a container (e.g., "media-files")
3. Get your connection string from Azure Portal:
   - Navigate to Storage Account → Access keys
   - Copy "Connection string"

### 3. Environment Configuration

Create a `.env` file in the project root:

```bash
cp .env.example .env
```

Edit `.env` and add your Azure credentials:

```env
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=YOUR_ACCOUNT;AccountKey=YOUR_KEY;EndpointSuffix=core.windows.net
AZURE_CONTAINER_NAME=media-files
```

### 4. Run the Application

```bash
python main.py
```

Or with uvicorn directly:

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at: `http://localhost:8000`

## 📚 API Endpoints

### Upload Media
```http
POST /upload
Content-Type: multipart/form-data

file: <binary>
```

**Response:**
```json
{
  "success": true,
  "media_id": "uuid-string",
  "filename": "video.mp4",
  "size": 1048576,
  "content_type": "video/mp4",
  "stream_url": "/stream/uuid-string"
}
```

### Stream Media
```http
GET /stream/{media_id}
```

Supports HTTP Range requests for video seeking. Returns streaming content with headers that prevent downloads.

### Get Media Info
```http
GET /media/{media_id}
```

**Response:**
```json
{
  "media_id": "uuid-string",
  "filename": "video.mp4",
  "content_type": "video/mp4",
  "size": 1048576,
  "upload_time": "2026-01-22T10:30:00",
  "media_type": "video"
}
```

### List All Media
```http
GET /media/list
```

**Response:**
```json
{
  "total": 2,
  "media": [
    {
      "media_id": "uuid-1",
      "filename": "video.mp4",
      "size": 1048576,
      "upload_time": "2026-01-22T10:30:00",
      "media_type": "video",
      "stream_url": "/stream/uuid-1"
    }
  ]
}
```

### Delete Media
```http
DELETE /media/{media_id}
```

**Response:**
```json
{
  "success": true,
  "message": "Media uuid-string deleted successfully"
}
```

## 🎨 Web Client

Open `client.html` in your browser to access the web interface:

```bash
# Start a simple HTTP server (if API is running separately)
python -m http.server 8080
```

Then navigate to: `http://localhost:8080/client.html`

### Features:
- Drag-and-drop file upload
- Upload progress indicator
- Video/audio player with controls
- Image viewer
- Media library with play and delete options
- Right-click protection to prevent downloads

## 🔒 Security Features

### Download Prevention

1. **Content-Disposition Header**: Set to "inline" to prevent download dialogs
2. **controlsList Attribute**: Prevents download button in video/audio players
3. **Right-Click Protection**: JavaScript blocks context menu on media elements
4. **Cache Control**: Prevents caching with no-cache headers

### Additional Security Recommendations

1. **Enable CORS properly** in production:
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://yourdomain.com"],  # Specify your domain
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)
```

2. **Add Authentication**: Implement JWT or OAuth2 authentication:
```python
from fastapi.security import HTTPBearer

security = HTTPBearer()

@app.post("/upload")
async def upload_media(
    file: UploadFile = File(...),
    credentials: str = Depends(security)
):
    # Verify token
    pass
```

3. **Add Rate Limiting**: Use slowapi or similar:
```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

@app.post("/upload")
@limiter.limit("5/minute")
async def upload_media(...):
    pass
```

4. **Add File Size Limits**:
```python
@app.post("/upload")
async def upload_media(file: UploadFile = File(..., max_size=100*1024*1024)):  # 100MB
    pass
```

## 🏗️ Architecture

```
┌─────────────┐      ┌──────────────┐      ┌─────────────────┐
│   Client    │─────▶│   FastAPI    │─────▶│ Azure Blob      │
│  (Browser)  │◀─────│   Backend    │◀─────│ Storage         │
└─────────────┘      └──────────────┘      └─────────────────┘
                            │
                            ▼
                     ┌──────────────┐
                     │  Streaming   │
                     │  Response    │
                     └──────────────┘
```

## 📝 Supported File Types

### Video
- MP4, AVI, MOV, WMV, FLV, WebM, MKV

### Audio
- MP3, WAV, OGG, M4A, FLAC

### Images
- JPG, JPEG, PNG, GIF, WebP, BMP

## 🐛 Troubleshooting

### Connection String Issues
```bash
# Verify your connection string format
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=myaccount;AccountKey=mykey;EndpointSuffix=core.windows.net
```

### CORS Errors
- Make sure the API is running on `localhost:8000`
- Check browser console for specific CORS errors
- Verify CORS middleware configuration

### Upload Fails
- Check Azure Storage account permissions
- Verify container exists
- Check file size limits
- Verify network connectivity to Azure

### Streaming Issues
- Ensure content-type is set correctly
- Check browser support for media format
- Verify range request headers

## 🚀 Production Deployment

### Using Docker

Create `Dockerfile`:
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Build and run:
```bash
docker build -t media-api .
docker run -p 8000:8000 --env-file .env media-api
```

### Using Azure App Service

```bash
# Login to Azure
az login

# Create resource group
az group create --name media-api-rg --location eastus

# Create App Service plan
az appservice plan create --name media-api-plan --resource-group media-api-rg --sku B1 --is-linux

# Create web app
az webapp create --resource-group media-api-rg --plan media-api-plan --name my-media-api --runtime "PYTHON|3.11"

# Configure environment variables
az webapp config appsettings set --resource-group media-api-rg --name my-media-api --settings AZURE_STORAGE_CONNECTION_STRING="your-connection-string"

# Deploy code
az webapp up --name my-media-api
```

## 📊 Performance Optimization

1. **Enable CDN**: Use Azure CDN for faster global delivery
2. **Compression**: Enable gzip compression for API responses
3. **Caching**: Implement Redis caching for media metadata
4. **Async Operations**: Use async/await throughout for better performance
5. **Connection Pooling**: Azure SDK handles connection pooling automatically

## 📄 License

MIT License - feel free to use this in your projects!

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📧 Support

For issues and questions, please open an issue on the repository.
# scmc-video-upload-api
