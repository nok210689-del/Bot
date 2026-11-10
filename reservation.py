
import re
from datetime import datetime

import discord

from config import (
    RESERVATION_CHANNEL_ID,
    ADMIN_ROLE_IDS,
    NOTICE_CHANNEL_ID,
)


# ==========================================
# 관리자 확인
# ==========================================

def is_admin(member):

    if not isinstance(member, discord.Member):
        return False

    return any(
        role.id in ADMIN_ROLE_IDS
        for role in member.roles
    )


# ==========================================
# 예약현황 버튼
# ==========================================

class ReservationView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="예약 확정",
        style=discord.ButtonStyle.success,
        custom_id="reservation_toggle",
    )
    async def reservation_toggle(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        if not is_admin(interaction.user):
            await interaction.response.send_message(
                "관리자만 사용할 수 있습니다.",
                ephemeral=True,
            )
            return

        message = interaction.message

        if message is None:
            await interaction.response.send_message(
                "예약현황 메시지를 찾을 수 없습니다.",
                ephemeral=True,
            )
            return

        content = message.content

        # 현재 예약 상태 확인
        is_confirmed = "상태 : ✅ 예약완료" in content

        # 신청자 디스코드 ID 추출
        match = re.search(
            r"디코아이디\s*:\s*<@!?(\d+)>",
            content,
        )

        if not match:
            await interaction.response.send_message(
                "신청자 정보를 찾을 수 없습니다.",
                ephemeral=True,
            )
            return

        user_id = int(match.group(1))

        guild = interaction.guild

        if guild is None:
            await interaction.response.send_message(
                "서버 정보를 찾을 수 없습니다.",
                ephemeral=True,
            )
            return

        member = guild.get_member(user_id)

        if member is None:
            try:
                member = await guild.fetch_member(user_id)
            except discord.HTTPException:
                member = None

        # ==================================
        # 예약 취소
        # ==================================

        if is_confirmed:

            content = content.replace(
                "상태 : ✅ 예약완료",
                "상태 : ⏳ 예약대기",
            )

            button.label = "예약 확정"
            button.style = discord.ButtonStyle.success

            await interaction.response.edit_message(
                content=content,
                view=self,
            )

            if member is not None:
                try:
                    await member.send(
                        "⚠️ **예약이 취소되었습니다.**\n\n"
                        "예약 상태가 변경되었습니다.\n"
                        "자세한 내용은 공대 관리자에게 문의해 주세요."
                    )
                except discord.HTTPException:
                    pass

            return

        # ==================================
        # 예약 확정
        # ==================================

        content = content.replace(
            "상태 : ⏳ 예약대기",
            "상태 : ✅ 예약완료",
        )

        button.label = "예약 취소"
        button.style = discord.ButtonStyle.danger

        await interaction.response.edit_message(
            content=content,
            view=self,
        )

        if member is not None:

            try:
                await member.send(
                    "🎉 **예약이 확정되었습니다!**\n\n"
                    "신청해 주셔서 감사합니다.\n\n"
                    "📢 원활한 공대 진행을 위해 공지사항과 "
                    "환불 및 주의사항을 다시 한번 확인해 주세요.\n\n"
                    "당일 늦지 않게 참여 부탁드립니다.\n\n"
                    "감사합니다!"
                )

            except discord.HTTPException:
                pass

        await interaction.followup.send(
            "예약을 확정했습니다.",
            ephemeral=True,
        )


# ==========================================
# 예약현황 등록
# ==========================================

async def register_reservation(guild, member, data):

    channel = guild.get_channel(
        RESERVATION_CHANNEL_ID
    )

    if channel is None:
        try:
            channel = await guild.fetch_channel(
                RESERVATION_CHANNEL_ID
            )
        except discord.HTTPException:
            return False

    if not isinstance(channel, discord.TextChannel):
        return False

    try:
        apply_date = datetime.strptime(
            data.apply_date,
            "%Y-%m-%d",
        )

        date_text = apply_date.strftime(
            "%Y-%m-%d"
        )

        return_text = f"반납 : {data.return_status}"

        content = (
            f"**{date_text}**\n\n"
            f"알+올목({return_text}) : "
            f"{data.nickname} / "
            f"{data.level} / "
            f"{data.job} / "
            f"{data.amount:,}\n\n"
            f"디코아이디 : {member.mention}\n"
            f"상태 : ⏳ 예약대기"
        )

        await channel.send(
            content=content,
            view=ReservationView(),
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
            ),
        )

        return True

    except Exception as e:

        print(f"[예약현황 등록 오류] {e}")

        return False
