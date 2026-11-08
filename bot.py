import os
import asyncio
from contextlib import asynccontextmanager
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import discord
from discord.ext import commands

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
ADMIN_CHANNEL_ID = 1568751408294002879    # 관리자 채널 ID

# 1. FastAPI Lifespan을 이용해 웹서버와 디스코드 봇을 단일 이벤트 루프에서 통합 실행
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 서버가 켜질 때 디스코드 봇 백그라운드 태스크 시작
    bot_task = asyncio.create_task(bot.start(TOKEN))
    yield
    # 서버가 꺼질 때 봇 정상 종료
    await bot.close()
    try:
        await bot_task
    except asyncio.CancelledError:
        pass

app = FastAPI(lifespan=lifespan)

# UptimeRobot 및 cron-job 핑을 안전하게 받아주도록 GET, HEAD 요청 모두 허용
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

class ApplyData(BaseModel):
    discord_id: str
    nickname: str
    role_type: str  # '손님' 또는 '용병'
    job: str        
    apply_date: str 

@bot.event
async def on_ready():
    print(f"로그인 완료: {bot.user} (ID: {bot.user.id})")
    print("디스코드 봇과 백엔드 서버가 단일 루프에서 정상적으로 준비되었습니다.")


# 관리자가 승인/거절할 때 사용할 승인 버튼 뷰
class AdminApprovalView(discord.ui.View):
    def __init__(self, target_user_id: int, new_nickname: str, role_type: str, date_short: str):
        super().__init__(timeout=None)
        self.target_user_id = target_user_id
        self.new_nickname = new_nickname
        self.role_type = role_type
        self.date_short = date_short

    @discord.ui.button(label="승인", style=discord.ButtonStyle.success, custom_id="admin_approve_btn")
    async def approve_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("❌ 서버 정보를 찾을 수 없습니다.", ephemeral=True)
            return

        try:
            member = await guild.fetch_member(self.target_user_id)
        except discord.NotFound:
            await interaction.response.send_message("❌ 서버에 해당 유저가 존재하지 않습니다.", ephemeral=True)
            return

        # 1. 닉네임 변경 시도
        try:
            await member.edit(nick=self.new_nickname)
        except discord.Forbidden:
            await interaction.response.send_message("❌ 봇의 권한이 부족하여 유저의 닉네임을 변경할 수 없습니다.", ephemeral=True)
            return

        # 2. 역할 부여 시도
        role = discord.utils.get(guild.roles, name=self.role_type)
        if not role:
            await interaction.response.send_message(f"❌ 서버 내에 '{self.role_type}' 역할이 없습니다.", ephemeral=True)
            return

        try:
            await member.add_roles(role)
        except discord.Forbidden:
            await interaction.response.send_message("❌ 역할을 부여할 봇의 권한이 부족합니다.", ephemeral=True)
            return

        # 버튼 비활성화 및 메시지 수정
        for child in self.children:
            child.disabled = True

        approved_embed = interaction.message.embeds[0]
        approved_embed.color = 0x57F287  # 초록색으로 변경
        approved_embed.add_field(name="상태", value=f"✅ **{interaction.user.display_name}** 님에 의해 **승인됨**", inline=False)

        await interaction.message.edit(embed=approved_embed, view=self)
        await interaction.response.send_message(f"✅ {member.mention}님의 지원을 승인하고 권한을 부여했습니다!", ephemeral=True)

        try:
            await member.send(f"🎉 신청하신 용병 지원이 관리자에 의해 **승인**되었습니다! 닉네임과 역할이 적용되었습니다.")
        except:
            pass

    @discord.ui.button(label="거절", style=discord.ButtonStyle.danger, custom_id="admin_reject_btn")
    async def reject_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True

        rejected_embed = interaction.message.embeds[0]
        rejected_embed.color = 0xED4245  # 빨간색으로 변경
        rejected_embed.add_field(name="상태", value=f"❌ **{interaction.user.display_name}** 님에 의해 **거절됨**", inline=False)

        await interaction.message.edit(embed=rejected_embed, view=self)
        await interaction.response.send_message("❌ 지원을 거절했습니다.", ephemeral=
