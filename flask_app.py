import os
import json
import sqlite3
import secrets
import hashlib
import shutil
import subprocess
from functools import wraps
from pathlib import Path
from datetime import datetime, timedelta
from flask import (
    Flask, request, redirect, url_for, session, render_template_string,
    flash, send_from_directory, abort
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# ============================================================
# พระสงฆ์สมไอซ์ — ระบบกฎหมายคณะสงฆ์และงานบริหาร
# Single-file Flask + SQLite
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "somice_sangha.db"
BACKUP_DIR = DATA_DIR / "backups"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key-in-production")
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024

ADMIN_USER = os.environ.get("ADMIN_USER", "1482")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "1842111482")

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}

# ------------------------- Database -------------------------

def restore_latest_backup_if_needed():
    """Restore the newest local DB backup only when the active DB is missing/empty."""
    if DB_PATH.exists() and DB_PATH.stat().st_size > 0:
        return False
    backups = sorted(BACKUP_DIR.glob("somice_sangha_*.db"), key=lambda x: x.stat().st_mtime, reverse=True)
    if backups:
        shutil.copy2(backups[0], DB_PATH)
        return True
    return False

def backup_database():
    """Create a timestamped SQLite backup without changing the live database."""
    if not DB_PATH.exists() or DB_PATH.stat().st_size == 0:
        return None
    target = BACKUP_DIR / f"somice_sangha_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    try:
        source = sqlite3.connect(DB_PATH)
        dest = sqlite3.connect(target)
        with dest:
            source.backup(dest)
        dest.close(); source.close()
        # Keep the newest 10 backups.
        backups = sorted(BACKUP_DIR.glob("somice_sangha_*.db"), key=lambda x: x.stat().st_mtime, reverse=True)
        for old in backups[10:]:
            try: old.unlink()
            except OSError: pass
        return target
    except Exception:
        try:
            if target.exists(): target.unlink()
        except OSError: pass
        return None

restore_latest_backup_if_needed()

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

POSITION_OPTIONS = [
    "เจ้าคณะใหญ่ธรรมยุต", "เจ้าคณะใหญ่มหานิกาย", "เจ้าคณะภาค", "เจ้าคณะหน",
    "เจ้าคณะจังหวัด", "รองเจ้าคณะจังหวัด", "เจ้าคณะอำเภอ", "รองเจ้าคณะอำเภอ",
    "เจ้าคณะตำบล", "รองเจ้าคณะตำบล", "เจ้าอาวาส", "รองเจ้าอาวาส",
    "ผู้ช่วยเจ้าอาวาส", "พระอุปัชฌาย์", "กรรมการมหาเถรสมาคม", "พระเลขานุการ", "อื่น ๆ"
]

def init_db():
    conn = db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS laws (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sort_order INTEGER NOT NULL,
        title TEXT NOT NULL,
        section TEXT NOT NULL,
        content TEXT NOT NULL,
        penalty TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS temples (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        ordination_date TEXT NOT NULL DEFAULT '',
        temple TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'บวชแล้ว',
        source TEXT NOT NULL DEFAULT 'manual',
        created_at TEXT NOT NULL,
        position TEXT NOT NULL DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS council (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        royal_name TEXT NOT NULL,
        active_date TEXT NOT NULL DEFAULT '',
        temple TEXT NOT NULL DEFAULT '',
        details TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        position TEXT NOT NULL DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS ordination_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        real_name TEXT NOT NULL,
        age INTEGER NOT NULL,
        temple TEXT NOT NULL,
        chant TEXT NOT NULL,
        kind TEXT NOT NULL,
        birth_temple TEXT NOT NULL,
        reason TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        assigned_preceptor_id INTEGER,
        monastic_name TEXT NOT NULL DEFAULT '',
        ordination_date TEXT NOT NULL DEFAULT '',
        affiliated_temple TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        FOREIGN KEY (assigned_preceptor_id) REFERENCES preceptors(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS preceptors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        display_name TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        position TEXT NOT NULL DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS employees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        display_name TEXT NOT NULL DEFAULT '',
        total_works INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        position TEXT NOT NULL DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS works (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        work_count INTEGER NOT NULL,
        image_file TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL,
        FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS study_applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER,
        name TEXT NOT NULL,
        type TEXT NOT NULL,
        vassa TEXT NOT NULL,
        level TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL,
        FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS preceptor_applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        vassa TEXT NOT NULL,
        temple TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL,
        FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS prayers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        link TEXT NOT NULL DEFAULT '',
        image_file TEXT NOT NULL DEFAULT '',
        body TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS salary_settings (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        is_open INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS salary_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        temple TEXT NOT NULL,
        total_works INTEGER NOT NULL DEFAULT 0,
        payment_channel TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL,
        FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS temple_admins (
        id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
        royal_name TEXT NOT NULL, temple TEXT NOT NULL, position TEXT NOT NULL, employee_id INTEGER, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS promotion_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT, employee_id INTEGER, preceptor_id INTEGER, applicant_name TEXT NOT NULL, royal_name TEXT NOT NULL,
        vassa TEXT NOT NULL, temple TEXT NOT NULL, position TEXT NOT NULL, current_rank TEXT NOT NULL, requested_rank TEXT NOT NULL, temple_role TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL, decided_at TEXT NOT NULL DEFAULT '',
        FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE, FOREIGN KEY(preceptor_id) REFERENCES preceptors(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS defrock_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, reason TEXT NOT NULL, discord_username TEXT NOT NULL, temple TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending', preceptor_id INTEGER, created_at TEXT NOT NULL, decided_at TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS temple_delete_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT, temple_id INTEGER NOT NULL, temple_admin_id INTEGER NOT NULL, reason TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS transfer_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT, source_temple TEXT NOT NULL, target_temple TEXT NOT NULL, name TEXT NOT NULL, reason TEXT NOT NULL,
        requester_admin_id INTEGER, receiver_admin_id INTEGER, status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL, decided_at TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS activities (
        id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL UNIQUE, is_open INTEGER NOT NULL DEFAULT 0, question_count INTEGER NOT NULL DEFAULT 0, main_question TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS funeral_participants (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        activity_kind TEXT NOT NULL,
        name TEXT NOT NULL,
        employee_id INTEGER,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL,
        decided_at TEXT NOT NULL DEFAULT '',
        FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE SET NULL
    );
    CREATE TABLE IF NOT EXISTS promotion_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, employee_id INTEGER, applicant_name TEXT NOT NULL, royal_name TEXT NOT NULL, vassa TEXT NOT NULL, temple TEXT NOT NULL,
        position TEXT NOT NULL, current_rank TEXT NOT NULL, requested_rank TEXT NOT NULL, temple_role TEXT NOT NULL, approved_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS activity_submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, activity_id INTEGER NOT NULL, name TEXT NOT NULL, royal_name TEXT NOT NULL DEFAULT '', tiktok_link TEXT NOT NULL DEFAULT '', temple TEXT NOT NULL DEFAULT '',
        answer TEXT NOT NULL DEFAULT '', score INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS contact_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT, royal_name TEXT NOT NULL, subject TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL, decided_at TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS site_settings (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        site_enabled INTEGER NOT NULL DEFAULT 1,
        input_enabled INTEGER NOT NULL DEFAULT 1,
        attack_lock_until TEXT NOT NULL DEFAULT '',
        attack_lock_reason TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS spam_guard (
        fingerprint TEXT PRIMARY KEY,
        hit_count INTEGER NOT NULL DEFAULT 1,
        first_seen TEXT NOT NULL,
        last_seen TEXT NOT NULL
    );
    INSERT OR IGNORE INTO activities(kind,is_open,question_count,main_question) VALUES ('promo',0,0,''),('quiz',0,0,'');
    INSERT OR IGNORE INTO activities(kind,is_open,question_count,main_question) VALUES ('funeral_water',0,0,''),('funeral_cremation',0,0,'');
    """)
    # Small compatibility migrations for older SQLite databases.
    def add_column_if_missing(table, column, definition):
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    add_column_if_missing("temples", "source", "TEXT NOT NULL DEFAULT 'manual'")
    add_column_if_missing("temples", "source_ref", "TEXT NOT NULL DEFAULT ''")
    add_column_if_missing("temples", "position", "TEXT NOT NULL DEFAULT ''")
    add_column_if_missing("council", "position", "TEXT NOT NULL DEFAULT ''")
    add_column_if_missing("preceptors", "position", "TEXT NOT NULL DEFAULT ''")
    # สถานะบุคคลในทะเบียนวัด: ข้อมูลเดิมทั้งหมดให้เป็น "พระ" โดยอัตโนมัติ
    add_column_if_missing("temples", "person_type", "TEXT NOT NULL DEFAULT 'พระ'")
    add_column_if_missing("employees", "position", "TEXT NOT NULL DEFAULT ''")

    # Older builds sometimes made study_applications.employee_id NOT NULL.
    # Rebuild that table so public applications can enter the employee approval queue.
    cols = conn.execute("PRAGMA table_info(study_applications)").fetchall()
    emp_col = next((r for r in cols if r[1] == "employee_id"), None)
    if emp_col and emp_col[3] == 1:
        conn.execute("""CREATE TABLE IF NOT EXISTS study_applications_mig (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER,
            name TEXT NOT NULL, type TEXT NOT NULL, vassa TEXT NOT NULL,
            level TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL,
            FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE
        )""")
        conn.execute("""INSERT INTO study_applications_mig
            (id,employee_id,name,type,vassa,level,status,created_at)
            SELECT id,employee_id,name,type,vassa,level,status,created_at FROM study_applications""")
        conn.execute("DROP TABLE study_applications")
        conn.execute("ALTER TABLE study_applications_mig RENAME TO study_applications")

    conn.execute("INSERT OR IGNORE INTO salary_settings(id, is_open) VALUES (1, 0)")
    conn.execute("INSERT OR IGNORE INTO site_settings(id, site_enabled, input_enabled) VALUES (1, 1, 1)")
    conn.commit()
    conn.close()

# Initialize before handling requests, including Gunicorn/Render.
init_db()

# ------------------------- Extended simulation modules -------------------------
def init_extended_db():
    conn=db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS board_members(
      id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT NOT NULL, side TEXT NOT NULL DEFAULT 'center',
      parent_role TEXT NOT NULL DEFAULT '', name TEXT NOT NULL DEFAULT '', temple TEXT NOT NULL DEFAULT '', photo TEXT NOT NULL DEFAULT '', sort_order INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS chats(
      id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, title TEXT NOT NULL, actor_a TEXT NOT NULL,
      actor_b TEXT NOT NULL, temple TEXT NOT NULL DEFAULT '', visitor_name TEXT NOT NULL DEFAULT '', closed INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS chat_messages(
      id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, sender TEXT NOT NULL, sender_name TEXT NOT NULL DEFAULT '',
      message TEXT NOT NULL DEFAULT '', image_file TEXT NOT NULL DEFAULT '', audio_file TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
      FOREIGN KEY(chat_id) REFERENCES chats(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS vinaya_officers(
      id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
      royal_name TEXT NOT NULL, region TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS invitations(
      id INTEGER PRIMARY KEY AUTOINCREMENT, contact_name TEXT NOT NULL, temple TEXT NOT NULL, event_type TEXT NOT NULL,
      event_date TEXT NOT NULL, event_time TEXT NOT NULL, monk_count INTEGER NOT NULL DEFAULT 1, details TEXT NOT NULL DEFAULT '',
      status TEXT NOT NULL DEFAULT 'pending', chat_id INTEGER, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS complaints(
      id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, category TEXT NOT NULL, subject TEXT NOT NULL,
      details TEXT NOT NULL, image_file TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'pending', chat_id INTEGER, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS death_requests(
      id INTEGER PRIMARY KEY AUTOINCREMENT, temple_id INTEGER NOT NULL, temple TEXT NOT NULL, name TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL, decided_at TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS documents(
      id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, image_file TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS announcements(
      id INTEGER PRIMARY KEY AUTOINCREMENT, image_file TEXT NOT NULL, is_open INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS system_announcements(
      id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL DEFAULT 'general', title TEXT NOT NULL,
      content TEXT NOT NULL, image_file TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, is_open INTEGER NOT NULL DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS blessings(
      id INTEGER PRIMARY KEY CHECK(id=1), is_open INTEGER NOT NULL DEFAULT 0, occasion TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS blessing_entries(
      id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, message TEXT NOT NULL, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS suggestions(
      id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, suggestion TEXT NOT NULL, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS audit_logs(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      actor_role TEXT NOT NULL, actor_id TEXT NOT NULL DEFAULT '', actor_name TEXT NOT NULL DEFAULT '',
      action TEXT NOT NULL DEFAULT '', endpoint TEXT NOT NULL DEFAULT '', method TEXT NOT NULL DEFAULT '',
      target_id TEXT NOT NULL DEFAULT '', summary TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS admin_notifications(
      id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, title TEXT NOT NULL,
      message TEXT NOT NULL DEFAULT '', target_id TEXT NOT NULL DEFAULT '',
      is_read INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS account_security(
      id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT NOT NULL, account_id TEXT NOT NULL,
      delete_count INTEGER NOT NULL DEFAULT 0, banned_until TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
      UNIQUE(role,account_id)
    );
    CREATE TABLE IF NOT EXISTS chat_users(
      id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS chat_profiles(
      user_id INTEGER PRIMARY KEY, display_name TEXT NOT NULL DEFAULT '', avatar_file TEXT NOT NULL DEFAULT '',
      bio TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL,
      FOREIGN KEY(user_id) REFERENCES chat_users(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS chat_friends(
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, friend_id INTEGER NOT NULL, created_at TEXT NOT NULL,
      UNIQUE(user_id,friend_id),
      FOREIGN KEY(user_id) REFERENCES chat_users(id) ON DELETE CASCADE,
      FOREIGN KEY(friend_id) REFERENCES chat_users(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS store_users(
      id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
      display_name TEXT NOT NULL DEFAULT '', avatar_file TEXT NOT NULL DEFAULT '', bio TEXT NOT NULL DEFAULT '',
      is_seller INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS store_products(
      id INTEGER PRIMARY KEY AUTOINCREMENT, seller_id INTEGER NOT NULL, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
      image_file TEXT NOT NULL DEFAULT '', price INTEGER NOT NULL DEFAULT 0, digital_content TEXT NOT NULL DEFAULT '',
      active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
      FOREIGN KEY(seller_id) REFERENCES store_users(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS store_purchases(
      id INTEGER PRIMARY KEY AUTOINCREMENT, buyer_id INTEGER NOT NULL, product_id INTEGER NOT NULL, seller_id INTEGER NOT NULL,
      price INTEGER NOT NULL DEFAULT 0, digital_content TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'completed', created_at TEXT NOT NULL,
      FOREIGN KEY(buyer_id) REFERENCES store_users(id) ON DELETE CASCADE,
      FOREIGN KEY(product_id) REFERENCES store_products(id) ON DELETE CASCADE,
      FOREIGN KEY(seller_id) REFERENCES store_users(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS store_reviews(
      id INTEGER PRIMARY KEY AUTOINCREMENT, product_id INTEGER NOT NULL, buyer_id INTEGER NOT NULL, rating INTEGER NOT NULL,
      text TEXT NOT NULL DEFAULT '', image_file TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
      UNIQUE(product_id,buyer_id),
      FOREIGN KEY(product_id) REFERENCES store_products(id) ON DELETE CASCADE,
      FOREIGN KEY(buyer_id) REFERENCES store_users(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS social_users(
      id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
      display_name TEXT NOT NULL, avatar_file TEXT NOT NULL DEFAULT '', bio TEXT NOT NULL DEFAULT '',
      chat_user_id INTEGER, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS social_posts(
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, caption TEXT NOT NULL DEFAULT '',
      video_file TEXT NOT NULL DEFAULT '', video_duration REAL NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
      FOREIGN KEY(user_id) REFERENCES social_users(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS social_post_images(
      id INTEGER PRIMARY KEY AUTOINCREMENT, post_id INTEGER NOT NULL, image_file TEXT NOT NULL, sort_order INTEGER NOT NULL DEFAULT 0,
      FOREIGN KEY(post_id) REFERENCES social_posts(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS social_follows(
      id INTEGER PRIMARY KEY AUTOINCREMENT, follower_id INTEGER NOT NULL, following_id INTEGER NOT NULL, created_at TEXT NOT NULL,
      UNIQUE(follower_id,following_id),
      FOREIGN KEY(follower_id) REFERENCES social_users(id) ON DELETE CASCADE,
      FOREIGN KEY(following_id) REFERENCES social_users(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS social_likes(
      id INTEGER PRIMARY KEY AUTOINCREMENT, post_id INTEGER NOT NULL, user_id INTEGER NOT NULL, created_at TEXT NOT NULL,
      UNIQUE(post_id,user_id),
      FOREIGN KEY(post_id) REFERENCES social_posts(id) ON DELETE CASCADE,
      FOREIGN KEY(user_id) REFERENCES social_users(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS social_comments(
      id INTEGER PRIMARY KEY AUTOINCREMENT, post_id INTEGER NOT NULL, user_id INTEGER NOT NULL, text TEXT NOT NULL, created_at TEXT NOT NULL,
      FOREIGN KEY(post_id) REFERENCES social_posts(id) ON DELETE CASCADE,
      FOREIGN KEY(user_id) REFERENCES social_users(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS lottery_tickets (
      id INTEGER PRIMARY KEY AUTOINCREMENT, royal_name TEXT NOT NULL, ticket_no TEXT NOT NULL,
      quantity INTEGER NOT NULL DEFAULT 1 CHECK(quantity IN (1,2)), payment_status TEXT NOT NULL DEFAULT 'รอชำระ',
      created_at TEXT NOT NULL, paid_at TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS lottery_draws (
      id INTEGER PRIMARY KEY CHECK(id=1), prize1 TEXT NOT NULL DEFAULT '', prize2 TEXT NOT NULL DEFAULT '', prize3 TEXT NOT NULL DEFAULT '',
      last2 TEXT NOT NULL DEFAULT '', first2 TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS lottery_staff (
      id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, created_at TEXT NOT NULL
    );
    """)
    conn.execute("INSERT OR IGNORE INTO blessings(id,is_open,occasion,created_at) VALUES(1,0,'',?)",(now(),))
    conn.execute("INSERT OR IGNORE INTO lottery_draws(id,updated_at) VALUES(1,?)",(now(),))
    # Exam result support for the existing study table.
    cols={r[1] for r in conn.execute("PRAGMA table_info(study_applications)").fetchall()}
    if 'exam_result' not in cols: conn.execute("ALTER TABLE study_applications ADD COLUMN exam_result TEXT NOT NULL DEFAULT ''")
    if 'temple' not in cols: conn.execute("ALTER TABLE study_applications ADD COLUMN temple TEXT NOT NULL DEFAULT ''")
    for table in ('complaints','invitations'):
        cols2={r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if 'visitor_actor' not in cols2: conn.execute(f"ALTER TABLE {table} ADD COLUMN visitor_actor TEXT NOT NULL DEFAULT ''")
    vin_cols={r[1] for r in conn.execute("PRAGMA table_info(vinaya_officers)").fetchall()}
    if 'content_delete_enabled' not in vin_cols:
        conn.execute("ALTER TABLE vinaya_officers ADD COLUMN content_delete_enabled INTEGER NOT NULL DEFAULT 0")
    social_cols={r[1] for r in conn.execute("PRAGMA table_info(social_users)").fetchall()}
    if 'chat_user_id' not in social_cols:
        conn.execute("ALTER TABLE social_users ADD COLUMN chat_user_id INTEGER")
    conn.commit(); conn.close()

def migrate_security_columns():
    conn=db()
    cols={r[1] for r in conn.execute("PRAGMA table_info(site_settings)").fetchall()}
    if "attack_lock_until" not in cols:
        conn.execute("ALTER TABLE site_settings ADD COLUMN attack_lock_until TEXT NOT NULL DEFAULT ''")
    if "attack_lock_reason" not in cols:
        conn.execute("ALTER TABLE site_settings ADD COLUMN attack_lock_reason TEXT NOT NULL DEFAULT ''")
    conn.execute("INSERT OR IGNORE INTO site_settings(id,site_enabled,input_enabled,attack_lock_until,attack_lock_reason) VALUES(1,1,1,'','')")
    conn.commit(); conn.close()

migrate_security_columns()
init_extended_db()
backup_database()

def funeral_activity(kind):
    conn=db(); row=conn.execute("SELECT * FROM activities WHERE kind=?",(kind,)).fetchone(); conn.close(); return row

def approved_death_exists():
    conn=db(); row=conn.execute("SELECT 1 FROM death_requests WHERE status='approved' LIMIT 1").fetchone(); conn.close(); return bool(row)

# ------------------------- Helpers -------------------------

def site_state():
    conn=db()
    row=conn.execute("SELECT site_enabled,input_enabled,attack_lock_until,attack_lock_reason FROM site_settings WHERE id=1").fetchone()
    conn.close()
    if not row:
        return {"site_enabled":1,"input_enabled":1,"attack_lock_until":"","attack_lock_reason":""}
    return {"site_enabled":int(row["site_enabled"]),"input_enabled":int(row["input_enabled"]),"attack_lock_until":row["attack_lock_until"] or "","attack_lock_reason":row["attack_lock_reason"] or ""}

def set_site_state(site_enabled=None,input_enabled=None,attack_lock_until=None,attack_lock_reason=None):
    state=site_state()
    if site_enabled is None: site_enabled=state["site_enabled"]
    if input_enabled is None: input_enabled=state["input_enabled"]
    if attack_lock_until is None: attack_lock_until=state["attack_lock_until"]
    if attack_lock_reason is None: attack_lock_reason=state["attack_lock_reason"]
    conn=db(); conn.execute("UPDATE site_settings SET site_enabled=?,input_enabled=?,attack_lock_until=?,attack_lock_reason=? WHERE id=1",(int(bool(site_enabled)),int(bool(input_enabled)),attack_lock_until or "",attack_lock_reason or "")); conn.commit(); conn.close()

def clear_attack_lock():
    set_site_state(site_enabled=1,attack_lock_until="",attack_lock_reason="")

def detect_request_burst():
    """Defensive detector: blocks an abusive burst; never sends traffic outward."""
    if request.method not in ("GET","POST"): return False
    if (request.path or "").startswith(("/static/","/uploads/")): return False
    ip=(request.headers.get("X-Forwarded-For","").split(",")[0].strip() or request.remote_addr or "unknown")
    # Count requests per IP in a rolling 10-second window.
    conn=db(); row=conn.execute("SELECT hit_count,first_seen FROM spam_guard WHERE fingerprint=?",(ip,)).fetchone(); now_dt=datetime.now()
    if row:
        try: age=(now_dt-datetime.strptime(row["first_seen"],"%Y-%m-%d %H:%M:%S")).total_seconds()
        except Exception: age=999999
        hits=int(row["hit_count"])+1 if age<=10 else 1
        first= row["first_seen"] if age<=10 else now()
        conn.execute("UPDATE spam_guard SET hit_count=?,first_seen=?,last_seen=? WHERE fingerprint=?",(hits,first,now(),ip))
    else:
        hits=1; conn.execute("INSERT INTO spam_guard(fingerprint,hit_count,first_seen,last_seen) VALUES(?,?,?,?)",(ip,1,now(),ip))
    conn.execute("DELETE FROM spam_guard WHERE last_seen < datetime('now','-10 minutes')")
    locked=False
    if hits>=50:
        until=(now_dt+timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("UPDATE site_settings SET site_enabled=0,attack_lock_until=?,attack_lock_reason=? WHERE id=1",(until,"ตรวจพบคำขอจำนวนมากผิดปกติ")); locked=True
    conn.commit(); conn.close(); return locked

@app.before_request
def global_site_guard():
    endpoint=request.endpoint or ""
    if endpoint.startswith("admin") or endpoint=="admin_login" or endpoint=="static": return None
    role,account_id=security_key_for_session()
    banned_until=security_status(role,account_id)
    if banned_until: return white_ban_page(banned_until)
    detect_request_burst()
    state=site_state()
    # Automatic lock expires without requiring a public request to know about it.
    if state["attack_lock_until"]:
        try:
            if datetime.now()>=datetime.strptime(state["attack_lock_until"],"%Y-%m-%d %H:%M:%S"):
                clear_attack_lock(); state=site_state()
        except ValueError: pass
    if not state["site_enabled"]:
        return render_template_string("""<!doctype html><html lang='th'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>เว็บไซต์ปิดชั่วคราว</title><style>html,body{margin:0;width:100%;height:100%;background:#fff}.secret{position:fixed;left:50%;bottom:10px;transform:translateX(-50%);width:44px;height:3px;background:#e53935;border-radius:4px;cursor:pointer;opacity:.8}.secret span{display:none;position:absolute;bottom:8px;left:50%;transform:translateX(-50%);white-space:nowrap;background:#fff;border:1px solid #eee;border-radius:8px;padding:5px 8px;color:#333;font:12px Arial}.secret:hover span{display:block}</style></head><body><a class='secret' href='{{url_for("admin_login")}}' aria-label='Admin'><span>เข้าสู่ระบบ Admin</span></a></body></html>""")
    if not state["input_enabled"] and request.method=="POST":
        flash("ขณะนี้ Admin ปิดการกรอกข้อมูลชั่วคราว","error"); return redirect(request.referrer or url_for("home"))
    return None

def _audit_actor():
    role=session.get("role")
    if role=="temple_admin":
        aid=str(session.get("user_id","")); conn=db(); r=conn.execute("SELECT royal_name FROM temple_admins WHERE id=?",(session.get("user_id"),)).fetchone(); conn.close(); return role,aid,(r["royal_name"] if r else "ผู้ดูแลวัด")
    if role=="preceptor":
        aid=str(session.get("user_id","")); conn=db(); r=conn.execute("SELECT display_name,username FROM preceptors WHERE id=?",(session.get("user_id"),)).fetchone(); conn.close(); return role,aid,((r["display_name"] or r["username"]) if r else "พระอุปัชฌาย์")
    if role=="employee":
        aid=str(session.get("user_id","")); conn=db(); r=conn.execute("SELECT display_name,username FROM employees WHERE id=?",(session.get("user_id"),)).fetchone(); conn.close(); return role,aid,((r["display_name"] or r["username"]) if r else "พนักงาน")
    return None,None,None

@app.before_request
def audit_non_admin_activity():
    if request.path.startswith("/static/") or request.method not in ("POST","PUT","PATCH","DELETE"):
        return None
    role,aid,name=_audit_actor()
    if not role:
        return None
    safe={}
    for k,v in request.form.items():
        if k.lower() in {"password","password_hash","_csrf"}:
            continue
        safe[k]=v[:500] if isinstance(v,str) else str(v)
    target=safe.get("id",safe.get("request_id",safe.get("rid","")))
    summary=json.dumps(safe,ensure_ascii=False)[:4000]
    try:
        conn=db(); conn.execute("INSERT INTO audit_logs(actor_role,actor_id,actor_name,action,endpoint,method,target_id,summary,created_at) VALUES(?,?,?,?,?,?,?,?,?)",(role,aid,name,safe.get("action",request.endpoint or "view"),request.endpoint or "",request.method,target,summary,now())); conn.commit(); conn.close()
    except Exception:
        pass
    return None

def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(24)
    return session["csrf"]

def check_csrf():
    token = request.form.get("_csrf", "")
    return secrets.compare_digest(token, session.get("csrf", ""))

# Make the CSRF helper available inside all Jinja templates.
app.jinja_env.globals["csrf_token"] = csrf_token

def require_csrf():
    if not check_csrf():
        abort(400, "Invalid request token")

def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if session.get("role") != "admin":
            flash("กรุณาเข้าสู่ระบบผู้ดูแลก่อน", "error")
            return redirect(url_for("admin_login"))
        return fn(*args, **kwargs)
    return wrapper

def employee_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if session.get("role") != "employee":
            flash("กรุณาเข้าสู่ระบบพนักงานก่อน", "error")
            return redirect(url_for("employee_login"))
        return fn(*args, **kwargs)
    return wrapper

def preceptor_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if session.get("role") != "preceptor":
            flash("กรุณาเข้าสู่ระบบพระอุปัชฌาย์ก่อน", "error")
            return redirect(url_for("preceptor_login"))
        return fn(*args, **kwargs)
    return wrapper

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def save_upload(file_storage, prefix):
    if not file_storage or not file_storage.filename:
        return ""
    if not allowed_file(file_storage.filename):
        raise ValueError("รองรับเฉพาะ PNG, JPG, JPEG, WEBP และ GIF")
    ext = secure_filename(file_storage.filename).rsplit(".", 1)[1].lower()
    filename = f"{prefix}_{secrets.token_hex(8)}.{ext}"
    file_storage.save(UPLOAD_DIR / filename)
    return filename

VIDEO_EXTENSIONS = {"mp4", "webm", "mov", "m4v"}

def save_video_upload(file_storage, prefix="socialvideo"):
    if not file_storage or not file_storage.filename:
        return ""
    safe = secure_filename(file_storage.filename)
    if "." not in safe:
        raise ValueError("ไฟล์วิดีโอไม่ถูกต้อง")
    ext = safe.rsplit(".", 1)[1].lower()
    if ext not in VIDEO_EXTENSIONS:
        raise ValueError("รองรับวิดีโอ MP4, WEBM, MOV และ M4V")
    filename = f"{prefix}_{secrets.token_hex(8)}.{ext}"
    file_storage.save(UPLOAD_DIR / filename)
    return filename

def social_user_row():
    uid=session.get("social_user_id")
    if not uid: return None
    conn=db(); row=conn.execute("SELECT * FROM social_users WHERE id=?",(uid,)).fetchone(); conn.close()
    return row

def require_social_user():
    return bool(social_user_row())

def social_display_name(user_id):
    conn=db(); row=conn.execute("SELECT display_name,username FROM social_users WHERE id=?",(user_id,)).fetchone(); conn.close()
    return (row["display_name"] or row["username"]) if row else "ผู้ใช้"

def sync_social_to_chat(conn, social_id, username, display_name, avatar_file, bio):
    row=conn.execute("SELECT chat_user_id FROM social_users WHERE id=?",(social_id,)).fetchone()
    chat_id=row["chat_user_id"] if row else None
    if chat_id and conn.execute("SELECT id FROM chat_users WHERE id=?",(chat_id,)).fetchone():
        conn.execute("UPDATE chat_profiles SET display_name=?,avatar_file=?,bio=?,updated_at=? WHERE user_id=?",(display_name,avatar_file,bio,now(),chat_id))
    else:
        existing=conn.execute("SELECT id FROM chat_users WHERE username=?",(username,)).fetchone()
        if existing:
            chat_id=existing["id"]
        else:
            cur=conn.execute("INSERT INTO chat_users(username,created_at) VALUES(?,?)",(username,now())); chat_id=cur.lastrowid
        if conn.execute("SELECT 1 FROM chat_profiles WHERE user_id=?",(chat_id,)).fetchone():
            conn.execute("UPDATE chat_profiles SET display_name=?,avatar_file=?,bio=?,updated_at=? WHERE user_id=?",(display_name,avatar_file,bio,now(),chat_id))
        else:
            conn.execute("INSERT INTO chat_profiles(user_id,display_name,avatar_file,bio,updated_at) VALUES(?,?,?,?,?)",(chat_id,display_name,avatar_file,bio,now()))
        conn.execute("UPDATE social_users SET chat_user_id=? WHERE id=?",(chat_id,social_id))
    return chat_id

def next_law_order(conn):
    row = conn.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 AS n FROM laws").fetchone()
    return int(row["n"])

def current_employee():
    if session.get("role") != "employee":
        return None
    conn = db()
    row = conn.execute("SELECT * FROM employees WHERE id=?", (session["user_id"],)).fetchone()
    conn.close()
    return row

# ------------------------- UI -------------------------

CSS = r"""
:root{
  --bg:#f4efe7; --paper:#fffdf9; --ink:#171512; --muted:#6d665e;
  --line:#ddd2c4; --accent:#7a4b24; --accent2:#b98245;
  --good:#2e6b43; --bad:#9a3c32; --shadow:0 10px 30px rgba(45,30,18,.08);
}
*{box-sizing:border-box}
body{margin:0;background:linear-gradient(135deg,#f7f2eb,#eee5d8);color:var(--ink);
font-family:system-ui,-apple-system,"Noto Sans Thai","Tahoma",sans-serif;line-height:1.65}
a{color:inherit;text-decoration:none}
.container{width:min(1120px,92%);margin:auto}
.topbar{position:sticky;top:0;z-index:10;background:rgba(255,253,249,.94);backdrop-filter:blur(10px);
border-bottom:1px solid var(--line)}
.nav{min-height:68px;display:flex;align-items:center;justify-content:space-between;gap:12px}
.brand{font-weight:900;letter-spacing:.2px}.brand small{display:block;font-weight:500;color:var(--muted);font-size:11px}
.navlinks{display:flex;gap:7px;flex-wrap:wrap;justify-content:flex-end}
.navlinks a,.btn{border:1px solid var(--line);border-radius:12px;padding:8px 12px;background:#fff;
font-weight:700;font-size:14px}
.navlinks a:hover,.btn:hover{border-color:var(--accent2);transform:translateY(-1px)}
.hero{padding:54px 0 28px}.hero h1{font-size:clamp(28px,5vw,48px);margin:0 0 10px}
.hero p{color:var(--muted);max-width:780px;margin:0}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;padding:20px 0 44px}
.card{background:rgba(255,253,249,.96);border:1px solid var(--line);border-radius:20px;padding:20px;box-shadow:var(--shadow)}
.card h2,.card h3{margin-top:0}.card p{color:var(--muted)}
.icon{font-size:30px}.cardsmall{min-height:155px;display:flex;flex-direction:column;justify-content:space-between}
.section{padding:30px 0}.sectionhead{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:16px}
.sectionhead h1{margin:0}.muted{color:var(--muted)}
.form{display:grid;gap:13px}.formgrid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
label{font-weight:800;font-size:14px}input,textarea,select{width:100%;border:1px solid #cfc3b5;border-radius:12px;padding:12px;
font:inherit;background:#fff;color:var(--ink);outline:none}textarea{min-height:120px;resize:vertical}
input:focus,textarea:focus,select:focus{border-color:var(--accent2);box-shadow:0 0 0 3px rgba(185,130,69,.12)}
button{cursor:pointer}.btn{display:inline-block}.btn.primary{background:var(--accent);color:#fff;border-color:var(--accent)}
.btn.good{background:#edf7ef;border-color:#a9d0b2}.btn.bad{background:#fff0ee;border-color:#e1aaa3}
.btn.warn{background:#fff8e9;border-color:#e8c786}
.actions{display:flex;gap:8px;flex-wrap:wrap}.inline{display:inline}.tablewrap{overflow:auto}
table{width:100%;border-collapse:collapse;min-width:720px}th,td{padding:12px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{background:#f5eee4}.badge{display:inline-block;padding:3px 9px;border-radius:999px;background:#eee6db;font-size:12px;font-weight:800}
.badge.good{background:#e5f3e8}.badge.bad{background:#f8e3df}.badge.warn{background:#fff1cf}
.flash{margin:15px 0;padding:12px 14px;border-radius:12px;background:#fff;border:1px solid var(--line)}
.flash.error{border-color:#e1aaa3;background:#fff3f1}.flash.success{border-color:#abd1b3;background:#f0faf2}
.login{width:min(460px,92%);margin:60px auto}.login .card{padding:28px}
.adminbar{background:#201b16;color:#fff;padding:10px 0}.adminbar .nav{min-height:48px}.adminbar a{color:#fff}
.list{display:grid;gap:12px}.item{background:#fff;border:1px solid var(--line);border-radius:16px;padding:16px}
.kpi{font-size:30px;font-weight:900}.footer{padding:30px 0 60px;color:var(--muted);text-align:center}
img.preview{max-width:280px;max-height:220px;border-radius:14px;border:1px solid var(--line);display:block;margin-top:8px}
.empty{text-align:center;padding:28px;color:var(--muted)}
.avatar-large{width:110px;height:110px;object-fit:cover;border-radius:50%;border:1px solid var(--line);display:block;margin:0 0 12px}.avatar-empty{display:flex;align-items:center;justify-content:center;background:#f4efe8;font-size:42px}.float-store{position:fixed;right:18px;bottom:22px;width:62px;height:62px;border-radius:50%;z-index:9000;display:flex;align-items:center;justify-content:center;cursor:grab;box-shadow:0 8px 24px rgba(0,0,0,.18);background:#201b16;color:#fff;border:2px solid #fff;touch-action:none;user-select:none}.float-store.dragging{cursor:grabbing}
.social-shell{position:fixed;inset:0;background:#000;color:#fff;z-index:8000;display:flex;flex-direction:column}.social-top{height:58px;display:flex;align-items:center;justify-content:space-between;padding:8px 12px;background:rgba(0,0,0,.55);z-index:3}.social-top .btn{background:rgba(255,255,255,.12);color:#fff;border-color:rgba(255,255,255,.25);padding:7px 11px}.social-feed{flex:1;overflow-y:auto;scroll-snap-type:y mandatory}.social-post{height:calc(100vh - 58px);min-height:520px;position:relative;scroll-snap-align:start;overflow:hidden;background:#111}.social-media,.social-media video,.social-carousel{position:absolute;inset:0;width:100%;height:100%}.social-media video{object-fit:cover;background:#000}.social-carousel{display:flex;overflow-x:auto;scroll-snap-type:x mandatory;scrollbar-width:none}.social-carousel::-webkit-scrollbar{display:none}.social-carousel img{min-width:100%;width:100%;height:100%;object-fit:cover;scroll-snap-align:center}.social-gradient{position:absolute;inset:35% 0 0;background:linear-gradient(transparent,rgba(0,0,0,.85));pointer-events:none}.social-info{position:absolute;left:16px;right:78px;bottom:72px;z-index:2}.social-info p{margin:8px 0;white-space:pre-wrap}.social-user{display:flex;align-items:center;gap:8px}.social-user img{width:38px;height:38px;border-radius:50%;object-fit:cover;border:2px solid #fff}.social-actions{position:absolute;right:12px;bottom:82px;z-index:3;display:flex;flex-direction:column;gap:10px}.social-actions button,.social-actions a{width:48px;min-height:48px;border:0;border-radius:50%;background:rgba(0,0,0,.45);color:#fff;display:flex;flex-direction:column;align-items:center;justify-content:center;font-size:20px}.social-actions small{font-size:10px}.social-nav{height:62px;background:#080808;display:flex;align-items:center;justify-content:space-around;border-top:1px solid #333;z-index:5}.social-nav a{color:#aaa;text-align:center;font-size:22px;min-width:90px}.social-nav a span{display:block;font-size:11px}.social-nav a.active{color:#fff}.social-page{padding:20px 0 90px}.social-page .sectionhead h1{flex:1}.social-profile-card{display:flex;flex-direction:column;align-items:flex-start}.social-profile-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:5px;margin-top:16px}.social-thumb{aspect-ratio:1/1;background:#ddd;overflow:hidden}.social-thumb img,.social-thumb video{width:100%;height:100%;object-fit:cover;display:block}.float-video{position:fixed;right:18px;bottom:96px;width:62px;height:62px;border-radius:50%;z-index:9000;display:flex;align-items:center;justify-content:center;cursor:grab;box-shadow:0 8px 24px rgba(0,0,0,.18);background:#111;color:#fff;border:2px solid #fff;touch-action:none;user-select:none}.float-video.dragging{cursor:grabbing}
@media(max-width:800px){.grid{grid-template-columns:1fr 1fr}.formgrid{grid-template-columns:1fr}.nav{align-items:flex-start;padding:10px 0}.navlinks{justify-content:flex-start}}
@media(max-width:540px){.grid{grid-template-columns:1fr}.hero{padding-top:32px}.card{border-radius:16px}.navlinks a{font-size:12px;padding:7px 9px}}
"""

BASE = r"""
<!doctype html><html lang="th"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ title }} — พระสงฆ์สมไอซ์</title><style>{{ css|safe }}</style></head>
<body>
<header class="topbar"><div class="container nav">
<a class="brand" href="{{ url_for('home') }}">🙏 พระสงฆ์สมไอซ์<small>ระบบกฎหมายคณะสงฆ์และงานบริหาร</small></a>
<div class="navlinks">
<a href="{{ url_for('laws') }}">📜 กฎหมาย</a><a href="{{ url_for('temples') }}">🏯 ทะเบียนวัด</a>
<a href="{{ url_for('council') }}">🪷 มหาเถรสมาคม</a><a href="{{ url_for('prayers') }}">📖 บทสวด</a>
</div></div></header>
{% if session.get('role') in ['admin','employee','preceptor'] %}
<div class="adminbar"><div class="container nav">
<div>{{ {'admin':'ผู้ดูแลระบบ','employee':'ระบบพนักงาน','preceptor':'ระบบพระอุปัชฌาย์'}[session.get('role')] }}</div>
<div class="navlinks">
{% if session.get('role')=='admin' %}<a href="{{ url_for('admin') }}">หลังบ้าน</a>{% endif %}
{% if session.get('role')=='employee' %}<a href="{{ url_for('employee') }}">หน้าพนักงาน</a>{% endif %}
{% if session.get('role')=='preceptor' %}<a href="{{ url_for('preceptor') }}">หน้าอุปัชฌาย์</a>{% endif %}
<a href="{{ url_for('logout') }}">ออกจากระบบ</a></div></div></div>
{% endif %}
<main class="container">
{% with messages=get_flashed_messages(with_categories=true) %}
{% for category,message in messages %}<div class="flash {{ category }}">{{ message }}</div>{% endfor %}
{% endwith %}
{{ body|safe }}
</main>
{% if not input_enabled and session.get('role') != 'admin' %}<script>document.querySelectorAll('input:not([type="hidden"]):not(.admin-login-input),textarea:not(.admin-login-input),[contenteditable="true']:not(.admin-login-input)').forEach(function(el){el.disabled=true;el.readOnly=true;el.setAttribute('aria-disabled','true');});</script>{% endif %}
<div id="floatStore" class="float-store" title="ร้านค้าออนไลน์">🛍️</div><script>(function(){const b=document.getElementById('floatStore');if(!b)return;let pos;try{pos=JSON.parse(localStorage.getItem('floatStorePos')||'null')}catch(e){}if(pos){b.style.left=pos.x+'px';b.style.top=pos.y+'px';b.style.right='auto';b.style.bottom='auto'}let drag=false,moved=false,sx=0,sy=0,ox=0,oy=0;function down(e){const p=e.touches?e.touches[0]:e;drag=true;moved=false;sx=p.clientX;sy=p.clientY;ox=b.offsetLeft;oy=b.offsetTop;b.classList.add('dragging')}function move(e){if(!drag)return;const p=e.touches?e.touches[0]:e;const dx=p.clientX-sx,dy=p.clientY-sy;if(Math.abs(dx)+Math.abs(dy)>6)moved=true;b.style.left=Math.max(0,Math.min(innerWidth-b.offsetWidth,ox+dx))+'px';b.style.top=Math.max(0,Math.min(innerHeight-b.offsetHeight,oy+dy))+'px';b.style.right='auto';b.style.bottom='auto';if(e.cancelable)e.preventDefault()}function up(){if(!drag)return;drag=false;b.classList.remove('dragging');if(moved)localStorage.setItem('floatStorePos',JSON.stringify({x:b.offsetLeft,y:b.offsetTop}))}b.addEventListener('mousedown',down);addEventListener('mousemove',move);addEventListener('mouseup',up);b.addEventListener('touchstart',down,{passive:false});addEventListener('touchmove',move,{passive:false});addEventListener('touchend',up);b.addEventListener('click',function(){if(!moved)location.href='{{url_for("store_home")}}'})})();</script>
<div id="floatVideo" class="float-video" title="สมไอซ์ Video">📺</div><script>(function(){const b=document.getElementById('floatVideo');if(!b)return;let pos;try{pos=JSON.parse(localStorage.getItem('floatVideoPos')||'null')}catch(e){}if(pos){b.style.left=pos.x+'px';b.style.top=pos.y+'px';b.style.right='auto';b.style.bottom='auto'}let drag=false,moved=false,sx=0,sy=0,ox=0,oy=0;function down(e){const p=e.touches?e.touches[0]:e;drag=true;moved=false;sx=p.clientX;sy=p.clientY;ox=b.offsetLeft;oy=b.offsetTop;b.classList.add('dragging')}function move(e){if(!drag)return;const p=e.touches?e.touches[0]:e;const dx=p.clientX-sx,dy=p.clientY-sy;if(Math.abs(dx)+Math.abs(dy)>6)moved=true;b.style.left=Math.max(0,Math.min(innerWidth-b.offsetWidth,ox+dx))+'px';b.style.top=Math.max(0,Math.min(innerHeight-b.offsetHeight,oy+dy))+'px';b.style.right='auto';b.style.bottom='auto';if(e.cancelable)e.preventDefault()}function up(){if(!drag)return;drag=false;b.classList.remove('dragging');if(moved)localStorage.setItem('floatVideoPos',JSON.stringify({x:b.offsetLeft,y:b.offsetTop}))}b.addEventListener('mousedown',down);addEventListener('mousemove',move);addEventListener('mouseup',up);b.addEventListener('touchstart',down,{passive:false});addEventListener('touchmove',move,{passive:false});addEventListener('touchend',up);b.addEventListener('click',function(){if(!moved)location.href='{{url_for("social_home")}}'})})();</script>
<footer class="footer">พระสงฆ์สมไอซ์ • ระบบตัวอย่างสำหรับใช้งานภายในกลุ่ม</footer>
</body></html>
"""

def page(title, body, **ctx):
    # ทุกฟอร์มที่เกี่ยวกับสังกัดวัดใช้รายการกลางชุดเดียวกัน เพื่อป้องกันการกรอกชื่อวัดไม่ครบ/สะกดไม่ตรงกัน
    ctx.setdefault("temples", TEMPLE_OPTIONS)
    state = site_state()
    ctx.setdefault("input_enabled", bool(state["input_enabled"]))
    rendered = render_template_string(body, **ctx)
    return render_template_string(BASE, title=title, body=rendered, css=CSS, input_enabled=bool(state["input_enabled"]))

# ------------------------- Public -------------------------

@app.get("/")
def home():
    body = """
    <section class="hero">
      <h1>ระบบพระสงฆ์สมไอซ์</h1>
      <p>ศูนย์รวมกฎหมายคณะสงฆ์ ทะเบียน งานบวช การศึกษา ผลงาน และระบบบริหารภายในกลุ่ม</p>
    </section>
    {% if announcement %}<div id="announce" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.75);z-index:9999;align-items:center;justify-content:center"><div style="position:relative;max-width:95vw;max-height:95vh"><img src="{{url_for('uploaded_file',filename=announcement.image_file)}}" style="max-width:95vw;max-height:90vh;display:block"><button class="btn bad" style="position:absolute;right:5px;top:5px" onclick="document.getElementById('announce').style.display='none';sessionStorage.setItem('announcement_seen_{{announcement.id}}','1')">ปิด</button></div></div><script>if(!sessionStorage.getItem('announcement_seen_{{announcement.id}}'))document.getElementById('announce').style.display='flex';</script>{% endif %}
    {% if funeral_water_open or funeral_cremation_open %}
    <section class="card" style="margin-bottom:18px;border:2px solid #8b5a2b;background:linear-gradient(135deg,#fff8ef,#f4eadc)">
      <h2>🕯️ กิจกรรมสำหรับผู้ร่วมงาน</h2>
      <div class="actions">
        {% if funeral_water_open %}<a class="btn primary" href="{{url_for('funeral_water')}}">💧 ร่วมกิจกรรมรดน้ำศพ</a>{% endif %}
        {% if funeral_cremation_open %}<a class="btn bad" href="{{url_for('funeral_cremation')}}">🔥 ร่วมกิจกรรมฌาปนกิจ</a>{% endif %}
      </div>
    </section>
    {% endif %}
    <section class="grid">
      <a class="card cardsmall" href="{{ url_for('laws') }}"><div><div class="icon">📜</div><h3>กฎหมายคณะสงฆ์</h3><p>อ่านกฎหมายและมาตราที่ผู้ดูแลเพิ่มเข้าระบบ</p></div><b>เปิดดู →</b></a>
      <a class="card cardsmall" href="{{ url_for('temples') }}"><div><div class="icon">🏯</div><h3>ทะเบียนวัด</h3><p>รายชื่อพระ/เณรและสถานะการศึกษา</p></div><b>เปิดดู →</b></a>
      <a class="card cardsmall" href="{{ url_for('council') }}"><div><div class="icon">🪷</div><h3>ทะเบียนมหาเถรสมาคม</h3><p>ข้อมูลราชทินนามและวัดที่ประจำ</p></div><b>เปิดดู →</b></a>
      <a class="card cardsmall" href="{{ url_for('ordination') }}"><div><div class="icon">🙏</div><h3>ระบบบวช</h3><p>ยื่นคำขอบวชเพื่อส่งให้พระอุปัชฌาย์</p></div><b>ยื่นคำขอ →</b></a>
      <a class="card cardsmall" href="{{ url_for('education') }}"><div><div class="icon">📚</div><h3>สมัครเรียนนักธรรมและเปรียญธรรม</h3><p>ส่งใบสมัครเข้าสู่ระบบพนักงาน</p></div><b>สมัคร →</b></a>
      <a class="card cardsmall" href="{{ url_for('employee_login') }}"><div><div class="icon">👨‍💼</div><h3>ระบบพนักงาน</h3><p>ลงผลงาน สมัครเรียน และเบิกเงินเดือน</p></div><b>เข้าสู่ระบบ →</b></a>
      <a class="card cardsmall" href="{{ url_for('preceptor_login') }}"><div><div class="icon">🧘</div><h3>ระบบพระอุปัชฌาย์</h3><p>รับคำขอ อนุมัติ และบันทึกการบวช</p></div><b>เข้าสู่ระบบ →</b></a>
      <a class="card cardsmall" href="{{ url_for('prayers') }}"><div><div class="icon">📖</div><h3>บทสวดมนต์</h3><p>ข้อความ ลิงก์ และรูปบทสวด</p></div><b>เปิดดู →</b></a>
      <a class="card cardsmall" href="{{ url_for('monks_home') }}"><div><div class="icon">🧘‍♂️</div><h3>ระบบพระภิกษุสงฆ์</h3><p>แจ้งสึก ย้ายสังกัด และจัดการวัด</p></div><b>เปิดระบบ →</b></a>
      <a class="card cardsmall" href="{{ url_for('death_report') }}"><div><div class="icon">🕯️</div><h3>แจ้งมรณภาพ</h3><p>แจ้งพระในทะเบียนวัดเพื่อส่งให้ Admin ตรวจสอบและอนุมัติ</p></div><b>แจ้งมรณภาพ →</b></a>
      <a class="card cardsmall" href="{{ url_for('temple_admin_login') }}"><div><div class="icon">🏯</div><h3>ระบบเจ้าอาวาส/ผู้ดูแลวัด</h3><p>จัดการพระในวัดและคำขอย้ายเข้า</p></div><b>เข้าสู่ระบบ →</b></a>
      <a class="card cardsmall" href="{{url_for('announcements')}}"><div><div class="icon">📢</div><h3>ประกาศ{% if announcement_count %} <span class="badge">{{announcement_count}}</span>{% endif %}</h3><p>ประกาศทั่วไปและประกาศเร่งด่วน</p></div><b>ดูประกาศ →</b></a>
      <a class="card cardsmall" href="{{ url_for('admin_login') }}"><div><div class="icon">⚙️</div><h3>ระบบหลังบ้าน</h3><p>จัดการข้อมูลทั้งหมดของระบบ</p></div><b>Admin →</b></a>
      <a class="card cardsmall" href="{{ url_for('lottery_home') }}"><div><div class="icon">🎫</div><h3>สลากออนไลน์</h3><p>สลากจำลอง ใช้เงินในเกมเท่านั้น</p></div><b>เปิดระบบ →</b></a>
      <a class="card cardsmall" href="{{ url_for('board') }}"><div><div class="icon">🏛️</div><h3>บอร์ดบริหาร</h3><p>ตารางคณะบริหารจำลอง</p></div><b>เปิดดู →</b></a>
      <a class="card cardsmall" href="{{ url_for('temple_chat_home') }}"><div><div class="icon">💬</div><h3>แชท 4 วัด</h3><p>ติดต่อและคุยงานภายในระบบ</p></div><b>เปิดแชท →</b></a>
      <a class="card cardsmall" href="{{ url_for('my_chats') }}"><div><div class="icon">💬</div><h3>แชทของฉัน</h3><p>ดูแชทที่รับเรื่อง/รับงานแล้ว</p></div><b>ดูข้อความ →</b></a>
      <a class="card cardsmall" href="{{ url_for('invitation') }}"><div><div class="icon">🙏</div><h3>ติดต่อกิจนิมนต์</h3><p>ส่งคำขอนิมนต์ไปยังวัด</p></div><b>ติดต่อ →</b></a>
      <a class="card cardsmall" href="{{ url_for('complaint') }}"><div><div class="icon">📩</div><h3>ติดต่อร้องเรียน</h3><p>ติดต่อทั่วไปหรือแจ้งพฤติกรรม</p></div><b>เปิดฟอร์ม →</b></a>
      <a class="card cardsmall" href="{{ url_for('vinaya_login') }}"><div><div class="icon">🛡️</div><h3>ระบบตรวจสอบพระวินยาธิการ</h3><p>เข้าได้เมื่อ Admin อนุญาต</p></div><b>เข้าสู่ระบบ →</b></a>
      <a class="card cardsmall" href="{{ url_for('blessing') }}"><div><div class="icon">🌼</div><h3>ลงทะเบียนถวายพระพร</h3><p>เปิดใช้ตามวันสำคัญ</p></div><b>เปิดดู →</b></a>
      <a class="card cardsmall" href="{{ url_for('suggestion') }}"><div><div class="icon">💡</div><h3>เสนอแนะ</h3><p>ส่งข้อเสนอให้ Admin</p></div><b>เสนอ →</b></a>
    </section>
    <section class="card" style="margin-top:18px"><h2>💬 โปรไฟล์แชท</h2><p>สมัครบัญชีแชทและจัดการโปรไฟล์ของคุณ</p><div class="actions"><a class="btn primary" href="{{url_for('chat_profile')}}">โปรไฟล์แชท</a><a class="btn" href="{{url_for('my_chats')}}">ประวัติแชท</a><a class="btn" href="{{url_for('chat_friends')}}">เพื่อน</a></div></section>
    <section class="card" style="margin-top:18px"><h2>🛍️ ร้านค้าออนไลน์</h2><p>สินค้าดิจิทัล เช่น รหัสเกม และของออนไลน์ในระบบจำลอง</p><a class="btn primary" href="{{url_for('store_home')}}">เปิดร้านค้า</a></section>
    {% if trending %}<section class="section"><h2>🔥 สินค้าที่มีรีวิวมาก</h2><div class="grid">{% for x in trending %}<a class="card cardsmall" href="{{url_for('store_product',product_id=x.id)}}">{% if x.image_file %}<img class="preview" src="{{url_for('uploaded_file',filename=x.image_file)}}">{% endif %}<h3>{{x.name}}</h3><p>{{x.price}} บาท • ⭐ {{x.review_count}} รีวิว</p></a>{% endfor %}</div></section>{% endif %}
    """
    conn=db(); announcement=conn.execute("SELECT * FROM announcements WHERE is_open=1 ORDER BY id DESC LIMIT 1").fetchone(); announcement_count=conn.execute("SELECT COUNT(*) n FROM system_announcements WHERE is_open=1").fetchone()["n"]; trending=conn.execute("SELECT p.*,u.username seller,COUNT(r.id) review_count FROM store_products p JOIN store_users u ON u.id=p.seller_id LEFT JOIN store_reviews r ON r.product_id=p.id WHERE p.active=1 GROUP BY p.id ORDER BY review_count DESC,p.id DESC LIMIT 6").fetchall(); fw=conn.execute("SELECT * FROM activities WHERE kind='funeral_water'").fetchone(); fc=conn.execute("SELECT * FROM activities WHERE kind='funeral_cremation'").fetchone(); conn.close(); return page("หน้าแรก", body, announcement=announcement,announcement_count=announcement_count,trending=trending,funeral_water_open=bool(fw and fw["is_open"]),funeral_cremation_open=bool(fc and fc["is_open"]))

@app.get("/laws")
def laws():
    conn=db(); rows=conn.execute("SELECT * FROM laws ORDER BY sort_order,id").fetchall(); conn.close()
    body="""
    <section class="section"><div class="sectionhead"><h1>📜 กฎหมายคณะสงฆ์</h1><span class="badge">{{ laws|length }} รายการ</span></div>
    <div class="list">
    {% for x in laws %}<article class="item"><h2>{{ x.sort_order }}. {{ x.title }}</h2><p><b>มาตรา:</b> {{ x.section }}</p><p style="white-space:pre-wrap">{{ x.content }}</p>{% if x.penalty %}<p><b>โทษ/ความผิด:</b> {{ x.penalty }}</p>{% endif %}</article>
    {% else %}<div class="card empty">ยังไม่มีข้อมูลกฎหมาย</div>{% endfor %}</div></section>"""
    return page("กฎหมายคณะสงฆ์",body,laws=rows)

@app.route("/temples")
def temples():
    """ทะเบียนวัดแบบแยกตาม 4 วัด พร้อมสรุปจำนวน โดยไม่เปลี่ยนข้อมูลเดิม"""
    conn=db()
    rows=conn.execute("SELECT * FROM temples WHERE status!='มรณภาพ' ORDER BY temple, id DESC").fetchall()
    death_count=conn.execute("SELECT COUNT(*) n FROM temples WHERE status='มรณภาพ'").fetchone()["n"]
    grouped=[]
    for t in TEMPLE_OPTIONS:
        grouped.append({
            "name": t,
            "rows": [r for r in rows if r["temple"]==t],
            "count": conn.execute("SELECT COUNT(*) n FROM temples WHERE temple=? AND status!='มรณภาพ'", (t,)).fetchone()["n"]
        })
    total=len(rows)
    defrock_count=conn.execute("SELECT COUNT(*) n FROM temples WHERE status LIKE '%สึก%'").fetchone()["n"]
    conn.close()
    body="""
    <section class="section">
      <div class="sectionhead">
        <div><h1>🏯 ทะเบียนวัด</h1><p class="muted">แยกรายชื่อพระและเณรตามสังกัดวัด พร้อมจำนวนแต่ละวัดและจำนวนรวม</p></div>
        <a class="btn" href="{{url_for('home')}}">← หน้าแรก</a>
      </div>
      <section class="grid" style="margin-bottom:18px">
        <div class="card cardsmall"><h3>👥 พระ/เณรรวม</h3><div class="kpi">{{total}}</div></div>
        <div class="card cardsmall"><h3>🕯️ มรณภาพ</h3><div class="kpi">{{death_count}}</div></div>
        <div class="card cardsmall"><h3>📜 บันทึกสึก</h3><div class="kpi">{{defrock_count}}</div></div>
      </section>
      {% for g in grouped %}
      <section class="card" style="margin-bottom:18px">
        <div class="sectionhead"><h2>🏯 {{g.name}}</h2><span class="badge">{{g.count}} รูป/องค์</span></div>
        {% if g.rows %}
        <div class="tablewrap"><table>
          <tr><th>#</th><th>ประเภท</th><th>ชื่อ/ฉายา</th><th>วันที่บวช</th><th>ตำแหน่ง</th><th>สถานะ</th></tr>
          {% for x in g.rows %}
          <tr><td>{{loop.index}}</td><td><span class="badge">{{x.person_type or 'พระ'}}</span></td><td>{{x.name}}</td><td>{{x.ordination_date or '-'}}</td><td>{{x.position or '-'}}</td><td><span class="badge">{{x.status}}</span></td></tr>
          {% endfor %}
        </table></div>
        {% else %}<div class="empty">ยังไม่มีรายชื่อในวัดนี้</div>{% endif %}
      </section>
      {% endfor %}
    </section>
    """
    return page("ทะเบียนวัด", body, grouped=grouped, total=total, death_count=death_count, defrock_count=defrock_count)

@app.get("/council")
def council():
    conn=db(); rows=conn.execute("SELECT * FROM council ORDER BY id DESC").fetchall(); conn.close()
    body="""<section class="section"><h1>🪷 ทะเบียนมหาเถรสมาคม</h1><div class="list">
    {% for x in rows %}<article class="item"><h2>{{ x.royal_name }}</h2><p><b>วันที่ประจำ:</b> {{ x.active_date or '-' }}</p><p><b>วัด:</b> {{ x.temple }}</p><p style="white-space:pre-wrap">{{ x.details }}</p></article>
    {% else %}<div class="card empty">ยังไม่มีข้อมูล</div>{% endfor %}</div></section>"""
    return page("ทะเบียนมหาเถรสมาคม",body,rows=rows)

@app.route("/ordination", methods=["GET","POST"])
def ordination():
    if request.method=="POST":
        require_csrf()
        try:
            age=int(request.form.get("age","0"))
        except ValueError: age=0
        fields=["real_name","temple","chant","kind","birth_temple","reason"]
        if not request.form.get("real_name") or age < 1 or any(not request.form.get(f) for f in fields):
            flash("กรอกข้อมูลระบบบวชให้ครบ", "error")
        else:
            conn=db()
            real_name=request.form["real_name"].strip()
            temple=request.form["temple"].strip()
            chant=request.form["chant"].strip()
            kind=request.form["kind"].strip()
            birth_temple=request.form["birth_temple"].strip()
            reason=request.form["reason"].strip()
            if age < 1 or age > 120 or chant not in ("ได้","ไม่ได้") or kind not in ("พระ","เณร"):
                flash("ข้อมูลอายุ/ตัวเลือกไม่ถูกต้อง", "error")
            else:
                conn.execute("""INSERT INTO ordination_requests
                (real_name,age,temple,chant,kind,birth_temple,reason,status,created_at)
                VALUES(?,?,?,?,?,?,?, 'pending', ?)""",
                (real_name,age,temple,chant,kind,birth_temple,reason,now()))
                conn.commit(); flash("ส่งคำขอบวชเรียบร้อยแล้ว","success")
        return redirect(url_for("ordination"))
    conn=db(); rows=conn.execute("SELECT real_name,kind,status,created_at FROM ordination_requests ORDER BY id DESC LIMIT 20").fetchall(); conn.close()
    body="""<section class="section"><h1>🙏 ระบบบวช</h1><div class="card"><form class="form" method="post">
    <input type="hidden" name="_csrf" value="{{ csrf_token() }}"><div class="formgrid">
    <div><label>1. ชื่อจริง</label><input name="real_name" required></div>
    <div><label>2. อายุ</label><input name="age" type="number" min="1" max="120" required></div>
    <div><label>3. สังกัดวัด</label><select name="temple" required>{% for t in temples %}<option value="{{t}}">{{t}}</option>{% endfor %}</select></div>
    <div><label>4. ท่องบทสวดได้</label><select name="chant"><option>ได้</option><option>ไม่ได้</option></select></div>
    <div><label>5. สถานะบวช</label><select name="kind"><option>พระ</option><option>เณร</option></select></div>
    <div><label>6. วัดเกิด</label><input name="birth_temple" required></div></div>
    <div><label>7. เหตุผล</label><textarea name="reason" required></textarea></div>
    <button class="btn primary" type="submit">ยืนยันส่งคำขอบวช</button></form></div>
    <h2>สถานะคำขอล่าสุด</h2><div class="list">{% for x in rows %}<div class="item"><b>{{x.real_name}}</b> • {{x.kind}} <span class="badge">{{x.status}}</span></div>{% else %}<div class="empty">ยังไม่มีคำขอ</div>{% endfor %}</div></section>"""
    return page("ระบบบวช",body,rows=rows)

@app.route("/education", methods=["GET","POST"])
def education():
    if request.method=="POST":
        require_csrf()
        conn=db()
        name=request.form.get("name","").strip(); typ=request.form.get("type","").strip(); vassa=request.form.get("vassa","").strip(); level=request.form.get("level","").strip()
        if not name or typ not in ("นักธรรม","เปรียญธรรม") or not vassa or not level:
            conn.close(); flash("กรอกข้อมูลสมัครเรียนให้ครบและถูกต้อง","error")
        else:
            dup=conn.execute("SELECT id FROM study_applications WHERE employee_id IS NULL AND name=? AND type=? AND level=? AND status='pending'",(name,typ,level)).fetchone()
            if dup:
                conn.close(); flash("มีใบสมัครเดียวกันที่กำลังรออนุมัติอยู่แล้ว","error")
            else:
                conn.execute("""INSERT INTO study_applications(employee_id,name,type,vassa,level,status,created_at)
                VALUES(NULL,?,?,?,?, 'pending', ?)""",
                (name,typ,vassa,level,now()))
                conn.commit(); conn.close(); flash("ส่งใบสมัครเข้าสู่ระบบพนักงานแล้ว","success")
        return redirect(url_for("education"))
    # Public form intentionally permits application without employee login; employee_id is linked later by admin/employee.
    body="""<section class="section"><h1>📚 สมัครเรียนนักธรรมและเปรียญธรรม</h1>
    <div class="grid">
    <div class="card"><h2>สมัครนักธรรม</h2><form class="form" method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}">
    <input type="hidden" name="type" value="นักธรรม"><label>ชื่อ</label><input name="name" required><label>พรรษา</label><input name="vassa" required>
    <label>ชั้นธรรมที่สมัคร</label><select name="level" required><option value="ตรี">ตรี</option><option value="โท">โท</option><option value="เอก">เอก</option></select><button class="btn primary">ส่งสมัครนักธรรม</button></form></div>
    <div class="card"><h2>สมัครเปรียญธรรม</h2><form class="form" method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}">
    <input type="hidden" name="type" value="เปรียญธรรม"><label>ชื่อ</label><input name="name" required><label>พรรษา</label><input name="vassa" required>
    <label>ชั้นที่จะสมัคร</label><select name="level" required>{% for lv in ["1-2","3","4","5","6","7","8","9"] %}<option value="{{lv}}">{{lv}}</option>{% endfor %}</select><button class="btn primary">ส่งสมัครเปรียญธรรม</button></form></div></div></section>"""
    return page("สมัครเรียน",body)

@app.get("/prayers")
def prayers():
    conn=db(); rows=conn.execute("SELECT * FROM prayers ORDER BY id DESC").fetchall(); conn.close()
    body="""<section class="section"><h1>📖 บทสวดมนต์</h1><div class="list">
    {% for x in rows %}<article class="item"><h2>{{x.title}}</h2>{% if x.body %}<p style="white-space:pre-wrap">{{x.body}}</p>{% endif %}
    {% if x.link %}<p><a class="btn" href="{{x.link}}" target="_blank" rel="noopener">เปิดลิงก์หนังสือสวดมนต์</a></p>{% endif %}
    {% if x.image_file %}<img class="preview" src="{{url_for('uploaded_file',filename=x.image_file)}}" alt="บทสวด">{% endif %}</article>
    {% else %}<div class="card empty">ยังไม่มีบทสวดมนต์</div>{% endfor %}</div></section>"""
    return page("บทสวดมนต์",body,rows=rows)

@app.get("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)

# ------------------------- Admin -------------------------

@app.route("/admin/login", methods=["GET","POST"])
def admin_login():
    if request.method=="POST":
        require_csrf()
        if request.form.get("username")==ADMIN_USER and request.form.get("password")==ADMIN_PASS:
            session.clear(); session["role"]="admin"; session["csrf"]=secrets.token_urlsafe(24)
            flash("เข้าสู่ระบบผู้ดูแลแล้ว","success"); return redirect(url_for("admin"))
        flash("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง","error")
    body="""<section class="login"><div class="card"><h1>⚙️ เข้าสู่ระบบหลังบ้าน</h1>
    <form class="form admin-login-form" method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}">
    <label>ชื่อผู้ใช้</label><input class="admin-login-input" name="username" autocomplete="username" required><label>รหัส</label><input class="admin-login-input" name="password" type="password" autocomplete="current-password" required>
    <button class="btn primary">เข้าสู่ระบบ</button></form></div></section>"""
    return page("Admin Login",body)

@app.get("/admin/logout")
def admin_logout():
    session.clear(); return redirect(url_for("home"))

@app.get("/logout")
def logout():
    session.clear(); return redirect(url_for("home"))

@app.route("/admin/site-control", methods=["GET","POST"])
@admin_required
def admin_site_control():
    if request.method == "POST":
        require_csrf()
        action = request.form.get("action")
        if action == "site_off":
            backup_database(); set_site_state(site_enabled=0)
            flash("ปิดเว็บไซต์ชั่วคราวแล้ว — เฉพาะ Admin ที่ยังเข้าสู่ระบบได้", "success")
        elif action == "site_on":
            clear_attack_lock(); backup_database()
            flash("เปิดใช้งานเว็บไซต์แล้ว", "success")
        elif action == "backup_now":
            backup_database(); flash("สำรองฐานข้อมูลแล้ว", "success")
        elif action == "inputs_off":
            set_site_state(input_enabled=0)
            flash("ปิดการกรอกข้อมูลทุกช่องแล้ว", "success")
        elif action == "inputs_on":
            set_site_state(input_enabled=1)
            flash("เปิดการกรอกข้อมูลทุกช่องแล้ว", "success")
        return redirect(url_for("admin_site_control"))
    state = site_state()
    body="""<section class="section"><h1>🛠️ ควบคุมการใช้งานเว็บไซต์</h1>
    <div class="card"><h2>🌐 สถานะเว็บไซต์</h2>
    <p>สถานะปัจจุบัน: <b>{{ 'เปิดใช้งาน' if state.site_enabled else 'ปิดชั่วคราว' }}</b></p>
    <form method="post" style="display:inline-block"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><button class="btn bad" name="action" value="site_off">ปิดชั่วคราว</button></form>
    <form method="post" style="display:inline-block"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><button class="btn good" name="action" value="site_on">เปิดใช้งานเว็บไซต์</button></form></div>
    <div class="card"><h2>⌨️ การกรอกข้อมูล</h2>
    <p>สถานะปัจจุบัน: <b>{{ 'เปิดใช้งาน' if state.input_enabled else 'ปิดใช้งาน' }}</b></p>
    <p>เมื่อปิด ระบบจะล็อกช่องข้อความและป้องกันการส่งแบบฟอร์มจากผู้ใช้ทั่วไป Admin ยังใช้งานได้ตามปกติ</p>
    <form method="post" style="display:inline-block"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><button class="btn bad" name="action" value="inputs_off">ปิดใช้งาน</button></form>
    <form method="post" style="display:inline-block"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><button class="btn good" name="action" value="inputs_on">เปิดใช้งาน</button></form></div>
    <div class="card"><h2>🛡️ ป้องกันการยิงคำขอรัว</h2><p>ระบบจะตรวจจับคำขอจำนวนมากผิดปกติจากแหล่งเดียว และปิดหน้าเว็บสาธารณะชั่วคราวอัตโนมัติ โดยไม่ส่งคำขอกลับไปยังผู้โจมตี</p>{% if state.attack_lock_reason %}<p><b>{{state.attack_lock_reason}}</b> • {{state.attack_lock_until}}</p>{% endif %}</div>
    <div class="card"><h2>💾 สำรองข้อมูล</h2><p>ระบบเก็บสำเนา SQLite ล่าสุดไว้สูงสุด 10 ชุด และหากฐานข้อมูลหลักหาย/ว่าง ระบบจะพยายามกู้จากสำเนาล่าสุดโดยอัตโนมัติ</p><form method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><button class="btn primary" name="action" value="backup_now">สำรองฐานข้อมูลตอนนี้</button></form></div>
    </section>"""
    return page("ควบคุมเว็บไซต์",body,state=state)

@app.get("/admin")
@admin_required
def admin():
    conn=db()
    counts={
        "system_announcements":conn.execute("SELECT COUNT(*) n FROM system_announcements WHERE is_open=1").fetchone()["n"],
        "laws":conn.execute("SELECT COUNT(*) n FROM laws").fetchone()["n"],
        "temples":conn.execute("SELECT COUNT(*) n FROM temples").fetchone()["n"],
        "ord":conn.execute("SELECT COUNT(*) n FROM ordination_requests WHERE status='pending'").fetchone()["n"],
        "works":conn.execute("SELECT COUNT(*) n FROM works WHERE status='pending'").fetchone()["n"],
        "study":conn.execute("SELECT COUNT(*) n FROM study_applications WHERE status='pending'").fetchone()["n"],
        "preapp":conn.execute("SELECT COUNT(*) n FROM preceptor_applications WHERE status='pending'").fetchone()["n"],
        "salary":conn.execute("SELECT COUNT(*) n FROM salary_requests WHERE status='pending'").fetchone()["n"],
        "promotion":conn.execute("SELECT COUNT(*) n FROM promotion_requests WHERE status='pending'").fetchone()["n"],
        "defrock":conn.execute("SELECT COUNT(*) n FROM defrock_requests WHERE status='pending'").fetchone()["n"],
        "contact":conn.execute("SELECT COUNT(*) n FROM contact_requests WHERE status='pending'").fetchone()["n"],
        "deaths":conn.execute("SELECT COUNT(*) n FROM death_requests WHERE status='pending'").fetchone()["n"],
        "notifications":conn.execute("SELECT COUNT(*) n FROM admin_notifications WHERE is_read=0").fetchone()["n"],
    }
    conn.close()
    body="""<section class="hero"><h1>⚙️ หลังบ้านผู้ดูแล</h1><p>จัดการข้อมูลและคำขอของระบบพระสงฆ์สมไอซ์</p></section>
    <section class="grid">
    <a class="card cardsmall" href="{{url_for('admin_system_announcements')}}"><h3>📢 ระบบประกาศข่าวสาร</h3><div class="kpi">{{c.system_announcements}}</div><span>ประกาศทั่วไป / เร่งด่วน / ปรับปรุง</span></a>
    <a class="card cardsmall" href="{{url_for('admin_laws')}}"><h3>📜 จัดการกฎหมาย</h3><div class="kpi">{{c.laws}}</div><span>เพิ่ม/ลบ/เรียงลำดับ</span></a>
    <a class="card cardsmall" href="{{url_for('admin_temple')}}"><h3>🏯 จัดการทะเบียนวัด</h3><div class="kpi">{{c.temples}}</div><span>เพิ่มบุคคลเข้าวัด</span></a>
    <a class="card cardsmall" href="{{url_for('admin_council')}}"><h3>🪷 จัดการมหาเถรสมาคม</h3><span>เพิ่ม/ลบข้อมูล</span></a>
    <a class="card cardsmall" href="{{url_for('admin_ordination')}}"><h3>🙏 คำขอบวช</h3><div class="kpi">{{c.ord}}</div><span>มอบหมายอุปัชฌาย์</span></a>
    <a class="card cardsmall" href="{{url_for('admin_employees')}}"><h3>👨‍💼 ระบบพนักงาน</h3><span>เพิ่มบัญชีพนักงาน</span></a>
    <a class="card cardsmall" href="{{url_for('admin_works')}}"><h3>🏆 อนุมัติผลงาน</h3><div class="kpi">{{c.works}}</div><span>อนุมัติ/ปฏิเสธ</span></a>
    <a class="card cardsmall" href="{{url_for('admin_study')}}"><h3>📚 ใบสมัครเรียน</h3><div class="kpi">{{c.study}}</div><span>พนักงานเป็นผู้อนุมัติ • Admin ตรวจสอบ</span></a>
    <a class="card cardsmall" href="{{url_for('admin_preceptor')}}"><h3>🧘 ระบบพระอุปัชฌาย์</h3><div class="kpi">{{c.preapp}}</div><span>บัญชี/สมัครอุปัชฌาย์</span></a>
    <a class="card cardsmall" href="{{url_for('admin_prayers')}}"><h3>📖 บทสวดมนต์</h3><span>ข้อความ/ลิงก์/รูป</span></a>
    <a class="card cardsmall" href="{{url_for('admin_salary')}}"><h3>💰 เงินเดือน</h3><div class="kpi">{{c.salary}}</div><span>เปิด/ปิดและอนุมัติคำขอ</span></a>
    <a class="card cardsmall" href="{{url_for('admin_temple_admins')}}"><h3>🏯 เพิ่มเจ้าอาวาส/ผู้ดูแลวัด</h3><span>สร้างบัญชี 4 วัด</span></a>
    <a class="card cardsmall" href="{{url_for('admin_promotion')}}"><h3>🎖️ อนุมัติเลื่อนสมณศักดิ์</h3><div class="kpi">{{c.promotion}}</div><span>อนุมัติ/ไม่อนุมัติ</span></a>
    <a class="card cardsmall" href="{{url_for('admin_defrock')}}"><h3>🧘 คำขอสึก</h3><div class="kpi">{{c.defrock}}</div><span>ส่งต่อให้อุปัชฌาย์</span></a>
    <a class="card cardsmall" href="{{url_for('admin_temple_requests')}}"><h3>🏯 คำขอลบ/ย้ายวัด</h3><span>ตรวจสอบคำขอจากวัด</span></a>
    <a class="card cardsmall" href="{{url_for('admin_activities')}}"><h3>🎯 จัดกิจกรรม</h3><span>เปิด/ปิดกิจกรรมและรับคำขอ</span></a>
    <a class="card cardsmall" href="{{url_for('admin_funeral_activities')}}"><h3>🕯️ กิจกรรมรดน้ำศพ / ฌาปนกิจ</h3><span>เริ่ม/หยุดกิจกรรมและจัดการผู้เข้าร่วม</span></a>
    <a class="card cardsmall" href="{{url_for('admin_contacts')}}"><h3>📩 คำขอติดต่อ Admin</h3><div class="kpi">{{c.contact}}</div><span>ดำเนินการ/ปฏิเสธ</span></a>
    <a class="card cardsmall" href="{{url_for('admin_board')}}"><h3>🏛️ คณะบริหารคณะสงฆ์</h3><span>เพิ่ม/แก้ไข/ลบตำแหน่งและรายชื่อ</span></a>
    <a class="card cardsmall" href="{{url_for('admin_vinaya')}}"><h3>🛡️ ระบบพระวินยาธิการ</h3><span>สร้างบัญชีและอนุญาตการตรวจสอบ</span></a>
    <a class="card cardsmall" href="{{url_for('admin_invitations')}}"><h3>🙏 กิจนิมนต์</h3><span>ดูคำขอและสถานะแชท</span></a>
    <a class="card cardsmall" href="{{url_for('admin_complaints')}}"><h3>📩 ร้องเรียน/ติดต่อ</h3><span>รับเรื่องหรือไม่รับเรื่อง</span></a>
    <a class="card cardsmall" href="{{url_for('admin_deaths')}}"><h3>🕯️ อนุมัติมรณภาพ</h3><div class="kpi">{{c.deaths}}</div><span>คำขอรออนุมัติ • ตรวจสอบก่อนย้ายออกทะเบียน</span></a>
    <a class="card cardsmall" href="{{url_for('admin_documents')}}"><h3>📜 เก็บเอกสารตราตั้ง</h3><span>เพิ่ม/แก้ไข/ลบเอกสาร</span></a>
    <a class="card cardsmall" href="{{url_for('admin_announcement')}}"><h3>📣 ประกาศหรือโฆษณา</h3><span>รูปเต็มหน้าจอเมื่อเข้าเว็บ</span></a>
    <a class="card cardsmall" href="{{url_for('admin_blessing')}}"><h3>🌼 ลงทะเบียนถวายพระพร</h3><span>เปิด/ปิดและดูรายชื่อ</span></a>
    <a class="card cardsmall" href="{{url_for('admin_suggestions')}}"><h3>💡 คำขอเสนอ</h3><span>อ่านและลบข้อเสนอ</span></a>
    <a class="card cardsmall" href="{{url_for('admin_social')}}"><h3>📺 ระบบวิดีโอ</h3><span>จัดการบัญชีและลบโพสต์</span></a>
    <a class="card cardsmall" href="{{url_for('admin_site_control')}}"><h3>🛠️ ปิดใช้งานเว็บไซต์/ช่องกรอก</h3><span>เปิด-ปิดเว็บไซต์และการกรอกข้อมูล</span></a>
    <a class="card cardsmall" href="{{url_for('admin_lottery')}}"><h3>🎫 ระบบสลากออนไลน์</h3><span>จัดการรายการและสถานะชำระเงิน</span></a>
    <a class="card cardsmall" href="{{url_for('admin_lottery_staff')}}"><h3>👤 พนักงานจัดการสลาก</h3><span>เพิ่ม/ลบบัญชีเจ้าหน้าที่</span></a>
    <a class="card cardsmall" href="{{url_for('admin_notifications')}}"><h3>🔔 การแจ้งเตือน Admin</h3><div class="kpi">{{c.notifications}}</div><span>คำขอและเหตุการณ์ใหม่</span></a>
    </section>"""
    return page("หลังบ้าน",body,c=counts)

def notify_admin(kind, title, message, target_id=""):
    conn=db()
    conn.execute("INSERT INTO admin_notifications(kind,title,message,target_id,created_at) VALUES(?,?,?,?,?)",(kind,title,message,str(target_id),now()))
    conn.commit(); conn.close()

@app.route("/admin/notifications",methods=["GET","POST"])
@admin_required
def admin_notifications():
    conn=db()
    if request.method=="POST":
        require_csrf(); action=request.form.get("action")
        if action=="read":
            conn.execute("UPDATE admin_notifications SET is_read=1 WHERE id=?",(int(request.form.get("id",0)),))
        elif action=="read_all":
            conn.execute("UPDATE admin_notifications SET is_read=1 WHERE is_read=0")
        elif action=="delete":
            conn.execute("DELETE FROM admin_notifications WHERE id=?",(int(request.form.get("id",0)),))
        conn.commit()
    rows=conn.execute("SELECT * FROM admin_notifications ORDER BY id DESC LIMIT 200").fetchall(); conn.close()
    body="""<section class="section"><div class="sectionhead"><h1>🔔 การแจ้งเตือน Admin</h1><form method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><button class="btn" name="action" value="read_all">อ่านทั้งหมด</button></form></div><div class="list">{% for x in rows %}<article class="item" style="opacity:{{1 if not x.is_read else .65}}"><b>{{x.title}}</b><p>{{x.message}}</p><small>{{x.created_at}}</small><div class="actions">{% if not x.is_read %}<form method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="id" value="{{x.id}}"><button class="btn good" name="action" value="read">อ่านแล้ว</button></form>{% endif %}<form method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="id" value="{{x.id}}"><button class="btn bad" name="action" value="delete">ลบ</button></form></div></article>{% else %}<div class="empty">ยังไม่มีการแจ้งเตือน</div>{% endfor %}</div></section>"""
    return page("การแจ้งเตือน Admin",body,rows=rows)

@app.route("/lottery", methods=["GET","POST"])
def lottery_home():
    conn=db()
    if request.method=="POST":
        require_csrf(); royal_name=request.form.get("royal_name","").strip(); ticket_no=request.form.get("ticket_no","").strip()
        try: qty=int(request.form.get("quantity","1"))
        except ValueError: qty=0
        if not royal_name or not ticket_no.isdigit() or len(ticket_no)!=3 or qty not in (1,2):
            conn.close(); flash("กรุณากรอกชื่อ เลข 3 หลัก และเลือกจำนวน 1 หรือ 2 ใบ", "error"); return redirect(url_for("lottery_home"))
        conn.execute("INSERT INTO lottery_tickets(royal_name,ticket_no,quantity,payment_status,created_at) VALUES(?,?,?,?,?)",(royal_name,ticket_no,qty,"รอชำระ",now()))
        conn.commit(); conn.close(); flash("บันทึกคำสั่งซื้อแล้ว สถานะเริ่มต้นคือรอชำระ", "success"); return redirect(url_for("lottery_home"))
    draw=conn.execute("SELECT * FROM lottery_draws WHERE id=1").fetchone(); conn.close()
    q=request.args.get("q","").strip(); results=[]
    if q:
        c=db(); results=c.execute("SELECT * FROM lottery_tickets WHERE royal_name LIKE ? ORDER BY id DESC",('%'+q+'%',)).fetchall(); c.close()
    number=request.args.get("number","").strip(); check=None
    if number.isdigit() and len(number)==3:
        msgs=[]
        if draw and draw["prize1"]==number: msgs.append("ถูกรางวัลที่ 1 — 20 บาทในเกม")
        if draw and draw["prize2"]==number: msgs.append("ถูกรางวัลที่ 2 — 15 บาทในเกม")
        if draw and draw["prize3"]==number: msgs.append("ถูกรางวัลที่ 3 — 10 บาทในเกม")
        if draw and draw["last2"] and number[-2:]==draw["last2"]: msgs.append("ถูกเลขท้าย 2 ตัว — 5 บาทในเกม")
        if draw and draw["first2"] and number[:2]==draw["first2"]: msgs.append("ถูกเลขหน้า 2 ตัว — 5 บาทในเกม")
        check={"number":number,"text":" / ".join(msgs) if msgs else "ไม่ถูกรางวัลในงวดนี้"}
    body='''
    <section class="hero"><div style="display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap"><div><h1>🎫 สลากออนไลน์</h1><p>ระบบสลากจำลอง ใช้เพื่อความสนุกเท่านั้น ไม่มีการรับเงินจริงหรือถอนเงินจริง</p></div><a class="btn" href="{{url_for('lottery_staff_login')}}">เจ้าหน้าที่จัดการสลาก</a></div></section>
    <div class="grid">
      <section class="card"><h2>🧾 ซื้อสลากจำลอง</h2><form method="post" class="form"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><label>ชื่อราชทินนาม</label><input name="royal_name" required><label>เลขสลาก 3 ตัว</label><input name="ticket_no" inputmode="numeric" pattern="[0-9]{3}" maxlength="3" minlength="3" required><label>จำนวน</label><select name="quantity"><option value="1">1 ใบ</option><option value="2">2 ใบ</option></select><button class="btn primary">ยืนยันการซื้อ</button></form></section>
      <section class="card"><h2>🔎 ตรวจสอบสถานะชำระเงิน</h2><form method="get" class="form"><input name="q" value="{{request.args.get('q','')}}" placeholder="ชื่อหรือราชทินนาม"><button class="btn">ค้นหา</button></form>{% if results is not none %}<div class="list">{% for x in results %}<article class="item"><b>{{x.royal_name}}</b><div>เลข {{x.ticket_no}} • {{x.quantity}} ใบ</div><div>สถานะ: <strong>{{x.payment_status}}</strong></div></article>{% else %}<div class="empty">ไม่พบรายการ</div>{% endfor %}</div>{% endif %}</section>
    </div>
    <section class="card" style="margin-top:18px"><h2>🏆 ตรวจรางวัล</h2><form method="get" class="form"><input name="number" inputmode="numeric" maxlength="3" pattern="[0-9]{3}" placeholder="กรอกเลข 3 ตัว"><button class="btn primary">ตรวจรางวัล</button></form>{% if check %}<div class="flash success"><b>{{check.number}}</b><br>{{check.text}}</div>{% endif %}<hr><div class="grid"><div><b>รางวัลที่ 1</b> • {{draw.prize1 or 'ยังไม่ออก'}} • 20 บาทในเกม</div><div><b>รางวัลที่ 2</b> • {{draw.prize2 or 'ยังไม่ออก'}} • 15 บาทในเกม</div><div><b>รางวัลที่ 3</b> • {{draw.prize3 or 'ยังไม่ออก'}} • 10 บาทในเกม</div><div><b>เลขท้าย 2 ตัว</b> • {{draw.last2 or 'ยังไม่ออก'}} • 5 บาทในเกม</div><div><b>เลขหน้า 2 ตัว</b> • {{draw.first2 or 'ยังไม่ออก'}} • 5 บาทในเกม</div></div></section>
    '''
    return page("สลากออนไลน์",body,draw=draw,results=results if q else None,check=check)

@app.route("/admin/lottery", methods=["GET","POST"])
@admin_required
def admin_lottery():
    conn=db()
    if request.method=="POST":
        require_csrf(); action=request.form.get("action")
        if action=="status":
            tid=int(request.form.get("id",0)); status=request.form.get("status")
            if status in ("รอชำระ","ชำระเงินแล้ว"):
                conn.execute("UPDATE lottery_tickets SET payment_status=?,paid_at=? WHERE id=?",(status,now() if status=="ชำระเงินแล้ว" else "",tid)); conn.commit(); flash("เปลี่ยนสถานะแล้ว", "success")
        elif action=="delete":
            conn.execute("DELETE FROM lottery_tickets WHERE id=?",(int(request.form.get("id",0)),)); conn.commit(); flash("ลบรายการแล้ว", "success")
        elif action=="draw":
            import random
            vals={k:f"{random.randint(0,999):03d}" for k in ("prize1","prize2","prize3")}; vals["last2"]=f"{random.randint(0,99):02d}"; vals["first2"]=f"{random.randint(0,99):02d}"
            conn.execute("UPDATE lottery_draws SET prize1=?,prize2=?,prize3=?,last2=?,first2=?,updated_at=? WHERE id=1",(vals["prize1"],vals["prize2"],vals["prize3"],vals["last2"],vals["first2"],now())); conn.commit(); flash("สุ่มผลรางวัลแล้ว", "success")
        conn.close(); return redirect(url_for("admin_lottery"))
    tickets=conn.execute("SELECT * FROM lottery_tickets ORDER BY id DESC").fetchall(); draw=conn.execute("SELECT * FROM lottery_draws WHERE id=1").fetchone(); conn.close()
    body='''<section class="section"><h1>🎫 ระบบสลากออนไลน์</h1><p class="muted">รายการทั้งหมดและสถานะการชำระเงินของระบบจำลอง</p><div class="card"><h2>🏆 ผลรางวัล</h2><p>รางวัล 1: {{draw.prize1 or 'ยังไม่ออก'}} • รางวัล 2: {{draw.prize2 or 'ยังไม่ออก'}} • รางวัล 3: {{draw.prize3 or 'ยังไม่ออก'}} • ท้าย: {{draw.last2 or 'ยังไม่ออก'}} • หน้า: {{draw.first2 or 'ยังไม่ออก'}}</p><form method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><button class="btn primary" name="action" value="draw">🎲 สุ่มผลรางวัลใหม่</button></form></div><div class="list">{% for x in tickets %}<article class="item"><h3>{{x.royal_name}} • เลข {{x.ticket_no}} • {{x.quantity}} ใบ</h3><p>สถานะ: <b>{{x.payment_status}}</b> • {{x.created_at}}</p><form method="post" class="actions"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="id" value="{{x.id}}"><select name="status"><option value="รอชำระ" {% if x.payment_status=='รอชำระ' %}selected{% endif %}>ยังไม่ได้ชำระเงิน</option><option value="ชำระเงินแล้ว" {% if x.payment_status=='ชำระเงินแล้ว' %}selected{% endif %}>ชำระเงินแล้ว</option></select><button class="btn good" name="action" value="status">เปลี่ยนสถานะ</button><button class="btn bad" name="action" value="delete" onclick="return confirm('ลบรายการนี้หรือไม่')">ลบ</button></form></article>{% else %}<div class="empty">ยังไม่มีรายการ</div>{% endfor %}</div></section>'''
    return page("Admin • สลากออนไลน์",body,tickets=tickets,draw=draw)

@app.route("/admin/lottery-staff", methods=["GET","POST"])
@admin_required
def admin_lottery_staff():
    conn=db()
    if request.method=="POST":
        require_csrf(); action=request.form.get("action")
        if action=="add":
            username=request.form.get("username","").strip(); password=request.form.get("password","")
            if not username or not password: flash("กรุณากรอกชื่อและรหัส", "error")
            else:
                try: conn.execute("INSERT INTO lottery_staff(username,password_hash,created_at) VALUES(?,?,?)",(username,generate_password_hash(password),now())); conn.commit(); flash("เพิ่มเจ้าหน้าที่แล้ว", "success")
                except sqlite3.IntegrityError: flash("ชื่อผู้ใช้นี้มีอยู่แล้ว", "error")
        elif action=="delete": conn.execute("DELETE FROM lottery_staff WHERE id=?",(int(request.form.get("id",0)),)); conn.commit(); flash("ลบเจ้าหน้าที่แล้ว", "success")
        conn.close(); return redirect(url_for("admin_lottery_staff"))
    staff=conn.execute("SELECT * FROM lottery_staff ORDER BY id DESC").fetchall(); conn.close()
    body='''<section class="section"><h1>👤 พนักงานจัดการสลาก</h1><form method="post" class="card form"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="add"><label>ชื่อ</label><input name="username" required><label>รหัส</label><input name="password" type="password" required><button class="btn primary">ตกลง</button></form><div class="list">{% for x in staff %}<article class="item"><b>{{x.username}}</b><form method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="delete"><input type="hidden" name="id" value="{{x.id}}"><button class="btn bad">ลบ</button></form></article>{% endfor %}</div></section>'''
    return page("พนักงานจัดการสลาก",body,staff=staff)

@app.route("/lottery/staff-login", methods=["GET","POST"])
def lottery_staff_login():
    if request.method=="POST":
        require_csrf(); username=request.form.get("username","").strip(); password=request.form.get("password","")
        conn=db(); row=conn.execute("SELECT * FROM lottery_staff WHERE username=?",(username,)).fetchone(); conn.close()
        if row and check_password_hash(row["password_hash"],password): session["lottery_staff_id"]=row["id"]; return redirect(url_for("lottery_staff"))
        flash("ชื่อหรือรหัสไม่ถูกต้อง", "error")
    body='''<section class="section"><div class="card form"><h1>👤 เจ้าหน้าที่จัดการสลาก</h1><form method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><label>ชื่อ</label><input name="username" required><label>รหัส</label><input name="password" type="password" required><button class="btn primary">เข้าสู่ระบบ</button></form></div></section>'''
    return page("เข้าสู่ระบบเจ้าหน้าที่สลาก",body)

def lottery_staff_required(fn):
    @wraps(fn)
    def wrapper(*args,**kwargs):
        if not session.get("lottery_staff_id"): return redirect(url_for("lottery_staff_login"))
        return fn(*args,**kwargs)
    return wrapper

@app.route("/lottery/staff", methods=["GET","POST"])
@lottery_staff_required
def lottery_staff():
    conn=db()
    if request.method=="POST":
        require_csrf(); tid=int(request.form.get("id",0)); conn.execute("UPDATE lottery_tickets SET payment_status='ชำระเงินแล้ว',paid_at=? WHERE id=? AND payment_status='รอชำระ'",(now(),tid)); conn.commit(); conn.close(); return redirect(url_for("lottery_staff"))
    tickets=conn.execute("SELECT * FROM lottery_tickets WHERE payment_status='รอชำระ' ORDER BY id DESC").fetchall(); conn.close()
    body='''<section class="section"><div class="hero"><h1>👤 เจ้าหน้าที่จัดการสลาก</h1><p>แสดงเฉพาะรายการที่ยังไม่ได้รับชำระเงิน</p></div><div class="list">{% for x in tickets %}<article class="item"><h3>{{x.royal_name}}</h3><p>เลข {{x.ticket_no}} • {{x.quantity}} ใบ • {{x.created_at}}</p><form method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="id" value="{{x.id}}"><button class="btn good">ยืนยันว่าชำระเงินแล้ว</button></form></article>{% else %}<div class="empty">ไม่มีรายการรอชำระ</div>{% endfor %}</div><a class="btn" href="{{url_for('lottery_home')}}">กลับหน้าสลาก</a></section>'''
    return page("เจ้าหน้าที่จัดการสลาก",body,tickets=tickets)

@app.route("/admin/laws", methods=["GET","POST"])
@admin_required
def admin_laws():
    conn=db()
    if request.method=="POST":
        require_csrf()
        action=request.form.get("action")
        if action=="add":
            title=request.form.get("title","").strip(); section=request.form.get("section","").strip()
            content=request.form.get("content","").strip(); penalty=request.form.get("penalty","").strip()
            if not title or not section or not content:
                flash("กรอกชื่อกฎหมาย มาตรา และเนื้อหาให้ครบ","error")
            else:
                conn.execute("INSERT INTO laws(sort_order,title,section,content,penalty,created_at) VALUES(?,?,?,?,?,?)",
                             (next_law_order(conn),title,section,content,penalty,now()))
                conn.commit(); flash("เพิ่มกฎหมายเรียบร้อย","success")
        elif action=="edit":
            lid=int(request.form.get("id",0)); title=request.form.get("title","").strip(); section=request.form.get("section","").strip(); content=request.form.get("content","").strip(); penalty=request.form.get("penalty","").strip()
            conn.execute("UPDATE laws SET title=?,section=?,content=?,penalty=? WHERE id=?",(title,section,content,penalty,lid)); conn.commit(); flash("แก้ไขกฎหมายแล้ว","success")
        elif action=="delete":
            lid=int(request.form.get("id",0))
            conn.execute("DELETE FROM laws WHERE id=?", (lid,)); conn.commit()
            # Re-number 1..N after deletion.
            rows=conn.execute("SELECT id FROM laws ORDER BY sort_order,id").fetchall()
            for i,row in enumerate(rows,1):
                conn.execute("UPDATE laws SET sort_order=? WHERE id=?",(i,row["id"]))
            conn.commit(); flash("ลบกฎหมายและจัดลำดับใหม่แล้ว","success")
        return redirect(url_for("admin_laws"))
    rows=conn.execute("SELECT * FROM laws ORDER BY sort_order,id").fetchall(); conn.close()
    body="""<section class="section"><div class="sectionhead"><h1>📜 จัดการกฎหมายคณะสงฆ์</h1><a class="btn" href="{{url_for('admin')}}">← หลังบ้าน</a></div>
    <div class="card"><h2>เพิ่มกฎหมาย</h2><form class="form" method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="add">
    <label>ชื่อกฎหมาย</label><input name="title" required><label>มาตรา</label><input name="section" placeholder="เช่น มาตรา 1" required>
    <label>เนื้อหา</label><textarea name="content" required></textarea><label>โทษ/ความผิด</label><textarea name="penalty"></textarea>
    <button class="btn primary">ยืนยันเพิ่มกฎหมาย</button></form></div>
    <h2>รายการกฎหมายทั้งหมด</h2><div class="list">{% for x in rows %}<article class="item"><h3>{{x.sort_order}}. {{x.title}}</h3><p><b>{{x.section}}</b></p><p style="white-space:pre-wrap">{{x.content}}</p>{% if x.penalty %}<p><b>โทษ/ความผิด:</b> {{x.penalty}}</p>{% endif %}
    <button class="btn" type="button" onclick="document.getElementById('edit-law-{{x.id}}').style.display='block'">เปลี่ยนข้อมูล</button> <form method="post" style="display:inline" onsubmit="return confirm('ยืนยันการลบกฎหมายรายการนี้หรือไม่?');"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="delete"><input type="hidden" name="id" value="{{x.id}}"><button class="btn bad">ลบ</button></form><div id="edit-law-{{x.id}}" class="card" style="display:none;margin-top:8px"><form class="form" method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="edit"><input type="hidden" name="id" value="{{x.id}}"><label>ชื่อกฎหมาย</label><input name="title" value="{{x.title}}" required><label>มาตรา</label><input name="section" value="{{x.section}}" required><label>เนื้อหา</label><textarea name="content" required>{{x.content}}</textarea><label>โทษ/ความผิด</label><textarea name="penalty">{{x.penalty}}</textarea><button class="btn primary">บันทึกการเปลี่ยนข้อมูล</button></form></div></article>{% else %}<div class="empty">ยังไม่มีรายการ</div>{% endfor %}</div></section>"""
    return page("จัดการกฎหมาย",body,rows=rows)

@app.route("/admin/temple", methods=["GET","POST"])
@admin_required
def admin_temple():
    conn=db()
    if request.method=="POST":
        require_csrf(); action=request.form.get("action")
        if action=="add":
            conn.execute("INSERT INTO temples(name,ordination_date,temple,status,source,position,person_type,created_at) VALUES(?,?,?,?,?,?,?,?)",
                         (request.form["name"],request.form.get("ordination_date",""),request.form["temple"],request.form.get("status","บวชแล้ว"),"manual",request.form.get("position",""),request.form.get("person_type","พระ"),now()))
            conn.commit(); flash("เพิ่มบุคคลเข้าทะเบียนวัดแล้ว","success")
        elif action=="delete":
            conn.execute("DELETE FROM temples WHERE id=?",(request.form["id"],)); conn.commit(); flash("ลบรายการแล้ว","success")
        elif action=="edit":
            conn.execute("UPDATE temples SET name=?,ordination_date=?,temple=?,status=?,position=?,person_type=? WHERE id=?",
                         (request.form["name"],request.form.get("ordination_date",""),request.form["temple"],request.form.get("status","บวชแล้ว"),request.form.get("position",""),request.form.get("person_type","พระ"),request.form["id"]))
            conn.commit(); flash("แก้ไขข้อมูลทะเบียนวัดแล้ว","success")
        return redirect(url_for("admin_temple"))
    rows=conn.execute("SELECT * FROM temples ORDER BY id DESC").fetchall(); conn.close()
    body="""<section class="section"><h1>🏯 จัดการทะเบียนวัด</h1><div class="card"><form class="form" method="post">
    <input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="add">
    <div class="formgrid"><div><label>ประเภท</label><select name="person_type"><option value="พระ">พระ</option><option value="เณร">เณร</option></select></div><div><label>ชื่อ/ฉายา</label><input name="name" required></div><div><label>วันที่บวช</label><input name="ordination_date" type="date"></div>
    <div><label>วัดที่ประจำ</label><select name="temple" required>{% for t in temples %}<option value="{{t}}">{{t}}</option>{% endfor %}</select></div><div><label>สถานะ</label><input name="status" value="บวชแล้ว"></div></div>
    <label>ตำแหน่งทางคณะสงฆ์</label><select name="position"><option value="">-- ไม่มี/ไม่ระบุ --</option>{% for p in position_options %}<option>{{p}}</option>{% endfor %}</select>
    <button class="btn primary">เพิ่มเข้าทะเบียนวัด</button></form></div>
    <div class="tablewrap"><table><tr><th>ประเภท</th><th>ชื่อ</th><th>วันที่บวช</th><th>วัด</th><th>ตำแหน่ง</th><th>สถานะ</th><th>จัดการ</th></tr>
    {% for x in rows %}<tr><td>{{x.person_type or 'พระ'}}</td><td>{{x.name}}</td><td>{{x.ordination_date or '-'}}</td><td>{{x.temple}}</td><td>{{x.position or '-'}}</td><td>{{x.status}}</td><td><button class="btn" type="button" onclick="document.getElementById('edit-{{x.id}}').style.display='block'">เปลี่ยนข้อมูล</button>
    <form method="post" style="display:inline" onsubmit="return confirm('ยืนยันลบรายการนี้?')"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="delete"><input type="hidden" name="id" value="{{x.id}}"><button class="btn bad">ลบ</button></form>
    <div id="edit-{{x.id}}" class="card" style="display:none;margin-top:8px"><form class="form" method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="edit"><input type="hidden" name="id" value="{{x.id}}"><label>ประเภท</label><select name="person_type"><option value="พระ" {% if (x.person_type or 'พระ')=='พระ' %}selected{% endif %}>พระ</option><option value="เณร" {% if x.person_type=='เณร' %}selected{% endif %}>เณร</option></select><label>ชื่อ/ฉายา</label><input name="name" value="{{x.name}}" required><label>วันที่บวช</label><input name="ordination_date" type="date" value="{{x.ordination_date}}"><label>วัด</label><select name="temple" required>{% for t in temples %}<option value="{{t}}" {% if x.temple==t %}selected{% endif %}>{{t}}</option>{% endfor %}</select><label>สถานะ</label><input name="status" value="{{x.status}}"><label>ตำแหน่ง</label><select name="position"><option value="">-- ไม่ระบุ --</option>{% for p in position_options %}<option value="{{p}}" {% if x.position==p %}selected{% endif %}>{{p}}</option>{% endfor %}</select><button class="btn primary">บันทึกการเปลี่ยนข้อมูล</button></form></div></td></tr>{% endfor %}</table></div></section>"""
    return page("จัดการทะเบียนวัด",body,rows=rows,position_options=POSITION_OPTIONS)


@app.route("/admin/council", methods=["GET","POST"])
@admin_required
def admin_council():
    conn=db()
    if request.method=="POST":
        require_csrf(); action=request.form.get("action")
        if action=="add":
            conn.execute("INSERT INTO council(royal_name,active_date,temple,details,position,created_at) VALUES(?,?,?,?,?,?)",
                         (request.form["royal_name"],request.form.get("active_date",""),request.form["temple"],request.form.get("details",""),request.form.get("position",""),now()))
            conn.commit(); flash("เพิ่มทะเบียนมหาเถรสมาคมแล้ว","success")
        elif action=="delete":
            conn.execute("DELETE FROM council WHERE id=?",(request.form["id"],)); conn.commit(); flash("ลบรายการแล้ว","success")
        elif action=="edit":
            conn.execute("UPDATE council SET royal_name=?,active_date=?,temple=?,details=?,position=? WHERE id=?",
                         (request.form["royal_name"],request.form.get("active_date",""),request.form["temple"],request.form.get("details",""),request.form.get("position",""),request.form["id"]))
            conn.commit(); flash("แก้ไขทะเบียนมหาเถรสมาคมแล้ว","success")
        return redirect(url_for("admin_council"))
    rows=conn.execute("SELECT * FROM council ORDER BY id DESC").fetchall(); conn.close()
    body="""<section class="section"><h1>🪷 จัดการทะเบียนมหาเถรสมาคม</h1><div class="card"><form class="form" method="post">
    <input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="add">
    <label>ชื่อราชทินนาม</label><input name="royal_name" required><label>วันที่ประจำ</label><input name="active_date" type="date">
    <label>วัดที่ประจำการ</label><select name="temple" required>{% for t in temples %}<option value="{{t}}">{{t}}</option>{% endfor %}</select><label>ตำแหน่ง/หน้าที่</label><select name="position"><option value="">-- ไม่ระบุ --</option>{% for p in position_options %}<option>{{p}}</option>{% endfor %}</select><label>รายละเอียด</label><textarea name="details"></textarea><button class="btn primary">เพิ่มข้อมูล</button></form></div>
    <div class="list">{% for x in rows %}<div class="item"><h3>{{x.royal_name}}</h3><p>{{x.active_date}} • {{x.temple}} • {{x.position or '-'}}</p><p>{{x.details}}</p><button class="btn" type="button" onclick="document.getElementById('edit-council-{{x.id}}').style.display='block'">เปลี่ยนข้อมูล</button>
    <form method="post" style="display:inline" onsubmit="return confirm('ยืนยันลบรายการนี้?')"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="delete"><input type="hidden" name="id" value="{{x.id}}"><button class="btn bad">ลบ</button></form>
    <div id="edit-council-{{x.id}}" class="card" style="display:none;margin-top:8px"><form class="form" method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="edit"><input type="hidden" name="id" value="{{x.id}}"><label>ชื่อราชทินนาม</label><input name="royal_name" value="{{x.royal_name}}" required><label>วันที่ประจำ</label><input name="active_date" type="date" value="{{x.active_date}}"><label>วัด</label><select name="temple" required>{% for t in temples %}<option value="{{t}}" {% if x.temple==t %}selected{% endif %}>{{t}}</option>{% endfor %}</select><label>ตำแหน่ง/หน้าที่</label><select name="position"><option value="">-- ไม่ระบุ --</option>{% for p in position_options %}<option value="{{p}}" {% if x.position==p %}selected{% endif %}>{{p}}</option>{% endfor %}</select><label>รายละเอียด</label><textarea name="details">{{x.details}}</textarea><button class="btn primary">บันทึกการเปลี่ยนข้อมูล</button></form></div></div>{% endfor %}</div></section>"""
    return page("จัดการมหาเถรสมาคม",body,rows=rows,position_options=POSITION_OPTIONS)


@app.route("/admin/ordination", methods=["GET","POST"])
@admin_required
def admin_ordination():
    conn=db()
    if request.method=="POST":
        require_csrf(); action=request.form.get("action"); oid=int(request.form["id"])
        if action=="assign":
            try: pid=int(request.form["preceptor_id"])
            except (TypeError,ValueError): pid=0
            pre=conn.execute("SELECT id FROM preceptors WHERE id=?",(pid,)).fetchone()
            if not pre:
                flash("ไม่พบพระอุปัชฌาย์ที่เลือก", "error")
            else:
                cur=conn.execute("UPDATE ordination_requests SET assigned_preceptor_id=?,status='รออนุมัติจากพระอุปัชฌาย์' WHERE id=? AND status='pending'",(pid,oid))
                if not cur.rowcount:
                    flash("คำขอนี้ถูกมอบหมายหรือดำเนินการไปแล้ว", "error")
                else:
                    conn.commit(); flash("ส่งคำขอไปยังพระอุปัชฌาย์แล้ว","success")
        elif action=="reject":
            cur=conn.execute("UPDATE ordination_requests SET status='ปฏิเสธ' WHERE id=? AND status='pending'",(oid,))
            if cur.rowcount: conn.commit(); flash("ปฏิเสธคำขอแล้ว","success")
            else: flash("คำขอนี้ถูกดำเนินการไปแล้ว", "error")
        return redirect(url_for("admin_ordination"))
    rows=conn.execute("""SELECT o.*,p.username preceptor_username,p.display_name preceptor_name
                         FROM ordination_requests o LEFT JOIN preceptors p ON p.id=o.assigned_preceptor_id
                         ORDER BY o.id DESC""").fetchall()
    preceptors=conn.execute("SELECT * FROM preceptors ORDER BY id DESC").fetchall(); conn.close()
    body="""<section class="section"><h1>🙏 จัดการคำขอบวช</h1><div class="list">
    {% for x in rows %}<article class="item"><h3>{{x.real_name}} • {{x.kind}}</h3><p>อายุ {{x.age}} • สังกัด {{x.temple}} • ท่องบทสวด: {{x.chant}}</p><p>วัดเกิด: {{x.birth_temple}}</p><p>เหตุผล: {{x.reason}}</p><p>สถานะ: <span class="badge">{{x.status}}</span></p>
    {% if x.status=='pending' %}
    <form class="form" method="post" onsubmit="return confirm('ยืนยันส่งคำขอนี้ให้พระอุปัชฌาย์ที่เลือก?')"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="id" value="{{x.id}}"><input type="hidden" name="action" value="assign">
    <label>เลือกพระอุปัชฌาย์</label><select name="preceptor_id" required><option value="">-- เลือก --</option>{% for p in preceptors %}<option value="{{p.id}}">{{p.display_name or p.username}} ({{p.username}})</option>{% endfor %}</select><button class="btn primary">ส่งให้พระอุปัชฌาย์</button></form>
    {% endif %}{% if x.status=='pending' %}<form method="post" style="margin-top:8px" onsubmit="return confirm('ยืนยันปฏิเสธคำขอบวชนี้?')"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="id" value="{{x.id}}"><input type="hidden" name="action" value="reject"><button class="btn bad">ปฏิเสธ</button></form>{% endif %}
    </article>{% else %}<div class="empty">ไม่มีคำขอ</div>{% endfor %}</div></section>"""
    return page("คำขอบวช",body,rows=rows,preceptors=preceptors)

@app.route("/admin/employees", methods=["GET","POST"])
@admin_required
def admin_employees():
    conn=db()
    if request.method=="POST":
        require_csrf(); action=request.form.get("action")
        if action=="create":
            username=request.form["username"].strip(); password=request.form["password"]; display=request.form.get("display_name","").strip()
            try:
                conn.execute("INSERT INTO employees(username,password_hash,display_name,created_at,position) VALUES(?,?,?,?,?)",
                             (username,generate_password_hash(password),display,now(),request.form.get("position","")))
                conn.commit(); flash("เพิ่มบัญชีพนักงานแล้ว","success")
            except sqlite3.IntegrityError: flash("ชื่อผู้ใช้นี้มีอยู่แล้ว","error")
        elif action=="delete":
            conn.execute("DELETE FROM employees WHERE id=?",(request.form["id"],)); conn.commit(); flash("ลบบัญชีพนักงานแล้ว","success")
        elif action=="edit":
            conn.execute("UPDATE employees SET username=?,display_name=?,position=? WHERE id=?",
                         (request.form["username"].strip(),request.form.get("display_name","").strip(),request.form.get("position",""),request.form["id"]))
            if request.form.get("password"):
                conn.execute("UPDATE employees SET password_hash=? WHERE id=?",(generate_password_hash(request.form["password"]),request.form["id"]))
            conn.commit(); flash("แก้ไขข้อมูลพนักงานแล้ว","success")
        return redirect(url_for("admin_employees"))
    rows=conn.execute("SELECT id,username,display_name,total_works,position,created_at FROM employees ORDER BY id DESC").fetchall(); conn.close()
    body="""<section class="section"><h1>👨‍💼 ระบบพนักงาน</h1><div class="card"><form class="form" method="post">
    <input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="create"><div class="formgrid"><div><label>ชื่อผู้ใช้</label><input name="username" required></div>
    <div><label>รหัสผู้ใช้</label><input name="password" type="password" required></div><div><label>ชื่อ</label><input name="display_name"></div></div><label>ตำแหน่งทางคณะสงฆ์</label><select name="position"><option value="">-- ไม่ระบุ --</option>{% for p in position_options %}<option>{{p}}</option>{% endfor %}</select><button class="btn primary">เพิ่มบัญชีพนักงาน</button></form></div>
    <div class="tablewrap"><table><tr><th>ชื่อผู้ใช้</th><th>ชื่อ</th><th>ตำแหน่ง</th><th>ผลงานสะสม</th><th>จัดการ</th></tr>{% for x in rows %}<tr><td>{{x.username}}</td><td>{{x.display_name}}</td><td>{{x.position or '-'}}</td><td>{{x.total_works}}</td><td><button class="btn" type="button" onclick="document.getElementById('edit-emp-{{x.id}}').style.display='block'">เปลี่ยนข้อมูล</button><form method="post" style="display:inline" onsubmit="return confirm('ยืนยันลบบัญชีพนักงานนี้? ข้อมูลผลงาน/ใบสมัครที่ผูกกับบัญชีอาจถูกลบด้วย')"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="delete"><input type="hidden" name="id" value="{{x.id}}"><button class="btn bad">ลบ</button></form>
    <div id="edit-emp-{{x.id}}" class="card" style="display:none;margin-top:8px"><form class="form" method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="edit"><input type="hidden" name="id" value="{{x.id}}"><label>ชื่อผู้ใช้</label><input name="username" value="{{x.username}}" required><label>ชื่อ</label><input name="display_name" value="{{x.display_name}}"><label>รหัสใหม่ (เว้นว่างถ้าไม่เปลี่ยน)</label><input name="password" type="password"><label>ตำแหน่ง</label><select name="position"><option value="">-- ไม่ระบุ --</option>{% for p in position_options %}<option value="{{p}}" {% if x.position==p %}selected{% endif %}>{{p}}</option>{% endfor %}</select><button class="btn primary">บันทึกการเปลี่ยนข้อมูล</button></form></div></td></tr>{% endfor %}</table></div></section>"""
    return page("ระบบพนักงาน",body,rows=rows,position_options=POSITION_OPTIONS)
@app.route("/admin/works", methods=["GET","POST"])
@admin_required
def admin_works():
    conn=db()
    if request.method=="POST":
        require_csrf(); wid=int(request.form["id"]); action=request.form["action"]
        row=conn.execute("SELECT * FROM works WHERE id=?",(wid,)).fetchone()
        if row and row["status"]=="pending" and action in ("approve","reject"):
            status="approved" if action=="approve" else "rejected"
            cur=conn.execute("UPDATE works SET status=? WHERE id=? AND status='pending'",(status,wid))
            if cur.rowcount:
                if status=="approved":
                    conn.execute("UPDATE employees SET total_works=total_works+? WHERE id=?",(row["work_count"],row["employee_id"]))
                conn.commit(); flash("อนุมัติ/ปฏิเสธผลงานเรียบร้อยแล้ว","success")
            else:
                flash("รายการนี้ถูกดำเนินการไปแล้ว","error")
        return redirect(url_for("admin_works"))
    rows=conn.execute("""SELECT w.*,e.username,e.display_name FROM works w JOIN employees e ON e.id=w.employee_id ORDER BY w.id DESC""").fetchall(); conn.close()
    body="""<section class="section"><h1>🏆 อนุมัติผลงาน</h1><div class="list">{% for x in rows %}<article class="item"><h3>{{x.name}} • {{x.work_count}} ผลงาน</h3>
    <p>พนักงาน: {{x.display_name or x.username}} • <span class="badge">{{x.status}}</span></p>{% if x.image_file %}<img class="preview" src="{{url_for('uploaded_file',filename=x.image_file)}}">{% endif %}
    {% if x.status=='pending' %}<div class="actions"><form method="post" onsubmit="return confirm('ยืนยันอนุมัติผลงานรายการนี้?')"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="id" value="{{x.id}}"><input type="hidden" name="action" value="approve"><button class="btn good">อนุมัติ</button></form>
    <form method="post" onsubmit="return confirm('ยืนยันปฏิเสธผลงานรายการนี้?')"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="id" value="{{x.id}}"><input type="hidden" name="action" value="reject"><button class="btn bad">ปฏิเสธ</button></form></div>{% endif %}</article>{% else %}<div class="empty">ไม่มีรายการ</div>{% endfor %}</div></section>"""
    return page("อนุมัติผลงาน",body,rows=rows)

@app.route("/admin/study",methods=["GET","POST"])
@admin_required
def admin_study():
    conn=db()
    if request.method=="POST":
        require_csrf(); sid=int(request.form.get("id",0)); action=request.form.get("action"); row=conn.execute("SELECT * FROM study_applications WHERE id=?",(sid,)).fetchone()
        if row:
            if action=="pass":
                temple=request.form.get("temple","")
                if temple not in TEMPLE_OPTIONS: flash("กรุณาเลือกวัด","error")
                else:
                    conn.execute("UPDATE study_applications SET status='approved',exam_result='ผ่าน',temple=? WHERE id=?",(temple,sid))
                    label=row["type"]+" "+row["level"]
                    if not conn.execute("SELECT id FROM temples WHERE source='study_exam' AND source_ref=?",(str(sid),)).fetchone():
                        conn.execute("INSERT INTO temples(name,ordination_date,temple,status,source,source_ref,position,created_at) VALUES(?,?,?,?,?,?,?,?)",(row["name"],"",temple,label,"study_exam",str(sid),"",now()))
                    conn.commit(); flash("บันทึกว่าสอบผ่านและเพิ่มสถานะในทะเบียนวัดแล้ว","success")
            elif action=="fail" or action=="delete": conn.execute("DELETE FROM study_applications WHERE id=?",(sid,)); conn.commit(); flash("ลบใบสมัคร/ผลสอบไม่ผ่านแล้ว","success")
        conn.close(); return redirect(url_for("admin_study"))
    rows=conn.execute("SELECT s.*,e.username,e.display_name FROM study_applications s LEFT JOIN employees e ON e.id=s.employee_id ORDER BY s.id DESC").fetchall(); conn.close()
    body="""<section class="section"><h1>📚 ใบสมัครนักธรรม/เปรียญธรรม</h1><div class="list">{% for x in rows %}<article class="item"><h3>{{x.name}} • {{x.type}} {{x.level}}</h3><p>พรรษา {{x.vassa}} • วัด {{x.temple or 'ยังไม่ระบุ'}} • <span class="badge">{{x.status}} {{x.exam_result}}</span></p><form method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="id" value="{{x.id}}"><select name="temple"><option value="">เลือกวัดเมื่อสอบผ่าน</option>{% for t in temples %}<option value="{{t}}" {% if x.temple==t %}selected{% endif %}>{{t}}</option>{% endfor %}</select><button class="btn good" name="action" value="pass">สอบผ่าน</button><button class="btn bad" name="action" value="fail">ไม่ผ่าน/ลบ</button><button class="btn" name="action" value="delete">ลบประวัติ</button></form></article>{% else %}<div class="empty">ยังไม่มีใบสมัคร</div>{% endfor %}</div></section>"""
    return page("ใบสมัครนักธรรม/เปรียญธรรม", body, rows=rows, temples=TEMPLE_OPTIONS)

@app.route("/admin/preceptor", methods=["GET","POST"])
@admin_required
def admin_preceptor():
    conn=db()
    if request.method=="POST":
        require_csrf(); action=request.form.get("action")
        if action=="create":
            try:
                conn.execute("INSERT INTO preceptors(username,password_hash,display_name,created_at,position) VALUES(?,?,?,?,?)",
                             (request.form["username"],generate_password_hash(request.form["password"]),request.form.get("display_name",""),now(),request.form.get("position","พระอุปัชฌาย์")))
                conn.commit(); flash("สร้างบัญชีพระอุปัชฌาย์แล้ว","success")
            except sqlite3.IntegrityError: flash("ชื่อผู้ใช้นี้มีอยู่แล้ว","error")
        elif action=="delete":
            conn.execute("DELETE FROM preceptors WHERE id=?",(request.form["id"],)); conn.commit(); flash("ลบบัญชีพระอุปัชฌาย์แล้ว","success")
        elif action=="edit":
            conn.execute("UPDATE preceptors SET username=?,display_name=?,position=? WHERE id=?",
                         (request.form["username"],request.form.get("display_name",""),request.form.get("position",""),request.form["id"]))
            if request.form.get("password"):
                conn.execute("UPDATE preceptors SET password_hash=? WHERE id=?",(generate_password_hash(request.form["password"]),request.form["id"]))
            conn.commit(); flash("แก้ไขข้อมูลพระอุปัชฌาย์แล้ว","success")
        elif action in ("approve","reject"):
            pid=int(request.form["id"]); row=conn.execute("SELECT * FROM preceptor_applications WHERE id=? AND status='pending'",(pid,)).fetchone()
            if row:
                status="approved" if action=="approve" else "rejected"; conn.execute("UPDATE preceptor_applications SET status=? WHERE id=?",(status,pid))
                if status=="approved" and not conn.execute("SELECT id FROM temples WHERE source='preceptor_application' AND source_ref=?",(str(row["id"]),)).fetchone():
                    conn.execute("INSERT INTO temples(name,ordination_date,temple,status,source,source_ref,position,created_at) VALUES(?,?,?,?,?,?,?,?)",
                                 (row["name"],"",row["temple"],"รอสอบอุปัชฌาย์","preceptor_application",str(row["id"]),"พระอุปัชฌาย์",now()))
                conn.commit(); flash("ดำเนินการสมัครอุปัชฌาย์แล้ว","success")
            else: flash("คำขอนี้ถูกดำเนินการไปแล้วหรือไม่พบข้อมูล","error")
        return redirect(url_for("admin_preceptor"))
    preceptors=conn.execute("SELECT * FROM preceptors ORDER BY id DESC").fetchall()
    apps=conn.execute("SELECT a.*,e.username FROM preceptor_applications a LEFT JOIN employees e ON e.id=a.employee_id ORDER BY a.id DESC").fetchall(); conn.close()
    body="""<section class="section"><h1>🧘 ระบบพระอุปัชฌาย์</h1><div class="card"><h2>เพิ่มบัญชีพระอุปัชฌาย์</h2><form class="form" method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="create"><div class="formgrid"><div><label>ชื่อผู้ใช้</label><input name="username" required></div><div><label>รหัสผู้ใช้</label><input name="password" type="password" required></div><div><label>ชื่อ</label><input name="display_name"></div></div><label>ตำแหน่งทางคณะสงฆ์</label><select name="position">{% for p in position_options %}<option {% if p=='พระอุปัชฌาย์' %}selected{% endif %}>{{p}}</option>{% endfor %}</select><button class="btn primary">สร้างบัญชี</button></form></div>
    <h2>คำขอสมัครอุปัชฌาย์</h2><div class="list">{% for x in apps %}<div class="item"><h3>{{x.name}}</h3><p>พรรษา {{x.vassa}} • {{x.temple}} • <span class="badge">{{x.status}}</span></p>{% if x.status=='pending' %}<div class="actions"><form method="post" onsubmit="return confirm('ยืนยันการดำเนินการกับคำขอนี้?')"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="id" value="{{x.id}}"><button class="btn good" name="action" value="approve">อนุมัติ</button><button class="btn bad" name="action" value="reject">ปฏิเสธ</button></form></div>{% endif %}</div>{% else %}<div class="empty">ไม่มีคำขอ</div>{% endfor %}</div>
    <h2>บัญชีพระอุปัชฌาย์</h2><div class="tablewrap"><table><tr><th>ผู้ใช้</th><th>ชื่อ</th><th>ตำแหน่ง</th><th>จัดการ</th></tr>{% for x in preceptors %}<tr><td>{{x.username}}</td><td>{{x.display_name}}</td><td>{{x.position or '-'}}</td><td><button class="btn" type="button" onclick="document.getElementById('edit-pre-{{x.id}}').style.display='block'">เปลี่ยนข้อมูล</button><form method="post" style="display:inline" onsubmit="return confirm('ยืนยันลบบัญชีนี้?')"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="delete"><input type="hidden" name="id" value="{{x.id}}"><button class="btn bad">ลบ</button></form><div id="edit-pre-{{x.id}}" class="card" style="display:none;margin-top:8px"><form class="form" method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="edit"><input type="hidden" name="id" value="{{x.id}}"><label>ชื่อผู้ใช้</label><input name="username" value="{{x.username}}" required><label>ชื่อ</label><input name="display_name" value="{{x.display_name}}"><label>รหัสใหม่ (เว้นว่างถ้าไม่เปลี่ยน)</label><input name="password" type="password"><label>ตำแหน่ง</label><select name="position"><option value="">-- ไม่ระบุ --</option>{% for p in position_options %}<option value="{{p}}" {% if x.position==p %}selected{% endif %}>{{p}}</option>{% endfor %}</select><button class="btn primary">บันทึกการเปลี่ยนข้อมูล</button></form></div></td></tr>{% endfor %}</table></div></section>"""
    return page("ระบบพระอุปัชฌาย์",body,preceptors=preceptors,apps=apps,position_options=POSITION_OPTIONS)
@app.route("/admin/prayers", methods=["GET","POST"])
@admin_required
def admin_prayers():
    conn=db()
    if request.method=="POST":
        require_csrf()
        if request.form.get("action")=="delete":
            conn.execute("DELETE FROM prayers WHERE id=?",(request.form["id"],)); conn.commit(); flash("ลบบทสวดแล้ว","success")
        elif request.form.get("action")=="edit":
            img=save_upload(request.files.get("image"),"prayer")
            if img:
                conn.execute("UPDATE prayers SET title=?,link=?,image_file=?,body=? WHERE id=?",(request.form["title"],request.form.get("link",""),img,request.form.get("body",""),request.form["id"]))
            else:
                conn.execute("UPDATE prayers SET title=?,link=?,body=? WHERE id=?",(request.form["title"],request.form.get("link",""),request.form.get("body",""),request.form["id"]))
            conn.commit(); flash("แก้ไขบทสวดแล้ว","success")
        else:
            img=save_upload(request.files.get("image"),"prayer")
            conn.execute("INSERT INTO prayers(title,link,image_file,body,created_at) VALUES(?,?,?,?,?)",
                         (request.form["title"],request.form.get("link",""),img,request.form.get("body",""),now()))
            conn.commit(); flash("เพิ่มบทสวดแล้ว","success")
        return redirect(url_for("admin_prayers"))
    rows=conn.execute("SELECT * FROM prayers ORDER BY id DESC").fetchall(); conn.close()
    body="""<section class="section"><h1>📖 จัดการบทสวดมนต์</h1><div class="card"><form class="form" method="post" enctype="multipart/form-data">
    <input type="hidden" name="_csrf" value="{{csrf_token()}}"><label>ชื่อบทสวด/หนังสือ</label><input name="title" required><label>ลิงก์</label><input name="link" type="url" placeholder="https://..."><label>รูปภาพ</label><input name="image" type="file" accept="image/*"><label>ข้อความบทสวด</label><textarea name="body"></textarea><button class="btn primary">เพิ่มบทสวด</button></form></div>
    <div class="list">{% for x in rows %}<div class="item"><h3>{{x.title}}</h3>{% if x.link %}<p>{{x.link}}</p>{% endif %}{% if x.image_file %}<img class="preview" src="{{url_for('uploaded_file',filename=x.image_file)}}">{% endif %}<button class="btn" type="button" onclick="document.getElementById('edit-prayer-{{x.id}}').style.display='block'">เปลี่ยนข้อมูล</button> <form method="post" style="display:inline" onsubmit="return confirm('ยืนยันลบบทสวดนี้?')"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="delete"><input type="hidden" name="id" value="{{x.id}}"><button class="btn bad">ลบ</button></form><div id="edit-prayer-{{x.id}}" class="card" style="display:none;margin-top:8px"><form class="form" method="post" enctype="multipart/form-data"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="edit"><input type="hidden" name="id" value="{{x.id}}"><label>ชื่อบทสวด/หนังสือ</label><input name="title" value="{{x.title}}" required><label>ลิงก์</label><input name="link" type="url" value="{{x.link}}"><label>รูปใหม่ (ถ้าต้องการเปลี่ยน)</label><input name="image" type="file" accept="image/*"><label>ข้อความบทสวด</label><textarea name="body">{{x.body}}</textarea><button class="btn primary">บันทึกการเปลี่ยนข้อมูล</button></form></div></div>{% endfor %}</div></section>"""
    return page("จัดการบทสวด",body,rows=rows)

@app.route("/admin/salary", methods=["GET","POST"])
@admin_required
def admin_salary():
    conn=db()
    if request.method=="POST":
        require_csrf(); action=request.form.get("action")
        if action=="toggle":
            openv=int(request.form["value"]); conn.execute("UPDATE salary_settings SET is_open=? WHERE id=1",(openv,)); conn.commit()
            flash("เปลี่ยนสถานะการรับคำขอเงินเดือนแล้ว","success")
        elif action in ("approve","reject"):
            rid=int(request.form["id"]); status="approved" if action=="approve" else "rejected"
            cur=conn.execute("UPDATE salary_requests SET status=? WHERE id=? AND status='pending'",(status,rid))
            if cur.rowcount:
                conn.commit(); flash("ดำเนินการคำขอเงินเดือนแล้ว","success")
            else:
                flash("คำขอนี้ถูกดำเนินการไปแล้ว","error")
        elif action=="delete":
            cur=conn.execute("DELETE FROM salary_requests WHERE id=? AND status='approved'",(request.form["id"],))
            if cur.rowcount:
                conn.commit(); flash("ลบรายการหลังยืนยันว่าจ่ายเงินแล้ว","success")
            else:
                flash("ลบได้เฉพาะรายการที่อนุมัติแล้ว","error")
        return redirect(url_for("admin_salary"))
    setting=conn.execute("SELECT is_open FROM salary_settings WHERE id=1").fetchone()
    rows=conn.execute("SELECT s.*,e.username,e.display_name FROM salary_requests s JOIN employees e ON e.id=s.employee_id ORDER BY s.id DESC").fetchall(); conn.close()
    body="""<section class="section"><h1>💰 ระบบเงินเดือน</h1><div class="card"><h2>รับคำขอเงินเดือน: <span class="badge {{'good' if setting.is_open else 'bad'}}">{{'เปิดรับ' if setting.is_open else 'ปิดรับ'}}</span></h2>
    <div class="actions"><form method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="toggle"><input type="hidden" name="value" value="1"><button class="btn good">เปิดรับเงินเดือน</button></form>
    <form method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="toggle"><input type="hidden" name="value" value="0"><button class="btn bad">ปิดรับเงินเดือน</button></form></div></div>
    <h2>คำขอเงินเดือน</h2><div class="list">{% for x in rows %}<article class="item"><h3>{{x.name}} • {{x.total_works}} ผลงาน</h3><p>วัด: {{x.temple}} • ช่องทาง: {{x.payment_channel}}</p><p>สถานะ: <span class="badge">{{x.status}}</span></p>
    {% if x.status=='pending' %}<form method="post" onsubmit="return confirm('ยืนยันการดำเนินการกับคำขอเงินเดือนนี้?')"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="id" value="{{x.id}}"><button class="btn good" name="action" value="approve">อนุมัติ</button><button class="btn bad" name="action" value="reject">ปฏิเสธ</button></form>{% elif x.status=='approved' %}<p><b>ช่องทางรับเงิน:</b> {{x.payment_channel}}</p><form method="post" onsubmit="return confirm('ยืนยันว่าจ่ายเงินแล้วและต้องการลบรายการนี้?')"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="id" value="{{x.id}}"><button class="btn warn" name="action" value="delete">ลบหลังจ่ายเงิน</button></form>{% endif %}</article>{% else %}<div class="empty">ไม่มีคำขอ</div>{% endfor %}</div></section>"""
    return page("ระบบเงินเดือน",body,setting=setting,rows=rows)

# ------------------------- Employee -------------------------

@app.route("/employee/login", methods=["GET","POST"])
def employee_login():
    if request.method=="POST":
        require_csrf(); conn=db()
        row=conn.execute("SELECT * FROM employees WHERE username=?",(request.form["username"],)).fetchone(); conn.close()
        if row and check_password_hash(row["password_hash"],request.form["password"]):
            banned=security_status("employee",row["id"])
            if banned: return white_ban_page(banned)
            session.clear(); session["role"]="employee"; session["user_id"]=row["id"]; session["csrf"]=secrets.token_urlsafe(24)
            return redirect(url_for("employee"))
        flash("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง","error")
    body="""<section class="login"><div class="card"><h1>👨‍💼 ระบบพนักงาน</h1><form class="form" method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}">
    <label>ชื่อ</label><input name="username" required><label>รหัส</label><input name="password" type="password" required><button class="btn primary">เข้าสู่ระบบ</button></form></div></section>"""
    return page("เข้าสู่ระบบพนักงาน",body)

@app.route("/employee", methods=["GET","POST"])
@employee_required
def employee():
    emp=current_employee()
    conn=db()
    if request.method=="POST":
        require_csrf(); action=request.form["action"]
        if action=="work":
            name=request.form.get("name","").strip()
            try: count=int(request.form.get("work_count","0"))
            except (TypeError,ValueError): count=0
            if not name or count < 1 or count > 100000:
                flash("กรอกชื่อผลงานและจำนวนผลงานให้ถูกต้อง (1-100000)","error")
            else:
                img=save_upload(request.files.get("image"),"work")
                conn.execute("INSERT INTO works(employee_id,name,work_count,image_file,created_at) VALUES(?,?,?,?,?)",
                             (emp["id"],name,count,img,now())); conn.commit(); flash("ส่งผลงานรออนุมัติแล้ว","success")
        elif action=="delete_work":
            wid=int(request.form.get("id",0)); cur=conn.execute("DELETE FROM works WHERE id=? AND employee_id=?",(wid,emp["id"]))
            if cur.rowcount:
                conn.commit()
                if delete_action_security("employee",emp["id"]): return white_ban_page(datetime.now()+timedelta(hours=1))
                flash("ลบประวัติผลงานแล้ว","success")
        elif action=="study":
            name=request.form.get("name","").strip(); typ=request.form.get("type","").strip(); vassa=request.form.get("vassa","").strip(); level=request.form.get("level","").strip()
            if not name or typ not in ("นักธรรม","เปรียญธรรม") or not vassa or not level:
                flash("กรอกข้อมูลสมัครเรียนให้ครบและถูกต้อง","error")
            else:
                dup=conn.execute("SELECT id FROM study_applications WHERE employee_id=? AND name=? AND type=? AND level=? AND status='pending'",(emp["id"],name,typ,level)).fetchone()
                if dup: flash("มีใบสมัครรายการเดียวกันที่กำลังรออนุมัติอยู่แล้ว","error")
                else:
                    conn.execute("INSERT INTO study_applications(employee_id,name,type,vassa,level,created_at) VALUES(?,?,?,?,?,?)",
                                 (emp["id"],name,typ,vassa,level,now())); conn.commit(); flash("ส่งสมัครเรียนแล้ว","success")
        elif action=="study_approve" or action=="study_reject":
            sid=int(request.form["study_id"])
            row=conn.execute("SELECT * FROM study_applications WHERE id=? AND status='pending' AND (employee_id IS NULL OR employee_id != ?)",(sid,emp['id'])).fetchone()
            if not row:
                flash("ใบสมัครนี้ถูกดำเนินการไปแล้วหรือไม่พบข้อมูล", "error")
            elif action=="study_reject":
                cur=conn.execute("DELETE FROM study_applications WHERE id=? AND status='pending'",(sid,))
                if cur.rowcount:
                    conn.commit(); flash("ปฏิเสธใบสมัครเรียนแล้ว","success")
            else:
                temple=request.form.get("temple","").strip()
                if not temple:
                    flash("ต้องระบุวัดก่อนอนุมัติใบสมัคร", "error")
                else:
                    cur=conn.execute("UPDATE study_applications SET status='approved',employee_id=COALESCE(employee_id,?),temple=? WHERE id=? AND status='pending'",(emp["id"],temple,sid))
                    if cur.rowcount:
                        conn.commit(); flash("อนุมัติใบสมัครเรียนแล้ว รอ Admin บันทึกผลสอบ","success")
                    else:
                        flash("ใบสมัครนี้ถูกดำเนินการไปแล้ว", "error")
        elif action=="preceptor_apply":
            name=request.form.get("name","").strip(); vassa=request.form.get("vassa","").strip(); temple=request.form.get("temple","").strip()
            if not name or not vassa or not temple:
                flash("กรอกข้อมูลสมัครอุปัชฌาย์ให้ครบ","error")
            else:
                dup=conn.execute("SELECT id FROM preceptor_applications WHERE employee_id=? AND status='pending'",(emp["id"],)).fetchone()
                if dup: flash("มีคำขอสมัครอุปัชฌาย์ที่กำลังรออนุมัติอยู่แล้ว","error")
                else:
                    conn.execute("INSERT INTO preceptor_applications(employee_id,name,vassa,temple,created_at) VALUES(?,?,?,?,?)",
                                 (emp["id"],name,vassa,temple,now())); conn.commit(); flash("ส่งสมัครอุปัชฌาย์แล้ว","success")
        elif action=="promotion":
            fields=[request.form.get(k,"").strip() for k in ("royal_name","vassa","temple","position","current_rank","requested_rank","temple_role")]
            royal_name,vassa,temple,position,current_rank,requested_rank,temple_role=fields
            if not all(fields): flash("กรอกข้อมูลขอเลื่อนสมณศักดิ์ให้ครบ","error")
            else:
                dup=conn.execute("SELECT id FROM promotion_requests WHERE employee_id=? AND status='pending'",(emp["id"],)).fetchone()
                if dup: flash("มีคำขอเลื่อนสมณศักดิ์ที่กำลังรออนุมัติอยู่แล้ว","error")
                else:
                    conn.execute("INSERT INTO promotion_requests(employee_id,applicant_name,royal_name,vassa,temple,position,current_rank,requested_rank,temple_role,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(emp["id"],emp["display_name"] or emp["username"],royal_name,vassa,temple,position,current_rank,requested_rank,temple_role,now()))
                    conn.commit(); flash("ส่งคำขอเลื่อนสมณศักดิ์แล้ว","success")
        elif action=="salary":
            setting=conn.execute("SELECT is_open FROM salary_settings WHERE id=1").fetchone()
            if not setting["is_open"]:
                flash("ขณะนี้ปิดรับคำขอเงินเดือน","error")
            else:
                name=request.form.get("name","").strip(); temple=request.form.get("temple","").strip(); channel=request.form.get("payment_channel","").strip()
                try: total_works=int(request.form.get("total_works","0"))
                except (TypeError,ValueError): total_works=-1
                if not name or not temple or not channel or total_works < 0:
                    flash("กรอกข้อมูลเงินเดือนให้ครบและถูกต้อง","error")
                else:
                    dup=conn.execute("SELECT id FROM salary_requests WHERE employee_id=? AND status='pending'",(emp["id"],)).fetchone()
                    if dup: flash("มีคำขอเงินเดือนที่กำลังรออนุมัติอยู่แล้ว","error")
                    else:
                        conn.execute("INSERT INTO salary_requests(employee_id,name,temple,total_works,payment_channel,created_at) VALUES(?,?,?,?,?,?)",
                                     (emp["id"],name,temple,total_works,channel,now()))
                        conn.commit(); flash("ส่งคำขอเงินเดือนแล้ว","success")
        return redirect(url_for("employee"))
    works=conn.execute("SELECT * FROM works WHERE employee_id=? ORDER BY id DESC",(emp["id"],)).fetchall()
    study=conn.execute("SELECT * FROM study_applications WHERE employee_id=? OR employee_id IS NULL ORDER BY id DESC",(emp["id"],)).fetchall()
    pending_public_study=conn.execute("SELECT * FROM study_applications WHERE status='pending' AND (employee_id IS NULL OR employee_id != ?) ORDER BY id DESC",(emp['id'],)).fetchall()
    preapps=conn.execute("SELECT * FROM preceptor_applications WHERE employee_id=? ORDER BY id DESC",(emp["id"],)).fetchall()
    setting=conn.execute("SELECT is_open FROM salary_settings WHERE id=1").fetchone()
    salary=conn.execute("SELECT * FROM salary_requests WHERE employee_id=? ORDER BY id DESC",(emp["id"],)).fetchall()
    promotions=conn.execute("SELECT * FROM promotion_history WHERE employee_id=? ORDER BY id DESC",(emp["id"],)).fetchall()
    promotion_status=conn.execute("SELECT * FROM promotion_requests WHERE employee_id=? ORDER BY id DESC",(emp["id"],)).fetchall(); conn.close()
    body="""<section class="section"><div class="sectionhead"><div><h1>👨‍💼 {{emp.display_name or emp.username}}</h1><p class="muted">ผลงานสะสม <b>{{emp.total_works}}</b> รายการ</p></div></div>
    <div class="grid">
    <div class="card"><h2>🏆 ลงผลงาน</h2><form class="form" method="post" enctype="multipart/form-data"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="work">
    <label>ชื่อผลงาน/ชื่อ</label><input name="name" required><label>จำนวนผลงาน</label><input name="work_count" type="number" min="1" required><label>รูปภาพผลงาน</label><input name="image" type="file" accept="image/*"><button class="btn primary">ส่งผลงาน</button></form></div>
    <div class="card"><h2>📚 สมัครนักธรรม/เปรียญธรรม</h2><form class="form" method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="study">
    <label>ชื่อ</label><input name="name" required><label>ประเภท</label><select name="type"><option>นักธรรม</option><option>เปรียญธรรม</option></select><label>พรรษา</label><input name="vassa" required><label>ชั้น</label><input name="level" required><button class="btn primary">ส่งสมัคร</button></form></div>
    <div class="card"><h2>📚 อนุมัติใบสมัครเรียน</h2><p class="muted">ใบสมัครที่ส่งจากหน้าแรกจะมารอที่นี่</p>
    {% for x in pending_public_study %}<form class="form" method="post" style="border-top:1px solid var(--line);padding-top:10px;margin-top:10px"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="study_id" value="{{x.id}}"><select name="temple" required><option value="">-- เลือกวัด --</option>{% for t in temples %}<option value="{{t}}">{{t}}</option>{% endfor %}</select><b>{{x.name}} • {{x.type}} {{x.level}} • พรรษา {{x.vassa}}</b><div class="actions"><button class="btn good" name="action" value="study_approve" onclick="return confirm('ยืนยันอนุมัติใบสมัครเรียนนี้?')">อนุมัติ</button><button class="btn bad" name="action" value="study_reject" onclick="return confirm('ยืนยันปฏิเสธใบสมัครเรียนนี้?')">ปฏิเสธ</button></div></form>{% else %}<p>ไม่มีใบสมัครรออนุมัติ</p>{% endfor %}</div>
    <div class="card"><h2>🧘 สมัครอุปัชฌาย์</h2><form class="form" method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="preceptor_apply">
    <label>ชื่อ</label><input name="name" required><label>พรรษา</label><input name="vassa" required><label>สังกัดวัด</label><select name="temple" required>{% for t in temples %}<option value="{{t}}">{{t}}</option>{% endfor %}</select><button class="btn primary">ส่งสมัคร</button></form></div>
    <div class="card"><h2>🎖️ ยื่นเลื่อนสมณศักดิ์</h2><form class="form" method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="promotion">
    <label>ชื่อราชทินนาม</label><input name="royal_name" required><label>พรรษา</label><input name="vassa" required><label>สังกัดวัด</label><select name="temple" required>{% for t in temples %}<option value="{{t}}">{{t}}</option>{% endfor %}</select><label>ตำแหน่ง</label><select name="position">{% for p in position_options %}<option>{{p}}</option>{% endfor %}</select><label>ชั้นยศปัจจุบัน</label><input name="current_rank" required><label>ชั้นยศที่จะขอเลื่อน</label><input name="requested_rank" required><label>ตำแหน่งอะไรในวัดของตัวเอง</label><input name="temple_role" required><button class="btn primary">ยื่นคำขอ</button></form></div>
    <div class="card"><h2>🙏 กิจนิมนต์</h2><a class="btn primary" href="{{url_for('temple_invitations')}}">ดูคำขอกิจนิมนต์</a><a class="btn" href="{{url_for('temple_death')}}">🕯️ บันทึกมรณภาพ</a></div>
    <div class="card"><h2>💰 เบิกเงินเดือน</h2>{% if setting.is_open %}<form class="form" method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="salary">
    <label>ชื่อ</label><input name="name" required><label>สังกัดวัด</label><select name="temple" required>{% for t in temples %}<option value="{{t}}">{{t}}</option>{% endfor %}</select><label>ผลงานทั้งหมด</label><input name="total_works" type="number" min="0" value="{{emp.total_works}}" required><label>ช่องทางรับเงิน</label><input name="payment_channel" placeholder="เช่น พร้อมเพย์/บัญชี..." required><button class="btn primary">ส่งคำขอเงินเดือน</button></form>{% else %}<p>ผู้ดูแลยังไม่เปิดรับคำขอเงินเดือน</p>{% endif %}</div></div>
    <h2>ประวัติผลงาน</h2><div class="list">{% for x in works %}<div class="item">{{x.name}} • {{x.work_count}} • <span class="badge">{{x.status}}</span>{% if x.image_file %}<img class="preview" src="{{url_for('uploaded_file',filename=x.image_file)}}">{% endif %}<form method="post" style="margin-top:8px" onsubmit="return confirm('ลบประวัติผลงานนี้หรือไม่? การลบครั้งที่ 2 จะถูกระงับบัญชี 1 ชั่วโมง')"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="delete_work"><input type="hidden" name="id" value="{{x.id}}"><button class="btn bad">ลบ</button></form></div>{% endfor %}</div>
    <h2>ประวัติขอเลื่อนสมณศักดิ์</h2><div class="list">{% for x in promotion_status %}<div class="item">{{x.royal_name}} • {{x.current_rank}} → {{x.requested_rank}} • <span class="badge">{{x.status}}</span></div>{% else %}<div class="empty">ยังไม่มี</div>{% endfor %}</div>
    <h2>ประวัติที่อนุมัติแล้ว</h2><div class="list">{% for x in promotions %}<div class="item">{{x.royal_name}} • {{x.requested_rank}} • <span class="badge">อนุมัติแล้ว</span></div>{% else %}<div class="empty">ยังไม่มี</div>{% endfor %}</div>
    <h2>สถานะสมัครเรียน</h2><div class="list">{% for x in study %}<div class="item">{{x.type}} {{x.level}} • <span class="badge">{{x.status}}</span></div>{% else %}<div class="empty">ยังไม่มี</div>{% endfor %}</div>
    <h2>สถานะสมัครอุปัชฌาย์</h2><div class="list">{% for x in preapps %}<div class="item">{{x.name}} • <span class="badge">{{x.status}}</span></div>{% else %}<div class="empty">ยังไม่มี</div>{% endfor %}</div>
    <h2>สถานะเงินเดือน</h2><div class="list">{% for x in salary %}<div class="item">{{x.total_works}} ผลงาน • <span class="badge">{{x.status}}</span>{% if x.status=='approved' %}<p><b>ช่องทางรับเงิน:</b> {{x.payment_channel}}</p>{% endif %}</div>{% else %}<div class="empty">ยังไม่มี</div>{% endfor %}</div>
    </section>"""
    return page("ระบบพนักงาน",body,emp=emp,works=works,study=study,pending_public_study=pending_public_study,preapps=preapps,setting=setting,salary=salary,promotions=promotions,promotion_status=promotion_status,position_options=POSITION_OPTIONS)

# ------------------------- Preceptor -------------------------

@app.route("/preceptor/login", methods=["GET","POST"])
def preceptor_login():
    if request.method=="POST":
        require_csrf(); conn=db()
        row=conn.execute("SELECT * FROM preceptors WHERE username=?",(request.form["username"],)).fetchone(); conn.close()
        if row and check_password_hash(row["password_hash"],request.form["password"]):
            banned=security_status("preceptor",row["id"])
            if banned: return white_ban_page(banned)
            session.clear(); session["role"]="preceptor"; session["user_id"]=row["id"]; session["csrf"]=secrets.token_urlsafe(24)
            return redirect(url_for("preceptor"))
        flash("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง","error")
    body="""<section class="login"><div class="card"><h1>🧘 ระบบพระอุปัชฌาย์</h1><form class="form" method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}">
    <label>ชื่อผู้ใช้</label><input name="username" required><label>รหัสผู้ใช้</label><input name="password" type="password" required><button class="btn primary">เข้าสู่ระบบ</button></form></div></section>"""
    return page("เข้าสู่ระบบพระอุปัชฌาย์",body)

@app.route("/preceptor", methods=["GET","POST"])
@preceptor_required
def preceptor():
    conn=db()
    if request.method=="POST":
        require_csrf(); oid=int(request.form["id"]); action=request.form["action"]
        row=conn.execute("SELECT * FROM ordination_requests WHERE id=? AND assigned_preceptor_id=?",
                         (oid,session["user_id"])).fetchone()
        if not row: flash("ไม่พบคำขอหรือคำขอนี้ไม่ได้มอบหมายให้คุณ","error")
        elif action=="approve":
            cur=conn.execute("UPDATE ordination_requests SET status='ผ่านการอนุมัติ รอเข้ารอบบวช' WHERE id=? AND assigned_preceptor_id=? AND status='รออนุมัติจากพระอุปัชฌาย์'",(oid,session["user_id"]))
            if cur.rowcount: conn.commit(); flash("อนุมัติคำขอแล้ว และย้ายเข้ารอบบวชแล้ว","success")
            else: flash("คำขอนี้ถูกดำเนินการไปแล้ว", "error")
        elif action=="reject":
            cur=conn.execute("UPDATE ordination_requests SET status='ปฏิเสธโดยพระอุปัชฌาย์' WHERE id=? AND assigned_preceptor_id=? AND status='รออนุมัติจากพระอุปัชฌาย์'",(oid,session["user_id"]))
            if cur.rowcount: conn.commit(); flash("ปฏิเสธคำขอแล้ว","success")
            else: flash("คำขอนี้ถูกดำเนินการไปแล้ว", "error")
        elif action in ("approve_preceptor", "reject_preceptor"):
            # Kept only for backward compatibility with old forms. Approval authority is Admin.
            flash("การสมัครอุปัชฌาย์ต้องให้ผู้ดูแลระบบอนุมัติ", "error")
        elif action=="delete_promotion":
            pid=int(request.form.get("id",0)); cur=conn.execute("DELETE FROM promotion_requests WHERE id=? AND preceptor_id=?",(pid,session["user_id"]))
            if cur.rowcount:
                conn.commit()
                if delete_action_security("preceptor",session["user_id"]): return white_ban_page(datetime.now()+timedelta(hours=1))
                flash("ลบประวัติคำขอเลื่อนสมณศักดิ์แล้ว","success")
        elif action=="promotion" or action=="defrock_approve" or action=="defrock_reject":
            if action=="promotion":
                fields=[request.form.get(k,"").strip() for k in ("royal_name","vassa","temple","position","current_rank","requested_rank","temple_role")]
                if not all(fields): flash("กรอกข้อมูลขอเลื่อนสมณศักดิ์ให้ครบ","error")
                else:
                    royal_name,vassa,temple,position,current_rank,requested_rank,temple_role=fields
                    conn.execute("INSERT INTO promotion_requests(preceptor_id,applicant_name,royal_name,vassa,temple,position,current_rank,requested_rank,temple_role,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(session["user_id"],royal_name,royal_name,vassa,temple,position,current_rank,requested_rank,temple_role,now()))
                    conn.commit(); flash("ส่งคำขอเลื่อนสมณศักดิ์แล้ว","success")
            else:
                did=int(request.form.get("defrock_id",0))
                status="approved" if action=="defrock_approve" else "rejected"
                cur=conn.execute("UPDATE defrock_requests SET status=?,preceptor_id=?,decided_at=? WHERE id=? AND status='pending'",(status,session["user_id"],now(),did))
                if cur.rowcount: conn.commit(); flash("ดำเนินการคำขอสึกแล้ว","success")
                else: flash("คำขอนี้ถูกดำเนินการแล้ว","error")
        elif action=="complete":
            monastic=request.form["monastic_name"]; date=request.form["ordination_date"]; temple=request.form["affiliated_temple"]
            if not monastic or not date or not temple: flash("กรอกข้อมูลหลังบวชให้ครบ","error")
            else:
                cur=conn.execute("""UPDATE ordination_requests SET status='บวชแล้ว',monastic_name=?,ordination_date=?,affiliated_temple=? WHERE id=? AND assigned_preceptor_id=? AND status='ผ่านการอนุมัติ รอเข้ารอบบวช'""",
                             (monastic,date,temple,oid,session["user_id"]))
                if cur.rowcount:
                    conn.execute("""INSERT INTO temples(name,ordination_date,temple,status,source,source_ref,person_type,created_at)
                                    SELECT ?,?,?,?,?,?,?,? WHERE NOT EXISTS (
                                      SELECT 1 FROM temples WHERE source='ordination' AND source_ref=?
                                    )""",(monastic,date,temple,"บวชแล้ว","ordination",str(oid),"พระ",now(),str(oid)))
                    conn.commit(); flash("บันทึกการบวชและเพิ่มเข้าทะเบียนวัดแล้ว","success")
                else:
                    flash("คำขอนี้บันทึกการบวชไปแล้วหรือไม่อยู่ในรอบบวช", "error")
        return redirect(url_for("preceptor"))
    assigned=conn.execute("""SELECT * FROM ordination_requests WHERE assigned_preceptor_id=? AND status='รออนุมัติจากพระอุปัชฌาย์' ORDER BY id DESC""",(session["user_id"],)).fetchall()
    queue=conn.execute("""SELECT * FROM ordination_requests WHERE assigned_preceptor_id=? AND status='ผ่านการอนุมัติ รอเข้ารอบบวช' ORDER BY id DESC""",(session["user_id"],)).fetchall()
    preceptor_apps=conn.execute("SELECT * FROM preceptor_applications WHERE status='approved' ORDER BY id DESC LIMIT 50").fetchall()
    defrocks=conn.execute("SELECT * FROM defrock_requests WHERE status='pending' ORDER BY id DESC").fetchall()
    promotions=conn.execute("SELECT * FROM promotion_requests WHERE preceptor_id=? ORDER BY id DESC",(session["user_id"],)).fetchall()
    conn.close()
    body="""<section class="section"><h1>🧘 ระบบพระอุปัชฌาย์</h1><h2>คำขอบวชที่รออนุมัติ</h2><div class="list">
    {% for x in assigned %}<article class="item"><h3>{{x.real_name}} • {{x.kind}}</h3><p>อายุ {{x.age}} • {{x.temple}} • ท่องบทสวด {{x.chant}}</p><p>วัดเกิด {{x.birth_temple}} • {{x.reason}}</p>
    <form method="post" onsubmit="return confirm('ยืนยันการดำเนินการกับคำขอบวชนี้?')"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="id" value="{{x.id}}"><button class="btn good" name="action" value="approve">อนุมัติ</button><button class="btn bad" name="action" value="reject">ปฏิเสธ</button></form></article>{% else %}<div class="empty">ไม่มีคำขอรออนุมัติ</div>{% endfor %}</div>
    <h2>🧘 ผู้สมัครอุปัชฌาย์ที่ Admin อนุมัติแล้ว</h2><div class="list">{% for x in preceptor_apps %}<article class="item"><h3>{{x.name}}</h3><p>พรรษา {{x.vassa}} • {{x.temple}} • <span class="badge good">ผ่านการอนุมัติจาก Admin</span></p></article>{% else %}<div class="empty">ยังไม่มีผู้สมัครที่ Admin อนุมัติ</div>{% endfor %}</div>
    <h2>🎖️ ยื่นเลื่อนสมณศักดิ์</h2><div class="card"><form class="form" method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="promotion"><label>ชื่อราชทินนาม</label><input name="royal_name" required><label>พรรษา</label><input name="vassa" required><label>สังกัดวัด</label><select name="temple" required>{% for t in temples %}<option value="{{t}}">{{t}}</option>{% endfor %}</select><label>ตำแหน่ง</label><select name="position">{% for p in position_options %}<option>{{p}}</option>{% endfor %}</select><label>ชั้นยศปัจจุบัน</label><input name="current_rank" required><label>ชั้นยศที่จะขอเลื่อน</label><input name="requested_rank" required><label>ตำแหน่งอะไรในวัดของตัวเอง</label><input name="temple_role" required><button class="btn primary">ยื่นคำขอ</button></form></div>
    <h2>🪷 คำขอสึก</h2><div class="list">{% for x in defrocks %}<article class="item"><h3>{{x.name}}</h3><p>วัด {{x.temple}} • Discord: {{x.discord_username}}</p><p>{{x.reason}}</p><form method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="defrock_id" value="{{x.id}}"><button class="btn good" name="action" value="defrock_approve" onclick="return confirm('ยืนยันอนุมัติการสึก?')">อนุมัติการสึก</button> <button class="btn bad" name="action" value="defrock_reject">ไม่อนุมัติ</button></form></article>{% else %}<div class="empty">ไม่มีคำขอสึก</div>{% endfor %}</div>
    <h2>ประวัติขอเลื่อนสมณศักดิ์</h2><div class="list">{% for x in promotions %}<div class="item">{{x.royal_name}} • {{x.current_rank}} → {{x.requested_rank}} • <span class="badge">{{x.status}}</span><form method="post" style="margin-top:8px" onsubmit="return confirm('ลบประวัตินี้หรือไม่? การลบครั้งที่ 2 จะถูกระงับบัญชี 1 ชั่วโมง')"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="delete_promotion"><input type="hidden" name="id" value="{{x.id}}"><button class="btn bad">ลบ</button></form></div>{% else %}<div class="empty">ยังไม่มี</div>{% endfor %}</div>
    <h2>รอบบวช</h2><div class="list">{% for x in queue %}<article class="item"><h3>{{x.real_name}}</h3><p>{{x.kind}} • {{x.temple}}</p>
    <form class="form" method="post" onsubmit="return confirm('ยืนยันว่าบวชเสร็จแล้วและบันทึกเข้าทะเบียนวัด?')"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="id" value="{{x.id}}"><input type="hidden" name="action" value="complete">
    <label>ชื่อฉายา</label><input name="monastic_name" required><label>วันที่บวช</label><input name="ordination_date" type="date" required><label>สังกัดวัด</label><select name="affiliated_temple" required>{% for t in temples %}<option value="{{t}}">{{t}}</option>{% endfor %}</select><button class="btn primary">บันทึกว่าบวชเสร็จแล้ว</button></form></article>{% else %}<div class="empty">ยังไม่มีรอบบวช</div>{% endfor %}</div></section>"""
    return page("ระบบพระอุปัชฌาย์",body,assigned=assigned,queue=queue,preceptor_apps=preceptor_apps,defrocks=defrocks,promotions=promotions,position_options=POSITION_OPTIONS)


# ------------------------- Sangha / Temple management -------------------------
TEMPLE_OPTIONS = ["วัดเนินกรอย", "วัดไตรมิตรวิทยาราม", "วัดป่าสังฆาภร", "วัดราชบพิธสถิตมหาสีมาราม"]
TEMPLE_POSITIONS = ["เจ้าอาวาส", "รองเจ้าอาวาส", "ผู้ช่วยเจ้าอาวาส"]
RANK_OPTIONS = ["ยังไม่มีสมณศักดิ์", "พระครู", "พระราชาคณะชั้นสามัญ", "พระราชาคณะชั้นราช", "พระราชาคณะชั้นเทพ", "พระราชาคณะชั้นธรรม", "พระราชาคณะชั้นหิรัญบัฏ", "พระราชาคณะชั้นสมเด็จ", "อื่น ๆ"]

def temple_admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if session.get("role") != "temple_admin":
            return redirect(url_for("temple_admin_login"))
        return fn(*args, **kwargs)
    return wrapper

@app.route("/monks", methods=["GET", "POST"])
def monks_home():
    conn=db()
    if request.method=="POST":
        require_csrf(); action=request.form.get("action")
        if action=="defrock":
            name=request.form.get("name","").strip(); reason=request.form.get("reason","").strip(); discord=request.form.get("discord_username","").strip(); temple=request.form.get("temple","").strip()
            if not name or not reason or not discord or temple not in TEMPLE_OPTIONS:
                flash("กรอกข้อมูลแจ้งสึกให้ครบและเลือกวัดให้ถูกต้อง","error")
            else:
                conn.execute("INSERT INTO defrock_requests(name,reason,discord_username,temple,created_at) VALUES(?,?,?,?,?)",(name,reason,discord,temple,now())); conn.commit(); flash("ส่งคำขอแจ้งสึกไปยังระบบพระอุปัชฌาย์แล้ว","success")
        elif action=="transfer":
            name=request.form.get("name","").strip(); reason=request.form.get("reason","").strip(); target=request.form.get("target_temple","").strip(); source=request.form.get("source_temple","").strip()
            if not name or not reason or source not in TEMPLE_OPTIONS or target not in TEMPLE_OPTIONS or source==target:
                flash("กรอกข้อมูลย้ายสังกัดให้ครบ และเลือกวัดปลายทางให้ถูกต้อง","error")
            else:
                conn.execute("INSERT INTO transfer_requests(source_temple,target_temple,name,reason,created_at) VALUES(?,?,?,?,?)",(source,target,name,reason,now())); conn.commit(); flash("ส่งคำขอย้ายสังกัดไปยังผู้ดูแลวัดปลายทางแล้ว","success")
        elif action=="contact":
            royal=request.form.get("royal_name","").strip(); subject=request.form.get("subject","").strip()
            if not royal or not subject: flash("กรอกชื่อราชทินนามและเรื่องที่จะติดต่อให้ครบ","error")
            else:
                conn.execute("INSERT INTO contact_requests(royal_name,subject,created_at) VALUES(?,?,?)",(royal,subject,now())); conn.commit(); flash("ส่งคำขอติดต่อ Admin แล้ว","success")
        conn.close(); return redirect(url_for("monks_home"))
    acts={r["kind"]:r for r in conn.execute("SELECT * FROM activities").fetchall()}; conn.close()
    body="""<section class="hero"><h1>🧘‍♂️ ระบบพระภิกษุสงฆ์</h1><p>ระบบกลางสำหรับการแจ้งสึก ย้ายสังกัด และกิจกรรมของพระภิกษุสงฆ์</p></section>
    <div class="grid">{% for t in temples %}<article class="card"><h2>🏯 {{t}}</h2><p>ระบบของวัดนี้ใช้ขั้นตอนเดียวกันกับทุกวัด</p></article>{% endfor %}</div>
    <section class="section"><div class="grid">
    <div class="card"><h2>📿 แจ้งสึก</h2><form class="form" method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="defrock"><label>ชื่อหรือราชทินนาม</label><input name="name" required><label>เหตุผลที่สึก</label><textarea name="reason" required></textarea><label>ชื่อผู้ใช้ Discord</label><input name="discord_username" required><label>สังกัดวัด</label><select name="temple">{% for t in temples %}<option>{{t}}</option>{% endfor %}</select><button class="btn primary">ตกลง</button></form></div>
    <div class="card"><h2>🔄 แจ้งย้ายสังกัด</h2><form class="form" method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="transfer"><label>ชื่อหรือราชทินนาม</label><input name="name" required><label>สังกัดปัจจุบัน</label><select name="source_temple">{% for t in temples %}<option>{{t}}</option>{% endfor %}</select><label>เหตุผลที่จะย้ายสังกัด</label><textarea name="reason" required></textarea><label>สังกัดวัดที่จะไป</label><select name="target_temple">{% for t in temples %}<option>{{t}}</option>{% endfor %}</select><button class="btn primary">ตกลง</button></form></div>
    {% if activity_promo.is_open %}<div class="card"><h2>🎬 กิจกรรมโปรโมทกลุ่ม</h2><form class="form" method="post" action="{{url_for('activity_submit')}}"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="kind" value="promo"><label>ชื่อหรือราชทินนาม</label><input name="royal_name" required><label>Link คลิป TikTok</label><input name="tiktok_link" type="url" required><label>สังกัดวัด</label><select name="temple">{% for t in temples %}<option>{{t}}</option>{% endfor %}</select><button class="btn primary">ส่งกิจกรรม</button></form></div>{% endif %}
    {% if activity_quiz.is_open %}<div class="card"><h2>❓ กิจกรรมตอบคำถาม</h2><p>จำนวนข้อ: {{activity_quiz.question_count}}</p><p><b>{{activity_quiz.main_question}}</b></p><form class="form" method="post" action="{{url_for('activity_submit')}}"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="kind" value="quiz"><label>ชื่อหรือราชทินนาม</label><input name="royal_name" required><label>คำตอบ</label><textarea name="answer" required></textarea><button class="btn primary">ส่งคำตอบ</button></form></div>{% endif %}
    </div></section>
    <div class="card" style="position:fixed;right:18px;bottom:18px;width:58px;height:58px;border-radius:50%;padding:0;display:grid;place-items:center;z-index:10"><button class="btn primary" style="border-radius:50%;width:58px;height:58px" onclick="document.getElementById('contactBox').style.display='block'">📩</button></div>
    <div id="contactBox" class="card" style="display:none;position:fixed;right:18px;bottom:88px;width:min(92vw,380px);z-index:11"><h2>ติดต่อ Admin</h2><form class="form" method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="contact"><label>ชื่อราชทินนาม</label><input name="royal_name" required><label>เรื่องที่จะติดต่อ</label><textarea name="subject" required></textarea><button class="btn primary">ส่ง</button> <button type="button" class="btn" onclick="this.parentElement.parentElement.style.display='none'">ปิด</button></form></div>
    <div class="card"><h3>🏯 สำหรับเจ้าอาวาส/รอง/ผู้ช่วย</h3><a class="btn" href="{{url_for('temple_admin_login')}}">เข้าสู่ระบบจัดการวัด</a></div>"""
    return page("ระบบพระภิกษุสงฆ์",body,temples=TEMPLE_OPTIONS,activity_promo=acts.get("promo",{"is_open":0,"question_count":0,"main_question":""}),activity_quiz=acts.get("quiz",{"is_open":0,"question_count":0,"main_question":""}))

@app.route("/activity/submit", methods=["POST"])
def activity_submit():
    require_csrf(); kind=request.form.get("kind"); conn=db(); act=conn.execute("SELECT * FROM activities WHERE kind=?",(kind,)).fetchone()
    if not act or not act["is_open"]: conn.close(); flash("กิจกรรมนี้ยังไม่เปิด","error"); return redirect(url_for("monks_home"))
    royal=request.form.get("royal_name","").strip()
    if not royal: conn.close(); flash("กรอกชื่อหรือราชทินนามก่อน","error"); return redirect(url_for("monks_home"))
    if kind=="promo":
        link=request.form.get("tiktok_link","").strip(); temple=request.form.get("temple","").strip()
        if not link or temple not in TEMPLE_OPTIONS: flash("กรอก Link TikTok และวัดให้ถูกต้อง","error")
        else: conn.execute("INSERT INTO activity_submissions(activity_id,royal_name,tiktok_link,temple,created_at) VALUES(?,?,?,?,?)",(act["id"],royal,link,temple,now())); conn.commit(); flash("ส่งคลิปกิจกรรมให้ Admin แล้ว","success")
    else:
        ans=request.form.get("answer","").strip()
        if not ans: flash("กรอกคำตอบก่อน","error")
        else: conn.execute("INSERT INTO activity_submissions(activity_id,royal_name,answer,created_at) VALUES(?,?,?,?)",(act["id"],royal,ans,now())); conn.commit(); flash("ส่งคำตอบกิจกรรมแล้ว","success")
    conn.close(); return redirect(url_for("monks_home"))

@app.route("/death-report", methods=["GET", "POST"])
def death_report():
    """หน้าสาธารณะสำหรับแจ้งมรณภาพ และใช้ตาราง death_requests เดิมร่วมกับ Admin."""
    conn = db()
    if request.method == "POST":
        require_csrf()
        try:
            temple_id = int(request.form.get("temple_id", "0"))
        except (TypeError, ValueError):
            temple_id = 0
        row = conn.execute(
            "SELECT * FROM temples WHERE id=? AND status!='มรณภาพ'",
            (temple_id,)
        ).fetchone()
        if not row:
            flash("ไม่พบพระในทะเบียน หรือพระรูปนี้ถูกบันทึกมรณภาพแล้ว", "error")
        else:
            pending = conn.execute(
                "SELECT id FROM death_requests WHERE temple_id=? AND status='pending'",
                (temple_id,)
            ).fetchone()
            if pending:
                flash("พระรูปนี้มีคำขอแจ้งมรณภาพที่กำลังรอ Admin ตรวจสอบอยู่แล้ว", "error")
            else:
                conn.execute(
                    "INSERT INTO death_requests(temple_id,temple,name,created_at) VALUES(?,?,?,?)",
                    (row["id"], row["temple"], row["name"], now())
                )
                conn.commit()
                flash("ส่งคำขอแจ้งมรณภาพไปยัง Admin แล้ว รอการอนุมัติ", "success")
        conn.close()
        return redirect(url_for("death_report"))

    rows = conn.execute(
        "SELECT id,name,temple,status FROM temples WHERE status!='มรณภาพ' ORDER BY temple,name"
    ).fetchall()
    pending = conn.execute(
        "SELECT temple_id FROM death_requests WHERE status='pending'"
    ).fetchall()
    pending_ids = {int(x["temple_id"]) for x in pending}
    conn.close()
    body = """<section class="section"><div class="sectionhead"><div><h1>🕯️ แจ้งมรณภาพ</h1><p class="muted">เลือกพระจากทะเบียนวัด แล้วส่งคำขอให้ Admin อนุมัติก่อน</p></div><a class="btn" href="{{url_for('home')}}">← หน้าแรก</a></div>
    <div class="card"><form class="form" method="post">
    <input type="hidden" name="_csrf" value="{{csrf_token()}}">
    <label>เลือกพระภิกษุ</label>
    <select name="temple_id" required>
      <option value="">-- เลือกพระจากทะเบียนวัด --</option>
      {% for x in rows %}{% if x.id not in pending_ids %}<option value="{{x.id}}">{{x.name}} — {{x.temple}}</option>{% endif %}{% endfor %}
    </select>
    <button class="btn bad" type="submit" onclick="return confirm('ยืนยันส่งคำขอแจ้งมรณภาพให้ Admin ตรวจสอบหรือไม่?')">ส่งคำขอแจ้งมรณภาพ</button>
    </form></div>
    {% if pending_ids %}<div class="card"><b>⏳ มีคำขอที่กำลังรอ Admin ตรวจสอบอยู่ {{pending_ids|length}} รายการ</b><p class="muted">เมื่อ Admin อนุมัติ สถานะพระจะเปลี่ยนเป็น “มรณภาพ” และจะไม่สามารถแจ้งซ้ำได้</p></div>{% endif %}
    </section>"""
    return page("แจ้งมรณภาพ", body, rows=rows, pending_ids=pending_ids)

@app.route("/temple-admin/login", methods=["GET","POST"])
def temple_admin_login():
    if request.method=="POST":
        require_csrf(); conn=db(); row=conn.execute("SELECT * FROM temple_admins WHERE username=?",(request.form.get("username","").strip(),)).fetchone(); conn.close()
        if row and check_password_hash(row["password_hash"],request.form.get("password","")):
            banned=security_status("temple_admin",row["id"])
            if banned: return white_ban_page(banned)
            session.clear(); session.update(role="temple_admin",user_id=row["id"],csrf=secrets.token_urlsafe(24)); return redirect(url_for("temple_admin"))
        flash("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง","error")
    body="""<section class="login"><div class="card"><h1>🏯 ระบบเจ้าอาวาส/ผู้ดูแลวัด</h1><form class="form" method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><label>ชื่อ</label><input name="username" required><label>รหัส</label><input type="password" name="password" required><button class="btn primary">เข้าสู่ระบบ</button></form></div></section>"""
    return page("เข้าสู่ระบบผู้ดูแลวัด",body)

@app.get("/temple-admin/logout")
def temple_admin_logout(): session.clear(); return redirect(url_for("home"))

@app.route("/temple-admin", methods=["GET","POST"])
@temple_admin_required
def temple_admin():
    conn=db(); me=conn.execute("SELECT * FROM temple_admins WHERE id=?",(session["user_id"],)).fetchone()
    if not me: conn.close(); session.clear(); return redirect(url_for("temple_admin_login"))
    if request.method=="POST":
        require_csrf(); action=request.form.get("action")
        if action=="edit_person":
            tid=int(request.form.get("id",0)); row=conn.execute("SELECT * FROM temples WHERE id=? AND temple=?",(tid,me["temple"])).fetchone()
            if row:
                conn.execute("UPDATE temples SET name=?,ordination_date=?,position=?,status=?,person_type=? WHERE id=?",(request.form.get("name",""),request.form.get("ordination_date",""),request.form.get("position",""),request.form.get("status","บวชแล้ว"),request.form.get("person_type","พระ"),tid)); conn.commit(); flash("แก้ไขข้อมูลพระแล้ว","success")
            else: flash("ไม่พบรายชื่อในวัดของคุณ","error")
        elif action=="delete_request":
            tid=int(request.form.get("id",0)); row=conn.execute("SELECT id FROM temples WHERE id=? AND temple=?",(tid,me["temple"])).fetchone()
            if row:
                conn.execute("INSERT INTO temple_delete_requests(temple_id,temple_admin_id,reason,created_at) VALUES(?,?,?,?)",(tid,me["id"],request.form.get("reason",""),now())); conn.commit()
                if delete_action_security("temple_admin",me["id"]): return white_ban_page(datetime.now()+timedelta(hours=1))
                flash("ส่งคำขอลบไปให้ Admin แล้ว","success")
        elif action=="salary":
            setting=conn.execute("SELECT is_open FROM salary_settings WHERE id=1").fetchone()
            try: total=int(request.form.get("total_works","0"))
            except ValueError: total=-1
            channel=request.form.get("payment_channel","").strip()
            if not setting["is_open"]: flash("ขณะนี้ Admin ยังไม่เปิดรับคำขอเงินเดือน","error")
            elif not me["employee_id"] or total<0 or not channel: flash("กรอกข้อมูลเบิกเงินเดือนให้ครบ","error")
            else:
                dup=conn.execute("SELECT id FROM salary_requests WHERE employee_id=? AND status='pending'",(me["employee_id"],)).fetchone()
                if dup: flash("มีคำขอเงินเดือนที่กำลังรออนุมัติอยู่แล้ว","error")
                else:
                    conn.execute("INSERT INTO salary_requests(employee_id,name,temple,total_works,payment_channel,created_at) VALUES(?,?,?,?,?,?)",(me["employee_id"],me["royal_name"],me["temple"],total,channel,now())); conn.commit(); flash("ส่งคำขอเงินเดือนแล้ว","success")
        elif action=="transfer":
            name=request.form.get("name","").strip(); target=request.form.get("target_temple","").strip(); reason=request.form.get("reason"," ").strip()
            row=conn.execute("SELECT id FROM temples WHERE temple=? AND name=? ORDER BY id DESC LIMIT 1",(me["temple"],name)).fetchone()
            if not row or target not in TEMPLE_OPTIONS or target==me["temple"]: flash("ไม่พบรายชื่อหรือเลือกวัดปลายทางไม่ถูกต้อง","error")
            else:
                conn.execute("INSERT INTO transfer_requests(source_temple,target_temple,name,reason,requester_admin_id,created_at) VALUES(?,?,?,?,?,?)",(me["temple"],target,name,reason,me["id"],now())); conn.commit(); flash("ส่งคำขอย้ายสังกัดไปยังวัดปลายทางแล้ว","success")
        elif action=="accept_transfer":
            rid=int(request.form.get("id",0)); tr=conn.execute("SELECT * FROM transfer_requests WHERE id=? AND target_temple=? AND status='pending'",(rid,me["temple"])).fetchone()
            if tr:
                person=conn.execute("SELECT id FROM temples WHERE temple=? AND name=? ORDER BY id DESC LIMIT 1",(tr["source_temple"],tr["name"])).fetchone()
                if person:
                    conn.execute("UPDATE temples SET temple=? WHERE id=?",(me["temple"],person["id"]))
                    conn.execute("UPDATE transfer_requests SET status='approved',receiver_admin_id=?,decided_at=? WHERE id=?",(me["id"],now(),rid)); conn.commit(); flash("รับพระเข้าวัดแล้ว และปรับทะเบียนวัดหลักทันที","success")
                else: flash("ไม่พบรายชื่อในวัดต้นทาง","error")
        elif action=="reject_transfer":
            rid=int(request.form.get("id",0)); cur=conn.execute("UPDATE transfer_requests SET status='rejected',receiver_admin_id=?,decided_at=? WHERE id=? AND target_temple=? AND status='pending'",(me["id"],now(),rid,me["temple"])); conn.commit() if cur.rowcount else None; flash("ปฏิเสธคำขอย้ายแล้ว","success")
        conn.close(); return redirect(url_for("temple_admin"))
    people=conn.execute("SELECT * FROM temples WHERE temple=? ORDER BY id DESC",(me["temple"],)).fetchall()
    incoming=conn.execute("SELECT * FROM transfer_requests WHERE target_temple=? AND status='pending' ORDER BY id DESC",(me["temple"],)).fetchall()
    outgoing=conn.execute("SELECT * FROM transfer_requests WHERE requester_admin_id=? ORDER BY id DESC",(me["id"],)).fetchall(); conn.close()
    body="""<section class="section"><div class="sectionhead"><div><h1>🏯 {{me.royal_name}}</h1><p>{{me.temple}} • {{me.position}}</p></div><a class="btn" href="{{url_for('temple_admin_logout')}}">ออกจากระบบ</a></div>
    <div class="card"><h2>👥 ทะเบียนพระ/เณรในวัดของฉัน</h2>{% for x in people %}<article class="item"><h3>{{x.person_type or 'พระ'}} {{x.name}}</h3><p>{{x.position or '-'}}</p><button class="btn" type="button" onclick="document.getElementById('e{{x.id}}').style.display='block'">เปลี่ยนชื่อ/แก้ไขข้อมูล</button> <form method="post" style="display:inline" onsubmit="return confirm('ส่งคำขอลบรายชื่อนี้ให้ Admin หรือไม่?')"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="delete_request"><input type="hidden" name="id" value="{{x.id}}"><button class="btn bad">ลบ</button></form><div id="e{{x.id}}" class="card" style="display:none"><form class="form" method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="edit_person"><input type="hidden" name="id" value="{{x.id}}"><label>ประเภท</label><select name="person_type"><option value="พระ" {% if (x.person_type or 'พระ')=='พระ' %}selected{% endif %}>พระ</option><option value="เณร" {% if x.person_type=='เณร' %}selected{% endif %}>เณร</option></select><label>ชื่อ/ฉายา</label><input name="name" value="{{x.name}}" required><label>วันที่บวช</label><input name="ordination_date" value="{{x.ordination_date}}"><label>ตำแหน่ง</label><select name="position">{% for p in position_options %}<option {% if p==x.position %}selected{% endif %}>{{p}}</option>{% endfor %}</select><label>สถานะ</label><input name="status" value="{{x.status}}"><button class="btn primary">บันทึก</button></form></div></article>{% else %}<div class="empty">ยังไม่มีรายชื่อ</div>{% endfor %}</div>
    <div class="card"><h2>🔄 คำขอย้ายเข้าสังกัด {{me.temple}}</h2>{% for x in incoming %}<article class="item"><h3>{{x.name}}</h3><p>จาก {{x.source_temple}} • {{x.reason}}</p><form method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="id" value="{{x.id}}"><button class="btn good" name="action" value="accept_transfer">อนุมัติรับเข้า</button> <button class="btn bad" name="action" value="reject_transfer">ไม่อนุมัติ</button></form></article>{% else %}<div class="empty">ไม่มีคำขอย้ายเข้าสังกัด</div>{% endfor %}</div>
    <div class="card"><h2>📤 แจ้งย้ายสังกัด</h2><form class="form" method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="transfer"><label>ชื่อ/ราชทินนาม</label><input name="name" required><label>เหตุผล</label><textarea name="reason" required></textarea><label>วัดที่จะไป</label><select name="target_temple">{% for t in temples %}{% if t!=me.temple %}<option>{{t}}</option>{% endif %}{% endfor %}</select><button class="btn primary">ส่งคำขอย้าย</button></form></div>
    <div class="card"><h2>💰 เบิกเงินเดือน</h2><p>ใช้ฐานคำขอเงินเดือนเดียวกับระบบพนักงาน</p>{% if salary_open %}<form class="form" method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="salary"><label>ผลงานทั้งหมด</label><input name="total_works" type="number" min="0" value="0" required><label>ช่องทางรับเงิน</label><input name="payment_channel" required placeholder="พร้อมเพย์/บัญชี"><button class="btn primary">ส่งคำขอเงินเดือน</button></form>{% else %}<p>Admin ยังไม่เปิดรับคำขอเงินเดือน</p>{% endif %}</div></section>"""
    c2=db(); salary_open=bool(c2.execute("SELECT is_open FROM salary_settings WHERE id=1").fetchone()["is_open"]); c2.close()
    return page("ระบบจัดการวัด",body,me=me,people=people,incoming=incoming,outgoing=outgoing,temples=TEMPLE_OPTIONS,position_options=POSITION_OPTIONS,salary_open=salary_open)

# ------------------------- Admin additions -------------------------
@app.route("/admin/temple-admins", methods=["GET","POST"])
@admin_required
def admin_temple_admins():
    conn=db()
    if request.method=="POST":
        require_csrf(); action=request.form.get("action")
        if action=="add":
            username=request.form.get("username","").strip(); password=request.form.get("password",""); royal=request.form.get("royal_name","").strip(); temple=request.form.get("temple",""); pos=request.form.get("position","")
            if not username or not password or not royal or temple not in TEMPLE_OPTIONS or pos not in TEMPLE_POSITIONS: flash("กรอกข้อมูลบัญชีผู้ดูแลวัดให้ครบ","error")
            elif conn.execute("SELECT id FROM temple_admins WHERE username=?",(username,)).fetchone() or conn.execute("SELECT id FROM employees WHERE username=?",(username,)).fetchone(): flash("ชื่อผู้ใช้นี้มีอยู่แล้ว","error")
            else:
                cur=conn.execute("INSERT INTO employees(username,password_hash,display_name,position,created_at) VALUES(?,?,?,?,?)",(username,generate_password_hash(password),royal,pos,now())); eid=cur.lastrowid
                conn.execute("INSERT INTO temple_admins(username,password_hash,royal_name,temple,position,employee_id,created_at) VALUES(?,?,?,?,?,?,?)",(username,generate_password_hash(password),royal,temple,pos,eid,now())); conn.commit(); flash("เพิ่มบัญชีเจ้าอาวาส/ผู้ดูแลวัดแล้ว และเชื่อมกับระบบพนักงานแล้ว","success")
        elif action=="delete":
            tid=int(request.form.get("id",0)); row=conn.execute("SELECT employee_id FROM temple_admins WHERE id=?",(tid,)).fetchone()
            if row:
                conn.execute("DELETE FROM temple_admins WHERE id=?",(tid,));
                if row["employee_id"]: conn.execute("DELETE FROM employees WHERE id=?",(row["employee_id"],))
                conn.commit(); flash("ลบบัญชีผู้ดูแลวัดแล้ว","success")
        return redirect(url_for("admin_temple_admins"))
    rows=conn.execute("SELECT * FROM temple_admins ORDER BY id DESC").fetchall(); conn.close()
    body="""<section class="section"><div class="sectionhead"><h1>🏯 เพิ่มเจ้าอาวาส/ผู้ดูแลวัด</h1><a class="btn" href="{{url_for('admin')}}">← หลังบ้าน</a></div><div class="card"><form class="form" method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="add"><label>ชื่อผู้ใช้</label><input name="username" required><label>รหัส</label><input name="password" type="password" required><label>ชื่อราชทินนาม</label><input name="royal_name" required><label>สังกัดวัด</label><select name="temple">{% for t in temples %}<option>{{t}}</option>{% endfor %}</select><label>ตำแหน่งภายในวัด</label><select name="position">{% for p in temple_positions %}<option>{{p}}</option>{% endfor %}</select><button class="btn primary">เพิ่มบัญชี</button></form></div><div class="list">{% for x in rows %}<div class="item"><b>{{x.royal_name}}</b> • {{x.temple}} • {{x.position}} • {{x.username}} <form method="post" style="display:inline" onsubmit="return confirm('ลบบัญชีนี้หรือไม่?')"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="delete"><input type="hidden" name="id" value="{{x.id}}"><button class="btn bad">ลบ</button></form></div>{% endfor %}</div></section>"""
    return page("เพิ่มเจ้าอาวาส",body,rows=rows,temples=TEMPLE_OPTIONS,temple_positions=TEMPLE_POSITIONS)

@app.route("/admin/promotion", methods=["GET","POST"])
@admin_required
def admin_promotion():
    conn=db()
    if request.method=="POST":
        require_csrf(); rid=int(request.form.get("id",0)); action=request.form.get("action"); row=conn.execute("SELECT * FROM promotion_requests WHERE id=? AND status='pending'",(rid,)).fetchone()
        if row:
            if action=="approve":
                conn.execute("INSERT INTO promotion_history(employee_id,applicant_name,royal_name,vassa,temple,position,current_rank,requested_rank,temple_role,approved_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(row["employee_id"],row["applicant_name"],row["royal_name"],row["vassa"],row["temple"],row["position"],row["current_rank"],row["requested_rank"],row["temple_role"],now()))
                if row["employee_id"]: conn.execute("UPDATE employees SET position=? WHERE id=?",(row["position"],row["employee_id"]))
                conn.execute("DELETE FROM promotion_requests WHERE id=?",(rid,)); conn.commit(); flash("อนุมัติเลื่อนสมณศักดิ์และย้ายรายการไปประวัติแล้ว","success")
            elif action=="reject": conn.execute("DELETE FROM promotion_requests WHERE id=?",(rid,)); conn.commit(); flash("ไม่อนุมัติคำขอเลื่อนสมณศักดิ์แล้ว","success")
        return redirect(url_for("admin_promotion"))
    rows=conn.execute("SELECT * FROM promotion_requests WHERE status='pending' ORDER BY id DESC").fetchall(); conn.close()
    body="""<section class="section"><div class="sectionhead"><h1>🎖️ อนุมัติเลื่อนสมณศักดิ์</h1><a class="btn" href="{{url_for('admin')}}">← หลังบ้าน</a></div><div class="list">{% for x in rows %}<article class="item"><h3>{{x.royal_name}}</h3><p>พรรษา {{x.vassa}} • {{x.temple}} • {{x.position}}</p><p>ชั้นยศปัจจุบัน: {{x.current_rank}} → ขอ: {{x.requested_rank}}</p><p>ตำแหน่งในวัด: {{x.temple_role}}</p><form method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="id" value="{{x.id}}"><button class="btn good" name="action" value="approve">อนุมัติ</button> <button class="btn bad" name="action" value="reject">ไม่อนุมัติ</button></form></article>{% else %}<div class="empty">ไม่มีคำขอรออนุมัติ</div>{% endfor %}</div></section>"""
    return page("อนุมัติเลื่อนสมณศักดิ์",body,rows=rows)

@app.route("/admin/defrock", methods=["GET","POST"])
@admin_required
def admin_defrock():
    conn=db()
    if request.method=="POST":
        require_csrf(); rid=int(request.form.get("id",0)); action=request.form.get("action")
        if action=="send":
            pid=int(request.form.get("preceptor_id",0)); cur=conn.execute("UPDATE defrock_requests SET preceptor_id=? WHERE id=? AND status='pending'",(pid,rid)); conn.commit() if cur.rowcount else None; flash("ส่งคำขอสึกไปยังพระอุปัชฌาย์แล้ว","success")
        elif action=="delete": conn.execute("DELETE FROM defrock_requests WHERE id=?",(rid,)); conn.commit(); flash("ลบคำขอสึกแล้ว","success")
        return redirect(url_for("admin_defrock"))
    rows=conn.execute("SELECT * FROM defrock_requests WHERE status='pending' ORDER BY id DESC").fetchall(); pre=conn.execute("SELECT * FROM preceptors ORDER BY id").fetchall(); conn.close()
    body="""<section class="section"><h1>🧘 คำขอสึก</h1><div class="list">{% for x in rows %}<article class="item"><h3>{{x.name}}</h3><p>{{x.temple}} • Discord {{x.discord_username}}</p><p>{{x.reason}}</p><form class="form" method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="id" value="{{x.id}}"><label>พระอุปัชฌาย์</label><select name="preceptor_id">{% for p in pre %}<option value="{{p.id}}">{{p.display_name or p.username}}</option>{% endfor %}</select><button class="btn primary" name="action" value="send">ส่งต่อ</button><button class="btn bad" name="action" value="delete">ลบ</button></form></article>{% else %}<div class="empty">ไม่มีคำขอสึก</div>{% endfor %}</div></section>"""
    return page("คำขอสึก",body,rows=rows,pre=pre)

@app.route("/admin/temple-requests", methods=["GET","POST"])
@admin_required
def admin_temple_requests():
    conn=db()
    if request.method=="POST":
        require_csrf(); action=request.form.get("action"); rid=int(request.form.get("id",0))
        if action in ("approve_delete","reject_delete"):
            row=conn.execute("SELECT * FROM temple_delete_requests WHERE id=? AND status='pending'",(rid,)).fetchone()
            if row:
                if action=="approve_delete": conn.execute("DELETE FROM temples WHERE id=?",(row["temple_id"],))
                conn.execute("UPDATE temple_delete_requests SET status=?,created_at=created_at WHERE id=?",("approved" if action=="approve_delete" else "rejected",rid)); conn.commit(); flash("ดำเนินการคำขอลบทะเบียนแล้ว","success")
        return redirect(url_for("admin_temple_requests"))
    rows=conn.execute("SELECT r.*,t.name,t.temple FROM temple_delete_requests r LEFT JOIN temples t ON t.id=r.temple_id WHERE r.status='pending' ORDER BY r.id DESC").fetchall(); conn.close()
    body="""<section class="section"><h1>🏯 คำขอลบคนออกจากวัด</h1><div class="list">{% for x in rows %}<article class="item"><h3>{{x.name}}</h3><p>{{x.temple}} • {{x.reason or 'ไม่ได้ระบุเหตุผล'}}</p><form method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="id" value="{{x.id}}"><button class="btn good" name="action" value="approve_delete">อนุมัติ</button> <button class="btn bad" name="action" value="reject_delete">ไม่อนุมัติ</button></form></article>{% else %}<div class="empty">ไม่มีคำขอ</div>{% endfor %}</div></section>"""
    return page("คำขอลบคนออกจากวัด",body,rows=rows)

@app.route("/admin/activities", methods=["GET","POST"])
@admin_required
def admin_activities():
    conn=db()
    if request.method=="POST":
        require_csrf(); action=request.form.get("action"); kind=request.form.get("kind")
        if action=="toggle":
            val=1 if request.form.get("is_open")=="1" else 0; conn.execute("UPDATE activities SET is_open=? WHERE kind=?",(val,kind)); conn.commit(); flash("เปลี่ยนสถานะกิจกรรมแล้ว","success")
        elif action=="quiz_setup":
            try: count=max(1,int(request.form.get("question_count","1")))
            except ValueError: count=1
            q=request.form.get("main_question","").strip(); conn.execute("UPDATE activities SET question_count=?,main_question=? WHERE kind='quiz'",(count,q)); conn.commit(); flash("บันทึกกิจกรรมตอบคำถามแล้ว","success")
        elif action=="decision":
            sid=int(request.form.get("id",0)); st="approved" if request.form.get("decision")=="approve" else "rejected"; conn.execute("UPDATE activity_submissions SET status=? WHERE id=?",(st,sid)); conn.commit(); flash("ดำเนินการคำขอกิจกรรมแล้ว","success")
        return redirect(url_for("admin_activities"))
    acts={r["kind"]:r for r in conn.execute("SELECT * FROM activities").fetchall()}; subs=conn.execute("SELECT s.*,a.kind FROM activity_submissions s JOIN activities a ON a.id=s.activity_id WHERE s.status='pending' ORDER BY s.id DESC").fetchall(); conn.close()
    body="""<section class="section"><h1>🎯 จัดกิจกรรม</h1><div class="grid"><div class="card"><h2>🎬 จัดกิจกรรมโปรโมทกลุ่ม</h2><p>สถานะ: {{'เริ่มกิจกรรม' if promo.is_open else 'ไม่เริ่ม'}}</p><form method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="toggle"><input type="hidden" name="kind" value="promo"><input type="hidden" name="is_open" value="{{0 if promo.is_open else 1}}"><button class="btn primary">{{'ไม่เริ่มกิจกรรม' if promo.is_open else 'เริ่มกิจกรรม'}}</button></form></div><div class="card"><h2>❓ ตอบคำถาม</h2><p>สถานะ: {{'เริ่มกิจกรรม' if quiz.is_open else 'ไม่เริ่ม'}}</p><form class="form" method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="quiz_setup"><label>จำนวนข้อ</label><input name="question_count" type="number" min="1" value="{{quiz.question_count or 1}}"><label>คำถามหลัก</label><textarea name="main_question">{{quiz.main_question}}</textarea><button class="btn primary">บันทึกคำถาม</button></form><form method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="toggle"><input type="hidden" name="kind" value="quiz"><input type="hidden" name="is_open" value="{{0 if quiz.is_open else 1}}"><button class="btn">{{'ไม่เริ่มกิจกรรม' if quiz.is_open else 'เริ่มกิจกรรม'}}</button></form></div></div><h2>📨 คำขอส่งกิจกรรม</h2><div class="list">{% for x in subs %}<article class="item"><h3>{{x.royal_name}}</h3>{% if x.kind=='promo' %}<p>🎬 {{x.temple}} • {{x.tiktok_link}}</p>{% else %}<p>❓ {{x.answer}}</p>{% endif %}<form method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="id" value="{{x.id}}"><button class="btn good" name="action" value="decision" onclick="this.form.decision.value='approve'">อนุมัติ</button><button class="btn bad" name="action" value="decision" onclick="this.form.decision.value='reject'">ไม่อนุมัติ</button><input type="hidden" name="decision" value="approve"></form></article>{% else %}<div class="empty">ไม่มีคำขอกิจกรรม</div>{% endfor %}</div></section>"""
    return page("จัดกิจกรรม",body,promo=acts.get("promo"),quiz=acts.get("quiz"),subs=subs)

@app.route("/admin/contacts", methods=["GET","POST"])
@admin_required
def admin_contacts():
    conn=db()
    if request.method=="POST":
        require_csrf(); rid=int(request.form.get("id",0)); st="processing" if request.form.get("action")=="process" else "rejected"; conn.execute("UPDATE contact_requests SET status=?,decided_at=? WHERE id=? AND status='pending'",(st,now(),rid)); conn.commit(); flash("ดำเนินการคำขอติดต่อแล้ว","success"); return redirect(url_for("admin_contacts"))
    rows=conn.execute("SELECT * FROM contact_requests WHERE status='pending' ORDER BY id DESC").fetchall(); conn.close()
    body="""<section class="section"><h1>📩 คำขอติดต่อ Admin</h1><div class="list">{% for x in rows %}<article class="item"><h3>{{x.royal_name}}</h3><p style="white-space:pre-wrap">{{x.subject}}</p><form method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="id" value="{{x.id}}"><button class="btn good" name="action" value="process">ดำเนินการโดยเร็วที่สุด</button> <button class="btn bad" name="action" value="reject">ปฏิเสธ</button></form></article>{% else %}<div class="empty">ไม่มีคำขอติดต่อ</div>{% endfor %}</div></section>"""
    return page("คำขอติดต่อ Admin",body,rows=rows)



# ============================================================
# Extended modules: board / chat / invitations / complaints /
# vinaya / death / documents / announcements / blessings
# ============================================================

EVENT_TYPES=["งานแต่ง","งานศพ","งานบวช","งานเจริญพระพุทธมนต์","งานพระราชพิธี","งานทำบุญบ้าน","งานขึ้นบ้านใหม่","งานบุญทั่วไป"]
BOARD_DEFAULTS=[
 ("สมเด็จพระสังฆราช","center","","",1),("เจ้าคณะใหญ่ธรรมยุต","left","","",2),("เจ้าคณะใหญ่หนเหนือ","left","เจ้าคณะใหญ่ธรรมยุต","",3),("เจ้าคณะภาค 2","left","เจ้าคณะใหญ่ธรรมยุต","",4),("เจ้าคณะจังหวัดเพชรบูรณ์","left","เจ้าคณะภาค 2","",5),("เจ้าคณะกรุงเทพฯธรรมยุต","left","เจ้าคณะใหญ่ธรรมยุต","",6),("เจ้าคณะอำเภอชนแดน","left","เจ้าคณะจังหวัดเพชรบูรณ์","",7),("เจ้าคณะตำบลชนแดน","left","เจ้าคณะอำเภอชนแดน","",8),("เจ้าอาวาสวัดราชบพิธสถิตมหาสีมาราม","left","เจ้าคณะตำบลชนแดน","",9),("เจ้าอาวาสวัดป่าสังฆาภร","left","เจ้าคณะตำบลชนแดน","",10),("รองเจ้าอาวาส","left","เจ้าอาวาสวัดราชบพิธสถิตมหาสีมาราม","",11),("ผู้ช่วยเจ้าอาวาส","left","เจ้าอาวาสวัดราชบพิธสถิตมหาสีมาราม","",12),("รองเจ้าอาวาส","left","เจ้าอาวาสวัดป่าสังฆาภร","",13),("ผู้ช่วยเจ้าอาวาส","left","เจ้าอาวาสวัดป่าสังฆาภร","",14),
 ("เจ้าคณะใหญ่มหานิกาย","right","","",2),("เจ้าคณะใหญ่หนกลาง","right","เจ้าคณะใหญ่มหานิกาย","",3),("เจ้าคณะภาค 1","right","เจ้าคณะใหญ่มหานิกาย","",4),("เจ้าคณะจังหวัดกำแพงเพชร","right","เจ้าคณะภาค 1","",5),("เจ้าคณะกรุงเทพฯมหานิกาย","right","เจ้าคณะใหญ่มหานิกาย","",6),("เจ้าคณะอำเภอไทรงาม","right","เจ้าคณะจังหวัดกำแพงเพชร","",7),("เจ้าอาวาสวัดเนินกรอย","right","เจ้าคณะอำเภอไทรงาม","",8),("เจ้าอาวาสวัดไตรมิตรวิทยาราม","right","เจ้าคณะอำเภอไทรงาม","",9),("รองเจ้าอาวาส","right","เจ้าอาวาสวัดเนินกรอย","",10),("ผู้ช่วยเจ้าอาวาส","right","เจ้าอาวาสวัดเนินกรอย","",11),("รองเจ้าอาวาส","right","เจ้าอาวาสวัดไตรมิตรวิทยาราม","",12),("ผู้ช่วยเจ้าอาวาส","right","เจ้าอาวาสวัดไตรมิตรวิทยาราม","",13)
]

def seed_board():
    conn=db()
    if conn.execute("SELECT COUNT(*) n FROM board_members").fetchone()["n"]==0:
        for role,side,parent,name,order in BOARD_DEFAULTS:
            conn.execute("INSERT INTO board_members(role,side,parent_role,name,temple,sort_order) VALUES(?,?,?,?,?,?)",(role,side,parent,name,"",order))
        conn.commit()
    conn.close()
seed_board()

def security_key_for_session():
    role=session.get("role")
    if role in ("employee","preceptor","temple_admin","vinaya"):
        return role, str(session.get("user_id") or session.get("vinaya_id") or "")
    return None, None

def security_status(role, account_id):
    if not role or not account_id or role == "admin": return None
    conn=db(); row=conn.execute("SELECT banned_until FROM account_security WHERE role=? AND account_id=?",(role,str(account_id))).fetchone(); conn.close()
    if not row or not row["banned_until"]: return None
    try:
        until=datetime.strptime(row["banned_until"], "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None
    if datetime.now() >= until:
        conn=db(); conn.execute("UPDATE account_security SET banned_until='' WHERE role=? AND account_id=?",(role,str(account_id))); conn.commit(); conn.close(); return None
    return until

def delete_action_security(role, account_id):
    # Admin is exempt. The second deletion within the account lifetime triggers a 1-hour ban.
    if not role or not account_id or role == "admin": return False
    conn=db(); row=conn.execute("SELECT delete_count FROM account_security WHERE role=? AND account_id=?",(role,str(account_id))).fetchone()
    count=(int(row["delete_count"]) if row else 0)+1
    banned_until=''
    if count >= 2:
        banned_until=(datetime.now()+timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("""INSERT INTO account_security(role,account_id,delete_count,banned_until,created_at) VALUES(?,?,?,?,?)
                  ON CONFLICT(role,account_id) DO UPDATE SET delete_count=excluded.delete_count,banned_until=excluded.banned_until""",
                 (role,str(account_id),count,banned_until,now()))
    conn.commit(); conn.close()
    if banned_until:
        session.clear()
        return True
    return False

def white_ban_page(until):
    remaining=max(0,int((until-datetime.now()).total_seconds())) if until else 0
    mins=(remaining+59)//60
    return render_template_string("""<!doctype html><html lang='th'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>ถูกระงับชั่วคราว</title><style>html,body{margin:0;width:100%;height:100%;background:#fff}</style></head><body><script>document.title='ถูกระงับชั่วคราว';</script></body></html>"""), 403

def require_chat_user():
    uid=session.get("chat_user_id")
    if not uid:
        return False
    conn=db(); row=conn.execute("SELECT id FROM chat_users WHERE id=?",(uid,)).fetchone(); conn.close()
    return bool(row)

def chat_user_row():
    uid=session.get("chat_user_id")
    if not uid: return None
    conn=db(); row=conn.execute("SELECT u.*,p.display_name,p.avatar_file,p.bio FROM chat_users u LEFT JOIN chat_profiles p ON p.user_id=u.id WHERE u.id=?",(uid,)).fetchone(); conn.close(); return row

def chat_profile_name(user_id):
    conn=db(); row=conn.execute("SELECT u.username,COALESCE(p.display_name,'') display_name FROM chat_users u LEFT JOIN chat_profiles p ON p.user_id=u.id WHERE u.id=?",(user_id,)).fetchone(); conn.close()
    return ((row["display_name"] or row["username"]) if row else "ผู้ใช้")

def actor_id():
    if session.get("role")=="temple_admin": return "temple_admin:"+str(session.get("user_id"))
    if session.get("role")=="vinaya": return "vinaya:"+str(session.get("vinaya_id"))
    if session.get("role")=="admin": return "admin:"+str(ADMIN_USER)
    if session.get("chat_user_id"): return "chatuser:"+str(session["chat_user_id"])
    if "visitor_id" not in session: session["visitor_id"]=secrets.token_urlsafe(12)
    return "visitor:"+session["visitor_id"]

def actor_name():
    if session.get("role")=="temple_admin":
        conn=db(); r=conn.execute("SELECT royal_name FROM temple_admins WHERE id=?",(session.get("user_id"),)).fetchone(); conn.close(); return r["royal_name"] if r else "ผู้ดูแลวัด"
    if session.get("role")=="vinaya":
        conn=db(); r=conn.execute("SELECT royal_name FROM vinaya_officers WHERE id=?",(session.get("vinaya_id"),)).fetchone(); conn.close(); return r["royal_name"] if r else "พระวินยาธิการ"
    if session.get("chat_user_id"): return chat_profile_name(session["chat_user_id"])
    return session.get("visitor_name") or "ผู้ติดต่อ"

def chat_access(row):
    if not row or row["closed"]: return False
    a=actor_id()
    if a in (row["actor_a"],row["actor_b"]): return True
    if session.get("role")=="temple_admin":
        conn=db(); me=conn.execute("SELECT temple FROM temple_admins WHERE id=?",(session.get("user_id"),)).fetchone(); conn.close()
        if me and row["temple"]==me["temple"]: return True
    if session.get("role")=="admin" and row["actor_b"]=="admin:"+ADMIN_USER: return True
    if session.get("role")=="vinaya":
        conn=db(); ok=bool(conn.execute("SELECT enabled FROM vinaya_officers WHERE id=?",(session.get("vinaya_id"),)).fetchone()["enabled"]); conn.close(); return ok
    return False

def create_chat(kind,title,a,b,temple="",visitor_name=""):
    conn=db(); r=conn.execute("SELECT * FROM chats WHERE kind=? AND actor_a=? AND actor_b=? AND closed=0 ORDER BY id DESC LIMIT 1",(kind,a,b)).fetchone()
    if not r:
        r=conn.execute("SELECT * FROM chats WHERE kind=? AND actor_a=? AND actor_b=? AND closed=0 ORDER BY id DESC LIMIT 1",(kind,b,a)).fetchone()
    if r: conn.close(); return r["id"]
    cur=conn.execute("INSERT INTO chats(kind,title,actor_a,actor_b,temple,visitor_name,created_at) VALUES(?,?,?,?,?,?,?)",(kind,title,a,b,temple,visitor_name,now())); conn.commit(); cid=cur.lastrowid; conn.close(); return cid

@app.get("/board")
def board():
    conn=db(); rows=conn.execute("SELECT * FROM board_members ORDER BY side,sort_order,id").fetchall(); conn.close()
    body="""<section class="section"><h1>🏛️ บอร์ดบริหารคณะสงฆ์จำลอง</h1><p>ข้อมูลทั้งหมดเป็นข้อมูลจำลองสำหรับระบบนี้</p><div style="display:grid;grid-template-columns:1fr 1.2fr 1fr;gap:14px;align-items:start"><div class="card"><h2>ฝ่ายธรรมยุต</h2>{% for x in left %}<article class="item"><b>{{x.role}}</b><br>รูป: {{x.photo or '-'}}<br>ชื่อ: {{x.name or 'ว่าง'}}<br>วัด: {{x.temple or 'ว่าง'}}{% if x.role.startswith('เจ้าอาวาส') %}<small> • มีรอง/ผู้ช่วยในรายการย่อย</small>{% endif %}</article>{% endfor %}</div><div class="card"><h2 style="text-align:center">สมเด็จพระสังฆราช</h2>{% for x in center %}<article class="item"><b>{{x.role}}</b><br>รูป: {{x.photo or '-'}}<br>ชื่อ: {{x.name or 'ว่าง'}}<br>วัด: {{x.temple or 'ว่าง'}}</article>{% endfor %}</div><div class="card"><h2>ฝ่ายมหานิกาย</h2>{% for x in right %}<article class="item"><b>{{x.role}}</b><br>รูป: {{x.photo or '-'}}<br>ชื่อ: {{x.name or 'ว่าง'}}<br>วัด: {{x.temple or 'ว่าง'}}</article>{% endfor %}</div></div></section>"""
    return page("บอร์ดบริหาร",body,left=[x for x in rows if x["side"]=="left"],center=[x for x in rows if x["side"]=="center"],right=[x for x in rows if x["side"]=="right"])

@app.route("/admin/board",methods=["GET","POST"])
@admin_required
def admin_board():
    conn=db()
    if request.method=="POST":
        require_csrf(); action=request.form.get("action"); bid=int(request.form.get("id",0))
        if action=="add": conn.execute("INSERT INTO board_members(role,side,parent_role,name,temple,photo,sort_order) VALUES(?,?,?,?,?,?,?)",(request.form["role"],request.form["side"],request.form.get("parent_role",""),request.form.get("name",""),request.form.get("temple",""),request.form.get("photo",""),int(request.form.get("sort_order",99))))
        elif action=="edit": conn.execute("UPDATE board_members SET role=?,side=?,parent_role=?,name=?,temple=?,photo=?,sort_order=? WHERE id=?",(request.form["role"],request.form["side"],request.form.get("parent_role",""),request.form.get("name",""),request.form.get("temple",""),request.form.get("photo",""),int(request.form.get("sort_order",99)),bid))
        elif action=="delete": conn.execute("DELETE FROM board_members WHERE id=?",(bid,))
        conn.commit(); conn.close(); return redirect(url_for("admin_board"))
    rows=conn.execute("SELECT * FROM board_members ORDER BY side,sort_order,id").fetchall(); conn.close()
    body="""<section class="section"><h1>🏛️ คณะบริหารคณะสงฆ์</h1><div class="card"><form class="form" method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="add"><label>ตำแหน่ง</label><input name="role" required><label>ฝ่าย</label><select name="side"><option value="center">กลาง</option><option value="left">ธรรมยุต</option><option value="right">มหานิกาย</option></select><label>ตำแหน่งแม่</label><input name="parent_role"><label>รูป/ลิงก์รูป</label><input name="photo"><label>ชื่อ</label><input name="name"><label>วัด</label><select name="temple"><option value="">ว่าง</option>{% for t in temples %}<option>{{t}}</option>{% endfor %}</select><label>ลำดับ</label><input name="sort_order" type="number" value="99"><button class="btn primary">เพิ่ม</button></form></div><div class="list">{% for x in rows %}<article class="item"><b>{{x.role}}</b> • {{'ธรรมยุต' if x.side=='left' else ('มหานิกาย' if x.side=='right' else 'กลาง')}} • {{x.name or 'ว่าง'}} • {{x.temple or 'ว่าง'}}<button class="btn" type="button" onclick="document.getElementById('b{{x.id}}').style.display='block'">แก้ไข</button><form method="post" style="display:inline"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="delete"><input type="hidden" name="id" value="{{x.id}}"><button class="btn bad" onclick="return confirm('ลบรายการนี้?')">ลบ</button></form><div id="b{{x.id}}" class="card" style="display:none"><form class="form" method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="edit"><input type="hidden" name="id" value="{{x.id}}"><input name="role" value="{{x.role}}"><select name="side"><option value="center" {% if x.side=='center' %}selected{% endif %}>กลาง</option><option value="left" {% if x.side=='left' %}selected{% endif %}>ธรรมยุต</option><option value="right" {% if x.side=='right' %}selected{% endif %}>มหานิกาย</option></select><input name="parent_role" value="{{x.parent_role}}"><input name="photo" value="{{x.photo}}"><input name="name" value="{{x.name}}"><select name="temple"><option value="">ว่าง</option>{% for t in temples %}<option {% if x.temple==t %}selected{% endif %}>{{t}}</option>{% endfor %}</select><input name="sort_order" type="number" value="{{x.sort_order}}"><button class="btn primary">บันทึก</button></form></div></article>{% endfor %}</div></section>"""
    return page("จัดการคณะบริหาร",body,rows=rows)

@app.route("/chat/register",methods=["GET","POST"])
def chat_register():
    if request.method=="POST":
        require_csrf(); username=request.form.get("username","").strip()
        if len(username)<2 or len(username)>32:
            flash("ชื่อผู้ใช้ต้องมี 2-32 ตัวอักษร","error")
        else:
            conn=db(); row=conn.execute("SELECT id FROM chat_users WHERE username=?",(username,)).fetchone()
            if row:
                uid=row["id"]
            else:
                cur=conn.execute("INSERT INTO chat_users(username,created_at) VALUES(?,?)",(username,now())); uid=cur.lastrowid
                conn.execute("INSERT INTO chat_profiles(user_id,display_name,updated_at) VALUES(?,?,?)",(uid,username,now())); conn.commit()
            conn.close(); session["chat_user_id"]=uid; flash("เข้าสู่บัญชีแชทแล้ว","success"); return redirect(url_for("chat_profile"))
    body="""<section class="login"><div class="card"><h1>💬 สมัครบัญชีแชท</h1><p>ระบบจำลองนี้ใช้ชื่อผู้ใช้เพียงอย่างเดียว ไม่มีรหัสผ่าน</p><form class="form" method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><label>ชื่อผู้ใช้</label><input name="username" maxlength="32" required><button class="btn primary">ตกลง / เข้าใช้งาน</button></form></div></section>"""
    return page("สมัครบัญชีแชท",body)

@app.get("/chat/logout")
def chat_logout():
    session.pop("chat_user_id",None); return redirect(url_for("home"))

def chat_login():
    if request.method=="POST":
        require_csrf(); username=request.form.get("username","").strip()
        if len(username)<2 or len(username)>32:
            flash("กรุณาใส่ชื่อผู้ใช้ 2-32 ตัวอักษร","error")
        else:
            conn=db(); row=conn.execute("SELECT id FROM chat_users WHERE username=?",(username,)).fetchone(); conn.close()
            if row:
                session["chat_user_id"]=row["id"]
                flash("เข้าสู่บัญชีแชทแล้ว","success")
                return redirect(url_for("chat_profile"))
            flash("ไม่พบบัญชีนี้ กรุณาสมัครบัญชีแชทก่อน","error")
    body="""<section class="login"><div class="card"><h1>🔐 เข้าสู่ระบบแชท</h1><p>ใช้ชื่อผู้ใช้ที่สมัครไว้ ไม่ต้องสมัครใหม่ทุกครั้ง</p><form class="form" method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><label>ชื่อผู้ใช้</label><input name="username" maxlength="32" autocomplete="username" required><button class="btn primary">เข้าสู่ระบบ</button></form><p style="margin-top:14px"><a class="btn" href="{{url_for('chat_register')}}">✨ ยังไม่มีบัญชี → สมัคร</a></p></div></section>"""
    return page("เข้าสู่ระบบแชท",body)

@app.route("/chat/profile",methods=["GET","POST"])
def chat_profile():
    if not require_chat_user(): return redirect(url_for("chat_register"))
    uid=session["chat_user_id"]; conn=db()
    if request.method=="POST":
        require_csrf(); display=request.form.get("display_name","").strip() or chat_profile_name(uid); bio=request.form.get("bio","").strip(); avatar=save_upload(request.files.get("avatar"),"chatavatar") if request.files.get("avatar") else ""
        if avatar: conn.execute("UPDATE chat_profiles SET display_name=?,bio=?,avatar_file=?,updated_at=? WHERE user_id=?",(display,bio,avatar,now(),uid))
        else: conn.execute("UPDATE chat_profiles SET display_name=?,bio=?,updated_at=? WHERE user_id=?",(display,bio,now(),uid))
        conn.commit(); flash("บันทึกโปรไฟล์แชทแล้ว","success")
    row=conn.execute("SELECT u.username,p.display_name,p.avatar_file,p.bio FROM chat_users u LEFT JOIN chat_profiles p ON p.user_id=u.id WHERE u.id=?",(uid,)).fetchone(); conn.close()
    body="""<section class="section"><div class="sectionhead"><h1>👤 โปรไฟล์แชท</h1><a class="btn" href="{{url_for('chat_logout')}}">ออกจากบัญชีแชท</a></div><div class="card"><form class="form" method="post" enctype="multipart/form-data"><input type="hidden" name="_csrf" value="{{csrf_token()}}">{% if row.avatar_file %}<img class="avatar-large" src="{{url_for('uploaded_file',filename=row.avatar_file)}}">{% else %}<div class="avatar-large avatar-empty">👤</div>{% endif %}<label>ชื่อผู้ใช้</label><input value="{{row.username}}" disabled><label>ชื่อที่แสดง</label><input name="display_name" value="{{row.display_name or row.username}}" maxlength="50"><label>รายละเอียด</label><textarea name="bio" maxlength="300" placeholder="แนะนำตัวสั้น ๆ">{{row.bio}}</textarea><label>เปลี่ยนรูปโปรไฟล์</label><input type="file" name="avatar" accept="image/*"><button class="btn primary">บันทึกโปรไฟล์</button></form></div><div class="actions"><a class="btn" href="{{url_for('chat_friends')}}">👥 เพื่อน</a><a class="btn" href="{{url_for('my_chats')}}">💬 ประวัติแชท</a></div></section>"""
    return page("โปรไฟล์แชท",body,row=row)

@app.get("/chat/friends")
def chat_friends():
    if not require_chat_user(): return redirect(url_for("chat_register"))
    uid=session["chat_user_id"]; conn=db(); rows=conn.execute("SELECT u.id,u.username,p.display_name,p.avatar_file,p.bio FROM chat_friends f JOIN chat_users u ON u.id=f.friend_id LEFT JOIN chat_profiles p ON p.user_id=u.id WHERE f.user_id=? ORDER BY u.username",(uid,)).fetchall(); conn.close()
    body="""<section class="section"><div class="sectionhead"><h1>👥 เพื่อนของฉัน</h1><a class="btn" href="{{url_for('chat_profile')}}">โปรไฟล์</a></div><div class="list">{% for x in rows %}<article class="item"><b>{{x.display_name or x.username}}</b> <small>@{{x.username}}</small><p>{{x.bio or 'ไม่มีรายละเอียด'}}</p><a class="btn primary" href="{{url_for('chat_profile_view',user_id=x.id)}}">ดูโปรไฟล์</a> <a class="btn" href="{{url_for('private_chat',user_id=x.id)}}">แชท</a></article>{% else %}<div class="empty">ยังไม่มีเพื่อน กดดูโปรไฟล์ผู้ใช้จากห้องแชทเพื่อเพิ่มเพื่อนได้</div>{% endfor %}</div></section>"""
    return page("เพื่อนแชท",body,rows=rows)

@app.get("/chat/profile/<int:user_id>")
def chat_profile_view(user_id):
    if not require_chat_user(): return redirect(url_for("chat_register"))
    uid=session["chat_user_id"]; conn=db(); row=conn.execute("SELECT u.id,u.username,p.display_name,p.avatar_file,p.bio FROM chat_users u LEFT JOIN chat_profiles p ON p.user_id=u.id WHERE u.id=?",(user_id,)).fetchone(); friend=bool(conn.execute("SELECT 1 FROM chat_friends WHERE user_id=? AND friend_id=?",(uid,user_id)).fetchone()) if row and uid!=user_id else False; conn.close()
    if not row: abort(404)
    body="""<section class="section"><div class="card">{% if row.avatar_file %}<img class="avatar-large" src="{{url_for('uploaded_file',filename=row.avatar_file)}}">{% else %}<div class="avatar-large avatar-empty">👤</div>{% endif %}<h1>{{row.display_name or row.username}}</h1><p>@{{row.username}}</p><p style="white-space:pre-wrap">{{row.bio or 'ไม่มีรายละเอียด'}}</p>{% if row.id != current_id %}<div class="actions">{% if not friend %}<form method="post" action="{{url_for('add_friend',user_id=row.id)}}"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><button class="btn">➕ เพิ่มเพื่อน</button></form>{% else %}<span class="badge good">เป็นเพื่อนแล้ว</span>{% endif %}<a class="btn primary" href="{{url_for('private_chat',user_id=row.id)}}">💬 แชทส่วนตัว</a></div>{% endif %}</div></section>"""
    return page("โปรไฟล์ผู้ใช้",body,row=row,current_id=uid,friend=friend)

@app.post("/chat/profile/<int:user_id>/add-friend")
def add_friend(user_id):
    if not require_chat_user(): return redirect(url_for("chat_register"))
    require_csrf(); uid=session["chat_user_id"]
    if uid==user_id: return redirect(url_for("chat_profile"))
    conn=db(); exists=conn.execute("SELECT id FROM chat_users WHERE id=?",(user_id,)).fetchone()
    if exists:
        conn.execute("INSERT OR IGNORE INTO chat_friends(user_id,friend_id,created_at) VALUES(?,?,?)",(uid,user_id,now()))
        conn.execute("INSERT OR IGNORE INTO chat_friends(user_id,friend_id,created_at) VALUES(?,?,?)",(user_id,uid,now()))
        conn.commit(); flash("เพิ่มเพื่อนแล้ว","success")
    conn.close(); return redirect(url_for("chat_profile_view",user_id=user_id))

@app.get("/my-chats")
def my_chats():
    if not require_chat_user(): return redirect(url_for("chat_register"))
    a=actor_id(); conn=db(); rows=conn.execute("SELECT * FROM chats WHERE actor_a=? OR actor_b=? ORDER BY id DESC",(a,a)).fetchall(); conn.close()
    body="""<section class="section"><div class="sectionhead"><h1>💬 แชทของฉัน / ประวัติแชท</h1><a class="btn" href="{{url_for('chat_profile')}}">โปรไฟล์แชท</a></div><div class="list">{% for x in rows %}<article class="item"><b>{{x.title}}</b> • {{x.closed and 'หยุดแล้ว' or 'กำลังคุย'}} <div class="actions"><a class="btn primary" href="{{url_for('chat_room',chat_id=x.id)}}">เปิด</a><form method="post" action="{{url_for('chat_delete',chat_id=x.id)}}" onsubmit="return confirm('ลบประวัติแชทนี้หรือไม่?')"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><button class="btn bad">ลบ</button></form></div></article>{% else %}<div class="empty">ยังไม่มีแชท</div>{% endfor %}</div></section>"""
    return page("แชทของฉัน",body,rows=rows)

@app.get("/chat/temples")
def temple_chat_home():
    if not require_chat_user(): return redirect(url_for("chat_register"))
    body="""<section class="section"><div class="sectionhead"><h1>💬 แชทติดต่อ 4 วัด</h1><a class="btn" href="{{url_for('chat_profile')}}">โปรไฟล์แชท</a></div><p>เลือกวัดเพื่อเริ่มบทสนทนา</p><div class="grid">{% for t in temples %}<a class="card cardsmall" href="{{url_for('temple_chat',temple=t)}}"><h2>🏯 {{t}}</h2><span>เปิดแชท →</span></a>{% endfor %}</div></section>"""
    return page("แชท 4 วัด",body)

@app.route("/chat/temple/<path:temple>",methods=["GET","POST"])
def temple_chat(temple):
    if not require_chat_user(): return redirect(url_for("chat_register"))
    if temple not in TEMPLE_OPTIONS: abort(404)
    visitor=actor_id(); other="temple:"+temple
    cid=create_chat("temple","แชท "+temple,visitor,other,temple,chat_profile_name(session["chat_user_id"]))
    return redirect(url_for("chat_room",chat_id=cid))

@app.get("/chat/private/<int:user_id>")
def private_chat(user_id):
    if not require_chat_user(): return redirect(url_for("chat_register"))
    uid=session["chat_user_id"]
    if uid==user_id: return redirect(url_for("chat_profile"))
    conn=db(); row=conn.execute("SELECT id FROM chat_users WHERE id=?",(user_id,)).fetchone(); conn.close()
    if not row: abort(404)
    cid=create_chat("private", "แชทกับ "+chat_profile_name(user_id), "chatuser:"+str(uid), "chatuser:"+str(user_id), "", chat_profile_name(uid))
    return redirect(url_for("chat_room",chat_id=cid))

@app.route("/chat/<int:chat_id>",methods=["GET"])
def chat_room(chat_id):
    if not require_chat_user() and session.get("role") not in ("admin","temple_admin","vinaya"): return redirect(url_for("chat_register"))
    conn=db(); chat=conn.execute("SELECT * FROM chats WHERE id=?",(chat_id,)).fetchone(); conn.close()
    if not chat_access(chat): abort(403)
    can_stop=(actor_id() in (chat["actor_a"],chat["actor_b"])) or session.get("role") in ("admin","temple_admin")
    body="""<section class="section"><div class="sectionhead"><h1>💬 {{chat.title}}</h1><button class="btn" onclick="reloadChat()">↻ รี Chat</button></div><div class="card" id="messages" style="max-height:55vh;overflow:auto"></div><div class="card"><form id="chatForm" class="form" enctype="multipart/form-data"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><textarea name="message" placeholder="พิมพ์ข้อความ"></textarea><label>รูปภาพ</label><input type="file" name="image" accept="image/*"><label>เสียง</label><input type="file" name="audio" accept="audio/*"><button class="btn" type="button" id="record">🎙️ อัดเสียง</button><button class="btn primary">ส่งข้อความ</button></form>{% if can_stop %}<button class="btn bad" onclick="stopChat()">หยุดแชท</button>{% endif %}</div></section><script>
function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c]))} async function load(){let r=await fetch('/chat/api/{{chat.id}}',{cache:'no-store'});if(!r.ok)return;let d=await r.json();document.getElementById('messages').innerHTML=d.messages.map(x=>`<div class="item"><b>${x.profile_url?`<a href="${esc(x.profile_url)}">${esc(x.sender_name||x.sender)}</a>`:esc(x.sender_name||x.sender)}</b><small> ${esc(x.created_at)}</small><p>${esc(x.message||'')}</p>${x.image_file?`<img class="preview" src="/uploads/${encodeURIComponent(x.image_file)}">`:''}${x.audio_file?`<audio controls src="/uploads/${encodeURIComponent(x.audio_file)}"></audio>`:''}</div>`).join('');document.getElementById('messages').scrollTop=document.getElementById('messages').scrollHeight}
async function reloadChat(){await load()} setInterval(load,2500); load();
document.getElementById('chatForm').onsubmit=async(e)=>{e.preventDefault();let f=new FormData(e.target);let r=await fetch('/chat/{{chat.id}}/send',{method:'POST',body:f});if(r.ok){e.target.reset();load()}}
let recorder,parts=[];document.getElementById('record').onclick=async()=>{if(recorder&&recorder.state==='recording'){recorder.stop();return}let stream=await navigator.mediaDevices.getUserMedia({audio:true});recorder=new MediaRecorder(stream);parts=[];recorder.ondataavailable=e=>parts.push(e.data);recorder.onstop=async()=>{let blob=new Blob(parts,{type:'audio/webm'});let f=new FormData();f.append('_csrf','{{csrf_token()}}');f.append('audio',blob,'voice.webm');await fetch('/chat/{{chat.id}}/send',{method:'POST',body:f});stream.getTracks().forEach(t=>t.stop());load();document.getElementById('record').textContent='🎙️ อัดเสียง'};recorder.start();document.getElementById('record').textContent='⏹️ หยุดอัดเสียง'};
async function stopChat(){if(confirm('หยุดแชทจริงหรือไม่? ระบบจะลบห้องและข้อความทันที')){await fetch('/chat/{{chat.id}}/stop',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'_csrf={{csrf_token()}}'});location.href='/my-chats'}}
</script>"""
    return page("แชท",body,chat=chat,can_stop=can_stop)

@app.get("/chat/api/<int:chat_id>")
def chat_api(chat_id):
    if not require_chat_user() and session.get("role") not in ("admin","temple_admin","vinaya"): return {"error":"login_required"},401
    conn=db(); chat=conn.execute("SELECT * FROM chats WHERE id=?",(chat_id,)).fetchone()
    if not chat_access(chat): conn.close(); return {"error":"forbidden"},403
    rows=conn.execute("SELECT sender,sender_name,message,image_file,audio_file,created_at FROM chat_messages WHERE chat_id=? ORDER BY id",(chat_id,)).fetchall(); out=[]
    for x in rows:
        d=dict(x); d["profile_url"]=""
        if str(x["sender"]).startswith("chatuser:"):
            try: uid=int(str(x["sender"]).split(":",1)[1]); d["profile_url"]=url_for("chat_profile_view",user_id=uid)
            except Exception: pass
        out.append(d)
    conn.close(); return {"messages":out}

@app.post("/chat/<int:chat_id>/send")
def chat_send(chat_id):
    if not require_chat_user() and session.get("role") not in ("admin","temple_admin","vinaya"): return {"error":"login_required"},401
    require_csrf(); conn=db(); chat=conn.execute("SELECT * FROM chats WHERE id=?",(chat_id,)).fetchone()
    if not chat_access(chat): conn.close(); return {"error":"forbidden"},403
    msg=request.form.get("message","").strip(); image=""; audio=""
    try:
        if request.files.get("image"): image=save_upload(request.files["image"],"chatimg")
        if request.files.get("audio"):
            f=request.files["audio"]; safe_audio=secure_filename(f.filename); ext=safe_audio.rsplit('.',1)[-1].lower() if '.' in safe_audio else 'webm'
            if ext not in {"webm","ogg","mp3","wav","m4a","aac"}: raise ValueError("รองรับเสียง WEBM, OGG, MP3, WAV, M4A และ AAC")
            audio=f"chataudio_{secrets.token_hex(8)}.{ext}"; f.save(UPLOAD_DIR/audio)
    except ValueError as e: conn.close(); return {"error":str(e)},400
    if not msg and not image and not audio: conn.close(); return {"error":"empty"},400
    conn.execute("INSERT INTO chat_messages(chat_id,sender,sender_name,message,image_file,audio_file,created_at) VALUES(?,?,?,?,?,?,?)",(chat_id,actor_id(),actor_name(),msg,image,audio,now())); conn.commit(); conn.close(); return {"ok":True}

@app.post("/chat/<int:chat_id>/stop")
def chat_stop(chat_id):
    if not require_chat_user() and session.get("role") not in ("admin","temple_admin","vinaya"): return {"error":"login_required"},401
    require_csrf(); conn=db(); chat=conn.execute("SELECT * FROM chats WHERE id=?",(chat_id,)).fetchone()
    if not chat_access(chat): conn.close(); return {"error":"forbidden"},403
    if actor_id() not in (chat["actor_a"],chat["actor_b"]) and session.get("role") not in ("admin","temple_admin"):
        conn.close(); return {"error":"forbidden"},403
    conn.execute("DELETE FROM chats WHERE id=?",(chat_id,)); conn.commit(); conn.close(); return {"ok":True}

@app.post("/chat/<int:chat_id>/delete")
def chat_delete(chat_id):
    if not require_chat_user(): return redirect(url_for("chat_register"))
    require_csrf(); a=actor_id(); conn=db(); chat=conn.execute("SELECT * FROM chats WHERE id=?",(chat_id,)).fetchone()
    if chat and a in (chat["actor_a"],chat["actor_b"]):
        conn.execute("DELETE FROM chats WHERE id=?",(chat_id,)); conn.commit()
    conn.close(); return redirect(url_for("my_chats"))

@app.route("/invitation",methods=["GET","POST"])
def invitation():
    if request.method=="POST" and not require_chat_user():
        flash("ต้องสมัครบัญชีแชทก่อนจึงจะส่งคำขอที่เปิดห้องแชทได้","error")
        return redirect(url_for("chat_register"))
    if request.method=="POST":
        require_csrf(); name=request.form.get("name","").strip(); temple=request.form.get("temple",""); event=request.form.get("event_type",""); date=request.form.get("event_date",""); time=request.form.get("event_time",""); count=int(request.form.get("monk_count",1) or 1); details=request.form.get("details","").strip()
        if not name or temple not in TEMPLE_OPTIONS or event not in EVENT_TYPES or not date or not time: flash("กรอกข้อมูลให้ครบ","error")
        else:
            conn=db(); conn.execute("INSERT INTO invitations(contact_name,temple,event_type,event_date,event_time,monk_count,details,visitor_actor,created_at) VALUES(?,?,?,?,?,?,?,?,?)",(name,temple,event,date,time,count,details,actor_id(),now())); iid=conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]; conn.commit(); conn.close(); notify_admin("invitation","🙏 มีคำขอกิจนิมนต์ใหม่",f"{name} • {temple} • {event} • {date} {time} • {count} รูป",iid); flash("ส่งคำขอกิจนิมนต์แล้ว","success"); return redirect(url_for("invitation"))
    body="""<section class="section"><h1>🙏 ติดต่อกิจนิมนต์</h1><div class="card"><form class="form" method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><label>ชื่อผู้ติดต่อ</label><input name="name" required><label>วัด</label><select name="temple">{% for t in temples %}<option>{{t}}</option>{% endfor %}</select><label>งาน</label><select name="event_type">{% for x in event_types %}<option>{{x}}</option>{% endfor %}</select><label>วัน</label><input name="event_date" type="date" required><label>เวลา</label><input name="event_time" type="time" required><label>จำนวนพระ</label><input name="monk_count" type="number" min="1" value="1"><label>รายละเอียดเพิ่มเติม</label><textarea name="details"></textarea><button class="btn primary">ส่งคำขอ</button></form></div></section>"""
    return page("กิจนิมนต์",body,event_types=EVENT_TYPES)

@app.route("/temple/invitations",methods=["GET","POST"])
@temple_admin_required
def temple_invitations():
    conn=db(); me=conn.execute("SELECT * FROM temple_admins WHERE id=?",(session["user_id"],)).fetchone()
    if request.method=="POST":
        require_csrf(); iid=int(request.form.get("id")); action=request.form.get("action"); row=conn.execute("SELECT * FROM invitations WHERE id=? AND temple=? AND status='pending'",(iid,me["temple"])).fetchone()
        if row:
            if action=="accept":
                cid=create_chat("invitation","กิจนิมนต์ #"+str(iid),row["visitor_actor"],"temple:"+me["temple"],me["temple"],row["contact_name"])
                conn.execute("UPDATE invitations SET status='accepted',chat_id=? WHERE id=?",(cid,iid))
            else: conn.execute("UPDATE invitations SET status='rejected' WHERE id=?",(iid,))
            conn.commit()
        conn.close(); return redirect(url_for("temple_invitations"))
    rows=conn.execute("SELECT * FROM invitations WHERE temple=? ORDER BY id DESC",(me["temple"],)).fetchall(); conn.close()
    body="""<section class="section"><h1>🙏 กิจนิมนต์ของ {{me.temple}}</h1><div class="list">{% for x in rows %}<article class="item"><b>{{x.contact_name}}</b><p>{{x.event_type}} • {{x.event_date}} {{x.event_time}} • {{x.monk_count}} รูป</p><p>{{x.details}}</p><span class="badge">{{x.status}}</span>{% if x.chat_id %}<a class="btn" href="{{url_for('chat_room',chat_id=x.chat_id)}}">เปิดแชท</a>{% elif x.status=='pending' %}<form method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="id" value="{{x.id}}"><button class="btn good" name="action" value="accept">รับงาน</button><button class="btn bad" name="action" value="reject">ไม่รับ</button></form>{% endif %}</article>{% else %}<div class="empty">ไม่มีคำขอกิจนิมนต์</div>{% endfor %}</div></section>"""
    return page("กิจนิมนต์วัด",body,rows=rows,me=me)

@app.route("/admin/invitations",methods=["GET","POST"])
@admin_required
def admin_invitations():
    conn=db()
    if request.method=="POST":
        require_csrf(); rid=int(request.form.get("id")); action=request.form.get("action"); row=conn.execute("SELECT * FROM invitations WHERE id=?",(rid,)).fetchone()
        if row and action=="delete": conn.execute("DELETE FROM invitations WHERE id=?",(rid,))
        conn.commit(); conn.close(); return redirect(url_for("admin_invitations"))
    rows=conn.execute("SELECT * FROM invitations ORDER BY id DESC").fetchall(); conn.close()
    body="""<section class="section"><h1>🙏 คำขอกิจนิมนต์</h1><div class="list">{% for x in rows %}<article class="item"><b>{{x.contact_name}}</b> → {{x.temple}}<p>{{x.event_type}} • {{x.event_date}} {{x.event_time}} • {{x.monk_count}} รูป</p><p>{{x.details}}</p><span class="badge">{{x.status}}</span><form method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="id" value="{{x.id}}"><button class="btn bad" name="action" value="delete">ลบ</button></form></article>{% else %}<div class="empty">ไม่มีคำขอ</div>{% endfor %}</div></section>"""
    return page("กิจนิมนต์ Admin",body,rows=rows)

@app.route("/complaint",methods=["GET","POST"])
def complaint():
    if request.method=="POST" and not require_chat_user():
        flash("ต้องสมัครบัญชีแชทก่อนจึงจะส่งเรื่องที่เปิดห้องแชทได้","error")
        return redirect(url_for("chat_register"))
    if request.method=="POST":
        require_csrf(); name=request.form.get("name","").strip(); category=request.form.get("category",""); subject=request.form.get("subject","").strip(); details=request.form.get("details","").strip(); img=""
        try: img=save_upload(request.files.get("image"),"complaint")
        except ValueError as e: flash(str(e),"error")
        else:
            if name and category in ("ติดต่อทั่วไป","ติดต่อแจ้งพฤติกรรมพระสงฆ์") and subject and details:
                conn=db(); conn.execute("INSERT INTO complaints(name,category,subject,details,image_file,visitor_actor,created_at) VALUES(?,?,?,?,?,?,?)",(name,category,subject,details,img,actor_id(),now())); cid=conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]; conn.commit(); conn.close(); notify_admin("complaint","📩 มีเรื่องติดต่อ/ร้องเรียนใหม่",f"{name} • {category} • {subject}",cid); flash("ส่งเรื่องให้ Admin แล้ว","success"); return redirect(url_for("complaint"))
            flash("กรอกข้อมูลให้ครบ","error")
    body="""<section class="section"><h1>📩 ติดต่อร้องเรียน</h1><div class="card"><form class="form" method="post" enctype="multipart/form-data"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><label>ชื่อ</label><input name="name" required><label>ประเภท</label><select name="category"><option>ติดต่อทั่วไป</option><option>ติดต่อแจ้งพฤติกรรมพระสงฆ์</option></select><label>เรื่อง</label><input name="subject" required><label>รายละเอียด</label><textarea name="details" required></textarea><label>หลักฐานรูปภาพ</label><input type="file" name="image" accept="image/*"><button class="btn primary">ส่งเรื่อง</button></form></div></section>"""
    return page("ติดต่อร้องเรียน",body)

@app.route("/admin/complaints",methods=["GET","POST"])
@admin_required
def admin_complaints():
    conn=db()
    if request.method=="POST":
        require_csrf(); rid=int(request.form.get("id")); action=request.form.get("action"); row=conn.execute("SELECT * FROM complaints WHERE id=?",(rid,)).fetchone()
        if row:
            if action=="reject": conn.execute("UPDATE complaints SET status='rejected' WHERE id=?",(rid,))
            elif action=="accept":
                visitor=row["visitor_actor"] or ("visitor:"+secrets.token_urlsafe(8)); cid=create_chat("complaint","ติดต่อร้องเรียน #"+str(rid),visitor,"admin:"+ADMIN_USER,"",row["name"]); conn.execute("UPDATE complaints SET status='accepted',chat_id=? WHERE id=?",(cid,rid))
        conn.commit(); conn.close(); return redirect(url_for("admin_complaints"))
    rows=conn.execute("SELECT * FROM complaints ORDER BY id DESC").fetchall(); conn.close()
    body="""<section class="section"><h1>📩 ร้องเรียน/ติดต่อ</h1><div class="list">{% for x in rows %}<article class="item"><h3>{{x.name}} • {{x.category}}</h3><p><b>{{x.subject}}</b></p><p style="white-space:pre-wrap">{{x.details}}</p>{% if x.image_file %}<img class="preview" src="{{url_for('uploaded_file',filename=x.image_file)}}">{% endif %}<span class="badge">{{x.status}}</span>{% if x.chat_id %}<a class="btn" href="{{url_for('chat_room',chat_id=x.chat_id)}}">เปิดแชท</a>{% endif %}<form method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="id" value="{{x.id}}"><button class="btn good" name="action" value="accept">รับเรื่อง</button><button class="btn bad" name="action" value="reject">ไม่รับเรื่อง</button></form></article>{% else %}<div class="empty">ไม่มีเรื่อง</div>{% endfor %}</div></section>"""
    return page("คำร้องเรียน",body,rows=rows)

@app.route("/vinaya/login",methods=["GET","POST"])
def vinaya_login():
    if request.method=="POST":
        require_csrf(); u=request.form.get("username",""); p=request.form.get("password",""); conn=db(); r=conn.execute("SELECT * FROM vinaya_officers WHERE username=?",(u,)).fetchone(); conn.close()
        if r and r["enabled"] and check_password_hash(r["password_hash"],p):
            banned=security_status("vinaya",r["id"])
            if banned: return white_ban_page(banned)
            session.clear(); session["role"]="vinaya"; session["user_id"]=r["id"]; session["vinaya_id"]=r["id"]; session["csrf"]=secrets.token_urlsafe(24); return redirect(url_for("vinaya_home"))
        flash("บัญชีไม่มีสิทธิ์ใช้งานหรือข้อมูลไม่ถูกต้อง","error")
    body="""<section class="login"><div class="card"><h1>🛡️ พระวินยาธิการ</h1><form class="form" method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input name="username" placeholder="ชื่อ" required><input name="password" type="password" placeholder="รหัส" required><button class="btn primary">เข้าสู่ระบบ</button></form></div></section>"""
    return page("พระวินยาธิการ",body)

@app.get("/vinaya")
def vinaya_home():
    if session.get("role")!="vinaya": return redirect(url_for("vinaya_login"))
    conn=db(); r=conn.execute("SELECT enabled,content_delete_enabled FROM vinaya_officers WHERE id=?",(session.get("vinaya_id"),)).fetchone(); chats=conn.execute("SELECT * FROM chats WHERE closed=0 ORDER BY id DESC").fetchall(); audit_rows=conn.execute("SELECT * FROM audit_logs WHERE actor_role IN ('temple_admin','preceptor','employee') ORDER BY id DESC LIMIT 300").fetchall(); conn.close()
    if not r or not r["enabled"]: session.clear(); return redirect(url_for("vinaya_login"))
    body="""<section class="section"><h1>🛡️ ระบบตรวจสอบพระวินยาธิการ</h1><p>เมื่อ Admin อนุญาต จะเห็นแชทที่ยังไม่ปิด รวมถึงแชทส่วนตัวตามสิทธิ์ของระบบจำลอง</p>{% if r.content_delete_enabled %}<div class="card"><h2>📺 ตรวจเนื้อหาวิดีโอ/รูป</h2><p>Admin เปิดสิทธิ์ลบเนื้อหาให้บัญชีนี้แล้ว</p><a class="btn primary" href="{{url_for('social_moderation')}}">เปิดระบบตรวจเนื้อหา</a></div>{% else %}<div class="card"><p>สถานะเนื้อหา: ดูได้อย่างเดียว เพราะ Admin ยังไม่เปิดสิทธิ์ลบ</p></div>{% endif %}<div class="list">{% for x in chats %}<article class="item"><b>{{x.title}}</b> • {{x.created_at}} <a class="btn" href="{{url_for('chat_room',chat_id=x.id)}}">เปิดดู</a></article>{% else %}<div class="empty">ไม่มีแชท</div>{% endfor %}</div></section><section class="section"><h2>📋 ประวัติการใช้งานที่ได้รับอนุญาต</h2><p class="muted">แสดงเฉพาะการทำงานของเจ้าอาวาส/ผู้ดูแลวัด พระอุปัชฌาย์ และพนักงาน ไม่รวมการทำงานของ Admin</p><div class="list">{% for x in audit_rows %}<article class="item"><b>{{x.actor_name}}</b> • {{x.actor_role}}<p>{{x.action}} • {{x.endpoint}} • {{x.method}}</p><small>{{x.created_at}}</small></article>{% else %}<div class="empty">ยังไม่มีประวัติการใช้งาน</div>{% endfor %}</div></section>"""
    return page("ตรวจสอบพระวินยาธิการ",body,chats=chats,r=r,audit_rows=audit_rows)

@app.get("/vinaya/logout")
def vinaya_logout(): session.clear(); return redirect(url_for("home"))

@app.route("/admin/vinaya",methods=["GET","POST"])
@admin_required
def admin_vinaya():
    conn=db()
    if request.method=="POST":
        require_csrf(); action=request.form.get("action")
        if action=="add":
            try: conn.execute("INSERT INTO vinaya_officers(username,password_hash,royal_name,region,enabled,created_at) VALUES(?,?,?,?,0,?)",(request.form["username"],generate_password_hash(request.form["password"]),request.form["royal_name"],request.form["region"],now()))
            except sqlite3.IntegrityError: flash("ชื่อผู้ใช้นี้มีอยู่แล้ว","error")
        elif action=="toggle": conn.execute("UPDATE vinaya_officers SET enabled=? WHERE id=?",(int(request.form.get("enabled")=='1'),request.form["id"]))
        elif action=="toggle_content": conn.execute("UPDATE vinaya_officers SET content_delete_enabled=? WHERE id=?",(int(request.form.get("enabled")=='1'),request.form["id"]))
        elif action=="delete": conn.execute("DELETE FROM vinaya_officers WHERE id=?",(request.form["id"],))
        conn.commit(); conn.close(); return redirect(url_for("admin_vinaya"))
    rows=conn.execute("SELECT * FROM vinaya_officers ORDER BY id DESC").fetchall(); conn.close()
    body="""<section class="section"><h1>🛡️ ระบบพระวินยาธิการ</h1><div class="card"><form class="form" method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="add"><input name="username" placeholder="ชื่อ" required><input name="password" type="password" placeholder="รหัส" required><input name="royal_name" placeholder="ชื่อราชทินนาม" required><select name="region"><option>ภาค 1 มหานิกาย</option><option>ภาค 2 ธรรมยุต</option></select><button class="btn primary">เพิ่มบัญชี</button></form></div><div class="list">{% for x in rows %}<article class="item"><b>{{x.royal_name}}</b> • {{x.region}} • {{x.username}} • <span class="badge">{{'อนุญาตเข้าระบบ' if x.enabled else 'ไม่อนุญาตเข้าระบบ'}}</span> <span class="badge">{{'ลบเนื้อหาได้' if x.content_delete_enabled else 'ดูอย่างเดียว'}}</span><form method="post" style="display:inline"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="id" value="{{x.id}}"><input type="hidden" name="action" value="toggle"><input type="hidden" name="enabled" value="{{0 if x.enabled else 1}}"><button class="btn">{{'ไม่อนุญาต' if x.enabled else 'อนุญาต'}}</button></form><form method="post" style="display:inline"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="id" value="{{x.id}}"><input type="hidden" name="action" value="toggle_content"><input type="hidden" name="enabled" value="{{0 if x.content_delete_enabled else 1}}"><button class="btn warn">{{'ปิดสิทธิลบเนื้อหา' if x.content_delete_enabled else 'อนุญาตลบเนื้อหา'}}</button></form><a class="btn" href="{{url_for('social_moderation')}}">ตรวจวิดีโอ</a><form method="post" style="display:inline"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="id" value="{{x.id}}"><input type="hidden" name="action" value="delete"><button class="btn bad">ลบ</button></form></article>{% endfor %}</div></section>"""
    return page("จัดการพระวินยาธิการ",body,rows=rows)

@app.route("/admin/deaths",methods=["GET","POST"])
@admin_required
def admin_deaths():
    conn=db()
    if request.method=="POST":
        require_csrf(); rid=int(request.form.get("id")); action=request.form.get("action"); row=conn.execute("SELECT * FROM death_requests WHERE id=? AND status='pending'",(rid,)).fetchone()
        if row:
            if action=="approve": conn.execute("UPDATE death_requests SET status='approved',decided_at=? WHERE id=?",(now(),rid)); conn.execute("UPDATE temples SET status='มรณภาพ' WHERE id=?",(row["temple_id"],))
            else: conn.execute("UPDATE death_requests SET status='rejected',decided_at=? WHERE id=?",(now(),rid))
        conn.commit(); conn.close(); return redirect(url_for("admin_deaths"))
    rows=conn.execute("SELECT * FROM death_requests ORDER BY id DESC").fetchall(); conn.close()
    body="""<section class="section"><h1>🕯️ อนุมัติมรณภาพ</h1><div class="list">{% for x in rows %}<article class="item"><b>{{x.person_type or 'พระ'}} {{x.name}}</b> • {{x.temple}} • <span class="badge">{{x.status}}</span>{% if x.status=='pending' %}<form method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="id" value="{{x.id}}"><button class="btn good" name="action" value="approve">อนุมัติมรณภาพ</button><button class="btn bad" name="action" value="reject">ไม่อนุมัติ</button></form>{% endif %}</article>{% else %}<div class="empty">ไม่มีคำขอ</div>{% endfor %}</div></section>"""
    return page("อนุมัติมรณภาพ",body,rows=rows)

@app.route("/temple/death",methods=["GET","POST"])
@temple_admin_required
def temple_death():
    conn=db(); me=conn.execute("SELECT * FROM temple_admins WHERE id=?",(session["user_id"],)).fetchone()
    if request.method=="POST":
        require_csrf(); tid=int(request.form.get("temple_id")); row=conn.execute("SELECT * FROM temples WHERE id=? AND temple=? AND status!='มรณภาพ'",(tid,me["temple"])).fetchone()
        if row: conn.execute("INSERT INTO death_requests(temple_id,temple,name,created_at) VALUES(?,?,?,?)",(tid,me["temple"],row["name"],now())); conn.commit(); flash("ส่งคำขออนุมัติมรณภาพให้ Admin แล้ว","success")
        conn.close(); return redirect(url_for("temple_death"))
    rows=conn.execute("SELECT * FROM temples WHERE temple=? AND status!='มรณภาพ' ORDER BY id DESC",(me["temple"],)).fetchall(); conn.close()
    body="""<section class="section"><h1>🕯️ บันทึกมรณภาพ</h1><div class="list">{% for x in rows %}<article class="item"><b>{{x.person_type or 'พระ'}} {{x.name}}</b> • {{x.status}}<form method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="temple_id" value="{{x.id}}"><button class="btn bad">แจ้งมรณภาพ</button></form></article>{% endfor %}</div></section>"""
    return page("บันทึกมรณภาพ",body,rows=rows)

@app.route("/admin/documents",methods=["GET","POST"])
@admin_required
def admin_documents():
    conn=db()
    if request.method=="POST":
        require_csrf(); action=request.form.get("action"); did=int(request.form.get("id",0)); img=""
        if action=="add": img=save_upload(request.files.get("image"),"doc"); conn.execute("INSERT INTO documents(title,image_file,created_at) VALUES(?,?,?)",(request.form["title"],img,now()))
        elif action=="delete": conn.execute("DELETE FROM documents WHERE id=?",(did,))
        elif action=="edit":
            img=save_upload(request.files.get("image"),"doc")
            if img: conn.execute("UPDATE documents SET title=?,image_file=? WHERE id=?",(request.form["title"],img,did))
            else: conn.execute("UPDATE documents SET title=? WHERE id=?",(request.form["title"],did))
        conn.commit(); conn.close(); return redirect(url_for("admin_documents"))
    rows=conn.execute("SELECT * FROM documents ORDER BY id DESC").fetchall(); conn.close()
    body="""<section class="section"><h1>📜 เก็บเอกสารตราตั้ง</h1><div class="card"><form class="form" method="post" enctype="multipart/form-data"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="add"><label>หัวเรื่อง</label><input name="title" required><label>รูปเอกสาร</label><input type="file" name="image" accept="image/*" required><button class="btn primary">บันทึก</button></form></div><div class="list">{% for x in rows %}<article class="item"><b>{{x.title}}</b>{% if x.image_file %}<img class="preview" src="{{url_for('uploaded_file',filename=x.image_file)}}">{% endif %}<button class="btn" onclick="document.getElementById('d{{x.id}}').style.display='block'">แก้ไข</button><form method="post" style="display:inline"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="delete"><input type="hidden" name="id" value="{{x.id}}"><button class="btn bad">ลบ</button></form><div id="d{{x.id}}" class="card" style="display:none"><form class="form" method="post" enctype="multipart/form-data"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="edit"><input type="hidden" name="id" value="{{x.id}}"><input name="title" value="{{x.title}}"><input type="file" name="image" accept="image/*"><button class="btn primary">บันทึก</button></form></div></article>{% endfor %}</div></section>"""
    return page("เอกสารตราตั้ง",body,rows=rows)

@app.route("/announcements")
def announcements():
    conn=db(); general=conn.execute("SELECT * FROM system_announcements WHERE is_open=1 AND kind='general' ORDER BY id DESC").fetchall(); urgent=conn.execute("SELECT * FROM system_announcements WHERE is_open=1 AND kind='urgent' ORDER BY id DESC").fetchall(); conn.close()
    body="""<section class="section"><div class="sectionhead"><h1>📢 ประกาศ</h1><a class="btn" href="{{url_for('home')}}">🏯 หน้าแรก</a></div><div class="card"><h2>🚨 ประกาศเร่งด่วน</h2>{% for x in urgent %}<article class="item" style="border-left:5px solid #d00"><h3>{{x.title}}</h3><p style="white-space:pre-wrap">{{x.content}}</p>{% if x.image_file %}<img class="preview" src="{{url_for('uploaded_file',filename=x.image_file)}}">{% endif %}<small>{{x.created_at}}</small></article>{% else %}<div class="empty">ไม่มีประกาศเร่งด่วน</div>{% endfor %}</div><div class="card"><h2>📣 ประกาศทั่วไป</h2>{% for x in general %}<article class="item"><h3>{{x.title}}</h3><p style="white-space:pre-wrap">{{x.content}}</p>{% if x.image_file %}<img class="preview" src="{{url_for('uploaded_file',filename=x.image_file)}}">{% endif %}<small>{{x.created_at}}</small></article>{% else %}<div class="empty">ยังไม่มีประกาศทั่วไป</div>{% endfor %}</div></section>"""
    return page("ประกาศ",body,general=general,urgent=urgent)

@app.route("/admin/system-announcements",methods=["GET","POST"])
@admin_required
def admin_system_announcements():
    conn=db()
    if request.method=="POST":
        require_csrf(); action=request.form.get("action"); aid=int(request.form.get("id",0))
        if action=="add":
            kind=request.form.get("kind","general"); title=request.form.get("title","").strip(); content=request.form.get("content","").strip(); img=save_upload(request.files.get("image"),"system_announce") if request.files.get("image") else ""
            if kind not in ("general","urgent","maintenance"): kind="general"
            if not title or not content or (kind=="urgent" and not img): flash("กรุณากรอกข้อมูลให้ครบ และประกาศเร่งด่วนต้องมีรูปภาพ","error")
            else:
                store_kind="general" if kind=="maintenance" else kind
                conn.execute("INSERT INTO system_announcements(kind,title,content,image_file,created_at,is_open) VALUES(?,?,?,?,?,1)",(store_kind,title,content,img,now())); conn.commit(); flash("เพิ่มประกาศแล้ว","success")
        elif action=="toggle": conn.execute("UPDATE system_announcements SET is_open=? WHERE id=?",(int(request.form.get("open")=="1"),aid)); conn.commit()
        elif action=="delete": conn.execute("DELETE FROM system_announcements WHERE id=?",(aid,)); conn.commit()
        conn.close(); return redirect(url_for("admin_system_announcements"))
    rows=conn.execute("SELECT * FROM system_announcements ORDER BY id DESC").fetchall(); conn.close()
    body="""<section class="section"><div class="sectionhead"><h1>📢 ระบบประกาศข่าวสาร</h1></div><div class="card"><h2>➕ สร้างประกาศ</h2><form class="form" method="post" enctype="multipart/form-data"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="add"><select name="kind"><option value="general">ประกาศข่าวสารทั่วไป</option><option value="urgent">ประกาศเร่งด่วน</option><option value="maintenance">ประกาศปรับปรุง</option></select><input name="title" placeholder="หัวเรื่อง" required><textarea name="content" placeholder="เนื้อหาของประกาศ" required></textarea><label>รูปภาพประกาศ (ทั่วไปไม่บังคับ / เร่งด่วนต้องใส่)</label><input type="file" name="image" accept="image/*"><button class="btn primary">📢 ส่งประกาศ</button></form></div><div class="list">{% for x in rows %}<article class="item"><h3>{{ '🚨 ประกาศเร่งด่วน' if x.kind=='urgent' else '📣 ประกาศทั่วไป' }}</h3><b>{{x.title}}</b><p style="white-space:pre-wrap">{{x.content}}</p>{% if x.image_file %}<img class="preview" src="{{url_for('uploaded_file',filename=x.image_file)}}">{% endif %}<small>{{x.created_at}} • {{'เปิด' if x.is_open else 'ปิด'}}</small><div class="actions"><form method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="toggle"><input type="hidden" name="id" value="{{x.id}}"><input type="hidden" name="open" value="{{0 if x.is_open else 1}}"><button class="btn">{{'ปิดประกาศ' if x.is_open else 'เปิดประกาศ'}}</button></form><form method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="delete"><input type="hidden" name="id" value="{{x.id}}"><button class="btn bad">ลบ</button></form></div></article>{% else %}<div class="empty">ยังไม่มีประกาศ</div>{% endfor %}</div></section>"""
    return page("ระบบประกาศข่าวสาร",body,rows=rows)

@app.route("/admin/announcement",methods=["GET","POST"])
@admin_required
def admin_announcement():
    conn=db()
    if request.method=="POST":
        require_csrf(); action=request.form.get("action"); aid=int(request.form.get("id",0))
        if action=="add": img=save_upload(request.files.get("image"),"announce"); conn.execute("INSERT INTO announcements(image_file,is_open,created_at) VALUES(?,?,?)",(img,1,now()))
        elif action=="toggle": conn.execute("UPDATE announcements SET is_open=? WHERE id=?",(int(request.form.get("open")=='1'),aid))
        elif action=="delete": conn.execute("DELETE FROM announcements WHERE id=?",(aid,))
        conn.commit(); conn.close(); return redirect(url_for("admin_announcement"))
    rows=conn.execute("SELECT * FROM announcements ORDER BY id DESC").fetchall(); conn.close()
    body="""<section class="section"><h1>📣 ประกาศหรือโฆษณา</h1><div class="card"><form class="form" method="post" enctype="multipart/form-data"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="add"><input type="file" name="image" accept="image/*" required><button class="btn primary">เพิ่มประกาศ</button></form></div><div class="list">{% for x in rows %}<article class="item"><img class="preview" src="{{url_for('uploaded_file',filename=x.image_file)}}"><p>สถานะ: {{'เปิด' if x.is_open else 'ปิด'}}</p><form method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="toggle"><input type="hidden" name="id" value="{{x.id}}"><input type="hidden" name="open" value="{{0 if x.is_open else 1}}"><button class="btn">{{'ปิด' if x.is_open else 'เปิด'}}</button></form><form method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="delete"><input type="hidden" name="id" value="{{x.id}}"><button class="btn bad">ลบ</button></form></article>{% endfor %}</div></section>"""
    return page("ประกาศ",body,rows=rows)

@app.route("/blessing",methods=["GET","POST"])
def blessing():
    conn=db(); setting=conn.execute("SELECT * FROM blessings WHERE id=1").fetchone()
    if request.method=="POST":
        require_csrf(); name=request.form.get("name","").strip(); msg=request.form.get("message","").strip(); monk=conn.execute("SELECT id FROM temples WHERE name=? AND status!='มรณภาพ' LIMIT 1",(name,)).fetchone()
        if monk: flash("พระที่มีชื่ออยู่ในทะเบียนวัดไม่สามารถลงนามถวายพระพรในระบบนี้ได้","error")
        elif not setting["is_open"]: flash("ยังไม่เปิดให้ลงนาม","error")
        elif name and msg: conn.execute("INSERT INTO blessing_entries(name,message,created_at) VALUES(?,?,?)",(name,msg,now())); conn.commit(); flash("ลงนามเรียบร้อยแล้ว","success")
        conn.close(); return redirect(url_for("blessing"))
    conn.close()
    body="""<section class="section"><h1>🌼 ลงทะเบียนถวายพระพร</h1>{% if not setting.is_open %}<div class="card">ยังไม่เปิดให้ลงนามถวายพระพร</div>{% else %}<div class="card"><h2>{{setting.occasion}}</h2><form class="form" method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input name="name" placeholder="ชื่อ" required><label>ถ้อยความถวายพระพร</label><select name="message"><option>ขอพระองค์ทรงพระเจริญ</option><option>ขอพระองค์ทรงมีพระพลานามัยสมบูรณ์แข็งแรง</option><option>ขอพระองค์ทรงพระเกษมสำราญและทรงพระเจริญยิ่งยืนนาน</option></select><button class="btn primary">ลงนามถวายพระพร</button></form></div>{% endif %}</section>"""
    return page("ถวายพระพร",body,setting=setting)

@app.route("/admin/blessing",methods=["GET","POST"])
@admin_required
def admin_blessing():
    conn=db()
    if request.method=="POST":
        require_csrf(); action=request.form.get("action")
        if action=="toggle": conn.execute("UPDATE blessings SET is_open=?,occasion=? WHERE id=1",(int(request.form.get("open")=='1'),request.form.get("occasion","")))
        elif action=="delete": conn.execute("DELETE FROM blessing_entries WHERE id=?",(request.form.get("id"),))
        conn.commit(); conn.close(); return redirect(url_for("admin_blessing"))
    setting=conn.execute("SELECT * FROM blessings WHERE id=1").fetchone(); rows=conn.execute("SELECT * FROM blessing_entries ORDER BY id DESC").fetchall(); conn.close()
    body="""<section class="section"><h1>🌼 จัดการถวายพระพร</h1><div class="card"><form class="form" method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="toggle"><input name="occasion" value="{{setting.occasion}}" placeholder="วันสำคัญ/โอกาส"><input type="hidden" name="open" value="{{0 if setting.is_open else 1}}"><button class="btn primary">{{'ปิดการลงนาม' if setting.is_open else 'เปิดการลงนาม'}}</button></form></div><div class="list">{% for x in rows %}<article class="item"><b>{{x.name}}</b><p>{{x.message}}</p><form method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="delete"><input type="hidden" name="id" value="{{x.id}}"><button class="btn bad">ลบ</button></form></article>{% endfor %}</div></section>"""
    return page("จัดการถวายพระพร",body,setting=setting,rows=rows)

@app.route("/suggestion",methods=["GET","POST"])
def suggestion():
    if request.method=="POST":
        require_csrf(); name=request.form.get("name","").strip(); text=request.form.get("suggestion","").strip();
        if name and text:
            conn=db(); conn.execute("INSERT INTO suggestions(name,suggestion,created_at) VALUES(?,?,?)",(name,text,now())); conn.commit(); conn.close(); flash("ส่งข้อเสนอให้ Admin แล้ว","success"); return redirect(url_for("suggestion"))
    body="""<section class="section"><h1>💡 เสนอแนะ</h1><div class="card"><form class="form" method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input name="name" placeholder="ชื่อ" required><textarea name="suggestion" placeholder="สิ่งที่จะเสนอ" required></textarea><button class="btn primary">ส่งข้อเสนอ</button></form></div></section>"""
    return page("เสนอแนะ",body)

@app.route("/admin/suggestions",methods=["GET","POST"])
@admin_required
def admin_suggestions():
    conn=db()
    if request.method=="POST": require_csrf(); conn.execute("DELETE FROM suggestions WHERE id=?",(request.form.get("id"),)); conn.commit(); conn.close(); return redirect(url_for("admin_suggestions"))
    rows=conn.execute("SELECT * FROM suggestions ORDER BY id DESC").fetchall(); conn.close()
    body="""<section class="section"><h1>💡 คำขอเสนอ</h1><div class="list">{% for x in rows %}<article class="item"><b>{{x.name}}</b><p style="white-space:pre-wrap">{{x.suggestion}}</p><form method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="id" value="{{x.id}}"><button class="btn bad">ลบ</button></form></article>{% else %}<div class="empty">ไม่มีข้อเสนอ</div>{% endfor %}</div></section>"""
    return page("คำขอเสนอ",body,rows=rows)


# ============================================================
# ============================================================
# Short-video social system (simulation)
# ============================================================

SOCIAL_MAX_VIDEO_SECONDS = 180

SOCIAL_NAV = '''<div class="social-nav"><a href="{{url_for('social_home')}}" class="{{'active' if tab=='feed' else ''}}">🏠<span>วิดีโอ</span></a><a href="{{url_for('social_chats')}}" class="{{'active' if tab=='chat' else ''}}">💬<span>แชท</span></a><a href="{{url_for('social_profile')}}" class="{{'active' if tab=='profile' else ''}}">👤<span>โปรไฟล์</span></a></div>'''

def probe_video_duration(path):
    exe=shutil.which("ffprobe")
    if not exe: return 0.0
    try:
        out=subprocess.check_output([exe,"-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(path)],stderr=subprocess.DEVNULL,timeout=8).decode().strip()
        return float(out) if out else 0.0
    except Exception:
        return 0.0

def social_feed_rows(conn, viewer_id):
    posts=conn.execute("""SELECT p.*,u.username,u.display_name,u.avatar_file,
        (SELECT COUNT(*) FROM social_likes l WHERE l.post_id=p.id) like_count,
        (SELECT COUNT(*) FROM social_comments c WHERE c.post_id=p.id) comment_count,
        EXISTS(SELECT 1 FROM social_likes l2 WHERE l2.post_id=p.id AND l2.user_id=?) liked,
        EXISTS(SELECT 1 FROM social_follows f WHERE f.follower_id=? AND f.following_id=p.user_id) following
        FROM social_posts p JOIN social_users u ON u.id=p.user_id
        WHERE p.active=1 ORDER BY p.id DESC""",(viewer_id,viewer_id)).fetchall()
    result=[]
    for p in posts:
        imgs=conn.execute("SELECT image_file FROM social_post_images WHERE post_id=? ORDER BY sort_order,id",(p["id"],)).fetchall()
        d=dict(p); d["images"]=[x["image_file"] for x in imgs]; result.append(d)
    return result

@app.route("/social/register",methods=["GET","POST"])
def social_register():
    if request.method=="POST":
        require_csrf(); username=request.form.get("username","").strip(); password=request.form.get("password",""); display=request.form.get("display_name","").strip() or username
        if len(username)<2 or len(username)>32 or len(password)<4: flash("ชื่อ 2-32 ตัวอักษร และรหัสอย่างน้อย 4 ตัว","error")
        elif not request.files.get("avatar"): flash("กรุณาเลือกรูปโปรไฟล์","error")
        else:
            try: avatar=save_upload(request.files.get("avatar"),"socialavatar")
            except ValueError as e: avatar=""; flash(str(e),"error")
            if avatar:
                conn=db(); exists=conn.execute("SELECT id FROM social_users WHERE username=?",(username,)).fetchone()
                if exists: conn.close(); flash("ชื่อผู้ใช้นี้มีแล้ว","error")
                else:
                    cur=conn.execute("INSERT INTO social_users(username,password_hash,display_name,avatar_file,created_at,updated_at) VALUES(?,?,?,?,?,?)",(username,generate_password_hash(password),display,avatar,now(),now())); uid=cur.lastrowid
                    chat_id=sync_social_to_chat(conn,uid,username,display,avatar,""); conn.commit(); conn.close(); session["social_user_id"]=uid; session["chat_user_id"]=chat_id; flash("สมัครบัญชีวิดีโอแล้ว","success"); return redirect(url_for("social_home"))
    body='''<section class="login"><div class="card"><h1>📺 สมัครระบบวิดีโอ</h1><p>ต้องสมัครก่อนจึงจะดูคลิปและโพสต์ได้</p><form class="form" method="post" enctype="multipart/form-data"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><label>ชื่อผู้ใช้</label><input name="username" maxlength="32" required><label>รหัส</label><input name="password" type="password" minlength="4" required><label>ชื่อโปรไฟล์</label><input name="display_name" maxlength="50" required><label>รูปภาพโปรไฟล์</label><input name="avatar" type="file" accept="image/*" required><button class="btn primary">ตกลง / เริ่มดูวิดีโอ</button></form></div></section>'''
    return page("สมัครระบบวิดีโอ",body)

@app.route("/social/login",methods=["GET","POST"])
def social_login():
    if request.method=="POST":
        require_csrf(); conn=db(); row=conn.execute("SELECT * FROM social_users WHERE username=?",(request.form.get("username","").strip(),)).fetchone()
        if row and check_password_hash(row["password_hash"],request.form.get("password","")):
            chat_id=sync_social_to_chat(conn,row["id"],row["username"],row["display_name"],row["avatar_file"],row["bio"]); conn.commit(); conn.close(); session["social_user_id"]=row["id"]; session["chat_user_id"]=chat_id; return redirect(url_for("social_home"))
        conn.close(); flash("ชื่อผู้ใช้หรือรหัสไม่ถูกต้อง","error")
    body='''<section class="login"><div class="card"><h1>📺 เข้าสู่ระบบวิดีโอ</h1><form class="form" method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><label>ชื่อผู้ใช้</label><input name="username" required><label>รหัส</label><input name="password" type="password" required><button class="btn primary">เข้าสู่ระบบ</button></form><p><a href="{{url_for('social_register')}}">สมัครบัญชีใหม่</a></p></div></section>'''
    return page("เข้าสู่ระบบวิดีโอ",body)

@app.get("/social/logout")
def social_logout():
    session.pop("social_user_id",None); return redirect(url_for("home"))

@app.get("/social")
def social_home():
    if not require_social_user(): return redirect(url_for("social_register"))
    uid=session["social_user_id"]; conn=db(); posts=social_feed_rows(conn,uid); user=conn.execute("SELECT * FROM social_users WHERE id=?",(uid,)).fetchone(); conn.close()
    body='''<section class="social-shell"><div class="social-top"><b>📺 สมไอซ์ Video</b><div><a class="btn" href="{{url_for('home')}}">🏯</a><a class="btn" href="{{url_for('social_create')}}">＋</a></div></div><div class="social-feed" id="socialFeed">
    {% for p in posts %}<article class="social-post" id="post-{{p.id}}"><div class="social-media">{% if p.video_file %}<video src="{{url_for('uploaded_file',filename=p.video_file)}}" playsinline muted loop preload="metadata"></video>{% elif p.images %}<div class="social-carousel">{% for im in p.images %}<img src="{{url_for('uploaded_file',filename=im)}}">{% endfor %}</div>{% endif %}</div><div class="social-gradient"></div><div class="social-info"><a class="social-user" href="{{url_for('social_user',user_id=p.user_id)}}">{% if p.avatar_file %}<img src="{{url_for('uploaded_file',filename=p.avatar_file)}}">{% else %}👤{% endif %}<b>{{p.display_name or p.username}}</b></a><p>{{p.caption}}</p></div><div class="social-actions"><a href="{{url_for('social_user',user_id=p.user_id)}}">👤</a><button onclick="likePost({{p.id}},this)">{{'❤️' if p.liked else '🤍'}}<small>{{p.like_count}}</small></button><button onclick="commentPost({{p.id}})">💬<small>{{p.comment_count}}</small></button>{% if p.user_id!=user.id %}<a href="{{url_for('social_chat',user_id=p.user_id)}}">✉️</a>{% endif %}</div></article>{% else %}<div class="empty">ยังไม่มีคลิปหรือโพสต์ กด ＋ เพื่อโพสต์แรก</div>{% endfor %}</div>{{social_nav|safe}}</section>
    <script>const csrf={{csrf_token()|tojson}};const obs=new IntersectionObserver(es=>es.forEach(e=>{const v=e.target.querySelector('video');if(v){if(e.isIntersecting)v.play().catch(()=>{});else v.pause()}}),{threshold:.7});document.querySelectorAll('.social-post').forEach(x=>obs.observe(x));async function likePost(id,b){let r=await fetch('/social/post/'+id+'/like',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'_csrf='+encodeURIComponent(csrf)});if(r.ok){let d=await r.json();b.firstChild.textContent=d.liked?'❤️':'🤍';b.querySelector('small').textContent=d.count}}async function commentPost(id){let t=prompt('พิมพ์ความคิดเห็น');if(!t)return;let f=new URLSearchParams({_csrf:csrf,text:t});let r=await fetch('/social/post/'+id+'/comment',{method:'POST',body:f});if(r.ok)location.reload()}</script>'''
    return page("สมไอซ์ Video",body,posts=posts,user=user,social_nav=render_template_string(SOCIAL_NAV,tab="feed"))

@app.route("/social/create",methods=["GET","POST"])
def social_create():
    if not require_social_user(): return redirect(url_for("social_register"))
    uid=session["social_user_id"]
    if request.method=="POST":
        require_csrf(); caption=request.form.get("caption","").strip(); images=[x for x in request.files.getlist("images") if x and x.filename]
        if request.files.get("video") and request.files.get("video").filename: flash("ระบบโพสต์ใหม่รองรับเฉพาะรูปภาพ","error")
        elif not images: flash("กรุณาเลือกรูปภาพ","error")
        else:
            conn=db()
            try:
                cur=conn.execute("INSERT INTO social_posts(user_id,caption,created_at) VALUES(?,?,?)",(uid,caption,now())); pid=cur.lastrowid
                for i,f in enumerate(images):
                    name=save_upload(f,"socialimg"); conn.execute("INSERT INTO social_post_images(post_id,image_file,sort_order) VALUES(?,?,?)",(pid,name,i))
                conn.commit(); conn.close(); flash("โพสต์แล้ว","success"); return redirect(url_for("social_home"))
            except ValueError as e: conn.rollback(); conn.close(); flash(str(e),"error")
    body='''<section class="social-page"><div class="sectionhead"><h1>＋ ลงโพสต์</h1><a class="btn" href="{{url_for('social_home')}}">กลับวิดีโอ</a></div><div class="card"><form class="form" method="post" enctype="multipart/form-data" id="postForm"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><label>ข้อความ/ชื่อคลิป</label><textarea name="caption" maxlength="1000" placeholder="เขียนรายละเอียด..." required></textarea><label>รูปภาพ (ไม่จำกัดจำนวน)</label><input id="images" name="images" type="file" accept="image/*" multiple><p class="muted">โพสต์ใหม่รองรับรูปภาพหลายรูป ไม่จำกัดจำนวนต่อโพสต์</p><button class="btn primary">เผยแพร่</button></form></div></section><script>const ims=document.getElementById('images');</script>'''
    return page("ลงโพสต์",body)

@app.post("/social/post/<int:post_id>/like")
def social_like(post_id):
    if not require_social_user(): return {"error":"login_required"},401
    uid=session["social_user_id"]; conn=db(); exists=conn.execute("SELECT 1 FROM social_likes WHERE post_id=? AND user_id=?",(post_id,uid)).fetchone()
    if exists: conn.execute("DELETE FROM social_likes WHERE post_id=? AND user_id=?",(post_id,uid)); liked=False
    else: conn.execute("INSERT OR IGNORE INTO social_likes(post_id,user_id,created_at) VALUES(?,?,?)",(post_id,uid,now())); liked=True
    count=conn.execute("SELECT COUNT(*) n FROM social_likes WHERE post_id=?",(post_id,)).fetchone()["n"]; conn.commit(); conn.close(); return {"liked":liked,"count":count}

@app.post("/social/post/<int:post_id>/comment")
def social_comment(post_id):
    if not require_social_user(): return {"error":"login_required"},401
    textv=request.form.get("text","").strip()
    if not textv: return {"error":"empty"},400
    conn=db(); exists=conn.execute("SELECT id FROM social_posts WHERE id=? AND active=1",(post_id,)).fetchone()
    if not exists: conn.close(); return {"error":"not_found"},404
    conn.execute("INSERT INTO social_comments(post_id,user_id,text,created_at) VALUES(?,?,?,?)",(post_id,session["social_user_id"],textv,now())); conn.commit(); conn.close(); return {"ok":True}

@app.get("/social/user/<int:user_id>")
def social_user(user_id):
    if not require_social_user(): return redirect(url_for("social_register"))
    uid=session["social_user_id"]; conn=db(); user=conn.execute("SELECT * FROM social_users WHERE id=?",(user_id,)).fetchone()
    if not user: conn.close(); abort(404)
    following=bool(conn.execute("SELECT 1 FROM social_follows WHERE follower_id=? AND following_id=?",(uid,user_id)).fetchone()) if uid!=user_id else False
    followers=conn.execute("SELECT COUNT(*) n FROM social_follows WHERE following_id=?",(user_id,)).fetchone()["n"]; following_count=conn.execute("SELECT COUNT(*) n FROM social_follows WHERE follower_id=?",(user_id,)).fetchone()["n"]
    posts=social_feed_rows(conn,uid); posts=[p for p in posts if p["user_id"]==user_id]; conn.close()
    body='''<section class="social-page"><div class="sectionhead"><a class="btn" href="{{url_for('social_home')}}">←</a><h1>{{user.display_name}}</h1><a class="btn" href="{{url_for('social_profile')}}">👤</a></div><div class="card social-profile-card">{% if user.avatar_file %}<img class="avatar-large" src="{{url_for('uploaded_file',filename=user.avatar_file)}}">{% endif %}<h2>{{user.display_name}}</h2><p>@{{user.username}}</p><p>{{user.bio or 'ยังไม่มีรายละเอียด'}}</p><p>ผู้ติดตาม {{followers}} • กำลังติดตาม {{following_count}}</p>{% if user.id!=current_id %}<div class="actions"><form method="post" action="{{url_for('social_follow',user_id=user.id)}}"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><button class="btn {{'good' if following else 'primary'}}">{{'กำลังติดตาม' if following else 'ติดตาม'}}</button></form><a class="btn" href="{{url_for('social_chat',user_id=user.id)}}">💬 แชท</a></div>{% endif %}</div><div class="social-profile-grid">{% for p in posts %}<a href="{{url_for('social_home')}}#post-{{p.id}}" class="social-thumb">{% if p.video_file %}<video src="{{url_for('uploaded_file',filename=p.video_file)}}" muted></video>{% elif p.images %}<img src="{{url_for('uploaded_file',filename=p.images[0])}}">{% endif %}</a>{% else %}<div class="empty">ยังไม่มีโพสต์</div>{% endfor %}</div></section>'''
    return page("โปรไฟล์ผู้ใช้",body,user=user,following=following,followers=followers,following_count=following_count,current_id=uid)

@app.post("/social/user/<int:user_id>/follow")
def social_follow(user_id):
    if not require_social_user(): return redirect(url_for("social_register"))
    uid=session["social_user_id"]; conn=db()
    if uid!=user_id and conn.execute("SELECT id FROM social_users WHERE id=?",(user_id,)).fetchone():
        exists=conn.execute("SELECT id FROM social_follows WHERE follower_id=? AND following_id=?",(uid,user_id)).fetchone()
        if exists: conn.execute("DELETE FROM social_follows WHERE id=?",(exists["id"],))
        else: conn.execute("INSERT OR IGNORE INTO social_follows(follower_id,following_id,created_at) VALUES(?,?,?)",(uid,user_id,now()))
        conn.commit()
    conn.close(); return redirect(url_for("social_user",user_id=user_id))

@app.route("/social/profile",methods=["GET","POST"])
def social_profile():
    if not require_social_user(): return redirect(url_for("social_register"))
    uid=session["social_user_id"]; conn=db()
    if request.method=="POST":
        require_csrf(); username=request.form.get("username","").strip(); display=request.form.get("display_name","").strip() or username; bio=request.form.get("bio","").strip(); password=request.form.get("password","")
        row=conn.execute("SELECT * FROM social_users WHERE id=?",(uid,)).fetchone(); avatar=row["avatar_file"]
        if request.files.get("avatar"): avatar=save_upload(request.files["avatar"],"socialavatar")
        conflict=conn.execute("SELECT id FROM social_users WHERE username=? AND id!=?",(username,uid)).fetchone()
        if conflict: flash("ชื่อผู้ใช้นี้มีคนใช้แล้ว","error")
        elif len(username)<2 or len(username)>32: flash("ชื่อผู้ใช้ต้องมี 2-32 ตัวอักษร","error")
        else:
            if password: conn.execute("UPDATE social_users SET username=?,display_name=?,bio=?,avatar_file=?,password_hash=?,updated_at=? WHERE id=?",(username,display,bio,avatar,generate_password_hash(password),now(),uid))
            else: conn.execute("UPDATE social_users SET username=?,display_name=?,bio=?,avatar_file=?,updated_at=? WHERE id=?",(username,display,bio,avatar,now(),uid))
            chat_id=sync_social_to_chat(conn,uid,username,display,avatar,bio); conn.commit(); session["chat_user_id"]=chat_id; flash("บันทึกโปรไฟล์แล้ว","success")
    row=conn.execute("SELECT * FROM social_users WHERE id=?",(uid,)).fetchone(); followers=conn.execute("SELECT COUNT(*) n FROM social_follows WHERE following_id=?",(uid,)).fetchone()["n"]; following=conn.execute("SELECT COUNT(*) n FROM social_follows WHERE follower_id=?",(uid,)).fetchone()["n"]; posts=social_feed_rows(conn,uid); posts=[p for p in posts if p["user_id"]==uid]; conn.close()
    body='''<section class="social-page"><div class="sectionhead"><h1>👤 โปรไฟล์</h1><a class="btn" href="{{url_for('social_home')}}">🏠 วิดีโอ</a></div><div class="card"><form class="form" method="post" enctype="multipart/form-data"><input type="hidden" name="_csrf" value="{{csrf_token()}}">{% if row.avatar_file %}<img class="avatar-large" src="{{url_for('uploaded_file',filename=row.avatar_file)}}">{% endif %}<label>ชื่อผู้ใช้</label><input name="username" value="{{row.username}}" required><label>ชื่อโปรไฟล์</label><input name="display_name" value="{{row.display_name}}" required><label>รายละเอียด</label><textarea name="bio">{{row.bio}}</textarea><label>เปลี่ยนรหัส</label><input name="password" type="password" placeholder="เว้นว่างถ้าไม่เปลี่ยน"><label>เปลี่ยนรูป</label><input name="avatar" type="file" accept="image/*"><button class="btn primary">บันทึก</button></form></div><div class="card"><b>ผู้ติดตาม {{followers}} • กำลังติดตาม {{following}}</b><div class="actions" style="margin-top:10px"><a class="btn" href="{{url_for('social_create')}}">＋ ลงคลิป/รูป</a><a class="btn" href="{{url_for('social_chats')}}">💬 แชท</a><a class="btn bad" href="{{url_for('social_logout')}}">ออกจากระบบ</a></div></div><div class="social-profile-grid">{% for p in posts %}<div class="social-thumb">{% if p.video_file %}<video src="{{url_for('uploaded_file',filename=p.video_file)}}" controls></video>{% elif p.images %}<img src="{{url_for('uploaded_file',filename=p.images[0])}}">{% endif %}</div>{% endfor %}</div>{{social_nav|safe}}</section>'''
    return page("โปรไฟล์วิดีโอ",body,row=row,followers=followers,following=following,posts=posts,tab="profile",social_nav=render_template_string(SOCIAL_NAV,tab="profile"))

@app.get("/social/chats")
def social_chats():
    if not require_social_user(): return redirect(url_for("social_register"))
    uid=session["social_user_id"]; conn=db(); following=conn.execute("SELECT u.* FROM social_follows f JOIN social_users u ON u.id=f.following_id WHERE f.follower_id=? ORDER BY u.display_name,u.username",(uid,)).fetchall(); followers=conn.execute("SELECT u.* FROM social_follows f JOIN social_users u ON u.id=f.follower_id WHERE f.following_id=? ORDER BY u.display_name,u.username",(uid,)).fetchall(); conn.close()
    people=[]; seen=set()
    for r in list(following)+list(followers):
        if r["id"]!=uid and r["id"] not in seen: people.append(r); seen.add(r["id"])
    body='''<section class="social-page"><div class="sectionhead"><h1>💬 แชท</h1><a class="btn" href="{{url_for('social_home')}}">🏠</a></div><div class="card"><p>เลือกคนที่คุณติดตามหรือคนที่ติดตามคุณเพื่อเริ่มแชท</p><div class="list">{% for p in people %}<article class="item"><b>{{p.display_name}}</b><small> @{{p.username}}</small><a class="btn primary" href="{{url_for('social_chat',user_id=p.id)}}">แชท</a></article>{% else %}<div class="empty">ยังไม่มีคนสำหรับแชท ลองติดตามคนอื่นก่อน</div>{% endfor %}</div></div>{{social_nav|safe}}</section>'''
    return page("แชทวิดีโอ",body,people=people,tab="chat",social_nav=render_template_string(SOCIAL_NAV,tab="chat"))

@app.get("/social/chat/<int:user_id>")
def social_chat(user_id):
    if not require_social_user(): return redirect(url_for("social_register"))
    uid=session["social_user_id"]; conn=db(); me=conn.execute("SELECT * FROM social_users WHERE id=?",(uid,)).fetchone(); other=conn.execute("SELECT * FROM social_users WHERE id=?",(user_id,)).fetchone()
    if not other or uid==user_id: conn.close(); abort(404)
    a=sync_social_to_chat(conn,uid,me["username"],me["display_name"],me["avatar_file"],me["bio"]); b=sync_social_to_chat(conn,user_id,other["username"],other["display_name"],other["avatar_file"],other["bio"]); conn.commit(); conn.close()
    session["chat_user_id"]=a; cid=create_chat("social_private","แชทกับ "+(other["display_name"] or other["username"]),"chatuser:"+str(a),"chatuser:"+str(b),"",me["display_name"])
    return redirect(url_for("chat_room",chat_id=cid))

@app.route("/social/moderation",methods=["GET","POST"])
def social_moderation():
    if session.get("role")=="admin": allowed=True
    elif session.get("role")=="vinaya":
        conn=db(); r=conn.execute("SELECT enabled,content_delete_enabled FROM vinaya_officers WHERE id=?",(session.get("vinaya_id"),)).fetchone(); conn.close(); allowed=bool(r and r["enabled"] and r["content_delete_enabled"])
    else: allowed=False
    if not allowed: return redirect(url_for("social_register"))
    conn=db()
    if request.method=="POST":
        require_csrf(); action=request.form.get("action"); pid=int(request.form.get("id",0))
        if action=="delete_post": conn.execute("DELETE FROM social_posts WHERE id=?",(pid,)); conn.commit(); flash("ลบโพสต์แล้ว","success")
        return redirect(url_for("social_moderation"))
    posts=conn.execute("SELECT p.*,u.username,u.display_name FROM social_posts p JOIN social_users u ON u.id=p.user_id ORDER BY p.id DESC").fetchall(); images_by_post={}
    for p in posts: images_by_post[p["id"]]=[x["image_file"] for x in conn.execute("SELECT image_file FROM social_post_images WHERE post_id=? ORDER BY sort_order,id",(p["id"],)).fetchall()]
    conn.close()
    body='''<section class="section"><h1>🛡️ ตรวจสอบเนื้อหาวิดีโอ</h1><p>สิทธิ์นี้ขึ้นอยู่กับ Admin ที่อนุญาตเท่านั้น</p><div class="list">{% for p in posts %}<article class="item"><b>{{p.display_name}}</b> • {{p.created_at}}<p>{{p.caption}}</p>{% if p.video_file %}<video src="{{url_for('uploaded_file',filename=p.video_file)}}" controls style="max-width:300px"></video>{% endif %}{% set ims = [] %}{% if p.id %}{% endif %}<div>{% for im in images_by_post.get(p.id, []) %}<img class="preview" src="{{url_for('uploaded_file',filename=im)}}">{% endfor %}</div><form method="post" style="margin-top:8px" onsubmit="return confirm('ลบโพสต์นี้หรือไม่?')"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="delete_post"><input type="hidden" name="id" value="{{p.id}}"><button class="btn bad">ลบโพสต์</button></form></article>{% else %}<div class="empty">ไม่มีโพสต์</div>{% endfor %}</div></section>'''
    return page("ตรวจสอบวิดีโอ",body,posts=posts,images_by_post=images_by_post)

@app.route("/admin/social",methods=["GET","POST"])
@admin_required
def admin_social():
    conn=db()
    if request.method=="POST":
        require_csrf(); action=request.form.get("action"); uid=int(request.form.get("id",0)); pid=int(request.form.get("post_id",0))
        if action=="delete_user": conn.execute("DELETE FROM social_users WHERE id=?",(uid,)); conn.commit(); flash("ลบบัญชีผู้ใช้ระบบวิดีโอแล้ว","success")
        elif action=="delete_post": conn.execute("DELETE FROM social_posts WHERE id=?",(pid,)); conn.commit(); flash("ลบโพสต์แล้ว","success")
        return redirect(url_for("admin_social"))
    users=conn.execute("SELECT u.*,COUNT(p.id) post_count FROM social_users u LEFT JOIN social_posts p ON p.user_id=u.id GROUP BY u.id ORDER BY u.id DESC").fetchall(); posts=conn.execute("SELECT p.*,u.username,u.display_name FROM social_posts p JOIN social_users u ON u.id=p.user_id ORDER BY p.id DESC LIMIT 100").fetchall(); conn.close()
    body='''<section class="section"><div class="sectionhead"><h1>📺 จัดการระบบวิดีโอ</h1><a class="btn" href="{{url_for('admin')}}">← หลังบ้าน</a></div><div class="card"><h2>บัญชีผู้ใช้</h2><div class="list">{% for u in users %}<article class="item"><b>{{u.display_name}}</b> • @{{u.username}} • {{u.post_count}} โพสต์<form method="post" style="display:inline" onsubmit="return confirm('ลบบัญชีและโพสต์ทั้งหมดของผู้ใช้นี้หรือไม่?')"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="delete_user"><input type="hidden" name="id" value="{{u.id}}"><button class="btn bad">ลบบัญชี</button></form></article>{% else %}<div class="empty">ยังไม่มีผู้ใช้</div>{% endfor %}</div></div><div class="card"><h2>โพสต์ทั้งหมด</h2><div class="list">{% for p in posts %}<article class="item"><b>{{p.display_name}}</b> • {{p.created_at}}<p>{{p.caption}}</p><form method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="delete_post"><input type="hidden" name="post_id" value="{{p.id}}"><button class="btn bad">ลบโพสต์</button></form></article>{% endfor %}</div></div></section>'''
    return page("จัดการระบบวิดีโอ",body,users=users,posts=posts)


# Chat / Marketplace simulation
# ============================================================

def store_user_row():
    uid=session.get("store_user_id")
    if not uid: return None
    conn=db(); row=conn.execute("SELECT * FROM store_users WHERE id=?",(uid,)).fetchone(); conn.close(); return row

def require_store_user():
    return bool(store_user_row())

def store_ranked_products(conn, where="", params=()):
    return conn.execute("SELECT p.*,u.username seller,COALESCE(COUNT(r.id),0) review_count,COALESCE(AVG(r.rating),0) avg_rating FROM store_products p JOIN store_users u ON u.id=p.seller_id LEFT JOIN store_reviews r ON r.product_id=p.id WHERE p.active=1 "+where+" GROUP BY p.id ORDER BY review_count DESC,p.id DESC",params).fetchall()

@app.route("/store/register",methods=["GET","POST"])
def store_register():
    if request.method=="POST":
        require_csrf(); username=request.form.get("username","").strip(); password=request.form.get("password","")
        if len(username)<2 or len(username)>32 or len(password)<4: flash("ชื่อผู้ใช้ 2-32 ตัวอักษร และรหัสผู้ใช้อย่างน้อย 4 ตัว","error")
        else:
            conn=db(); exists=conn.execute("SELECT id FROM store_users WHERE username=?",(username,)).fetchone()
            if exists: flash("ชื่อผู้ใช้นี้มีแล้ว ให้เข้าสู่ระบบแทน","error")
            else:
                cur=conn.execute("INSERT INTO store_users(username,password_hash,display_name,created_at,updated_at) VALUES(?,?,?,?,?)",(username,generate_password_hash(password),username,now(),now())); uid=cur.lastrowid; conn.commit(); conn.close(); session["store_user_id"]=uid; flash("สมัครร้านค้าออนไลน์แล้ว","success"); return redirect(url_for("store_home"))
            conn.close()
    body="""<section class="login"><div class="card"><h1>🛍️ สมัครบัญชีร้านค้า</h1><form class="form" method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><label>ชื่อผู้ใช้</label><input name="username" required><label>รหัสผู้ใช้</label><input type="password" name="password" required><button class="btn primary">สมัคร</button></form><p><a href="{{url_for('store_login')}}">มีบัญชีแล้ว → เข้าสู่ระบบ</a></p></div></section>"""
    return page("สมัครร้านค้า",body)

@app.route("/store/login",methods=["GET","POST"])
def store_login():
    if request.method=="POST":
        require_csrf(); conn=db(); row=conn.execute("SELECT * FROM store_users WHERE username=?",(request.form.get("username","").strip(),)).fetchone(); conn.close()
        if row and check_password_hash(row["password_hash"],request.form.get("password","")):
            session["store_user_id"]=row["id"]; flash("เข้าสู่ร้านค้าแล้ว","success"); return redirect(url_for("store_home"))
        flash("ชื่อผู้ใช้หรือรหัสไม่ถูกต้อง","error")
    body="""<section class="login"><div class="card"><h1>🛍️ เข้าสู่ร้านค้า</h1><form class="form" method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><label>ชื่อผู้ใช้</label><input name="username" required><label>รหัสผู้ใช้</label><input type="password" name="password" required><button class="btn primary">เข้าสู่ระบบ</button></form><p><a href="{{url_for('store_register')}}">สมัครบัญชีใหม่</a></p></div></section>"""
    return page("เข้าสู่ร้านค้า",body)

@app.get("/store/logout")
def store_logout():
    session.pop("store_user_id",None); return redirect(url_for("store_home"))

@app.get("/store")
def store_home():
    conn=db(); products=store_ranked_products(conn)[:30]; conn.close()
    body="""<section class="section"><div class="sectionhead"><div><h1>🛍️ ร้านค้าออนไลน์</h1><p>สินค้าดิจิทัลในระบบจำลอง</p></div><a class="btn" href="{{url_for('home')}}">🏯 หน้าวัด</a></div><form class="card form" method="get" action="{{url_for('store_search')}}"><input name="q" placeholder="ค้นหาสินค้า..."><button class="btn primary">🔎 ค้นหา</button></form><div class="grid">{% for x in products %}<a class="card cardsmall" href="{{url_for('store_product',product_id=x.id)}}">{% if x.image_file %}<img class="preview" src="{{url_for('uploaded_file',filename=x.image_file)}}">{% endif %}<h3>{{x.name}}</h3><p>{{x.price}} บาท • ⭐ {{x.review_count}} รีวิว</p><small>ร้าน {{x.seller}}</small></a>{% else %}<div class="empty">ยังไม่มีสินค้า</div>{% endfor %}</div><div class="card" style="margin-top:18px"><div class="actions"><a class="btn" href="{{url_for('store_profile')}}">👤 Profile</a>{% if user %}<a class="btn" href="{{url_for('store_seller')}}">🏪 สมัครร้านค้า/จัดการสินค้า</a><a class="btn" href="{{url_for('store_history')}}">🧾 ประวัติการซื้อ</a><a class="btn" href="{{url_for('store_logout')}}">ออกจากระบบ</a>{% else %}<a class="btn primary" href="{{url_for('store_login')}}">เข้าสู่ระบบ</a>{% endif %}</div></div></section>"""
    return page("ร้านค้า",body,products=products,user=store_user_row())

@app.get("/store/search")
def store_search():
    q=request.args.get("q","").strip(); conn=db();
    if q:
        products=store_ranked_products(conn,"AND (p.name LIKE ? OR p.description LIKE ?)",(f"%{q}%",f"%{q}%"))
    else: products=store_ranked_products(conn)
    conn.close()
    body="""<section class="section"><div class="sectionhead"><h1>🔎 ค้นหาสินค้า</h1><a class="btn" href="{{url_for('store_home')}}">🏯 หน้าวัด</a></div><form class="card form" method="get"><input name="q" value="{{q}}" placeholder="ค้นหา..."><button class="btn primary">ค้นหา</button></form><div class="grid">{% for x in products %}<a class="card cardsmall" href="{{url_for('store_product',product_id=x.id)}}">{% if x.image_file %}<img class="preview" src="{{url_for('uploaded_file',filename=x.image_file)}}">{% endif %}<h3>{{x.name}}</h3><p>{{x.price}} บาท • ⭐ {{x.review_count}} รีวิว</p></a>{% else %}<div class="empty">ไม่พบสินค้า</div>{% endfor %}</div></section>"""
    return page("ค้นหาร้านค้า",body,products=products,q=q)

@app.route("/store/profile",methods=["GET","POST"])
def store_profile():
    if not require_store_user(): return redirect(url_for("store_login"))
    uid=session["store_user_id"]; conn=db();
    if request.method=="POST":
        require_csrf(); display=request.form.get("display_name","").strip() or "ผู้ใช้"; bio=request.form.get("bio","").strip(); avatar=save_upload(request.files.get("avatar"),"storeavatar") if request.files.get("avatar") else ""
        if avatar: conn.execute("UPDATE store_users SET display_name=?,bio=?,avatar_file=?,updated_at=? WHERE id=?",(display,bio,avatar,now(),uid))
        else: conn.execute("UPDATE store_users SET display_name=?,bio=?,updated_at=? WHERE id=?",(display,bio,now(),uid))
        conn.commit()
    row=conn.execute("SELECT * FROM store_users WHERE id=?",(uid,)).fetchone(); conn.close()
    body="""<section class="section"><div class="sectionhead"><h1>👤 Profile ร้านค้า</h1><a class="btn" href="{{url_for('store_home')}}">🏯 หน้าวัด</a></div><div class="card"><form class="form" method="post" enctype="multipart/form-data"><input type="hidden" name="_csrf" value="{{csrf_token()}}">{% if row.avatar_file %}<img class="avatar-large" src="{{url_for('uploaded_file',filename=row.avatar_file)}}">{% else %}<div class="avatar-large avatar-empty">👤</div>{% endif %}<label>ชื่อผู้ใช้</label><input value="{{row.username}}" disabled><label>ชื่อที่แสดง</label><input name="display_name" value="{{row.display_name}}"><label>รายละเอียด</label><textarea name="bio">{{row.bio}}</textarea><label>รูปโปรไฟล์</label><input type="file" name="avatar" accept="image/*"><button class="btn primary">บันทึก</button></form></div></section>"""
    return page("Profile ร้านค้า",body,row=row)

@app.route("/store/seller",methods=["GET","POST"])
def store_seller():
    if not require_store_user(): return redirect(url_for("store_login"))
    uid=session["store_user_id"]; conn=db(); user=conn.execute("SELECT * FROM store_users WHERE id=?",(uid,)).fetchone()
    if request.method=="POST":
        require_csrf(); action=request.form.get("action")
        if action=="apply": conn.execute("UPDATE store_users SET is_seller=1,updated_at=? WHERE id=?",(now(),uid)); conn.commit(); flash("สมัครร้านค้าแล้ว","success")
        elif action=="add" and user["is_seller"]:
            try: price=max(0,int(request.form.get("price",0)))
            except ValueError: price=0
            image=save_upload(request.files.get("image"),"product") if request.files.get("image") else ""
            name=request.form.get("name","").strip(); desc=request.form.get("description","").strip(); digital=request.form.get("digital_content","")
            if not name or not digital: flash("ต้องใส่ชื่อสินค้าและเนื้อหาดิจิทัล/รหัสที่จะส่งให้ผู้ซื้อ","error")
            else: conn.execute("INSERT INTO store_products(seller_id,name,description,image_file,price,digital_content,created_at) VALUES(?,?,?,?,?,?,?)",(uid,name,desc,image,price,digital,now())); conn.commit(); flash("เพิ่มสินค้าแล้ว","success")
        elif action=="delete":
            pid=int(request.form.get("id",0)); row=conn.execute("SELECT id FROM store_products WHERE id=? AND seller_id=?",(pid,uid)).fetchone()
            if row:
                conn.execute("DELETE FROM store_products WHERE id=?",(pid,)); conn.commit(); flash("ลบสินค้าแล้ว","success")
        user=conn.execute("SELECT * FROM store_users WHERE id=?",(uid,)).fetchone()
    products=conn.execute("SELECT p.*,COUNT(r.id) review_count FROM store_products p LEFT JOIN store_reviews r ON r.product_id=p.id WHERE p.seller_id=? GROUP BY p.id ORDER BY p.id DESC",(uid,)).fetchall(); conn.close()
    body="""<section class="section"><div class="sectionhead"><h1>🏪 ร้านของฉัน</h1><a class="btn" href="{{url_for('store_home')}}">🏯 หน้าวัด</a></div>{% if not user.is_seller %}<div class="card"><h2>สมัครร้านค้า</h2><p>สมัครเพื่อเพิ่มสินค้าดิจิทัลของคุณ</p><form method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="apply"><button class="btn primary">สมัครร้านค้า</button></form></div>{% else %}<div class="card"><h2>เพิ่มสินค้า</h2><form class="form" method="post" enctype="multipart/form-data"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="add"><label>ชื่อสินค้า</label><input name="name" required><label>รายละเอียด</label><textarea name="description" required></textarea><label>รูปสินค้า</label><input type="file" name="image" accept="image/*"><label>ราคา (บาท - ระบบจำลอง)</label><input type="number" name="price" min="0" value="0"><label>เนื้อหาดิจิทัล/รหัสที่จะส่งหลังซื้อ</label><textarea name="digital_content" required></textarea><button class="btn primary">ลงสินค้า</button></form></div>{% endif %}<div class="list">{% for x in products %}<article class="item"><b>{{x.name}}</b> • {{x.price}} บาท • ⭐ {{x.review_count}} รีวิว<form method="post" style="display:inline" onsubmit="return confirm('ลบสินค้านี้?')"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="delete"><input type="hidden" name="id" value="{{x.id}}"><button class="btn bad">ลบ</button></form></article>{% else %}<div class="empty">ยังไม่มีสินค้า</div>{% endfor %}</div></section>"""
    return page("ร้านของฉัน",body,user=user,products=products)

@app.route("/store/product/<int:product_id>",methods=["GET","POST"])
def store_product(product_id):
    conn=db(); product=conn.execute("SELECT p.*,u.username seller, u.display_name seller_name FROM store_products p JOIN store_users u ON u.id=p.seller_id WHERE p.id=? AND p.active=1",(product_id,)).fetchone()
    if not product: conn.close(); abort(404)
    if request.method=="POST":
        if not require_store_user(): conn.close(); return redirect(url_for("store_login"))
        require_csrf(); uid=session["store_user_id"]; action=request.form.get("action")
        if action=="buy":
            if uid==product["seller_id"]: flash("เจ้าของร้านไม่สามารถซื้อสินค้าตัวเองได้","error")
            else:
                conn.execute("INSERT INTO store_purchases(buyer_id,product_id,seller_id,price,digital_content,created_at) VALUES(?,?,?,?,?,?)",(uid,product_id,product["seller_id"],product["price"],product["digital_content"],now())); conn.commit(); flash("ซื้อสินค้าจำลองแล้ว ดูรหัสได้ที่ประวัติการซื้อ","success")
        elif action=="review":
            bought=conn.execute("SELECT id FROM store_purchases WHERE buyer_id=? AND product_id=? LIMIT 1",(uid,product_id)).fetchone()
            if not bought: flash("ต้องซื้อสินค้าก่อนจึงรีวิวได้","error")
            else:
                try: rating=max(1,min(5,int(request.form.get("rating",5))))
                except ValueError: rating=5
                img=save_upload(request.files.get("image"),"review") if request.files.get("image") else ""
                textv=request.form.get("review"," ").strip()
                conn.execute("INSERT INTO store_reviews(product_id,buyer_id,rating,text,image_file,created_at) VALUES(?,?,?,?,?,?) ON CONFLICT(product_id,buyer_id) DO UPDATE SET rating=excluded.rating,text=excluded.text,image_file=excluded.image_file,created_at=excluded.created_at",(product_id,uid,rating,textv,img,now())); conn.commit(); flash("บันทึกรีวิวแล้ว","success")
    reviews=conn.execute("SELECT r.*,u.username,u.display_name FROM store_reviews r JOIN store_users u ON u.id=r.buyer_id WHERE r.product_id=? ORDER BY r.id DESC",(product_id,)).fetchall(); bought=bool(session.get("store_user_id") and conn.execute("SELECT 1 FROM store_purchases WHERE buyer_id=? AND product_id=? LIMIT 1",(session["store_user_id"],product_id)).fetchone())
    conn.close()
    body="""<section class="section"><div class="sectionhead"><h1>🛍️ {{product.name}}</h1><a class="btn" href="{{url_for('store_home')}}">🏯 หน้าวัด</a></div><div class="card">{% if product.image_file %}<img class="preview" src="{{url_for('uploaded_file',filename=product.image_file)}}">{% endif %}<h2>{{product.name}}</h2><p style="white-space:pre-wrap">{{product.description}}</p><h3>{{product.price}} บาท</h3><p>ร้าน: {{product.seller_name or product.seller}}</p>{% if user %}<form method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="buy"><button class="btn primary">ซื้อสินค้า (จำลอง)</button></form>{% else %}<a class="btn primary" href="{{url_for('store_login')}}">เข้าสู่ระบบเพื่อซื้อ</a>{% endif %}</div>{% if bought %}<div class="card"><h2>⭐ รีวิวสินค้า</h2><form class="form" method="post" enctype="multipart/form-data"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="review"><label>คะแนน 1-5</label><select name="rating"><option>5</option><option>4</option><option>3</option><option>2</option><option>1</option></select><textarea name="review" placeholder="ข้อความรีวิว"></textarea><input type="file" name="image" accept="image/*"><button class="btn primary">ส่งรีวิว</button></form></div>{% endif %}<div class="list"><h2>รีวิวทั้งหมด ({{reviews|length}})</h2>{% for x in reviews %}<article class="item"><b>⭐ {{x.rating}} • {{x.display_name or x.username}}</b><p>{{x.text}}</p>{% if x.image_file %}<img class="preview" src="{{url_for('uploaded_file',filename=x.image_file)}}">{% endif %}</article>{% else %}<div class="empty">ยังไม่มีรีวิว</div>{% endfor %}</div></section>"""
    return page("สินค้า",body,product=product,reviews=reviews,bought=bought,user=store_user_row())

@app.get("/store/history")
def store_history():
    if not require_store_user(): return redirect(url_for("store_login"))
    uid=session["store_user_id"]; conn=db(); rows=conn.execute("SELECT p.*,sp.created_at bought_at,sp.digital_content,sp.price FROM store_purchases sp JOIN store_products p ON p.id=sp.product_id WHERE sp.buyer_id=? ORDER BY sp.id DESC",(uid,)).fetchall(); conn.close()
    body="""<section class="section"><div class="sectionhead"><h1>🧾 ประวัติการซื้อ</h1><a class="btn" href="{{url_for('store_home')}}">🏯 หน้าวัด</a></div><div class="list">{% for x in rows %}<article class="item"><h3>{{x.name}}</h3><p>{{x.price}} บาท • {{x.bought_at}}</p><div class="card"><b>ข้อมูลดิจิทัล/รหัส:</b><pre style="white-space:pre-wrap">{{x.digital_content}}</pre></div><a class="btn" href="{{url_for('store_product',product_id=x.id)}}">ดูสินค้า/รีวิว</a></article>{% else %}<div class="empty">ยังไม่มีประวัติการซื้อ</div>{% endfor %}</div></section>"""
    return page("ประวัติการซื้อ",body,rows=rows)

# ------------------------- Run -------------------------

@app.get("/health")
def health():
    return {"status":"ok","service":"somice-sangha"}

@app.errorhandler(413)
def too_large(_):
    return page("ไฟล์ใหญ่เกินไป","""<section class="section"><div class="card"><h1>ไฟล์ใหญ่เกินไป</h1><p>จำกัดไฟล์อัปโหลดไม่เกิน 64 MB</p><a class="btn" href="javascript:history.back()">กลับ</a></div></section>"""), 413

@app.route("/funeral/water", methods=["GET","POST"])
def funeral_water():
    act=funeral_activity("funeral_water")
    if not act or not act["is_open"]:
        flash("กิจกรรมรดน้ำศพยังไม่เปิด", "error")
        return redirect(url_for("home"))
    if request.method=="POST":
        require_csrf(); name=request.form.get("name","").strip()
        if not name: flash("กรุณากรอกชื่อหรือราชทินนาม", "error")
        else:
            conn=db(); conn.execute("INSERT INTO funeral_participants(activity_kind,name,created_at) VALUES(?,?,?)",("funeral_water",name,now())); conn.commit(); conn.close()
            flash("บันทึกการเข้าร่วมกิจกรรมแล้ว", "success"); return redirect(url_for("home"))
    body="""
    <section class="section funeral-page">
      <div class="funeral-scene water-scene"><div class="cloud c1"></div><div class="cloud c2"></div><div class="body-symbol"><div class="robe"></div><div class="head-symbol"></div></div><div class="hand-symbol"></div><div class="conch" id="conch">🐚</div><div class="water-drop" id="drop">💧</div></div>
      <div class="card funeral-panel"><h1>💧 รดน้ำศพ</h1><p class="muted">กดสังข์เพื่อร่วมกิจกรรม แล้วกรอกชื่อหรือราชทินนาม</p>
      <button class="funeral-action water-action" onclick="pourWater()">🐚 รดน้ำศพ</button>
      <form id="nameBox" class="form" method="post" style="display:none;margin-top:16px"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><label>ชื่อหรือราชทินนาม</label><input name="name" required autofocus><button class="btn primary">ตกลง</button></form></div>
    </section>
    <style>
    .funeral-page{max-width:760px;margin:auto}.funeral-scene{height:360px;border-radius:24px;position:relative;overflow:hidden;background:linear-gradient(#8ed2ff,#fff0cf);box-shadow:0 12px 35px rgba(0,0,0,.12)}
    .cloud{position:absolute;width:120px;height:34px;background:#fff;border-radius:50px;opacity:.75}.cloud:before,.cloud:after{content:"";position:absolute;background:#fff;border-radius:50%}.cloud:before{width:45px;height:45px;left:20px;top:-18px}.cloud:after{width:60px;height:60px;right:20px;top:-28px}.c1{left:8%;top:55px}.c2{right:8%;top:95px;transform:scale(.75)}
    .body-symbol{position:absolute;left:12%;bottom:55px;width:62%;height:125px;background:#d6a06d;border-radius:70px 45px 30px 35px;transform:rotate(-2deg);box-shadow:0 8px 0 rgba(117,72,35,.12)}.robe{position:absolute;inset:28px 5px 0;background:#d8892b;border-radius:50px 35px 28px 25px}.head-symbol{position:absolute;right:-42px;top:8px;width:85px;height:85px;border-radius:50%;background:#d9a06e}.hand-symbol{position:absolute;left:48%;bottom:112px;width:115px;height:30px;background:#d9a06e;border-radius:30px;transform:rotate(8deg);z-index:3}.conch{position:absolute;left:44%;bottom:36px;font-size:62px;z-index:4;transition:.8s}.conch.pour{transform:translate(25px,-70px) rotate(-35deg)}.water-drop{position:absolute;left:51%;bottom:100px;font-size:25px;opacity:0;z-index:5}.water-drop.fall{animation:dropfall .8s ease-out forwards}@keyframes dropfall{0%{opacity:0;transform:translateY(-15px)}30%{opacity:1}100%{opacity:1;transform:translateY(45px)}}.funeral-panel{margin-top:18px;text-align:center}.funeral-action{border:0;border-radius:999px;padding:16px 30px;font-size:20px;font-weight:700;cursor:pointer}.water-action{background:#c9873b;color:#fff}
    </style><script>function pourWater(){document.getElementById('conch').classList.add('pour');document.getElementById('drop').classList.add('fall');setTimeout(()=>document.getElementById('nameBox').style.display='block',900)}</script>
    """
    return page("รดน้ำศพ",body)

@app.route("/funeral/cremation", methods=["GET","POST"])
def funeral_cremation():
    act=funeral_activity("funeral_cremation")
    if not act or not act["is_open"]:
        flash("กิจกรรมฌาปนกิจยังไม่เปิด", "error"); return redirect(url_for("home"))
    if request.method=="POST":
        require_csrf(); name=request.form.get("name","").strip()
        if not name: flash("กรุณากรอกชื่อ", "error")
        else:
            conn=db(); conn.execute("INSERT INTO funeral_participants(activity_kind,name,created_at) VALUES(?,?,?)",("funeral_cremation",name,now())); conn.commit(); conn.close(); flash("ส่งรายชื่อผู้เข้าร่วมกิจกรรมให้ Admin แล้ว", "success"); return redirect(url_for("home"))
    body="""
    <section class="section funeral-page"><div class="funeral-scene cremation-scene" id="cremationScene"><div class="temple-roof"></div><div class="crematorium"><div class="door"></div><div class="fire" id="fire">🔥</div><div class="smoke"></div></div></div>
    <div class="card funeral-panel"><h1>🔥 ฌาปนกิจ</h1><p class="muted">กดปุ่มไฟเพื่อเริ่มฉากกิจกรรม</p><button class="funeral-action cremation-action" onclick="startCremation()">🔥</button><form id="cremationName" class="form" method="post" style="display:none;margin-top:16px"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><label>ชื่อผู้เข้าร่วม</label><input name="name" required><button class="btn primary">ตกลง</button></form></div></section>
    <style>.cremation-scene{height:380px;border-radius:24px;position:relative;overflow:hidden;background:linear-gradient(#86c8ff,#ffdca0);box-shadow:0 12px 35px rgba(0,0,0,.15)}.temple-roof{position:absolute;left:15%;top:48px;width:70%;height:35px;background:#9d3f2f;clip-path:polygon(50% 0,100% 100%,0 100%)}.crematorium{position:absolute;left:22%;bottom:45px;width:56%;height:235px;background:#e8d6bc;border:8px solid #b68b5a;border-radius:18px 18px 5px 5px;box-shadow:inset 0 0 0 5px #f8ecd9}.door{position:absolute;left:18%;bottom:0;width:64%;height:165px;background:#54463c;border-radius:10px 10px 0 0;transform-origin:bottom;transition:1.2s}.fire{position:absolute;left:42%;bottom:50px;font-size:75px;opacity:.1;z-index:2}.burn .fire{opacity:1;animation:flame .45s infinite alternate}@keyframes flame{to{transform:scale(1.08) translateY(-5px)}}.burn .door{transform:perspective(300px) rotateX(-70deg)}.smoke{position:absolute;left:48%;top:5px;width:35px;height:35px;border-radius:50%;background:rgba(90,90,90,.25);opacity:0}.burn .smoke{animation:smoke 2s infinite}@keyframes smoke{0%{opacity:.2;transform:translateY(0) scale(.7)}100%{opacity:0;transform:translateY(-80px) scale(1.8)}}.funeral-panel{text-align:center;margin-top:18px}.funeral-action{border:0;border-radius:50%;width:78px;height:78px;font-size:35px;cursor:pointer}.cremation-action{background:#df6b21;color:#fff}</style><script>function startCremation(){document.getElementById('cremationScene').classList.add('burn');setTimeout(()=>document.getElementById('cremationName').style.display='block',1400)}</script>
    """
    return page("ฌาปนกิจ",body)

@app.route("/admin/funeral-activities", methods=["GET","POST"])
@admin_required
def admin_funeral_activities():
    conn=db()
    if request.method=="POST":
        require_csrf(); action=request.form.get("action"); kind=request.form.get("kind")
        if action=="toggle":
            if kind in ("funeral_water","funeral_cremation") and not approved_death_exists():
                conn.close(); flash("ยังไม่มีพระมรณภาพที่ Admin อนุมัติ จึงยังเริ่มกิจกรรมไม่ได้", "error"); return redirect(url_for("admin_funeral_activities"))
            if kind=="funeral_cremation":
                water=conn.execute("SELECT is_open FROM activities WHERE kind='funeral_water'").fetchone()
                if water and water["is_open"]:
                    conn.close(); flash("ต้องปิดกิจกรรมรดน้ำศพก่อน จึงจะเริ่มกิจกรรมฌาปนกิจได้", "error"); return redirect(url_for("admin_funeral_activities"))
            val=1 if request.form.get("is_open")=="1" else 0; conn.execute("UPDATE activities SET is_open=? WHERE kind=?",(val,kind)); conn.commit(); flash("เปลี่ยนสถานะกิจกรรมแล้ว", "success")
        elif action=="participant":
            pid=int(request.form.get("id",0)); decision=request.form.get("decision"); emp_id=request.form.get("employee_id"); row=conn.execute("SELECT * FROM funeral_participants WHERE id=? AND status='pending'",(pid,)).fetchone()
            if row and decision=="approve" and emp_id:
                emp=conn.execute("SELECT * FROM employees WHERE id=?",(emp_id,)).fetchone()
                if emp:
                    conn.execute("UPDATE funeral_participants SET status='approved',employee_id=?,decided_at=? WHERE id=?",(emp_id,now(),pid)); conn.execute("UPDATE employees SET total_works=total_works+1 WHERE id=?",(emp_id,)); conn.execute("INSERT INTO works(employee_id,name,work_count,image_file,status,created_at) VALUES(?,?,?,?,?,?)",(emp_id,"กิจกรรม"+("รดน้ำศพ" if row["activity_kind"]=="funeral_water" else "ฌาปนกิจ"),1,"","approved",now())); conn.commit(); flash("อนุมัติและเพิ่ม 1 ผลงานให้พนักงานแล้ว", "success")
                else: flash("ไม่พบพนักงาน", "error")
            elif row and decision=="approve": flash("กรุณาเลือกพนักงานก่อนอนุมัติ", "error")
            elif row and decision=="reject": conn.execute("UPDATE funeral_participants SET status='rejected',decided_at=? WHERE id=?",(now(),pid)); conn.commit(); flash("ปฏิเสธรายชื่อแล้ว", "success")
        return redirect(url_for("admin_funeral_activities"))
    acts={r["kind"]:r for r in conn.execute("SELECT * FROM activities WHERE kind IN ('funeral_water','funeral_cremation')").fetchall()}; participants=conn.execute("SELECT * FROM funeral_participants ORDER BY id DESC").fetchall(); employees=conn.execute("SELECT * FROM employees ORDER BY display_name,username").fetchall(); conn.close()
    body="""
    <section class="section"><h1>🕯️ กิจกรรมรดน้ำศพ / ฌาปนกิจ</h1><p class="muted">สองกิจกรรมนี้แสดงหน้าแรกเฉพาะเมื่อ Admin กดเริ่ม และไม่มีห้องแชท</p><div class="grid">
    <div class="card"><h2>💧 กิจกรรมรดน้ำศพ</h2><p>สถานะ: <b>{{'เริ่มอยู่' if water.is_open else 'ไม่เริ่ม'}}</b></p><form method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="toggle"><input type="hidden" name="kind" value="funeral_water"><input type="hidden" name="is_open" value="{{0 if water.is_open else 1}}"><button class="btn primary">{{'ปิดกิจกรรม' if water.is_open else 'เริ่มกิจกรรม'}}</button></form></div>
    <div class="card"><h2>🔥 กิจกรรมฌาปนกิจ</h2><p>สถานะ: <b>{{'เริ่มอยู่' if cremation.is_open else 'ไม่เริ่ม'}}</b></p><p class="muted">เริ่มได้เมื่อมีพระมรณภาพที่อนุมัติแล้ว และรดน้ำศพปิดแล้ว</p><form method="post"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="toggle"><input type="hidden" name="kind" value="funeral_cremation"><input type="hidden" name="is_open" value="{{0 if cremation.is_open else 1}}"><button class="btn bad">{{'ปิดกิจกรรม' if cremation.is_open else 'เริ่มกิจกรรม'}}</button></form></div></div>
    <h2 style="margin-top:22px">👥 รายชื่อผู้เข้าร่วม</h2><div class="list">{% for x in participants %}<article class="item"><h3>{{'💧' if x.activity_kind=='funeral_water' else '🔥'}} {{x.name}}</h3><p>{{'รดน้ำศพ' if x.activity_kind=='funeral_water' else 'ฌาปนกิจ'}} • {{x.status}} • {{x.created_at}}</p>{% if x.status=='pending' %}<form method="post" class="form"><input type="hidden" name="_csrf" value="{{csrf_token()}}"><input type="hidden" name="action" value="participant"><input type="hidden" name="id" value="{{x.id}}"><select name="employee_id"><option value="">-- เลือกพนักงาน --</option>{% for e in employees %}<option value="{{e.id}}">{{e.display_name or e.username}}{% if e.position %} • {{e.position}}{% endif %}</option>{% endfor %}</select><div class="actions"><button class="btn good" name="decision" value="approve">ตกลง + เพิ่ม 1 ผลงาน</button><button class="btn bad" name="decision" value="reject">ปฏิเสธ</button></div></form>{% endif %}</article>{% else %}<div class="empty">ยังไม่มีรายชื่อผู้เข้าร่วม</div>{% endfor %}</div></section>"""
    return page("กิจกรรมรดน้ำศพ / ฌาปนกิจ",body,water=acts.get("funeral_water",{"is_open":0}),cremation=acts.get("funeral_cremation",{"is_open":0}),participants=participants,employees=employees)


if __name__ == "__main__":
    host=os.environ.get("HOST","0.0.0.0")
    port=int(os.environ.get("PORT","5000"))
    app.run(host=host,port=port,debug=False)
