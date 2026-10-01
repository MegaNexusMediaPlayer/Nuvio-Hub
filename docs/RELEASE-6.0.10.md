# Nuvio Hub 6.0.10 — izmjene, provjere i granice

Datum: 30.09.2026. Baza: dostavljeni source 6.0.9. Status: **lokalni testni kandidat**.
Nije napravljen push, promjena GitHub main grane ni objava releasea. Pri provjeri
GitHub README još je prikazivao 6.0.7; prethodni popravci 6.0.9 ostali su baza.

## 1. Kolekcije i metadata

Home više ne preuzima interne kolekcije kao prešutnu zadanu konfiguraciju.
Obavezne su provjerene, neprazne kolekcije i uključeni metadata/stream addoni.
Korisnik može uvesti kolekcije iz Nuviova računa, uvesti JSON bez računa ili
ručno kreirati kolekciju iz instaliranih kataloga. Postojeći raspored ostaje
spremljen i provjerava se; neispravan ili otkazan uvoz ne zamjenjuje datoteku.
Nuvio račun **nije obavezan**. Isto vrijedi za Simkl; lokalni resume ostaje.

Provjera uspoređuje identitet manifesta, ID kataloga, vrstu sadržaja, obavezne
filtere/opcije i stvarni dohvat metadata za najviše dva uzorka po izvoru.
Drugi metadata addon ne smije prisvojiti katalog krivoga identiteta. Interni
predlošci moraju proći istu provjeru: naziv providera ili njegova domena nisu
samostalni dokaz kompatibilnosti. Prazan/nedostupan katalog zasad ne može proći
inicijalnu provjeru, jer nema uzorka za potvrdu. To je namjerno stroga provjera,
ali **nije iscrpno testiranje svakog filma niti jamstvo budućih odgovora**.

Dokaz validacije veže se uz relevantnu konfiguraciju. Promjena metadata addona,
uključivanja/isključivanja ili kataloga zahtijeva novu provjeru. Catalog-only
addon može koristiti drugi uključeni, kompatibilni metadata provider.

Dodana je zasebna lista **Metadata add-ons**, dodavanje URL-a manifesta i
pojedinačni On/Off. Prethodno odabrani provider ostaje uključen pri migraciji;
novi se uključuju izričito. Dohvat detalja poštuje resource types/idPrefixes,
provjerava povratni ID i pokušava sljedeći kompatibilni uključeni provider u
ograničenom vremenskom budžetu. Home pretraga, katalozi, detalji i filmografija
koriste novu podršku. Stari pomoćni integracijski kod i neke legacy rute ostaju
radi kompatibilnosti; nije provedeno prepisivanje svih modula od nule.

## 2. Glumci, Unicode i prikaz detalja

Klik na glumca otvara zaseban ekran s kružnim portretom, imenom, redom Movies
pa redom Series. Svaki red prikazuje prvih 24 naslova i ima View all za ostatak
vraćene filmografije. TMDb ključ je opcionalan fallback za portret i credits;
metadata provider i dalje može nuditi svoje People Search kataloge. Nepostojeći
podaci prikazuju jasno prazno stanje, ne izmišljenu filmografiju.

Tekst se normalizira kao Unicode NFC uz očuvanje izvornih CJK znakova, spojenih
emoji sekvenci, dijakritike i imena. Ne radi se automatsko prevođenje ili
transliteracija osobnih imena. Skin koristi Unicode font iz instaliranog Kodija;
font datoteke nisu uključene u source ni installer. **Pokrivenost svih kineskih
znakova i obojenih emojija nije potvrđena** i ovisi o konkretnom Kodi buildu.
Novi prikaz treba provjeriti i na drugim skinovima koji mogu nametnuti svoj font.

Epizode imaju vidljiv Season N / Episode N i datum Released ili Airs kada je
valjan podatak dostupan. Specials/Season 0 se ne pretvara u Season 1. Kod odabira
druge sezone osvježava se oznaka i sadržaj reda. Oba rasporeda kartica imaju više
mjesta za opis i automatsko pomicanje; duži opis dostupan je i u zasebnom prikazu.

## 3. Continue Watching: Nuvio i Simkl

Ispravljen je format Nuviova progress_key: film koristi content ID, a epizoda
`<content_id>_s<season>e<episode>`. Wire position/duration/last_watched koriste
milisekunde, lokalne pozicije sekunde; dodana je normalizacija postojećih oznaka
vremena i tipova. Nije dopušteno izmišljanje trajanja iz samog postotka.

Nuviove lokalne promjene idu u trajni SQLite red vezan uz račun i profil.
Prvo se povlači udaljeno stanje, zatim se uspoređuju stvarne vremenske oznake i
šalju lokalne promjene. Potvrđuje se samo točna verzija poslanog zapisa, tako da
novi heartbeat tijekom HTTP zahtjeva ne bude izgubljen. Neuspjelo slanje ostaje
za ponovni pokušaj. Postojeći poznati ID alias može sačuvati udaljeni identitet.

Novi ciklus ne čeka idle stanje Homea/reprodukcije. Zadani interval je 60 sekundi,
izbor 30/60/120/300. Lokalne dirty promjene imaju 5-sekundni debounce, a mrežni
problemi exponential backoff. Simkl red se pokušava slati svakih 10 sekundi uz
vlastita ograničenja; povlačenje pozicija prati interval, dok se watched-history
ne osvježava češće od 120 sekundi. Isključeni master cloud sync ostaje isključen.
Svi intervali su raspored pokušaja, **ne jamstvo isporuke točno u toj sekundi**.

Usklađeni su Simkl pause/stop pragovi i zadržavanje poznatog lokalnog trajanja.
Continue Watching se sortira prema normaliziranom vremenu; osvježavanje čuva
odabranu karticu po identitetu, umjesto nasilnog skoka na prvi naslov.

**Granice sinkronizacije:** nije izveden test s dva stvarna Nuvio/Simkl računa i
uređaja. Odlazno brisanje Nuviova resume zapisa je u redu za slanje, ali primanje
udaljenih delete događaja/delta-cursora nije implementirano. Nestanak zapisa iz
ograničenog ili neuspjelog snapshota zato se ne tumači kao brisanje. Stari server
zapisi s legacy ključevima nisu automatski masovno obrisani. To treba zasebno
provjeriti pri migraciji računa s duplikatima. Ispravnost autha, rate-limita i
konkretnog profila mora se potvrditi na stvarnoj usluzi.

## 4. Brzina, RAM i loading

RAM 200 preset sada dijeli budžet na **160 MiB preuzetih slika + 40 MiB
serijaliziranih browse metadata podataka**. Prethodni RAM 150 preset prelazi na
novi, ali korisnikov disk/OFF izbor ostaje. Browse cache dodatno ima 128 MiB
logičkog payload budžeta na disku. To **nije ukupna RAM granica procesa**:
Python objekti, SQLite stranice, Kodi/GPU teksture, ostali cacheovi i zasebni
Kodi interpreteri mogu koristiti dodatnu memoriju.

Disk cache traje između otvaranja Homea; ulazak u Settings više ga ne briše.
Isti istodobni zahtjevi za katalog spajaju se, provider/config/filter ulaze u
cache ključ, a LRU ograničava memoriju. Na klik se prvo koriste postojeći podaci,
a detalji se nadopunjuju izvan GUI callbacka uz zaštitu od zakašnjelih rezultata.

Prvi Home ulaz s nedostajućim cacheom prikazuje loading screen i priprema
početne stranice konfiguriranih kataloga, najviše četiri workera istodobno.
Foreground priprema ima granicu 40 sekundi i Back za preskakanje; ograničen
broj prvih postera može se unaprijed povući. Preostali sadržaj učitava se na
zahtjev. **Ne preuzima se beskonačna paginacija, svaki poster ni puni detalji
svakog naslova**. To je namjerno kako loading ne bi trajao neograničeno niti
zaustavio slabiji uređaj. Nema izmjerenog ubrzanja ili RSS benchmarka na uređaju;
"ultra snappy" nije potvrđeni rezultat ovih testova.

## 5. Home, traileri i prethodni popravci

Down na zadnjem Home redu više ne vraća fokus na vrh. Osvježavanje i povratak
čuvaju stabilan identitet odabranog naslova. Trailer ima novi default 90 sekundi
i izbor Full trailer, uz postojeće kraće/duže izbore. Postojeća izričito spremljena
vrijednost ostaje do promjene. Ograničenje mjeri vrijeme reprodukcije, ne čekanja.

Zadržane su provjere iz 6.0.9: HUB je izričit ulaz nakon Settings, Home Back ne
otvara HUB; povratak filma zadržava roditeljski ekran; IPTV prvi klik preview,
drugi fullscreen, Esc povratak istom vodiču; nema promjene Windows rezolucije;
zajednički clock/weather i video screensaver te stream source oznake ostaju.
Ovo opisuje kod/regresijske provjere, ne novo vizualno testiranje uređaja.

## 6. AGENTS i Kodi skillovi

U sourceu su dodani `AGENTS.md`,
`.agents/skills/kodi-quality/SKILL.md` i
`.agents/skills/kodi-performance/SKILL.md`.
Sadrže pravila pregleda koda, privatnosti, migracija, provider identiteta,
GUI-thread discipline, sinkronizacije, cachea, pakiranja, mjerenja i ručne
acceptance provjere. To su repo upute za AI agente, ne instalirani globalni plugin.
`review/check_610.py` pokreće održavanu regresijsku provjeru i parse/grammar gate.

## 7. Izvedene automatizirane provjere

- **337/337 testova PASS**: 243 postojeća (uz dokumentirano usklađivanje promijenjenih
  očekivanja) + 94 nova. Kodi/HTTP test doubles, stvarni lokalni SQLite.
- **24/24 release guard PASS**: verzije, ABI deklaracije, namespace, lokalizacija,
  migracijski aliasi i pregled uklonjenih standardnih Python modula.
- **268 Python datoteka compile PASS** na Pythonu 3.13.5; zasebno **204 runtime
  datoteke prolaze Python 3.8 grammar parse**. To nije pokretanje na Pythonu 3.8/3.14.
- **146 component XML + 4 component JSON parse PASS**; guard također parsira review
  JSON datoteke. Broj tih izvještajnih JSON-a mijenja se dodavanjem izvještaja.
- Iz konačnog raspakiranog installera: **50 importiranih modula PASS**,
  **1.456 XML asset referenci PASS**, verzije sva četiri dijela 6.0.10 i unutarnji
  SHA-256 hashovi/ZIP CRC provjereni.

Komande:

```sh
python review/check_610.py
python review/check_608_rebrand_kodi22.py 6.0.10
python review/build_bundle.py --output /tmp/Nuvio-Hub-Complete-6.0.10.zip
python review/check_packaged_build.py /tmp/Nuvio-Hub-Complete-6.0.10.zip
```

Promijenjena stara očekivanja odnose se na namjernu promjenu ugovora: nema
implicitnih internih kolekcija, pogrešan addon ID se odbija, vrijeme određuje
Continue Watching redoslijed i cache je trajan/byte-bounded. Testovi nisu izbačeni
radi zelenog rezultata; novi testovi provjeravaju nove uvjete i rollback.

## 8. Obavezno ručno prije javne objave

Na Kodi 21 i Kodi 22 RC1, CoreELEC i Windows provjeriti: svježi profil bez računa;
nadogradnju s 6.0.9; valjan/nevaljan/prazan/offline uvoz; required filtere; dva
metadata addona i OFF fallback; CJK/emojije; glumca s oba reda; Season 2 i Specials;
obje orijentacije kartica i dugi opis; zadnji red/fokus poslije synca; cold/warm
loading i Back cancel; disk cache nakon restarta; trailer 90/full; native video
povratak; IPTV preview/fullscreen/EPG/Esc; screensaver i sakriveni sat; dvije
klijentske pozicije; completion; prekid mreže/ponovni pokušaj; logout/profil
usred zahtjeva. Izmjeriti latenciju i RAM na stvarnom uređaju.

**Nijedan od tih native/device/live-account testova nije izveden u ovoj sesiji.**

## 9. Isporuka i rollback

Installer je `Nuvio-Hub-Complete-6.0.10.zip`; source i tekstualni patch su zasebni.
Prije nadogradnje spremiti backup profila, zaustaviti video, zatvoriti frontend,
instalirati ZIP, otvoriti backend Nuvio Hub jednom i restartati Kodi. Ne brisati
userdata. Za rollback koristiti stari paket i odgovarajući backup profila.

Source ZIP ne sadrži Git povijest, lokalne račune, cache baze, bytecode, font
binarije ni već ugrađene ZIP pakete; `build_bundle.py` iz njega ponovno stvara
pakete. Patch se primjenjuje na supplied 6.0.9 source i ne sadrži binarne font
razlike ni generirane instalere. Stare neaktivne font datoteke mogu ostati u
radnoj kopiji nakon primjene patcha; novi builder ih nikad ne uključuje.

## Primarni API izvori pregledani pri izmjenama

- NuvioMedia/NuvioTV: `WatchProgressSyncService.kt`, `WatchProgressRepositoryImpl.kt`,
  `WatchProgress.kt`, `SupabaseModels.kt` i collection source modeli. Potvrđen je
  format ključeva, milisekundi, RPC polja i identitet izvora kolekcije.
- SIMKL/API `apiary.apib`: playback/scrobble tok i različiti completion pragovi.
- Stremio Addon SDK: manifest resource types/idPrefixes i catalog extra ugovor.
- Kodi GUIFontManager / Fonts i Text Box dokumentacija; TMDb person details i
  combined credits API. Vanjski ugovori provjereni su u primarnim izvorima, ali
  korisnički autorizirani endpointi nisu korišteni za integracijski test.
