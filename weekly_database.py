
import os
import json
import sqlite3

from datetime import datetime
from zoneinfo import ZoneInfo


# ==========================================
# DB 설정
# ==========================================

KST = ZoneInfo("Asia/Seoul")

DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "weekly_schedule.db"
)


# ==========================================
# DB 연결
# ==========================================

def get_connection():

    conn = sqlite3.connect(DB_PATH)

    conn.row_factory = sqlite3.Row

    return conn


# ==========================================
# 초기 테이블 생성
# ==========================================

def init_db():

    with get_connection() as conn:

        conn.execute("""
            CREATE TABLE IF NOT EXISTS weekly_schedules (
                user_id INTEGER NOT NULL,
                week_start TEXT NOT NULL,
                schedule TEXT NOT NULL,
                updated_at TEXT NOT NULL,

                PRIMARY KEY (user_id, week_start)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS weekly_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                week_start TEXT NOT NULL,
                schedule TEXT NOT NULL,
                submitted_at TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS weekly_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # 기본 휴무일: 일요일
        conn.execute("""
            INSERT OR IGNORE INTO weekly_settings (
                setting_key,
                setting_value,
                updated_at
            )
            VALUES (?, ?, ?)
        """, (
            "rest_days",
            json.dumps([6]),
            datetime.now(KST).isoformat()
        ))


# ==========================================
# 일정 조회
# ==========================================

def get_schedule(user_id, week_start):

    with get_connection() as conn:

        row = conn.execute("""
            SELECT schedule
            FROM weekly_schedules
            WHERE user_id = ?
              AND week_start = ?
        """, (
            user_id,
            week_start
        )).fetchone()

    if not row:
        return {}

    return json.loads(row["schedule"])


# ==========================================
# 일정 저장 및 수정
# ==========================================

def save_schedule(user_id, week_start, schedule):

    now = datetime.now(KST)

    today = now.date()

    week_schedule = {}

    # 기존 일정 조회
    previous = get_schedule(
        user_id,
        week_start
    )

    # 날짜별 과거 일정은 기존 상태 유지
    for date_text, status in schedule.items():

        date = datetime.fromisoformat(
            date_text
        ).date()

        if date < today:

            status = previous.get(
                date_text,
                status
            )

        week_schedule[date_text] = status

    schedule_json = json.dumps(
        week_schedule,
        ensure_ascii=False
    )

    now_text = now.isoformat()

    with get_connection() as conn:

        # 현재 일정 저장
        conn.execute("""
            INSERT INTO weekly_schedules (
                user_id,
                week_start,
                schedule,
                updated_at
            )
            VALUES (?, ?, ?, ?)

            ON CONFLICT(user_id, week_start)
            DO UPDATE SET
                schedule = excluded.schedule,
                updated_at = excluded.updated_at
        """, (
            user_id,
            week_start,
            schedule_json,
            now_text
        ))

        # 제출 및 수정 이력 저장
        conn.execute("""
            INSERT INTO weekly_history (
                user_id,
                week_start,
                schedule,
                submitted_at
            )
            VALUES (?, ?, ?, ?)
        """, (
            user_id,
            week_start,
            schedule_json,
            now_text
        ))


# ==========================================
# 지난주 일정 복사
# ==========================================

def copy_previous_schedule(
    user_id,
    previous_week,
    current_week
):

    previous = get_schedule(
        user_id,
        previous_week
    )

    if not previous:
        return False

    today = datetime.now(KST).date()

    current = {}

    for date_text, status in previous.items():

        date = datetime.fromisoformat(
            date_text
        ).date()

        # 과거 날짜는 복사하지 않음
        if date < today:
            continue

        current[date_text] = status

    save_schedule(
        user_id,
        current_week,
        current
    )

    return True


# ==========================================
# 휴무일 조회
# ==========================================

def get_rest_days():

    with get_connection() as conn:

        row = conn.execute("""
            SELECT setting_value
            FROM weekly_settings
            WHERE setting_key = ?
        """, (
            "rest_days",
        )).fetchone()

    if not row:
        return [6]

    return json.loads(
        row["setting_value"]
    )


# ==========================================
# 휴무일 저장
# ==========================================

def set_rest_days(days):

    days = sorted(set(days))

    if any(
        not isinstance(day, int) or day < 0 or day > 6
        for day in days
    ):
        raise ValueError("휴무일은 0~6 사이여야 합니다.")

    now = datetime.now(KST).isoformat()

    with get_connection() as conn:

        conn.execute("""
            INSERT INTO weekly_settings (
                setting_key,
                setting_value,
                updated_at
            )
            VALUES (?, ?, ?)

            ON CONFLICT(setting_key)
            DO UPDATE SET
                setting_value = excluded.setting_value,
                updated_at = excluded.updated_at
        """, (
            "rest_days",
            json.dumps(days),
            now
        ))


# ==========================================
# 주간 전체 제출 현황
# ==========================================

def get_week_records(week_start):

    with get_connection() as conn:

        rows = conn.execute("""
            SELECT user_id, schedule
            FROM weekly_schedules
            WHERE week_start = ?
            ORDER BY user_id
        """, (
            week_start,
        )).fetchall()

    records = []

    for row in rows:

        records.append({
            "user_id": row["user_id"],
            "schedule": json.loads(
                row["schedule"]
            )
        })

    return records


# ==========================================
# 개인 일정 수정 이력
# ==========================================

def get_schedule_history(user_id, week_start):

    with get_connection() as conn:

        rows = conn.execute("""
            SELECT
                id,
                schedule,
                submitted_at
            FROM weekly_history
            WHERE user_id = ?
              AND week_start = ?
            ORDER BY id DESC
        """, (
            user_id,
            week_start
        )).fetchall()

    history = []

    for row in rows:

        history.append({
            "id": row["id"],
            "schedule": json.loads(
                row["schedule"]
            ),
            "submitted_at": row["submitted_at"]
        })

    return history


# ==========================================
# DB 초기화
# ==========================================

init_db()
