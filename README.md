# Video Caption Generator

A practical first prototype for **visual video captioning**:

1. Upload a short video in the browser.
2. The server detects visual scene changes and chooses meaningful moments to analyse.
3. A pretrained BLIP image-captioning model captions each detected scene; a compact person detector verifies plural people counts.
4. The app returns the main visual caption plus a timestamped, natural audio-description script.

This is deliberately a prototype, not a training pipeline. It uses `Salesforce/blip-image-captioning-base`, so the first request downloads model weights. No dataset or model training is needed.

## What it does and does not do

- **Does:** generate a concise caption for what is visually happening in a video, including silent videos.
- **Does:** combine semantically repeated views while narrating meaningful new actions and visual changes in direct sentences.
- **Does:** verify visible-person counts before changing a singular caption to phrases such as "four people".
- **Does:** use CUDA automatically when the installed PyTorch build can see an NVIDIA GPU; otherwise it works on CPU.
- **Does not yet:** transcribe spoken audio, create subtitle files, or train a custom model. Those are planned follow-up modules after this visual baseline works.

## Project layout

```text
app/
  main.py             FastAPI routes and UI hosting
  caption_service.py  video frame sampling + pretrained-model inference
  schemas.py          API response models
static/
  index.html          browser interface
  app.js              upload interaction
  styles.css          interface styling
requirements.txt      Python dependencies
```

## Run locally (Windows)

Open PowerShell inside this project folder and run:

```powershell
.\setup.ps1
.\run.ps1
```

Then open http://127.0.0.1:8000.

If PowerShell blocks either script, run this once in that same PowerShell window, then retry:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

`setup.ps1` uses the installed Python 3.13 and creates a separate `.venv` just for this project. It does not alter or remove your system Python.

## GPU note

The code chooses CUDA only when `torch.cuda.is_available()` is true. A regular PyTorch installation may run on CPU; the application will still work, just more slowly. We will configure the RTX 2050-specific PyTorch build only after confirming the basic app starts.

## Test video

Use a short `.mp4`, `.mov`, `.avi`, or `.mkv` file (ideally under 30 seconds for the first test). The first caption request can take a few minutes because it downloads the pretrained model.
