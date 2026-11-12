
import re
from datetime import datetime

import discord

from config import (
    RESERVATION_CHANNEL_ID,
    ADMIN_ROLE_IDS,
    PARTY_MEMBER_ROLE_IDS,
)


# ==========================================
# 예약 상태
# ==========================================

STATUS_WAITING = "예약대기"
STATUS_CONFIRMED = "예약완료"

DM_SENT_MARKER = "예약 알림 발송 완료"


# ==========================================
# 관리자 전용 권한 확인
# 용병 승인 / 거절
# ==========================================

def is_admin(member):

    if not isinstance(member, discord.Member):
        return False

    return any(
        role.id in ADMIN_ROLE_IDS
        for role in member.roles
    )


# ==========================================
# 예약 관리 권한 확인
# 공대장 / 관리자 / 공대원
# 용병 제외
# ==========================================

def can_manage_reservation(member):

    if not isinstance(member, discord.Member):
        return False

    allowed_roles = (
        ADMIN_ROLE_IDS
        + PARTY_MEMBER_ROLE_IDS
    )

    return any(
        role.id in allowed_roles
        for role in member.roles
    )


# ==========================================
# Embed 필드 수정
# ==========================================

def set_embed_field(embed, name, value):

    for index, field in enumerate(embed.fields):

        if field.name == name:

            embed.set_field_at(
                index,
                name=name,
                value=value,
                inline=field.inline,
            )

            return

    embed.add_field(
        name=name,
        value=value,
        inline=True,
    )


def get_embed_field(embed, name):

    for field in embed.fields:

        if field.name == name:
            return field.value

    return None


def get_reservation_embed(message):

    if not message.embeds:
        return None

    return discord.Embed.from_dict(
        message.embeds[0].to_dict()
    )


def get_applicant_id(embed):

    applicant = get_embed_field(
        embed,
        "신청자",
    )

    if not applicant:
        return None

    match = re.search(
        r"<@!?(\d+)>",
        applicant,
    )

    if not match:
        return None

    return int(match.group(1))


# ==========================================
# 예약 확정 가격 입력 모달
# ==========================================

class ReservationConfirmModal(discord.ui.Modal):

    def __init__(self, message, user_id):

        super().__init__(
            title="예약 확정 - 가격 입력"
        )

        self.message = message
        self.user_id = user_id

        self.amount = discord.ui.TextInput(
            label="가격 (만 단위)",
            placeholder="예: 350",
            required=True,
            max_length=12,
        )

        self.add_item(self.amount)

    async def on_submit(self, interaction: discord.Interaction):

        if not can_manage_reservation(interaction.user):
            await interaction.response.send_message(
                "공대원 또는 관리자만 사용할 수 있습니다.",
                ephemeral=True,
            )
            return

        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "처음 예약 확정을 진행한 사용자만 처리할 수 있습니다.",
                ephemeral=True,
            )
            return

        amount_text = (
            self.amount.value.strip().replace(",", "")
        )

        if not amount_text.isdigit():
            await interaction.response.send_message(
                "가격은 0 이상의 숫자로 입력해 주세요.",
                ephemeral=True,
            )
            return

        amount = int(amount_text)

        embed = get_reservation_embed(
            self.message
        )

        if embed is None:
            await interaction.response.send_message(
                "예약 정보를 찾을 수 없습니다.",
                ephemeral=True,
            )
            return

        if get_embed_field(embed, "상태") != STATUS_WAITING:
            await interaction.response.send_message(
                "이미 처리된 예약입니다.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"입력한 가격: **{amount:,}만**\n\n"
            "알버프 여부를 선택해 주세요.",
            view=ReturnStatusView(
                self.message,
                amount,
                self.user_id,
            ),
            ephemeral=True,
        )


# ==========================================
# 알버프 선택 메뉴
# ==========================================

class ReturnStatusSelect(discord.ui.Select):

    def __init__(self, message, amount, user_id):

        self.message = message
        self.amount = amount
        self.user_id = user_id

        options = [
            discord.SelectOption(
                label="반납",
                value="반납",
                description="알버프 반납",
            ),
            discord.SelectOption(
                label="미반납",
                value="미반납",
                description="알버프 미반납",
            ),
        ]

        super().__init__(
            placeholder="알버프 여부를 선택하세요.",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):

        if not can_manage_reservation(interaction.user):
            await interaction.response.send_message(
                "공대원 또는 관리자만 사용할 수 있습니다.",
                ephemeral=True,
            )
            return

        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "처음 예약 확정을 진행한 사용자만 처리할 수 있습니다.",
                ephemeral=True,
            )
            return

        embed = get_reservation_embed(
            self.message
        )

        if embed is None:
            await interaction.response.edit_message(
                content="예약 정보를 찾을 수 없습니다.",
                view=None,
            )
            return

        if get_embed_field(embed, "상태") != STATUS_WAITING:
            await interaction.response.edit_message(
                content="이미 처리된 예약입니다.",
                view=None,
            )
            return

        return_status = self.values[0]

        # ==================================
        # 예약 정보 수정
        # ==================================

        set_embed_field(
            embed,
            "알버프",
            return_status,
        )

        set_embed_field(
            embed,
            "가격",
            f"{self.amount:,}만",
        )

        set_embed_field(
            embed,
            "상태",
            STATUS_CONFIRMED,
        )

        # ==================================
        # 예약 버튼 변경
        # ==================================

        reservation_view = ReservationView()

        for item in reservation_view.children:

            if isinstance(item, discord.ui.Button):
                item.label = "예약 취소"
                item.style = discord.ButtonStyle.danger

        await interaction.response.defer(
            ephemeral=True
        )

        await self.message.edit(
            embed=embed,
            view=reservation_view,
        )

        # ==================================
        # 신청자 확인
        # ==================================

        user_id = get_applicant_id(embed)

        member = None

        if user_id and interaction.guild is not None:

            member = interaction.guild.get_member(
                user_id
            )

            if member is None:
                try:
                    member = await interaction.guild.fetch_member(
                        user_id
                    )
                except discord.HTTPException:
                    member = None

        # ==================================
        # 최초 확정 DM 발송
        # ==================================

        footer_text = embed.footer.text or ""

        already_sent = (
            DM_SENT_MARKER in footer_text
        )

        if member is not None and not already_sent:

            try:
                await member.send(
                    "🎉 **예약이 확정되었습니다!**\n\n"
                    "신청해 주셔서 감사합니다.\n\n"
                    f"💰 가격: **{self.amount:,}만**\n"
                    f"📦 알버프: **{return_status}**\n\n"
                    "📢 원활한 공대 진행을 위해 공지사항과 "
                    "환불 및 주의사항을 다시 한번 확인해 주세요.\n\n"
                    "당일 늦지 않게 참여 부탁드립니다.\n\n"
                    "감사합니다!"
                )

                embed.set_footer(
                    text=DM_SENT_MARKER
                )

                await self.message.edit(
                    embed=embed
                )

            except discord.HTTPException as e:
                print(f"[예약 확정 DM 발송 오류] {e}")

        await interaction.followup.send(
            "예약을 확정했습니다.",
            ephemeral=True,
        )


class ReturnStatusView(discord.ui.View):

    def __init__(self, message, amount, user_id):

        super().__init__(timeout=180)

        self.add_item(
            ReturnStatusSelect(
                message,
                amount,
                user_id,
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

        if not can_manage_reservation(interaction.user):
            await interaction.response.send_message(
                "공대원 또는 관리자만 사용할 수 있습니다.",
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

        embed = get_reservation_embed(message)

        if embed is None:
            await interaction.response.send_message(
                "예약 정보를 찾을 수 없습니다.",
                ephemeral=True,
            )
            return

        status = get_embed_field(
            embed,
            "상태",
        )

        # ==================================
        # 예약 취소
        # ==================================

        if status == STATUS_CONFIRMED:

            set_embed_field(
                embed,
                "상태",
                STATUS_WAITING,
            )

            set_embed_field(
                embed,
                "알버프",
                "미정",
            )

            set_embed_field(
                embed,
                "가격",
                "미정",
            )

            button.label = "예약 확정"
            button.style = discord.ButtonStyle.success

            await interaction.response.edit_message(
                embed=embed,
                view=self,
            )

            # 신청자 확인
            user_id = get_applicant_id(embed)

            member = None

            if user_id and interaction.guild is not None:

                member = interaction.guild.get_member(
                    user_id
                )

                if member is None:
                    try:
                        member = await interaction.guild.fetch_member(
                            user_id
                        )
                    except discord.HTTPException:
                        member = None

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

        if status != STATUS_WAITING:
            await interaction.response.send_message(
                "예약 상태를 확인할 수 없습니다.",
                ephemeral=True,
            )
            return

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
        # 예약현황 Embed
        # ==================================

        embed = discord.Embed(
            title=f"📅 {date_text}",
            color=discord.Color.orange(),
        )

        embed.add_field(
            name="닉네임",
            value=data.nickname,
            inline=True,
        )

        embed.add_field(
            name="레벨",
            value=str(data.level),
            inline=True,
        )

        embed.add_field(
            name="직업",
            value=data.job,
            inline=True,
        )

        embed.add_field(
            name="알버프",
            value="미정",
            inline=True,
        )

        embed.add_field(
            name="가격",
            value="미정",
            inline=True,
        )

        embed.add_field(
            name="신청자",
            value=member.mention,
            inline=False,
        )

        embed.add_field(
            name="초대한 사람",
            value=inviter_text,
            inline=False,
        )

        embed.add_field(
            name="상태",
            value=STATUS_WAITING,
            inline=False,
        )

        await channel.send(
            embed=embed,
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
