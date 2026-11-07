import os
import asyncio
import uvicorn
import threading
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import discord
from discord.ext import commands

# 1. FastAPI 및 디스코드 봇 설정
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

TOKEN = os.getenv("DISCORD_TOKEN")
guild_id_str = os.getenv("GUILD_ID")

if not TOKEN or not guild_id_str:
    raise ValueError("DISCORD_TOKEN 또는 GUILD_ID 환경 변수가 설정되지 않았습니다.")

GUILD_ID = int(guild_id_str)
GITHUB_BASE_URL = "https://nok210689-del.github.io/Bot/"
NOTICE_CHANNEL_ID = 1414170433883996211  # 공지 채널 ID
ADMIN_CHANNEL_ID = 1568751408294002879   # 용병 지원 알림을 받을 관리자 채널 ID

class ApplyData(BaseModel):
    discord_id: str
    nickname: str
    role_type: str  # '손님' 또는 '용병'
    job: str        
    apply_date: str 

@bot.event
async def on_ready():
    print(f"로그인 완료: {bot.user} (ID: {bot.user.id})")
    print("디스코드 봇과 백엔드 서버가 정상적으로 준비되었습니다.")

@app.post("/api/apply")
async def process_application(data: ApplyData):
    
    async def _process_discord_actions():
        guild = bot.get_guild(GUILD_ID)
        if not guild:
            raise HTTPException(status_code=500, detail="디스코드 서버를 찾을 수 없습니다.")

        try:
            user_id = int(data.discord_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="유효하지 않은 디스코드 ID 형식입니다.")

        try:
            member = await guild.fetch_member(user_id)
        except discord.NotFound:
            raise HTTPException(status_code=404, detail="서버에 없는 유저입니다.")
        except discord.HTTPException:
            raise HTTPException(status_code=400, detail="디스코드 API 통신 중 오류가 발생했습니다.")

        try:
            parts = data.apply_date.split("-")
            date_short = f"{parts[1]}.{parts[2]}"
        except Exception:
            date_short = data.apply_date

        new_nickname = f"[{data.role_type}][{data.job}][{date_short}]{data.nickname}"
        
        if len(new_nickname) > 32:
            raise HTTPException(status_code=400, detail="조합된 닉네임이 디스코드 제한(32자)을 초과합니다.")
        
        try:
            await member.edit(nick=new_nickname)
        except discord.Forbidden:
            raise HTTPException(status_code=403, detail="봇의 권한이 부족하여 닉네임을 바꿀 수 없습니다.")

        role_name = data.role_type 
        role = discord.utils.get(guild.roles, name=role_name)
        
        if not role:
            raise HTTPException(status_code=500, detail=f"디스코드 서버 내에 '{role_name}' 역할이 없습니다.")

        try:
            await member.add_roles(role)
        except discord.Forbidden:
            raise HTTPException(status_code=403, detail="역할을 부여할 봇의 권한이 부족합니다.")

        # 지원자가 '용병'을 선택했을 때 관리자 채널로 알림 전송
        if data.role_type == "용병":
            admin_channel = guild.get_channel(ADMIN_CHANNEL_ID)
            if admin_channel:
                admin_embed = discord.Embed(
                    title="🚨 용병 지원 요청 알림",
                    description=(
                        f"새로운 **용병** 지원서가 제출되었습니다!\n\n"
                        f"• **지원자:** {member.mention} ({member.name})\n"
                        f"• **인게임 닉네임:** `{data.nickname}`\n"
                        f"• **직업:** `{data.job}`\n"
                        f"• **지원 날짜:** `{date_short}`\n"
                        f"• **변경된 닉네임:** `{new_nickname}`"
                    ),
                    color=0xFEE75C 
                )
                await admin_channel.send(embed=admin_embed)

        return {"status": "success", "message": f"{new_nickname} 님 적용 완료!"}

    future = asyncio.run_coroutine_threadsafe(_process_discord_actions(), bot.loop)
    return await asyncio.wrap_future(future)


# 3. 버튼 클릭 시 DM 발송 (공지/환불 필독 강조)
class ApplyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="지원서 작성하기", style=discord.ButtonStyle.primary, custom_id="persistent_apply_button")
    async def apply_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        github_page_url = f"{GITHUB_BASE_URL}?discord_id={user_id}"
        
        embed = discord.Embed(
            title="🍁 메이플랜드 파티 지원 안내",
            description=(
                f"⚠️ **주의사항 및 환불/A/S 관련 공지사항을 반드시 읽어주세요!**\n"
                f"👉 <#{NOTICE_CHANNEL_ID}> 채널 필독\n\n"
                "공지를 확인하셨다면 아래 버튼을 눌러 지원서를 작성해 주세요."
            ),
            color=0xED4245
        )
        
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="웹 지원서 작성하기", url=github_page_url, style=discord.ButtonStyle.link))
        
        try:
            await interaction.user.send(embed=embed, view=view)
            await interaction.response.send_message("📩 DM으로 지원서 링크를 보내드렸습니다!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ DM 차단이 켜져 있어서 링크를 보낼 수 없습니다. DM을 열어주세요!", ephemeral=True)


# 4. 패널 생성 명령어 (!패널)
@bot.command(name="패널")
@commands.has_permissions(administrator=True)
async def create_panel(ctx):
    embed = discord.Embed(
        title="🍁 메이플랜드 파티 지원서 접수처",
        description=(
            f"⚠️ **환불 및 주의 공지사항은 <#{NOTICE_CHANNEL_ID}> 채널을 꼭 확인해 주세요!**\n\n"
            "아래 버튼을 누르면 지원서를 작성할 수 있는 링크를 DM으로 보내드립니다."
        ),
        color=0x5865F2
    )
    
    view = ApplyView()
    await ctx.send(embed=embed, view=view)


# 5. 봇 실행 및 FastAPI 서버 통합 실행 (Threading 방식)
def run_fastapi():
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))

if __name__ == "__main__":
    # FastAPI를 백그라운드 스레드로 실행
    fastapi_thread = threading.Thread(target=run_fastapi, daemon=True)
    fastapi_thread.start()

    # 디스코드 봇 실행
    bot.run(TOKEN)
