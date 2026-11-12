
import os
import asyncio
import time
import calendar

from datetime import datetime, date
from zoneinfo import ZoneInfo
from contextlib import asynccontextmanager

import discord
import uvicorn

from discord.ext import commands
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from config import (
    TOKEN,
    GUILD_ID,
    NOTICE_CHANNEL_ID,
)

from reservation import (
    ReservationView,
)

from application import (
    set_bot,
    process_application,
    save_inviter,
    save_invite,
    claim_deleted_invite,
)

from message_forward import (
    setup_message_forward,
)


# ==========================================
# 기본 설정
# ==========================================

PANEL_OWNER_ID = 218196720058630147

KST = ZoneInfo("Asia/Seoul")


# ==========================================
# 지원서 데이터 모델
# ==========================================

class ApplyData(BaseModel):
    discord_id: str
    nickname: str
    role_type: str
    job: str
    apply_date: str

    level: int = Field(ge=1, le=200)


# ==========================================
# Discord 봇 설정
# ==========================================

intents = discord.Intents.default()

intents.members = True
intents.message_content = True
intents.invites = True
intents.guild_reactions = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
)

set_bot(bot)

setup_message_forward(bot)


# ==========================================
# 초대 기록 캐시
# ==========================================

invite_cache = {}

invite_lock = asyncio.Lock()

views_registered = False


# ==========================================
# 초대 링크 갱신
# ==========================================

async def refresh_invites(guild):

    try:
        invites = await guild.invites()

        current = {}

        for invite in invites:

            current[invite.code] = (
                invite.uses or 0
            )

            inviter_id = (
                invite.inviter.id
                if invite.inviter
                else None
            )

            save_invite(
                guild_id=guild.id,
                code=invite.code,
                inviter_id=inviter_id,
                max_uses=invite.max_uses,
                uses=invite.uses or 0,
            )

        invite_cache[guild.id] = current

        print(
            f"[초대 추적] "
            f"초대 링크 {len(invites)}개 확인"
        )

        return True

    except discord.Forbidden:

        print(
            "[초대 추적 오류] "
            "서버 관리 권한이 필요합니다."
        )

    except discord.HTTPException as e:

        print(f"[초대 조회 오류] {e}")

    return False


# ==========================================
# 초대 링크 생성 감지
# ==========================================

@bot.event
async def on_invite_create(invite):

    print(
        f"[초대 생성 이벤트 수신] "
        f"code={invite.code} / "
        f"guild={invite.guild.id if invite.guild else None} / "
        f"inviter={invite.inviter}"
    )

    if invite.guild is None:
        print("[초대 생성 오류] 서버 정보 없음")
        return

    inviter_id = (
        invite.inviter.id
        if invite.inviter
        else None
    )

    success = save_invite(
        guild_id=invite.guild.id,
        code=invite.code,
        inviter_id=inviter_id,
        max_uses=invite.max_uses,
        uses=invite.uses or 0,
    )

    if success:

        print(
            f"[초대 생성 기록 완료] "
            f"{invite.code} / {inviter_id}"
        )

        async with invite_lock:

            cache = invite_cache.setdefault(
                invite.guild.id,
                {},
            )

            cache[invite.code] = (
                invite.uses or 0
            )

    else:

        print(
            f"[초대 생성 기록 실패] {invite.code}"
        )


# ==========================================
# 초대 링크 삭제 감지
# ==========================================

@bot.event
async def on_invite_delete(invite):

    if invite.guild is None:
        return

    async with invite_lock:

        cache = invite_cache.get(
            invite.guild.id,
            {},
        )

        cache.pop(invite.code, None)

    print(
        f"[초대 삭제] {invite.code} "
        "- DB 기록 보존"
    )


# ==========================================
# 초대자 확인
# ==========================================

async def detect_used_invite(guild, member_id):

    old_invites = invite_cache.get(
        guild.id,
        {},
    ).copy()

    for attempt in range(5):

        try:
            new_invites = await guild.invites()

            current_invites = {
                invite.code: invite.uses or 0
                for invite in new_invites
            }

            used_invites = [
                invite
                for invite in new_invites
                if (invite.uses or 0)
                > old_invites.get(invite.code, 0)
            ]

            if len(used_invites) == 1:

                used = used_invites[0]

                inviter_id = (
                    used.inviter.id
                    if used.inviter
                    else None
                )

                invite_cache[guild.id] = (
                    current_invites
                )

                if inviter_id is not None:
                    return inviter_id

            elif len(used_invites) > 1:

                print(
                    "[초대 추적] "
                    "여러 초대 링크 사용 감지"
                )

                invite_cache[guild.id] = (
                    current_invites
                )

                return None

            deleted_codes = (
                set(old_invites)
                - set(current_invites)
            )

            if deleted_codes:

                inviter_id = claim_deleted_invite(
                    guild.id,
                    list(deleted_codes),
                    member_id,
                )

                if inviter_id is not None:

                    invite_cache[guild.id] = (
                        current_invites
                    )

                    print(
                        "[초대 추적] "
                        "삭제된 초대 링크와 입장자 연결 성공"
                    )

                    return inviter_id

            invite_cache[guild.id] = (
                current_invites
            )

            print(
                f"[초대 추적] "
                f"사용 횟수 갱신 대기 "
                f"({attempt + 1}/5)"
            )

        except discord.Forbidden:

            print(
                "[초대 추적 오류] "
                "초대 조회 권한이 없습니다."
            )

            return None

        except discord.HTTPException as e:

            print(f"[초대 조회 오류] {e}")

        if attempt < 4:
            await asyncio.sleep(1)

    return None


# ==========================================
# 지원 유형 선택
# ==========================================

class ApplyTypeView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=180)

    async def interaction_check(self, interaction):

        if interaction.user.bot:
            return False

        return True

    @discord.ui.button(
        label="손님 지원",
        style=discord.ButtonStyle.primary,
        custom_id="apply_type_guest",
    )
    async def guest_callback(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await interaction.response.send_modal(
            ApplyModal("손님")
        )

    @discord.ui.button(
        label="용병 지원",
        style=discord.ButtonStyle.success,
        custom_id="apply_type_mercenary",
    )
    async def mercenary_callback(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await interaction.response.send_modal(
            ApplyModal("용병")
        )


# ==========================================
# 지원서 입력 모달
# ==========================================

class ApplyModal(discord.ui.Modal):

    def __init__(self, role_type):

        super().__init__(
            title=f"{role_type} 지원서 작성"
        )

        self.role_type = role_type

        self.nickname = discord.ui.TextInput(
            label="인게임 닉네임",
            placeholder="메이플랜드 닉네임",
            max_length=20,
            required=True,
        )

        self.job = discord.ui.TextInput(
            label="직업",
            placeholder="예: 보우마스터",
            max_length=20,
            required=True,
        )

        self.level = discord.ui.TextInput(
            label="레벨",
            placeholder="1~200",
            max_length=3,
            required=True,
        )

        self.add_item(self.nickname)
        self.add_item(self.job)
        self.add_item(self.level)

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ):

        nickname = self.nickname.value.strip()
        job = self.job.value.strip()

        try:
            level = int(self.level.value.strip())

        except ValueError:

            await interaction.response.send_message(
                "레벨은 숫자로 입력해 주세요.",
                ephemeral=True,
            )

            return

        if not 1 <= level <= 200:

            await interaction.response.send_message(
                "레벨은 1~200 사이로 입력해 주세요.",
                ephemeral=True,
            )

            return

        if not nickname or not job:

            await interaction.response.send_message(
                "닉네임과 직업을 입력해 주세요.",
                ephemeral=True,
            )

            return

        apply_data = {
            "discord_id": str(interaction.user.id),
            "nickname": nickname,
            "role_type": self.role_type,
            "job": job,
            "level": level,
        }

        view = ApplyCalendarView(
            interaction.user.id,
            apply_data,
        )

        await interaction.response.send_message(
            "📅 **참여 날짜를 선택해 주세요.**\n"
            "오늘 이전 날짜는 선택할 수 없습니다.",
            embed=view.make_embed(),
            view=view,
            ephemeral=True,
        )


# ==========================================
# 지원 날짜 달력
# ==========================================

class ApplyCalendarView(discord.ui.View):

    def __init__(self, user_id, apply_data):

        super().__init__(timeout=300)

        self.user_id = user_id
        self.apply_data = apply_data

        today = datetime.now(KST).date()

        self.year = today.year
        self.month = today.month

        # 0 = 1~25일
        # 1 = 26~31일
        self.date_page = 0

        self.build_components()

    async def interaction_check(self, interaction):

        if interaction.user.id != self.user_id:

            await interaction.response.send_message(
                "본인의 지원서에서만 사용할 수 있습니다.",
                ephemeral=True,
            )

            return False

        return True

    def today(self):

        return datetime.now(KST).date()

    def make_embed(self):

        today = self.today()

        first_day = date(
            self.year,
            self.month,
            1,
        )

        # 일요일을 첫 번째 요일로 설정
        cal = calendar.Calendar(
            firstweekday=6
        )

        weeks = cal.monthdayscalendar(
            self.year,
            self.month,
        )

        weekdays = [
            "일",
            "월",
            "화",
            "수",
            "목",
            "금",
            "토",
        ]

        lines = []

        lines.append(
            " ".join(
                f"{day:^3}"
                for day in weekdays
            )
        )

        for week in weeks:

            row = []

            for day in week:

                if day == 0:
                    row.append("   ")
                    continue

                current_date = date(
                    self.year,
                    self.month,
                    day,
                )

                if current_date < today:
                    row.append(" × ")
                else:
                    row.append(
                        f"{day:^3}"
                    )

            lines.append(" ".join(row))

        embed = discord.Embed(
            title=f"📅 {self.year}년 {self.month}월",
            description=(
                "```text\n"
                + "\n".join(lines)
                + "\n```"
                "날짜 선택 목록에서 참여일을 골라 주세요.\n"
                "× 표시는 선택할 수 없는 지난 날짜입니다."
            ),
            color=0x5865F2,
        )

        embed.add_field(
            name="날짜 선택 페이지",
            value=(
                "1페이지: 1일~25일\n"
                "2페이지: 26일~31일"
            ),
            inline=False,
        )

        return embed

    def get_date_options(self):

        today = self.today()

        if self.date_page == 0:
            start_day = 1
            end_day = 25
        else:
            start_day = 26
            end_day = 31

        last_day = calendar.monthrange(
            self.year,
            self.month,
        )[1]

        options = []

        for day in range(
            start_day,
            min(end_day, last_day) + 1,
        ):

            selected_date = date(
                self.year,
                self.month,
                day,
            )

            # 오늘 이전 날짜는 목록에서 제외
            if selected_date < today:
                continue

            weekday = [
                "월",
                "화",
                "수",
                "목",
                "금",
                "토",
                "일",
            ][selected_date.weekday()]

            options.append(
                discord.SelectOption(
                    label=f"{self.month}월 {day}일 ({weekday})",
                    value=selected_date.strftime(
                        "%Y-%m-%d"
                    ),
                )
            )

        return options

    def build_components(self):

        self.clear_items()

        options = self.get_date_options()

        if options:

            date_select = discord.ui.Select(
                placeholder="참여 날짜 선택",
                min_values=1,
                max_values=1,
                options=options,
                row=0,
            )

            date_select.callback = (
                self.date_select_callback
            )

            self.add_item(date_select)

        today = self.today()

        current_month = (
            today.year,
            today.month,
        )

        previous_disabled = (
            self.year,
            self.month,
        ) <= current_month

        previous_month = discord.ui.Button(
            label="◀ 이전 달",
            style=discord.ButtonStyle.secondary,
            disabled=previous_disabled,
            row=1,
        )

        next_month = discord.ui.Button(
            label="다음 달 ▶",
            style=discord.ButtonStyle.secondary,
            row=1,
        )

        previous_page = discord.ui.Button(
            label="이전 날짜",
            style=discord.ButtonStyle.secondary,
            disabled=self.date_page == 0,
            row=1,
        )

        next_page = discord.ui.Button(
            label="다음 날짜",
            style=discord.ButtonStyle.secondary,
            disabled=self.date_page == 1,
            row=1,
        )

        cancel = discord.ui.Button(
            label="취소",
            style=discord.ButtonStyle.danger,
            row=1,
        )

        async def previous_month_callback(interaction):
            self.change_month(-1)
            await self.refresh(interaction)

        async def next_month_callback(interaction):
            self.change_month(1)
            await self.refresh(interaction)

        async def previous_page_callback(interaction):
            self.date_page = 0
            await self.refresh(interaction)

        async def next_page_callback(interaction):
            self.date_page = 1
            await self.refresh(interaction)

        async def cancel_callback(interaction):
            self.stop()

            await interaction.response.edit_message(
                content="지원서 작성을 취소했습니다.",
                embed=None,
                view=None,
            )

        previous_month.callback = (
            previous_month_callback
        )

        next_month.callback = (
            next_month_callback
        )

        previous_page.callback = (
            previous_page_callback
        )

        next_page.callback = (
            next_page_callback
        )

        cancel.callback = cancel_callback

        self.add_item(previous_month)
        self.add_item(next_month)
        self.add_item(previous_page)
        self.add_item(next_page)
        self.add_item(cancel)

    def change_month(self, amount):

        month = self.month + amount
        year = self.year

        if month < 1:
            month = 12
            year -= 1

        elif month > 12:
            month = 1
            year += 1

        self.year = year
        self.month = month

        self.date_page = 0

    async def refresh(self, interaction):

        self.build_components()

        await interaction.response.edit_message(
            embed=self.make_embed(),
            view=self,
        )

    async def date_select_callback(self, interaction):

        selected_date = (
            interaction.data["values"][0]
        )

        selected = datetime.strptime(
            selected_date,
            "%Y-%m-%d",
        ).date()

        if selected < self.today():

            await interaction.response.send_message(
                "오늘 이전 날짜는 선택할 수 없습니다.",
                ephemeral=True,
            )

            return

        self.apply_data["apply_date"] = (
            selected_date
        )

        data = ApplyData(
            **self.apply_data
        )

        await interaction.response.defer(
            ephemeral=True
        )

        try:

            result = await process_application(
                data
            )

            for child in self.children:
                child.disabled = True

            await interaction.message.edit(
                view=self
            )

            await interaction.followup.send(
                f"✅ {result['message']}",
                ephemeral=True,
            )

            self.stop()

        except ValueError as e:

            await interaction.followup.send(
                f"❌ {e}",
                ephemeral=True,
            )

        except Exception as e:

            print(
                f"[지원서 처리 오류] {e}"
            )

            await interaction.followup.send(
                "지원서 처리 중 오류가 발생했습니다.",
                ephemeral=True,
            )


# ==========================================
# 지원서 작성 패널 버튼
# ==========================================

class ApplyView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="📝 지원서 작성",
        style=discord.ButtonStyle.primary,
        custom_id="persistent_apply_button",
    )
    async def apply_callback(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await interaction.response.send_message(
            "지원 유형을 선택해 주세요.",
            view=ApplyTypeView(),
            ephemeral=True,
        )


# ==========================================
# 봇 준비 완료
# ==========================================

@bot.event
async def on_ready():

    global views_registered

    print("=" * 40)

    print(
        f"[Discord.py 버전] "
        f"{discord.__version__}"
    )

    print(
        f"[초대 인텐트 활성화] "
        f"{bot.intents.invites}"
    )

    print(
        f"[멤버 인텐트 활성화] "
        f"{bot.intents.members}"
    )

    print(
        f"[반응 인텐트 활성화] "
        f"{bot.intents.guild_reactions}"
    )

    print(
        f"[Gateway 인텐트 값] "
        f"{bot.intents.value}"
    )

    print(
        f"[초대 이벤트 핸들러 등록] "
        f"{callable(getattr(bot, 'on_invite_create', None))}"
    )

    print(f"Discord 로그인 완료: {bot.user}")
    print(f"서버 ID: {GUILD_ID}")

    print("=" * 40)

    if not views_registered:

        bot.add_view(ApplyView())
        bot.add_view(ReservationView())

        views_registered = True

        print("[완료] 지원서 버튼 등록")
        print("[완료] 예약현황 버튼 등록")

    guild = bot.get_guild(GUILD_ID)

    if guild is not None:

        async with invite_lock:
            await refresh_invites(guild)


# ==========================================
# 멤버 입장 및 초대한 사람 확인
# ==========================================

@bot.event
async def on_member_join(member):

    if member.guild.id != GUILD_ID:
        return

    print(
        f"[입장 감지] "
        f"{member} ({member.id})"
    )

    async with invite_lock:

        inviter_id = await detect_used_invite(
            member.guild,
            member.id,
        )

        if inviter_id is None:

            print(
                f"[입장] {member} ({member.id}) "
                "- 초대자 확인 불가"
            )

            return

        save_inviter(
            member.id,
            inviter_id,
        )

        inviter = bot.get_user(inviter_id)

        print(
            f"[초대 기록 완료] "
            f"입장자: {member} ({member.id})"
        )

        print(
            f"[초대한 사람] "
            f"{inviter or inviter_id} "
            f"({inviter_id})"
        )


# ==========================================
# 지원 패널 명령어
# ==========================================

@bot.command(name="패널")
async def panel_command(ctx):

    if ctx.author.id != PANEL_OWNER_ID:

        await ctx.reply(
            "패널 명령어 사용 권한이 없습니다."
        )

        return

    embed = discord.Embed(
        title="🍁 RICE 공대 지원 접수처",
        description=(
            "메이플랜드 RICE 공대 손님 및 용병 지원 접수처입니다.\n\n"
            "👥 **손님 지원**\n"
            f"<#{NOTICE_CHANNEL_ID}> 채널에서 "
            "환불 및 주의사항을 반드시 확인해 주세요.\n\n"
            "⚔️ **용병 지원**\n"
            "지원서 제출 후 관리자 승인을 기다려 주세요.\n"
            "승인 완료 시 규칙 채널을 안내해 드립니다.\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "📝 **지원서 작성**\n"
            "아래 버튼을 눌러 지원 유형과 지원서를 작성해 주세요.\n\n"
            "⚠️ **버튼이 작동하지 않나요?**\n"
            "예약 문의는 예약 안내를 받으신 담당자 "
            "또는 아래 담당자에게 DM으로 문의해 주세요.\n"
            f"[📩 공대 담당자에게 DM 보내기]"
            f"(https://discord.com/users/{PANEL_OWNER_ID})"
        ),
        color=0x5865F2,
    )

    await ctx.send(
        embed=embed,
        view=ApplyView(),
    )


# ==========================================
# FastAPI 설정
# ==========================================

@asynccontextmanager
async def lifespan(app: FastAPI):

    print("[서버] Discord 봇 시작")

    bot_task = asyncio.create_task(
        bot.start(TOKEN)
    )

    try:
        yield

    finally:

        print("[서버] Discord 봇 종료 중...")

        if not bot.is_closed():
            await bot.close()

        try:
            await bot_task

        except Exception as e:

            print(
                f"[종료 중 예외 발생 (무시됨)] {e}"
            )

        print("[서버] Discord 봇 완전 종료 완료")


app = FastAPI(
    lifespan=lifespan,
)


# ==========================================
# CORS 설정
# ==========================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==========================================
# UptimeRobot 상태 확인
# ==========================================

@app.get("/")
@app.head("/")
async def health_check():

    return {
        "status": "ok"
    }


# ==========================================
# 기존 지원서 API 유지
# ==========================================

@app.post("/api/apply")
async def apply_application(data: ApplyData):

    try:

        result = await process_application(data)

        return result

    except ValueError as e:

        raise HTTPException(
            status_code=400,
            detail=str(e),
        )

    except HTTPException:
        raise

    except Exception as e:

        print(
            f"[지원서 처리 오류] {e}"
        )

        raise HTTPException(
            status_code=500,
            detail="지원서 처리 중 오류가 발생했습니다.",
        )


# ==========================================
# 서버 실행
# ==========================================

if __name__ == "__main__":

    port = int(
        os.environ.get("PORT", 10000)
    )

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        timeout_keep_alive=75,
    )
