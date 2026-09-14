import os
import re
import time
import json
import hashlib
import functools
from flask import Flask, render_template, request, redirect, url_for, session, jsonify

app = Flask(__name__)
app.secret_key = os.environ.get("QDT_SECRET_KEY", "qdt-quadrant-time-secret-key")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)

ADMIN_NAME = "admin"
ADMIN_PASSWORD = "admin"  # 管理员 json 缺失时自动重建使用的默认密码
DEFAULT_QUADRANTS = ["重要且紧急", "重要不紧急", "紧急不重要", "不紧急不重要"]

CONFIG_FILE = os.path.join(DATA_DIR, "config.json")

# 用户名格式：2-20位字母数字下划线中划线，不允许点号与保留名
USERNAME_RE = re.compile(r"^[A-Za-z0-9_\-]{2,20}$")
RESERVED_NAMES = {"admin", "config"}

# 限流状态（内存级）：登录/注册 60秒内最多5次；密码类操作 60秒内最多10次
_rate = {}
RATE_LIMITS = {
    "auth": (5, 60),
    "pwd": (10, 60),
}


def rate_limited(kind):
    limit, window = RATE_LIMITS[kind]
    now = time.time()
    hits = [t for t in _rate.get(kind, []) if now - t < window]
    _rate[kind] = hits
    if len(hits) >= limit:
        return True
    hits.append(now)
    _rate[kind] = hits
    return False


def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def registration_enabled():
    return load_config().get("registration_enabled", True)


def get_footer():
    """全站页脚文案（管理员在后台设置，可为空）"""
    return load_config().get("footer", "")


def set_registration_enabled(enabled):
    cfg = load_config()
    cfg["registration_enabled"] = bool(enabled)
    save_config(cfg)


def get_salt():
    cfg = load_config()
    salt = cfg.get("salt")
    if not salt:
        salt = hashlib.sha256(os.urandom(32)).hexdigest()
        cfg["salt"] = salt
        save_config(cfg)
    return salt


def hash_password(password):
    """带盐 SHA256"""
    return hashlib.sha256((get_salt() + password).encode("utf-8")).hexdigest()


def user_file(username):
    return os.path.join(DATA_DIR, f"{username}.json")


def valid_username(name):
    return bool(USERNAME_RE.match(name)) and name not in RESERVED_NAMES


def load_user(username):
    # 只校验格式（合法保留名如 admin 本身也是真实账户，必须能加载）
    if not USERNAME_RE.match(username):
        return None
    path = user_file(username)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None  # 文件损坏时按不存在处理，避免 500
    return None


def save_user(username, data):
    with open(user_file(username), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def new_user_data(username):
    return {"username": username, "password_hash": None, "session_token": None,
            "quadrants": DEFAULT_QUADRANTS, "tasks": []}


def new_session_token():
    return hashlib.sha256(os.urandom(16)).hexdigest()


def ensure_admin():
    if load_user(ADMIN_NAME) is None:
        data = new_user_data(ADMIN_NAME)
        data["password_hash"] = hash_password(ADMIN_PASSWORD)
        data["session_token"] = new_session_token()
        save_user(ADMIN_NAME, data)


ensure_admin()


@app.before_request
def ensure_admin_exists():
    """运行时检测：admin.json 缺失则自动重建（默认密码 admin），无需重启服务"""
    if not os.path.exists(user_file(ADMIN_NAME)):
        ensure_admin()


def login_required(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        user = load_user(session.get("username", ""))
        if user is None or user.get("session_token") != session.get("token"):
            session.clear()
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


def admin_required(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        user = load_user(session.get("username", "")) if session.get("logged_in") else None
        if (user is None or user.get("session_token") != session.get("token")
                or session.get("username") != ADMIN_NAME):
            return jsonify({"ok": False, "msg": "需要管理员权限"}), 403
        return fn(*args, **kwargs)
    return wrapper


@app.route("/")
@login_required
def index():
    user = load_user(session["username"])
    if user is None:
        session.clear()
        return redirect(url_for("login"))
    return render_template("index.html", username=session["username"], is_admin=session.get("is_admin", False), footer=get_footer())


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if rate_limited("auth"):
            return render_template("login.html", error="尝试次数过多，请60秒后再试", footer=get_footer())
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = load_user(username)
        if user and user.get("password_hash") == hash_password(password):
            # 轮换 session 与令牌，防止 session fixation 与旧会话残留
            token = new_session_token()
            user["session_token"] = token
            save_user(username, user)
            session.clear()
            session["logged_in"] = True
            session["username"] = username
            session["is_admin"] = (username == ADMIN_NAME)
            session["token"] = token
            return redirect(url_for("index"))
        return render_template("login.html", error="用户名或密码错误", footer=get_footer())
    return render_template("login.html", footer=get_footer())


@app.route("/register", methods=["GET", "POST"])
def register():
    if not registration_enabled():
        if request.method == "POST":
            return render_template("register.html", error="注册功能已关闭", footer=get_footer())
        return render_template("register.html", closed=True, footer=get_footer())
    if request.method == "POST":
        if rate_limited("auth"):
            return render_template("register.html", error="尝试次数过多，请60秒后再试", footer=get_footer())
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        if not username or not password:
            return render_template("register.html", error="用户名和密码不能为空", footer=get_footer())
        if not valid_username(username):
            return render_template("register.html", error="用户名须为2-20位字母、数字或_、-，且不可使用保留名", footer=get_footer())
        if len(password) < 6:
            return render_template("register.html", error="密码长度不能少于6位", footer=get_footer())
        if password != confirm:
            return render_template("register.html", error="两次输入的密码不一致", footer=get_footer())
        if load_user(username) is not None:
            return render_template("register.html", error="该用户名已存在", footer=get_footer())
        data = new_user_data(username)
        data["password_hash"] = hash_password(password)
        save_user(username, data)
        return redirect(url_for("login"))
    return render_template("register.html", footer=get_footer())


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/api/password", methods=["POST"])
@login_required
def change_password():
    if rate_limited("pwd"):
        return jsonify({"ok": False, "msg": "操作过于频繁，请稍后再试"}), 429
    username = session["username"]
    user = load_user(username)
    if user is None:
        return jsonify({"ok": False, "msg": "用户不存在"}), 404
    payload = request.get_json(force=True)
    old = payload.get("old_password") or ""
    new = payload.get("new_password") or ""
    if user.get("password_hash") != hash_password(old):
        return jsonify({"ok": False, "msg": "原密码不正确"})
    if len(new) < 6:
        return jsonify({"ok": False, "msg": "新密码长度不能少于6位"})
    user["password_hash"] = hash_password(new)
    # 轮换令牌：其他设备上的旧会话立即失效
    user["session_token"] = new_session_token()
    save_user(username, user)
    session["token"] = user["session_token"]
    return jsonify({"ok": True, "msg": "密码修改成功"})


@app.route("/api/account", methods=["POST"])
@login_required
def change_account():
    if rate_limited("pwd"):
        return jsonify({"ok": False, "msg": "操作过于频繁，请稍后再试"}), 429
    username = session["username"]
    if username == ADMIN_NAME:
        return jsonify({"ok": False, "msg": "管理员不可修改用户名"})
    user = load_user(username)
    if user is None:
        return jsonify({"ok": False, "msg": "用户不存在"}), 404
    payload = request.get_json(force=True)
    old = payload.get("old_password") or ""
    new_username = (payload.get("new_username") or "").strip()
    new_password = payload.get("new_password") or ""
    if user.get("password_hash") != hash_password(old):
        return jsonify({"ok": False, "msg": "原密码不正确"})
    if new_password and len(new_password) < 6:
        return jsonify({"ok": False, "msg": "新密码长度不能少于6位"})
    if new_username and new_username != username:
        if not valid_username(new_username):
            return jsonify({"ok": False, "msg": "新用户名须为2-20位字母、数字或_、-，且不可使用保留名"})
        if load_user(new_username) is not None:
            return jsonify({"ok": False, "msg": "该用户名已存在"})
        user["username"] = new_username
        save_user(new_username, user)
        if os.path.exists(user_file(username)) and username != new_username:
            os.remove(user_file(username))
        session["username"] = new_username
    if new_password:
        user["password_hash"] = hash_password(new_password)
    # 轮换令牌：改名/改密后其他设备上的旧会话立即失效
    user["session_token"] = new_session_token()
    save_user(session["username"], user)
    session["token"] = user["session_token"]
    return jsonify({"ok": True, "msg": "账户修改成功", "username": session["username"]})


@app.route("/api/tasks", methods=["GET"])
@login_required
def get_tasks():
    user = load_user(session["username"])
    if user is None:
        return jsonify({"ok": False}), 404
    return jsonify({"ok": True, "tasks": user["tasks"], "quadrants": user["quadrants"]})


@app.route("/api/tasks", methods=["POST"])
@login_required
def add_task():
    user = load_user(session["username"])
    if user is None:
        return jsonify({"ok": False}), 404
    payload = request.get_json(force=True)
    title = (payload.get("title") or "").strip()
    quadrant = (payload.get("quadrant") or "").strip()
    if not title:
        return jsonify({"ok": False, "msg": "任务内容不能为空"})
    if quadrant not in user["quadrants"]:
        return jsonify({"ok": False, "msg": "无效的象限"})
    user["tasks"].append({"id": len(user["tasks"]) + 1, "title": title, "quadrant": quadrant, "completed": False})
    save_user(session["username"], user)
    return jsonify({"ok": True})


@app.route("/api/tasks/<int:task_id>/toggle", methods=["POST"])
@login_required
def toggle_task(task_id):
    """切换任务完成状态（打钩/取消，不删除）"""
    user = load_user(session["username"])
    if user is None:
        return jsonify({"ok": False}), 404
    task = next((t for t in user["tasks"] if t["id"] == task_id), None)
    if task is None:
        return jsonify({"ok": False, "msg": "任务不存在"}), 404
    task["completed"] = not bool(task.get("completed", False))
    save_user(session["username"], user)
    return jsonify({"ok": True, "completed": task["completed"]})


@app.route("/api/tasks/<int:task_id>", methods=["PUT"])
@login_required
def update_task(task_id):
    user = load_user(session["username"])
    if user is None:
        return jsonify({"ok": False}), 404
    task = next((t for t in user["tasks"] if t["id"] == task_id), None)
    if task is None:
        return jsonify({"ok": False, "msg": "任务不存在"})
    payload = request.get_json(force=True)
    title = (payload.get("title") or "").strip()
    quadrant = (payload.get("quadrant") or "").strip()
    if not title:
        return jsonify({"ok": False, "msg": "任务内容不能为空"})
    if quadrant not in user["quadrants"]:
        return jsonify({"ok": False, "msg": "无效的象限"})
    task["title"] = title
    task["quadrant"] = quadrant
    save_user(session["username"], user)
    return jsonify({"ok": True})


@app.route("/api/tasks/<int:task_id>", methods=["DELETE"])
@login_required
def delete_task(task_id):
    user = load_user(session["username"])
    if user is None:
        return jsonify({"ok": False}), 404
    user["tasks"] = [t for t in user["tasks"] if t["id"] != task_id]
    save_user(session["username"], user)
    return jsonify({"ok": True})


@app.route("/api/users", methods=["GET"])
@admin_required
def list_users():
    users = []
    for name in sorted(os.listdir(DATA_DIR)):
        if name.endswith(".json") and name != "config.json":
            uname = name[:-5]
            # 显示所有格式合法的用户（含 admin，前端有禁用删除按钮）
            if USERNAME_RE.match(uname) and uname != "config":
                users.append(uname)
    return jsonify({"ok": True, "users": users, "self": session.get("username")})


@app.route("/api/users/<username>", methods=["DELETE"])
@admin_required
def delete_user(username):
    # 严格校验：只允许删除合法格式的、真实存在的用户文件
    # 杜绝通过净化碰撞（如 ad!min -> admin.json）删除保留账户
    if username == ADMIN_NAME:
        return jsonify({"ok": False, "msg": "不能删除管理员账户"}), 403
    if not valid_username(username):
        return jsonify({"ok": False, "msg": "用户名不存在"}), 404
    path = user_file(username)
    # 最终防线：确认路径必须位于 DATA_DIR 内且是存在的普通文件
    real = os.path.realpath(path)
    if not real.startswith(os.path.realpath(DATA_DIR) + os.sep) or not os.path.isfile(real):
        return jsonify({"ok": False, "msg": "用户不存在"}), 404
    if load_user(username) is None:
        return jsonify({"ok": False, "msg": "用户不存在"}), 404
    os.remove(real)
    return jsonify({"ok": True})


@app.route("/api/registration", methods=["GET", "POST"])
@admin_required
def toggle_registration():
    if request.method == "POST":
        payload = request.get_json(force=True)
        enabled = bool(payload.get("enabled"))
        set_registration_enabled(enabled)
        return jsonify({"ok": True, "enabled": enabled, "msg": "注册功能已" + ("开启" if enabled else "关闭")})
    return jsonify({"ok": True, "enabled": registration_enabled()})


@app.route("/api/footer", methods=["GET", "PUT"])
@admin_required
def save_footer():
    """管理员设置全站页脚文案（纯文本，前端自动转义）"""
    if request.method == "PUT":
        payload = request.get_json(force=True)
        footer = (payload.get("footer") or "").strip()[:200]  # 限制长度，防滥用
        cfg = load_config()
        cfg["footer"] = footer
        save_config(cfg)
        return jsonify({"ok": True, "footer": footer, "msg": "页脚已保存"})
    return jsonify({"ok": True, "footer": load_config().get("footer", "")})


@app.errorhandler(404)
def not_found(e):
    return "404 - 页面不存在", 404


@app.errorhandler(405)
def method_not_allowed(e):
    return "405 - 方法不允许", 405


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
