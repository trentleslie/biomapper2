# Biomapper2 API Deployment

This directory contains deployment configuration for the Biomapper2 REST API.

## AWS Lightsail Deployment

The API is deployed to the same Lightsail instance as kraken-backend:

| Property | Value |
|----------|-------|
| Instance | `expert-in-the-loop-upgraded` |
| IP | `35.161.242.62` |
| SSH | `ssh -i ~/.ssh/lightsail-expert.pem ubuntu@35.161.242.62` |
| Port | `8001` |
| URL | `https://biomapper.expertintheloop.io` |

## Initial Setup

1. **Clone the repository on the server:**
   ```bash
   ssh -i ~/.ssh/lightsail-expert.pem ubuntu@35.161.242.62
   cd ~
   git clone https://github.com/Phenome-Health/biomapper2.git
   cd biomapper2
   ```

2. **Create environment file:**
   ```bash
   cat > .env << 'EOF'
   KESTREL_API_KEY=your-kestrel-api-key
   BIOMAPPER_API_KEY=your-biomapper-api-key
   EOF
   ```

3. **Install uv and dependencies:**
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   source ~/.bashrc
   uv sync
   ```

4. **Install and start the service:**
   ```bash
   sudo cp deploy/biomapper2-api.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable biomapper2-api
   sudo systemctl start biomapper2-api
   ```

5. **Configure nginx:**
   Add to `/etc/nginx/sites-available/default`:
   ```nginx
   server {
       listen 80;
       server_name biomapper.expertintheloop.io;

       location / {
           proxy_pass http://127.0.0.1:8001;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
       }
   }
   ```

6. **Get SSL certificate:**
   ```bash
   sudo certbot --nginx -d biomapper.expertintheloop.io
   ```

## GitHub Actions Secrets

The deployment workflow requires these secrets:

- `LIGHTSAIL_HOST`: Server IP address
- `LIGHTSAIL_SSH_KEY`: Private SSH key for the server

## Service Management

```bash
# Check status
sudo systemctl status biomapper2-api

# View logs
sudo journalctl -u biomapper2-api -f

# Restart
sudo systemctl restart biomapper2-api

# Stop
sudo systemctl stop biomapper2-api
```

## Development API

A second API instance for testing feature branches before merging to production.

| Property | Value |
|----------|-------|
| Port | `8002` |
| Binding | `127.0.0.1` (localhost only) |
| Workers | `1` |
| Service | `biomapper2-api-dev` |
| Logs | `journalctl -t biomapper2-api-dev` |

### One-Time Server Setup

1. **Clone and configure remotes:**
   ```bash
   cd ~
   git clone https://github.com/Phenome-Health/biomapper2.git ~/biomapper2-dev
   cd ~/biomapper2-dev
   git remote add fork https://github.com/trentleslie/biomapper2.git
   ```

2. **Create environment file:**
   ```bash
   cat > .env << 'EOF'
   KESTREL_API_KEY=your-dev-kestrel-api-key
   BIOMAPPER2_API_KEYS=your-dev-api-key
   EOF
   ```
   Use a separate `KESTREL_API_KEY` from production for blast-radius isolation.

3. **Install and start the service:**
   ```bash
   sudo cp deploy/biomapper2-api-dev.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable biomapper2-api-dev
   sudo systemctl start biomapper2-api-dev
   ```

4. **Verify:**
   ```bash
   curl http://localhost:8002/api/v1/health
   journalctl -t biomapper2-api-dev --no-pager -n 5
   ```

### Deploying a Branch

Use the GitHub Actions workflow `Deploy Biomapper2 Dev API` (workflow_dispatch):
- **branch**: The branch name to deploy (default: `main`)
- **remote**: Which remote to fetch from — `origin` (Phenome-Health) or `fork` (trentleslie)

Access from your laptop via SSH tunnel:
```bash
ssh -L 8002:localhost:8002 ubuntu@<LIGHTSAIL_HOST>
# Then: curl http://localhost:8002/api/v1/health
```

### Dev Service Management

```bash
# Check status
sudo systemctl status biomapper2-api-dev

# View logs (dev only)
journalctl -t biomapper2-api-dev -f

# Restart
sudo systemctl restart biomapper2-api-dev

# Stop
sudo systemctl stop biomapper2-api-dev
```

## Local Development

```bash
# Run locally
uv run uvicorn biomapper2.api.main:app --reload --port 8001

# Test
curl http://localhost:8001/api/v1/health
```
