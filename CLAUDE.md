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
| krátké kliknutí levým | se zbraněmi na těle je tasí, se zbraněmi v rukou útočí |
| stisk kolečka | přepnutí sestavy zbraní |
| levý Shift | sprint |

Kliknutí od tažení kamery se rozlišuje délkou stisku (do 0,25 s) a pohybem myši. Po 15 s bez kliknutí
se zbraně samy vrátí na tělo.

**Sestavy zbraní** (`FOpenWorldLoadout` v `OpenWorldCharacter.h`): meč + štít, obouruční meč.
Každá má model do pravé a levé ruky, pochvu, polohy zbraní na těle, bojový střeh (stance), animaci
útoku, okno zásahu, rozměry čepele, hmotnost a látku, ze které je čepel.

**Dva stavy zbraní:** nebojový (zbraně na těle, ruce volné) a bojový (zbraně v rukou, bojový střeh).
Podrobně v sekci „Fyzika ve hře“.

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
2. střeh: v bojovém stavu drží paže zbraně pořád a ve stoje se přidá pokrčení kolen a předklon;
   v nebojovém stavu se štítem na zádech jen tlumí švih paží,
3. útok: horní polovina těla vždy, nohy jen když postava stojí. Proto útok nezastavuje běh.

**Kde co je**

| Cesta | Obsah |
|---|---|
| `Source/OpenWorld/OpenWorldCharacter.*` | kamera, vstupy, sprint, sestavy, stavy zbraní, útok, střet čepele, test ve hře |
| `Source/OpenWorld/OpenWorldGeneratedMounts.h` | polohy zbraní na těle; generuje skript, ručně needitovat |
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
| `create_weapons.py` | meč, obouruční meč, štít a pochva včetně kolizních tvarů a látky |
| `create_attack_anims.py` | bojové střehy, útoky a polohy zbraní na těle; `SLASH_PREVIEW=1` jen náhled, `SLASH_ONLY=<sestava>` jen jedna, `SLASH_MOUNTS_ONLY=1` jen polohy na těle |
| `audit_collisions.py` | měří průniky těla, zbraní a štítu ve všech kombinacích stavu a pohybu (24 případů) |
| `mounts.json` | polohy zbraní na těle pro kontrolu; generuje `create_attack_anims.py` |
| `setup_anim_blueprint.py` | nastaví rodiče `ABP_Unarmed` (stačí jednou) |

Skripty běží přes Python v editoru, **se zavřeným Unreal Editorem**:

    "C:/Program Files/Epic Games/UE_5.8/Engine/Binaries/Win64/UnrealEditor-Cmd.exe" C:/Dev/OpenWorld/OpenWorld.uproject -run=pythonscript -script=C:/Dev/OpenWorld/Tools/<skript>.py -unattended -nosplash -NullRHI

**Kompilace:**

    "C:/Program Files/Epic Games/UE_5.8/Engine/Build/BatchFiles/Build.bat" OpenWorldEditor Win64 Development -Project="C:/Dev/OpenWorld/OpenWorld.uproject" -WaitMutex

**Test ve hře bez okna:** `UnrealEditor-Cmd.exe OpenWorld.uproject -game -OWSelfTest -NullRHI -benchmark -fps=60`
(bez `-benchmark -fps=60` běží na tisících snímků za sekundu a nic nevypovídá). Výsledky jsou v logu
na řádcích `OWSELFTEST` a `OWCONTACT`: polohy rukou, zásahy do dřeva a oceli a hlavně
`deepest_blade_in_target`, tedy jak hluboko se vykreslená čepel dostala do terče. Má být do 1 cm.

Když skript změní polohy zbraní na těle, přepíše i `OpenWorldGeneratedMounts.h`, takže je potom
potřeba hru znovu zkompilovat.

**Stav** (commit `bf2c94c`). Hotovo: kamera, sprint, dvě sestavy zbraní, nebojový a bojový stav
s tasením na první stisk a schováním po 15 s, bojové střehy, seky i za běhu, kontrola průniků
(0 ve 24 případech), látky ocel a dřevo, střet čepele se zastavením o povrch a fyzikální reakcí.

**Co dál** je v sekci „Plán dalších kroků“.

## Jak pracujeme

- **Uživatel hru zkouší v editoru a hodnotí, jak vypadá.** Já vzhled nevidím, ověřuji měřením:
  kontrolou průniků a testem ve hře. Do hlášení patří naměřená čísla a otevřeně i to, co ověřené není.
- **Větší změnu chování nejdřív popsat a nechat schválit.** Uživatel má jasnou představu o hraní a
  návrh, který ji míjí, vrátí.
- **Commit a push až na pokyn,** každé zvlášť. Uživatel je potvrzuje po vyzkoušení.
- **Před skripty a kompilací musí být zavřený Unreal Editor.** Po pádu editoru může knihovnu hry
  držet okno Crash Reporteru (`CrashReportClientEditor`), dokud se nezavře.
- **Python v systému není.** Na pomocné skripty mimo editor použít ten z enginu:
  `C:/Program Files/Epic Games/UE_5.8/Engine/Binaries/ThirdParty/Python3/Win64/python.exe`.
- **Dlouhé běhy** (generování animací trvá minuty) pouštět na pozadí.

## Plán dalších kroků

V tomto pořadí, pokud uživatel neřekne jinak. Každý krok končí kontrolou průniků, testem ve hře
a vyzkoušením uživatelem.

1. **Pohyb tasení a schování zbraní.** Dnes zbraň přeskočí z těla do ruky a paže se do střehu jen
   prolnou (0,3 s). Cíl: ruka sáhne pro zbraň, vezme ji a přenese do střehu, bez průniku.
   - Meč z pochvy: čepel musí vyjíždět po ose pochvy. Paže na plný tah 80 cm z levého boku nedosáhne,
     takže se pochva musí při tasení natáčet za čepelí kolem svého závěsu (ústí zůstává na místě).
   - Obouruční meč ze zad: krátce povytáhnout po ose a pak přetočit přes pravé rameno dopředu.
   - Štít ze zad: rukou za záda mezi lopatky dosáhnout nejde. Realisticky se štít na řemenu přesune
     kolem levého boku dopředu a ruka ho převezme.
   - Zbraň se má přichytit k ruce ve chvíli, kdy úchop ruky přesně sedí na její poloze na těle, aby
     nepřeskočila.
   - Schování je stejný pohyb pozpátku. Během pohybu se nesmí dát útočit, nebo se má útok zařadit.
2. **Držený předmět odtlačovaný překážkou** (viz „Fyzika ve hře“, rozhodnuto uživatelem). Body
   předmětu, které by skončily ve stěně, odtlačit ven, z toho spočítat posun a natočení předmětu
   a dopočítat paži. Jen proti pevnému okolí, ne proti nepřátelům. Stejný postup pak použít na
   vlastní výbavu: lokty proti štítu na zádech, což by nahradilo dnešní tlumení švihu paží.
3. **Doladění toho, co je hotové jen zhruba:**
   - štít na zádech sedí vysoko (střed u krku, přesah 10 cm nad hlavu),
   - bojový střeh je ve stoje nehybný, chybí v něm dýchání,
   - volná bedna se po zásahu obouručním mečem dostane 3,4 cm do čepele,
   - při startu útoku ve stoje se chodidla posunou asi o 4 cm,
   - levé zápěstí při obouručním seku se krátce ohne až o 81° a předloktí přetočí o 108°.
4. **Nepřítel a krytí štítem.** Cíl, který se hýbe a útočí, zásah počítaný na povrch těla místo
   kolizní kapsle a štít, který ránu zastaví podle stejných pravidel jako čepel.
5. **Deformace a viditelné poškození** podle látky (zásek ve dřevě, promáčknutí, rozbití na kusy).
6. **Samotný otevřený svět:** krajina, World Partition, procedurální rozmístění. Zatím se hraje na
   mapě ze šablony.

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

## Fyzika ve hře

Tady je sepsané, jak se ve hře věci chovají při dotyku. Dnešní stav je výchozí bod, který se bude
postupně ladit. Každou změnu chování zapsat sem, včetně čísel.

### Zásady

1. **Všechno pevné má povrch a látku.** Povrch je kolizní tvar, látka (`UOpenWorldPhysicalMaterial`)
   říká, jak je věc tvrdá, těžká a kolik vydrží.
2. **Pohyb se zastaví o povrch.** Nic se nevykreslí uvnitř něčeho jiného, ani na jeden snímek.
   Proto se dotyk hledá dopředu, v póze, která se teprve vykreslí.
3. **O následku rozhodnou látky a hybnost,** ne animace. Tvrdost určí, jestli se čepel zasekne, nebo
   odskočí. Hmotnost a rychlost určí ráz.
4. **Platí to oběma směry.** Když se čepel zastaví o bednu, musí se i bedna zastavit o čepel.
5. **I cesta zpět je pohyb.** Po dotyku se věc vrací dráhou, o které se ví, že je volná.

### Výchozí stav (hodnoty k ladění)

Všechny jsou nastavitelné v `BP_ThirdPersonCharacter` (sekce Combat | Contact a Loadouts) nebo
ve skriptu `Tools/create_materials.py`.

| Co | Dnes | Kde |
|---|---|---|
| Tvrdost oceli / dřeva | 7,5 / 2,5 | `create_materials.py` |
| Hustota oceli / dřeva | 7,85 / 0,70 g/cm³ | `create_materials.py` |
| Houževnatost oceli / dřeva | 4,0 / 1,0 | `create_materials.py` |
| Čepel se zasekne, když je tvrdší aspoň | 1,2× | `BiteHardnessRatio` |
| Zaseknutí: jak dlouho drží, jak rychle se vrací | 0,12 s, 1,2× rychlost seku | `BiteHoldTime`, `BiteRewindRate` |
| Odskok: jak dlouho drží, jak rychle se vrací | 0,04 s, 2,0× rychlost seku | `BounceHoldTime`, `BounceRewindRate` |
| Poškození | základ sestavy × poměr tvrdostí (0,2–3) × rychlost čepele / 1200 cm/s (0,2–2) ÷ houževnatost cíle | `ResolveContact` |
| Ráz | rychlost čepele × hmotnost zbraně × 3 (váha těla za čepelí) | `StrikeMassScale` |
| Hmotnost meče / obouručního meče | 1,3 / 2,8 kg | sestavy |
| Okno, kdy čepel zasahuje | 0,27–0,52 s / 0,34–0,66 s od začátku seku | sestavy |
| Neznámý povrch bez látky | tvrdost 5 | `DefaultHardness` |

### Zbraně: nebojový a bojový stav

Zadal uživatel. Logika je v `OpenWorldCharacter` (`DrawWeapons`, `SheatheWeapons`, `ApplyWeaponState`).

- **Nebojový stav je výchozí.** Jednoruční meč je v pochvě u levého boku a štít na zádech. Obouruční
  meč je na zádech. Ruce jsou volné a hýbou se podle běžných animací.
- **Levé tlačítko v nebojovém stavu zbraně jen tasí,** neútočí.
- **Bojový střeh:** štít před levou částí hrudi, meč připravený vpravo, nebo kryt obouručním mečem
  před hrudí. Ve stoje jsou kolena pokrčená (pánev o 5 cm níž) a trup lehce předkloněný. Za chůze
  a běhu drží střeh jen paže, nohy a trup jdou z běžných animací.
- **Levé tlačítko v bojovém stavu je útok.** Při seku mečem ustoupí štít doleva, aby mu nestál v cestě.
- **Po 15 s od posledního stisku levého tlačítka** (`CombatTimeout`) se zbraně vrátí na tělo.
- **Se štítem na zádech se paže houpou jen napůl** (`SheathedArmDamping` 0,5). Běžná animace běhu
  vede lokty až 30 cm za záda, kam se štít nevejde. Hodnota musí být stejná v `owlib.py` i v sestavě.
- **Polohy zbraní na těle** hledá `create_attack_anims.py` proti povrchu těla ve všech snímcích stání,
  chůze a běhu a zapisuje je do `Tools/mounts.json` (pro kontrolu) a do
  `Source/OpenWorld/OpenWorldGeneratedMounts.h` (pro hru). Ručně se needitují.

**Co chybí:** pohyb tasení a schování. Zbraň dnes přeskočí z těla do ruky a paže se do střehu jen
prolnou (0,3 s). Správně má meč vyjet z pochvy po její ose a štít se přehodit ze zad, bez průniku.

### Držený předmět u překážky (rozhodnuto, zatím neuděláno)

Dnes nesená zbraň stěnou projde, střet se hlídá jen během seku. Rozhodnutí uživatele:

- **Zbraň se neschovává ani nepřepíná do jiné pózy.** Postava ji drží dál.
- **Překážka na předmět působí fyzikálně.** Body předmětu (meče, štítu, čehokoli v ruce) se posunou
  podle toho, jak proti nim stěna tlačí: předmět ustoupí jen o tolik, o kolik musí, a paže ho následuje.
- **Rozhoduje, jestli předmět překážku prorazí.** Většinou ne, zvlášť když postava jen stojí. Kdy
  ano, určí látky a hybnost, stejně jako u seku.
- Platí to pro jakýkoli držený předmět, ne jen pro meč.

Přepínání mezi dvěma pevnými pózami podle překážek bylo zamítnuto: v boji u stěny by bralo kontrolu
nad zbraní a reagovalo by i na nepřátele.

### Otevřené otázky

- **Jak přesně stěna na předmět působí** (viz „Držený předmět u překážky“ výše): kolik bodů
  předmětu sledovat, jak rychle se smí vracet a kdy se místo předmětu má pohnout nebo rozbít překážka.
- **Zbraně v nebojovém stavu** leží na těle, takže by se do stěn dostat neměly. Obouruční meč na
  zádech je ale delší než trup a je potřeba změřit, kam přesahuje.
- **Zásah do postav** se počítá na kolizní kapsli, ne na povrch těla.
- **Deformace a viditelné poškození** nejsou. Předmět má jen výdrž a po jejím vyčerpání zmizí.
- **Štít** útoky nekryje.

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
- **Návrh nejdřív projít v hlavní herní situaci.** Navrhl jsem stahování zbraně u překážek a neověřil,
  co udělá v boji u stěny, kde by hráči bralo zbraň z ruky. Než začnu řešení stavět, projít si ho
  ve chvíli, kdy na něm hráči záleží nejvíc, a u větších změn chování ho nejdřív popsat uživateli.
- **Hledání musí vzorkovat stejně hustě jako kontrola.** Polohy zbraní na těle jsem hledal na 18 pózách,
  kontrola pak na všech snímcích našla ruku míjející záštitu a patu u hrotu meče, obojí jen na snímek
  či dva. Co se ověřuje hustě, musí se hustě i navrhovat (hrubý výběr, pak přesné ověření nejlepších).
- **Podezření na chybu měření ověřit daty, ne úvahou.** U štítu na zádech jsem výsledek považoval za
  chybu měření, ale výpis konkrétních bodů ukázal, že je správně (lokty při běhu jdou 30 cm za záda).
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
