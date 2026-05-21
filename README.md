# IEC 61850 MMS IED simulator test package

Tama kansio on Windowsille tehty IEC 61850 MMS IED -simulaattorin testipaketti Moxa MGate 5119 -gatewayn testaukseen. Paketti ei tee Modbus TCP:ta eika GOOSE-lahetysta, vaan rakenne on tehty nimenomaan IEC 61850 MMS server -kayttoa varten.

## Sisalto

- `IEC61850_IED_Sim_Launcher.py`
  - ohut entrypoint, joka kaynnistaa paikallisen selainpohjaisen launcher-palvelun
- `launcher_service.py`
  - paikallinen HTTP-palvelin ja selain-UI osoitteessa `http://127.0.0.1:8787`
  - JSON-API releiden lisaykseen, poistoon, kaynnistykseen, pysaytykseen ja tagien muokkaukseen
  - kirjoittaa `runtime`-kansioon kullekin releelle `*_config.json` ja `*_values.json`
  - osaa kaynnistaa ulkoisen `ied_mms_server.exe`-prosessin, jos se on saatavilla
  - toimii myos ilman exe-tiedostoa ja nayttaa silloin tilan `missing exe`
  - tunnistaa jo kaynnissa olevan localhost-palvelun ja ohjaa siihen uuden instanssin sijaan
- `src/ied_mms_server_template.c`
  - libIEC61850-yhteensopiva C-runko MMS-serverille
  - lukee komentoriviargumentit `--ied-name`, `--type`, `--bind`, `--port`, `--values`
  - sitoo serverin haluttuun IP-osoitteeseen ja porttiin
  - lukee values-JSON-tiedoston 100 ms valein
  - sisaltaa selvasti merkityt TODO-kohdat attributtien paivitykselle
- `tools/add_ip_aliases.ps1`
  - valmis oletusversio IP-aliasien luontiin
  - selain-UI voi generoida tiedoston uudelleen kayttajan antamilla IP-osoitteilla
- `%LOCALAPPDATA%/Koffmatic/IEDsimulator/runtime/launcher_state.json`
  - tallennettu launcherin tila, jotta relelista ja tagimuutokset sailyvat seuraavaan kaynnistykseen
- `requirements.txt`
  - ei ulkoisia Python-riippuvuuksia; tiedosto on mukana yhteensopivuuden vuoksi

## Oletusreleet

Oletuslayout on nyt:

- 11 x `REF615`, nimet `REF615_SIM_01` ... `REF615_SIM_11`, IP:t `10.206.204.5` ... `10.206.204.15`
- 2 x `REU615`, nimet `REU615_SIM_01` ... `REU615_SIM_02`, IP:t `10.206.204.16` ... `10.206.204.17`
- 1 x `RED615`, nimi `RED615_SIM_01`, IP `10.206.204.18`

Jokainen IED tarvitsee oman IP-osoitteensa. Portti on tarkoituksella oletuksena `102`, koska Moxa toimii MMS-clienttina ja odottaa IEC 61850 MMS -palvelinta.

## Selain-UI:n kaynnistys

1. Python-riippuvuuksia ei tarvitse asentaa erikseen taman launcherin vuoksi.

2. Kaynnista launcher:

```powershell
py IEC61850_IED_Sim_Launcher.py
```

3. Selain-UI aukeaa oletuksena automaattisesti. Jos selain ei avaudu, mene osoitteeseen:

```text
http://127.0.0.1:8787
```

4. Voit halutessasi vaihtaa bind-hostin tai portin:

```powershell
py IEC61850_IED_Sim_Launcher.py --host 127.0.0.1 --port 8790 --no-browser
```

## Selain-UI:n ominaisuudet

Selain-UI:ssa voit:

- muuttaa kunkin releen nimea, tyyppia, IP:ta ja porttia
- lisata ja poistaa releita itse
- muokata analog-, word- ja bool-tagilistaa relekohtaisesti
- muokata tagien nykyarvoja selaimessa ja kirjoittaa ne suoraan runtime-JSONiin
- kaynnistaa yksittaisen releen tai kaikki enable-merkityt releet
- pysayttaa yksittaisen releen tai kaikki releet
- generoida satunnaiset arvot jatkuvasti napilla `Start auto random`
- kirjoittaa PowerShell IP alias -skriptin uudelleen
- palata samaan launcheriin suoraan localhost-osoitteella niin kauan kuin palvelu on kaynnissa

Jos `ied_mms_server.exe` puuttuu, launcher ei kaadu. Se kirjoittaa silti JSON-tiedostot ja skriptin, mutta rivin tila on `missing exe`.

## Runtime JSON -rakenne

Launcher kirjoittaa kaikki muokattavat tiedostot kayttajakohtaisesti kansioon:

```text
%LOCALAPPDATA%\Koffmatic\IEDsimulator\
```

Kullekin releelle syntyy kaksi tiedostoa sen `runtime`-alikansioon:

- `<IED_NAME>_config.json`
- `<IED_NAME>_values.json`

Lisaksi launcher tallentaa editorin tilan tiedostoon:

- `launcher_state.json`

IP alias -skripti kirjoitetaan polkuun:

- `%LOCALAPPDATA%/Koffmatic/IEDsimulator/tools/add_ip_aliases.ps1`

`values.json`-rakenne on:

```json
{
  "analogs": {
    "LD0.CMMXU1.A.phsA.instCVal.mag.f": 18.4
  },
  "bools": {
    "LD0.LEDGGIO1.Ind1.stVal": true
  },
  "words": {
    "LD0.SSCBR1.Beh.stVal": 1
  },
  "updated_unix_ms": 1715420000000
}
```

Launcher kaynnistaa varsinaisen serverin muodossa:

```text
ied_mms_server.exe --ied-name <name> --type <type> --bind <ip> --port <port> --values runtime/<IED_NAME>_values.json
```

## IP-aliasit Windowsissa

Jotta yhdella Windows-koneella voi simuloida useita MMS-palvelimia samalla verkkoadapterilla, kannattaa lisata adapterille useita IPv4-osoitteita.

1. Avaa PowerShell admin-oikeuksilla.
2. Aja `tools/add_ip_aliases.ps1`.
3. Tarkista tarvittaessa adapterin nimi. Skripti kayttaa oletuksena:

```powershell
$adapterName = "Ethernet"
```

Jos verkkoadapterin nimi on jotain muuta, muuta muuttuja ennen ajoa.

## libIEC61850:n rakentaminen Windowsissa

Yksinkertaisin tapa on buildata libIEC61850 CMake:lla Visual Studion tyokaluilla:

```powershell
git clone https://github.com/mz-automation/libiec61850.git
cd libiec61850
cmake -S . -B build
cmake --build build --config Release
```

Huomioita:

- Windowsilla GOOSE ei ole taman testin tavoite eika sita tarvita.
- Varsinainen ensimmaisen vaiheen MMS-testitavoite on yksi toimiva serveri portissa 102 omalla IP-osoitteella.
- `src/ied_mms_server_template.c` on tarkoitettu linkattavaksi libIEC61850:een seka generoituun malliin.

## static_model.c / static_model.h generointi ICD/CID/SCL-mallista

libIEC61850:n server-esimerkit perustuvat generoituun staattiseen malliin. Tarvitset siis oman suojareletta vastaavan SCL/ICD/CID-mallin.

Tyypillinen generointikomento on:

```powershell
java -jar genmodel.jar your_relay_model.icd
```

Joissakin libIEC61850-versioissa generaattorin nimi tai parametrit voivat poiketa hieman, mutta tavoite on sama: tuottaa `static_model.c` ja `static_model.h`.

Kun tiedostot on generoitu:

1. kopioi `static_model.c` ja `static_model.h` samaan projektiin `ied_mms_server_template.c`-tiedoston kanssa
2. linkkaa projekti libIEC61850-kirjastoon
3. tayta template-tiedoston TODO-kohdat oikeilla `DataAttribute*` handleilla, jotka tulivat juuri generoituun `static_model.h`-tiedostoon

## Ensimmainen testitavoite

Ensimmainen kaytannon tavoite on tama:

1. rakenna yksi oikea `ied_mms_server.exe` libIEC61850:lla
2. kaynnista selain-UI:sta `REF615_SIM_01`
3. varmista, etta Moxa MGate 5119 nakee `REF615_SIM_01`:n IEC 61850 MMS -serverina
4. vasta taman jalkeen laajenna muihin REF615-, REU615- ja RED615-instansseihin

Kun yksi REF615-palvelin nakyy Moxalle oikein, loppujen releiden ajaminen samalla rungolla on suoraviivaista.
