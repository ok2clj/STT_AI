# Popis verzí

## 0.2.1 — Oprava dekódování audia s PyAV 19

- Opravena chyba `TypeError: open() got an unexpected keyword argument 'metadata_errors'`, která blokovala načtení audia ještě před přepisem. Starší dekodér faster-whisper používal parametr odstraněný v PyAV 19.
- Aplikace nyní používá vlastní malý dekodér nad veřejným API PyAV, bez parametru `metadata_errors` a bez úprav knihoven v prostředí uživatele. Podporuje i instalovaný PyAV 19; downgrade není potřeba.
- Zachováno dekódování na mono float32 při 16 kHz pro všechny backendy. Resampler se na konci vyprázdní, aby se neztratily poslední vzorky audia. Prázdné a poškozené nahrávky se rozlišují.
- PyAV a NumPy jsou uvedeny jako přímé závislosti aplikace; podporovaná řada PyAV je `>=11,<20`.
- Přidáno šest regresních testů: skutečný WAV, stereo převzorkování a úplná délka výstupu, ticho, prázdný WAV, poškozený soubor a napojení skutečného dekodéru na engine s náhradní inferencí.
- Prošlo celkem **35 testů**. Skutečné dekódování ověřeno na PyAV **19.0.2**; kvalita inference ani GPU nejsou předmětem této opravy.

### Aktualizace

Aktualizujte soubory projektu, ukončete původně běžící server a znovu spusťte `start.command` nebo `start.ps1`. Neúspěšnou nahrávku nahrajte znovu: pracovní audio se při chybě odstraňuje. Existující přepisy a stažené modely není potřeba mazat.

## 0.2.0 — Procenta přepisu a vlastní české modely (22. 11. 2026)

### Nové funkce

- Průběh přepisu v procentech pro MLX, CTranslate2 a Transformers. Vedle procent se ukazuje zpracovaný čas a celková délka audia; průběh je dostupný i v historii.
- Procenta odpovídají délce dokončených zvukových úseků (maximálně 30 sekund), včetně ticha. Hodnota 100 % se nastaví až po uložení výsledku a odstranění pracovní kopie audia.
- Oddělené fáze fronty, stažení modelu, načtení modelu, dekódování audia, přepisu a ukládání. Stahování ani načítání se nevydává za procenta přepisu.
- Správa modelů v prohlížeči: katalog, stažení na pozadí, stav stažení, opakování při chybě a výběr staženého modelu.
- Přidání vlastního Hugging Face ID nebo odkazu. Podporované formáty: Whisper Transformers/Safetensors, CTranslate2 a MLX Whisper.
- Předvolený model `mikr/whisper-large-v3-czech-cv13`. Původní váhy se používají lokálně přes Transformers/PyTorch, bez potřeby konverze na CTranslate2 nebo MLX.
- Apple GPU MPS pro Transformers, NVIDIA CUDA a CPU; základní modely na Macu nadále používají MLX.
- Trvalé uložení vlastního katalogu a stažené revize. Přerušené stahování se po restartu označí chybou a lze ho zopakovat.

### Technické změny

- Všechny backendy přijímají 16kHz mono audio dekódované PyAV. MLX při přepisu nepotřebuje samostatný proces FFmpeg.
- Globální časové značky úseků se skládají ze skutečné pozice v audiu; při výpadku rozpoznávání či tichu se neposunou.
- Načítání stažených vah pouze z lokálního snapshotu. Backend Transformers používá přímo třídy Whisper a váhy Safetensors; nestahuje ani nespouští Python kód z modelových repozitářů.
- Spouštěče instalují rozšíření `hf` (Transformers a PyTorch). Při ruční instalaci: `uv sync --extra hf`.
- 28 automatických testů: celý cyklus API přes ASGI, polling probíhajícího přepisu, exporty, validace vstupů, katalog, stahování s náhradním zdrojem, volba backendu a časové značky. Ověřena syntaxe Pythonu, JavaScriptu, Bash a návaznost HTML prvků na skript.

### Ověření a omezení

Automatické testy prošly. Modelové inference a síťové stažení jsou v testech nahrazené, takže tyto výsledky nepotvrzují kvalitu skutečného přepisu ani funkčnost CUDA/MPS/MLX na konkrétním hardwaru. Prostředí pro vývoj blokuje stahování nových balíčků a nepřístupné Metal GPU nelze zde ověřit. České váhy nebyly v tomto prostředí staženy ani spuštěny.

Procenta se mění po dokončených úsecích, nikoli plynule podle uběhlého času. Krátká nahrávka do 30 sekund může zůstat na 0 % až do dokončení prvního úseku. Zpracování po úsecích může ovlivnit slova na jejich hranicích; přesnost přepisu a časových značek zkontrolujte. Stav stahování uvádí počet souborů, nikoli přenesené bajty.

## 0.1.0 — První verze (21. 11. 2026)

Lokální webová aplikace, nahrání audia, čeština a další jazyky, základní modely Whisper, backendy MLX/CTranslate2, historie v SQLite, úpravy textu a export TXT/SRT/VTT/JSON.
