
import discord
from datetime import datetime

from config import (
    GUILD_ID,
    ADMIN_CHANNEL_ID,
    RULE_CHANNEL_ID,
)

from reservation import (
    is_admin,
    register_reservation,
)


# ==========================================
# 관리자 승인 / 거절 버튼
# ==========================================

class AdminApprovalView(discord.ui.View):

    def __init__(
        self,
        target_user_id,
        new_nickname,
        role_type,
        date_short,
    ):
        super().__init__(timeout=None)

        self.target_user_id = target_user_id
        self.new_nickname = new_nickname
        self.role_type = role_type
        self.date_short = date_short

    @discord.ui.button(
        label="승인",
        style=discord.ButtonStyle.success,
        custom_id="application_approve",
    )
    async def approve_callback(
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

        guild = interaction.client.get_guild(GUILD_ID)

        if guild is None:
            await interaction.response.send_message(
                "서버를 찾을 수 없습니다.",
                ephemeral=True,
            )
            return

        member = guild.get_member(self.target_user_id)

        if member is None:
            try:
                member = await guild.fetch_member(
                    self.target_user_id
                )
            except discord.HTTPException:
                await interaction.response.send_message(
                    "지원자를 찾을 수 없습니다.",
                    ephemeral=True,
                )
                return

        role = discord.utils.get(
            guild.roles,
            name=self.role_type,
        )

        if role is None:
            await interaction.response.send_message(
                f"'{self.role_type}' 역할을 찾을 수 없습니다.",
                ephemeral=True,
            )
            return

        try:
            await member.edit(
                nick=self.new_nickname
            )

            await member.add_roles(role)

        except discord.HTTPException:
            await interaction.response.send_message(
                "닉네임 또는 역할 적용에 실패했습니다.",
                ephemeral=True,
            )
            return

        for child in self.children:
            child.disabled = True

        embed = interaction.message.embeds[0]

        embed.color = discord.Color.green()
        embed.add_field(
            name="승인 상태",
            value=f"✅ 승인 완료 - {interaction.user.mention}",
            inline=False,
        )

        await interaction.response.edit_message(
            embed=embed,
            view=self,
        )

        try:
            await member.send(
                "🎉 신청하신 용병 지원이 관리자에 의해 **승인**되었습니다!\n"
                "닉네임과 역할이 적용되었습니다.\n\n"
                "📋 용병 규칙을 반드시 확인해 주세요.\n"
                f"<#{RULE_CHANNEL_ID}>"
            )

        except discord.HTTPException:
            pass

        await interaction.followup.send(
            "용병 지원을 승인했습니다.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="거절",
        style=discord.ButtonStyle.danger,
        custom_id="application_reject",
    )
    async def reject_callback(
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

        for child in self.children:
            child.disabled = True

        embed = interaction.message.embeds[0]

        embed.color = discord.Color.red()
        embed.add_field(
            name="승인 상태",
            value=f"❌ 거절 - {interaction.user.mention}",
            inline=False,
        )

        await interaction.response.edit_message(
            embed=embed,
            view=self,
        )

        await interaction.followup.send(
            "용병 지원을 거절했습니다.",
            ephemeral=True,
        )


# ==========================================
# 지원서 처리
# ==========================================

async def process_application(data):

    if bot is None:
        raise ValueError("Discord 봇이 연결되지 않았습니다.")

    guild = bot.get_guild(GUILD_ID)

    if guild is None:
        raise ValueError("Discord 서버를 찾을 수 없습니다.")

    try:
        discord_id = int(data.discord_id)
    except (ValueError, TypeError):
        raise ValueError("잘못된 디스코드 ID입니다.")

    member = guild.get_member(discord_id)

    if member is None:
        try:
            member = await guild.fetch_member(discord_id)
        except discord.HTTPException:
            raise ValueError(
                "서버에서 신청자를 찾을 수 없습니다."
            )

    try:
        apply_date = datetime.strptime(
            data.apply_date,
            "%Y-%m-%d",
        )
    except (ValueError, TypeError):
        raise ValueError("잘못된 참여 날짜입니다.")

    date_short = apply_date.strftime("%m.%d")

    if data.role_type not in ["손님", "용병"]:
        raise ValueError("잘못된 지원 유형입니다.")

    if not data.nickname.strip():
        raise ValueError("닉네임을 입력해 주세요.")

    if not data.job.strip():
        raise ValueError("직업을 입력해 주세요.")

    # 손님과 용병 모두 레벨 필수
    if data.level is None or not 1 <= data.level <= 300:
        raise ValueError("레벨은 1~300 사이로 입력해 주세요.")

    new_nickname = (
        f"[{data.role_type}]"
        f"[{data.job}]"
        f"[{date_short}]"
        f"{data.nickname.strip()}"
    )

    # ======================================
    # 손님 신청
    # ======================================

    if data.role_type == "손님":

        if data.amount is None:
            raise ValueError("가격을 입력해 주세요.")

        if data.amount < 0:
            raise ValueError("가격은 0 이상이어야 합니다.")

        if data.return_status not in ["반납", "미반납"]:
            raise ValueError("반납 여부를 선택해 주세요.")

        role = discord.utils.get(
            guild.roles,
            name="손님",
        )

        if role is None:
            raise ValueError(
                "손님 역할을 찾을 수 없습니다."
            )

        await member.edit(
            nick=new_nickname
        )

        await member.add_roles(role)

        success = await register_reservation(
            guild,
            member,
            data,
        )

        if not success:
            raise ValueError(
                "예약현황 등록에 실패했습니다."
            )

        return {
            "success": True,
            "message": "손님 지원이 완료되었습니다.",
        }

    # ======================================
    # 용병 신청
    # ======================================

    if data.role_type == "용병":

        channel = guild.get_channel(ADMIN_CHANNEL_ID)

        if channel is None:
            try:
                channel = await guild.fetch_channel(
                    ADMIN_CHANNEL_ID
                )
            except discord.HTTPException:
                raise ValueError(
                    "관리자 채널을 찾을 수 없습니다."
                )

        if not isinstance(channel, discord.TextChannel):
            raise ValueError(
                "관리자 채널이 올바르지 않습니다."
            )

        embed = discord.Embed(
            title="🚨 용병 지원 승인 대기 중",
            description=(
                f"**지원자:** {member.mention} ({member.name})\n"
                f"**인게임 닉네임:** {data.nickname}\n"
                f"**직업:** {data.job}\n"
                f"**레벨:** {data.level}\n"
                f"**지원 날짜:** {date_short}"
            ),
            color=discord.Color.orange(),
        )

        view = AdminApprovalView(
            target_user_id=member.id,
            new_nickname=new_nickname,
            role_type="용병",
            date_short=date_short,
        )

        await channel.send(
            embed=embed,
            view=view,
        )

        return {
            "success": True,
            "message": (
                "용병 지원이 접수되었습니다. "
                "관리자 승인을 기다려 주세요."
            ),
        }


# ==========================================
# 봇 연결
# ==========================================

bot = None


def set_bot(bot_instance):
    global bot
    bot = bot_instance
