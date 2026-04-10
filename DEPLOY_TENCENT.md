# 🚀 VidNoteK 腾讯云部署指南

> **项目**: VidNoteK - 视频笔记AI助手  
> **部署目标**: 腾讯云服务器

---

## 📋 部署准备

### **服务器要求**
- **操作系统**: Ubuntu 20.04+ / CentOS 7+
- **CPU**: 2核+
- **内存**: 4GB+
- **磁盘**: 40GB+
- **网络**: 公网IP，带宽≥5Mbps

### **所需软件**
- Docker 20.10+
- Docker Compose 2.0+
- Git

---

## 🔧 部署步骤

### **第一步：登录服务器**

```bash
ssh root@your_server_ip
```

### **第二步：安装 Docker**

```bash
# 安装 Docker
curl -fsSL https://get.docker.com | bash -s docker --mirror Aliyun

# 启动 Docker
systemctl start docker
systemctl enable docker

# 安装 Docker Compose
curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose
```

### **第三步：克隆项目**

```bash
# 安装 Git
apt update && apt install -y git

# 克隆项目
cd /opt
git clone https://github.com/bcefghj/noteking.git vidnotek
cd vidnotek
```

### **第四步：配置环境变量**

```bash
# 创建 .env 文件
cat > .env << 'EOF'
# VidNoteK 环境配置

# LLM API 配置（DeepSeek）
NOTEKING_LLM_API_KEY=sk-540e2090a30e473dbd7b7017bd0127bc
NOTEKING_LLM_BASE_URL=https://api.deepseek.com
NOTEKING_LLM_MODEL=deepseek-chat

# 可选：B站 SESSDATA（如需下载B站视频）
# BILIBILI_SESSDATA=你的SESSDATA

# 可选：代理配置
# NOTEKING_PROXY=socks5://127.0.0.1:7890
EOF
```

### **第五步：启动服务**

```bash
# 构建并启动
docker-compose up -d

# 查看日志
docker-compose logs -f
```

### **第六步：验证部署**

```bash
# 检查服务状态
docker-compose ps

# 测试 API
curl http://localhost:8000/health

# 测试前端
curl http://localhost:3000
```

---

## 🌐 配置域名（可选）

### **使用 Nginx 反向代理**

```bash
# 安装 Nginx
apt install -y nginx

# 配置文件
cat > /etc/nginx/sites-available/vidnotek << 'EOF'
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    location /api/ {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
EOF

# 启用配置
ln -s /etc/nginx/sites-available/vidnotek /etc/nginx/sites-enabled/
nginx -t
systemctl reload nginx
```

---

## 🔐 配置 SSL 证书（可选）

### **使用 Let's Encrypt**

```bash
# 安装 Certbot
apt install -y certbot python3-certbot-nginx

# 申请证书
certbot --nginx -d your-domain.com

# 自动续期
certbot renew --dry-run
```

---

## 📊 监控和日志

### **查看服务状态**

```bash
# 查看容器状态
docker-compose ps

# 查看实时日志
docker-compose logs -f

# 查看后端日志
docker-compose logs -f api

# 查看前端日志
docker-compose logs -f web
```

### **日志管理**

```bash
# 配置日志轮换
cat > /etc/logrotate.d/vidnotek << 'EOF'
/opt/vidnotek/logs/*.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
}
EOF
```

---

## 🔄 更新部署

### **一键更新脚本**

```bash
#!/bin/bash
# 使用方法：./update.sh

echo "🔄 更新 VidNoteK..."

# 1. 备份当前版本
echo "💾 备份当前版本..."
docker-compose down
cp -r . ../vidnotek-backup-$(date +%Y%m%d)

# 2. 拉取最新代码
echo "📥 拉取最新代码..."
git pull

# 3. 重新构建
echo "🔨 重新构建..."
docker-compose build

# 4. 重启服务
echo "🚀 重启服务..."
docker-compose up -d

echo "✅ 更新完成！"
```

---

## 🎯 部署后配置

### **防火墙配置**

```bash
# 开放必要端口
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 22/tcp
ufw enable
```

### **性能优化**

```bash
# 限制日志大小
echo "max-size=100m" >> /etc/docker/daemon.json

# 重启 Docker
systemctl restart docker
```

---

## 🐛 故障排查

### **问题1：容器启动失败**

```bash
# 查看详细日志
docker-compose logs api
docker-compose logs web

# 检查配置
docker-compose config
```

### **问题2：API 无法访问**

```bash
# 检查端口占用
netstat -tunlp | grep 8000

# 检查防火墙
ufw status
```

### **问题3：前端无法连接后端**

```bash
# 检查网络
docker-compose exec web ping api

# 查看环境变量
docker-compose exec web env | grep API_URL
```

---

## 📈 性能调优

### **优化 Docker 资源限制**

```yaml
# docker-compose.yml
services:
  api:
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 2G
        reservations:
          memory: 512M
  
  web:
    deploy:
      resources:
        limits:
          cpus: '1.0'
          memory: 1G
```

---

## 🎉 部署成功

部署完成后，访问：

- **Web 界面**: http://150.158.123.30:3000
- **API 文档**: http://150.158.123.30:3000/docs
- **健康检查**: http://150.158.123.30:3000/health

---

**文档版本**: v1.0
**更新时间**: 2026-04-10
