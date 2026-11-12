
import os
import asyncio
import time

from contextlib import asynccontextmanager
from urllib.parse import urlencode

import discord
import uvicorn

from discord.ext import commands
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from config import (
    TOKEN,
    GUILD_ID,
    GITHUB_BASE_URL,
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

# 메시지 자동 전달
from message_forward import (
    setup_message_forward,
)


# ==========================================
# 패널 명령어 사용 권한
# ==========================================

PANEL_OWNER_ID = 218196720058630147


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

# 메시지 전달 이벤트 등록
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
# 지원서 작성 버튼
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

        await interaction.response.defer(
            ephemeral=True,
        )

        params = urlencode({
            "discord_id": str(interaction.user.id)
        })

        apply_url = (
            f"{GITHUB_BASE_URL.rstrip('/')}/"
            f"?{params}"
        )

        view = discord.ui.View()

        view.add_item(
            discord.ui.Button(
                label="지원서 작성 페이지 열기",
                style=discord.ButtonStyle.link,
                url=apply_url,
            )
        )

        await interaction.followup.send(
            "아래 버튼을 눌러 지원서를 작성해 주세요.",
            view=view,
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

    # 지정된 Discord 계정만 사용 가능
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
            "아래 버튼을 눌러 지원서를 작성해 주세요."
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

        print("[서버] Discord 봇 종료")

        await bot.close()

        try:
            await bot_task

        except Exception as e:
            print(f"[종료 오류] {e}")


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
# 지원서 접수 API
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

        print(f"[지원서 처리 오류] {e}")

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
    )
