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
import uuid
import numpy as np
from openwakeword.model import Model as WakeWordModel

from openwakeword.utils import download_models
download_models()

BASE_URL    = "http://127.0.0.1:8000"
WAKE_WORDS  = [
    # Exact
    "vaani", "hey vaani", "ok vaani",
    # Vosk mishearings of "vaani" / "hey vaani"
    "hey man", "hey when", "hey one", "hey wan",
    "bani", "bonnie", "barney",
    "jarvis", "hey jarvis",   # bonus classic wake words
]
MIC_INDEX   = 1        # Realtek Microphone Array
SAMPLE_RATE = 16000    # vosk needs 16kHz
VOSK_MODEL  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vosk-model-small-en-us-0.15")

import numpy as np
from openwakeword.model import Model as WakeWordModel

class VoiceEngine:
    CHUNK       = 1280   # openwakeword needs 1280 frames @ 16kHz
    CMD_SILENCE = 4
    CMD_MAX     = 10.0
    WAKE_THRESHOLD = 0.35  # confidence threshold (0.0-1.0), raise to reduce false positives

    def __init__(self, page, command_callback, status_callback):
        self.page             = page
        self.command_callback = command_callback
        self.status_callback  = status_callback
        self.running          = True
        self.speaking         = False

        pygame.mixer.init()

        # Load OpenWakeWord model
        # Use built-in "hey jarvis" or custom model path
        model_path = r"E:\MyAssist\venv\Lib\site-packages\openwakeword\resources\models\hey_jarvis_v0.1.onnx"

        self.oww = WakeWordModel(
            wakeword_models=["alexa"],
            inference_framework="onnx"
        )

        print("✅ OpenWakeWord loaded")

        # Load Vosk for command transcription only
        if not os.path.exists(VOSK_MODEL):
            raise FileNotFoundError(f"Vosk model not found: {VOSK_MODEL}")
        self.model = Model(VOSK_MODEL)
        print("✅ Vosk model loaded")

        self.pa = pyaudio.PyAudio()
        self.stream = self.pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=SAMPLE_RATE,
            input=True,
            input_device_index=MIC_INDEX,
            frames_per_buffer=self.CHUNK,
        )
        print(f"✅ Mic open — device {MIC_INDEX} @ {SAMPLE_RATE}Hz")

    def start(self):
        self.thread = threading.Thread(
            target=self._main_loop,
            daemon=True
        )
        self.thread.start()
        print("🚀 Voice engine started")

    def _read(self):
        return self.stream.read(self.CHUNK, exception_on_overflow=False)

    def _main_loop(self):
        print("🎤 Listening for wake word...")
        while self.running:
            try:
                if self.speaking:
                    self._read()
                    continue

                data = self._read()
                
                # Convert bytes to int16 numpy array for OpenWakeWord
                audio_int16 = np.frombuffer(data, dtype=np.int16)
                print("Max audio:", np.max(np.abs(audio_int16)))
                
                # Run wake word detection
                predictions = self.oww.predict(audio_int16)
                print(f"Predictions: ", predictions)
                
                # Check if any wake word exceeded threshold
                for model_name, score in predictions.items():
                    if score > self.WAKE_THRESHOLD:
                        print(f"✅ Wake word detected! [{model_name}] score={score:.3f}")
                        self.oww.reset()  # reset scores
                        self.status_callback("wake")
                        command = self._capture_command()
                        if command:
                            self.command_callback(command)
                        else:
                            self.status_callback("idle")
                        break

            except Exception as e:
                if self.running:
                    print(f"Loop error: {e}")

    def _capture_command(self):
        """
        After wake word: record until silence, then transcribe with Google STT.
        Uses the SAME pyaudio stream — no mic conflicts.
        """
        self.status_callback("listening")
        print("🎧 Speak your command...")

        rec = KaldiRecognizer(self.model, SAMPLE_RATE)
        frames = []
        silent_chunks = 0
        total_chunks  = 0

        # How many silent chunks = end of speech
        silence_limit = int(self.CMD_SILENCE * SAMPLE_RATE / self.CHUNK)
        max_chunks    = int(self.CMD_MAX    * SAMPLE_RATE / self.CHUNK)

        while total_chunks < max_chunks:
            data = self._read()
            frames.append(data)
            total_chunks += 1

            # Use vosk energy to detect silence
            rec.AcceptWaveform(data)
            partial = json.loads(rec.PartialResult()).get("partial", "")

            if partial:
                silent_chunks = 0   # reset silence counter on speech
                print(f"  cmd partial: {partial}")
            else:
                silent_chunks += 1

            if silent_chunks >= silence_limit and total_chunks > 8:
                break   # silence detected — done recording

        if not frames:
            return None

        # Send raw PCM to Google STT via sr.AudioData (no Microphone needed)
        raw = b"".join(frames)
        audio_data = sr.AudioData(raw, SAMPLE_RATE, 2)  # 2 bytes = paInt16

        recognizer = sr.Recognizer()
        try:
            text = recognizer.recognize_google(audio_data)
            print(f"📝 Command: {text}")
            return text
        except sr.UnknownValueError:
            print("Could not understand command.")
            return None
        except sr.RequestError as e:
            print(f"Google STT error: {e}")
            # Fallback: use vosk result
            result = json.loads(rec.FinalResult()).get("text", "")
            print(f"📝 Vosk fallback: {result}")
            return result if result else None

    # ── TTS ───────────────────────────────────────────────────────────────



    async def speak(self, text):
        if not text:
            return

        self.status_callback("speaking")
        self.speaking = True

        try:
            # Generate unique filename
            filename = f"vaani_{uuid.uuid4().hex}.mp3"
            tts_file = os.path.join(os.environ.get("TEMP", "."), filename)

            communicate = edge_tts.Communicate(text, "en-US-AriaNeural")
            await communicate.save(tts_file)

            pygame.mixer.music.load(tts_file)
            pygame.mixer.music.play()

            while pygame.mixer.music.get_busy():
                await asyncio.sleep(0.1)

            pygame.mixer.music.unload()  # release file lock

            # Optional: delete after playing
            try:
                os.remove(tts_file)
            except:
                pass

        except Exception as e:
            print(f"TTS error: {e}")

        finally:
            self.speaking = False
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
        print("🛑 Voice engine stopped")

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
            width=280,
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

        update()

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
        self._add_message(msg)

        self.update_status("processing")
        self._add_typing_indicator()

        future = asyncio.run_coroutine_threadsafe(
            self.call_backend(text),
            self.loop
        )

        try:
            response = future.result(20)
            self._remove_typing_indicator()

            ai_msg = Message("assistant", response)
            self.messages.append(ai_msg)
            self._add_message(ai_msg)

            asyncio.run_coroutine_threadsafe(
                self.engine.speak(response),
                self.loop
            )

        except Exception as e:
            print("Backend error:", e)
            self._remove_typing_indicator()
            err_msg = Message("assistant", "I couldn't connect to the server. Please check your connection.")
            self._add_message(err_msg)
            self.update_status("idle")

    async def call_backend(self, text):
        try:
            resp = await self.api.post(
                f"{BASE_URL}/assistant/api/v1/process",
                json={
                    "text": text,
                    "session_id": "vaani-session",
                    "partial": False
                },
            )

            if resp.status_code == 200:
                return resp.json().get("text_response", "No response.")
            return f"Server returned error {resp.status_code}."

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