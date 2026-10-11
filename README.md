# Hindi PDF Translator

A small app that runs on an ordinary office laptop with **8–12 GB RAM and no graphics card**. Upload a Hindi PDF (for example, documents from Beltron) and get an English translation back as Word, side-by-side view, layout-preserving PDF or text.

- **Primary model: Gemma 4,** E2B on 8 GB laptops and E4B on 12 GB laptops. It runs through the bundled **llama.cpp** server, with **models downloaded from Hugging Face** (no Ollama).
- **Users choose the model:** Auto (recommended), Fast, Balanced or Best quality. Only tested models are offered.
- **IndicTrans2** produces a quick draft within minutes and is the first fallback.
- **Free and local only:** no paid APIs, and documents never leave the machine.
- An **offline model pack** lets IT install models on many laptops without internet.

**Status:** planning. See **[PLAN.md](PLAN.md)** for the full design.
