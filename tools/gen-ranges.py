#!/usr/bin/env python3
"""Writes ranges/<region>/<lang>.json for the regions defined here (Japan, China, Russia, Australia,
South America). The European and North American files (eu, fr, uk, de, es, us, ca) come from uBonsole's
tools/gen-frequencies.py and are not touched.

    tools/gen-ranges.py            write every region below
    tools/gen-ranges.py jp au      only these

Only analog voice is listed: the detector looks for speech in AM / FM / SSB audio, so digital voice
(DMR, dPMR, Japan's 351 MHz DCR, China's 406 MHz shared band) and data (ACARS, AIS, APRS...) are left
out, as are the ranges that must not be listened to (police, emergency services, mobile phones).
Below 24 MHz and wider than 20 MHz, ranges start unticked (the scanner applies the same rule).

Sources (checked November 2026): national regulators and amateur societies, see each region's note.
"""
import json
import os
import sys

LANGS = ("en", "fr", "de", "es")

SECTIONS = {
    "BROADCAST": ("BROADCAST", "RADIODIFFUSION", "RUNDFUNK", "RADIODIFUSIÓN"),
    "AMATEUR": ("AMATEUR RADIO", "RADIOAMATEUR", "AMATEURFUNK", "RADIOAFICIONADOS"),
    "HOBBY": ("HOBBY / MISC", "LOISIRS / DIVERS", "HOBBY / SONSTIGES", "OCIO / VARIOS"),
    # Listening to non-broadcast traffic: how the region treats it (the same wording as the other files)
    "TOLERATED": ("TOLERATED LISTENING — DISCLOSE NOTHING", "ÉCOUTE TOLÉRÉE — NE RIEN DIVULGUER",
                  "GEDULDETES MITHÖREN — NICHTS WEITERGEBEN", "ESCUCHA TOLERADA — NO DIVULGAR NADA"),
    "GREY": ("LEGAL GREY AREA — DISCLOSE NOTHING", "ZONE GRISE LÉGALE — NE RIEN DIVULGUER",
             "RECHTLICHE GRAUZONE — NICHTS WEITERGEBEN", "ZONA GRIS LEGAL — NO DIVULGAR NADA"),
    "RECEIVE": ("LEGAL TO RECEIVE — NEVER DISCLOSE", "RÉCEPTION LÉGALE — NE JAMAIS DIVULGUER",
                "EMPFANG ERLAUBT — NIE WEITERGEBEN", "RECEPCIÓN LEGAL — NUNCA DIVULGAR"),
    "RISKY": ("LEGALLY RISKY — CHECK LOCAL LAW", "LÉGALITÉ INCERTAINE — VÉRIFIER LA LOI LOCALE",
              "RECHTLICH RISKANT — LOKALES RECHT PRÜFEN", "LEGALIDAD DUDOSA — CONSULTAR LA LEY LOCAL"),
}

# Labels used by several regions: (en, fr, de, es)
FM = ("FM radio (stations)", "Radio FM (stations)", "UKW-Radio (Sender)", "Radio FM (emisoras)")
MW = ("Medium wave (MW)", "Ondes moyennes (PO)", "Mittelwelle (MW)", "Onda media (OM)")
LW = ("Long wave (LW)", "Grandes ondes (GO)", "Langwelle (LW)", "Onda larga (OL)")
AIR = ("Civil aviation (121.5 emergency)", "Aviation civile (121,5 détresse)", "Zivilluftfahrt (121,5 Notfall)",
       "Aviación civil (121,5 emergencia)")
MARINE = ("Marine VHF (ch. 16: 156.800)", "VHF marine (canal 16 : 156,800)", "Seefunk UKW (Kanal 16: 156,800)",
          "VHF marina (canal 16: 156,800)")
ISS = ("ISS (voice, SSTV)", "ISS (phonie, SSTV)", "ISS (Sprache, SSTV)", "ISS (voz, SSTV)")
CB40 = ("CB, 40 ch. (ch. 9 emergency, 19 road)", "CB, 40 canaux (9 urgence, 19 routiers)",
        "CB, 40 Kanäle (9 Notruf, 19 Fernfahrer)", "CB, 40 canales (9 emergencia, 19 carretera)")


def tr(label, lang):
    return label[LANGS.index(lang)] if isinstance(label, tuple) else label


def hf_amateur(*bands):
    """The HF bands as (label, lo, hi) in MHz; LSB below 10 MHz, USB above (the convention)."""
    return [(lbl, lo, hi, "LSB" if hi < 10 else "USB", "AMATEUR") for lbl, lo, hi in bands]


def region_2_south(sixty=False, cb=(26.965, 27.405, CB40), extra_amateur=(), extra_hobby=(), mw_hi=1.7):
    """South America (ITU Region 2): 10 kHz MW, 88 - 108 FM, 144 - 148 on 2 m, 430 - 440 on 70 cm."""
    return [
        (MW, 0.53, mw_hi, "AM", "BROADCAST"),
        (FM, 88.0, 108.0, "WFM", "BROADCAST"),
        *hf_amateur(("160 m", 1.8, 2.0), ("80 / 75 m", 3.5, 4.0),
                    *([("60 m", 5.3515, 5.3665)] if sixty else []), ("40 m", 7.0, 7.3),
                    ("20 m", 14.0, 14.35), ("15 m", 21.0, 21.45), ("10 m", 28.0, 29.7)),
        ("6 m", 50.0, 54.0, "USB", "AMATEUR"),
        (("2 m SSB (call 144.200)", "2 m BLU (appel 144,200)", "2 m SSB (Anruf 144,200)",
          "2 m BLU (llamada 144,200)"), 144.1, 144.275, "USB", "AMATEUR"),
        (("2 m FM, repeaters (call 146.52)", "2 m FM, relais (appel 146,52)", "2 m FM, Relais (Anruf 146,52)",
          "2 m FM, repetidores (llamada 146,52)"), 145.1, 148.0, "FM", "AMATEUR"),
        (ISS, 145.7875, 145.8125, "NFM", "AMATEUR"),
        *extra_amateur,
        (("70 cm (repeaters, satellites)", "70 cm (relais, satellites)", "70 cm (Relais, Satelliten)",
          "70 cm (repetidores, satélites)"), 430.0, 440.0, "NFM", "AMATEUR"),
        ("23 cm", 1240.0, 1300.0, "NFM", "AMATEUR"),
        (cb[2], cb[0], cb[1], "AM", "HOBBY"),
        *extra_hobby,
        (AIR, 118.0, 137.0, "AM", "TOLERATED"),
        (MARINE, 156.0, 162.0, "NFM", "TOLERATED"),
    ]


R125 = (("1.25 m", "1,25 m", "1,25 m", "1,25 m"), 220.0, 225.0, "NFM", "AMATEUR")

REGIONS = {
    # Japan: MIC (Radio Act art. 59: receiving is legal, disclosing or using the content is not), JARL band
    # plan 2025. FM 76 - 95 (90 - 95: AM simulcast), MW on a 9 kHz raster.
    "jp": [
        (MW, 0.5265, 1.6065, "AM", "BROADCAST"),
        (FM, 76.0, 95.0, "WFM", "BROADCAST"),
        *hf_amateur(("160 m", 1.8, 1.875), (("80 m (segmented)", "80 m (segmentée)", "80 m (segmentiert)", "80 m (segmentada)"), 3.5, 3.805), ("40 m", 7.0, 7.2),
                    ("20 m", 14.0, 14.35), ("15 m", 21.0, 21.45), ("10 m", 28.0, 29.7)),
        ("6 m", 50.0, 54.0, "USB", "AMATEUR"),
        (("2 m SSB", "2 m BLU", "2 m SSB", "2 m BLU"), 144.1, 144.5, "USB", "AMATEUR"),
        (("2 m FM (call 145.00)", "2 m FM (appel 145,00)", "2 m FM (Anruf 145,00)", "2 m FM (llamada 145,00)"),
         144.5, 146.0, "FM", "AMATEUR"),
        (ISS, 145.7875, 145.8125, "NFM", "AMATEUR"),
        (("70 cm (call 433.00)", "70 cm (appel 433,00)", "70 cm (Anruf 433,00)", "70 cm (llamada 433,00)"),
         430.0, 440.0, "NFM", "AMATEUR"),
        ("23 cm", 1260.0, 1300.0, "NFM", "AMATEUR"),
        (("CB, 8 ch. (26.968 - 27.144)", "CB, 8 canaux (26,968 - 27,144)", "CB, 8 Kanäle (26,968 - 27,144)",
          "CB, 8 canales (26,968 - 27,144)"), 26.968, 27.144, "AM", "HOBBY"),
        (("Low-power radio, simplex (tokutei)", "Radio faible puissance, simplex (tokutei)",
          "Kleinleistungsfunk, Simplex (tokutei)", "Radio de baja potencia, símplex (tokutei)"),
         422.05, 422.3, "NFM", "HOBBY"),
        (("Low-power radio, repeater inputs", "Radio faible puissance, entrées relais",
          "Kleinleistungsfunk, Relaiseingaben", "Radio de baja potencia, entradas de repetidor"),
         421.575, 421.9125, "NFM", "HOBBY"),
        (("Low-power radio, repeater outputs", "Radio faible puissance, sorties relais",
          "Kleinleistungsfunk, Relaisausgaben", "Radio de baja potencia, salidas de repetidor"),
         440.025, 440.3625, "NFM", "HOBBY"),
        (AIR, 118.0, 137.0, "AM", "RECEIVE"),
        (MARINE, 156.0, 162.0, "NFM", "RECEIVE"),
    ],
    # China (mainland): MIIT / SRRC; public walkie-talkies per 国无办〔2025〕1号 (409.75 - 409.9875 analog FM).
    # The 2016 Radio Regulations forbid receiving outside one's licence: aviation and marine start unticked.
    "cn": [
        (MW, 0.531, 1.602, "AM", "BROADCAST"),
        (FM, 87.5, 108.0, "WFM", "BROADCAST"),
        *hf_amateur(("160 m", 1.8, 2.0), ("80 m", 3.5, 3.9), ("40 m", 7.0, 7.2), ("20 m", 14.0, 14.35),
                    ("15 m", 21.0, 21.45), ("10 m", 28.0, 29.7)),
        ("6 m", 50.0, 54.0, "USB", "AMATEUR"),
        (("2 m SSB", "2 m BLU", "2 m SSB", "2 m BLU"), 144.05, 144.4, "USB", "AMATEUR"),
        (("2 m FM, repeaters", "2 m FM, relais", "2 m FM, Relais", "2 m FM, repetidores"), 144.5, 148.0, "FM",
         "AMATEUR"),
        (ISS, 145.7875, 145.8125, "NFM", "AMATEUR"),
        (("70 cm (repeaters, satellites)", "70 cm (relais, satellites)", "70 cm (Relais, Satelliten)",
          "70 cm (repetidores, satélites)"), 430.0, 440.0, "NFM", "AMATEUR"),
        ("23 cm", 1240.0, 1300.0, "NFM", "AMATEUR"),
        (("Public walkie-talkies (20 ch.)", "Talkies-walkies publics (20 canaux)", "Öffentliche Funkgeräte (20 Kanäle)",
          "Walkie-talkies públicos (20 canales)"), 409.75, 409.9875, "NFM", "HOBBY"),
        (AIR, 118.0, 137.0, "AM", "RISKY", False),
        (MARINE, 156.0, 162.0, "NFM", "RISKY", False),
    ],
    # Russia: SCRF (GKRCh) decisions 06-14-03-001 (CB), 04-03-04-001 (LPD), 05-10-02-001 (PMR446); IARU
    # Region 1 band plan. Receiving needs no permit; disclosing intercepted content is an offence (126-FZ
    # art. 63, Criminal Code art. 138). The OIRT band (65.9 - 74, 30 kHz raster) is left out: the station
    # finder works on the 100 kHz raster.
    "ru": [
        (LW, 0.1485, 0.2835, "AM", "BROADCAST"),
        (MW, 0.5265, 1.6065, "AM", "BROADCAST"),
        (FM, 87.5, 108.0, "WFM", "BROADCAST"),
        *hf_amateur(("160 m", 1.81, 2.0), ("80 m", 3.5, 3.8), ("40 m", 7.0, 7.2), ("20 m", 14.0, 14.35),
                    ("15 m", 21.0, 21.45), ("10 m", 28.0, 29.7)),
        (("2 m SSB (call 144.300)", "2 m BLU (appel 144,300)", "2 m SSB (Anruf 144,300)",
          "2 m BLU (llamada 144,300)"), 144.05, 144.4, "USB", "AMATEUR"),
        (("2 m, repeaters (145.6+)", "2 m, relais (145,6+)", "2 m, Relais (145,6+)", "2 m, repetidores (145,6+)"),
         145.2, 145.8, "FM", "AMATEUR"),
        (ISS, 145.7875, 145.8125, "NFM", "AMATEUR"),
        (("70 cm (repeaters, satellites)", "70 cm (relais, satellites)", "70 cm (Relais, Satelliten)",
          "70 cm (repetidores, satélites)"), 430.0, 440.0, "NFM", "AMATEUR"),
        ("23 cm", 1260.0, 1300.0, "NFM", "AMATEUR"),
        (("CB, grid C, 40 ch. (ch. 15: 27.135)", "CB, grille C, 40 canaux (15 : 27,135)",
          "CB, Raster C, 40 Kanäle (15: 27,135)", "CB, rejilla C, 40 canales (15: 27,135)"),
         26.96, 27.41, "FM", "HOBBY"),
        (("LPD433 (69 ch.)", "LPD433 (69 canaux)", "LPD433 (69 Kanäle)", "LPD433 (69 canales)"),
         433.075, 434.775, "NFM", "HOBBY"),
        (("PMR446 (walkie-talkies, 8 ch.)", "PMR446 (talkies-walkies, 8 canaux)", "PMR446 (Funkgeräte, 8 Kanäle)",
          "PMR446 (walkie-talkies, 8 canales)"), 446.0, 446.1, "NFM", "HOBBY"),
        (AIR, 118.0, 137.0, "AM", "GREY"),
        (MARINE, 156.0, 162.0, "NFM", "GREY"),
    ],
    # Australia: ACMA, Amateur and CB class licences (F2025L01087, F2025L01088), WIA band plan. No 60 m
    # (refused for defence). Receiving is generally lawful; intercepting telecommunications-network traffic
    # and disclosing or using radio content are offences.
    "au": [
        (MW, 0.5265, 1.7015, "AM", "BROADCAST"),
        (FM, 87.5, 108.0, "WFM", "BROADCAST"),
        *hf_amateur(("160 m", 1.8, 1.875), ("80 m", 3.5, 3.8), ("40 m", 7.0, 7.3), ("20 m", 14.0, 14.35),
                    ("15 m", 21.0, 21.45), ("10 m", 28.0, 29.7)),
        ("6 m", 50.0, 54.0, "USB", "AMATEUR"),
        (("2 m SSB (call 144.100)", "2 m BLU (appel 144,100)", "2 m SSB (Anruf 144,100)",
          "2 m BLU (llamada 144,100)"), 144.05, 144.4, "USB", "AMATEUR"),
        (("2 m FM, repeaters (call 146.500)", "2 m FM, relais (appel 146,500)", "2 m FM, Relais (Anruf 146,500)",
          "2 m FM, repetidores (llamada 146,500)"), 146.0, 148.0, "FM", "AMATEUR"),
        (ISS, 145.7875, 145.8125, "NFM", "AMATEUR"),
        (("70 cm (call 439.000)", "70 cm (appel 439,000)", "70 cm (Anruf 439,000)", "70 cm (llamada 439,000)"),
         430.0, 440.0, "NFM", "AMATEUR"),
        ("23 cm", 1240.0, 1300.0, "NFM", "AMATEUR"),
        (("CB 27 MHz, 40 ch. (9 emergency, 11 call)", "CB 27 MHz, 40 canaux (9 urgence, 11 appel)",
          "CB 27 MHz, 40 Kanäle (9 Notruf, 11 Anruf)", "CB 27 MHz, 40 canales (9 emergencia, 11 llamada)"),
         26.965, 27.405, "AM", "HOBBY"),
        (("UHF CB, 80 ch. (5 / 35 emergency)", "CB UHF, 80 canaux (5 / 35 urgence)", "UHF-CB, 80 Kanäle (5 / 35 Notruf)",
          "CB UHF, 80 canales (5 / 35 emergencia)"), 476.425, 477.4125, "NFM", "HOBBY"),
        (("Marine 27 MHz (27.88 call)", "Marine 27 MHz (appel 27,88)", "Seefunk 27 MHz (Anruf 27,88)",
          "Marina 27 MHz (llamada 27,88)"), 27.68, 27.94, "AM", "HOBBY"),
        (AIR, 118.0, 137.0, "AM", "RECEIVE"),
        (MARINE, 156.0, 162.0, "NFM", "RECEIVE"),
    ],
    # Brazil: Anatel Res. 697/2018 (amateur), Rádio do Cidadão (80 channels up to 27.855), extended FM
    # (eFM, 76.1 - 87.9: the AM stations moved to FM). Secrecy: Constitution art. 5 XII, LGT art. 3 V.
    "br": [
        (("Extended FM (eFM, former AM stations)", "FM étendue (eFM, anciennes stations AM)",
          "Erweitertes UKW (eFM, frühere AM-Sender)", "FM extendida (eFM, antiguas emisoras AM)"),
         76.1, 87.9, "WFM", "BROADCAST"),
        *region_2_south(sixty=True, cb=(26.965, 27.855, (
            "Citizen band (PX), 80 ch.", "Bande citoyenne (PX), 80 canaux", "Jedermannfunk (PX), 80 Kanäle",
            "Banda ciudadana (PX), 80 canales")), extra_amateur=[R125]),
    ],
    # Argentina: ENACOM (2017 resolution: 60 m, 160 / 80 m extended). Ley 19.798: telecom inviolable.
    "ar": region_2_south(sixty=True, mw_hi=1.71),
    # Chile: SUBTEL Res. Ex. 1985/2017 (reduced-range devices: CB, LPD 433, FRS-like 462 / 467). Ley 18.168
    # art. 36 B.
    "cl": region_2_south(cb=(26.96, 27.41, CB40), extra_amateur=[R125], extra_hobby=[
        (("FRS (walkie-talkies, 462 MHz)", "FRS (talkies-walkies, 462 MHz)", "FRS (Funkgeräte, 462 MHz)",
          "FRS (walkie-talkies, 462 MHz)"), 462.54, 462.74, "NFM", "HOBBY"),
        (("FRS (walkie-talkies, 467 MHz)", "FRS (talkies-walkies, 467 MHz)", "FRS (Funkgeräte, 467 MHz)",
          "FRS (walkie-talkies, 467 MHz)"), 467.55, 467.725, "NFM", "HOBBY"),
        (("LPD433 (walkie-talkies)", "LPD433 (talkies-walkies)", "LPD433 (Funkgeräte)", "LPD433 (walkie-talkies)"),
         433.05, 434.79, "NFM", "HOBBY"),
    ]),
    # Colombia: MinTIC Res. 964/2019 (CB 26.96 - 27.41, amateur service), ANE national table.
    "co": region_2_south(cb=(26.96, 27.41, CB40), mw_hi=1.705),
    # Rest of South America (Uruguay, Paraguay, Peru, Bolivia, Ecuador, Venezuela): the Region 2 pattern.
    "sa": region_2_south(),
}


def entries(region, lang):
    out = []
    for item in REGIONS[region]:
        label, lo, hi, mode, section = item[:5]
        enabled = item[5] if len(item) > 5 else (lo >= 24 and hi - lo <= 20 and section != "BROADCAST"
                                                  or mode == "WFM")
        out.append({"label": tr(label, lang), "lo_mhz": lo, "hi_mhz": hi, "mode": mode,
                    "section": tr(SECTIONS[section], lang), "enabled": bool(enabled)})
    order = list(SECTIONS)        # broadcast, amateur, hobby, then the listening section (as in the other files)
    return sorted(out, key=lambda d: next(i for i, k in enumerate(order) if d["section"] == tr(SECTIONS[k], lang)))


def main(regions):
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "ranges")
    for region in regions:
        os.makedirs(os.path.join(root, region), exist_ok=True)
        for lang in LANGS:
            path = os.path.join(root, region, lang + ".json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(entries(region, lang), f, ensure_ascii=False, indent=1)
                f.write("\n")
            print(path)


if __name__ == "__main__":
    unknown = [r for r in sys.argv[1:] if r not in REGIONS]
    if unknown:
        sys.exit("unknown region: %s (known: %s)" % (", ".join(unknown), " ".join(REGIONS)))
    main(sys.argv[1:] or list(REGIONS))
