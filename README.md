# QDT

QDT 是一个基于 Python Flask 开发的极简主义时间管理工具，旨在通过经典的四象限法则（艾森豪威尔矩阵）帮助用户理清工作优先级，提升执行效率。

QDT is a minimalist time management tool built with Python Flask, designed to help users sort out work priorities and improve execution efficiency through the classic Four Quadrant Method (Eisenhower Matrix).

## 功能 Features

- 四象限任务管理：重要且紧急 / 重要不紧急 / 紧急不重要 / 不紧急不重要
- 任务添加、编辑、删除、完成打钩
- 用户注册 / 登录，会话令牌轮换
- 管理员后台：用户管理、开关注册、全站页脚
- 数据以 JSON 文件持久化，轻量无数据库
- 登录/注册限流，防止暴力尝试

- Four-quadrant task management: Important & Urgent / Important & Not Urgent / Urgent & Not Important / Not Urgent & Not Important
- Add, edit, delete, and check off tasks
- User registration / login with session token rotation
- Admin backend: user management, registration toggle, site-wide footer
- JSON file-based persistence, lightweight with no database
- Rate limiting on login/registration to deter brute-force attempts

## 部署 Deployment

### 本地运行 Local Run

需要 Python 3.x 环境。Requires Python 3.x.

```bash
# 安装依赖 Install the dependency
pip install flask

# 启动服务（默认 http://127.0.0.1:5000）Start the server (default http://127.0.0.1:5000)
python app.py
```

### 环境变量 Environment Variable

| 变量 Variable | 说明 Description |
| --- | --- |
| `QDT_SECRET_KEY` | Flask 会话签名密钥。生产环境务必设置一个随机强值。Flask session signing key. Set a strong random value in production. |

```bash
# Linux / macOS
export QDT_SECRET_KEY="your-random-secret"
python app.py

# Windows PowerShell
$env:QDT_SECRET_KEY = "your-random-secret"
python app.py
```

### 生产环境 Production (Gunicorn)

Linux/macOS 下推荐用 Gunicorn 作为 WSGI 服务器：Recommended Gunicorn as the WSGI server on Linux/macOS:

```bash
pip install gunicorn
QDT_SECRET_KEY="your-random-secret" gunicorn -w 2 -b 127.0.0.1:5000 app:app
```

如需对外访问，请置于 Nginx 等反向代理之后并启用 HTTPS。For public access, put it behind a reverse proxy such as Nginx with HTTPS enabled.

### 数据与备份 Data & Backup

所有用户数据保存在 `data/` 目录（每个用户一个 JSON 文件）。备份该目录即可；迁移时原样复制。All user data is stored in the `data/` directory (one JSON file per user). Back up that directory; copy it as-is when migrating.

首次启动会自动创建管理员账户（用户名 `admin`，默认密码 `admin`），请登录后立即修改。On first start, an admin account is created automatically (username `admin`, default password `admin`) — change the password after logging in.
