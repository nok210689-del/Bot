
import discord

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from discord.ui import View, Button, Modal, Select

from config import (
    GUILD_ID,
    ADMIN_ROLE_IDS,
    SCHEDULE_CHANNEL_ID,
)

import weekly_database as db


KST = ZoneInfo("Asia/Seoul")

WEEKDAYS = [
    "월", "화", "수", "목", "금", "토", "일"
]


# ==========================================
# 날짜 계산
# ==========================================

def get_week_start(date=None):

    if date is None:
        date = datetime.now(KST).date()

    return date - timedelta(days=date.weekday())


def get_week_dates():

    monday = get_week_start()

    return [
        monday + timedelta(days=i)
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

def get_day_status(user_id, date, schedule):

    today = datetime.now(KST).date()

    date_text = date.isoformat()

    # 이미 지난 날짜는 잠금
    if date < today:

        status = schedule.get(date_text, "참석")

        if status == "휴무":
            return "휴무 잠금"

        if status == "불참":
            return "불참 잠금"

        return "참석 잠금"

    # 현재 휴무 설정 확인
    rest_days = db.get_rest_days()

    if date.weekday() in rest_days:
        return "휴무"

    return schedule.get(date_text, "참석")


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

        rest_days = db.get_rest_days()

        modal = WeeklyScheduleModal(
            user_id,
            week_start,
            current,
            rest_days
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

        db.copy_previous_schedule(
            user_id,
            previous_week.isoformat(),
            current_week.isoformat()
        )

        await interaction.response.send_message(
            "지난주 일정을 이번 주 일정에 복사했습니다.",
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
        current,
        rest_days
    ):

        super().__init__(
            title="주간 참석 일정 제출"
        )

        self.user_id = user_id
        self.week_start = week_start

        self.days = get_week_dates()

        self.selects = []

        for i, date in enumerate(self.days):

            date_text = date.isoformat()

            status = current.get(date_text, "참석")

            if i in rest_days:
                status = "휴무"

            select = Select(
                placeholder=format_day(date),
                options=[
                    discord.SelectOption(
                        label="참석",
                        value="참석",
                        default=status == "참석"
                    ),
                    discord.SelectOption(
                        label="불참",
                        value="불참",
                        default=status == "불참"
                    ),
                    discord.SelectOption(
                        label="휴무",
                        value="휴무",
                        default=status == "휴무"
                    )
                ]
            )

            # Modal에는 Select를 직접 넣을 수 없으므로
            # 아래 날짜별 입력은 텍스트 방식으로 처리한다.
            self.selects.append(select)

        self.day_input = discord.ui.TextInput(
            label="불참 날짜",
            placeholder="예: 화, 목, 토 (참석 가능한 날은 입력하지 않음)",
            required=False,
            max_length=50
        )

        self.add_item(self.day_input)

        self.current = current

    async def on_submit(self, interaction):

        if interaction.user.id != self.user_id:

            await interaction.response.send_message(
                "본인의 일정만 제출할 수 있습니다.",
                ephemeral=True
            )

            return

        today = datetime.now(KST).date()

        week_start = self.week_start

        previous = db.get_schedule(
            self.user_id,
            week_start.isoformat()
        )

        unavailable = [
            x.strip()
            for x in self.day_input.value.split(",")
            if x.strip()
        ]

        valid_days = set(WEEKDAYS)

        if any(x not in valid_days for x in unavailable):

            await interaction.response.send_message(
                "요일은 월, 화, 수, 목, 금, 토, 일 중에서 입력해 주세요.",
                ephemeral=True
            )

            return

        schedule = {}

        rest_days = db.get_rest_days()

        for date in self.days:

            date_text = date.isoformat()

            weekday = WEEKDAYS[date.weekday()]

            # 과거 일정은 기존 상태 유지
            if date < today:

                old_status = previous.get(
                    date_text,
                    "참석"
                )

                schedule[date_text] = old_status

                continue

            # 기본 휴무일
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
# 공대장 설정
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

        lines = []

        for record in records:

            user_id = record["user_id"]

            schedule = record["schedule"]

            unavailable = []

            for date_text, status in schedule.items():

                if status == "불참":

                    date = datetime.fromisoformat(date_text).date()

                    unavailable.append(format_day(date))

            text = ", ".join(unavailable) if unavailable else "전부 참석"

            lines.append(
                f"<@{user_id}> : {text}"
            )

        await interaction.response.send_message(
            "\n".join(lines),
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
# 패널 생성
# ==========================================

async def send_weekly_panel(channel):

    embed = discord.Embed(
        title="📅 주간 참석 일정",
        description=(
            "이번 주 참석 가능 일정을 제출해 주세요.\n\n"
            "기본은 참석으로 설정되어 있습니다.\n"
            "불참하는 날짜만 입력하면 됩니다.\n\n"
            "지난주와 동일한 일정이라면 복사 기능을 이용하세요."
        ),
        color=discord.Color.blue()
    )

    embed.set_footer(
        text="일정은 언제든 수정할 수 있습니다."
    )

    await channel.send(
        embed=embed,
        view=WeeklyScheduleView()
    )


# ==========================================
# 봇 시작 시 등록
# ==========================================

def setup_weekly_schedule(bot):

    bot.add_view(WeeklyScheduleView())
