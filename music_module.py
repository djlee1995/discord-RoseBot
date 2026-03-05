import discord
import asyncio
import re
import sys
import os
import subprocess
import shutil
from collections import deque
from discord.utils import get

# =========================
# 경로 설정
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

# PyInstaller exe 포함본 우선, 없으면 시스템 경로 사용
if IS_WINDOWS:
    bundled_ffmpeg = os.path.join(RESOURCE_DIR, "ffmpeg.exe")
    ffmpeg_path = bundled_ffmpeg if os.path.exists(bundled_ffmpeg) else FFMPEG_BIN
    bundled_ytdlp = os.path.join(BASE_DIR, "yt-dlp.exe")
    ytdlp_exe = bundled_ytdlp if os.path.exists(bundled_ytdlp) else YTDLP_BIN
else:
    ffmpeg_path = shutil.which("ffmpeg") or "ffmpeg"
    ytdlp_exe = shutil.which("yt-dlp") or "yt-dlp"

ffmpeg_options = {
    "executable": ffmpeg_path,
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin",
    "options": "-vn"
}

# Windows에서만 opus.dll 수동 로드
if IS_WINDOWS:
    OPUS_PATH = os.path.join(RESOURCE_DIR, "opus.dll")
    if not discord.opus.is_loaded():
        try:
            discord.opus.load_opus(OPUS_PATH)
        except OSError:
            raise RuntimeError(f"Opus DLL 로드 실패: {OPUS_PATH}")

# =========================
# yt-dlp 호출 함수
# =========================
def get_stream_info(query: str, allow_search: bool = True):
    if allow_search and not re.match(r"^(https?\:\/\/)?(www\.youtube\.com|youtu\.?be)\/.+$", query):
        query = f"ytsearch1:{query}"

    result = subprocess.run(
        [ytdlp_exe, "-f", "bestaudio/best", "--no-playlist", "--quiet",
         "--print", "url", "--print", "title", "--print", "original_url", query],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp 실행 실패: {result.stderr.strip()}")

    lines = result.stdout.strip().splitlines()
    if len(lines) < 3:
        raise RuntimeError("yt-dlp 결과가 올바르지 않습니다.")

    stream_url, title, original_url = lines
    return stream_url, title, original_url

def get_duration(url: str) -> int:
    result = subprocess.run(
        [ytdlp_exe, "--no-playlist", "--quiet", "--print", "duration", url],
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        return 0

    out = result.stdout.strip()
    return int(out) if out.isdigit() else 0

# =========================
# 상태 저장
# =========================
queues = {}
play_locks = {}
current_song = {}

def _get_lock(guild_id: int) -> asyncio.Lock:
    if guild_id not in play_locks:
        play_locks[guild_id] = asyncio.Lock()
    return play_locks[guild_id]

def _get_queue(guild_id: int) -> deque:
    if guild_id not in queues:
        queues[guild_id] = deque()
    return queues[guild_id]

async def _ensure_connected(bot, ctx):
    if not ctx.author.voice:
        await ctx.send("먼저 음성 채널에 들어가 주세요!")
        return None

    channel = ctx.author.voice.channel
    voice_client = get(bot.voice_clients, guild=ctx.guild)

    if voice_client is None:
        voice_client = await channel.connect(timeout=60, reconnect=False)
        return voice_client

    if voice_client.channel != channel:
        await voice_client.move_to(channel)

    return voice_client

# =========================
# 재생 로직
# =========================
async def _start_play(ctx, bot, item, seek_seconds=0):
    try:
        stream_url = item["stream_url"]
        title = item["title"]
        original_url = item["webpage_url"]

        voice_client = get(bot.voice_clients, guild=ctx.guild)
        if not voice_client or not voice_client.is_connected():
            return

        def after_playing(error):
            if error:
                asyncio.run_coroutine_threadsafe(
                    ctx.send(f"⚠️ 재생 중 오류 발생: {error}"), bot.loop
                )
            asyncio.run_coroutine_threadsafe(play_next(ctx, bot), bot.loop)

        ffmpeg_opts = ffmpeg_options.copy()
        if seek_seconds > 0:
            ffmpeg_opts["before_options"] += f" -ss {seek_seconds}"

        source = discord.FFmpegPCMAudio(stream_url, **ffmpeg_opts)
        voice_client.play(source, after=after_playing)

        current_song[ctx.guild.id] = {
            "title": title,
            "stream_url": stream_url,
            "webpage_url": original_url,
            "start_time": asyncio.get_running_loop().time(),
            "seek_offset": seek_seconds,
        }

        if seek_seconds > 0:
            await ctx.send(f"🎵 재생 중: {title} (⏩ {seek_seconds}초 지점)")
        else:
            await ctx.send(f"🎵 재생 중: {title}")

    except Exception as e:
        await ctx.send(f"⚠️ 재생 실패: {e}")
        asyncio.create_task(play_next(ctx, bot))

async def play_next(ctx, bot):
    guild_id = ctx.guild.id
    lock = _get_lock(guild_id)

    async with lock:
        voice_client = get(bot.voice_clients, guild=ctx.guild)
        if not voice_client or not voice_client.is_connected():
            return

        q = _get_queue(guild_id)

        if voice_client.is_playing() or voice_client.is_paused():
            return

        if not q:
            await ctx.send("🎵 대기열이 비어 음성 채널에서 나갑니다!")
            await voice_client.disconnect()
            current_song.pop(guild_id, None)
            return

        item = q.popleft()
        await _start_play(ctx, bot, item)

def setup_music(bot):
    @bot.command(name="재생")
    async def play(ctx, *, query: str):
        voice_client = await _ensure_connected(bot, ctx)
        if voice_client is None:
            return

        await ctx.send(f"🔍 '{query}' 확인 중...")

        try:
            stream_url, title, original_url = get_stream_info(query, allow_search=True)

            item = {
                "query": query,
                "title": title,
                "stream_url": stream_url,
                "webpage_url": original_url,
            }

            q = _get_queue(ctx.guild.id)
            q.append(item)
            await ctx.send(f"🎵 '{title}'을(를) 대기열에 추가했습니다. 위치: {len(q)}")

            if not voice_client.is_playing() and not voice_client.is_paused():
                await play_next(ctx, bot)

        except Exception as e:
            await ctx.send(f"⚠️ 오류 발생: {e}")

    @bot.command(name="링크")
    async def play_url(ctx, url: str):
        youtube_regex = re.compile(r"^(https?\:\/\/)?(www\.youtube\.com|youtu\.?be)\/.+$")
        if not youtube_regex.match(url):
            await ctx.send("⚠️ 유튜브 링크가 아닙니다.")
            return

        voice_client = await _ensure_connected(bot, ctx)
        if voice_client is None:
            return

        await ctx.send("🔗 유튜브 링크 확인 중...")

        try:
            stream_url, title, original_url = get_stream_info(url, allow_search=False)

            item = {
                "query": url,
                "title": title,
                "stream_url": stream_url,
                "webpage_url": original_url,
            }

            q = _get_queue(ctx.guild.id)
            q.append(item)
            await ctx.send(f"🎵 '{title}'을(를) 대기열에 추가했습니다. 위치: {len(q)}")

            if not voice_client.is_playing() and not voice_client.is_paused():
                await play_next(ctx, bot)

        except Exception as e:
            await ctx.send(f"⚠️ 오류 발생: {e}")

    @bot.command(name="대기열")
    async def queue_cmd(ctx):
        q = _get_queue(ctx.guild.id)
        if q:
            queue_list = [f"{i+1}. {item['title']}" for i, item in enumerate(q)]
            await ctx.send("🎶 대기열:\n" + "\n".join(queue_list))
        else:
            await ctx.send("대기열이 비었습니다!")

    @bot.command(name="스킵")
    async def skip(ctx):
        voice_client = get(bot.voice_clients, guild=ctx.guild)
        if voice_client and voice_client.is_playing():
            voice_client.stop()
            await ctx.send("⏭️ 현재 곡을 스킵합니다.")
        else:
            await ctx.send("재생 중인 곡이 없습니다.")

    @bot.command(name="일시정지")
    async def pause(ctx):
        voice_client = get(bot.voice_clients, guild=ctx.guild)
        if voice_client and voice_client.is_playing():
            voice_client.pause()
            await ctx.send("⏸️ 일시정지했습니다.")
        else:
            await ctx.send("재생 중이 아닙니다.")

    @bot.command(name="재개")
    async def resume(ctx):
        voice_client = get(bot.voice_clients, guild=ctx.guild)
        if voice_client and voice_client.is_paused():
            voice_client.resume()
            await ctx.send("▶️ 재개했습니다.")
        else:
            await ctx.send("일시정지 상태가 아닙니다.")

    @bot.command(name="정지")
    async def stop(ctx):
        guild_id = ctx.guild.id
        voice_client = get(bot.voice_clients, guild=ctx.guild)

        if voice_client and voice_client.is_connected():
            if voice_client.is_playing() or voice_client.is_paused():
                voice_client.stop()
            await voice_client.disconnect()

            queues[guild_id] = deque()
            current_song.pop(guild_id, None)
            await ctx.send("🛑 정지 및 대기열 초기화, 음성 채널 퇴장")
        else:
            await ctx.send("봇이 음성 채널에 연결되어 있지 않습니다!")

    @bot.command(name="빨리감기")
    async def fast_forward(ctx, seconds: int):
        guild_id = ctx.guild.id
        voice_client = get(bot.voice_clients, guild=ctx.guild)

        if not voice_client or not voice_client.is_playing():
            await ctx.send("⚠️ 현재 재생 중인 곡이 없습니다.")
            return

        if guild_id not in current_song:
            await ctx.send("⚠️ 현재 곡 정보를 찾을 수 없습니다.")
            return

        song = current_song[guild_id]
        elapsed = int(asyncio.get_running_loop().time() - song["start_time"])
        current_pos = song["seek_offset"] + elapsed
        new_pos = current_pos + seconds

        duration = get_duration(song["webpage_url"])

        await ctx.send(f"⏩ {seconds}초 빨리감기 중...")

        if duration and new_pos >= duration:
            voice_client.stop()
            await ctx.send("곡이 끝나 다음 곡으로 넘어갑니다.")
            return

        voice_client.stop()
        item = {
            "title": song["title"],
            "stream_url": song["stream_url"],
            "webpage_url": song["webpage_url"]
        }
        await _start_play(ctx, bot, item, seek_seconds=new_pos)
        await ctx.send(f"⏩ {seconds}초 빨리감기 (현재 {new_pos}/{duration}초)")

    @bot.command(name="되감기")
    async def rewind(ctx, seconds: int):
        guild_id = ctx.guild.id
        voice_client = get(bot.voice_clients, guild=ctx.guild)

        if not voice_client or not voice_client.is_playing():
            await ctx.send("⚠️ 현재 재생 중인 곡이 없습니다.")
            return

        if guild_id not in current_song:
            await ctx.send("⚠️ 현재 곡 정보를 찾을 수 없습니다.")
            return

        song = current_song[guild_id]
        elapsed = int(asyncio.get_running_loop().time() - song["start_time"])
        current_pos = song["seek_offset"] + elapsed
        new_pos = max(0, current_pos - seconds)

        duration = get_duration(song["webpage_url"])

        await ctx.send(f"⏪ {seconds}초 되감기 중...")

        voice_client.stop()
        item = {
            "title": song["title"],
            "stream_url": song["stream_url"],
            "webpage_url": song["webpage_url"]
        }
        await _start_play(ctx, bot, item, seek_seconds=new_pos)
        await ctx.send(f"⏪ {seconds}초 되감기 (현재 {new_pos}/{duration}초)")