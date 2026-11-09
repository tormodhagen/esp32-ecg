# Kontrollert i utviklingsmiljøet

- Python-syntaks: OK.
- GUI startet med Qt offscreen og visuelt kontrollert med Williams RA–LL-data.
- Rå- og filtrert visning: OK. BPM skjules ved stopp/stale data.
- Serialtråd testet via pseudoterminal med delte pakker: OK.
- Sekvenshull og CSV-skriving: OK.
- Syntetisk 75 BPM, begge polariteter og bred T-lignende bølge: detektert 75 BPM.
- Flatlinje/databrudd: ingen BPM. Telleroverløp og reset: OK.
- På 5–17 s av de tre opplastede 1600 SPS-filene: ca. 74,7 BPM (Tormod armer),
  88,7 BPM (William armer), 85,7 BPM (William RA–LL). Medianbaserte estimater
  avhenger av vinduet. Dette er en funksjonstest, ikke klinisk validering.
- PlatformIO-konfigurasjonen er lest av PIO og plattform 55.3.36 er hentet.
- **Full firmwarekompilering ikke fullført:** nedlasting av Arduino 3.3.6
  stoppet med CERTIFICATE_VERIFY_FAILED i dette miljøet, også ved forsøk med
  systemets sertifikatlager. Ingen binærfil leveres og ingen fysisk C6/ADS1115
  har vært tilgjengelig for test. TLS-verifisering ble ikke deaktivert.

Kjør `python -m unittest test_signal.py` for de medfølgende signaltestene,
og `pio run -e c6_usb` for firmwarebygg på din maskin.

## Flatlinjelyd – oppdatering

Testet: oppvarmingstid, flatt signal, signal tilbake, datagap, foreldede data,
demping, testknapp, stopptilstand og generert WAV-format. GUI startet med
Qt offscreen. Faktisk avspilling er ikke bekreftet: miljøet har ingen brukbar
lydutgang. Bruk «Test lyd (1 s)» på PC-en.

## Opptak med to klikk – oppdatering

Testet med Qt offscreen: første klikk starter uten dialog; andre klikk
stopper datainnsamlingen før dialogen; avbrutt dialog beholder opptaket;
senere samples legges ikke til et avsluttet opptak; nytt lagringsforsøk
skriver de opprinnelige radene med relativ tid fra null.

## BLE – oppdatering

- Seks Python-tester består: eksisterende signaltester, binær BLE-dekoding med
  fortegn, tidsomslag og sekvensgap, ugyldig pakkelengde og simulert BLE-klient
  med notifications og frakobling.
- Qt offscreen: vinduet starter og bytter mellom USB og BLE.
- NimBLE API-signaturer kontrollert mot offisiell prosjektdokumentasjon.
- Nytt PlatformIO-bygg forsøkt: Arduino-nedlasting stopper fortsatt med
  CERTIFICATE_VERIFY_FAILED før kompilering. BLE-firmware er derfor ikke
  bekreftet kompilert. Ingen fysisk ESP32/Bluetooth-adapter tilgjengelig;
  radiostrøm, Windows-tilkobling og faktisk latens må testes på brukerens PC.

Kjør alle Python-tester med `python -m unittest discover` fra prosjektmappen.

## Kaldstart / UART-rettelse

Åtte Python-tester består. Nye tester kontrollerer at DTR/RTS er inaktive
før portåpning og at BLE uten samples viser ADC-status. Firmware er gjennomgått,
men denne rettelsen er ikke kompilert eller testet på fysisk kort her.
Kaldstart, reset-knapp, native USB og USB-UART må verifiseres på målekortet.
