import discord
from discord.ext import commands
from discord import app_commands
import os
import json
import datetime
import secrets
from dotenv import load_dotenv

load_dotenv()

# 設定
WEB_AUTH_FILE = "web_auth_tokens.json"  # Web認証トークン管理
PENDING_ORDERS_FILE = "pending_orders.json"  # 購入申請の状態
PAYPAY_CHANNEL_FILE = "paypay_notify_channel.json"  # PayPay通知チャンネル設定

# Botの設定
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# プレフィックスコマンドとスラッシュコマンドの両方を使用
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

@bot.event
async def on_guild_join(guild):
    """サーバーに参加したときにコマンドを同期"""
    try:
        await bot.tree.sync(guild=guild)
        print(f'🔄 {guild.name} でコマンドを同期しました')
    except Exception as e:
        print(f'❌ {guild.name} での同期エラー: {e}')

# ===== Web認証用関数 =====

def load_web_auth_tokens() -> dict:
    try:
        with open(WEB_AUTH_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"⚠️ Web認証トークンの読み込みに失敗しました: {e}")
        return {}


def persist_web_auth_tokens(tokens: dict):
    try:
        with open(WEB_AUTH_FILE, "w", encoding="utf-8") as f:
            json.dump(tokens, f)
    except Exception as e:
        print(f"⚠️ Web認証トークンの保存に失敗しました: {e}")


def generate_web_auth_token(user_id: int, user_name: str) -> str:
    """Web認証用トークンを生成"""
    token = secrets.token_urlsafe(32)
    
    tokens = load_web_auth_tokens()
    tokens[token] = {
        "user_id": user_id,
        "user_name": user_name,
        "created_at": datetime.datetime.now().isoformat(),
        "expires_at": (datetime.datetime.now() + datetime.timedelta(hours=1)).isoformat()
    }
    persist_web_auth_tokens(tokens)
    return token


def validate_web_auth_token(token: str) -> dict | None:
    """Web認証トークンを検証"""
    tokens = load_web_auth_tokens()
    if token not in tokens:
        return None
    
    token_data = tokens[token]
    expires_at = datetime.datetime.fromisoformat(token_data["expires_at"])
    
    if datetime.datetime.now() > expires_at:
        # 期限切れトークンを削除
        del tokens[token]
        persist_web_auth_tokens(tokens)
        return None
    
    return token_data


# ===== 注文管理用関数 =====

def load_pending_orders() -> dict:
    try:
        with open(PENDING_ORDERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"⚠️ 購入申請データの読み込みに失敗しました: {e}")
        return {}


def persist_pending_orders(orders: dict):
    try:
        with open(PENDING_ORDERS_FILE, "w", encoding="utf-8") as f:
            json.dump(orders, f)
    except Exception as e:
        print(f"⚠️ 購入申請データの保存に失敗しました: {e}")


def get_order(order_id: str) -> dict | None:
    return load_pending_orders().get(order_id)


def upsert_order(order_id: str, data: dict):
    orders = load_pending_orders()
    orders[order_id] = data
    persist_pending_orders(orders)


def update_order_status(order_id: str, status: str):
    orders = load_pending_orders()
    if order_id not in orders:
        return
    orders[order_id]["status"] = status
    persist_pending_orders(orders)


def load_paypay_notify_channels() -> dict[int, int]:
    try:
        with open(PAYPAY_CHANNEL_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
            return {int(k): int(v) for k, v in raw.items()}
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"⚠️ PayPay通知チャンネル設定の読み込みに失敗しました: {e}")
        return {}


def get_paypay_notify_channel_id(guild_id: int) -> int | None:
    return load_paypay_notify_channels().get(int(guild_id))


def is_guild_manager(interaction: discord.Interaction) -> bool:
    if not interaction.guild: return False
    return interaction.user.guild_permissions.administrator or interaction.user.guild_permissions.manage_guild


# ===== 管理者用注文ビュー =====

class AdminOrderView(discord.ui.View):
    def __init__(self, order_id: str):
        super().__init__(timeout=None)
        self.order_id = order_id

        self.add_item(discord.ui.Button(label="ロール付与 & 承認", style=discord.ButtonStyle.success, custom_id=f"order_role_approve:{order_id}", emoji="👑"))
        self.add_item(discord.ui.Button(label="却下", style=discord.ButtonStyle.danger, custom_id=f"order_decline:{order_id}"))

    @discord.ui.button(label="ロール付与 & 承認", style=discord.ButtonStyle.success, custom_id="auto_role_btn", emoji="👑")
    async def approve_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_guild_manager(interaction):
            return await interaction.response.send_message("管理者権限が必要です。", ephemeral=True)
        
        order = get_order(self.order_id)
        if not order or order.get("status") != "pending":
            return await interaction.response.send_message("既に処理済みか、データがありません。", ephemeral=True)

        guild = interaction.guild
        buyer_id = int(order["buyer_id"])
        member = guild.get_member(buyer_id) or await guild.fetch_member(buyer_id)
        
        # ロール抽出 (selected_optionから)
        import re
        role_match = re.search(r"Role: (\d+)", order.get("selected_option", ""))
        if not role_match:
            return await interaction.response.send_message("この商品にはロールIDが紐付いていません。", ephemeral=True)

        role_id = int(role_match.group(1))
        role = guild.get_role(role_id)
        if not role:
            return await interaction.response.send_message("ロールが見つかりませんでした。", ephemeral=True)

        try:
            await member.add_roles(role, reason="Webストア注文承認")
            update_order_status(self.order_id, "fulfilled")
            
            # メッセージ更新
            emb = interaction.message.embeds[0]
            emb.color = discord.Color.gold()
            emb.set_footer(text="ステータス: 承認済み (ロール付与完了)")
            await interaction.message.edit(embed=emb, view=None)
            
            await interaction.response.send_message(f"✅ {member.mention} に {role.name} を付与しました。", ephemeral=True)
            try: await member.send(f"🌟 ご購入ありがとうございます！**{role.name}** ロールを付与しました。")
            except: pass
        except Exception as e:
            await interaction.response.send_message(f"❌ エラー: {e}", ephemeral=True)

    @discord.ui.button(label="却下", style=discord.ButtonStyle.danger, custom_id="decline_btn")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_guild_manager(interaction):
            return await interaction.response.send_message("管理者権限が必要です。", ephemeral=True)
        
        update_order_status(self.order_id, "declined")
        emb = interaction.message.embeds[0]
        emb.color = discord.Color.red()
        emb.set_footer(text="ステータス: 却下済み")
        await interaction.message.edit(embed=emb, view=None)
        await interaction.response.send_message("注文を却下しました。", ephemeral=True)

@bot.event
async def on_ready():
    """Botが起動したときに呼ばれるイベント"""
    print(f'✅ ログイン: {bot.user.name}')
    print(f'🆔 Bot ID: {bot.user.id}')
    print(f'📡 接続サーバー数: {len(bot.guilds)}')
    
    # 永続ビューの再登録
    for oid, odata in load_pending_orders().items():
        if odata.get("status") == "pending":
            bot.add_view(AdminOrderView(oid))

    # スラッシュコマンドを同期
    try:
        await bot.tree.sync()
        print('🔄 コマンドを同期しました')
        
    except Exception as e:
        print(f'❌ 初期化エラー: {e}')
    print('------')

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    await bot.process_commands(message)

# ===== エラーハンドリング =====

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ 引数が足りません！使い方はこちら:\n`{ctx.prefix}{ctx.command.name} {ctx.command.signature}`")
    elif isinstance(error, commands.BadArgument):
        await ctx.send(f"❌ 入力された値が正しくありません。")
    elif isinstance(error, commands.CommandNotFound):
        pass
    else:
        print(f"⚠️ エラー: {error}")

# ===== ヘルプコマンド =====

async def send_help(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🌌 BOT2 MENU",
        description="新しいボットのメニューです。",
        color=0x2b2d31
    )
    embed.add_field(name="🛠️ Utility", value="`/help`, `/web_auth`, `/sync` ", inline=False)
    embed.set_footer(text="すべてのコマンドはスラッシュコマンド '/' で利用可能です。")
    
    if isinstance(interaction, discord.Interaction):
        await interaction.response.send_message(embed=embed)
    else:
        await interaction.send(embed=embed)

@bot.command(name='help')
async def help_ctx(ctx): 
    await send_help(ctx)

@bot.tree.command(name='help', description='コマンドを表示します')
async def help_slash(interaction: discord.Interaction): 
    await send_help(interaction)

# ===== テストコマンド =====

@bot.tree.command(name='ping', description='応答速度')
async def ping_slash(interaction: discord.Interaction):
    await interaction.response.send_message(f'🏓 Pong! {round(bot.latency * 1000)}ms')

@bot.tree.command(name='userinfo', description='ユーザー情報を表示')
async def userinfo_slash(interaction: discord.Interaction, user: discord.User = None):
    target_user = user or interaction.user
    embed = discord.Embed(title=f'{target_user.display_name}の情報', color=0x2b2d31)
    embed.add_field(name="ユーザーID", value=target_user.id, inline=True)
    embed.add_field(name="アカウント作成日", value=target_user.created_at.strftime('%Y年%m月%d日'), inline=True)
    embed.set_thumbnail(url=target_user.display_avatar.url)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name='sync', description='コマンドを手動で同期します（管理者のみ）')
async def sync_slash(interaction: discord.Interaction):
    """コマンドを手動で同期"""
    # 管理者チェック
    if interaction.user.id != 1488225308804120759:
        await interaction.response.send_message("このコマンドは管理者のみ使用できます。", ephemeral=True)
        return
    
    await interaction.response.defer(ephemeral=True)
    
    try:
        # グローバル同期
        synced = await bot.tree.sync()
        await interaction.followup.send(f"✅ グローバルコマンドを同期しました: {len(synced)}個", ephemeral=True)
        
        # サーバー同期
        if interaction.guild:
            guild_synced = await bot.tree.sync(guild=interaction.guild)
            await interaction.followup.send(f"✅ {interaction.guild.name} でコマンドを同期しました: {len(guild_synced)}個", ephemeral=True)
            
    except Exception as e:
        await interaction.followup.send(f"❌ 同期エラー: {e}", ephemeral=True)

@bot.tree.command(name='set_paypay_channel', description='PayPay通知用チャンネルを設定します')
@app_commands.checks.has_permissions(administrator=True)
async def set_paypay_channel_slash(interaction: discord.Interaction, channel: discord.TextChannel):
    """通知先チャンネルを保存"""
    try:
        persist_paypay_notify_channel(interaction.guild.id, channel.id)
        await interaction.response.send_message(f"✅ {channel.mention} を通知チャンネルに設定しました。")
    except Exception as e:
        await interaction.response.send_message(f"❌ エラー: {e}", ephemeral=True)

def persist_paypay_notify_channel(guild_id: int, channel_id: int):
    data = load_paypay_notify_channels()
    data[int(guild_id)] = int(channel_id)
    with open(PAYPAY_CHANNEL_FILE, "w", encoding="utf-8") as f:
        json.dump({str(k): v for k, v in data.items()}, f)

@bot.tree.command(name='web_auth', description='Webサイト用の認証トークンを取得します')
async def web_auth_slash(interaction: discord.Interaction):
    """Webサイト用認証トークンを生成してDMに送信"""
    try:
        await interaction.response.defer(ephemeral=True)
        
        # トークンを生成
        token = generate_web_auth_token(interaction.user.id, str(interaction.user))
        
        # WebサイトのURLを構築
        web_url = "https://prim.gg"  # Cloudflare Pages用URL
        
        # DMでトークンを送信
        embed = discord.Embed(
            title="🔐 Webサイト認証トークン",
            description="以下のトークンをWebサイトで入力して認証してください。",
            color=0x5865F2
        )
        embed.add_field(name="認証トークン", value=f"```\n{token}\n```", inline=False)
        embed.add_field(name="Webサイト", value=f"[アクセスする]({web_url})", inline=False)
        embed.add_field(name="有効期限", value="1時間", inline=True)
        embed.set_footer(text="このトークンを共有しないでください")
        
        try:
            await interaction.user.send(embed=embed)
            await interaction.followup.send("認証トークンをDMに送信しました。", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("DMを送信できませんでした。プライバシー設定を確認してください。", ephemeral=True)
            
    except Exception as e:
        await interaction.followup.send(f"エラーが発生しました: {e}", ephemeral=True)

# ===== Webストア連携 API (Flask) =====

from flask import Flask, request, jsonify
import threading

app = Flask(__name__)

@app.route('/api/webhook-order', methods=['POST'])
def handle_webstore_order():
    try:
        data = request.get_json()
        order_id = secrets.token_hex(8)
        
        async def send_order_notice():
            if not bot.guilds: return
            guild = bot.guilds[0]
            ch_id = get_paypay_notify_channel_id(guild.id)
            channel = bot.get_channel(ch_id) if ch_id else None
            if not channel: return

            buyer_id = int(data.get('userId', 0))
            items = data.get('items', [])
            item_details = [f"{i['name']}{f' (Role: {i.get('roleId')})' if i.get('roleId') else ''}" for i in items]
            
            embed = discord.Embed(title="🛒 Webストア受注 (PayPay)", color=0x3B82F6)
            embed.add_field(name="ユーザー", value=f"<@{buyer_id}>", inline=False)
            embed.add_field(name="商品", value="\n".join(item_details), inline=False)
            embed.add_field(name="PayPayリンク", value=f"```{data.get('paypayLink')}```", inline=False)
            
            view = AdminOrderView(order_id)
            msg = await channel.send(embed=embed, view=view)
            
            upsert_order(order_id, {
                "guild_id": guild.id, "channel_id": channel.id, "message_id": msg.id,
                "buyer_id": buyer_id, "selected_option": ", ".join(item_details), "status": "pending"
            })

        bot.loop.create_task(send_order_notice())
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

def start_server():
    app.run(host='0.0.0.0', port=8000)

threading.Thread(target=start_server, daemon=True).start()

# ===== Botの起動 =====

if __name__ == '__main__':
    token = os.getenv('DISCORD_TOKEN2')
    if not token:
        print("❌ DISCORD_TOKEN2 が設定されていません。")
    else:
        bot.run(token)
