import os


# ==========================================
# Discord 봇 환경변수
# ==========================================

TOKEN = os.environ.get("DISCORD_TOKEN")
GUILD_ID = os.environ.get("GUILD_ID")

if not TOKEN:
    raise ValueError("DISCORD_TOKEN 환경변수가 없습니다.")

if not GUILD_ID:
    raise ValueError("GUILD_ID 환경변수가 없습니다.")

GUILD_ID = int(GUILD_ID)


# ==========================================
# GitHub Pages
# ==========================================

GITHUB_BASE_URL = "https://nok210689-del.github.io/Bot/"


# ==========================================
# Discord 채널 ID
# ==========================================

NOTICE_CHANNEL_ID = 1414170433883996211

ADMIN_CHANNEL_ID = 1568751408294002879

RESERVATION_CHANNEL_ID = 1414173512561856512

RULE_CHANNEL_ID = 1414171609303875625


# ==========================================
# 관리자 역할 ID
# ==========================================

ADMIN_ROLE_IDS = [
    1414176238997602304,  # 공대장
    1414234299456294953,  # 관리자
]


# ==========================================
# 지원 유형
# ==========================================

APPLICATION_ROLES = [
    "손님",
    "용병",
]
