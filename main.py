import discord
from discord import app_commands
import urllib.parse
import random
import json
import os
import asyncio
import time
from aiohttp import web

# --- 設定 ---
TOKEN = os.environ.get("DISCORD_TOKEN")
GITHUB_URL = "https://shiritori-bot-l248.onrender.com"
RECORD_FILE = "records.json"

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

game_state = {
    "current_char": "あ",
    "history": [],
    "is_locked": False,
    "lock_user_id": None,
    "lock_time": 0,
    "current_answer_list": [],
    "current_author_id": None,
    "current_channel_id": None,
    "turn": 0,
    "active_token": None,
    "url_msg_id": None
}

# --- サーバー設定（Render最適化版） ---
async def handle_index(request):
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            return web.Response(text=f.read(), content_type='text/html')
    except:
        return web.Response(text="index.html not found", status=404)

async def handle_check(request):
    # 100%返事を返すためのシンプル応答
    return web.Response(text="OK")

async def start_server():
    app = web.Application()
    app.router.add_get('/', handle_index)
    app.router.add_get('/check', handle_check)
    runner = web.AppRunner(app)
    await runner.setup()
    # Renderのポート指定に確実に合わせる
    port = int(os.environ.get("PORT", 10000)) 
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"Server started on port {port}")

# --- 記録管理 ---
def get_best_record(guild_id):
    try:
        if os.path.exists(RECORD_FILE):
            with open(RECORD_FILE, "r") as f:
                data = json.load(f)
                return data.get(str(guild_id), 0)
    except: pass
    return 0

def save_best_record(guild_id, score):
    try:
        data = {}
        if os.path.exists(RECORD_FILE):
            with open(RECORD_FILE, "r") as f:
                data = json.load(f)
        if score > data.get(str(guild_id), 0):
            data[str(guild_id)] = score
            with open(RECORD_FILE, "w") as f:
                json.dump(data, f)
    except: pass

async def cleanup_url_message():
    if game_state["url_msg_id"] and game_state["current_channel_id"]:
        channel = client.get_channel(game_state["current_channel_id"])
        if channel:
            try:
                msg = await channel.fetch_message(game_state["url_msg_id"])
                await msg.delete()
            except: pass
    game_state["url_msg_id"] = None

# --- メインロジック ---
class ShiritoriView(discord.ui.View):
    def __init__(self, disabled=False):
        super().__init__(timeout=None)
        btn = discord.ui.Button(label="絵を描く", style=discord.ButtonStyle.primary, disabled=disabled)
        btn.callback = self.draw_callback
        self.add_item(btn)

    async def draw_callback(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
        except: pass

        if game_state["is_locked"] and (time.time() - game_state["lock_time"] > 300):
            game_state["is_locked"] = False
            await cleanup_url_message()

        if game_state["is_locked"]:
            await interaction.followup.send("現在他の人が挑戦中だよ！", ephemeral=True)
            return

        now = time.time()
        new_token = str(random.randint(100000, 999999))
        webhooks = await interaction.channel.webhooks()
        w_url = webhooks[0].url if webhooks else ""

        game_state.update({
            "is_locked": True,
            "lock_user_id": str(interaction.user.id),
            "lock_time": now,
            "current_channel_id": interaction.channel.id,
            "active_token": new_token
        })

        p = {
            "user": interaction.user.display_name,
            "userId": interaction.user.id,
            "char": game_state['current_char'],
            "history": ",".join(game_state["history"]),
            "webhook": w_url,
            "start": int(now),
            "token": new_token
        }
        url = f"{GITHUB_URL}/?{urllib.parse.urlencode(p)}"
        
        try:
            msg = await interaction.followup.send(f"🎨 専用URL:\n{url}", ephemeral=False)
            game_state["url_msg_id"] = msg.id
        except: pass
        
        asyncio.create_task(self.timer_task(now))

    async def timer_task(self, st):
        await asyncio.sleep(300)
        if game_state["is_locked"] and game_state["lock_time"] == st:
            game_state["is_locked"] = False
            await cleanup_url_message()

@client.event
async def on_ready():
    await start_server()
    for guild in client.guilds:
        tree.copy_global_to(guild=guild)
        await tree.sync(guild=guild)
    print(f"Bot Ready: {client.user}")

@tree.command(name="start", description="開始")
async def start(interaction: discord.Interaction):
    try:
        webhooks = await interaction.channel.webhooks()
        if not webhooks: await interaction.channel.create_webhook(name="ShiritoriBot")
        best = get_best_record(interaction.guild_id)
        game_state.update({"current_char": random.choice("あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろ"), "history": [], "is_locked": False, "turn": 1})
        await interaction.response.send_message(f"🎨 開始！次は【{game_state['current_char']}】\n🏆 最高: {best}", view=ShiritoriView())
    except:
        await interaction.channel.send(f"🎨 開始！次は【{game_state['current_char']}】", view=ShiritoriView())

@tree.command(name="giveup", description="リセット")
async def giveup(interaction: discord.Interaction):
    await cleanup_url_message()
    game_state["is_locked"] = False
    await interaction.response.send_message("📢 リセットしました。", view=ShiritoriView())

@client.event
async def on_message(message):
    if message.author == client.user: return
    if message.webhook_id and message.attachments:
        try:
            parts = message.attachments[0].filename.replace(".png", "").split("_")
            if game_state.get("active_token") == parts[4]:
                game_state["current_answer_list"] = bytes.fromhex(parts[1]).decode('utf-8').split('　')
                game_state["current_author_id"] = str(parts[3])
        except: pass

    if game_state["is_locked"] and message.content in game_state.get("current_answer_list", []):
        if str(message.author.id) != game_state["current_author_id"]:
            await cleanup_url_message()
            last_word = message.content
            next_char = last_word[-1]
            if next_char == "ー": next_char = last_word[-2]
            next_char = {"ぁ":"あ","ぃ":"い","ぅ":"う","ぇ":"え","ぉ":"お","ゃ":"や","ゅ":"ゆ","ょ":"よ","っ":"つ","ゎ":"わ"}.get(next_char, next_char)
            save_best_record(message.guild.id, game_state["turn"])
            game_state.update({"current_char": next_char, "is_locked": False, "turn": game_state["turn"] + 1})
            game_state["history"].append(last_word)
            await message.reply(f"🎊 正解！次は【{next_char}】！", view=ShiritoriView())

client.run(TOKEN)
