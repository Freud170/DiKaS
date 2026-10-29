"""Szenarien aus dem Vereinsalltag – jeweils komplette Abläufe mit Endkontrolle."""

from datetime import date

import pytest

from dikas import buchhaltung as bh
from dikas.db.models import Buchungsart as Art, MitgliedStatus as St

from conftest import ct


# --- Mitgliedsbeiträge ----------------------------------------------------

class TestBeitraege:
    def test_beitrag_wird_vollstaendig_bezahlt(self, verein):
        kasse = verein.kasse("Beitragskasse")
        tom = verein.mitglied("Tom")
        verein.beitrag(tom, kasse, "60")
        assert verein.saldo(tom) == ct("-60")  # Tom schuldet 60 €

        verein.einzahlung(tom, "60", "Überweisung Beitrag")

        assert verein.saldo(tom) == 0
        assert verein.saldo(kasse) == ct("60")
        assert verein.saldo(verein.kw) == ct("60")
        verein.pruefe_abstimmung()

    def test_ratenzahlung(self, verein):
        kasse = verein.kasse("Beitragskasse")
        tom = verein.mitglied("Tom")
        verein.beitrag(tom, kasse, "100")
        for rate in ("25", "25", "30"):
            verein.einzahlung(tom, rate, "Rate")
        assert verein.saldo(tom) == ct("-20")  # Rest offen
        verein.einzahlung(tom, "20", "letzte Rate")
        assert verein.saldo(tom) == 0
        verein.pruefe_abstimmung()

    def test_ueberzahlung_wird_guthaben_und_erstattet(self, verein):
        kasse = verein.kasse("Beitragskasse")
        tom = verein.mitglied("Tom")
        verein.beitrag(tom, kasse, "60")
        verein.einzahlung(tom, "100", "zu viel überwiesen")
        assert verein.saldo(tom) == ct("40")  # Guthaben

        verein.auszahlung(tom, "40", "Erstattung Überzahlung")

        assert verein.saldo(tom) == 0
        assert verein.saldo(verein.kw) == ct("60")
        verein.pruefe_abstimmung()

    def test_guthaben_wird_mit_naechstem_beitrag_verrechnet(self, verein):
        kasse = verein.kasse("Beitragskasse")
        tom = verein.mitglied("Tom")
        verein.einzahlung(tom, "100", "Vorauszahlung")
        verein.beitrag(tom, kasse, "60", datum=date(2026, 1, 1))
        verein.beitrag(tom, kasse, "60", datum=date(2027, 1, 1))
        assert verein.saldo(tom) == ct("-20")
        verein.pruefe_abstimmung()

    def test_vorauszahlung_vor_dem_beitrag(self, verein):
        kasse = verein.kasse("Beitragskasse")
        tom = verein.mitglied("Tom")
        verein.einzahlung(tom, "60")
        assert verein.saldo(tom) == ct("60")
        verein.beitrag(tom, kasse, "60")
        assert verein.saldo(tom) == 0
        verein.pruefe_abstimmung()

    def test_beitragslauf_unterschiedliche_betraege_je_status(self, verein, session):
        kasse = verein.kasse("Beitragskasse")
        fuxe = [verein.mitglied(f"Fux {i}", St.FUX) for i in range(3)]
        aktive = [verein.mitglied(f"Aktiver {i}", St.AKTIVER) for i in range(5)]
        alumni = [verein.mitglied(f"Alumnus {i}", St.ALUMNI) for i in range(4)]

        buchungen = verein.beitragslauf(kasse, fux="30", aktiver="60", alumni="120")

        assert len(buchungen) == 12
        assert all(verein.saldo(m) == ct("-30") for m in fuxe)
        assert all(verein.saldo(m) == ct("-60") for m in aktive)
        assert all(verein.saldo(m) == ct("-120") for m in alumni)
        assert verein.saldo(kasse) == ct(3 * 30 + 5 * 60 + 4 * 120)
        assert verein.saldo(verein.kw) == 0
        verein.pruefe_abstimmung()

    def test_beitragslauf_alumni_beitragsfrei(self, verein):
        kasse = verein.kasse("Beitragskasse")
        fux = verein.mitglied("Fritz", St.FUX)
        alumnus = verein.mitglied("Alfred", St.ALUMNI)

        buchungen = verein.beitragslauf(kasse, fux="30", aktiver="60", alumni="0")

        assert len(buchungen) == 1
        assert verein.saldo(fux) == ct("-30")
        assert verein.saldo(alumnus) == 0

    def test_beitragslauf_ueberspringt_ausgetretene(self, verein):
        kasse = verein.kasse("Beitragskasse")
        tom = verein.mitglied("Tom")
        weg = verein.mitglied("Ausgetreten")
        weg.aktiv = False

        verein.beitragslauf(kasse, aktiver="60")

        assert verein.saldo(tom) == ct("-60")
        assert verein.saldo(weg) == 0

    def test_beitragslauf_bucht_nicht_auf_kassen(self, verein):
        kasse = verein.kasse("Beitragskasse")
        andere = verein.kasse("Getränkekasse")
        verein.mitglied("Tom")
        verein.beitragslauf(kasse, aktiver="60")
        assert verein.saldo(andere) == 0

    def test_beitragslauf_setzt_datum_und_text(self, verein):
        kasse = verein.kasse("Beitragskasse")
        verein.mitglied("Tom")
        (b,) = verein.beitragslauf(kasse, aktiver="60", text="Jahresbeitrag 2026", datum=date(2026, 3, 1))
        assert (b.datum, b.text, b.art) == (date(2026, 3, 1), "Jahresbeitrag 2026", Art.BEITRAG)

    def test_statuswechsel_zwischen_zwei_beitragslaeufen(self, verein, session):
        kasse = verein.kasse("Beitragskasse")
        fritz = verein.mitglied("Fritz", St.FUX)
        verein.beitragslauf(kasse, fux="30", aktiver="60", alumni="20", datum=date(2026, 1, 1))

        bh.konto_bearbeiten(session, fritz.id, "Fritz", St.AKTIVER, "", True)  # Burschung
        verein.beitragslauf(kasse, fux="30", aktiver="60", alumni="20", datum=date(2027, 1, 1))

        bh.konto_bearbeiten(session, fritz.id, "Fritz", St.ALUMNI, "", True)  # Philistrierung
        verein.beitragslauf(kasse, fux="30", aktiver="60", alumni="20", datum=date(2028, 1, 1))

        assert verein.saldo(fritz) == ct("-110")
        verein.pruefe_abstimmung()

    def test_versehentlich_doppelter_beitragslauf_wird_storniert(self, verein):
        kasse = verein.kasse("Beitragskasse")
        mitglieder = [verein.mitglied(n) for n in ("A", "B", "C")]
        verein.beitragslauf(kasse, aktiver="60")
        doppelt = verein.beitragslauf(kasse, aktiver="60")

        for b in doppelt:
            verein.storno(b)

        assert all(verein.saldo(m) == ct("-60") for m in mitglieder)
        assert verein.saldo(kasse) == ct("180")
        verein.pruefe_abstimmung()

    def test_beitragslauf_ohne_mitglieder(self, verein):
        kasse = verein.kasse("Beitragskasse")
        with pytest.raises(bh.BuchhaltungsFehler):
            verein.beitragslauf(kasse, aktiver="60")

    def test_beitragslauf_alle_betraege_null(self, verein):
        kasse = verein.kasse("Beitragskasse")
        verein.mitglied("Tom")
        with pytest.raises(bh.BuchhaltungsFehler):
            verein.beitragslauf(kasse)

    def test_beitragslauf_negativer_betrag(self, verein, session):
        kasse = verein.kasse("Beitragskasse")
        verein.mitglied("Tom")
        with pytest.raises(bh.BuchhaltungsFehler):
            bh.beitraege_abbuchen(session, {St.AKTIVER: -100}, kasse.id, "Beitrag")

    def test_beitragslauf_auf_deaktivierte_kasse(self, verein):
        kasse = verein.kasse("Alte Kasse")
        kasse.aktiv = False
        verein.mitglied("Tom")
        with pytest.raises(bh.BuchhaltungsFehler):
            verein.beitragslauf(kasse, aktiver="60")

    def test_beitragslauf_auf_privatkonto_verboten(self, verein):
        tom = verein.mitglied("Tom")
        verein.mitglied("Fritz")
        with pytest.raises(bh.BuchhaltungsFehler):
            verein.beitragslauf(tom, aktiver="60")

    def test_einzelner_nachtraeglicher_beitrag_fuer_neuen_fux(self, verein):
        kasse = verein.kasse("Beitragskasse")
        verein.mitglied("Tom")
        verein.beitragslauf(kasse, fux="30", aktiver="60")
        neu = verein.mitglied("Neuer Fux", St.FUX)  # tritt erst später ein
        verein.beitrag(neu, kasse, "15", "Halber Beitrag Sommersemester")
        assert verein.saldo(neu) == ct("-15")
        assert verein.saldo(kasse) == ct("75")


# --- Getränke / Strichliste ----------------------------------------------

class TestGetraenke:
    def test_strichliste_und_einkauf(self, verein):
        getraenke = verein.kasse("Getränkekasse")
        tom, fritz = verein.mitglied("Tom"), verein.mitglied("Fritz", St.FUX)

        verein.ausgabe(getraenke, "120", "Einkauf Getränkemarkt")
        verein.umbuchung(tom, getraenke, "14,50", "Strichliste Oktober")
        verein.umbuchung(fritz, getraenke, "22", "Strichliste Oktober")
        verein.einzahlung(tom, "14,50")
        verein.einzahlung(fritz, "22")

        assert verein.saldo(tom) == verein.saldo(fritz) == 0
        assert verein.saldo(getraenke) == ct("-83,50")  # Einkauf noch nicht gedeckt
        assert verein.saldo(verein.kw) == ct("-83,50")
        verein.pruefe_abstimmung()

    def test_barverkauf_an_der_theke(self, verein):
        getraenke = verein.kasse("Getränkekasse")
        verein.einnahme(getraenke, "37,80", "Barverkauf Kneipenabend")
        assert verein.saldo(getraenke) == verein.saldo(verein.kw) == ct("37,80")

    def test_pfandrueckgabe(self, verein):
        getraenke = verein.kasse("Getränkekasse")
        verein.ausgabe(getraenke, "100", "Einkauf inkl. Pfand")
        verein.einnahme(getraenke, "12,30", "Pfandrückgabe")
        assert verein.saldo(getraenke) == ct("-87,70")
        verein.pruefe_abstimmung()

    def test_mitglied_mit_schulden_bei_der_getraenkekasse(self, verein):
        getraenke = verein.kasse("Getränkekasse")
        tom = verein.mitglied("Tom")
        for _ in range(10):
            verein.umbuchung(tom, getraenke, "1,50", "Bier")
        assert verein.saldo(tom) == ct("-15")
        assert verein.saldo(getraenke) == ct("15")
        assert verein.saldo(verein.kw) == 0  # kein Geld geflossen


# --- Auslagen / Erstattungen ---------------------------------------------

class TestAuslagen:
    def test_mitglied_streckt_geld_vor_und_bekommt_es_erstattet(self, verein):
        fest = verein.kasse("Festkasse")
        tom = verein.mitglied("Tom")

        # Tom kauft Deko für 45 € aus eigener Tasche: Kasse trägt die Kosten, Tom bekommt Guthaben
        verein.umbuchung(fest, tom, "45", "Auslage Deko")
        assert verein.saldo(tom) == ct("45")
        assert verein.saldo(fest) == ct("-45")
        assert verein.saldo(verein.kw) == 0

        verein.auszahlung(tom, "45", "Erstattung Auslage")
        assert verein.saldo(tom) == 0
        assert verein.saldo(verein.kw) == ct("-45")
        verein.pruefe_abstimmung()

    def test_auslage_wird_mit_schulden_verrechnet(self, verein):
        beitrag = verein.kasse("Beitragskasse")
        fest = verein.kasse("Festkasse")
        tom = verein.mitglied("Tom")
        verein.beitrag(tom, beitrag, "60")
        verein.umbuchung(fest, tom, "45", "Auslage Deko")
        assert verein.saldo(tom) == ct("-15")  # Rest-Schuld
        verein.pruefe_abstimmung()

    def test_vorschuss_an_mitglied_fuer_einkauf(self, verein):
        fest = verein.kasse("Festkasse")
        tom = verein.mitglied("Tom")
        verein.auszahlung(tom, "200", "Vorschuss Einkauf Sommerfest")
        # Tom kauft für 180 € ein und gibt 20 € zurück
        verein.umbuchung(fest, tom, "180", "Abrechnung Einkauf")
        verein.einzahlung(tom, "20", "Rückgabe Restgeld")
        assert verein.saldo(tom) == 0
        assert verein.saldo(fest) == ct("-180")
        assert verein.saldo(verein.kw) == ct("-180")
        verein.pruefe_abstimmung()


# --- Veranstaltungen, Spenden, Kassen ------------------------------------

class TestKassen:
    def test_sommerfest_komplett(self, verein):
        fest = verein.kasse("Festkasse")
        verein.ausgabe(fest, "350", "Getränke")
        verein.ausgabe(fest, "120,50", "Grillgut")
        verein.ausgabe(fest, "80", "Zeltmiete")
        verein.einnahme(fest, "410", "Eintritt")
        verein.einnahme(fest, "275,30", "Verkauf")
        assert verein.saldo(fest) == ct("134,80")  # Gewinn
        verein.pruefe_abstimmung()

    def test_veranstaltung_mit_verlust(self, verein):
        fest = verein.kasse("Festkasse")
        verein.ausgabe(fest, "500")
        verein.einnahme(fest, "320")
        assert verein.saldo(fest) == ct("-180")
        verein.pruefe_abstimmung()

    def test_spende(self, verein):
        allgemein = verein.kasse("Allgemeine Kasse")
        verein.einnahme(allgemein, "500", "Spende Altherrenverband")
        assert verein.saldo(allgemein) == verein.saldo(verein.kw) == ct("500")

    def test_spende_eines_mitglieds_ueber_sein_privatkonto(self, verein):
        allgemein = verein.kasse("Allgemeine Kasse")
        tom = verein.mitglied("Tom", St.ALUMNI)
        verein.einzahlung(tom, "250", "Überweisung inkl. Spende")
        verein.umbuchung(tom, allgemein, "250", "Spende")
        assert verein.saldo(tom) == 0
        assert verein.saldo(allgemein) == ct("250")
        verein.pruefe_abstimmung()

    def test_umbuchung_zwischen_kassen(self, verein):
        beitrag = verein.kasse("Beitragskasse")
        fest = verein.kasse("Festkasse")
        verein.einnahme(beitrag, "1000")
        verein.umbuchung(beitrag, fest, "300", "Zuschuss Sommerfest")
        assert verein.saldo(beitrag) == ct("700")
        assert verein.saldo(fest) == ct("300")
        assert verein.saldo(verein.kw) == ct("1000")
        verein.pruefe_abstimmung()

    def test_laufende_kosten_aus_allgemeiner_kasse(self, verein):
        allgemein = verein.kasse("Allgemeine Kasse")
        verein.einnahme(allgemein, "2000", "Startbestand")
        for monat in range(1, 13):
            verein.ausgabe(allgemein, "9,99", f"Kontoführung {monat}/2026", date(2026, monat, 1))
        assert verein.saldo(allgemein) == ct("2000") - 12 * ct("9,99")
        verein.pruefe_abstimmung()

    def test_kasse_kann_ins_minus(self, verein):
        kasse = verein.kasse("Kasse")
        verein.ausgabe(kasse, "50")
        assert verein.saldo(kasse) == ct("-50")

    def test_kassen_bleiben_getrennt(self, verein):
        a, b, c = verein.kasse("A"), verein.kasse("B"), verein.kasse("C")
        verein.einnahme(a, "100")
        verein.ausgabe(b, "30")
        assert (verein.saldo(a), verein.saldo(b), verein.saldo(c)) == (ct(100), ct(-30), 0)
        assert verein.saldo(verein.kw) == ct(70)


# --- Mitglieder untereinander --------------------------------------------

class TestZwischenMitgliedern:
    def test_mitglied_zahlt_fuer_anderes_mitglied(self, verein):
        beitrag = verein.kasse("Beitragskasse")
        vater, sohn = verein.mitglied("Vater", St.ALUMNI), verein.mitglied("Sohn", St.FUX)
        verein.beitrag(sohn, beitrag, "30")
        verein.einzahlung(vater, "30", "Zahlung für Sohn")
        verein.umbuchung(vater, sohn, "30", "Übernahme Beitrag Sohn")
        assert verein.saldo(vater) == verein.saldo(sohn) == 0
        verein.pruefe_abstimmung()

    def test_schulden_zwischen_mitgliedern_verschieben(self, verein):
        tom, fritz = verein.mitglied("Tom"), verein.mitglied("Fritz")
        verein.umbuchung(tom, fritz, "20", "Tom schuldet Fritz 20 €")
        assert verein.saldo(tom) == ct(-20)
        assert verein.saldo(fritz) == ct(20)
        assert verein.saldo(verein.kw) == 0


# --- Korrekturen ----------------------------------------------------------

class TestKorrekturen:
    def test_falscher_betrag_storno_und_neu(self, verein):
        tom = verein.mitglied("Tom")
        falsch = verein.einzahlung(tom, "100", "Überweisung")
        verein.storno(falsch)
        verein.einzahlung(tom, "10", "Überweisung (korrigiert)")
        assert verein.saldo(tom) == verein.saldo(verein.kw) == ct(10)
        verein.pruefe_abstimmung()

    def test_falsches_mitglied_storno_und_neu(self, verein):
        tom, tim = verein.mitglied("Tom"), verein.mitglied("Tim")
        falsch = verein.einzahlung(tim, "60")
        verein.storno(falsch)
        verein.einzahlung(tom, "60")
        assert verein.saldo(tim) == 0
        assert verein.saldo(tom) == ct(60)

    def test_falsche_buchungsart_storno(self, verein):
        tom = verein.mitglied("Tom")
        falsch = verein.auszahlung(tom, "50")  # war eigentlich eine Einzahlung
        verein.storno(falsch)
        verein.einzahlung(tom, "50")
        assert verein.saldo(tom) == verein.saldo(verein.kw) == ct(50)

    def test_storno_eines_beitrags(self, verein):
        kasse = verein.kasse("Beitragskasse")
        tom = verein.mitglied("Tom", St.ALUMNI)
        b = verein.beitrag(tom, kasse, "60")
        storno = verein.storno(b)
        assert storno.soll_konto_id == kasse.id and storno.haben_konto_id == tom.id
        assert verein.saldo(tom) == verein.saldo(kasse) == 0

    def test_storno_einer_umbuchung(self, verein):
        a, b = verein.kasse("A"), verein.kasse("B")
        u = verein.umbuchung(a, b, "10")
        verein.storno(u)
        assert verein.saldo(a) == verein.saldo(b) == 0

    def test_storno_bleibt_in_der_historie(self, verein, session):
        tom = verein.mitglied("Tom")
        b = verein.einzahlung(tom, "10")
        verein.storno(b)
        liste = bh.buchungen(session, tom.id)
        assert len(liste) == 2
        assert {x.art for x in liste} == {Art.EINZAHLUNG, Art.STORNO}

    def test_storno_mit_eigenem_datum(self, verein, session):
        tom = verein.mitglied("Tom")
        b = verein.einzahlung(tom, "10", datum=date(2026, 1, 5))
        storno = bh.stornieren(session, b.id, date(2026, 2, 1))
        assert storno.datum == date(2026, 2, 1)

    def test_storno_uebernimmt_beleg(self, verein, session):
        tom = verein.mitglied("Tom")
        b = bh.buchen(session, Art.EINZAHLUNG, tom.id, 100, "x", beleg="KA-2026-017")
        assert verein.storno(b).beleg == "KA-2026-017"

    def test_storno_auf_deaktiviertem_konto_erlaubt(self, verein):
        """Fehler müssen auch nach dem Austritt noch korrigierbar sein."""
        tom = verein.mitglied("Tom")
        b = verein.einzahlung(tom, "10")
        tom.aktiv = False
        verein.storno(b)
        assert verein.saldo(tom) == 0

    def test_storno_unbekannte_buchung(self, session):
        with pytest.raises(bh.BuchhaltungsFehler):
            bh.stornieren(session, 9999)


# --- Ein- und Austritte ---------------------------------------------------

class TestMitgliedschaft:
    def test_austritt_mit_offenem_beitrag(self, verein, session):
        kasse = verein.kasse("Beitragskasse")
        tom = verein.mitglied("Tom")
        verein.beitrag(tom, kasse, "60")
        bh.konto_bearbeiten(session, tom.id, "Tom", St.AKTIVER, "ausgetreten", False)

        assert verein.saldo(tom) == ct(-60)  # Schuld bleibt sichtbar
        with pytest.raises(bh.BuchhaltungsFehler):
            verein.einzahlung(tom, "60")  # deaktiviert: keine neuen Buchungen

        bh.konto_bearbeiten(session, tom.id, "Tom", St.AKTIVER, "", True)  # reaktivieren
        verein.einzahlung(tom, "60")
        assert verein.saldo(tom) == 0

    def test_wiedereintritt_unter_gleichem_namen_nicht_doppelt(self, verein):
        verein.mitglied("Tom")
        with pytest.raises(bh.BuchhaltungsFehler):
            verein.mitglied("Tom", St.ALUMNI)

    def test_gleichnamige_mitglieder_mit_zusatz(self, verein):
        a = verein.mitglied("Max Müller")
        b = verein.mitglied("Max Müller (2)")
        assert a.id != b.id

    def test_umbenennen_behaelt_buchungen(self, verein, session):
        tom = verein.mitglied("Tom")
        verein.einzahlung(tom, "10")
        bh.konto_bearbeiten(session, tom.id, "Thomas", St.AKTIVER, "", True)
        assert verein.saldo(tom) == ct(10)
        assert bh.buchungen(session, tom.id)[0].haben_konto.name == "Thomas"

    def test_name_wird_getrimmt(self, verein):
        assert verein.mitglied("  Tom  ").name == "Tom"

    @pytest.mark.parametrize("name", ["", "   "])
    def test_leerer_name(self, verein, name):
        with pytest.raises(bh.BuchhaltungsFehler):
            verein.mitglied(name)

    def test_unbekanntes_konto_bearbeiten(self, session):
        with pytest.raises(bh.BuchhaltungsFehler):
            bh.konto_bearbeiten(session, 9999, "x", None, "", True)

    def test_status_von_kasse_setzen_verboten(self, verein, session):
        kasse = verein.kasse("K")
        with pytest.raises(bh.BuchhaltungsFehler):
            bh.konto_bearbeiten(session, kasse.id, "K", St.FUX, "", True)

    def test_status_bei_privatkonto_entfernen_verboten(self, verein, session):
        tom = verein.mitglied("Tom")
        with pytest.raises(bh.BuchhaltungsFehler):
            bh.konto_bearbeiten(session, tom.id, "Tom", None, "", True)


# --- Ganzes Vereinsjahr ---------------------------------------------------

def test_komplettes_vereinsjahr(verein, session):
    beitrag = verein.kasse("Beitragskasse")
    getraenke = verein.kasse("Getränkekasse")
    fest = verein.kasse("Festkasse")
    fuxe = [verein.mitglied(n, St.FUX) for n in ("Fritz", "Felix")]
    aktive = [verein.mitglied(n, St.AKTIVER) for n in ("Tom", "Anna", "Ben")]
    alumni = [verein.mitglied(n, St.ALUMNI) for n in ("Alfred", "Bernd")]

    verein.beitragslauf(beitrag, fux="30", aktiver="60", alumni="100", datum=date(2026, 1, 15))
    for m in fuxe + aktive + alumni[:1]:
        verein.einzahlung(m, {St.FUX: "30", St.AKTIVER: "60", St.ALUMNI: "100"}[m.status])
    # Bernd zahlt nicht

    verein.ausgabe(getraenke, "240", "Getränkeeinkauf")
    for m, betrag in zip(aktive, ("31,50", "12", "48,20")):
        verein.umbuchung(m, getraenke, betrag, "Strichliste")
    verein.einzahlung(aktive[0], "31,50")

    verein.umbuchung(beitrag, fest, "150", "Zuschuss Sommerfest")
    verein.ausgabe(fest, "420")
    verein.einnahme(fest, "380")
    verein.einnahme(beitrag, "200", "Spende")

    b = verein.einzahlung(alumni[1], "1000", "Tippfehler")
    verein.storno(b)

    salden = bh.salden(session)
    assert salden[alumni[1].id] == ct(-100)
    assert salden[aktive[1].id] == ct(-12)
    assert salden[aktive[2].id] == ct("-48,20")
    assert salden[getraenke.id] == ct("-240") + ct("91,70")
    assert salden[fest.id] == ct(110)
    assert salden[beitrag.id] == ct(2 * 30 + 3 * 60 + 2 * 100 - 150 + 200)
    offene_posten = sum(v for k, v in salden.items() if v < 0 and k in {m.id for m in fuxe + aktive + alumni})
    assert offene_posten == ct("-160,20")
    verein.pruefe_abstimmung()
