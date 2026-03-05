import os
import sys
import traceback
import shutil
import discord
from discord.ext import commands
from music_module import setup_music

# =========================
# 기본 경로
# =========================
if getattr(sys, "frozen", False):
    RESOURCE_DIR = sys._MEIPASS
    BASE_DIR = os.path.dirname(sys.executable)
else:
    RESOURCE_DIR = os.path.dirname(os.path.abspath(__file__))
    BASE_DIR = RESOURCE_DIR

IS_WINDOWS = sys.platform.startswith("win")

FFMPEG_BIN = "ffmpeg.exe" if IS_WINDOWS else "ffmpeg"
YTDLP_BIN = "yt-dlp.exe" if IS_WINDOWS else "yt-dlp"

print("=== DEBUG: starting ===")
print("RESOURCE_DIR:", RESOURCE_DIR)
print("BASE_DIR    :", BASE_DIR)
print("IS_WINDOWS  :", IS_WINDOWS)
print("FFMPEG BIN  :", FFMPEG_BIN, "->", shutil.which(FFMPEG_BIN))
print("YTDLP BIN   :", YTDLP_BIN, "->", shutil.which(YTDLP_BIN))
print("PYTHON:", sys.executable)
print("PYTHON VERSION:", sys.version)
print("DISCORD.PY VERSION:", discord.__version__)
print("DISCORD.PY PATH:", discord.__file__)

# =========================
# Opus 로드 (Windows에서만)
# =========================
if IS_WINDOWS:
    opus_path = os.path.join(BASE_DIR, "opus.dll")
    if not discord.opus.is_loaded():
        try:
            discord.opus.load_opus(opus_path)
            print("Opus loaded OK:", discord.opus.is_loaded())
        except Exception as e:
            print("Opus load failed:", e)
else:
    print("Linux container environment -> opus.dll manual load skipped")

# =========================
# 봇 설정
# =========================
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="##", intents=intents)

setup_music(bot)

# =========================
# 이벤트 핸들러
# =========================
@bot.event
async def on_disconnect():
    print("❌ Discord 연결 끊김 → 재연결 시도 중...")

@bot.event
async def on_resumed():
    print("✅ Discord 연결 복구됨")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ 이 명령어를 실행하려면 관리자 권한이 필요합니다.")
        return

    if isinstance(error, commands.CommandInvokeError):
        orig = getattr(error, "original", error)
        tb = "".join(traceback.format_exception(type(orig), orig, orig.__traceback__))
        print("\n===== Command Error Traceback =====\n", tb)
        await ctx.send(f"⚠️ 오류가 발생했습니다: {orig}")
        return

    print("Unhandled error:", error)

@bot.event
async def on_error(event, *args, **kwargs):
    print(f"❌ 이벤트 '{event}'에서 오류 발생: {args}, {kwargs}")

@bot.event
async def on_ready():
    print("봇이 로그인되었습니다!")
    print(f"봇 이름: {bot.user.name}")
    print(f"봇 ID: {bot.user.id}")

# =========================
# 실행
# =========================
if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN 환경변수가 없습니다.")

    bot.run(token)

