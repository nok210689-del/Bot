import os
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import discord
from discord.ext import commands

# 1. FastAPI 및 디스코드 봇 설정
app = FastAPI()

# 웹페이지(GitHub Pages 등)에서 보내는 요청을 차단하지 않도록 CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 실제 운영 시 내 깃허브 주소만 허용하도록 바꿀 수 있습니다.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 디스코드 봇 인텐트 설정
intents = discord.Intents.default()
intents.members = naver = True if hasattr(discord.Intents, 'members') else True
bot = commands.Bot(command_prefix="!", intents=intents)

# 환경 변수에서 토큰 및 서버 ID 불러오기 (혹은 직접 입력 가능)
TOKEN = os.getenv("DISCORD_TOKEN", "여기에_디스코드_봇_토큰_입력")
GUILD_ID = int(os.getenv("GUILD_ID", "여기에_디스코드_서버_ID_입력"))

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

    # 3. 닉네임 변경 형식 조합: [구분] [직업] 닉네임 (예: [손님] [비숍] 홍길동)
    new_nickname = f"[{data.role_type}] [{data.job}] {data.nickname}"
    
    try:
        # 디스코드 닉네임 변경
        await member.edit(nick=new_nickname)
    except discord.Forbidden:
        raise HTTPException(status_code=403, detail="봇의 권한이 부족하여 닉네임을 바꿀 수 없습니다. (봇 역할 위치를 위로 올리세요)")

    # 4. 역할(Role) 부여 로직
    # '손님' 또는 '용병'이라는 이름을 가진 디스코드 역할을 찾아 유저에게 부여
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
    # 내 깃허브 페이지 주소 뒤에 유저의 디스코드 ID를 자동으로 붙여서 개인 링크 생성
    github_page_url = f"https://nok210689-del.github.io/저장소이름/?discord_id={user_id}"
    
    embed = discord.Embed(
        title="🍁 메이플랜드 파티 지원 안내",
        description="아래 버튼을 눌러 지원서를 작성해 주세요.\n본인 계정으로 자동 연동된 링크입니다.",
        color=0x5865F2
    )
    
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label="지원서 작성하기", url=github_page_url, style=discord.ButtonStyle.link))
    
    # 유저에게 개인 메시지(DM)로 전송
    try:
        await ctx.author.send(embed=embed, view=view)
        await ctx.send(f"{ctx.author.mention} 님, 지원서 링크를 **DM(귓속말)**로 보내드렸습니다! 📩", delete_after=10)
    except discord.Forbidden:
        await ctx.send(f"{ctx.author.mention} 님, DM 차단이 켜져 있어 링크를 보낼 수 없습니다. DM을 허용해 주세요!")

# 6. FastAPI(웹서버)와 Discord Bot을 동시에 실행하는 메인 함수
if __name__ == "__main__":
    import threading
    
    # 백그라운드에서 FastAPI 웹서버 구동 (포트 8000)
    def run_web():
        uvicorn.run(app, host="0.0.0.0", port=8000)

    web_thread = threading.Thread(target=run_web)
    web_thread.daemon = True
    web_thread.start()

    # 디스코드 봇 실행
    bot.run(TOKEN)
