import asyncio
import threading
import struct
import flet as ft
import httpx
import pvporcupine
import speech_recognition as sr
import edge_tts
import pygame
import pyaudio

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

BASE_URL = "http://127.0.0.1:8000"
PICOVOICE_ACCESS_KEY = "0r2tm2DQ7r4g4sRbxBUaPceuv316wLJ1nsQ5h1HF5IVJA9F5SvR6Mg=="
WAKE_WORD = "bumblebee"  # must be built-in keyword


# ─────────────────────────────────────────────
# VOICE ENGINE (Industry Multi-Threaded)
# ─────────────────────────────────────────────

import threading
import queue
import struct
import pyaudio
import pvporcupine
import speech_recognition as sr
import pygame
import asyncio

MIC_INDEX = 13  # Stable mic from your device list


class VoiceEngine:
    def __init__(self, page, command_callback, status_callback):
        self.page = page
        self.command_callback = command_callback
        self.status_callback = status_callback

        self.running = True
        self.audio_queue = queue.Queue()
        self.wake_event = threading.Event()

        pygame.mixer.init()
        self.recognizer = sr.Recognizer()

        # Create Porcupine
        self.porcupine = pvporcupine.create(
            access_key=PICOVOICE_ACCESS_KEY,
            keywords=[WAKE_WORD]
        )

        # Open mic ONLY ONCE
        self.pa = pyaudio.PyAudio()
        self.stream = self.pa.open(
            rate=self.porcupine.sample_rate,
            channels=1,
            format=pyaudio.paInt16,
            input=True,
            input_device_index=MIC_INDEX,
            frames_per_buffer=self.porcupine.frame_length,
            stream_callback=self._audio_callback
        )

    # ─────────────────────────────
    # AUDIO CALLBACK (runs internally)
    # ─────────────────────────────
    def _audio_callback(self, in_data, frame_count, time_info, status):
        if self.running:
            self.audio_queue.put(in_data)
        return (None, pyaudio.paContinue)

    # ─────────────────────────────
    # START ENGINE
    # ─────────────────────────────
    def start(self):
        print("🎤 Listening for wake word...")
        self.stream.start_stream()

        threading.Thread(target=self._wake_loop, daemon=True).start()
        threading.Thread(target=self._stt_loop, daemon=True).start()

    # ─────────────────────────────
    # WAKE WORD THREAD
    # ─────────────────────────────
    def _wake_loop(self):
        while self.running:
            pcm = self.audio_queue.get()

            pcm_unpacked = struct.unpack_from(
                "h" * self.porcupine.frame_length,
                pcm
            )

            result = self.porcupine.process(pcm_unpacked)

            if result >= 0:
                print("✅ Wake word detected")
                self.status_callback("wake")
                self.wake_event.set()

    # ─────────────────────────────
    # STT THREAD
    # ─────────────────────────────
    def _stt_loop(self):
        while self.running:
            self.wake_event.wait()  # Wait for wake signal
            self.status_callback("processing")

            print("🎧 Listening for command...")

            try:
                with sr.Microphone(device_index=MIC_INDEX) as source:
                    audio = self.recognizer.listen(
                        source,
                        timeout=5,
                        phrase_time_limit=5
                    )

                text = self.recognizer.recognize_google(audio)

                if text:
                    print("📝 Heard:", text)
                    self.command_callback(text)

            except Exception as e:
                print("STT error:", e)

            self.wake_event.clear()

    # ─────────────────────────────
    # TTS (Async)
    # ─────────────────────────────
    async def speak(self, text):
        if not text:
            return

        self.status_callback("speaking")

        try:
            tts_file = "response.mp3"
            communicate = edge_tts.Communicate(text, "en-US-AriaNeural")
            await communicate.save(tts_file)

            pygame.mixer.music.load(tts_file)
            pygame.mixer.music.play()

            while pygame.mixer.music.get_busy():
                await asyncio.sleep(0.1)

        except Exception as e:
            print("TTS error:", e)

        self.status_callback("idle")

    # ─────────────────────────────
    # CLEAN SHUTDOWN
    # ─────────────────────────────
    def stop(self):
        self.running = False
        self.stream.stop_stream()
        self.stream.close()
        self.pa.terminate()
        self.porcupine.delete()
# ─────────────────────────────────────────────
# ASSISTANT APP
# ─────────────────────────────────────────────

class AssistantApp:
    def __init__(self, page: ft.Page):
        self.page = page
        self.page.title = "Vaani Assistant"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.bgcolor = "#000000"

        self.api = httpx.AsyncClient(timeout=20.0)
        self.loop = asyncio.get_running_loop()

        self.setup_ui()

        self.engine = VoiceEngine(
            page,
            self.on_command_received,
            self.update_status
        )

        self.engine.start()

    # ───────── UI ─────────

    def setup_ui(self):
        self.status_text = ft.Text(
            "Say 'Hey Jarvis'",
            color=ft.Colors.WHITE70,
            size=16,
        )

        self.orb_icon = ft.Icon(
            ft.Icons.MIC_NONE,
            size=50,
            color=ft.Colors.WHITE
        )

        self.orb = ft.Container(
            content=self.orb_icon,
            width=140,
            height=140,
            border_radius=70,
            bgcolor=ft.Colors.with_opacity(0.2, ft.Colors.INDIGO),
            alignment=ft.Alignment(0, 0),
        )

        self.page.add(
            ft.Column(
                [
                    ft.Container(expand=True),
                    self.orb,
                    ft.Container(height=20),
                    self.status_text,
                    ft.Container(height=50),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                expand=True,
            )
        )

    # ───────── SAFE UI UPDATE ─────────

    def update_status(self, state):
        def update():
            if state == "wake":
                self.status_text.value = "Listening..."
                self.orb.bgcolor = ft.Colors.GREEN_400
                self.orb_icon.name = ft.Icons.HEARING

            elif state == "speaking":
                self.status_text.value = "Speaking..."
                self.orb.bgcolor = ft.Colors.BLUE_400
                self.orb_icon.name = ft.Icons.VOLUME_UP

            elif state == "processing":
                self.status_text.value = "Thinking..."
                self.orb.bgcolor = ft.Colors.ORANGE_400
                self.orb_icon.name = ft.Icons.AUTO_AWESOME

            else:
                self.status_text.value = "Say 'Hey Jarvis'"
                self.orb.bgcolor = ft.Colors.with_opacity(
                    0.2, ft.Colors.INDIGO
                )
                self.orb_icon.name = ft.Icons.MIC_NONE

            self.page.update()

        self.page.call_from_thread(update)

    # ───────── COMMAND HANDLING ─────────

    def on_command_received(self, text):
        self.update_status("processing")

        future = asyncio.run_coroutine_threadsafe(
            self.call_backend(text),
            self.loop
        )

        try:
            response = future.result(15)

            asyncio.run_coroutine_threadsafe(
                self.engine.speak(response),
                self.loop
            )

        except Exception as e:
            print("Backend error:", e)
            self.update_status("idle")

    async def call_backend(self, text):
        try:
            resp = await self.api.post(
                f"{BASE_URL}/assistant/chat",
                json={"text": text},
            )

            if resp.status_code == 200:
                return resp.json().get("response", "No response.")

            return "Server error."

        except:
            return "Cannot connect to server."


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

async def main(page: ft.Page):

    page.window.width = 420
    page.window.height = 640
    page.window.resizable = False

    await page.window.center()   # MUST await

    AssistantApp(page)

if __name__ == "__main__":
    ft.run(main)