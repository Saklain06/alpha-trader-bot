# 🌐 Free Cloud Deployment Guide

Yes! You can run this bot 24/7 for **FREE** using the "Always Free" tiers from major cloud providers.
This guide walks you through moving your bot from your laptop to a Cloud Server (VPS).

## 🏆 Recommended Free Options

| Provider | Free Tier Config | Best For... | Notes |
|---|---|---|---|
| **Oracle Cloud** | **4 Core ARM, 24GB RAM** | ✅ Performance | "Always Free" but registration can be strict. |
| **AWS** | **t2.micro / t3.micro** | ✅ Reliability | Free for **12 months** only. |
| **Google Cloud** | **e2-micro (2 vCPU, 1GB RAM)** | ✅ Simplicity | "Always Free" in US regions. Tight on RAM. |

---

## 🚀 Step 1: Prepare Your Code
Push your code to a private GitHub repository so you can easily pull it onto the server.

1. **Create a Repository** on GitHub.
2. **Push Code**:
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin <YOUR_REPO_URL>
   git push -u origin main
   ```

## ☁️ Step 2: Set Up the Server
*(Example assumes Ubuntu 22.04 LTS)*

1. **Sign up** for one of the providers above.
2. **Create a VM Instance** (use Ubuntu 22.04).
3. **Connect via SSH**:
   ```bash
   ssh ubuntu@<YOUR_SERVER_IP>
   ```

## ⚙️ Step 3: Install Dependencies
Run these commands on your new server to set up the environment:

```bash
# 1. Update System
sudo apt update && sudo apt upgrade -y

# 2. Install Python & Pip
sudo apt install -y python3-pip python3-venv git

# 3. Install Node.js (for Dashboard)
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install -y nodejs
```

## 📥 Step 4: Deploy Bot
1. **Clone your repository**:
   ```bash
   git clone <YOUR_REPO_URL> bot
   cd bot
   ```
2. **Set up Python Environment**:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
3. **Set up Dashboard**:
   ```bash
   cd crypto-dashboard
   npm install
   npm run build
   cd ..
   ```
4. **Configure Secrets**:
   - Create your `.env` file with your API keys.
   ```bash
   nano .env
   # Paste your API keys here
   # Press Ctrl+X, then Y, then Enter to save
   ```

## 🟢 Step 5: Start 24/7 Service
I have already created the service scripts for you!

```bash
# Install the background service
sudo bash install_service.sh
```

**That's it! Your bot is now running 24/7 in the cloud.** 🚀

---

## 🛠 Management Commands
- **Check Logs**: `journalctl -u alpha_bot -f`
- **Stop**: `sudo systemctl stop alpha_bot`
- **Restart**: `sudo systemctl restart alpha_bot`
