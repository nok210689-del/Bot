
import re
from datetime import datetime

import discord

from config import (
    RESERVATION_CHANNEL_ID,
    ADMIN_ROLE_IDS,
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
# 예약 확정 / 취소 버튼
# ==========================================

class ReservationView(discord.ui.View):

    def __init__(self, confirmed=False):
        super().__init__(timeout=None)

        self.confirmed = confirmed

        button = discord.ui.Button(
            label="예약 취소" if confirmed else "예약 확정",
            style=(
                discord.ButtonStyle.danger
                if confirmed
                else discord.ButtonStyle.success
            ),
            custom_id="reservation_toggle",
        )

        button.callback = self.toggle_callback
        self.add_item(button)

    async def toggle_callback(self, interaction: discord.Interaction):

        if not is_admin(interaction.user):
            await interaction.response.send_message(
                "관리자만 사용할 수 있습니다.",
                ephemeral=True,
            )
            return

        message = interaction.message

        if message is None:
            await interaction.response.send_message(
                "예약 메시지를 찾을 수 없습니다.",
                ephemeral=True,
            )
            return

        match = re.search(
            r"디코아이디\s*:\s*<@!?(\d+)>",
            message.content,
        )

        if not match:
            await interaction.response.send_message(
                "신청자 정보를 찾을 수 없습니다.",
                ephemeral=True,
            )
            return

        user_id = int(match.group(1))

        confirmed = not self.confirmed

        status_text = (
            "상태 : ✅ 예약완료"
            if confirmed
            else "상태 : ⏳ 예약대기"
        )

        content = re.sub(
            r"상태\s*:\s*.*",
            status_text,
            message.content,
        )

        await interaction.response.edit_message(
            content=content,
            view=ReservationView(confirmed=confirmed),
        )

        try:
            user = interaction.client.get_user(user_id)

            if user is None:
                user = await interaction.client.fetch_user(user_id)

            if confirmed:
                dm_text = (
                    "✅ 예약이 확정되었습니다!\n"
                    "예약현황을 확인해 주세요."
                )
            else:
                dm_text = (
                    "⏳ 예약이 취소되었습니다.\n"
                    "자세한 내용은 공대 관리자에게 문의해 주세요."
                )

            await user.send(dm_text)

        except discord.HTTPException:
            pass

        result_text = (
            "예약을 확정했습니다."
            if confirmed
            else "예약을 취소했습니다."
        )

        await interaction.followup.send(
            result_text,
            ephemeral=True,
        )


# ==========================================
# 예약 등록
# ==========================================

async def register_reservation(guild, member, data):

    channel = guild.get_channel(RESERVATION_CHANNEL_ID)

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

        date_text = (
            f"{apply_date.month}/{apply_date.day} "
            f"({['월', '화', '수', '목', '금', '토', '일'][apply_date.weekday()]})"
        )

        return_text = (
            f"반납 : {data.return_status}"
        )

        content = (
            f"**{date_text}**\n\n"
            f"알+올목({return_text}) : "
            f"{data.nickname} / "
            f"{data.level} / "
            f"{data.job} / "
            f"{data.amount:,}\n\n"
            f"디코아이디 : <@{member.id}>\n\n"
            f"상태 : ⏳ 예약대기"
        )

        await channel.send(
            content,
            view=ReservationView(),
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
            ),
        )

        return True

    except (ValueError, discord.HTTPException):
        return False
