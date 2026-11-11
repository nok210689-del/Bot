
import discord

from config import (
    SOURCE_CHANNEL_ID,
    TARGET_CHANNEL_ID,
    RAID_LEADER_ROLE_ID,
)


# ==========================================
# 설정
# ==========================================

CHECK_EMOJI = "✅"
FORWARD_EMOJI = "📢"


# 이미 전달한 메시지 ID
forwarded_messages = set()


# ==========================================
# 채널 및 역할 확인
# ==========================================

def is_raid_leader(member):

    if not isinstance(member, discord.Member):
        return False

    return any(
        role.id == RAID_LEADER_ROLE_ID
        for role in member.roles
    )


# ==========================================
# 원본 메시지 감지
# ==========================================

async def handle_source_message(message):

    if message.author.bot:
        return

    if message.channel.id != SOURCE_CHANNEL_ID:
        return

    if not is_raid_leader(message.author):
        return

    try:
        await message.add_reaction(CHECK_EMOJI)
        await message.add_reaction(FORWARD_EMOJI)

        print(
            f"[메시지 전달] 확인 완료 "
            f"- 작성자: {message.author} "
            f"- 메시지 ID: {message.id}"
        )

    except discord.Forbidden:
        print("[메시지 전달] 반응 권한이 없습니다.")

    except discord.HTTPException as e:
        print(f"[메시지 전달] 반응 오류: {e}")


# ==========================================
# 전달 이모지 감지
# ==========================================

async def handle_forward_reaction(
    payload,
    bot
):

    if payload.guild_id is None:
        return

    if payload.channel_id != SOURCE_CHANNEL_ID:
        return

    if payload.user_id == bot.user.id:
        return

    if str(payload.emoji) != FORWARD_EMOJI:
        return

    # 사용자 정보 확인
    guild = bot.get_guild(payload.guild_id)

    if guild is None:
        return

    member = guild.get_member(payload.user_id)

    if member is None:
        try:
            member = await guild.fetch_member(
                payload.user_id
            )
        except discord.HTTPException:
            return

    # 공대장 역할 확인
    if not is_raid_leader(member):
        print(
            f"[메시지 전달] 권한 없음 "
            f"- 사용자: {member}"
        )
        return

    # 중복 전달 방지
    message_id = payload.message_id

    if message_id in forwarded_messages:
        return

    source_channel = bot.get_channel(
        SOURCE_CHANNEL_ID
    )

    target_channel = bot.get_channel(
        TARGET_CHANNEL_ID
    )

    if source_channel is None or target_channel is None:
        print("[메시지 전달] 채널을 찾을 수 없습니다.")
        return

    try:
        source_message = await source_channel.fetch_message(
            message_id
        )

        # 봇이 작성한 메시지는 전달하지 않음
        if source_message.author.bot:
            return

        # 본문과 이미지 첨부파일
        content = source_message.content or None

        files = []

        for attachment in source_message.attachments:
            file = await attachment.to_file()
            files.append(file)

        # 공개 채널로 전달
        await target_channel.send(
            content=content,
            files=files if files else None,
            allowed_mentions=discord.AllowedMentions.none()
        )

        forwarded_messages.add(message_id)

        print(
            f"[메시지 전달] 성공 "
            f"- 메시지 ID: {message_id} "
            f"- 전달자: {member}"
        )

    except discord.Forbidden:
        print("[메시지 전달] 채널 권한이 없습니다.")

    except discord.NotFound:
        print("[메시지 전달] 원본 메시지를 찾을 수 없습니다.")

    except discord.HTTPException as e:
        print(f"[메시지 전달] 전송 오류: {e}")

    except Exception as e:
        print(f"[메시지 전달] 알 수 없는 오류: {e}")


# ==========================================
# 봇 이벤트 등록
# ==========================================

def setup_message_forward(bot):

    @bot.listen("on_message")
    async def message_forward_on_message(message):
        await handle_source_message(message)

    @bot.listen("on_raw_reaction_add")
    async def message_forward_on_reaction(payload):
        await handle_forward_reaction(
            payload,
            bot
        )

    print("[메시지 전달] 기능 등록 완료")
