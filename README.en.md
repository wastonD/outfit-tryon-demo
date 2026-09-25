# Outfit Try-On

> Put clothes from Taobao, JD, Uniqlo and Amazon onto a model with your body type, and see whether they actually go together.

**Cross-store AI virtual try-on · Web app + browser extension · Runs locally on an 8 GB laptop GPU · Commercially licensed models only**

[中文](README.md)

![The same outfit on different body types](docs/assets/showcase.jpg)

<sub>Real output: two flat-lay product photos (sample images from Alibaba Cloud's public docs) tried on with FASHN VTON v1.5 running locally on an RTX 4060 Laptop (8 GB). All models are AI-generated.</sub>

## The problem

When the top comes from one store, the trousers from another and the jacket from a third platform, every product page shows a different model. You can't see how the pieces look together, let alone on your own body type.

## What it does

1. **Collect**: one click in the browser extension on any product page, or paste a link or share text, or drop / paste an image (avif and heic supported).
2. **Understand**: a local vision-language model (Qwen3-VL-4B via llama.cpp) classifies each item (top / outerwear / bottom / skirt / dress), its colour, and whether it's a flat-lay or an on-model photo. It cuts the item out when needed (BiRefNet).
3. **Style**: pick a preset model close to your build: 18 body types (gender × build × skin tone), 53 looks.
4. **Generate**: a layering planner orders the steps (bottoms, then tops, then outerwear, with tuck-in or tuck-out options). FASHN VTON renders each step, and Real-ESRGAN can upscale the result.

## Architecture highlights

- **Capability-based plug-in design**: seven capabilities (`resolver`, `analyzer`, `segmenter`, `tryon`, `upscaler`, `turntable`, `model_generator`). Each capability can have several providers, local or cloud, chained in `providers.yaml` with automatic fallback. Adding a model takes one adapter file and one config line. Business logic, API and UI stay unchanged.
- **Full pipeline on an 8 GB laptop GPU**: the VLM runs on CPU. The GPU worker runs one job at a time behind a global lock and loads or evicts models by VRAM budget (LRU).
- **License-audited stack**: code, weights, training data and dependencies are checked separately ([LICENSES.md](LICENSES.md)). FASHN's bundled human parser is non-commercial (NVIDIA SegFormer), so it was removed from the vendored code.
- **Classifier performance**: inputs are resized to 768 px on the long side, cutting a call from 263 s to about 35 s (p90); with prompt tuning, category accuracy went from 60% to 93%.
- **One API for every client**: the web app and browser extension share the same REST API, ready for a future mobile app.
- Multi-user invite tokens, per-user data isolation, daily quotas, two job queues (light / GPU) with queue positions, and content-hash result caching.
- 96 server tests plus an end-to-end API regression script.

## Status

Works well for single garments, dresses and top + bottom sets. Three-layer outfits (T-shirt + jacket + trousers) are still unstable; improving them is the next focus, followed by a 360° turntable view and a mobile app on the same API.

## Quick start

See the [Chinese README](README.md#快速开始) for full steps (Windows, Python 3.12 / 3.14, Node 20+, NVIDIA GPU 8 GB+). You can also try the UI without any models: `cd web; $env:VITE_MOCK="1"; npm run dev`.

## License

Apache-2.0. Preset models are AI-generated virtual models and don't depict real people. Try-on outputs are synthetic images, so label them "AI-generated" if you share them.
