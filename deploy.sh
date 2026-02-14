#!/bin/bash
set -euxo pipefail

echo "=== Bedrock LLM Monitor - Deploy Script ==="

APP_DIR=/home/ec2-user/model-monitoring

# 1. Install system deps
sudo dnf update -y --allowerasing
sudo dnf install -y python3 python3-pip docker

# 2. Start Docker & PostgreSQL
sudo systemctl enable --now docker
sudo usermod -aG docker ec2-user
cd $APP_DIR
sudo docker compose up -d

# Wait for Postgres to be ready
echo "Waiting for PostgreSQL..."
for i in {1..30}; do
  sudo docker exec monitoring-postgres pg_isready -U postgres && break
  sleep 2
done

# 3. Install backend deps
pip3 install --ignore-installed -r $APP_DIR/backend/requirements.txt

# 4. Install frontend deps & build
cd $APP_DIR/frontend
npm install
npm run build

# 5. Create systemd services
sudo tee /etc/systemd/system/monitor-backend.service > /dev/null << 'EOF'
[Unit]
Description=Bedrock Monitor Backend (FastAPI)
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User=ec2-user
WorkingDirectory=/home/ec2-user/model-monitoring/backend
ExecStart=/usr/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/monitor-frontend.service > /dev/null << 'EOF'
[Unit]
Description=Bedrock Monitor Frontend (Next.js)
After=network.target monitor-backend.service

[Service]
Type=simple
User=ec2-user
WorkingDirectory=/home/ec2-user/model-monitoring/frontend
ExecStart=/usr/bin/node node_modules/.bin/next start -p 3000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# 6. Start services
sudo systemctl daemon-reload
sudo systemctl enable --now monitor-backend
sudo systemctl enable --now monitor-frontend

echo "=== Deploy complete ==="
echo "Backend: http://localhost:8000"
echo "Frontend: http://localhost:3000"
