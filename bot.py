import os
import asyncio
import re
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
import discord

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from discord.ext import commands


# ==============================
# 디스코드 봇 설정
# ==============================

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

TOKEN = os.getenv("DISCORD_TOKEN")
guild_id_str = os.getenv("GUILD_ID")

if not TOKEN or not guild_id_str:
    raise ValueError(
        "DISCORD_TOKEN 또는 GUILD_ID 환경 변수가 설정되지 않았습니다."
    )

GUILD_ID = int(guild_id_str)

GITHUB_BASE_URL = "https://nok210689-del.github.io/Bot/"

NOTICE_CHANNEL_ID = 1414170433883996211
ADMIN_CHANNEL_ID = 1568751408294002879
RESERVATION_CHANNEL_ID = 1414173512561856512

# 공대장 / 관리자 역할 ID
ADMIN_ROLE_IDS = {
    1414176238997602304,  # 공대장
    1414234299456294953   # 관리자
}

reservation_view_registered = False


# ==============================
# 관리자 권한 확인
# ==============================

def is_admin(member):
    if not isinstance(member, discord.Member):
        return False

    return any(
        role.id in ADMIN_ROLE_IDS
        for role in member.roles
    )


# ==============================
# 예약확정 / 취소 버튼
# ==============================

class ReservationView(discord.ui.View):

    def __init__(self, confirmed=False):
        super().__init__(timeout=None)

        button = discord.ui.Button(
            label=(
                "예약확정 취소"
                if confirmed
                else "예약확정"
            ),
            style=(
                discord.ButtonStyle.danger
                if confirmed
                else discord.ButtonStyle.success
            ),
            custom_id="reservation_toggle"
        )

        button.callback = self.toggle_callback
        self.add_item(button)

    async def toggle_callback(
        self,
        interaction: discord.Interaction
    ):

        # 관리자 권한 확인
        if not is_admin(interaction.user):
            await interaction.response.send_message(
                "❌ 공대장 또는 관리자 역할이 있는 사람만 처리할 수 있습니다.",
                ephemeral=True
            )
            return

        if not interaction.guild or not interaction.message:
            await interaction.response.send_message(
                "❌ 서버 정보를 확인할 수 없습니다.",
                ephemeral=True
            )
            return

        message = interaction.message
        content = message.content

        # 신청자 디스코드 ID 추출
        match = re.search(
            r"디코아이디\s*:\s*<@!?(\d+)>",
            content
        )

        if not match:
            await interaction.response.send_message(
                "❌ 신청자 디스코드 ID를 찾을 수 없습니다.",
                ephemeral=True
            )
            return

        target_user_id = int(match.group(1))

        # 현재 예약 상태 확인
        confirmed = "상태 : ✅ 예약완료" in content

        if confirmed:

            # 예약확정 취소
            new_content = content.replace(
                "상태 : ✅ 예약완료",
                "상태 : ⏳ 예약대기"
            )

            new_view = ReservationView(
                confirmed=False
            )

            dm_text = (
                "⚠️ 신청하신 예약의 확정이 취소되었습니다.\n"
                "자세한 내용은 관리자에게 문의해주세요."
            )

            result_text = "예약확정을 취소했습니다."

        else:

            # 예약확정
            new_content = content.replace(
                "상태 : ⏳ 예약대기",
                "상태 : ✅ 예약완료"
            )

            new_view = ReservationView(
                confirmed=True
            )

            dm_text = (
                "🎉 신청하신 예약이 확정되었습니다!\n"
            )

            result_text = "예약이 확정되었습니다."

        if new_content == content:
            await interaction.response.send_message(
                "❌ 예약 상태를 변경할 수 없습니다.",
                ephemeral=True
            )
            return

        await interaction.response.defer(
            ephemeral=True
        )

        # 게시글 상태 및 버튼 변경
        try:
            await message.edit(
                content=new_content,
                view=new_view
            )

        except discord.HTTPException:
            await interaction.followup.send(
                "❌ 예약 상태 변경에 실패했습니다.",
                ephemeral=True
            )
            return

        # 신청자에게 DM 발송
        dm_success = False

        try:
            user = await bot.fetch_user(
                target_user_id
            )

            await user.send(dm_text)
            dm_success = True

        except discord.Forbidden:
            print(
                f"[DM 실패] {target_user_id} : DM 수신 차단"
            )

        except discord.HTTPException as e:
            print(
                f"[DM 오류] {target_user_id} : {e}"
            )

        if dm_success:
            await interaction.followup.send(
                f"✅ {result_text}\n신청자에게 DM을 발송했습니다.",
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                f"✅ {result_text}\n⚠️ DM 발송에는 실패했습니다.",
                ephemeral=True
            )

        print(
            f"[예약상태 변경] "
            f"신청자={target_user_id} / "
            f"상태={'예약대기' if confirmed else '예약완료'} / "
            f"처리자={interaction.user}"
        )


# ==============================
# FastAPI 서버
# ==============================

@asynccontextmanager
async def lifespan(app: FastAPI):

    bot_task = asyncio.create_task(
        bot.start(TOKEN)
    )

    yield

    await bot.close()

    try:
        await bot_task

    except asyncio.CancelledError:
        pass


app = FastAPI(lifespan=lifespan)


@app.api_route("/", methods=["GET", "HEAD"])
def home():
    return {"status": "running"}


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==============================
# 지원서 데이터
# ==============================

class ApplyData(BaseModel):
    discord_id: str
    nickname: str
    role_type: str
    job: str
    apply_date: str

    level: Optional[int] = Field(
        default=None,
        ge=1,
        le=300
    )

    amount: Optional[int] = Field(
        default=None,
        ge=0
    )

    return_status: Optional[str] = None


# ==============================
# 봇 로그인
# ==============================

@bot.event
async def on_ready():

    global reservation_view_registered

    print(
        f"로그인 완료: {bot.user} (ID: {bot.user.id})"
    )

    print(
        "디스코드 봇과 백엔드 서버가 정상적으로 준비되었습니다."
    )

    # 재시작 후 예약 버튼 등록
    if not reservation_view_registered:

        bot.add_view(
            ReservationView()
        )

        reservation_view_registered = True

        print(
            "[시스템] 예약확정 버튼 등록 완료"
        )


# ==============================
# 용병 관리자 승인 버튼
# ==============================

class AdminApprovalView(discord.ui.View):

    def __init__(
        self,
        target_user_id: int,
        new_nickname: str,
        role_type: str,
        date_short: str
    ):

        super().__init__(timeout=None)

        self.target_user_id = target_user_id
        self.new_nickname = new_nickname
        self.role_type = role_type
        self.date_short = date_short

    @discord.ui.button(
        label="승인",
        style=discord.ButtonStyle.success,
        custom_id="admin_approve_btn"
    )
    async def approve_callback(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if not is_admin(interaction.user):
            await interaction.response.send_message(
                "❌ 공대장 또는 관리자 역할이 있는 사람만 처리할 수 있습니다.",
                ephemeral=True
            )
            return

        guild = interaction.guild

        if not guild:
            await interaction.response.send_message(
                "❌ 서버 정보를 찾을 수 없습니다.",
                ephemeral=True
            )
            return

        try:
            member = await guild.fetch_member(
                self.target_user_id
            )

        except discord.NotFound:
            await interaction.response.send_message(
                "❌ 서버에 해당 유저가 존재하지 않습니다.",
                ephemeral=True
            )
            return

        role = discord.utils.get(
            guild.roles,
            name=self.role_type
        )

        if not role:
            await interaction.response.send_message(
                f"❌ 서버 내에 '{self.role_type}' 역할이 없습니다.",
                ephemeral=True
            )
            return

        try:
            await member.edit(
                nick=self.new_nickname
            )

            await member.add_roles(role)

        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ 봇의 권한이 부족합니다.",
                ephemeral=True
            )
            return

        except discord.HTTPException:
            await interaction.response.send_message(
                "❌ 디스코드 API 오류가 발생했습니다.",
                ephemeral=True
            )
            return

        for child in self.children:
            child.disabled = True

        approved_embed = interaction.message.embeds[0]
        approved_embed.color = 0x57F287

        approved_embed.add_field(
            name="상태",
            value=(
                f"✅ **{interaction.user.display_name}** "
                "님에 의해 **승인됨**"
            ),
            inline=False
        )

        await interaction.message.edit(
            embed=approved_embed,
            view=self
        )

        await interaction.response.send_message(
            f"✅ {member.mention}님의 지원을 승인했습니다!",
            ephemeral=True
        )

        try:
            await member.send(
                "🎉 신청하신 용병 지원이 관리자에 의해 "
                "**승인**되었습니다! 닉네임과 역할이 적용되었습니다."
            )

        except discord.HTTPException:
            print(
                f"[DM 실패] 용병 승인 알림: {member.id}"
            )

    @discord.ui.button(
        label="거절",
        style=discord.ButtonStyle.danger,
        custom_id="admin_reject_btn"
    )
    async def reject_callback(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if not is_admin(interaction.user):
            await interaction.response.send_message(
                "❌ 공대장 또는 관리자 역할이 있는 사람만 처리할 수 있습니다.",
                ephemeral=True
            )
            return

        for child in self.children:
            child.disabled = True

        rejected_embed = interaction.message.embeds[0]
        rejected_embed.color = 0xED4245

        rejected_embed.add_field(
            name="상태",
            value=(
                f"❌ **{interaction.user.display_name}** "
                "님에 의해 **거절됨**"
            ),
            inline=False
        )

        await interaction.message.edit(
            embed=rejected_embed,
            view=self
        )

        await interaction.response.send_message(
            "❌ 지원을 거절했습니다.",
            ephemeral=True
        )


# ==============================
# 손님 예약현황 등록
# ==============================

async def register_reservation(
    guild: discord.Guild,
    member: discord.Member,
    data: ApplyData
):

    channel = guild.get_channel(
        RESERVATION_CHANNEL_ID
    )

    if channel is None:

        try:
            channel = await bot.fetch_channel(
                RESERVATION_CHANNEL_ID
            )

        except discord.HTTPException:
            raise HTTPException(
                status_code=500,
                detail="손님 예약현황 채널을 찾을 수 없습니다."
            )

    if not isinstance(channel, discord.TextChannel):
        raise HTTPException(
            status_code=500,
            detail="예약현황 채널이 일반 텍스트 채널이 아닙니다."
        )

    # 날짜 및 요일 계산
    try:
        apply_date = datetime.strptime(
            data.apply_date,
            "%Y-%m-%d"
        )

    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="참여 날짜 형식이 올바르지 않습니다."
        )

    weekdays = [
        "월", "화", "수", "목",
        "금", "토", "일"
    ]

    date_text = (
        f"{apply_date.month}/{apply_date.day} "
        f"({weekdays[apply_date.weekday()]})"
    )

    return_text = (
        "반납"
        if data.return_status == "반납"
        else "미반납"
    )

    message = (
        f"**{date_text}**\n\n"
        f"알+올목({return_text}) : "
        f"{data.nickname} / "
        f"{data.level} / "
        f"{data.job} / "
        f"{data.amount}\n\n"
        f"디코아이디 : <@{member.id}>\n\n"
        f"상태 : ⏳ 예약대기"
    )

    try:
        await channel.send(
            content=message,
            view=ReservationView(),
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False
            )
        )

    except discord.Forbidden:
        raise HTTPException(
            status_code=403,
            detail="예약현황 채널에 메시지를 작성할 권한이 없습니다."
        )

    except discord.HTTPException:
        raise HTTPException(
            status_code=500,
            detail="예약현황 메시지 등록에 실패했습니다."
        )

    print(
        f"[예약등록] {date_text} / "
        f"{data.nickname} / {data.level} / "
        f"{data.job} / {data.amount} / "
        f"{return_text} / ID={member.id}"
    )


# ==============================
# 지원서 접수 API
# ==============================

@app.post("/api/apply")
async def process_application(data: ApplyData):

    guild = bot.get_guild(GUILD_ID)

    if not guild:
        raise HTTPException(
            status_code=500,
            detail="디스코드 서버를 찾을 수 없습니다."
        )

    # 디스코드 ID 확인
    try:
        user_id = int(data.discord_id)

    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="유효하지 않은 디스코드 ID 형식입니다."
        )

    try:
        member = await guild.fetch_member(
            user_id
        )

    except discord.NotFound:
        raise HTTPException(
            status_code=404,
            detail="서버에 없는 유저입니다."
        )

    except discord.HTTPException:
        raise HTTPException(
            status_code=400,
            detail="디스코드 API 통신 중 오류가 발생했습니다."
        )

    # 지원 날짜
    try:
        apply_date = datetime.strptime(
            data.apply_date,
            "%Y-%m-%d"
        )

        date_short = apply_date.strftime("%m.%d")

    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="참여 날짜 형식이 올바르지 않습니다."
        )

    # 입력값 검증
    if data.role_type not in ["손님", "용병"]:
        raise HTTPException(
            status_code=400,
            detail="유효하지 않은 역할 타입입니다."
        )

    if not data.nickname.strip() or not data.job.strip():
        raise HTTPException(
            status_code=400,
            detail="닉네임과 직업을 입력해주세요."
        )

    # 닉네임 생성
    new_nickname = (
        f"[{data.role_type}]"
        f"[{data.job}]"
        f"[{date_short}]"
        f"{data.nickname.strip()}"
    )

    if len(new_nickname) > 32:
        raise HTTPException(
            status_code=400,
            detail="조합된 닉네임이 디스코드 제한(32자)을 초과합니다."
        )

    # ==========================
    # 손님 신청
    # ==========================

    if data.role_type == "손님":

        if data.level is None:
            raise HTTPException(
                status_code=400,
                detail="레벨을 입력해주세요."
            )

        if data.amount is None:
            raise HTTPException(
                status_code=400,
                detail="구인금액을 입력해주세요."
            )

        if data.return_status not in ["반납", "미반납"]:
            raise HTTPException(
                status_code=400,
                detail="반납 여부를 선택해주세요."
            )

        role = discord.utils.get(
            guild.roles,
            name="손님"
        )

        if not role:
            raise HTTPException(
                status_code=500,
                detail="디스코드 서버 내에 '손님' 역할이 없습니다."
            )

        reservation_channel = guild.get_channel(
            RESERVATION_CHANNEL_ID
        )

        if reservation_channel is None:

            try:
                reservation_channel = await bot.fetch_channel(
                    RESERVATION_CHANNEL_ID
                )

            except discord.HTTPException:
                raise HTTPException(
                    status_code=500,
                    detail="예약현황 채널을 찾을 수 없습니다."
                )

        # 닉네임 변경
        try:
            await member.edit(
                nick=new_nickname
            )

        except discord.Forbidden:
            raise HTTPException(
                status_code=403,
                detail="봇의 권한이 부족하여 닉네임을 바꿀 수 없습니다."
            )

        # 역할 부여
        try:
            await member.add_roles(role)

        except discord.Forbidden:
            raise HTTPException(
                status_code=403,
                detail="역할을 부여할 봇의 권한이 부족합니다."
            )

        # 예약현황 등록
        await register_reservation(
            guild,
            member,
            data
        )

        return {
            "status": "success",
            "message": "✅ 손님 신청 및 예약현황 등록이 완료되었습니다!"
        }

    # ==========================
    # 용병 신청
    # ==========================

    elif data.role_type == "용병":

        admin_channel = guild.get_channel(
            ADMIN_CHANNEL_ID
        )

        if not admin_channel:
            raise HTTPException(
                status_code=500,
                detail="관리자 채널을 찾을 수 없습니다."
            )

        admin_embed = discord.Embed(
            title="🚨 용병 지원 승인 대기 중",
            description=(
                f"새로운 **용병** 지원서가 제출되었습니다!\n\n"
                f"• **지원자:** {member.mention} ({member.name})\n"
                f"• **인게임 닉네임:** `{data.nickname}`\n"
                f"• **직업:** `{data.job}`\n"
                f"• **지원 날짜:** `{date_short}`\n"
                f"• **예상 닉네임:** `{new_nickname}`\n\n"
                f"관리자가 아래 버튼을 누르기 전까지는 "
                f"**권한이 부여되지 않습니다.**"
            ),
            color=0xFEE75C
        )

        view = AdminApprovalView(
            target_user_id=member.id,
            new_nickname=new_nickname,
            role_type="용병",
            date_short=date_short
        )

        await admin_channel.send(
            embed=admin_embed,
            view=view
        )

        return {
            "status": "success",
            "message": "용병 지원이 완료되었습니다. 관리자 승인을 기다려주세요!"
        }


# ==============================
# 지원서 작성 버튼
# ==============================

class ApplyView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="지원서 작성하기",
        style=discord.ButtonStyle.primary,
        custom_id="persistent_apply_button"
    )
    async def apply_button_callback(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        # [수정] 서버가 깨어나는 동안 3초 제한에 걸리지 않도록 지연 응답 먼저 전송
        await interaction.response.defer(ephemeral=True)

        user_id = interaction.user.id

        github_page_url = (
            f"{GITHUB_BASE_URL}?discord_id={user_id}"
        )

        view = discord.ui.View()

        view.add_item(
            discord.ui.Button(
                label="웹 지원서 작성하기",
                url=github_page_url,
                style=discord.ButtonStyle.link
            )
        )

        # [수정] defer를 사용했으므로 response.send_message 대신 followup.send 사용
        await interaction.followup.send(
            "👇 아래 버튼을 누르면 본인의 디스코드 ID가 포함된 지원서 작성 페이지가 열립니다!",
            view=view,
            ephemeral=True
        )


# ==============================
# 패널 생성 명령어 (!패널)
# ==============================

@bot.command(name="패널")
@commands.has_permissions(administrator=True)
async def create_panel(ctx):

    embed = discord.Embed(
        title="🍁 메이플랜드 파티 지원서 접수처",
        description=(
            f"⚠️ **환불 및 주의 공지사항은 "
            f"<#{NOTICE_CHANNEL_ID}> 채널을 꼭 확인해 주세요!**\n\n"
            "아래 버튼을 누르면 본인만 볼 수 있는 지원서 작성 링크가 생성됩니다."
        ),
        color=0x5865F2
    )

    view = ApplyView()

    await ctx.send(
        embed=embed,
        view=view
    )


# ==============================
# 프로그램 실행
# ==============================

if __name__ == "__main__":

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 10000))
    )
