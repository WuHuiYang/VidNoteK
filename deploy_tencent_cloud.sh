#!/bin/bash
# 腾讯云部署脚本 - VidNoteK
# 使用方法：chmod +x deploy_tencent_cloud.sh && ./deploy_tencent_cloud.sh

echo "🚀 开始部署 VidNoteK 到腾讯云..."

# 1. 停止旧容器
echo "📦 停止旧容器..."
docker-compose down

# 2. 拉取最新代码
echo "📥 拉取最新代码..."
git pull

# 3. 重新构建镜像
echo "🔨 重新构建镜像..."
docker-compose build --no-cache

# 4. 启动服务
echo "🚀 启动服务..."
docker-compose up -d

# 5. 查看日志
echo "📋 查看启动日志..."
docker-compose logs -f --tail=50
