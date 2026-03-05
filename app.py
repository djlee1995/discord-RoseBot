import os
import sys
import traceback
import subprocess
import shutil
import discord
from discord.ext import commands
from music_module import setup_music  # music_module.py 사용

# =========================
# 기본 경로
# =========================
# PyInstaller 실행 여부 확인
if getattr(sys, "frozen", False):
    RESOURCE_DIR = sys._MEIPASS                 # exe 안 리소스 (ffmpeg.exe, opus.dll)
    BASE_DIR = os.path.dirname(sys.executable)  # exe가 있는 폴더 (yt-dlp.exe)
else:
    RESOURCE_DIR = os.path.dirname(os.path.abspath(__file__))
    BASE_DIR = RESOURCE_DIR

IS_WINDOWS = sys.platform.startswith("win")

# =========================
# 실행 파일 경로 결정 (윈도우/리눅스 공용)
# =========================
def resolve_bin(name_win: str, name_linux: str, bundled_dir: str, bundled_name: str):
    """
    - Windows: PyInstaller 번들 or BASE_DIR/RESOURCE_DIR에 있는 exe 우선 사용
    - Linux(Docker): PATH에서 which로 찾음
    """
    if IS_WINDOWS:
        bundled = os.path.join(bundled_dir, bundled_name)
        if os.path.exists(bundled):
            return bundled
        # PATH 또는 현재 디렉토리에 있을 수도 있음
        return name_win
    else:
        return shutil.which(name_linux) or name_linux

FFMPEG_BIN = resolve_bin("ffmpeg.exe", "ffmpeg", RESOURCE_DIR, "ffmpeg.exe")
YTDLP_BIN  = resolve_bin("yt-dlp.exe", "yt-dlp", BASE_DIR, "yt-dlp.exe")

print("=== DEBUG: starting ===")
print("RESOURCE_DIR:", RESOURCE_DIR)
print("BASE_DIR    :", BASE_DIR)
print("IS_WINDOWS  :", IS_WINDOWS)
print("FFMPEG_BIN  :", FFMPEG_BIN)
print("YTDLP_BIN   :", YTDLP_BIN)
print("PYTHON:", sys.executable)
print("PYTHON VERSION:", sys.version)
print("DISCORD.PY VERSION:", discord.__version__)
print("DISCORD.PY PATH:", discord.__file__)

# =========================
# yt-dlp 자동 업데이트 (윈도우 exe 배포에서만)
# =========================
def update_ytdlp():
    # Docker/Linux에서는 pip로 설치한 yt-dlp를 쓰므로 업데이트 로직 불필요
    if not IS_WINDOWS:
        return

    ytdlp_path = os.path.join(BASE_DIR, "yt-dlp.exe")
    if not os.path.exists(ytdlp_path):
        print("⚠️ yt-dlp.exe 파일이 없습니다! (윈도우 exe 배포 시 BASE_DIR에 필요)")
        return

    try:
        print("🔄 yt-dlp 업데이트 확인 중...")
        subprocess.run([ytdlp_path, "-U"], check=True)
        print("✅ yt-dlp 최신 버전 유지 완료")
    except Exception as e:
        print(f"⚠️ yt-dlp 업데이트 실패: {e}")

# =========================
# Opus 로드 (윈도우에서만)
# =========================
if IS_WINDOWS:
    OPUS_PATH = os.path.join(RESOURCE_DIR, "opus.dll")  # 보통 _MEIPASS 쪽이 안전
    if not discord.opus.is_loaded():
        try:
            discord.opus.load_opus(OPUS_PATH)
            print("Opus loaded OK:", discord.opus.is_loaded())
        except Exception as e:
            print("Opus load failed:", e)
else:
    print("Linux/Docker 환경 -> opus.dll 수동 로드 스킵")

# =========================
# 봇 설정
# =========================
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True  # 필요 없으면 False로 줄이세요

bot = commands.Bot(command_prefix="##", intents=intents)

# 음악 커맨드 등록 (FFMPEG/YTDLP 경로를 모듈에 전달)
setup_music(bot, ffmpeg_bin=FFMPEG_BIN, ytdlp_bin=YTDLP_BIN)

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
    update_ytdlp()

    # ✅ 토큰은 무조건 환경변수로
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN 환경변수가 없습니다. (Cloudtype Secret에 등록하세요)")

    bot.run(token)