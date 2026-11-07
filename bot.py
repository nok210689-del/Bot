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

# 웹페이지(GitHub Pages 등)에서 보내는 요청 허용 (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 디스코드 봇 인텐트 설정
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# 깃허브 시크릿 또는 환경 변수에서 토큰 및 서버 ID 불러오기
TOKEN = os.getenv("DISCORD_TOKEN")
guild_id_str = os.getenv("GUILD_ID")

if not TOKEN or not guild_id_str:
    raise ValueError("DISCORD_TOKEN 또는 GUILD_ID 환경 변수가 설정되지 않았습니다.")

GUILD_ID = int(guild_id_str)

# 웹에서 받을 데이터 양식 (Pydantic)
class ApplyData(BaseModel):
    discord_id: str
    nickname: str
    role_type: str  # '손님' 또는 '용병'
    job: str        # '비숍' 등
    apply_date: str # '2026-11-09' 등 날짜 데이터

@bot.event
async def on_ready():
    print(f"로그인 완료: {bot.user} (ID: {bot.user.id})")
    print("디스코드 봇과 백엔드 서버가 정상적으로 준비되었습니다.")

# 2. 웹페이지에서 [제출하기]를 누르면 실행되는 API 엔드포인트
@app.post("/api/apply")
async def process_application(data: ApplyData):
    
    # 디스코드 API 작업들을 봇의 메인 이벤트 루프에서 안전하게 실행하기 위한 내부 함수
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
            raise HTTPException(status_code=404, detail="서버에 없는 유저입니다. 먼저 서버에 입장해 주세요.")
        except discord.HTTPException:
            raise HTTPException(status_code=400, detail="디스코드 API 통신 중 오류가 발생했습니다.")

        # 3. 년도를 제외하고 '월.일' 형식으로 변환 (예: '2026-11-09' -> '11.09')
        try:
            parts = data.apply_date.split("-")
            date_short = f"{parts[1]}.{parts[2]}"
        except Exception:
            date_short = data.apply_date

        # 요청하신 닉네임 형식 조합: [구분][직업][월.일]닉네임 (예: [손님][비숍][11.09]소여)
        new_nickname = f"[{data.role_type}][{data.job}][{date_short}]{data.nickname}"
        
        # 32자 제한 방어
        if len(new_nickname) > 32:
            raise HTTPException(status_code=400, detail="조합된 닉네임이 디스코드 제한(32자)을 초과합니다. 닉네임을 짧게 입력해 주세요.")
        
        try:
            await member.edit(nick=new_nickname)
        except discord.Forbidden:
            raise HTTPException(status_code=403, detail="봇의 권한이 부족하여 닉네임을 바꿀 수 없습니다. (봇 역할 위치를 서버 제일 위로 올리세요)")

        # 4. 역할(Role) 부여 로직
        role_name = data.role_type 
        role = discord.utils.get(guild.roles, name=role_name)
        
        if not role:
            raise HTTPException(status_code=500, detail=f"디스코드 서버 내에 '{role_name}' 역할(Role)이 존재하지 않습니다. 역할을 먼저 생성해 주세요.")

        try:
            await member.add_roles(role)
        except discord.Forbidden:
            raise HTTPException(status_code=403, detail="역할을 부여할 봇의 권한이 부족합니다.")

        return {"status": "success", "message": f"{new_nickname} 님 적용 완료!"}

    # 스레드 간 이벤트 루프 충돌을 방지하기 위해 bot.loop로 안전하게 전달하여 실행
    future = asyncio.run_coroutine_threadsafe(_process_discord_actions(), bot.loop)
    return await asyncio.wrap_future(future)

# 5. 디스코드 명령어: 유저에게 맞춤형 웹페이지 링크 생성해 주기
@bot.command(name="지원서")
async def apply_link(ctx):
    user_id = ctx.author.id
    github_page_url = f"https://nok210689-del.github.io/Bot/?discord_id={user_id}"
    
    embed = discord.Embed(
        title="🍁 메이플랜드 파티 지원 안내",
        description="아래 버튼을 눌러 지원서를 작성해 주세요.\n본인 계정으로 자동 연동된 링크입니다.",
        color=0x5865F2
    )
    
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label="지원서 작성하기", url=github_page_url, style=discord.ButtonStyle.link))
    
    try:
        await ctx.author.send(embed=embed, view=view)
        await ctx.send(f"{ctx.author.mention} 님, DM으로 지원서 링크를 보내드렸습니다!", delete_after=10)
    except discord.Forbidden:
        await ctx.send(f"{ctx.author.mention} 님, DM(다이렉트 메시지) 차단이 켜져 있어 전송에 실패했습니다. DM을 열어주세요.")

# 6. FastAPI 웹 서버와 디스코드 봇을 동시에 실행하는 구문
def run_web():
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

if __name__ == "__main__":
    web_thread = threading.Thread(target=run_web)
    web_thread.daemon = True
    web_thread.start()
    
    bot.run(TOKEN)
