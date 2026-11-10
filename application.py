
import os
import sqlite3

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
# 데이터베이스 경로
# ==========================================

DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "invite_records.db",
)


# ==========================================
# 데이터베이스 초기화
# ==========================================

def init_invite_db():

    with sqlite3.connect(DB_PATH) as conn:

        # 입장자별 초대한 사람 기록
        conn.execute("""
            CREATE TABLE IF NOT EXISTS invite_records (
                member_id INTEGER PRIMARY KEY,
                inviter_id INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        # 초대 링크 생성 기록
        conn.execute("""
            CREATE TABLE IF NOT EXISTS invite_links (
                code TEXT PRIMARY KEY,
                guild_id INTEGER NOT NULL,
                inviter_id INTEGER,
                max_uses INTEGER,
                uses INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                used_by INTEGER,
                used_at TEXT
            )
        """)

        conn.commit()


# ==========================================
# 초대 링크 생성 기록
# ==========================================

def save_invite(
    guild_id,
    code,
    inviter_id,
    max_uses=None,
    uses=0,
):

    try:

        with sqlite3.connect(DB_PATH) as conn:

            conn.execute("""
                INSERT OR REPLACE INTO invite_links (
                    code,
                    guild_id,
                    inviter_id,
                    max_uses,
                    uses,
                    created_at,
                    used_by,
                    used_at
                )
                VALUES (?, ?, ?, ?, ?, ?, NULL, NULL)
            """, (
                str(code),
                int(guild_id),
                int(inviter_id) if inviter_id else None,
                max_uses,
                uses or 0,
                datetime.now().isoformat(),
            ))

            conn.commit()

        print(
            f"[초대 DB 저장] "
            f"{code} / 생성자: {inviter_id}"
        )

        return True

    except Exception as e:

        print(f"[초대 DB 저장 오류] {e}")

        return False


# ==========================================
# 삭제된 초대 링크 사용 처리
# ==========================================

def claim_deleted_invite(
    guild_id,
    deleted_codes,
    member_id,
):

    if not deleted_codes:
        return None

    try:

        with sqlite3.connect(DB_PATH) as conn:

            conn.execute("BEGIN IMMEDIATE")

            placeholders = ",".join(
                "?" for _ in deleted_codes
            )

            query = f"""
                SELECT code, inviter_id
                FROM invite_links
                WHERE guild_id = ?
                AND code IN ({placeholders})
                AND inviter_id IS NOT NULL
                AND used_by IS NULL
            """

            candidates = conn.execute(
                query,
                [int(guild_id)] + list(deleted_codes),
            ).fetchall()

            # 후보가 정확히 하나일 때만 연결
            if len(candidates) != 1:

                conn.rollback()

                if len(candidates) > 1:
                    print(
                        "[초대 DB] "
                        "삭제된 초대 링크가 여러 개라 "
                        "입장자 연결을 보류합니다."
                    )

                return None

            code, inviter_id = candidates[0]

            now = datetime.now().isoformat()

            # 초대 링크 사용 처리
            cursor = conn.execute("""
                UPDATE invite_links
                SET used_by = ?,
                    used_at = ?
                WHERE code = ?
                AND guild_id = ?
                AND used_by IS NULL
            """, (
                int(member_id),
                now,
                code,
                int(guild_id),
            ))

            if cursor.rowcount != 1:

                conn.rollback()
                return None

            # 입장자별 초대한 사람 기록
            conn.execute("""
                INSERT OR REPLACE INTO invite_records (
                    member_id,
                    inviter_id,
                    created_at
                )
                VALUES (?, ?, ?)
            """, (
                int(member_id),
                int(inviter_id),
                now,
            ))

            conn.commit()

        print(
            f"[초대 DB 연결] "
            f"{code} / "
            f"입장자: {member_id} / "
            f"초대한 사람: {inviter_id}"
        )

        return int(inviter_id)

    except Exception as e:

        print(f"[초대 DB 연결 오류] {e}")

        return None


# ==========================================
# 입장자 초대 기록 저장
# ==========================================

def save_inviter(member_id, inviter_id):

    try:

        with sqlite3.connect(DB_PATH) as conn:

            conn.execute("""
                INSERT OR REPLACE INTO invite_records
                (member_id, inviter_id, created_at)
                VALUES (?, ?, ?)
            """, (
                int(member_id),
                int(inviter_id),
                datetime.now().isoformat(),
            ))

            conn.commit()

        print(
            f"[DB 저장] {member_id} -> {inviter_id}"
        )

    except Exception as e:

        print(f"[초대 기록 저장 오류] {e}")


# ==========================================
# 입장자 초대 기록 조회
# ==========================================

def get_inviter(member_id):

    try:

        with sqlite3.connect(DB_PATH) as conn:

            result = conn.execute("""
                SELECT inviter_id
                FROM invite_records
                WHERE member_id = ?
            """, (
                int(member_id),
            )).fetchone()

        if result:
            return result[0]

    except Exception as e:

        print(f"[초대 기록 조회 오류] {e}")

    return None


# 데이터베이스 초기화
init_invite_db()


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

        # 손님 Discord ID로 초대자 조회
        inviter_id = get_inviter(member.id)

        success = await register_reservation(
            guild,
            member,
            data,
            inviter_id=inviter_id,
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
