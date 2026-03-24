# Docker Deployment Guide

## Quick Start with Docker

### Prerequisites
- Docker Desktop installed
- YOUTUBE_API_KEY available

### Option 1: Docker Compose (Recommended)

```bash
# 1. Create .env file with YouTube API key
echo "YOUTUBE_API_KEY=your_api_key_here" >> .env

# 2. Start the service
docker-compose up -d

# 3. Wait for services to be healthy (30-60 seconds)
docker-compose ps

# 4. Access the app
open http://localhost:8000

# 5. View logs
docker-compose logs -f app

# 6. Stop the service
docker-compose down
```

### Option 2: Manual Docker Build

```bash
# 1. Build the image
docker build -t youtube-analysis:latest .

# 2. Start PostgreSQL container
docker run -d \
  --name youtube-analysis-db \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=techdb \
  -p 5432:5432 \
  postgres:15-alpine

# 3. Run the app container
docker run -d \
  --name youtube-analysis-app \
  -e DATABASE_URL=postgresql://postgres:postgres@youtube-analysis-db:5432/techdb \
  -e YOUTUBE_API_KEY=your_api_key_here \
  -p 8000:8000 \
  --link youtube-analysis-db \
  youtube-analysis:latest

# 4. Access the app
open http://localhost:8000

# 5. View logs
docker logs -f youtube-analysis-app

# 6. Stop containers
docker stop youtube-analysis-app youtube-analysis-db
docker rm youtube-analysis-app youtube-analysis-db
```

## Environment Variables

```env
YOUTUBE_API_KEY=your_youtube_api_key_here
DATABASE_URL=postgresql://postgres:postgres@postgres:5432/techdb  # Docker Compose
```

## Docker Commands Reference

### View Container Status
```bash
docker-compose ps
```

### View Application Logs
```bash
docker-compose logs -f app      # Follow app logs
docker-compose logs app -n 100  # Last 100 lines
```

### Access PostgreSQL
```bash
docker-compose exec postgres psql -U postgres -d techdb

# Example queries
\dt              # List tables
SELECT * FROM tech_products;
SELECT * FROM videos;
```

### Restart Services
```bash
docker-compose restart
```

### Rebuild on Code Changes
```bash
docker-compose down
docker-compose up -d --build
```

### Remove Everything
```bash
docker-compose down -v  # -v removes volumes (database)
```

## Production Deployment

### On Linux Server (Ubuntu)

```bash
# 1. Install Docker
sudo apt-get update
sudo apt-get install docker.io docker-compose

# 2. Clone repository
git clone <repo> youtube-analysis
cd youtube-analysis

# 3. Create environment
cp .env.example .env
nano .env  # Add YOUTUBE_API_KEY

# 4. Start service
sudo docker-compose up -d

# 5. Check status
sudo docker-compose ps
sudo docker-compose logs app

# 6. Enable auto-restart
sudo docker-compose down
sudo docker-compose up -d --restart unless-stopped
```

### With Nginx Reverse Proxy

```bash
# Install nginx
sudo apt-get install nginx

# Configure /etc/nginx/sites-available/youtube-analysis
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

# Enable site
sudo ln -s /etc/nginx/sites-available/youtube-analysis /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

### With SSL (Let's Encrypt)

```bash
# Install certbot
sudo apt-get install certbot python3-certbot-nginx

# Get certificate
sudo certbot certonly --standalone -d your-domain.com

# Update nginx config to use SSL
# Then run: sudo systemctl restart nginx
```

## Monitoring

### Check Container Health
```bash
docker-compose ps
```

### Monitor Resource Usage
```bash
docker stats youtube-analysis-app
```

### View Application Logs
```bash
docker-compose logs app --follow
```

### Access PostgreSQL Directly
```bash
docker-compose exec postgres psql -U postgres -d techdb
\dt  # List all tables
```

## Troubleshooting

### App won't start
```bash
# Check logs
docker-compose logs app

# Common issues:
# 1. YOUTUBE_API_KEY not set
# 2. PostgreSQL not ready (wait 30 seconds)
# 3. Port 8000 already in use (change docker-compose.yml)
```

### PostgreSQL connection failed
```bash
# Wait for health check
docker-compose ps

# Manually check connection
docker-compose exec postgres psql -U postgres -d techdb -c "SELECT 1;"
```

### Database errors
```bash
# Destroy and recreate
docker-compose down -v
docker-compose up -d
```

### View startup logs
```bash
docker-compose logs app --tail 50
```

## Files Included

- **docker-compose.yml** - Multi-container orchestration
- **Dockerfile** - Application container definition

## Directory Structure

```
.
├── main_youtube_analysis.py
├── requirements.txt
├── .env
├── docker-compose.yml
├── Dockerfile
├── templates/
└── README.md
```

---

Last Updated: March 2026
