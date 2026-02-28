import asyncio
import threading
import os
import json
import flet as ft
import httpx
import speech_recognition as sr
import edge_tts
import pygame
import pyaudio
from vosk import Model, KaldiRecognizer
from datetime import datetime

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

BASE_URL    = "http://127.0.0.1:8000"
WAKE_WORDS  = ["vaani", "hey vaani", "ok vaani"]   # all lowercase
MIC_INDEX   = 1        # Realtek Microphone Array
SAMPLE_RATE = 16000    # vosk needs 16kHz
VOSK_MODEL  = "vosk-model-small-en-us-0.15"  # folder name after extraction


# ─────────────────────────────────────────────
# VOICE ENGINE
# ─────────────────────────────────────────────

class VoiceEngine:
    """
    Wake word  : vosk  (local, offline, instant — no API call)
    Commands   : Google STT (accurate for full sentences)
    TTS        : edge-tts (Microsoft Neural voices)
    """

    def __init__(self, page, command_callback, status_callback):
        self.page             = page
        self.command_callback = command_callback
        self.status_callback  = status_callback
        self.running          = True

        pygame.mixer.init()

        # ── Load vosk model ──────────────────────────────────────────────
        if not os.path.exists(VOSK_MODEL):
            raise FileNotFoundError(
                f"Vosk model not found: '{VOSK_MODEL}'\n"
                "Run setup_vosk.bat first!"
            )

        print("Loading vosk model...", end=" ", flush=True)
        self.vosk_model = Model(VOSK_MODEL)
        print("ready")

        # ── PyAudio stream (16kHz mono — vosk requirement) ───────────────
        self.pa     = pyaudio.PyAudio()
        self.stream = self.pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=SAMPLE_RATE,
            input=True,
            input_device_index=MIC_INDEX,
            frames_per_buffer=4000,
        )

        # ── Google STT for commands ──────────────────────────────────────
        self.recognizer = sr.Recognizer()
        self.recognizer.energy_threshold         = 300
        self.recognizer.dynamic_energy_threshold = True
        self.recognizer.pause_threshold           = 0.7

        print(f"✅ Voice engine ready  |  wake words: {WAKE_WORDS}")

    # ── Start ─────────────────────────────────────────────────────────────

    def start(self):
        self.stream.start_stream()
        threading.Thread(target=self._wake_loop, daemon=True).start()
        print("🎤 Listening...")

    # ── Wake word loop (vosk — local, zero latency) ───────────────────────

    def _wake_loop(self):
        rec = KaldiRecognizer(self.vosk_model, SAMPLE_RATE)
        rec.SetWords(False)  # faster — no word timestamps needed

        while self.running:
            try:
                data = self.stream.read(4000, exception_on_overflow=False)

                if rec.AcceptWaveform(data):
                    result = json.loads(rec.Result()).get("text", "").lower()
                else:
                    result = json.loads(rec.PartialResult()).get("partial", "").lower()

                if not result:
                    continue

                # Print only non-empty partials for debug
                # print(f"  partial: {result}")

                if any(w in result for w in WAKE_WORDS):
                    print(f"✅ Wake word in: '{result}'")
                    rec = KaldiRecognizer(self.vosk_model, SAMPLE_RATE)  # reset
                    self.status_callback("wake")
                    self._listen_for_command()

            except Exception as e:
                if self.running:
                    print(f"Wake loop error: {e}")

    # ── Command (Google STT — accurate for full sentences) ────────────────

    def _listen_for_command(self):
        self.status_callback("listening")
        print("🎧 Listening for command...")

        # Pause vosk stream briefly so sr.Microphone can use the mic
        self.stream.stop_stream()
        try:
            with sr.Microphone(device_index=MIC_INDEX) as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=0.2)
                audio = self.recognizer.listen(source, timeout=6, phrase_time_limit=10)

            text = self.recognizer.recognize_google(audio)
            if text:
                print(f"📝 Command: {text}")
                self.command_callback(text)

        except sr.WaitTimeoutError:
            print("No command heard.")
            self.status_callback("idle")
        except sr.UnknownValueError:
            print("Could not understand.")
            self.status_callback("idle")
        except Exception as e:
            print(f"Command error: {e}")
            self.status_callback("idle")
        finally:
            self.stream.start_stream()  # resume wake word listening

    # ── TTS ───────────────────────────────────────────────────────────────

    async def speak(self, text):
        if not text:
            return
        self.status_callback("speaking")
        self.stream.stop_stream()   # free mic during TTS
        try:
            tts_file = os.path.join(os.environ.get("TEMP", "."), "vaani_response.mp3")
            communicate = edge_tts.Communicate(text, "en-US-AriaNeural")
            await communicate.save(tts_file)
            pygame.mixer.music.load(tts_file)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                await asyncio.sleep(0.1)
        except Exception as e:
            print(f"TTS error: {e}")
        finally:
            self.stream.start_stream()
        self.status_callback("idle")

    # ── Stop ──────────────────────────────────────────────────────────────

    def stop(self):
        self.running = False
        try:
            self.stream.stop_stream()
            self.stream.close()
            self.pa.terminate()
        except:
            pass


# ─────────────────────────────────────────────
# MESSAGE MODEL
# ─────────────────────────────────────────────

class Message:
    def __init__(self, role, text, timestamp=None):
        self.role = role  # "user" or "assistant"
        self.text = text
        self.timestamp = timestamp or datetime.now().strftime("%H:%M")


# ─────────────────────────────────────────────
# ASSISTANT APP
# ─────────────────────────────────────────────

class AssistantApp:
    def __init__(self, page: ft.Page):
        self.page = page
        self.page.title = "Vaani — AI Assistant"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.bgcolor = "#080C14"
        self.page.padding = 0

        self.api = httpx.AsyncClient(timeout=30.0)
        self.loop = asyncio.get_running_loop()
        self.messages: list[Message] = []
        self.current_status = "idle"

        self._build_ui()

        self.engine = VoiceEngine(
            page,
            self.on_command_received,
            self.update_status
        )
        self.engine.start()

    # ──────────────────────────────────────────
    # UI BUILDER
    # ──────────────────────────────────────────

    def _build_ui(self):
        # ── Top Header ──
        self.header = ft.Container(
            content=ft.Row(
                [
                    ft.Row([
                        ft.Container(
                            content=ft.Text("V", color="#FFFFFF", size=14, weight=ft.FontWeight.BOLD),
                            width=32, height=32,
                            border_radius=10,
                            bgcolor="#3D6FFF",
                            alignment=ft.Alignment(0, 0),
                        ),
                        ft.Column([
                            ft.Text("Vaani", color="#FFFFFF", size=15, weight=ft.FontWeight.W_600),
                            ft.Text("AI Assistant", color="#4A5568", size=11),
                        ], spacing=0),
                    ], spacing=10),
                    ft.Row([
                        ft.Container(
                            content=ft.Icon(ft.Icons.CIRCLE, size=8, color="#22C55E"),
                            tooltip="Connected"
                        ),
                        ft.Text("Live", color="#22C55E", size=11),
                        ft.IconButton(
                            icon=ft.Icons.MORE_VERT,
                            icon_color="#4A5568",
                            icon_size=18,
                        )
                    ], spacing=4),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            padding=ft.Padding.symmetric(horizontal=20, vertical=14),
            bgcolor="#080C14",
        )

        # ── Orb Status Area ──
        self.orb_ring = ft.Container(
            width=180, height=180,
            border_radius=90,
            bgcolor="transparent",
            border=ft.Border.all(1.5, "#1E2A44"),
        )

        self.orb_inner = ft.Container(
            width=140, height=140,
            border_radius=70,
            gradient=ft.RadialGradient(
                colors=["#1A2744", "#0D1628"],
                center=ft.Alignment(0, 0),
                radius=1.0,
            ),
            shadow=ft.BoxShadow(
                blur_radius=40,
                color="#1E3A8A40",
                offset=ft.Offset(0, 0),
                spread_radius=10,
            ),
        )

        self.orb_icon = ft.Icon(ft.Icons.MIC_NONE, size=36, color="#3D6FFF")

        self.orb_stack = ft.Stack(
            controls=[
                ft.Container(self.orb_ring, alignment=ft.Alignment(0, 0)),
                ft.Container(self.orb_inner, alignment=ft.Alignment(0, 0)),
                ft.Container(self.orb_icon, alignment=ft.Alignment(0, 0)),
            ],
            width=180,
            height=180,
        )

        self.status_badge = ft.Container(
            content=ft.Row([
                ft.Container(width=6, height=6, border_radius=3, bgcolor="#3D6FFF"),
                ft.Text("Say 'Hey Vaani'", color="#6B7280", size=12),
            ], spacing=6, tight=True),
            padding=ft.Padding.symmetric(horizontal=14, vertical=6),
            border_radius=20,
            bgcolor="#0F172A",
            border=ft.Border.all(1, "#1E2A44"),
        )

        self.orb_section = ft.Container(
            content=ft.Column([
                self.orb_stack,
                ft.Container(height=16),
                self.status_badge,
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=0),
            padding=ft.Padding.symmetric(vertical=24),
            alignment=ft.Alignment(0, 0),
        )

        # ── Chat Messages ──
        self.chat_column = ft.Column(
            controls=[],
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
            auto_scroll=True,
            expand=True,
        )

        self.chat_container = ft.Container(
            content=ft.Column([
                self.orb_section,
                ft.Divider(height=1, color="#0F172A"),
                ft.Container(
                    content=self.chat_column,
                    padding=ft.Padding.symmetric(horizontal=16, vertical=12),
                    expand=True,
                ),
            ], spacing=0, expand=True),
            expand=True,
            bgcolor="#080C14",
        )

        # ── Input Row ──
        self.input_field = ft.TextField(
            hint_text="Type a message...",
            hint_style=ft.TextStyle(color="#2D3748", size=14),
            text_style=ft.TextStyle(color="#FFFFFF", size=14),
            bgcolor="transparent",
            border=ft.InputBorder.NONE,
            expand=True,
            color="#FFFFFF",
            cursor_color="#3D6FFF",
            on_submit=self._on_text_submit,
            content_padding=ft.Padding.symmetric(horizontal=4, vertical=10),
        )

        self.mic_btn = ft.IconButton(
            icon=ft.Icons.MIC_NONE_ROUNDED,
            icon_color="#3D6FFF",
            icon_size=22,
            tooltip="Voice Input",
            on_click=self._on_mic_click,
            style=ft.ButtonStyle(
                shape=ft.CircleBorder(),
                bgcolor={"": "#0F1929"},
            ),
            width=42, height=42,
        )

        self.send_btn = ft.IconButton(
            icon=ft.Icons.SEND_ROUNDED,
            icon_color="#FFFFFF",
            icon_size=18,
            tooltip="Send",
            on_click=self._on_text_submit,
            style=ft.ButtonStyle(
                shape=ft.CircleBorder(),
                bgcolor={"": "#3D6FFF"},
            ),
            width=42, height=42,
        )

        self.input_bar = ft.Container(
            content=ft.Row([
                ft.Container(
                    content=ft.Row([
                        ft.Container(width=4),
                        self.input_field,
                        self.mic_btn,
                    ], spacing=4),
                    expand=True,
                    bgcolor="#0D1626",
                    border_radius=24,
                    border=ft.Border.all(1, "#1A2744"),
                    height=50,
                    padding=ft.Padding.only(left=8, right=4),
                ),
                self.send_btn,
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.Padding.symmetric(horizontal=16, vertical=10),
            bgcolor="#080C14",
            shadow=ft.BoxShadow(blur_radius=20, color="#00000080", offset=ft.Offset(0, -4)),
        )

        # ── Suggestions (quick chips) ──
        self.suggestions = ft.Container(
            content=ft.Row(
                [self._chip(t) for t in ["What's the weather?", "Set a timer", "Tell me a joke", "News today"]],
                scroll=ft.ScrollMode.AUTO,
                spacing=8,
            ),
            padding=ft.Padding.only(left=16, right=16, bottom=4),
            bgcolor="#080C14",
        )

        # ── Main Layout ──
        self.page.add(
            ft.Column([
                self.header,
                ft.Container(
                    content=self.chat_container,
                    expand=True,
                ),
                self.suggestions,
                self.input_bar,
            ], spacing=0, expand=True)
        )

    def _chip(self, label):
        return ft.GestureDetector(
            content=ft.Container(
                content=ft.Text(label, color="#6B7280", size=12),
                padding=ft.Padding.symmetric(horizontal=12, vertical=6),
                border_radius=16,
                bgcolor="#0D1626",
                border=ft.Border.all(1, "#1A2744"),
            ),
            on_tap=lambda e, l=label: self._chip_tapped(l),
        )

    def _chip_tapped(self, text):
        self.input_field.value = text
        self.page.update()
        self.on_command_received(text)
        self.input_field.value = ""
        self.page.update()

    # ──────────────────────────────────────────
    # CHAT BUBBLES
    # ──────────────────────────────────────────

    def _add_message(self, msg: Message):
        is_user = msg.role == "user"

        bubble = ft.Container(
            content=ft.Column([
                ft.Text(
                    msg.text,
                    color="#FFFFFF" if is_user else "#CBD5E1",
                    size=14,
                    selectable=True,
                ),
                ft.Text(
                    msg.timestamp,
                    color="#FFFFFF40" if is_user else "#4A556880",
                    size=10,
                ),
            ], spacing=4, tight=True),
            padding=ft.Padding.symmetric(horizontal=14, vertical=10),
            border_radius=ft.BorderRadius(
                top_left=16,
                top_right=16,
                bottom_left=4 if is_user else 16,
                bottom_right=16 if is_user else 4,
            ),
            bgcolor="#2255FF" if is_user else "#0F1929",
            border=None if is_user else ft.Border.all(1, "#1A2744"),
            shadow=ft.BoxShadow(
                blur_radius=12,
                color="#3D6FFF30" if is_user else "#00000020",
            ),
            max_width=280,
        )

        row = ft.Row(
            [bubble],
            alignment=ft.MainAxisAlignment.END if is_user else ft.MainAxisAlignment.START,
        )

        # Avatar for assistant
        if not is_user:
            avatar = ft.Container(
                content=ft.Text("V", color="#FFFFFF", size=11, weight=ft.FontWeight.BOLD),
                width=26, height=26,
                border_radius=13,
                bgcolor="#1E3A8A",
                alignment=ft.Alignment(0, 0),
            )
            row = ft.Row([avatar, bubble], spacing=8, vertical_alignment=ft.CrossAxisAlignment.END)

        self.chat_column.controls.append(row)
        self.page.update()

    def _add_typing_indicator(self):
        self._typing_row = ft.Row([
            ft.Container(
                content=ft.Text("V", color="#FFFFFF", size=11, weight=ft.FontWeight.BOLD),
                width=26, height=26, border_radius=13,
                bgcolor="#1E3A8A", alignment=ft.Alignment(0, 0),
            ),
            ft.Container(
                content=ft.Row([
                    ft.Container(width=6, height=6, border_radius=3, bgcolor="#3D6FFF", opacity=0.6),
                    ft.Container(width=6, height=6, border_radius=3, bgcolor="#3D6FFF", opacity=0.4),
                    ft.Container(width=6, height=6, border_radius=3, bgcolor="#3D6FFF", opacity=0.2),
                ], spacing=4),
                padding=ft.Padding.symmetric(horizontal=14, vertical=12),
                border_radius=16,
                bgcolor="#0F1929",
                border=ft.Border.all(1, "#1A2744"),
            )
        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.END)
        self.chat_column.controls.append(self._typing_row)
        self.page.update()

    def _remove_typing_indicator(self):
        if hasattr(self, '_typing_row') and self._typing_row in self.chat_column.controls:
            self.chat_column.controls.remove(self._typing_row)
            self.page.update()

    # ──────────────────────────────────────────
    # STATUS UPDATES
    # ──────────────────────────────────────────

    def update_status(self, state):
        self.current_status = state
        def update():
            if state == "wake":
                self._set_orb("#22C55E", ft.Icons.HEARING, "Listening...", "#22C55E")
            elif state == "listening":
                self._set_orb("#22C55E", ft.Icons.GRAPHIC_EQ, "Listening...", "#22C55E")
            elif state == "speaking":
                self._set_orb("#3D6FFF", ft.Icons.VOLUME_UP_ROUNDED, "Speaking...", "#3D6FFF")
            elif state == "processing":
                self._set_orb("#F59E0B", ft.Icons.AUTO_AWESOME, "Thinking...", "#F59E0B")
            else:
                self._set_orb("#1A2744", ft.Icons.MIC_NONE, "Say 'Hey Vaani'", "#3D6FFF")
            self.page.update()

        self.page.call_from_thread(update)

    def _set_orb(self, ring_color, icon, status_text, icon_color):
        self.orb_ring.border = ft.Border.all(1.5, ring_color)
        self.orb_ring.shadow = ft.BoxShadow(
            blur_radius=30, color=f"{ring_color}40",
            offset=ft.Offset(0, 0), spread_radius=5
        )
        self.orb_icon.name = icon
        self.orb_icon.color = icon_color

        # Update status badge
        badge_row = self.status_badge.content
        badge_row.controls[0].bgcolor = ring_color
        badge_row.controls[1].value = status_text
        badge_row.controls[1].color = ring_color

    # ──────────────────────────────────────────
    # COMMAND HANDLING
    # ──────────────────────────────────────────

    def _on_mic_click(self, e):
        if self.current_status == "idle":
            self.update_status("listening")
            threading.Thread(target=self._manual_listen, daemon=True).start()

    def _manual_listen(self):
        try:
            recognizer = sr.Recognizer()
            with sr.Microphone(device_index=MIC_INDEX) as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.3)
                audio = recognizer.listen(source, timeout=6, phrase_time_limit=8)
            text = recognizer.recognize_google(audio)
            if text:
                self.on_command_received(text)
        except Exception as e:
            print("Manual listen error:", e)
            self.update_status("idle")

    def _on_text_submit(self, e):
        text = self.input_field.value.strip()
        if not text:
            return
        self.input_field.value = ""
        self.page.update()
        self.on_command_received(text)

    def on_command_received(self, text):
        # Add user message
        msg = Message("user", text)
        self.messages.append(msg)
        self.page.call_from_thread(lambda: self._add_message(msg))

        self.update_status("processing")
        self.page.call_from_thread(self._add_typing_indicator)

        future = asyncio.run_coroutine_threadsafe(
            self.call_backend(text),
            self.loop
        )

        try:
            response = future.result(20)
            self.page.call_from_thread(self._remove_typing_indicator)

            ai_msg = Message("assistant", response)
            self.messages.append(ai_msg)
            self.page.call_from_thread(lambda: self._add_message(ai_msg))

            asyncio.run_coroutine_threadsafe(
                self.engine.speak(response),
                self.loop
            )

        except Exception as e:
            print("Backend error:", e)
            self.page.call_from_thread(self._remove_typing_indicator)
            err_msg = Message("assistant", "I couldn't connect to the server. Please check your connection.")
            self.page.call_from_thread(lambda: self._add_message(err_msg))
            self.update_status("idle")

    async def call_backend(self, text):
        try:
            resp = await self.api.post(
                f"{BASE_URL}/assistant/chat",
                json={"text": text},
            )
            if resp.status_code == 200:
                return resp.json().get("response", "No response.")
            return f"Server returned error {resp.status_code}."
        except httpx.ConnectError:
            return "Unable to reach the assistant server."
        except Exception as e:
            return f"Error: {str(e)}"


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

async def main(page: ft.Page):
    page.window.width = 400
    page.window.height = 720
    page.window.resizable = False
    page.window.title_bar_hidden = False
    page.fonts = {
        "Sora": "https://fonts.gstatic.com/s/sora/v12/xMQOuFFYT72X5wkB_18qmnndmSe3dY.woff2",
    }
    page.theme = ft.Theme(font_family="Sora")
    try:
        await page.window.center()
    except Exception:
        pass
    AssistantApp(page)


if __name__ == "__main__":
    ft.run(main)