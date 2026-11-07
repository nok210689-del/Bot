import os
import uvicorn
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

@bot.event
async def on_ready():
    print(f"로그인 완료: {bot.user} (ID: {bot.user.id})")
    print("디스코드 봇과 백엔드 서버가 정상적으로 준비되었습니다.")

# 2. 웹페이지에서 [제출하기]를 누르면 실행되는 API 엔드포인트
@app.post("/api/apply")
async def process_application(data: ApplyData):
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        raise HTTPException(status_code=500, detail="디스코드 서버를 찾을 수 없습니다.")

    try:
        member = await guild.fetch_member(int(data.discord_id))
    except discord.NotFound:
        raise HTTPException(status_code=404, detail="서버에 없는 유저입니다.")
    except Exception:
        raise HTTPException(status_code=400, detail="잘못된 디스코드 ID입니다.")

    # 3. 닉네임 변경 형식 조합 (예: [손님] [비숍] 홍길동)
    new_nickname = f"[{data.role_type}] [{data.job}] {data.nickname}"
    
    try:
        await member.edit(nick=new_nickname)
    except discord.Forbidden:
        raise HTTPException(status_code=403, detail="봇의 권한이 부족하여 닉네임을 바꿀 수 없습니다. (봇 역할 위치를 위로 올리세요)")

    # 4. 역할(Role) 부여 로직
    role_name = data.role_type 
    role = discord.utils.get(guild.roles, name=role_name)
    
    if role:
        try:
            await member.add_roles(role)
        except discord.Forbidden:
            raise HTTPException(status_code=403, detail="역할을 부여할 권한이 없습니다.")

    return {"status": "success", "message": f"{new_nickname} 님 적용 완료!"}

# 5. 디스코드 명령어: 유저에게 맞춤형 웹페이지 링크 생성해 주기
@bot.command(name="지원서")
async def apply_link(ctx):
    user_id = ctx.author.id
    # 본인의 실제 GitHub Pages 주소로 변경하세요 (예: https://nok210689-del.github.io/Bot/)
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
        await ctx.send(f"{ctx.author.mention} 님, 지원
