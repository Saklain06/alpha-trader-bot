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

## ⚡ Quick Start (Automated Setup)
This is the **recommended** method for Hostinger, DigitalOcean, or AWS/Google Cloud Ubuntu servers.

1. **Connect to your VPS**:
   ```bash
   ssh root@<YOUR_SERVER_IP>
   ```

2. **Clone your repository**:
   ```bash
   git clone <YOUR_REPO_URL> alpha_bot
   cd alpha_bot
   ```

3. **Run the Setup Script**:
   ```bash
   # Make it executable
   chmod +x setup_hostinger.sh
   
   # Run the installer
   sudo bash setup_hostinger.sh
   ```
   **What this does:**
   - Updates system & firewall
   - Installs Python, Node.js, Nginx
   - Sets up the Backend Service (Systemd)
   - Sets up the Frontend Dashboard (PM2)
   - Reverse proxies everything so you can access it on Port 80

4. **Access your Dashboard**:
   - Open `http://<YOUR_SERVER_IP>` in your browser.

---

## 🛠 Manual Setup (Old Method)
If the script fails or you prefer manual control, follow these steps:

### 1. Install Dependencies
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-pip python3-venv git nodejs npm nginx ufw
npm install -g pm2
```

### 2. Setup Backend
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Start manually or copy alpha_bot.service to /etc/systemd/system/
```

### 3. Setup Frontend
```bash
cd crypto-dashboard
npm install
npm run build
pm2 start npm --name "dashboard" -- start
pm2 save
```

### 4. Firewall
```bash
ufw allow 22
ufw allow 80
ufw allow 8000
ufw enable
```

---

## 🛠 Management Commands
- **Check Bot Logs**: `journalctl -u alpha_bot -f`
- **Restart Bot**: `sudo systemctl restart alpha_bot`
- **Check Dashboard**: `pm2 status`
- **Restart Dashboard**: `pm2 restart dashboard`
