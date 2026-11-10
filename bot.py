
import os
import asyncio
from contextlib import asynccontextmanager
from urllib.parse import urlencode

import discord
import uvicorn

from discord.ext import commands
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional

from config import (
    TOKEN,
    GUILD_ID,
    GITHUB_BASE_URL,
    NOTICE_CHANNEL_ID,
)

from reservation import (
    is_admin,
    ReservationView,
)

from application import (
    set_bot,
    process_application,
)


# ==========================================
# 지원서 데이터 모델
# ==========================================

class ApplyData(BaseModel):

    discord_id: str
    nickname: str
    role_type: str
    job: str
    apply_date: str

    # 손님 / 용병 공통 필수
    level: int = Field(ge=1, le=300)

    # 손님만 사용
    amount: Optional[int] = Field(
        default=None,
        ge=0,
    )

    return_status: Optional[str] = None


# ==========================================
# Discord 봇 설정
# ==========================================

intents = discord.Intents.default()

intents.members = True
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
)

# application.py에 봇 연결
set_bot(bot)


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

    print("=" * 40)
    print(f"Discord 로그인 완료: {bot.user}")
    print(f"서버 ID: {GUILD_ID}")
    print("=" * 40)


# ==========================================
# Persistent View 등록
# ==========================================

@bot.event
async def setup_hook():

    bot.add_view(ApplyView())
    bot.add_view(ReservationView())

    print("[완료] 지원서 버튼 등록")
    print("[완료] 예약현황 버튼 등록")


# ==========================================
# 지원 패널 명령어
# ==========================================

@bot.command(name="패널")
async def panel_command(ctx):

    if not is_admin(ctx.author):
        await ctx.reply(
            "관리자만 사용할 수 있습니다."
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
