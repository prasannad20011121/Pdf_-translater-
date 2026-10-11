# Hindi PDF Translator

A small app that runs on an ordinary office laptop with **8–12 GB RAM and no graphics card**. Upload a Hindi PDF (for example, documents from Beltron) and get an English translation back as Word, side-by-side view, layout-preserving PDF or text.

- **Primary model: Gemma 4,** run locally through Ollama: E2B on 8 GB laptops, E4B on 12 GB laptops.
- **IndicTrans2** produces a quick draft within minutes and is the first fallback.
- **Free and local only:** no paid APIs, and documents never leave the machine.
- **Fallbacks at every stage,** including switching to a smaller model when memory runs short.

**Status:** planning. See **[PLAN.md](PLAN.md)** for the full design, engine choices, memory budget, fallback strategy, evaluation plan and roadmap.
