# Nuvio Hub 6.0.9 — izmjene i provjere

**Status: lokalni testni kandidat, 30. rujna 2026.** Izmjene su napravljene na dostavljenom 6.0.8 source ZIP-u. GitHub `MegaNexusMediaPlayer/Nuvio-Hub` / `main` nije mijenjan; pročitani javni README još je bio na 6.0.7. Ovo nije potvrda rada na stvarnom Kodi 22 RC1 uređaju.

## Što je promijenjeno

| Područje | Implementacija u kandidatu |
|---|---|
| Home → HUB | Gumb **HUB** je iza **Settings** u oba Home rasporeda. Back na Homeu više ne zatvara frontend. Back u kolekciji/pretrazi vraća na Home. Izlaz na glavni HUB je izričit odabir gumba. |
| Povratak iz filma | Zadržan je obični native `WindowXML` ispod privremenih dijaloga. Pri povratku iz fullscreen playera podloga je Nuvio scena, ne HUB launcher. Roditeljski ekran i odabir ostaju u memoriji. Stvarni frame-by-frame prikaz treba provjeriti na uređaju. |
| Sat i vrijeme | Jedan trajni prekidač, uz migraciju stare skin postavke. Isti uvjet vidljivosti koriste Home, detalji/katalozi, IPTV i screensaver. U dostavljenom HUB launcheru uopće nema dinamičkih sat/vrijeme kontrola. |
| Video screensaver | Izbor Image/GIF ili MP4/M4V/MKV/WebM/MOV/AVI/TS/M2TS datoteke; loop u vlastitom videowindowu, bez zvuka. Slika ostaje fallback. Pauzirani ili aktivni korisnički medij nije zamijenjen. Prethodno mute stanje vraća se pri zatvaranju. Kod koristi odvojeni screensaver video skript jer pokretanje videa deaktivira Kodi screensaver. |
| Glumci i pretraga | Ne skrivaju se greške kao prazna filmografija. Podržani su People Search katalog za filmove i serije, moderni i legacy manifest extras, posebna ruta za kartice osoba, opcionalni TMDb cast/crew fallback i sačuvan upit pri Browse all. Pretraga koristi i anime/custom tipove koje provider oglašava. Višak kategorija ostaje dostupan pod More search categories. |
| Više stream addona | Odmah iza metadata odabira je popis stream addona sa zasebnim On/Off. Stari odabir ostaje upgrade default; novi su opt-in. Svaki source pokazuje ime addona. Redoslijed, duplikati, zaglavlja i titlovi se ne uklanjaju. Reprodukcija koristi provider baš odabranog rezultata. |
| IPTV | Prvi klik je preview, drugi klik istoga aktivnog kanala je native fullscreen. IPTV dijalog se tijekom fullscreen prikaza uklanja iz native modalnog sloja, a zatim se vraćaju isti objekt, grupa, kanal i EPG. Back/Stop ne zatvara IPTV u HUB. Za HUB postoji zaseban gumb. Stop/EOF ne pokreće kanal ponovno. |

## Bitne konfiguracijske granice

Za filmografiju bez dodatnog ključa metadata manifest mora objaviti **People Search za filmove i serije**. To treba uključiti u AIOMetadata/provider konfiguraciji i osvježiti ili ponovno uvesti manifest. Kada provider to ne nudi, moguće je unijeti opcionalni TMDb API ključ u **Settings → Add-ons → Actor search fallback**. Naziv pretrage ne može sam proizvesti podatke koje provider ne nudi. Dostupnost i potpunost rezultata ovise o provideru.

Video screensaver reproducira datoteku koja je dostupna Kodi file browseru; format spremnika ne jamči da konkretan codec radi na svakom uređaju. Ako je korisnikov video pauziran, screensaver prikazuje sliku umjesto preuzimanja jedinog playera. Ako datoteka nedostaje, ne može se otvoriti ili se ne može sigurno isključiti zvuk, koristi se slika.

PVR preview se postavlja preko stvarne Kodi postavke `pvrplayback.switchtofullscreenchanneltypes`: prethodna se vrijednost čita, privremeno bira preview i vraća u `finally`. JSON-RPC `Player.Open(channelid)` nema dodanu izmišljenu `windowed` opciju. Nisu mijenjani Windows fullscreen, rezolucija ni video zoom. Izgled s Windows video izlazom još mora potvrditi ručni test.

## Što je stvarno izvršeno

| Provjera | Rezultat |
|---|---|
| Ciljani automatizirani testovi | **243/243 PASS**, od toga **51 novi test** za ove zahtjeve |
| Release guard | **24/24 PASS** |
| Python datoteke | **255 compile PASS** na **CPython 3.13.5** |
| XML / JSON | **145 XML**, **7 JSON** parsiranja bez greške |
| Stvarni isporučeni ZIP | Raspakiran; CRC provjere, sva četiri manifesta i unutarnji component hashovi prošli |
| Import iz raspakiranog ZIP-a | **39 modula PASS**, uključujući session, saver i nove backend module |
| Asset reference u paketu | **1441 provjera PASS** |
| Jedinstvena verzija | Backend, frontend, skin i screensaver **6.0.9** |
| Kodi dependency floor | Zadržani `xbmc.python 3.0.0` i `xbmc.gui 5.17.0`; stvarni Kodi runtime nije korišten |

Testovi koriste eksplicitne zamjene za Kodi API na njegovim granicama. Prolaz znači provjerenu logiku i strukturu paketa, **ne** dokaz stvarnog renderiranja, AV izlaza ili instalacije na Kodi 22 RC1. Raniji testovi koji su tražili Back → HUB i zatvaranje IPTV prozora prilagođeni su novom zahtjevu; dodane su zasebne provjere da takav izlaz više nije moguć. Stari source-order test i dalje provjerava neizmijenjene izvorne redove, uz novu zasebnu oznaku stvarnog providera.

Glavne nove provjere pokrivaju: čuvanje starog stream odabira; strogi all-off; opt-in dodatnih providera; odbijanje metadata-only addona; type/ID filters; podrijetlo sourceova i očuvanje headera/titlova; ponašanje kad jedan provider ne odgovori; Back/HUB odvajanje; PVR preview i vraćanje preferencije čak i pri grešci; zadržavanje IPTV objekta; rehidraciju grupa/EPG-a bez autoplayja; zajednički sat/vrijeme prekidač; actor IDs i rute; otkazanu pretragu; zabranu neautoriziranog TMDb poziva; istekao screensaver handoff; zaštitu drugog videa od kasnog Stop događaja; screensaver loop i vraćanje mute stanja.

### Ponovljivo pokretanje

```sh
PYTHONPATH=plugin.video.nuviohub/tests python -m unittest test_nuvio_601 test_nuvio_602 test_nuvio_603 test_nuvio_604 test_nuvio_605 test_nuvio_609 test_nuvio_home_iptv test_nuvio_build test_nuvio_extras test_nuvio_reliability test_nuvio_architecture
python review/check_608_rebrand_kodi22.py 6.0.9
python review/build_bundle.py --output Nuvio-Hub-Complete-6.0.9.zip
python review/check_packaged_build.py Nuvio-Hub-Complete-6.0.9.zip
```

U source arhivi su `review/unit-tests-6.0.9.txt`, `review/results-6.0.9.json` i engleske release bilješke.

## Ručna provjera na uređajima — još nije izvedena

Za **Windows + Kodi 22 RC1** i zasebno za **CoreELEC + korisnikovu postojeću verziju Kodija** provjeriti sljedeće:

| Scenarij | Očekivani rezultat | Status |
|---|---|---|
| Nadogradnja preko postojeće instalacije | Sve četiri komponente 6.0.9; sačuvani računi, kolekcije, IPTV i pozicije | NIJE IZVEDENO |
| Home → Back/Esc, uključujući fokus na Settings/HUB | Ostaje frontend Home; HUB samo klikom gumba HUB | NIJE IZVEDENO |
| Film iz Homea i zatim iz kolekcije → izlaz/Stop | Povratak u isti Nuvio kontekst bez bljeska HUB launchera | NIJE IZVEDENO |
| Sat/vrijeme Off → svi ekrani, screensaver, restart | Nema sata/vremena; postavka ostaje Off | NIJE IZVEDENO |
| Lokalni MP4 screensaver → barem dva loopa → tipka | Video se ponavlja, nema zvuka, izlaz se čisti i zvuk se vrati | NIJE IZVEDENO |
| Screensaver dok je film pauziran | Prikazuje se slika; film i pozicija ostaju netaknuti | NIJE IZVEDENO |
| Klik glumca + pretraga imena | Prikazani filmovi/serije ili jasno navedena provider konfiguracijska greška | NIJE IZVEDENO |
| Dva stream manifesta → jedan On/Off; jedan nedostupan | Poziva se samo uključeni; source prikazuje stvarni addon; ostali rezultati ostaju | NIJE IZVEDENO |
| IPTV prvi OK, drugi OK, Esc | Mali preview → native fullscreen bez EPG overlayja → isti IPTV vodič | NIJE IZVEDENO |
| IPTV Stop/EOF i ponovno otvaranje kategorije | Nema izlaza u HUB ni nenamjernog ponovnog autoplayja | NIJE IZVEDENO |
| Izlaz iz videa preko daljinskog i držanog Backa | Nema neželjenog drugog izlaza ni gubitka odabira | NIJE IZVEDENO |

## Instalacija, source i rollback

Prvo napraviti backup Kodi profila. Za nadogradnju zaustaviti video i zatvoriti Nuvio frontend, instalirati `Nuvio-Hub-Complete-6.0.9.zip` kroz **Install from zip file**, otvoriti backend **Nuvio Hub** jednom kako bi se obnovile povezane komponente, zatim ponovno pokrenuti Kodi. Ne brisati postojeće addon podatke i ne deinstalirati paket radi nadogradnje.

Source ZIP nije Kodi installer. U njemu nema generiranih nested ZIP-ova, `.git`, cacheova ili testnih profila; `review/build_bundle.py` izrađuje sve komponente. Git patch je inkrement **6.0.8 → 6.0.9**. GitHub `main` nije ažuriran niti je objavljen release.

Za povratak prije testiranja sačuvati 6.0.8 instalacijski paket i backup profila. Ponovna instalacija starijeg paketa ne poništava automatski baš svaku postavku koju korisnik tijekom testa sam promijeni; backup je pouzdanija polazna točka.

**SHA-256 finalnog installera:** `78280e8ea1f5a12e10d870b9857f8a65199e95dc916d2ce432b6f17bc00e2e49`

## Tehničke reference pregledane pri izmjenama

Kodi Python Player dokumentacija: https://xbmc.github.io/docs.kodi.tv/master/kodi-base/d9/da1/group__python___player.html

Kodi JSON-RPC Player.Open dispatch: https://github.com/xbmc/xbmc/blob/master/xbmc/interfaces/json-rpc/PlayerOperations.cpp

Kodi PVR fullscreen odluka: https://github.com/xbmc/xbmc/blob/master/xbmc/pvr/guilib/PVRGUIActionsPlayback.cpp

Kodi definicija PVR postavke: https://github.com/xbmc/xbmc/blob/master/system/settings/settings.xml

AIOMetadata People Search/credits implementacija i manifest: https://github.com/cedya77/aiometadata/blob/dev/addon/lib/getSearch.ts i https://github.com/cedya77/aiometadata/blob/dev/addon/lib/getManifest.ts

Povijesni Kodi video-screensaver primjer koji objašnjava potrebu za odvojenim skriptom: https://github.com/nickrout/screensaver.video/blob/master/default.py . Ovaj stari primjer nije dokaz kompatibilnosti s Kodi 22; kandidat ima vlastitu implementaciju i zahtijeva gore navedene runtime provjere.
