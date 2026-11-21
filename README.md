# STT AI — lokální přepis nahrávek

Česká webová aplikace pro převod nahraného audia na text pomocí modelů Whisper. Prohlížeč zobrazuje rozhraní, inference probíhá v Pythonu na počítači, kde běží server. Není potřeba účet, API klíč ani placená cloudová služba.

## Co aplikace umí

- Nahrání souboru přetažením nebo výběrem, náhled přehrávače před odesláním.
- MP3, M4A, WAV, AAC, FLAC, OGG, Opus, AIFF, WMA, WebM a MP4; přepisuje se zvuková stopa. Skutečná podpora závisí na dekodéru a kodeku souboru.
- Čeština, slovenština, angličtina, němčina, polština, ukrajinština; automatická detekce dalších jazyků podporovaných Whisperem.
- Modely Tiny, Base, Small, Medium, Large v3 a Turbo.
- Apple Silicon GPU přes MLX, NVIDIA CUDA GPU přes faster-whisper, CPU včetně Apple ARM přes faster-whisper INT8.
- Pomocný kontext pro vlastní jména a odborné výrazy.
- Fronta nejvýše 8 současně přijatých úloh; inference vždy po jedné, aby se zbytečně nepřeplňovala paměť.
- Místní historie v SQLite, opravy textu jednotlivých časových úseků.
- Export upraveného přepisu do TXT, SRT, VTT a JSON. Export automaticky uloží aktuální úpravy.

Aktuální verze nepřiřazuje mluvčí, nenahrává přímo z mikrofonu a nepřekládá ani neshrnuje. Časové značky v titulcích odpovídají úsekům modelu, nikoli jednotlivým slovům. Přepis zkontrolujte, zvlášť jména, čísla a odborné výrazy.

## Nejrychlejší spuštění na Macu M1/M2/M3/M4 a novějším

Potřebujete macOS podporovaný aktuálním balíčkem MLX (minimálně macOS 14 pro tuto aplikaci), Apple Silicon a internet pro instalaci a první stažení každého modelu. Nainstalujte [Homebrew](https://brew.sh), pokud jej ještě nemáte.

V Terminálu:

```bash
brew install uv ffmpeg
cd /Users/ok2clj/Documents/Codex/STT
./start.command
```

Pokud jste aplikaci rozbalili jinam, v příkazu `cd` použijte cestu ke své složce. Při chybě oprávnění spusťte `bash start.command`. Soubor `start.command` lze také otevřít z Finderu.

Spouštěč připraví Python 3.13, oddělené prostředí a závislosti. Poté v prohlížeči otevřete:

**http://127.0.0.1:8765**

Terminál ponechte otevřený, ukončení je Ctrl+C. Pro váš MacBook Air M2 začněte modelem **Small** a volbou **Automaticky**. Ta zvolí Apple GPU přes MLX. Pro porovnání můžete ručně vybrat **CPU · včetně ARM**. Větší modely potřebují více sjednocené paměti; zejména při 8 GB RAM začínejte malým modelem.

První přepis může trvat déle kvůli stahování vah. MLX zobrazuje neurčitý indikátor průběhu, faster-whisper průběh podle již přepsané délky audia. Žádná z těchto hodnot není odhad času do dokončení.

## Windows

Nainstalujte [uv](https://docs.astral.sh/uv/getting-started/installation/) a [FFmpeg](https://ffmpeg.org/download.html). FFmpeg musí být v PATH; pro faster-whisper se běžná média dekódují přibaleným PyAV, samostatný FFmpeg je nutný zejména pro MLX na Macu.

V PowerShellu ve složce aplikace:

```powershell
.\start.ps1
```

Pokud místní pravidla PowerShellu skript nepovolí, použijte přímo:

```powershell
uv sync --python 3.13 --no-dev
uv run --python 3.13 --no-dev uvicorn stt.app:app --host 127.0.0.1 --port 8765
```

Tato přímá varianta ukládá cache modelů také do výchozích uživatelských cache Hugging Face, namísto jejich soustředění do `data/` spouštěčem.

## Linux

Nainstalujte uv a případně FFmpeg z balíčků své distribuce. Ve složce aplikace spusťte:

```bash
bash start.command
```

## NVIDIA GPU na Windows/Linuxu

Inference používá CTranslate2/faster-whisper. Je potřeba podporovaná NVIDIA GPU, ovladač a odpovídající runtime knihovny. Aktuální řada CTranslate2 požaduje **CUDA 12 (cuBLAS) a cuDNN 9**. GPU používá FP16; CPU INT8. Přesné požadavky kontrolujte v [oficiálním návodu faster-whisper](https://github.com/SYSTRAN/faster-whisper#gpu).

Na Linuxu lze runtime knihovny přidat do prostředí aplikace:

```bash
uv pip install --python .venv/bin/python nvidia-cublas-cu12 'nvidia-cudnn-cu12==9.*'
export LD_LIBRARY_PATH="$(.venv/bin/python -c 'import os, nvidia.cublas.lib, nvidia.cudnn.lib; print(os.path.dirname(nvidia.cublas.lib.__file__) + ":" + os.path.dirname(nvidia.cudnn.lib.__file__))')${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
.venv/bin/python -m uvicorn stt.app:app --host 127.0.0.1 --port 8765
```

Po ručním přidání knihoven použijte poslední příkaz přímo: další `uv sync` může balíčky, které nejsou v projektu deklarované, odstranit. Na Windows použijte postup instalace CUDA/cuDNN z oficiální dokumentace a doplňte adresáře DLL do PATH. `nvidia-smi` samo o sobě nepotvrzuje přítomnost cuDNN.

Volba Automaticky vybere NVIDIA GPU, pokud ji CTranslate2 detekuje. Pokud knihovny chybějí nebo dojde paměť, úloha zobrazí chybu. Přepnutí na CPU je ruční, aby se nezamlčela chyba GPU. Podpora AMD/ROCm a Intel GPU v této verzi není implementována.

## Data, offline provoz a přístup

- Server se standardně váže pouze na `127.0.0.1`; jde o osobní aplikaci bez přihlašování. Otevře ji libovolný místní uživatel nebo proces s přístupem k tomuto portu.
- Rozhraní nevyužívá externí fonty, analytiku ani CDN.
- Zvuk se odesílá na lokální server, nikoli do služby pro přepis. Po dokončení nebo chybě se pracovní kopie audia odstraní; zdrojový soubor na disku se nemění. Při pádu procesu se zbytky odstraní při dalším startu.
- Text, názvy souborů a pomocný kontext zůstávají v `data/transcripts.sqlite3`, dokud přepis nesmažete. SQLite mazání není garantované bezpečné vymazání z disku, záloh či snapshotů.
- Spouštěče ukládají modely a pomocné soubory pod `data/`, nastavují `HF_HOME` a vypínají běžnou telemetrii Hugging Face. Při ručním spuštění může MLX používat výchozí uživatelskou cache.
- Po stažení modelu lze vynutit offline režim: před startem nastavte `HF_HUB_OFFLINE=1`. Nejdříve musí být konkrétní model pro konkrétní backend kompletně stažený. CPU/CUDA a MLX používají odlišné formáty vah.
- Limit souboru je 500 MiB; lze změnit proměnnou `STT_MAX_UPLOAD_MB`. Komprimovaný soubor se při dekódování může výrazně zvětšit v RAM.
- `STT_DATA_DIR` umožňuje změnit umístění databáze, pracovního audia a faster-whisper modelů. Pro změnu cache MLX nastavte rovněž `HF_HOME`.
- Spouštějte **jednu instanci a jeden Uvicorn worker** pro jeden adresář dat. Po restartu se rozpracované úlohy označí chybou a je třeba je nahrát znovu.

Pro přístup z telefonu nebo dalších počítačů by bylo potřeba doplnit autentizaci, HTTPS a správu přístupů; aktuální nastavení záměrně přijímá pouze místní hostnames a stejný webový origin. Inference využívá hardware serveru, nikoli GPU telefonu, na kterém máte otevřený prohlížeč.

## Testy a stav ověření

Testy jádra bez instalace závislostí:

```bash
python3 -m unittest discover -s tests -p test_core.py -v
```

Celá sada včetně API:

```bash
uv sync --python 3.13
uv run pytest -q
```

Při vytvoření aplikace prošlo 8 testů jádra (formáty, české znaky, časové značky, volba backendu a nastavení inference s náhradními modely). Ověřena je syntaxe Pythonu, JavaScriptu a Bash spouštěče i návaznost odkazů rozhraní na HTML prvky a lokální soubory. API testy jsou přiložené, ale nebyly spuštěny: prostředí blokovalo DNS/přístup na PyPI a závislosti nešlo nainstalovat. **Skutečný přepis ani běh GPU zatím nebyl na tomto počítači ověřen.** Soubor `uv.lock` vznikne při prvním úspěšném `uv sync`; přesné verze závislostí tedy zatím nejsou uzamčené.

## Technologie

- [faster-whisper](https://github.com/SYSTRAN/faster-whisper): NVIDIA CUDA a CPU, lokální modely Whisper.
- [MLX Whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper): akcelerace na Apple Silicon GPU.
- FastAPI, SQLite, čistý HTML/CSS/JavaScript bez sestavování frontendu.

Licence a případné podmínky použitých modelů a knihoven se řídí jejich vlastními repozitáři.
