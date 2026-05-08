import sqlite3

def get_db():
    conn = sqlite3.connect('questions.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS quizzes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,
            questions TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def save_quiz(topic, questions):
    conn = get_db()
    import json
    conn.execute(
        'INSERT INTO quizzes (topic, questions) VALUES (?, ?)',
        (topic, json.dumps(questions))
    )
    conn.commit()
    conn.close()

def get_all_quizzes():
    conn = get_db()
    import json
    rows = conn.execute(
        'SELECT * FROM quizzes ORDER BY created_at DESC'
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        r = dict(row)
        r['questions'] = json.loads(r['questions'])
        result.append(r)
    return result