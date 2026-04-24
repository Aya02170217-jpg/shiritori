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

# ゲーム状態の管理
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

# --- HTMLからの入室確認に応答するAPI ---
async def handle_index(request):
    try:
        # さっき作った index.html を読み込んで表示する機能です
        with open("index.html", "r", encoding="utf-8") as f:
            return web.Response(text=f.read(), content_type='text/html')
    except FileNotFoundError:
        return web.Response(text="index.htmlが見つかりません。ファイル名を確認してください。", status=404)

async def handle_check(request):
    return web.Response(text="OK")

async def start_server():
    app = web.Application()
    app.router.add_get('/', handle_index)  # ←これを追加しました（トップ画面用）
    app.router.add_get('/check', handle_check)
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"API Server started on port {port}")

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
    data = {}
    try:
        if os.path.exists(RECORD_FILE):
            with open(RECORD_FILE, "r") as f:
                data = json.load(f)
        current_best = data.get(str(guild_id), 0)
        if score > current_best:
            data[str(guild_id)] = score
            with open(RECORD_FILE, "w") as f:
                json.dump(data, f)
            return True
    except: pass
    return False

# --- メッセージお掃除 ---
async def cleanup_url_message():
    if game_state["url_msg_id"] and game_state["current_channel_id"]:
        channel = client.get_channel(game_state["current_channel_id"])
        if channel:
            try:
                msg = await channel.fetch_message(game_state["url_msg_id"])
                await msg.delete()
            except: pass
        game_state["url_msg_id"] = None

# --- ロック View ---
class ShiritoriView(discord.ui.View):
    def __init__(self, disabled=False):
        super().__init__(timeout=None)
        btn = discord.ui.Button(label="絵を描く", style=discord.ButtonStyle.primary, disabled=disabled)
        btn.callback = self.draw_callback
        self.add_item(btn)

    async def draw_callback(self, interaction: discord.Interaction):
        if game_state["is_locked"] and (time.time() - game_state["lock_time"] > 300):
            game_state["is_locked"] = False
            await cleanup_url_message()

        if game_state["is_locked"]:
            await interaction.response.send_message("現在他の人が挑戦中だよ！", ephemeral=True)
            return

        now = time.time()
        new_token = str(random.randint(100000, 999999))

        game_state.update({
            "is_locked": True,
            "lock_user_id": str(interaction.user.id),
            "lock_time": now,
            "current_channel_id": interaction.channel.id,
            "active_token": new_token
        })
        
        await interaction.response.edit_message(
            content=f"🔒 **{interaction.user.display_name}** さんが挑戦中！（最長5分）\n次は【 **{game_state['current_char']}** 】から始まる絵を描いてね！",
            view=ShiritoriView(disabled=True)
        )

        u = urllib.parse.quote(interaction.user.display_name)
        h = urllib.parse.quote(",".join(game_state["history"]))
        webhooks = await interaction.channel.webhooks()
        w = urllib.parse.quote(webhooks[0].url if webhooks else "")
        
        url = f"{GITHUB_URL}?user={u}&userId={interaction.user.id}&char={game_state['current_char']}&history={h}&webhook={w}&start={int(now)}&token={new_token}"
        
        msg = await interaction.followup.send(f"🎨 **{interaction.user.display_name}** さん専用URL（本人以外は入れません）:\n{url}", ephemeral=False)
        game_state["url_msg_id"] = msg.id
        asyncio.create_task(self.timer_task(now))

    async def timer_task(self, start_time):
        await asyncio.sleep(300)
        if game_state["is_locked"] and game_state["lock_time"] == start_time:
            game_state["is_locked"] = False
            game_state["active_token"] = None
            await cleanup_url_message()
            channel = client.get_channel(game_state["current_channel_id"])
            if channel:
                await channel.send("⏰ 5分経過したのでロックを解除したよ。次の人どうぞ！", view=ShiritoriView())

@client.event
async def on_ready():
    await start_server()
    for guild in client.guilds:
        tree.copy_global_to(guild=guild)
        await tree.sync(guild=guild)
    print(f"Bot準備完了: {client.user}")

@tree.command(name="start", description="ゲームを開始します")
async def start(interaction: discord.Interaction):
    webhooks = await interaction.channel.webhooks()
    if not webhooks: await interaction.channel.create_webhook(name="ShiritoriBot")
    
    best = get_best_record(interaction.guild_id)
    chars = "あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろ"
    game_state.update({
        "current_char": random.choice(chars),
        "history": [], 
        "is_locked": False, 
        "current_channel_id": interaction.channel.id, 
        "turn": 1,
        "current_answer_list": [],
        "active_token": None,
        "url_msg_id": None
    })
    await interaction.response.send_message(
        f"🎨 お絵描きしりとり開始！\n最初の文字は【 **{game_state['current_char']}** 】です！\n🏆 最高記録: {best} ターン",
        view=ShiritoriView()
    )

@tree.command(name="giveup", description="管理者リセット")
@app_commands.default_permissions(administrator=True)
async def giveup(interaction: discord.Interaction):
    await cleanup_url_message()
    chars = "あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろ"
    game_state.update({
        "current_char": random.choice(chars),
        "history": [],
        "is_locked": False,
        "turn": 1,
        "current_answer_list": [],
        "active_token": None
    })
    await interaction.response.send_message("📢 ゲームを完全にリセットしました。", view=ShiritoriView())

@client.event
async def on_message(message):
    if message.author == client.user: return
    if message.webhook_id and message.attachments:
        fname = message.attachments[0].filename
        if fname.startswith("ans_"):
            try:
                parts = fname.replace(".png", "").split("_")
                token_from_web = parts[4] if len(parts) > 4 else ""
                if game_state["active_token"] is None or token_from_web != game_state["active_token"]:
                    return 
                decoded_ans = bytes.fromhex(parts[1]).decode('utf-8')
                game_state["current_answer_list"] = decoded_ans.split('　')
                game_state["current_author_id"] = str(parts[3])
                return
            except: pass

    if game_state["is_locked"] and message.channel.id == game_state["current_channel_id"]:
        if message.content in game_state.get("current_answer_list", []):
            if str(message.author.id) == game_state["current_author_id"]:
                await message.reply("⚠️ 描いた本人は回答できないよ！")
                return
            await cleanup_url_message()
            game_state["active_token"] = None
            last_word = message.content
            next_char = last_word[-1]
            if next_char == "ー" and len(last_word) > 1: next_char = last_word[-2]
            vowels = {"ぁ":"あ","ぃ":"い","ぅ":"う","ぇ":"え","ぉ":"お","ゃ":"や","ゅ":"ゆ","ょ":"よ","っ":"つ","ゎ":"わ"}
            next_char = vowels.get(next_char, next_char)
            save_best_record(message.guild.id, game_state["turn"])
            game_state["history"].append(last_word)
            game_state["current_char"], game_state["is_locked"] = next_char, False
            game_state["turn"] += 1
            await message.reply(
                f"🎊 正解！「{last_word}」！\n次は【 **{game_state['current_char']}** 】から描いてね！",
                view=ShiritoriView()
            )

client.run(TOKEN)
