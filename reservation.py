
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
# 예약 확정 가격 입력 모달
# ==========================================

class ReservationConfirmModal(discord.ui.Modal):

    def __init__(self, message, admin_id):

        super().__init__(
            title="예약 확정 - 가격 입력"
        )

        self.message = message
        self.admin_id = admin_id

        self.amount = discord.ui.TextInput(
            label="가격 (만 단위)",
            placeholder="예: 350",
            required=True,
            max_length=12,
        )

        self.add_item(self.amount)

    async def on_submit(self, interaction: discord.Interaction):

        if not is_admin(interaction.user):
            await interaction.response.send_message(
                "관리자만 사용할 수 있습니다.",
                ephemeral=True,
            )
            return

        amount_text = self.amount.value.strip().replace(",", "")

        if not amount_text.isdigit():
            await interaction.response.send_message(
                "가격은 0 이상의 숫자로 입력해 주세요.",
                ephemeral=True,
            )
            return

        amount = int(amount_text)

        if "상태 : ⏳ 예약대기" not in self.message.content:
            await interaction.response.send_message(
                "이미 처리된 예약입니다.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"입력한 가격: **{amount:,}만**\n\n"
            "반납 여부를 선택해 주세요.",
            view=ReturnStatusView(
                self.message,
                amount,
                self.admin_id,
            ),
            ephemeral=True,
        )


# ==========================================
# 반납 여부 선택 메뉴
# ==========================================

class ReturnStatusSelect(discord.ui.Select):

    def __init__(self, message, amount, admin_id):

        self.message = message
        self.amount = amount
        self.admin_id = admin_id

        options = [
            discord.SelectOption(
                label="반납",
                value="반납",
                description="반납하는 예약",
            ),
            discord.SelectOption(
                label="미반납",
                value="미반납",
                description="반납하지 않는 예약",
            ),
        ]

        super().__init__(
            placeholder="반납 여부를 선택하세요.",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):

        if not is_admin(interaction.user):
            await interaction.response.send_message(
                "관리자만 사용할 수 있습니다.",
                ephemeral=True,
            )
            return

        if interaction.user.id != self.admin_id:
            await interaction.response.send_message(
                "처음 예약 확정을 진행한 관리자만 처리할 수 있습니다.",
                ephemeral=True,
            )
            return

        content = self.message.content

        if "상태 : ⏳ 예약대기" not in content:
            await interaction.response.edit_message(
                content="이미 처리된 예약입니다.",
                view=None,
            )
            return

        return_status = self.values[0]

        # ==================================
        # 예약 정보 수정
        # ==================================

        content = re.sub(
            r"알\+올목\(.*?\)\s*:",
            f"알+올목({return_status}) :",
            content,
            count=1,
        )

        content = content.replace(
            "가격 미정",
            f"{self.amount:,}만",
            1,
        )

        content = content.replace(
            "상태 : ⏳ 예약대기",
            "상태 : ✅ 예약완료",
            1,
        )

        # ==================================
        # 예약 버튼 변경
        # ==================================

        reservation_view = ReservationView()

        for item in reservation_view.children:
            if isinstance(item, discord.ui.Button):
                item.label = "예약 취소"
                item.style = discord.ButtonStyle.danger

        await interaction.response.defer(ephemeral=True)

        await self.message.edit(
            content=content,
            view=reservation_view,
        )

        # ==================================
        # 신청자 확인
        # ==================================

        match = re.search(
            r"디코아이디\s*:\s*<@!?(\d+)>",
            content,
        )

        member = None

        if match and interaction.guild is not None:

            user_id = int(match.group(1))

            member = interaction.guild.get_member(user_id)

            if member is None:
                try:
                    member = await interaction.guild.fetch_member(user_id)
                except discord.HTTPException:
                    member = None

        if member is not None:

            try:
                await member.send(
                    "🎉 **예약이 확정되었습니다!**\n\n"
                    "신청해 주셔서 감사합니다.\n\n"
                    f"💰 가격: **{self.amount:,}만**\n"
                    f"📦 반납 여부: **{return_status}**\n\n"
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


class ReturnStatusView(discord.ui.View):

    def __init__(self, message, amount, admin_id):

        super().__init__(timeout=180)

        self.add_item(
            ReturnStatusSelect(
                message,
                amount,
                admin_id,
            )
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

        is_confirmed = (
            "상태 : ✅ 예약완료" in content
        )

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
                1,
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
        # 예약 확정 - 가격 입력
        # ==================================

        await interaction.response.send_modal(
            ReservationConfirmModal(
                message,
                interaction.user.id,
            )
        )


# ==========================================
# 예약현황 등록
# ==========================================

async def register_reservation(
    guild,
    member,
    data,
    inviter_id=None,
):

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

        # ==================================
        # 초대한 사람 확인
        # ==================================

        if inviter_id is not None:

            inviter = guild.get_member(
                inviter_id
            )

            if inviter is None:
                try:
                    inviter = await guild.fetch_member(
                        inviter_id
                    )
                except discord.HTTPException:
                    inviter = None

            inviter_text = (
                f"<@{inviter_id}>"
                if inviter is not None
                else f"<@{inviter_id}> (서버 미가입)"
            )

        else:
            inviter_text = "확인 불가"

        # ==================================
        # 예약현황 메시지
        # ==================================

        content = (
            f"**{date_text}**\n\n"
            f"알+올목(미정) : "
            f"{data.nickname} / "
            f"{data.level} / "
            f"{data.job} / "
            f"가격 미정\n\n"
            f"디코아이디 : {member.mention}\n"
            f"초대한 사람 : {inviter_text}\n"
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
