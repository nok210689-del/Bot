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

# ─── [추가] cron-job 핑을 받아줄 루트 경로 (404 에러 방지용) ───
@app.get("/")
def home():
    return {"status": "running"}
# -------------------------------------------------------------

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
ADMIN_CHANNEL_ID = 1568751408294002879    # 관리자 채널 ID

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

        # 유저에게 DM으로 승인 알림 전송 (선택사항)
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
        await interaction.response.send_message("❌ 지원을 거절했습니다.", ephemeral=True)


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

        # --- [손님]인 경우: 기존처럼 즉시 적용 ---
        if data.role_type == "손님":
            try:
                await member.edit(nick=new_nickname)
            except discord.Forbidden:
                raise HTTPException(status_code=403, detail="봇의 권한이 부족하여 닉네임을 바꿀 수 없습니다.")

            role = discord.utils.get(guild.roles, name="손님")
            if not role:
                raise HTTPException(status_code=500, detail="디스코드 서버 내에 '손님' 역할이 없습니다.")

            try:
                await member.add_roles(role)
            except discord.Forbidden:
                raise HTTPException(status_code=403, detail="역할을 부여할 봇의 권한이 부족합니다.")

            return {"status": "success", "message": "손님 신청이 완료되었습니다!"}

        # --- [용병]인 경우: 관리자 승인 대기 (권한 즉시 부여 안 함) ---
        elif data.role_type == "용병":
            admin_channel = guild.get_channel(ADMIN_CHANNEL_ID)
            if not admin_channel:
                raise HTTPException(status_code=500, detail="관리자 채널을 찾을 수 없습니다.")

            admin_embed = discord.Embed(
                title="🚨 용병 지원 승인 대기 중",
                description=(
                    f"새로운 **용병** 지원서가 제출되었습니다!\n\n"
                    f"• **지원자:** {member.mention} ({member.name})\n"
                    f"• **인게임 닉네임:** `{data.nickname}`\n"
                    f"• **직업:** `{data.job}`\n"
                    f"• **지원 날짜:** `{date_short}`\n"
                    f"• **예상 닉네임:** `{new_nickname}`\n\n"
                    f"관리자가 아래 버튼을 누르기 전까지는 **권한이 부여되지 않습니다.**"
                ),
                color=0xFEE75C 
            )

            # 승인/거절 버튼 부착
            view = AdminApprovalView(
                target_user_id=member.id,
                new_nickname=new_nickname,
                role_type="용병",
                date_short=date_short
            )

            await admin_channel.send(embed=admin_embed, view=view)
            return {"status": "success", "message": "용병 지원이 완료되었습니다. 관리자 승인을 기다려주세요!"}

        else:
            raise HTTPException(status_code=400, detail="유효하지 않은 역할 타입입니다.")

    future = asyncio.run_coroutine_threadsafe(_process_discord_actions(), bot.loop)
    return await asyncio.wrap_future(future)


# 3. 버튼 클릭 시 DM 발송
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


# 5. 봇 실행 및 FastAPI 서버 통합 실행
def run_fastapi():
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))

if __name__ == "__main__":
    fastapi_thread = threading.Thread(target=run_fastapi, daemon=True)
    fastapi_thread.start()
    bot.run(TOKEN)
