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
Každá má model do pravé a levé ruky, držení (stance), animaci útoku a časy zásahu.

**Animace se skládají ve třech vrstvách** (`OpenWorldAnimInstance`, rodič animačního Blueprintu `ABP_Unarmed`):
1. pohyb z animačního Blueprintu (stání, chůze, běh, skok),
2. držení zbraní na obou pažích, pořád,
3. útok: horní polovina těla vždy, nohy jen když postava stojí. Proto útok nezastavuje běh.

**Kde co je**

| Cesta | Obsah |
|---|---|
| `Source/OpenWorld/OpenWorldCharacter.*` | kamera, vstupy, sprint, sestavy, útok, zásah |
| `Source/OpenWorld/OpenWorldAnimInstance.*` | vrstvy držení a útoku nad animačním Blueprintem |
| `Source/OpenWorld/OpenWorldPlayerController.*` | kurzor myši, limity náklonu kamery |
| `Source/OpenWorld/Variant_*` | ukázky ze šablony Epicu (Combat, Platforming, SideScrolling), hra je nepoužívá |
| `Content/Weapons/` | vygenerované modely, materiály a animace zbraní |
| `Content/ThirdPerson/`, `Content/Characters/` | obsah šablony: mapa, Blueprinty hráče, mannequin |
| `Tools/` | skripty, které modely a animace vyrábějí a kontrolují |

**Modely a animace zbraní se negenerují ručně, vyrábějí je skripty v `Tools/`.** Úprava = změna čísel
ve skriptu a nové spuštění, ne ruční zásah do assetu.

| Skript | K čemu |
|---|---|
| `owlib.py` | sdílená knihovna: matematika, kostra a IK, kolizní povrch postavy, tvary zbraní |
| `create_weapons.py` | meč, obouruční meč, štít včetně kolizních tvarů |
| `create_attack_anims.py` | držení zbraní a útoky; `SLASH_PREVIEW=1` jen náhled, `SLASH_ONLY=<sestava>` jen jedna |
| `audit_collisions.py` | měří průniky těla, zbraní a štítu ve všech kombinacích pohybu |
| `setup_anim_blueprint.py` | nastaví rodiče `ABP_Unarmed` (stačí jednou) |

Skripty běží přes Python v editoru, **se zavřeným Unreal Editorem**:

    "C:/Program Files/Epic Games/UE_5.8/Engine/Binaries/Win64/UnrealEditor-Cmd.exe" C:/Dev/OpenWorld/OpenWorld.uproject -run=pythonscript -script=C:/Dev/OpenWorld/Tools/<skript>.py -unattended -nosplash -NullRHI

**Kompilace:**

    "C:/Program Files/Epic Games/UE_5.8/Engine/Build/BatchFiles/Build.bat" OpenWorldEditor Win64 Development -Project="C:/Dev/OpenWorld/OpenWorld.uproject" -WaitMutex

**Test ve hře bez okna:** `UnrealEditor-Cmd.exe OpenWorld.uproject -game -OWSelfTest -NullRHI`, výsledky jsou
v logu na řádcích `OWSELFTEST` (polohy rukou, rychlost, stav útoku).

**Stav.** Hotovo: kamera, sprint, dvě sestavy zbraní s držením a seky, útok za běhu, kontrola průniků.
Další na řadě: střet ve hře (pravidlo 1, bod 3). Zásah se zatím vyhodnocuje koulí před postavou,
ne dráhou čepele, a meč se o nic nezastaví.

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
- **Nenastavovat funkce pro tým, když pracuje jeden člověk.** Zamykání souborů v Git LFS udělalo
  z assetů soubory jen pro čtení a blokovalo úpravy. Výchozí nastavení volit podle skutečného provozu.
- **Názvy nesmí kolidovat s vestavěnými.** Projekt pojmenovaný `Temp` se nezkompiloval, protože z názvu
  vznikl identifikátor, který engine už má. U nových názvů zvážit, co se z nich odvodí.
