# 更新日志

格式说明：
- **课本更新**：人教社教材目录变化（新增/下架/更新）
- **代码更新**：功能、修复、优化等代码变更

---

## v2026-09-11

### 课本更新
- 新增 2026 年秋季学期教材
- 更新教材封面及元数据

### 代码更新
- feat: 新增 Docker Compose 部署方案 + WebUI 镜像
- feat: 新增 GitHub Actions 多平台自动构建（Windows/macOS/Linux）
- feat: 新增跨平台独立打包脚本（build_linux.py / build_macos.py）
- fix: 修复 webui.py 缺失 `import re` 问题
- chore: 使用阿里云镜像加速 Docker 构建

---

## v2026-09-10

### 课本更新
- 新增 2026 年秋季学期教材
- 更新教材封面及元数据

### 代码更新
- feat: 新增 Docker Compose 部署方案 + WebUI 镜像
- feat: 新增 GitHub Actions 多平台自动构建（Windows/macOS/Linux）
- fix: 修复 webui.py 缺失 `import re` 问题
- chore: 使用阿里云镜像加速 Docker 构建

---

## v2026-08-31

### 课本更新
- 全量教材目录同步至 2026 年秋季开学版本
- 共收录 780+ 本教材

### 代码更新
- 调整默认下载线程和等待时间
- 更新到 v1.1
- 加入命令行批量下载功能
- 优化 WAF 滑块验证绕过算法 + 自动端口回退
