# CodeDesk

Desktop code agent wrapper za OpenRouter free modele. Aplikacija deluje v slogu Claude Code / Codex: izberes mapo, napises navodilo, agent naredi snapshot tekstovnih datotek, predlaga spremembe in jih lahko sprejmes ali zavrnes. Pogovor se nadaljuje, zato lahko po zavrnitvi ali sprejemu napises naslednje navodilo in agent ima kontekst seje.

## Zagon

```powershell
python .\codex_free_wrapper.py
```

Ali z dvojnim klikom:

```text
Run CodeDesk.bat
```

API key se sam nalozi iz `local_config.json` ali iz okoljske spremenljivke `OPENROUTER_API_KEY`. Key ni prikazan v UI. `local_config.json` je v `.gitignore` in ga aplikacija ne poslje modelu kot del projekta.

## Funkcije

- avtomatski model fallback brez roccne izbire modela
- vrstni red: Qwen Coder free, DeepSeek free, GLM free, Kimi free, OpenRouter free router
- back-and-forth chat seja z `Run / Continue`
- `Auto apply` je privzeto vklopljen
- `Accept Changes` in `Reject Changes`, ko auto apply izklopis
- `New Chat` za cisto sejo
- context scope se izbere sam glede na velikost projekta
- bolj minimalističen Windows-friendly layout brez macOS okenskih pik
- sidebar je razdeljen na jasne tekstovne glavne gumbe in kompaktne icon-only hitre gumbe
- pulzirajoc status indikator, hover feedback na gumbih in subtilen flash pri povzetkih
- sredinski `Working Summary` za kratek opis trenutnega dela
- manjsi terminalni `Activity` panel
- desni diff pogled: zgoraj seznam urejenih datotek, spodaj diff izbrane datoteke
- zeleni `+` dodatki in rdeci `-` izbrisi
- opcijski `Auto apply`
- ignoriranje `.git`, `node_modules`, build map, virtualenv map, `local_config.json` in binarnih datotek

## Varnostna opomba

Ker je API key credential, ga ne commitaj v repozitorij. Trenutni `local_config.json` je namenoma ignoriran z gitom. Ce je bil key kdaj poslan v chat ali javno mesto, ga je najbolje rotirati v OpenRouter nastavitvah.
