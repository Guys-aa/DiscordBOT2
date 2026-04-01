# 役割確認用チャンネル設定
@bot.tree.command(name='set_paypay_channel', description='PayPay通知用チャンネルを設定します')
@app_commands.checks.has_permissions(administrator=True)
async def set_paypay_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    from bot2 import PAYPAY_CHANNEL_FILE
    import json
    
    try:
        data = {}
        if os.path.exists(PAYPAY_CHANNEL_FILE):
            with open(PAYPAY_CHANNEL_FILE, "r") as f: data = json.load(f)
        data[str(interaction.guild.id)] = channel.id
        with open(PAYPAY_CHANNEL_FILE, "w") as f: json.dump(data, f)
        await interaction.response.send_message(f"✅ {channel.mention} を通知チャンネルに設定しました。")
    except Exception as e:
        await interaction.response.send_message(f"❌ エラー: {e}")
