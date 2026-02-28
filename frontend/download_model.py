import os, zipfile, urllib.request

model_url = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
model_zip = "vosk-model-small-en-us-0.15.zip"
model_dir = "vosk-model-small-en-us-0.15"

if os.path.exists(model_dir):
    print("Model already exists:", model_dir)
else:
    print("Downloading vosk model (~40MB)...")
    def progress(block, block_size, total):
        pct = min(100, int(block * block_size * 100 / total))
        bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
        print(f"\r  [{bar}] {pct}%", end="", flush=True)
    urllib.request.urlretrieve(model_url, model_zip, reporthook=progress)
    print("\nExtracting...")
    with zipfile.ZipFile(model_zip, "r") as z:
        z.extractall(".")
    os.remove(model_zip)
    print("Model ready:", model_dir)

print("\nDone! Now run:  flet run app.py")