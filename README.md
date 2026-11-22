# STT AI 0.2.0 — lokální přepis audia

Česká webová aplikace pro přepis nahrávek pomocí Whisperu. V prohlížeči nahrajete soubor, AI ho zpracuje na vašem počítači. Není potřeba cloudový přepis, účet ani placené API.

**Novinky 0.2.0:** procenta přepisu i na Macu, správa a stahování modelů a podpora [mikr/whisper-large-v3-czech-cv13](https://huggingface.co/mikr/whisper-large-v3-czech-cv13). [Úplný popis verzí](CHANGELOG.md).

## Spuštění na Macu s Apple Silicon

Nainstalujte [Homebrew](https://brew.sh), pokud ho ještě nemáte. V Terminálu:

```bash
brew install uv ffmpeg
git clone https://github.com/ok2clj/STT_AI.git
cd STT_AI
./start.command
```

Pokud už máte projekt v původní pracovní složce, stačí v ní spustit `./start.command` (při chybě oprávnění `bash start.command`). Spouštěč připraví Python 3.13, vlastní prostředí a rozšíření pro české modely. První instalace může chvíli trvat, protože instaluje i PyTorch a Transformers.

Otevřete **http://127.0.0.1:8765**, Terminál ponechte běžet; ukončení Ctrl+C. Server spouštějte jen jednou, s jedním Uvicorn workerem.

Pro základní modely na MacBooku Air M2 doporučujeme začít modelem **Small** a zpracováním **Automaticky**. Tato volba použije MLX. Větší modely vyžadují výrazně více paměti. MLX potřebuje macOS a Apple Silicon s podporou Metal; PyTorch MPS používá vlastní podporu Apple GPU.

## Jak použít český model mikr

1. Spusťte aktualizovanou aplikaci pomocí `start.command` / `start.ps1`.
2. Nechte zpracování **Automaticky** a otevřete **Správa a stahování modelů** pod formulářem.
3. U **Čeština · mikr Large v3 CV13** zvolte **Stáhnout**. Samotné váhy modelu mají přibližně 3,22 GB; počítejte i s dalšími soubory a vyšší spotřebou RAM za běhu.
4. Po stažení klikněte **Použít**, vyberte jazyk **Čeština**, nahrajte audio a spusťte přepis.

Jde o původní checkpoint Transformers, proto se na Apple GPU používá **MPS**, na NVIDIA **CUDA**, případně **CPU**. Není to model MLX ani CTranslate2; volba neslučitelného formátu skončí srozumitelnou chybou. Konverze není potřeba a aplikace nic netrénuje.

Model je specializovaný fine-tuning Whisper Large v3. Lepší kvalitu proti základnímu modelu nelze zaručit pro každý typ nahrávky; porovnejte ho na svých datech. Použití se řídí podmínkami autora modelu.

## Přidání dalších modelů

Ve správě modelů zadejte `autor/model` nebo odkaz na hlavní stránku Hugging Face modelu, vyberte skutečný formát vah a případně vlastní název. Potom model stáhněte a použijte.

| Formát v aplikaci | Co musí repozitář obsahovat | Zpracování |
| --- | --- | --- |
| Transformers | Whisper `config.json`, kompletní processor/tokenizer a `model*.safetensors` | CPU, NVIDIA CUDA, Apple MPS |
| CTranslate2 | Konvertovaný Whisper s `model.bin`, `config.json`, `tokenizer.json` | CPU INT8 nebo NVIDIA CUDA FP16 |
| MLX | Whisper MLX konfiguraci s `n_mels` a váhy `weights.npz` nebo `weights.safetensors` | Apple GPU MLX |
| Základní Whisper | Katalog Tiny, Base, Small, Medium, Large v3, Turbo | Automaticky MLX na Macu, jinak CTranslate2 |

Podporovány jsou kompletní modely Whisper, nikoli libovolné ASR modely, GGUF nebo samostatné LoRA adaptéry. Soukromé/gated repozitáře vyžadují předem dostupné oprávnění v Hugging Face cache/konfiguraci prostředí; aplikace neobsahuje přihlašovací formulář.

U základních modelů se při stažení zvolí formát podle aktuálního nastavení **Zpracování**. MLX a CTranslate2 jsou odlišné váhy: stažený model pro CPU není automaticky připravený pro MLX. Stav stažení zobrazuje počet dokončených souborů, nikoli bajty; velký soubor může trvat déle než všechny malé dohromady. Při chybě lze stažení zopakovat.

## Co znamenají procenta

- Nejdříve aplikace ukazuje **frontu → přípravu/stažení modelu → načítání modelu → načítání audia**. Tyto fáze nemají procenta přepisu.
- Při přepisu vidíte velké procento a **zpracovaný čas / celkovou délku audia**. Údaje jsou dostupné i při návratu k úloze z historie.
- Průběh se počítá z dokončených úseků nahrávky, dlouhých nejvýše 30 sekund. Ticho se započítává stejně jako řeč. Nejde o odhad zbývajícího času.
- Po každém úseku se procenta změní; během náročného výpočtu jednoho úseku mohou stát. Nahrávka kratší než 30 sekund může přejít z 0 % rovnou na dokončení.
- **100 %** se uloží až s dokončeným výsledkem po odstranění pracovní kopie audia. Do té doby je horní hranice 99 %.

Nahrávka se dekóduje do paměti. Přepis po samostatných úsecích může ovlivnit návaznost slov na jejich hranicích. Výsledek, jména, čísla a časové značky před dalším použitím zkontrolujte.

## Další funkce

- Nahrání přetažením, náhled audia před odesláním. MP3, M4A, WAV, AAC, FLAC, OGG, Opus, AIFF, WMA, WebM a MP4 podle podpory dekodéru PyAV.
- Čeština, slovenština, angličtina, němčina, polština, ukrajinština a automatická detekce dalších jazyků Whisperu.
- Vlastní kontext pro jména a odborné výrazy.
- Nejvýše 8 přijatých přepisů ve frontě; inference vždy po jedné. Stahování má samostatnou omezenou frontu.
- Historie v SQLite, úpravy textu časových úseků a export TXT, SRT, VTT, JSON. Export automaticky ukládá úpravy.
- Aktuálně bez rozlišení mluvčích, přímého nahrávání mikrofonu, překladu a shrnování.

## Windows a Linux

Nainstalujte [uv](https://docs.astral.sh/uv/getting-started/installation/). Na Windows ve složce projektu spusťte v PowerShellu:

```powershell
.\start.ps1
```

Pokud místní pravidla PowerShellu skript nepovolí, spusťte přímo:

```powershell
uv sync --python 3.13 --extra hf --no-dev
uv run --python 3.13 --extra hf --no-dev uvicorn stt.app:app --host 127.0.0.1 --port 8765
```

Na Linuxu použijte `bash start.command` nebo stejné přímé příkazy. Rozhraní je vždy http://127.0.0.1:8765. Dekódování zajišťuje PyAV; samostatný FFmpeg už není pro přepis MLX potřeba.

### GPU NVIDIA

CTranslate2/faster-whisper vyžaduje podporovanou GPU, ovladač a aktuálně CUDA 12/cuBLAS + cuDNN 9. Viz [oficiální dokumentace](https://github.com/SYSTRAN/faster-whisper#gpu). Transformers vyžaduje **PyTorch s podporou CUDA**, jehož konkrétní instalaci vyberte podle [oficiálního návodu PyTorch](https://pytorch.org/get-started/locally/). Samotné `nvidia-smi` nepotvrzuje přítomnost všech runtime knihoven.

Pokud CPU balíček PyTorch CUDA nepodporuje, aplikace zobrazí chybu. Chyby GPU se nezamlčují automatickým přechodem na CPU. Pro ručně upravené prostředí spouštějte `.venv/bin/python -m uvicorn stt.app:app --host 127.0.0.1 --port 8765` (na Windows `.venv\Scripts\python.exe -m uvicorn ...`); `uv sync` může balíčky doplněné mimo definici projektu změnit. AMD/ROCm a Intel GPU nejsou v této verzi implementované.

## Ruční instalace a offline provoz

```bash
uv sync --python 3.13 --extra hf
uv run --python 3.13 --extra hf uvicorn stt.app:app --host 127.0.0.1 --port 8765
```

Pro základní MLX/CTranslate2 bez Transformers lze vynechat `--extra hf`. Český model mikr a další Transformers modely pak při použití oznámí chybějící rozšíření.

Po kompletním stažení konkrétního modelu lze před startem nastavit `HF_HUB_OFFLINE=1`. Stažené snapshoty se při přepisu načítají lokálně. Při ručním spuštění respektují Transformers/MLX standardní Hugging Face cache; spouštěče ji směrují pod `data/huggingface/`. CTranslate2 zachovává původní umístění `data/models/`, takže lze využít dříve stažené základní modely.

## Data a soukromí

- Server přijímá pouze místní hostnames a stejný webový origin; standardně naslouchá na `127.0.0.1`. Jde o osobní aplikaci **bez přihlašování**, dostupnou místním uživatelům/procesům s přístupem k portu.
- Audio se zpracovává na serveru, nikoli GPU zařízení, na kterém máte otevřený prohlížeč. Zvuk se neposílá poskytovateli modelu.
- Po dokončení nebo chybě se pracovní audio odstraní; zdrojový soubor se nemění. Zbytky po pádu procesu se odstraní při dalším startu.
- Text, názvy nahrávek a pomocný kontext zůstávají v `data/transcripts.sqlite3` do smazání přepisu. SQLite mazání nezaručuje bezpečné odstranění z disku, záloh či snapshotů.
- Vlastní katalog a stav stažení jsou v `data/model-library/catalog.json`. Stažené modely zůstávají v cache i po smazání přepisu. Odstranění modelů z UI zatím není implementované.
- Rozhraní nepoužívá externí fonty, analytiku ani CDN. Spouštěče vypínají běžnou telemetrii Hugging Face a směrují pomocné soubory pod `data/`.
- Limit souboru je 500 MiB (`STT_MAX_UPLOAD_MB`). `STT_DATA_DIR` mění umístění databáze, modelového katalogu, audia a CTranslate2 cache; cache Transformers/MLX se nastavuje zvlášť přes `HF_HOME`.
- Po restartu se přerušený přepis označí chybou a vyžaduje nové nahrání souboru. Přerušené stažení lze zopakovat.

Pro přístup z dalších zařízení je potřeba doplnit autentizaci, HTTPS a odpovídající síťové nastavení.

## Testy a stav ověření

```bash
uv sync --python 3.13 --extra hf
uv run --extra hf python -m unittest discover -s tests -v
```

Prošlo **29 testů** včetně skutečných ASGI rout/middleware/fronty, pollingu průběhu, exportů, validace a katalogu. Inference a síťová stažení jsou nahrazené testovacími implementacemi; testy nepotvrzují kvalitu skutečného českého přepisu. Ověřena je i syntaxe Pythonu, JavaScriptu a Bash a návaznost HTML prvků na skript.

Vývojové prostředí aktuálně blokuje síťové stahování nových balíčků a neposkytuje přístup k Metal GPU. **Nový český model ani skutečné GPU zpracování zde nebyly spuštěny.** Závislosti pro v0.2.0 se uzamknou při prvním úspěšném `uv sync`; do repozitáře není vložen neověřený starší lockfile.

Technologie: [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [MLX Whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper), [Transformers Whisper](https://huggingface.co/docs/transformers/model_doc/whisper), PyTorch, FastAPI, SQLite, HTML/CSS/JavaScript. Licence modelů a knihoven se řídí jejich vlastními podmínkami.
