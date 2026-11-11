
import discord

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from discord.ui import View, Modal, Select

from config import ADMIN_ROLE_IDS

import weekly_database as db


KST = ZoneInfo("Asia/Seoul")

WEEKDAYS = [
    "월", "화", "수", "목", "금", "토", "일"
]


# ==========================================
# 날짜 계산
# ==========================================

def get_today():

    return datetime.now(KST).date()


def get_week_start(date=None):

    if date is None:
        date = get_today()

    return date - timedelta(days=date.weekday())


def get_week_dates(week_start=None):

    if week_start is None:
        week_start = get_week_start()

    return [
        week_start + timedelta(days=i)
        for i in range(7)
    ]


def format_day(date):

    return f"{WEEKDAYS[date.weekday()]} {date.day}일"


def is_admin(member):

    if not isinstance(member, discord.Member):
        return False

    return any(
        role.id in ADMIN_ROLE_IDS
        for role in member.roles
    )


# ==========================================
# 일정 상태
# ==========================================

def get_day_status(date, schedule):

    date_text = date.isoformat()

    today = get_today()

    rest_days = db.get_rest_days()

    # 저장된 일정 우선
    status = schedule.get(date_text)

    # 과거 날짜
    if date < today:

        if status is None:
            status = (
                "휴무"
                if date.weekday() in rest_days
                else "참석"
            )

        if status == "휴무":
            return "휴무 잠금"

        if status == "불참":
            return "불참 잠금"

        return "참석 잠금"

    # 오늘 및 미래 날짜
    if date.weekday() in rest_days:
        return "휴무"

    return status or "참석"


# ==========================================
# 개인 일정 불참 요일 변환
# ==========================================

def get_unavailable_days(schedule, dates):

    unavailable = []

    today = get_today()

    rest_days = db.get_rest_days()

    for date in dates:

        if date < today:
            continue

        if date.weekday() in rest_days:
            continue

        status = schedule.get(
            date.isoformat(),
            "참석"
        )

        if status == "불참":

            unavailable.append(
                WEEKDAYS[date.weekday()]
            )

    return unavailable


# ==========================================
# 일정 패널
# ==========================================

class WeeklyScheduleView(View):

    def __init__(self):

        super().__init__(timeout=None)

    @discord.ui.button(
        label="📋 내 일정 제출 / 수정",
        style=discord.ButtonStyle.primary,
        custom_id="weekly:edit"
    )
    async def edit_schedule(self, interaction, button):

        user_id = interaction.user.id

        week_start = get_week_start()

        current = db.get_schedule(
            user_id,
            week_start.isoformat()
        )

        modal = WeeklyScheduleModal(
            user_id,
            week_start,
            current
        )

        await interaction.response.send_modal(modal)

    @discord.ui.button(
        label="🔁 지난주와 동일",
        style=discord.ButtonStyle.secondary,
        custom_id="weekly:copy"
    )
    async def copy_schedule(self, interaction, button):

        user_id = interaction.user.id

        current_week = get_week_start()

        previous_week = current_week - timedelta(days=7)

        previous = db.get_schedule(
            user_id,
            previous_week.isoformat()
        )

        if not previous:

            await interaction.response.send_message(
                "지난주 제출 기록이 없습니다.",
                ephemeral=True
            )

            return

        # 지난주 날짜를 이번 주 날짜로 변환
        current = db.get_schedule(
            user_id,
            current_week.isoformat()
        )

        today = get_today()

        new_schedule = {}

        previous_dates = get_week_dates(
            previous_week
        )

        current_dates = get_week_dates(
            current_week
        )

        for old_date, new_date in zip(
            previous_dates,
            current_dates
        ):

            date_text = new_date.isoformat()

            # 지난 날짜는 기존 일정 유지
            if new_date < today:

                if date_text in current:
                    new_schedule[date_text] = current[date_text]

                else:
                    new_schedule[date_text] = (
                        "휴무"
                        if new_date.weekday() in db.get_rest_days()
                        else "참석"
                    )

                continue

            old_status = previous.get(
                old_date.isoformat(),
                "참석"
            )

            # 이번 주 휴무 설정 우선
            if new_date.weekday() in db.get_rest_days():

                new_schedule[date_text] = "휴무"

            elif old_status == "불참":

                new_schedule[date_text] = "불참"

            else:

                new_schedule[date_text] = "참석"

        db.save_schedule(
            user_id,
            current_week.isoformat(),
            new_schedule
        )

        await interaction.response.send_message(
            "지난주 일정을 이번 주에 복사했습니다.",
            ephemeral=True
        )

    @discord.ui.button(
        label="⚙️ 일정 설정",
        style=discord.ButtonStyle.secondary,
        custom_id="weekly:settings"
    )
    async def settings(self, interaction, button):

        if not is_admin(interaction.user):

            await interaction.response.send_message(
                "공대장만 사용할 수 있습니다.",
                ephemeral=True
            )

            return

        await interaction.response.send_message(
            "주간 일정 설정",
            view=WeeklyAdminView(),
            ephemeral=True
        )


# ==========================================
# 개인 일정 제출 Modal
# ==========================================

class WeeklyScheduleModal(Modal):

    def __init__(
        self,
        user_id,
        week_start,
        current
    ):

        super().__init__(
            title="주간 참석 일정 제출"
        )

        self.user_id = user_id
        self.week_start = week_start

        self.days = get_week_dates(
            week_start
        )

        # 기존 불참 일정 표시
        unavailable = get_unavailable_days(
            current,
            self.days
        )

        default_text = ", ".join(unavailable)

        self.day_input = discord.ui.TextInput(
            label="불참 날짜",
            placeholder="예: 화, 목, 토",
            default=default_text,
            required=False,
            max_length=50
        )

        self.add_item(self.day_input)

    async def on_submit(self, interaction):

        # 본인 일정만 제출 가능
        if interaction.user.id != self.user_id:

            await interaction.response.send_message(
                "본인의 일정만 제출할 수 있습니다.",
                ephemeral=True
            )

            return

        today = get_today()

        week_start = self.week_start

        # 현재 DB 일정 다시 조회
        previous = db.get_schedule(
            self.user_id,
            week_start.isoformat()
        )

        # 입력값 정리
        unavailable = [
            x.strip()
            for x in self.day_input.value.split(",")
            if x.strip()
        ]

        valid_days = set(WEEKDAYS)

        if any(
            day not in valid_days
            for day in unavailable
        ):

            await interaction.response.send_message(
                "요일은 월, 화, 수, 목, 금, 토, 일 중에서 입력해 주세요.",
                ephemeral=True
            )

            return

        # 중복 요일 검사
        if len(unavailable) != len(set(unavailable)):

            await interaction.response.send_message(
                "같은 요일을 중복 입력할 수 없습니다.",
                ephemeral=True
            )

            return

        schedule = {}

        rest_days = db.get_rest_days()

        for date in self.days:

            date_text = date.isoformat()

            weekday = WEEKDAYS[date.weekday()]

            # 과거 날짜는 기존 상태 유지
            if date < today:

                old_status = previous.get(
                    date_text,
                    "휴무" if date.weekday() in rest_days else "참석"
                )

                schedule[date_text] = old_status

                continue

            # 휴무일 우선 적용
            if date.weekday() in rest_days:

                schedule[date_text] = "휴무"

                continue

            # 불참 날짜
            if weekday in unavailable:

                schedule[date_text] = "불참"

            else:

                schedule[date_text] = "참석"

        db.save_schedule(
            self.user_id,
            week_start.isoformat(),
            schedule
        )

        await interaction.response.send_message(
            "주간 일정이 저장되었습니다.",
            ephemeral=True
        )


# ==========================================
# 공대장 설정 화면
# ==========================================

class WeeklyAdminView(View):

    def __init__(self):

        super().__init__(timeout=180)

    @discord.ui.button(
        label="휴무일 설정",
        style=discord.ButtonStyle.primary
    )
    async def rest_day_settings(self, interaction, button):

        if not is_admin(interaction.user):

            await interaction.response.send_message(
                "공대장만 사용할 수 있습니다.",
                ephemeral=True
            )

            return

        await interaction.response.send_message(
            "기본 휴무일을 선택하세요.",
            view=RestDayView(),
            ephemeral=True
        )

    @discord.ui.button(
        label="이번 주 제출 현황",
        style=discord.ButtonStyle.secondary
    )
    async def weekly_status(self, interaction, button):

        if not is_admin(interaction.user):

            await interaction.response.send_message(
                "공대장만 사용할 수 있습니다.",
                ephemeral=True
            )

            return

        week_start = get_week_start()

        records = db.get_week_records(
            week_start.isoformat()
        )

        if not records:

            await interaction.response.send_message(
                "이번 주 제출 기록이 없습니다.",
                ephemeral=True
            )

            return

        dates = get_week_dates(
            week_start
        )

        lines = []

        lines.append("📊 **이번 주 참석 현황**")
        lines.append("")

        # 요일별 참석 인원
        for date in dates:

            date_text = date.isoformat()

            attendees = 0
            unavailable = 0
            rest = 0

            for record in records:

                schedule = record["schedule"]

                status = get_day_status(
                    date,
                    schedule
                )

                if status in ("참석", "참석 잠금"):
                    attendees += 1

                elif status in ("불참", "불참 잠금"):
                    unavailable += 1

                elif status in ("휴무", "휴무 잠금"):
                    rest += 1

            lines.append(
                f"**{format_day(date)}** "
                f"참석 {attendees}명 / "
                f"불참 {unavailable}명 / "
                f"휴무 {rest}명"
            )

        lines.append("")
        lines.append("📋 **개인별 불참 일정**")

        for record in records:

            user_id = record["user_id"]

            schedule = record["schedule"]

            unavailable = []

            for date in dates:

                status = get_day_status(
                    date,
                    schedule
                )

                if status in ("불참", "불참 잠금"):

                    unavailable.append(
                        format_day(date)
                    )

            text = (
                ", ".join(unavailable)
                if unavailable
                else "불참 없음"
            )

            lines.append(
                f"<@{user_id}> : {text}"
            )

        # Discord 메시지 길이 제한 대응
        content = "\n".join(lines)

        chunks = []

        while len(content) > 1900:

            split_index = content.rfind(
                "\n",
                0,
                1900
            )

            if split_index <= 0:
                split_index = 1900

            chunks.append(
                content[:split_index]
            )

            content = content[split_index:].lstrip()

        if content:
            chunks.append(content)

        await interaction.response.send_message(
            chunks[0],
            ephemeral=True
        )

        for chunk in chunks[1:]:

            await interaction.followup.send(
                chunk,
                ephemeral=True
            )


# ==========================================
# 휴무일 설정
# ==========================================

class RestDayView(View):

    def __init__(self):

        super().__init__(timeout=180)

        current = db.get_rest_days()

        options = []

        for i, day in enumerate(WEEKDAYS):

            options.append(
                discord.SelectOption(
                    label=day,
                    value=str(i),
                    default=i in current
                )
            )

        self.select = Select(
            placeholder="휴무일 선택",
            min_values=0,
            max_values=7,
            options=options
        )

        self.select.callback = self.select_callback

        self.add_item(self.select)

    async def select_callback(self, interaction):

        if not is_admin(interaction.user):

            await interaction.response.send_message(
                "공대장만 설정할 수 있습니다.",
                ephemeral=True
            )

            return

        days = [
            int(value)
            for value in self.select.values
        ]

        db.set_rest_days(days)

        await interaction.response.send_message(
            "휴무일 설정을 저장했습니다.",
            ephemeral=True
        )


# ==========================================
# 공용 패널 생성
# ==========================================

async def send_weekly_panel(channel):

    week_start = get_week_start()

    dates = get_week_dates(
        week_start
    )

    date_text = " / ".join(
        format_day(date)
        for date in dates
    )

    embed = discord.Embed(
        title="📅 주간 참석 일정",
        description=(
            f"**이번 주 일정: {date_text}**\n\n"
            "기본 상태는 참석입니다.\n"
            "불참하는 요일만 입력해 주세요.\n\n"
            "지난주와 일정이 동일하다면\n"
            "지난주와 동일 버튼을 이용하세요."
        ),
        color=discord.Color.blue()
    )

    embed.set_footer(
        text="제출 후에도 언제든 일정을 수정할 수 있습니다."
    )

    await channel.send(
        embed=embed,
        view=WeeklyScheduleView()
    )


# ==========================================
# 봇 시작 시 등록
# ==========================================

def setup_weekly_schedule(bot):

    bot.add_view(
        WeeklyScheduleView()
    )
