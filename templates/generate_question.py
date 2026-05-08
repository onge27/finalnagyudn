# ─── Imports ─────────────────────────────────────────────
import os
import re
import json
import secrets as pysecrets
import sqlite3
from functools import wraps
from datetime import datetime

import bcrypt
import pandas as pd
import google.generativeai as genai

from flask import Flask, render_template, request, redirect, url_for, session, flash, abort
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

load_dotenv()

# ─── Gemini AI Setup ─────────────────────────────────────
api_key = os.getenv("GEMINI_API_KEY")

print("🔍 GEMINI API KEY LOADED:", "YES" if api_key else "NO")

if not api_key:
    raise Exception("❌ GEMINI_API_KEY not found. Please check your .env file")

genai.configure(api_key=api_key)
gemini_model = genai.GenerativeModel("models/gemini-1.5-flash")

print("✅ Gemini initialized successfully")

# ─── Database Setup ───────────────────────────────────────
DATABASE_URL = os.getenv('DATABASE_URL') or os.getenv('NEON_DATABASE_URL')

if DATABASE_URL:
    import psycopg2
    import psycopg2.extras
    USE_POSTGRES = True
else:
    USE_POSTGRES = False


def get_db():
    if USE_POSTGRES:
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False
        return conn
    else:
        conn = sqlite3.connect('examination.db')
        conn.row_factory = sqlite3.Row
        return conn


def db_cursor(conn):
    if USE_POSTGRES:
        return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    return conn.cursor()


def db_execute(conn, sql, params=()):
    if USE_POSTGRES:
        sql = sql.replace('?', '%s')
        cur = db_cursor(conn)
        cur.execute(sql, params)
        return cur
    else:
        cur = db_cursor(conn)
        cur.execute(sql, params)
        return cur


def db_lastid(cur):
    if USE_POSTGRES:
        row = cur.fetchone()
        return row['id'] if row else None
    return cur.lastrowid


# ─── Flask App Setup ──────────────────────────────────────
app = Flask(__name__)

app.secret_key = os.getenv('FLASK_SECRET_KEY', 'wmsu-oes-secure-key-2026')

app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['ALLOWED_EXTENSIONS'] = {'csv', 'xlsx'}
app.config['CLERK_PUBLISHABLE_KEY'] = os.getenv('CLERK_PUBLISHABLE_KEY', '')
app.config['CLERK_SECRET_KEY'] = os.getenv('CLERK_SECRET_KEY', '')
app.config['YEAR'] = 2026

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


# ─── Helpers ──────────────────────────────────────────────
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please sign in to continue.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def role_required(role):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if session.get('role') != role:
                flash('You do not have permission to access that page.', 'danger')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated
    return decorator


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') != 'admin':
            flash('Admin access required.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated


def check_password(stored, provided):
    if isinstance(stored, str):
        stored = stored.encode()
    return bcrypt.checkpw(provided.encode(), stored)


# ─── Routes (Core) ───────────────────────────────────────
@app.route('/')
def index():
    return redirect(url_for('login'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    conn = get_db()
    subjects = db_execute(conn, "SELECT id, subject_name FROM subjects").fetchall()
    conn.close()

    if request.method == 'POST':
        name = request.form['name'].strip()
        email = request.form['email'].strip().lower()
        password = request.form['password']
        confirm_password = request.form.get('confirm_password')
        role = request.form['role']
        teacher_code = request.form.get('teacher_code', '')
        subject_id = request.form.get('subject_id')

        if not name or not email or not password or not confirm_password:
            flash('All fields are required.', 'danger')
            return render_template('register.html', subjects=subjects)

        if not re.match(r'^[A-Za-z\s]+$', name):
            flash('Name must contain only letters and spaces.', 'danger')
            return render_template('register.html', subjects=subjects)

        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
            return render_template('register.html', subjects=subjects)

        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template('register.html', subjects=subjects)

        if not email.endswith('@gmail.com'):
            flash('Only Gmail addresses are allowed.', 'danger')
            return render_template('register.html', subjects=subjects)

        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
        hashed_store = hashed.decode() if not USE_POSTGRES else hashed

        try:
            conn = get_db()
            cur = db_execute(conn,
                "INSERT INTO users (name, email, password, role) VALUES (?, ?, ?, ?)",
                (name, email, hashed_store, role)
            )
            conn.commit()
            conn.close()

            flash('Registration successful!', 'success')
            return redirect(url_for('login'))

        except Exception:
            flash('Email already exists.', 'danger')
            return render_template('register.html', subjects=subjects)

    return render_template('register.html', subjects=subjects)


# ─── Login ────────────────────────────────────────────────
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        login_id = request.form['login_id'].strip()
        password = request.form['password']

        conn = get_db()

        if login_id.isdigit():
            user = db_execute(conn, "SELECT * FROM users WHERE student_number = ?", (int(login_id),)).fetchone()
        else:
            user = db_execute(conn, "SELECT * FROM users WHERE email = ?", (login_id,)).fetchone()

        conn.close()

        if user and check_password(user['password'], password):
            session['user_id'] = user['id']
            session['role'] = user['role']
            session['name'] = user['name']

            flash(f"Welcome {user['name']}!", 'success')
            return redirect(url_for('dashboard'))

        flash('Invalid credentials.', 'danger')

    return render_template('login.html')


# ─── Dashboard Router ─────────────────────────────────────
@app.route('/dashboard')
@login_required
def dashboard():
    role = session.get('role')

    if role == 'admin':
        return redirect(url_for('admin_dashboard'))
    elif role == 'teacher':
        return redirect(url_for('teacher_dashboard'))
    else:
        return redirect(url_for('student_dashboard'))


# ─── (Your remaining routes continue below...) ────────────

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)