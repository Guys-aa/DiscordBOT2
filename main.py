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

@bot.event
async def on_ready():
    """Botが起動したときに呼ばれるイベント"""
    print(f'✅ ログイン: {bot.user.name}')
    print(f'🆔 Bot ID: {bot.user.id}')
    print(f'📡 接続サーバー数: {len(bot.guilds)}')
    
    # スラッシュコマンドを同期
    try:
        # グローバル同期（時間がかかる）
        synced = await bot.tree.sync()
        print(f'🔄 グローバルコマンドを同期しました: {len(synced)}個')
        
        # 各サーバーでも同期（即時反映）
        for guild in bot.guilds:
            try:
                guild_synced = await bot.tree.sync(guild=guild)
                print(f'🔄 {guild.name} でコマンドを同期しました: {len(guild_synced)}個')
            except Exception as guild_error:
                print(f'❌ {guild.name} での同期エラー: {guild_error}')
                
    except Exception as e:
        print(f'❌ コマンド同期エラー: {e}')
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
    embed.add_field(name="🛠️ Utility", value="`/help`, `/web_auth` ", inline=False)
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

# ===== Botの起動 =====

if __name__ == '__main__':
    token = os.getenv('DISCORD_TOKEN2')  # 新しい環境変数名
    if not token:
        print("❌ DISCORD_TOKEN2 が設定されていません。.env ファイルを確認してください。")
    else:
        bot.run(token)
