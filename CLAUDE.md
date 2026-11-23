# OpenWorld

Open world hra z pohledu třetí osoby v Unreal Engine 5.8. C++ projekt, modul `OpenWorld`.
Repozitář: github.com/capecpavel-gh/OpenWorld (větev `main`, binární assety přes Git LFS).
S uživatelem se mluví česky. Kód, komentáře a commity jsou anglicky.

## Jak se v projektu zorientovat

**Hráč.** Blueprint `BP_ThirdPersonCharacter` (rodič v C++ `AOpenWorldCharacter`), model `SKM_Quinn_Simple`.
Quinn má jiné proporce než výchozí Manny, i když sdílejí kostru. Všechno se počítá na Quinn.

**Ovládání** (vstupy se vytvářejí v kódu postavy, ne jako assety):

| Vstup | Co dělá |
|---|---|
| WASD, mezerník | pohyb, skok |
| otáčení kolečka | zoom kamery |
| držení pravého tlačítka | otáčí kamerou i postavou |
| držení levého tlačítka | kamera obíhá kolem postavy |
| krátké kliknutí levým | útok podle aktuální sestavy |
| stisk kolečka | přepnutí sestavy zbraní |
| levý Shift | sprint |

**Sestavy zbraní** (`FOpenWorldLoadout` v `OpenWorldCharacter.h`): meč + štít, obouruční meč.
Každá má model do pravé a levé ruky, držení (stance), animaci útoku, okno zásahu, rozměry čepele,
hmotnost a látku, ze které je čepel.

**Látky.** Všechno pevné je z nějaké látky (`UOpenWorldPhysicalMaterial`): tření, pružnost a hustota
z enginu plus tvrdost a houževnatost. Zatím existuje ocel (tvrdost 7,5) a dřevo (2,5). Látku nese
materiál i kolize modelu, takže ji zásah vždy zjistí.

**Střet čepele** (`UpdateBladeContact` a `ResolveContact` v `OpenWorldCharacter.cpp`):
1. Každý snímek seku se z animace spočítá, kde bude čepel v póze, která se teprve vykreslí.
2. Body čepele se protáhnou světem z nynější polohy do té příští. První povrch v cestě sek zastaví
   přesně v okamžiku dotyku, dřív než se průnik vykreslí.
3. Podle tvrdosti se čepel buď zasekne (tvrdší než cíl), nebo odskočí. Cíl dostane poškození a ráz.
4. Meč se vrátí stejnou dráhou, kterou přišel. Ta je jediná zaručeně volná.

Zbraň a štít v ruce jsou zároveň pevný povrch pro volné fyzikální předměty.
Herní režim (`OpenWorldGameMode`) staví před start hráče řadu zkušebních terčů ze dřeva a oceli.

**Animace se skládají ve třech vrstvách** (`OpenWorldAnimInstance`, rodič animačního Blueprintu `ABP_Unarmed`):
1. pohyb z animačního Blueprintu (stání, chůze, běh, skok),
2. držení zbraní na obou pažích, pořád,
3. útok: horní polovina těla vždy, nohy jen když postava stojí. Proto útok nezastavuje běh.

**Kde co je**

| Cesta | Obsah |
|---|---|
| `Source/OpenWorld/OpenWorldCharacter.*` | kamera, vstupy, sprint, sestavy, útok, střet čepele, test ve hře |
| `Source/OpenWorld/OpenWorldAnimInstance.*` | vrstvy držení a útoku nad animačním Blueprintem, zastavení a návrat seku |
| `Source/OpenWorld/OpenWorldPhysicalMaterial.*` | látka: fyzikální materiál s tvrdostí a houževnatostí |
| `Source/OpenWorld/OpenWorldProp.*` | pevný předmět z jedné látky (kůl, blok, bedna), dá se rozbít |
| `Source/OpenWorld/OpenWorldGameMode.*` | herní režim, zkušební terče |
| `Source/OpenWorld/OpenWorldPlayerController.*` | kurzor myši, limity náklonu kamery |
| `Content/Materials/Substances/` | vygenerované textury, materiály a látky (ocel, dřevo) |
| `Source/OpenWorld/Variant_*` | ukázky ze šablony Epicu (Combat, Platforming, SideScrolling), hra je nepoužívá |
| `Content/Weapons/` | vygenerované modely, materiály a animace zbraní |
| `Content/ThirdPerson/`, `Content/Characters/` | obsah šablony: mapa, Blueprinty hráče, mannequin |
| `Tools/` | skripty, které modely a animace vyrábějí a kontrolují |

**Modely a animace zbraní se negenerují ručně, vyrábějí je skripty v `Tools/`.** Úprava = změna čísel
ve skriptu a nové spuštění, ne ruční zásah do assetu.

| Skript | K čemu |
|---|---|
| `owlib.py` | sdílená knihovna: matematika, kostra a IK, kolizní povrch postavy, tvary zbraní |
| `create_materials.py` | textury, materiály a látky pro ocel a dřevo; spouští se před `create_weapons.py` |
| `create_weapons.py` | meč, obouruční meč, štít včetně kolizních tvarů a látky |
| `create_attack_anims.py` | držení zbraní a útoky; `SLASH_PREVIEW=1` jen náhled, `SLASH_ONLY=<sestava>` jen jedna |
| `audit_collisions.py` | měří průniky těla, zbraní a štítu ve všech kombinacích pohybu |
| `setup_anim_blueprint.py` | nastaví rodiče `ABP_Unarmed` (stačí jednou) |

Skripty běží přes Python v editoru, **se zavřeným Unreal Editorem**:

    "C:/Program Files/Epic Games/UE_5.8/Engine/Binaries/Win64/UnrealEditor-Cmd.exe" C:/Dev/OpenWorld/OpenWorld.uproject -run=pythonscript -script=C:/Dev/OpenWorld/Tools/<skript>.py -unattended -nosplash -NullRHI

**Kompilace:**

    "C:/Program Files/Epic Games/UE_5.8/Engine/Build/BatchFiles/Build.bat" OpenWorldEditor Win64 Development -Project="C:/Dev/OpenWorld/OpenWorld.uproject" -WaitMutex

**Test ve hře bez okna:** `UnrealEditor-Cmd.exe OpenWorld.uproject -game -OWSelfTest -NullRHI -benchmark -fps=60`
(bez `-benchmark -fps=60` běží na tisících snímků za sekundu a nic nevypovídá). Výsledky jsou v logu
na řádcích `OWSELFTEST` a `OWCONTACT`: polohy rukou, zásahy do dřeva a oceli a hlavně
`deepest_blade_in_target`, tedy jak hluboko se vykreslená čepel dostala do terče. Má být do 1 cm.

**Stav.** Hotovo: kamera, sprint, dvě sestavy zbraní s držením a seky, útok za běhu, kontrola průniků
animací, látky ocel a dřevo, střet čepele se zastavením o povrch a fyzikální reakcí.

**Co pravidlo 1 zatím nesplňuje:**
- Nesená zbraň projde zdí, když k ní postava dojde. Střet se hlídá jen během seku.
- U postav se zásah počítá na kolizní kapsli, ne na povrch těla.
- Deformace a viditelné poškození neexistují. Předmět má jen výdrž a po jejím vyčerpání zmizí.
- Štít útoky nekryje (zatím nikdo neútočí).

## Pravidla

### 1. Nic neprochází ničím

Každá postava a každý asset (zbraň, štít, rekvizita) má vlastní kolizní povrch, který přesně kryje to,
co je vidět. Modely a animace se nesmí prolínat.

1. **Povrchy.** Nový asset není hotový, dokud nemá kolizní povrch odpovídající tomu, co se kreslí.
   Povrch postavy se počítá z jejího vlastního modelu (`Tools/owlib.py`), ne odhadem.
2. **Připravený obsah.** Držení i animace musí udržet každý povrch vně všech ostatních (zbraň a tělo,
   štít a paže, paže a trup, ruka a ruka, pokud spolu něco nedrží). Ověřuje se to skriptem
   `Tools/audit_collisions.py`, ne okem. Animace s naměřeným průnikem není hotová.
3. **Střet ve hře.** Když se dvě věci potkají, pohyb se zastaví o povrch. Co bude dál, rozhodne fyzika
   (odstrčení, odhození, deformace, poškození), nikdy to, že jeden model projede druhým.

Při hlášení práce uvádět naměřená čísla z kontroly. Co se proti povrchům ověřit nedalo, říct otevřeně.

### 2. Z každé chyby se zapíše poučení

Když se ukáže chyba v mé práci (pád, špatný výsledek, něco, co uživatel musel vrátit), po opravě
přidám jeden řádek do sekce **Poučení z chyb** níže: proč k chybě došlo a čemu se příště vyhnout.
Krátce a obecně, aby poučení platilo i mimo ten jeden případ. Bez popisu, jak probíhala oprava.

Před prací v oblasti, které se některé poučení týká, si ho přečíst.

## Poučení z chyb

- **Vstupy cizích funkcí neodhadovat.** Engine shodil hru, protože funkce na prolínání kostí vyžaduje
  normalizované rotace a póza z animačního Blueprintu je nemá. U funkcí enginu ověřit, co předpokládají
  o vstupu, nebo si vstup upravit sám.
- **Test musí projít stejnou cestou jako hra.** Automatický test pád nezachytil, protože pózu začal
  vyhodnocovat až po úvodním prolnutí. U každého testu si říct, kterou část kódu skutečně spustí.
- **Ověřovat na tom, co se opravdu zobrazí.** Pohyb jsem kontroloval na drátěné postavě bez objemu,
  takže průniky rukou a zbraní tělem nebyly vidět. Kontrola musí měřit stejnou věc, kterou uvidí hráč.
- **Počítat na skutečných datech, ne na výchozích.** Animace byly spočítané na proporce jiné postavy,
  než jakou hráč používá, a ruce pak neseděly. Vždy si ověřit, se kterým modelem, kostrou a měřítkem
  hra doopravdy pracuje.
- **Obsah ověřovat v kombinaci, ve které běží.** Držení zbraní bylo čisté ve stoje, ale za běhu do něj
  narážela stehna. Co se ve hře skládá z více vrstev, musí se kontrolovat složené.
- **Počítat s tím, že uložení data změní.** Uložená animace se po kompresi lišila od vypočítané až
  o 2 cm a délka mimo násobek 1/30 s kompresi shodila. Po uložení načíst zpět a změřit znovu,
  s rezervou na nepřesnost.
- **Cesta zpět je taky pohyb.** Meč se o terč zastavil správně, ale při návratu do držení jím projel
  (15,9 cm). Každý pohyb, i ten „úklidový“ po hlavní akci, musí splnit stejná pravidla jako akce sama.
- **Pravidlo o dvou věcech platí oběma směry.** Čepel se zastavila o bednu, ale bedna pak vjela do
  čepele, protože zbraň neměla pro fyziku povrch. U každého vztahu ověřit obě strany v pohybu.
- **Když číslo nesedí, nejdřív ověřit měření.** Třikrát jsem ladil hru podle údaje, který byl špatně
  změřený (porovnání o snímek vedle, terč mimo dosah). Než opravím měřenou věc, zkontrolovat, co
  přesně měření porovnává.
- **Testovat za podmínek, ve kterých hra běží.** Test bez okna běžel na 2000 snímcích za sekundu, takže
  neodhalil nic, co závisí na délce snímku. Podmínky testu (rychlost, rozměry, časování) nastavit
  jako ve skutečném provozu.
- **Nenastavovat funkce pro tým, když pracuje jeden člověk.** Zamykání souborů v Git LFS udělalo
  z assetů soubory jen pro čtení a blokovalo úpravy. Výchozí nastavení volit podle skutečného provozu.
- **Názvy nesmí kolidovat s vestavěnými.** Projekt pojmenovaný `Temp` se nezkompiloval, protože z názvu
  vznikl identifikátor, který engine už má. U nových názvů zvážit, co se z nich odvodí.
