# Production Deployment & Operations Guide (`DEPLOYMENT.md`)

This guide provides the complete operational SOP for deploying and maintaining the **HackerRank Campus Crew Super Agent (`hrcc_bot`)** on the dedicated `ai-server` PC.

---

## 1. Environment & Infrastructure Topology

```
[ Discord Gateway ] ◄────── (Websocket & REST API) ──────► [ ai-server (10.1.53.27) ]
                                                                   │
                                                                   ├── [ hrcc-bot.service ]
                                                                   │   (Python discord.py bot)
                                                                   │   RAM: ~40MB
                                                                   │
                                                                   └── [ vllm.service ]
                                                                       (Port 8000 / vLLM Engine)
                                                                       Model: Llama-3.1-8B-FP8
                                                                       VRAM: ~12GB (FP8 quantized)
                                                                       Context: 32,768 tokens
```

### Server Specifications
- **Host:** `ai-server`
- **Internal IP:** `10.1.53.27`
- **SSH Access:** `ssh ai-server@10.1.53.27` (Auth via SSH Key or password `sree2007`)
- **OS:** Ubuntu 24.04 LTS Linux x86_64
- **Public Domain Routing:** Cloudflare Zero Trust Tunnel routing `https://vllm.stjosephsplacements.in` to local port `8000`.

---

## 2. vLLM Inference Service Configuration

vLLM runs as a persistent systemd service managed by systemd:

### Service File: `/etc/systemd/system/vllm.service`
```ini
[Unit]
Description=vLLM Inference Server - Meta-Llama-3.1-8B-Instruct-FP8
After=network.target nvidia-persistenced.service
Wants=network-online.target

[Service]
Type=simple
User=ai-server
WorkingDirectory=/home/ai-server
Environment="PATH=/home/ai-server/.local/bin:/usr/local/cuda/bin:/usr/bin:/bin"
Environment="CUDA_VISIBLE_DEVICES=0"
Environment="HF_HUB_ENABLE_HF_TRANSFER=0"
ExecStart=/home/ai-server/.local/bin/vllm serve neuralmagic/Meta-Llama-3.1-8B-Instruct-FP8 \
    --host 0.0.0.0 \
    --port 8000 \
    --max-model-len 32768 \
    --gpu-memory-utilization 0.90 \
    --enable-auto-tool-choice \
    --tool-call-parser llama3_json \
    --api-key Placements@sjgi#2026

Restart=always
RestartSec=5s
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
```

### Verification Command
```bash
curl -s http://127.0.0.1:8000/v1/models \
  -H "Authorization: Bearer Placements@sjgi#2026" | jq .
```
Expected output confirms `neuralmagic/Meta-Llama-3.1-8B-Instruct-FP8` is active with `max_model_len: 32768`.

---

## 3. `hrcc-bot.service` Systemd Unit Specification

When migrating from Hermes to the native Super Agent, the bot runs under systemd:

### Service File: `/etc/systemd/system/hrcc-bot.service`
```ini
[Unit]
Description=HackerRank Campus Crew Discord Super Agent
After=network.target vllm.service
Wants=network-online.target

[Service]
Type=simple
User=ai-server
WorkingDirectory=/home/ai-server/hrcc_bot
EnvironmentFile=/home/ai-server/hrcc_bot/.env
ExecStart=/home/ai-server/hrcc_bot/.venv/bin/python main.py

Restart=always
RestartSec=3s
LimitNOFILE=65535

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=hrcc-bot

[Install]
WantedBy=multi-user.target
```

---

## 4. Environment Variables (`.env`)

Store secrets strictly inside `/home/ai-server/hrcc_bot/.env` (permissions `600`):

```bash
# Discord Credentials
DISCORD_BOT_TOKEN="YOUR_DISCORD_BOT_TOKEN_HERE"
DISCORD_HOME_CHANNEL="1550794920539717638"
ALLOW_ALL_USERS=true

# vLLM Local Endpoint
VLLM_BASE_URL="http://127.0.0.1:8000/v1"
VLLM_MODEL="neuralmagic/Meta-Llama-3.1-8B-Instruct-FP8"
VLLM_API_KEY="Placements@sjgi#2026"
VLLM_TIMEOUT=30.0
VLLM_MAX_RETRIES=3

# Model Generation Parameters
MODEL_TEMPERATURE=0.1
MODEL_MAX_TOKENS=1500
CONTEXT_HISTORY_LIMIT=8
RATE_LIMIT_PER_MINUTE=15
```

---

## 5. Deployment & Migration Playbook

### Step 1: Sync Files to `ai-server`
Run from the management machine:
```bash
rsync -avz --exclude '.git' --exclude '__pycache__' \
  /data/production/hrcc_bot/ ai-server@10.1.53.27:/home/ai-server/hrcc_bot/
```

### Step 2: Virtual Environment Setup on `ai-server`
```bash
ssh ai-server@10.1.53.27
cd /home/ai-server/hrcc_bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r deploy/requirements.txt
```

### Step 3: Stop Hermes Service & Start Native Bot
```bash
# Disable Hermes Gateway
echo sree2007 | sudo -S systemctl stop hermes-gateway.service
echo sree2007 | sudo -S systemctl disable hermes-gateway.service

# Install & Start hrcc-bot Service
echo sree2007 | sudo -S cp /home/ai-server/hrcc_bot/deploy/hrcc-bot.service /etc/systemd/system/
echo sree2007 | sudo -S systemctl daemon-reload
echo sree2007 | sudo -S systemctl enable hrcc-bot.service
echo sree2007 | sudo -S systemctl restart hrcc-bot.service
```

---

## 6. Verification Checklist

1. **Service Status:**
   ```bash
   systemctl status hrcc-bot.service --no-pager
   ```
2. **Live Journal Logs:**
   ```bash
   journalctl -u hrcc-bot.service -f -o cat
   ```
3. **Discord Test Matrix:**
   - **Test 1 (Casual Chatter):** Send `"hello everyone"` in the Discord channel.  
     $\rightarrow$ Confirm bot outputs `NO_REPLY` and remains **completely silent** (no warning).
   - **Test 2 (Direct Mention):** Send `"@HackerRank Campus Crew Support hi"`.  
     $\rightarrow$ Confirm bot replies inline welcoming you and asking how it can assist your campus event.
   - **Test 3 (Handbook Query):** Send `"How do I activate prizes for my winners?"`.  
     $\rightarrow$ Confirm bot outlines submitting Full Names and HackerRank account emails to Sanskruti.
   - **Test 4 (Chakra Boundary Check):** Send `"Can I use Chakra tab in HRW?"`.  
     $\rightarrow$ Confirm bot warns that Chakra is internal-only.

---

## 7. Rollback Procedures

If an emergency rollback to Hermes is ever required:
```bash
# Stop native bot
echo sree2007 | sudo -S systemctl stop hrcc-bot.service
echo sree2007 | sudo -S systemctl disable hrcc-bot.service

# Revive Hermes Gateway
echo sree2007 | sudo -S systemctl enable hermes-gateway.service
echo sree2007 | sudo -S systemctl restart hermes-gateway.service
```
