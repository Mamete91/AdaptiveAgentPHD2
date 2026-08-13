# -*- coding: utf-8 -*-
"""Genera il PDF del Manuale Utente di Adaptive Agent for PHD2.

§26: metadata PDF (titolo, autore, soggetto, creator, keywords) letti dal
modulo phd2_agent/__about__.py — single source of truth del branding.
Usa font DejaVu (no emoji font disponibile) -> marcatori grafici al posto
delle emoji.
"""
# §26: import branding direttamente dal file __about__.py via importlib.
# Evita di passare per phd2_agent/__init__.py (che carica controller/analyzer
# e richiede tomli/numpy/scipy non necessari per la generazione del PDF).
import os as _os, sys as _sys
import importlib.util as _ilu
_ABOUT_PATH = _os.path.join(
    _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
    "phd2_agent", "__about__.py"
)
_about_spec = _ilu.spec_from_file_location("_phd2_about_isolated", _ABOUT_PATH)
_about = _ilu.module_from_spec(_about_spec)
_about_spec.loader.exec_module(_about)
__project_name__    = _about.__project_name__
__version__         = _about.__version__
__author__          = _about.__author__
__copyright__       = _about.__copyright__
__contact_telegram__ = _about.__contact_telegram__

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer,
    Table, TableStyle, ListFlowable, ListItem, HRFlowable, KeepTogether
)
from reportlab.platypus.flowables import Flowable

# ---- Fonts ----
def _find_dejavu_dir():
    """Cerca i 4 file DejaVuSans*.ttf cross-platform.
    Ordine: path Linux standard -> bundle matplotlib (Windows/macOS)."""
    import os
    candidates = ["/usr/share/fonts/truetype/dejavu/"]
    try:
        import matplotlib  # type: ignore
        candidates.append(os.path.join(os.path.dirname(matplotlib.__file__),
                                       "mpl-data", "fonts", "ttf") + os.sep)
    except ImportError:
        pass
    needed = ["DejaVuSans.ttf", "DejaVuSans-Bold.ttf",
              "DejaVuSans-Oblique.ttf", "DejaVuSans-BoldOblique.ttf"]
    for d in candidates:
        if all(os.path.isfile(d + n) for n in needed):
            return d
    raise RuntimeError("Font DejaVu non trovati. Su Windows/macOS: `pip install matplotlib`.")

FD = _find_dejavu_dir()
pdfmetrics.registerFont(TTFont("DJ",  FD + "DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("DJB", FD + "DejaVuSans-Bold.ttf"))
pdfmetrics.registerFont(TTFont("DJI", FD + "DejaVuSans-Oblique.ttf"))
pdfmetrics.registerFont(TTFont("DJBI", FD + "DejaVuSans-BoldOblique.ttf"))
registerFontFamily("DJ", normal="DJ", bold="DJB", italic="DJI", boldItalic="DJBI")

# ---- Palette ----
INK     = colors.HexColor("#1a2332")
MUTED   = colors.HexColor("#55617a")
ACCENT  = colors.HexColor("#3b5bdb")
ACCENT2 = colors.HexColor("#7048e8")
GOLD    = colors.HexColor("#d9a300")
GREEN   = colors.HexColor("#2f9e44")
RED     = colors.HexColor("#c92a2a")
LINEC   = colors.HexColor("#d6dbe6")
BGCARD  = colors.HexColor("#f4f6fb")
DEEP    = colors.HexColor("#0b1733")

# ---- Styles ----
body = ParagraphStyle("body", fontName="DJ", fontSize=10.2, leading=15.5,
                      textColor=INK, spaceAfter=7, alignment=TA_LEFT)
lead = ParagraphStyle("lead", parent=body, fontSize=11, leading=17, textColor=MUTED)
bullet = ParagraphStyle("bullet", parent=body, spaceAfter=5, leading=15)
h3 = ParagraphStyle("h3", fontName="DJB", fontSize=11.5, leading=15, textColor=INK,
                    spaceBefore=8, spaceAfter=4)
callout_t = ParagraphStyle("ct", parent=body, fontSize=9.8, leading=14.5, spaceAfter=0)
small = ParagraphStyle("small", parent=body, fontSize=8.6, textColor=MUTED, leading=12)


class SectionHeader(Flowable):
    def __init__(self, text, color=ACCENT, width=170*mm):
        super().__init__()
        self.text = text; self.color = color; self.width = width; self.height = 11*mm
    def wrap(self, aw, ah):
        return self.width, self.height
    def draw(self):
        c = self.canv
        c.setFillColor(self.color)
        c.roundRect(0, 1.5*mm, 3.2*mm, 8*mm, 1.2, fill=1, stroke=0)
        c.setFont("DJB", 14.5)
        c.setFillColor(ACCENT)
        c.drawString(7*mm, 3.4*mm, self.text)


class NumBadge(Flowable):
    def __init__(self, n, color):
        super().__init__(); self.n=str(n); self.color=color
        self.width=7*mm; self.height=7*mm
    def wrap(self,aw,ah): return self.width,self.height
    def draw(self):
        c=self.canv; c.setFillColor(self.color)
        c.circle(3.5*mm,3*mm,3.4*mm,fill=1,stroke=0)
        c.setFillColor(colors.white); c.setFont("DJB",10)
        c.drawCentredString(3.5*mm,1.6*mm,self.n)


def feature_head(n, title, color):
    p = Paragraph('<font name="DJB" size="11.5" color="#1a2332">%s</font>' % title, h3)
    t = Table([[NumBadge(n,color), p]], colWidths=[9*mm, 161*mm])
    t.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0),
        ("TOPPADDING",(0,0),(-1,-1),2),("BOTTOMPADDING",(0,0),(-1,-1),2),
    ]))
    return t


def callout(label, label_color, text):
    hexcol = "#" + label_color.hexval()[2:]
    inner = Paragraph(text, callout_t)
    t = Table([[inner]], colWidths=[163*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),BGCARD),
        ("LEFTPADDING",(0,0),(-1,-1),9),("RIGHTPADDING",(0,0),(-1,-1),9),
        ("TOPPADDING",(0,0),(-1,-1),7),("BOTTOMPADDING",(0,0),(-1,-1),7),
        ("LINEBEFORE",(0,0),(0,-1),3,label_color),
        ("BOX",(0,0),(-1,-1),0.5,LINEC),
    ]))
    head = Paragraph('<font name="DJB" size="8.5" color="%s">%s</font>' % (hexcol, label), callout_t)
    wrap = Table([[head],[t]], colWidths=[163*mm])
    wrap.setStyle(TableStyle([
        ("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0),
        ("TOPPADDING",(0,0),(0,0),0),("BOTTOMPADDING",(0,0),(0,0),3),
        ("TOPPADDING",(0,1),(0,1),0),("BOTTOMPADDING",(0,1),(0,1),0),
    ]))
    return KeepTogether([Spacer(1,3), wrap, Spacer(1,4)])


def pill(text, color):
    return Paragraph('<font name="DJB" size="9" color="%s">%s</font>'
                     % ("#"+color.hexval()[2:], text), small)


def blist(items):
    lis=[ListItem(Paragraph(x,bullet), leftIndent=6, value="–",
                  bulletColor=ACCENT) for x in items]
    return ListFlowable(lis, bulletType="bullet", start="–",
                        bulletFontName="DJB", bulletFontSize=10,
                        leftIndent=12, bulletColor=ACCENT)

def B(s): return "<b>%s</b>" % s
def I(s): return "<i>%s</i>" % s

story=[]; S=story.append

# ---------- COVER ----------
class Cover(Flowable):
    def __init__(self,w,h): super().__init__(); self.w=w; self.h=h
    def wrap(self,aw,ah): return self.w,self.h
    def draw(self):
        import random
        c=self.canv
        c.setFillColor(DEEP); c.rect(0,0,self.w,self.h,fill=1,stroke=0)
        random.seed(7); c.setFillColor(colors.white)
        for _ in range(60):
            x=random.uniform(0,self.w); y=random.uniform(self.h*0.12,self.h)
            r=random.choice([0.3,0.4,0.6,0.8])
            c.setFillAlpha(random.uniform(0.25,0.9)); c.circle(x,y,r,fill=1,stroke=0)
        c.setFillAlpha(1)
        c.setStrokeColor(colors.HexColor("#5b7cff")); c.setLineWidth(2)
        c.line(20*mm, self.h-34*mm, 70*mm, self.h-34*mm)
        c.setFillColor(colors.HexColor("#aebbff")); c.setFont("DJB",10.5)
        c.drawString(20*mm, self.h-30*mm, "MANUALE UTENTE")
        # §26: titolo branded — letto da phd2_agent.__about__ (single source of truth)
        c.setFillColor(colors.white); c.setFont("DJB",28)
        c.drawString(20*mm, self.h-50*mm, __project_name__)
        c.setFillColor(colors.HexColor("#c9d4ff")); c.setFont("DJB",16)
        c.drawString(20*mm, self.h-62*mm, f"Versione {__version__}  ·  by {__author__}")
        c.setFillColor(colors.HexColor("#c9d4ff")); c.setFont("DJI",12)
        c.drawString(20*mm, self.h-72*mm, "Il tuo copilota astrofotografico")
        # Footer cover: copyright + community Telegram (al posto della lista setup di sviluppo)
        c.setFillColor(colors.HexColor("#8a99c9")); c.setFont("DJ",9)
        c.drawString(20*mm, 20*mm, __copyright__)
        c.drawString(20*mm, 14*mm, f"Community e supporto:  {__contact_telegram__}")

S(Cover(170*mm, 150*mm))
S(Spacer(1,8*mm))
S(Paragraph(
    "L'%s è il tuo copilota astrofotografico. Lavora “sotto il cofano” "
    "assieme a PHD2 e alla tua suite principale (come NINA), agendo come un utente umano molto "
    "reattivo che fissa di continuo lo schermo della guida per fare i micro-aggiustamenti che ti "
    "salvano la nottata. %s sul tuo setup: legge dal profilo PHD2 la scala di campionamento del tuo "
    "treno ottico e tara le sue soglie sul cielo reale che sta misurando, notte per notte."
    % (B("Adaptive Agent"), B("Si configura da solo")), lead))

# ---------- PRIMA DI INIZIARE ----------
S(Spacer(1,6))
S(SectionHeader("Prima di iniziare (importante)", RED))
S(HRFlowable(width="100%", thickness=0.6, color=LINEC, spaceAfter=8))
S(Paragraph(B("Con quali algoritmi di guida PHD2 lavora l'Agente"), h3))
S(Paragraph(
    "L'Agente regola due «manopole» di PHD2: l'Aggressività e il MinMove. Funziona quindi "
    "al meglio con gli algoritmi che espongono entrambe — che sono anche quelli di default di PHD2:", body))

algo_tbl = Table([
    [Paragraph(B("Algoritmo"),small), Paragraph(B("Leve disponibili"),small), Paragraph(B("Compatibilità"),small)],
    [Paragraph("Hysteresis (RA) + Resist Switch (DEC)",small), Paragraph("Aggressività + MinMove",small), pill("Piena — consigliata", GREEN)],
    [Paragraph("Lowpass2",small), Paragraph("Aggressività + MinMove",small), pill("Piena", GREEN)],
    [Paragraph("Lowpass",small), Paragraph("solo MinMove",small), pill("Parziale", GOLD)],
    [Paragraph("Predictive PEC / Gaussian Process",small), Paragraph("solo MinMove",small), pill("Sconsigliato", RED)],
    [Paragraph("None",small), Paragraph("nessuna",small), pill("Non funziona", RED)],
], colWidths=[68*mm, 50*mm, 45*mm])
algo_tbl.setStyle(TableStyle([
    ("BACKGROUND",(0,0),(-1,0),ACCENT),
    ("TEXTCOLOR",(0,0),(-1,0),colors.white),("FONTNAME",(0,0),(-1,0),"DJB"),
    ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,BGCARD]),
    ("LINEBELOW",(0,0),(-1,-1),0.4,LINEC),("BOX",(0,0),(-1,-1),0.5,LINEC),
    ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
    ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),
    ("LEFTPADDING",(0,0),(-1,-1),7),
]))
S(algo_tbl)
S(Paragraph(
    "I due algoritmi sconsigliati (Predictive PEC e Gaussian Process) sono «predittivi»: costruiscono "
    "nel tempo un modello dell'errore periodico basato su una cadenza di posa costante. L'esposizione "
    "dinamica dell'Agente cambia il tempo di posa e ne disturba il modello; inoltre non espongono "
    "l'aggressività.", body))
S(callout("SUGGERIMENTO", GREEN,
    "In dubbio? Lascia PHD2 sui suoi valori predefiniti (Hysteresis su RA, Resist Switch su DEC): è "
    "esattamente lo scenario per cui l'Agente è stato progettato."))

S(Paragraph(B("Cosa NON fa l'Agente (e cosa serve prima di lanciarlo)"), h3))
S(Paragraph(
    "L'Agente è un %s, non un sistema di guida completo. Non calibra e non avvia la guida da solo: si "
    "appoggia a una sessione PHD2 %s. Prima di lanciarlo assicurati che:"
    % (B("assistente"), B("già calibrata e in guida attiva")), body))
S(blist([
    "PHD2 stia già guidando correttamente su una stella;",
    "in PHD2 sia attivo il server (%s, porta 4400): è il canale con cui l'Agente comunica;"
    % B("Strumenti → Abilita Server"),
    "nel profilo PHD2 in uso siano impostate correttamente %s e %s: da qui l'Agente ricava in "
    "automatico la scala di campionamento. Se questi dati non ci sono, l'Agente userà un valore di "
    "fallback e la dashboard te lo segnalerà;"
    % (B("focale di guida"), B("dimensione pixel della camera di guida")),
    "l'Agente possa scaricare le immagini di guida (serve alla riselezione delle stelle sature al cambio esposizione).",
]))
S(Paragraph(
    "E per tua tranquillità: l'Agente %s la calibrazione della montatura né la compensazione del "
    "backlash. Lavora solo su leve «morbide» e reversibili." % B("non tocca mai"), body))

# ---------- PERCHE' ----------
S(Spacer(1,6))
S(SectionHeader("Perché è nato questo progetto?"))
S(HRFlowable(width="100%", thickness=0.6, color=LINEC, spaceAfter=8))
S(Paragraph(
    "Quando il cielo è perfetto, PHD2 con i suoi settaggi aggressivi di “inizio serata” guida "
    "benissimo. Il problema è che il cielo %s: arrivano turbolenze, foschia, vento, nuvole di "
    "passaggio. E quei settaggi che prima erano l'ideale, ora diventano controproducenti."
    % B("non resta perfetto"), body))
S(Paragraph(
    "Il pericolo principale è l'%s: se il seeing peggiora, PHD2 continua a inseguire ogni piccolo "
    "tremolio della stella come se fosse un errore reale da correggere. Ma quel tremolio è solo aria "
    "che si muove. Il risultato è che la montatura “rincorre il rumore”, l'errore RMS sale invece "
    "di scendere, e le stelle nei tuoi scatti vengono mosse." % B("iper-correzione a catena"), body))
S(Paragraph(
    "C'è poi un secondo fronte: gli allarmi di %s (Stella persa). Bastano una nuvola di passaggio o un "
    "ri-puntamento (dither) e PHD2 perde la stella di guida. Spesso poi non riesce a riagganciarne una "
    "nuova da solo, oppure scarta proprio le stelle più luminose e utili perché le considera “troppo "
    "sature”. A quel punto la guida si ferma e, a cascata, si ferma anche NINA." % B("StarLost"), body))
S(Paragraph(
    "Lasciare PHD2 da solo tutta la notte significa accettare questi due rischi. L'%s è nato esattamente "
    "per stare sveglio al posto tuo: sorveglia di continuo come sta andando la guida e interviene in tre "
    "modi, sempre con l'idea di %s:"
    % (B("Agente"), B("prima la mossa «economica», poi quella più importante")), body))
S(blist([
    "%s quando l'aria peggiora, così PHD2 smette di rincorrere il rumore." % B("Ammorbidisce la guida"),
    "%s della camera di guida quando ammorbidire non basta più, per «mediare» la turbolenza." % B("Allunga l'esposizione"),
    "%s con un suo sistema di visione, quando PHD2 alza bandiera bianca." % B("Recupera la stella persa"),
]))
S(Paragraph("Il tutto mentre tu dormi o fai altro, e senza mai sostituirsi alle tue scelte di fondo.", body))

# ---------- COSA FA ----------
S(Spacer(1,6))
S(SectionHeader("Cosa fa in automatico?"))
S(HRFlowable(width="100%", thickness=0.6, color=LINEC, spaceAfter=8))

S(feature_head(1, "Regolazione Dinamica dei Parametri (RA / Dec)", ACCENT))
S(Paragraph("L'Agente analizza ciclicamente (ogni X secondi) il trend dell'errore RMS e una stima del "
            "seeing (confrontando i picchi di spostamento).", body))
S(blist([
    "%s: abbassa automaticamente l'%s e, se l'errore continua a saltare, alza il %s di tolleranza. In "
    "pratica permette alla montatura di «scivolare» sul vento invece di reagire a ogni colpo (che "
    "peggiorerebbe l'RMS)." % (B("Se fiuta Vento o Oscillazioni critiche"), I("Aggressività"), I("MinMove")),
    "%s: ripristina per gradi l'aggressività, per tornare alla guida precisa tipica delle notti "
    "perfette." % B("Se il cielo torna calmo e limpidissimo"),
    "%s: l'Agente sa qual e' il livello di errore tipico del tuo cielo migliore (la mediana che misura "
    "da solo durante la calibrazione). Appena la guida raggiunge quel livello, smette di «spingere» le "
    "leve verso la reattivita' massima e le lascia ferme sul punto buono: in un cielo gia' ottimo, leve "
    "troppo nervose inseguono il rumore atmosferico e l'RMS ricomincerebbe a salire. Se le condizioni "
    "peggiorano, l'Agente riprende automaticamente a regolare le leve come prima. Disattivabile da "
    "config.toml ([lever_optimization] enabled = false)."
    % B("Quando la guida e' gia' al suo meglio (novita' v2.3)"),
]))

S(feature_head(2, "Esposizione Dinamica della camera di guida", ACCENT2))
S(Paragraph(
    "Questa è la leva che entra in gioco %s. Allungare l'esposizione della camera di guida fa una cosa "
    "molto utile: ogni fotogramma «media» su più tempo le micro-vibrazioni dell'aria, quindi il segnale "
    "arriva a PHD2 già più pulito. L'Agente la usa in due situazioni distinte:"
    % B("quando le manopole di cui sopra non bastano più"), body))
S(blist([
    "%s: se il segnale della stella di guida crolla (nuvola sottile, foschia), l'Agente raddoppia "
    "l'esposizione per «raccogliere più luce» e non perdere la stella. È una mossa rapida e binaria "
    "(×2)." % B("Stella troppo debole (SNR basso)"),
    "%s: se l'aria è turbolenta ma la stella è ancora ben visibile, l'Agente alza l'esposizione per "
    "gradini dolci (passi di circa ×1,5, fino a due gradini sopra il valore base). Più posa = meno "
    "rumore ad alta frequenza = RMS più basso." % B("Seeing degradato (turbolenza)"),
]))
S(callout("IMPORTANTE", GOLD,
    "%s Prima prova sempre con le leve «economiche»: abbassa l'aggressività e alza il MinMove. Solo "
    "quando queste hanno raggiunto i loro limiti (la cosiddetta %s, il «cancello di escalation» si apre) "
    "e il cielo è ancora turbolento, allora — e solo allora — l'Agente decide di allungare l'esposizione. "
    "È una scala di interventi deliberata: prima il rimedio leggero, poi quello più impattante."
    % (B("L'Agente non tocca subito l'esposizione."), I("escalation gate"))))
S(Paragraph(
    "Per sicurezza l'esposizione %s che hai impostato tu, e ha un tetto massimo. Quando il cielo torna "
    "tranquillo, l'Agente riporta l'esposizione al valore base un gradino alla volta."
    % B("non scende mai sotto il valore base"), body))

S(feature_head(3, "Recupero della stella persa", GREEN))
S(Paragraph(
    "Quando PHD2 stacca il tracciamento e mostra «Stella Persa», l'Agente non resta a guardare — ma non "
    "prova nemmeno a fare il lavoro di PHD2 al posto suo. La selezione della stella di guida è competenza "
    "di PHD2, che sul proprio sensore ha molte più informazioni di quante ne abbia l'Agente da fuori. "
    "Quello che l'Agente aggiunge è il QUANDO e il QUANTO INSISTERE:", body))
S(blist([
    "Attende qualche secondo: molti STAR_LOST rientrano da soli (una folata di seeing, un satellite) e insistere subito non aiuta.",
    "Chiede a PHD2 di riselezionare la stella con il suo stesso algoritmo, quello che conosce il sensore.",
    "Se il tentativo fallisce, rallenta invece di accanirsi: dopo alcuni fallimenti dirada i tentativi, dopo altri si SOSPENDE. Nasce da un incidente reale — una camera di guida crashata via USB aveva ricevuto oltre 130 richieste in sei minuti, caricando proprio il bus che stava soffocando.",
    "Trova le coordinate della stella più consistente e ordina via RPC API a PHD2 di richiudersi su quel pixel, costringendolo a riprendere il tracciamento e recuperando il crollo in modo forzato.",
]))

# ---------- AUTO-CONFIGURAZIONE ----------
S(Spacer(1,6))
S(SectionHeader("Auto-configurazione: si tara da solo sul tuo setup", ACCENT2))
S(HRFlowable(width="100%", thickness=0.6, color=LINEC, spaceAfter=8))
S(Paragraph(
    "La novità che rende l'Agente «plug and play» su qualunque telescopio o camera di guida. Non devi più "
    "dirgli a mano la pixel scale, né tarare manualmente le soglie RMS per ogni rig: lo fa lui all'avvio.", body))
S(Paragraph(B("Pixel scale automatica."), h3))
S(Paragraph(
    "All'avvio l'Agente chiede a PHD2 la scala di campionamento del profilo attivo (calcolata da focale di "
    "guida × dimensione pixel della camera, considerando il binning). Quel numero diventa la sua «regola in "
    "arcsec» per tutta la sessione. Se cambi telescopio, monti un riduttore o passi ad altro profilo PHD2, "
    "basta selezionare il profilo giusto in PHD2 prima di lanciare l'Agente: si riadatta da solo. Se PHD2 "
    "non conosce la scala (focale di guida non impostata nel profilo), l'Agente usa il valore di fallback "
    "nel file di configurazione e te lo segnala sulla dashboard con un badge esplicito.", body))
S(Paragraph(B("Soglie RMS adattive."), h3))
S(Paragraph(
    "Le soglie che decidono quando il cielo è «degradato» o «eccellente» non sono più costanti fisse tarate "
    "a mano per ogni setup, ma si calcolano da una %s. Nei primi minuti di guida calma l'Agente raccoglie un "
    "campione di RMS in condizione normale, ne fa la mediana, e da quella deriva le soglie. In pratica: la "
    "tua notte sul tuo rig diventa il punto di riferimento, automaticamente. Una nottata buona tara soglie "
    "strette, una nottata mediocre soglie più larghe, sempre coerenti col cielo che hai davvero sopra la testa."
    % B("baseline misurata sul tuo cielo reale"), body))
S(Paragraph(B("Reti di sicurezza sulla calibrazione."), h3))
S(Paragraph(
    "L'Agente non lascia che una serata fuori scala «promuova» valori sbagliati a normalità. Se la baseline "
    "misurata è palesemente troppo alta, la calibrazione viene %s e l'Agente mantiene le soglie iniziali del "
    "file di configurazione (dashboard: badge %s). Se invece la baseline è normale ma la soglia derivata "
    "supererebbe %s — il riferimento universale di «guida pulita» indipendente dal setup — scatta il %s: "
    "la soglia viene «tagliata» a 1\" (dashboard: badge %s). Entrambe le reti tengono l'Agente sempre dentro "
    "un perimetro di qualità di guida riconosciuto, sia che tu usi un OAG sia che usi un cercatore-guida."
    % (B("rifiutata"), B("BASELINE RIFIUTATA"), B("1 arcsec"), B("cap"), B("CAP ATTIVO")), body))
S(Paragraph(B("Refresh ciclico della baseline."), h3))
S(Paragraph(
    "Una sessione astrofotografica può durare ore, e il cielo può cambiare nel frattempo. Per questo "
    "l'Agente non si «congela» sulla calibrazione iniziale: ogni 30 minuti la baseline viene ri-misurata "
    "silenziosamente (mentre le soglie correnti continuano a lavorare normalmente, senza buchi di copertura). "
    "Se la nuova baseline risulta %s della precedente — segno che il cielo è migliorato — viene sostituita e "
    "le soglie si stringono di conseguenza, rendendo l'Agente più reattivo. Se invece è uguale o più larga, "
    "viene %s: l'Agente non concede mai terreno al peggioramento del cielo. È la regola «tightest-wins», "
    "e ti garantisce che le soglie si tarino sempre sulle migliori condizioni della notte."
    % (B("più stretta"), B("ignorata")), body))
S(callout("SUGGERIMENTO", GREEN,
    "Hai un setup diverso da quelli su cui l'Agente è stato sviluppato? Non serve toccare nulla. Crea il "
    "profilo in PHD2 col tuo telescopio e la tua camera di guida (con focale e pixel size corrette), lancia "
    "Avvia.bat, e l'Agente farà il resto. %s"
    % B("Niente file da modificare a mano, niente versioni per setup.")))

# ---------- AVVIO RAPIDO ----------
S(Spacer(1,6))
S(SectionHeader("Avvio rapido", GREEN))
S(HRFlowable(width="100%", thickness=0.6, color=LINEC, spaceAfter=8))
S(Paragraph("Tutta la configurazione vive in %s e si lancia con %s:"
            % (B("un solo file"), B("un solo eseguibile")), body))
S(blist([
    "%s — l'unico file di configurazione, lo stesso per qualsiasi setup." % B("config.toml"),
    "%s — l'unico file di avvio, lo stesso per qualsiasi setup." % B("Avvia.bat"),
]))
S(Paragraph("Il workflow è in tre passi:", body))
S(blist([
    "Apri PHD2 e seleziona il %s che stai usando (con focale di guida e dimensione pixel camera corrette)."
    % B("profilo del telescopio"),
    "Avvia la guida su una stella in PHD2.",
    "Doppio clic su Avvia.bat e apri il browser su http://localhost:8080.",
]))
S(Paragraph(
    "Niente più «versione ridotta» del .bat: se monti il riduttore di focale, basta che il profilo PHD2 "
    "abbia la focale ridotta inserita (puoi avere due profili distinti, uno a focale piena e uno ridotta, e "
    "scegliere quello giusto in PHD2). L'Agente legge la scala reale da PHD2 e si adatta da sé, senza che "
    "tu cambi un solo file.", body))

# ---------- DASHBOARD ----------
S(Spacer(1,6))
S(SectionHeader("Come usare la Web Dashboard", ACCENT))
S(HRFlowable(width="100%", thickness=0.6, color=LINEC, spaceAfter=8))
S(Paragraph("La pagina web è la cabina di pilotaggio dove l'Agente ti espone in tempo reale la sua «mente».", body))
S(Paragraph(B("Grafici e Numeri (RMS / HFD / SNR)"), h3))
S(Paragraph("Una supervisione istantanea delle oscillazioni e della nitidezza stellare (condizione del "
            "cielo: DEGRADED, OSCILLATING, NORMAL).", body))
S(Paragraph(B("Pannello «Auto-calibrazione»  ")
            + '<font name="DJI" color="#2f9e44">(novità)</font>', h3))
S(Paragraph("Ti mostra come l'Agente si è tarato sul tuo setup:", body))
S(blist([
    "%s con badge %s (letta dal profilo PHD2) oppure %s (fallback se PHD2 non la conosce — significa che "
    "nel profilo PHD2 manca la focale di guida)."
    % (B("Pixel scale rilevata"), B("PHD2"), B("TOML")),
    "%s: i frame raccolti finora (es. «42/60») finché non si completa la misura, poi il valore di mediana "
    "misurato in arcsec." % B("Progresso baseline"),
    "%s: rms_high e rms_low derivate dalla baseline (le soglie con cui l'Agente sta giudicando il cielo in "
    "questo momento)." % B("Soglie attive"),
    "Badge %s: la soglia rms_high derivata avrebbe superato %s (il riferimento universale di guida pulita), "
    "ed è stata «tagliata» al cap. L'Agente è in modalità più severa del normale: significa che il cielo è "
    "ai limiti di quello che si considera una guida ancora accettabile."
    % (B("CAP ATTIVO (ambra)"), B("1 arcsec")),
    "Badge %s: la sessione è troppo compromessa per ricavarne una baseline rappresentativa. L'Agente usa le "
    "soglie iniziali del file di configurazione invece di calibrare su questa nottata."
    % B("BASELINE RIFIUTATA (rosso)"),
    "%s (novità §25): mostra il countdown al prossimo refresh automatico della baseline (es. «Prossimo tra "
    "24m 12s»), oppure «In corso: 23/60» quando la ri-misura è attiva. Durante la ri-misura le soglie "
    "precedenti continuano a essere applicate normalmente — non c'è mai un buco di copertura."
    % B("Refresh ciclico"),
    "Badge %s o %s: esito dell'ultimo ciclo di refresh. APPLICATO = il cielo è migliorato e le soglie si "
    "sono strette. RIFIUTATO = le condizioni sono rimaste uguali o sono peggiorate, l'Agente mantiene le "
    "soglie attive senza concedere reattività al peggioramento."
    % (B("Ultimo: APPLICATO (verde)"), B("Ultimo: RIFIUTATO (grigio)")),
]))
S(Paragraph(B("Pannello «Stato Esposizione & Escalation Gate»"), h3))
S(Paragraph("Ti mostra a colpo d'occhio cosa sta facendo l'Agente sull'esposizione e perché:", body))
S(blist([
    "%s: in che regime sei — %s (esposizione base), %s (alzata perché la stella era debole) o %s "
    "(alzata per gradini a causa della turbolenza)."
    % (B("Badge di stato esposizione"), I("NOMINAL"), I("BOOSTED_FOR_SNR"), I("BOOSTED_FOR_SEEING")),
    "%s: il tempo di posa corrente in millisecondi e quanti gradini sei sopra la base." % B("Valori di esposizione"),
    "%s: quanto sono «tirate» aggressività e MinMove su ciascun asse. Quando entrambe sono al limite, "
    "il cancello di escalation è aperto: è il segnale che l'Agente è autorizzato ad allungare "
    "l'esposizione." % B("Barre di saturazione delle leve (RA e DEC)"),
    "%s: i secondi che mancano prima che l'Agente possa fare un nuovo cambio di esposizione (evita che si "
    "agiti troppo)." % B("Cooldown residuo"),
    "%s: ogni cambio di esposizione lascia un triangolino sul grafico (giallo = esposizione alzata, verde = "
    "riportata giù), così colleghi a vista «ho cambiato esposizione qui» con l'andamento dell'RMS prima e "
    "dopo." % B("Marker sul grafico RMS"),
]))
S(Paragraph(B("Interruttore «MODALITÀ TEST»"), h3))
S(callout("SUGGERIMENTO", ACCENT,
    "Se %s (Dry Run) è %s, l'Agente emula le sue deduzioni nel «Log Decisioni Controller» dicendoti "
    "cosa farebbe, ma senza agire fisicamente in PHD2. Spegnila e passa in %s per lasciargli prendere "
    "attivamente il controllo del telescopio."
    % (B("MODALITÀ TEST"), B("ATTIVA"), B("LIVE CONTROL"))))
S(callout("NOTA", ACCENT2,
    "Il pacchetto distribuito parte %s, proprio perché il valore delle feature adattive (esposizione "
    "dinamica, soglie da baseline) si vede solo osservandone l'effetto reale sul grafico, non nei log di "
    "una simulazione." % B("già in LIVE")))
S(Paragraph(B("Log Decisioni Controller"), h3))
S(Paragraph(
    "Un tabellone cronologico con i messaggi. Ad esempio: «RA Aggressività 70 -> 65 | Abbasso "
    "aggressività perché Oscillazione rilevata» oppure «Esposizione 2000ms -> 3000ms | Seeing degradato, "
    "leve sature». Se è vuoto, significa semplicemente che la guida sta performando in modo sano e non "
    "serve intervenire.", body))

# ---------- BONUS: PLUGIN NINA ----------
S(Spacer(1,6))
S(SectionHeader("Bonus: usare la dashboard dentro NINA (plugin opzionale)", ACCENT2))
S(HRFlowable(width="100%", thickness=0.6, color=LINEC, spaceAfter=8))
S(Paragraph(
    "Se usi %s come suite di acquisizione, esiste un plugin C# separato — %s — che aggiunge a NINA un "
    "pannello dockable con la stessa dashboard «http://localhost:8080» caricata via WebView2 direttamente "
    "dentro l'interfaccia NINA. Vantaggio pratico: non devi più tenere aperta una finestra del browser "
    "accanto a NINA, la dashboard è una scheda dockable come tutte le altre."
    % (B("NINA"), B("Adaptive Agent for PHD2 — Dashboard")), body))
S(Paragraph(
    "%s Da v1.1 il pannello mostra in alto un badge che indica a colpo d'occhio se l'Agente è "
    "raggiungibile — «Agente online vX.Y» (verde) o «Agente offline» (grigio), aggiornato automaticamente "
    "ogni 15 secondi — e un pulsante %s che lancia Avvia.bat con un click, senza aprire Esplora Risorse. "
    "Per usarlo, imposta una sola volta il percorso del .bat in Options → Plugins → Adaptive Agent for "
    "PHD2 — Dashboard (pulsante «Sfoglia...»). Quando l'Agente è già online il pulsante si disabilita: "
    "resta una pura comodità, la dashboard funziona comunque."
    % (B("Pulsante Avvia e badge di stato."), B("«Avvia Adaptive Agent»")), body))
S(Paragraph(
    "%s Il cuore del plugin è un dispositivo virtuale che NINA usa come qualsiasi altro dispositivo di "
    "sicurezza. Appare nella tendina Equipment → Safety Monitor di NINA — che è il nome dello SLOT, non il "
    "ruolo del monitor — sotto la categoria %s col nome «Adaptive Agent for PHD2 — Condizioni del Cielo» "
    "(fino alla v1.11 si chiamava «Guide Safety»: NINA salva il dispositivo per identificativo, quindi il "
    "profilo esistente non si rompe). Selezionandolo e cliccando Connect, NINA riflette le condizioni di "
    "osservazione come flag safe/unsafe. Il driver dichiara %s in sei casi indipendenti: STAR_LOST persistente "
    "oltre il timeout configurato (default 5 minuti); trasparenza del cielo degradata a lungo, misurata sul "
    "conteggio stelle delle pose; crollo sostenuto del segnale della stella di guida, che il canale di guida "
    "vede minuti prima di quanto potrebbe la camera di ripresa; telemetria diventata stantia con l'ultimo "
    "cielo noto degradato; Agente irraggiungibile durante una sessione attiva; canale di guida ammutolito "
    "mentre la guida era attesa. Torna %s solo con evidenza positiva dalla camera di ripresa: una stella di "
    "guida sola può testimoniare che il cielo è peggiorato, non che il campo è tornato buono. Principio dalla "
    "v1.5, dopo una notte di validazione sul campo: perdere l'osservazione affidabile non è mai «sicuro» — il "
    "driver RESTA connesso anche se l'Agente sparisce, ed escala verso unsafe invece di disconnettersi in "
    "silenzio."
    % (B("Il monitor Condizioni del Cielo — il componente centrale."), B("N.I.N.A."), B("unsafe"), B("safe")), body))
S(callout("IMPORTANTE", GOLD,
    "Il driver Safety %s cosa fare al verificarsi dell'unsafe — %s. Le reazioni concrete (pausa sequenza, "
    "parking, warm-up camera, ecc.) si configurano dentro NINA, in Options → Safety (policy globale) oppure "
    "nell'Advanced Sequencer (istruzione «Wait until safe» e Global Trigger «Trigger On Unsafe»). Per uso "
    "domestico con supervisione attiva la configurazione consigliata è «Pause sequence on unsafe» + «Resume "
    "on safe», senza azioni custom aggressive. Per uso remoto non sorvegliato conviene aggiungere un "
    "«Trigger On Unsafe» con una sequenza custom di «safe shutdown»."
    % (B("non decide"), B("segnala soltanto"))))
S(callout("IMPORTANTE", GOLD,
    "Il plugin è %s: l'Agente funziona perfettamente senza. La dashboard web su http://localhost:8080 resta "
    "sempre il canale primario, ed è obbligatoria per chi vuole accedere da %s sulla stessa rete. Il plugin "
    "NINA non sostituisce il browser, lo affianca."
    % (B("opzionale"), B("tablet, secondo monitor o PC remoto"))))
S(Paragraph(B("Sequenza di avvio consigliata se usi anche il plugin NINA:"), h3))
S(blist([
    "Apri PHD2 e seleziona il profilo del telescopio.",
    "Lancia %s (l'Agente parte in background e serve la dashboard)." % B("Avvia.bat"),
    "Apri NINA: il pannello «Adaptive Agent for PHD2» si carica e mostra la dashboard automaticamente.",
]))
S(Paragraph(
    "Se NINA era già aperto prima dell'Agente, il pannello mostrerà inizialmente il messaggio «Agente non "
    "raggiungibile» con il pulsante %s: basta premerlo dopo che Avvia.bat è partito e la dashboard appare. "
    "È la stessa logica di fallback del browser: niente di rotto, solo l'ordine di avvio sbagliato."
    % B("Riprova"), body))
S(Paragraph(B("Installazione del plugin (una sola volta):"), h3))
S(Paragraph(
    "La DLL del plugin va copiata in %s e NINA va riavviato. Il pannello compare poi nel menu dockable di "
    "NINA. Per il dettaglio tecnico di build/install vedi il repository del plugin (progetto separato, "
    "distribuito sul gruppo Telegram della community insieme al pacchetto Agente)."
    % B("%LOCALAPPDATA%\\NINA\\Plugins\\3.0.0\\AdaptiveAgentForPHD2.NinaPlugin\\"), body))
S(callout("SUGGERIMENTO", GREEN,
    "Se il pannello mostra schermo bianco alla prima apertura senza messaggio di fallback, manca il "
    "%s: scaricalo dal sito Microsoft e riavvia NINA. Su Windows 11 è preinstallato, su Windows 10 "
    "aggiornato di solito anche, sui Windows 10 più datati può mancare."
    % B("runtime Microsoft Edge WebView2")))

# ---------- NINA ----------
S(Spacer(1,6))
S(SectionHeader("In sintonia perfetta con NINA", ACCENT))
S(HRFlowable(width="100%", thickness=0.6, color=LINEC, spaceAfter=8))
S(Paragraph("L'Agente non calpesta le azioni di NINA: si pone allo strato sottostante.", body))
S(Paragraph(
    "%s l'Agente mitiga l'RMS di PHD2 e lo mantiene stabile -> NINA, non appena riceve da PHD2 la notifica "
    "che l'RMS è rimasto sotto la soglia da te dichiarata (in Opzioni Apparecchiatura -> Settle pixels e "
    "Settle Time), è soddisfatta e scatta la foto. Così ottieni frame ultra-nitidi, perché NINA apre "
    "l'otturatore solo quando sa che tutto, sotto di sé, non sta sbandando." % B("Il workflow corretto è:"), body))

# ---------- FIDUCIA ----------
S(Spacer(1,6))
S(SectionHeader("In breve: di cosa puoi fidarti", GREEN))
S(HRFlowable(width="100%", thickness=0.6, color=LINEC, spaceAfter=8))
S(blist([
    "L'Agente %s: pixel scale letta dal profilo PHD2, soglie RMS tarate sulla baseline misurata del tuo "
    "cielo reale." % B("si configura da solo sul tuo setup"),
    "L'Agente %s: prima le manopole leggere (aggressività, MinMove), poi l'esposizione, e solo come "
    "ultima risorsa la visione AI per recuperare la stella." % B("interviene per gradi"),
    "L'esposizione %s e ha un tetto massimo: le tue scelte di partenza sono rispettate." % B("non scende mai sotto la tua base"),
    "Le %s sulla calibrazione (cap proporzionale + rigetto baseline) impediscono che una serata "
    "compromessa promuova soglie sbagliate a nuova normalità." % B("reti di sicurezza"),
    "Le soglie %s: la baseline viene ri-misurata periodicamente con la regola «tightest-wins» — l'Agente "
    "si stringe se il cielo migliora, ma non concede mai terreno se peggiora." % B("si adattano nel tempo"),
    "Se chiudi l'Agente o va in crash, un sistema di salvaguardia (%s) %s di PHD2, esposizione compresa."
    % (I("Baseline Guardian"), B("ripristina i parametri originali")),
    "L'Agente %s la compensazione del backlash né altri parametri di calibrazione delicati: lavora solo "
    "sulle leve «morbide» e reversibili." % B("non tocca"),
]))

# ---------- TROUBLESHOOTING (solo PDF — appendice per beta tester) ----------
S(Spacer(1,6))
S(SectionHeader("Troubleshooting rapido", GOLD))
S(HRFlowable(width="100%", thickness=0.6, color=LINEC, spaceAfter=8))
S(Paragraph(
    "Otto situazioni tipiche e cosa fare. Se non risolvi, riporta il caso sul gruppo Telegram della "
    "community (link in fondo) seguendo la sezione %s." % B("Come dare feedback"), body))

tshoot_rows = [
    [Paragraph(B("Sintomo"), small),
     Paragraph(B("Causa probabile"), small),
     Paragraph(B("Cosa fare"), small)],
    [Paragraph("La dashboard non si apre su localhost:8080", small),
     Paragraph("Firewall di Windows blocca la porta 8080.", small),
     Paragraph("Esegui una volta %s nella cartella del pacchetto (richiede privilegi di amministratore)." % B("Sblocca_Firewall_8080.bat"), small)],
    [Paragraph("Pixel scale nella card Auto-calibrazione resta con badge %s e non passa a %s" % (B("TOML"), B("PHD2")), small),
     Paragraph("Nel profilo PHD2 in uso mancano focale di guida o dimensione pixel della camera.", small),
     Paragraph("Apri %s in PHD2, completa i campi mancanti, salva il profilo e riavvia l'Agente." % B("Strumenti → Gestione profili"), small)],
    [Paragraph("Badge %s non sparisce dopo molti minuti" % B("BASELINE RIFIUTATA"), small),
     Paragraph("Seeing molto degradato o vento forte: l'Agente non riesce a campionare frame in condizione NOMINAL stabile.", small),
     Paragraph("Comportamento atteso, non è un bug. L'Agente sta usando le soglie del config.toml. Se persiste su una nottata buona, segnala il caso.", small)],
    [Paragraph("Progresso baseline resta fermo a 0/60 o n/60 a lungo", small),
     Paragraph("L'Agente raccoglie solo frame NOMINAL con SNR sufficiente. Cielo turbolento, stella debole o implosion detector attivo.", small),
     Paragraph("Aspetta condizioni più stabili. Verifica nei log che SNR sia sopra 8 e che non compaiano CRITICAL di tipo \"RMS IMPLOSION\".", small)],
    [Paragraph("Dopo la perdita della stella non viene riagganciata nulla", small),
     Paragraph("L'Agente chiede a PHD2 di riselezionare (find_star) a intervalli crescenti: se i tentativi "
               "falliscono ripetutamente entra in backoff e infine sospende, per non martellare una camera "
               "in difficoltà. Nel log compare \"find_star SUSPENDED dopo N fallimenti consecutivi\".", small),
     Paragraph("Quel messaggio indica un problema USB/camera, non dell'Agente: verifica cavo e alimentazione. "
               "Il monitor Condizioni del Cielo mostra GUIDE UNOBSERVABLE quando il canale di guida smette di "
               "fornire informazioni affidabili.", small)],
    [Paragraph("Triangoli (giallo/verde) non appaiono mai sul grafico RMS", small),
     Paragraph("Escalation gate chiuso (le leve aggr/MinMove non sono ancora sature), oppure il cielo è troppo stabile per richiedere il path B.", small),
     Paragraph("Normale: il path B esposizione scatta solo dopo che le leve cheap sono al limite da almeno un cooldown. Su cieli buoni può non scattare mai.", small)],
    [Paragraph("L'Agente si spegne da solo dopo X secondi/minuti", small),
     Paragraph("Connessione JSON-RPC a PHD2 caduta, oppure errore Python in un componente.", small),
     Paragraph("Controlla %s in cerca di righe ERROR/CRITICAL. Verifica che PHD2 sia attivo e che il server (porta 4400) sia abilitato." % B("Pacchetto_Distribuzione/logs/controller_*.log"), small)],
    [Paragraph("Tutti i parametri PHD2 tornano ai valori originali al riavvio", small),
     Paragraph("Non è un bug: è il %s che ripristina lo stato iniziale alla chiusura pulita o al rilevamento di una baseline orfana." % I("Baseline Guardian"), small),
     Paragraph("Comportamento corretto e desiderato. L'Agente parte sempre da una base nota, mai da uno stato ereditato.", small)],
]
tshoot_tbl = Table(tshoot_rows, colWidths=[48*mm, 55*mm, 60*mm])
tshoot_tbl.setStyle(TableStyle([
    ("BACKGROUND",(0,0),(-1,0),GOLD),
    ("TEXTCOLOR",(0,0),(-1,0),colors.white),("FONTNAME",(0,0),(-1,0),"DJB"),
    ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,BGCARD]),
    ("LINEBELOW",(0,0),(-1,-1),0.4,LINEC),("BOX",(0,0),(-1,-1),0.5,LINEC),
    ("VALIGN",(0,0),(-1,-1),"TOP"),
    ("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6),
    ("LEFTPADDING",(0,0),(-1,-1),7),("RIGHTPADDING",(0,0),(-1,-1),7),
]))
S(tshoot_tbl)

# ---------- COME DARE FEEDBACK (solo PDF — appendice per beta tester) ----------
S(Spacer(1,6))
S(SectionHeader("Come dare feedback (gruppo Telegram)", ACCENT))
S(HRFlowable(width="100%", thickness=0.6, color=LINEC, spaceAfter=8))
S(Paragraph(
    "Questa è la versione beta del software. Il tuo feedback è prezioso e serve a far evolvere l'Agente "
    "sui setup reali della community, non solo sui tre su cui è nato. Tutti i feedback transitano dal "
    "gruppo Telegram (link a fondo pagina). Per essere utile e veloce da diagnosticare, un buon report "
    "include alcune informazioni di base.", body))

S(Paragraph(B("Cosa allegare a un report di bug o comportamento strano"), h3))
S(blist([
    "%s del tuo setup: telescopio, focale di guida, camera di guida (modello + pixel size), montatura, eventuale riduttore." % B("Descrizione"),
    "%s del profilo PHD2 in uso e algoritmo di guida selezionato (es. Hysteresis su RA, Resist Switch su DEC)." % B("Nome"),
    "%s della card Auto-calibrazione e del pannello Stato Esposizione & Escalation Gate al momento del problema." % B("Screenshot"),
    "%s dalla cartella Pacchetto_Distribuzione/logs/ — almeno: decisions_*.jsonl della sessione in cui è capitato il problema, controller_*.log della stessa sessione, e se possibile session_*.summary.json (sono file di testo, pesano pochi KB)." % B("File di log"),
]))
S(callout("SUGGERIMENTO", GREEN,
    "Se non sei sicuro che sia un bug o un comportamento corretto, %s. È molto più facile spiegare "
    "perché qualcosa è atteso che dover indovinare perché qualcosa è andato storto. Anche i \"falsi "
    "allarmi\" sono utili: aiutano a capire cosa non è chiaro nel manuale."
    % B("scrivilo lo stesso")))

S(Paragraph(B("Cosa NON serve riportare (e perché)"), h3))
S(blist([
    "%s in sessioni con vento forte o seeing turbolento: è il comportamento corretto, l'Agente sta proteggendoti da una calibrazione su nottata anomala." % B("\"BASELINE RIFIUTATA\""),
    "%s: il path B esposizione scatta solo dopo saturazione delle leve cheap e una persistenza di seeing degradato. Su cieli buoni può non scattare mai per ore." % B("\"L'esposizione non si alza mai\""),
    "%s: NINA non riceve l'evento di settle finché PHD2 stesso non lo dichiara. L'Agente lavora sotto PHD2, non sopra NINA." % B("\"NINA non scatta finché RMS non scende sotto soglia\""),
    "%s: è la regola \"tightest-wins\" — l'Agente non concede mai reattività al peggioramento del cielo. È una scelta di design, non un limite." % B("\"Il refresh non applica mai una baseline più larga\""),
]))

# ---------- GLOSSARIO RAPIDO (solo PDF — appendice per beta tester) ----------
S(Spacer(1,6))
S(SectionHeader("Glossario rapido", ACCENT2))
S(HRFlowable(width="100%", thickness=0.6, color=LINEC, spaceAfter=8))
S(Paragraph(
    "I termini più ricorrenti che incontri nella dashboard, nei log e nelle conversazioni della community. "
    "Sono tutti definiti inline nel manuale, ma averli riuniti qui è utile come riferimento veloce.", body))

gloss_rows = [
    [Paragraph(B("Termine"), small), Paragraph(B("Cosa significa"), small)],
    [Paragraph(B("Aggressività"), small),
     Paragraph("Quanto PHD2 reagisce a una correzione di guida. Alta = molto reattivo, ottima in cielo perfetto ma pericolosa in turbolenza (rincorre il rumore). L'Agente la abbassa quando il seeing peggiora.", small)],
    [Paragraph(B("MinMove"), small),
     Paragraph("Soglia minima (in pixel) sotto la quale PHD2 ignora i movimenti della stella. Bassa = corregge anche micro-spostamenti, alta = ignora più rumore. L'Agente la alza in seeing degradato per non rincorrere la turbolenza.", small)],
    [Paragraph(B("Baseline"), small),
     Paragraph("Mediana dell'RMS misurato in condizione NOMINAL stabile sui primi 60 frame buoni. È il punto di riferimento da cui l'Agente deriva le soglie rms_high e rms_low della tua sessione.", small)],
    [Paragraph(B("Cap"), small),
     Paragraph("Tetto fisso a 1 arcsec sulla soglia rms_high derivata dalla baseline. Il riferimento universale di \"guida pulita\" indipendente dal setup, OAG o cercatore-guida che sia. Se la soglia derivata supera 1\", viene tagliata al cap (badge CAP ATTIVO).", small)],
    [Paragraph(B("Escalation gate"), small),
     Paragraph("\"Cancello\" che si apre solo quando aggressività e MinMove sono entrambe sature da almeno un cooldown. Finché è chiuso, l'esposizione resta al valore base. È il meccanismo che garantisce la gerarchia \"prima le leve leggere, poi quella pesante\".", small)],
    [Paragraph(B("Tightest-wins"), small),
     Paragraph("Regola del refresh ciclico: ogni 30 minuti la baseline viene ri-misurata e applicata SOLO se più stretta della corrente. L'Agente si adatta se il cielo migliora, non concede mai terreno se peggiora.", small)],
    [Paragraph(B("NOMINAL / BOOSTED_FOR_SNR / BOOSTED_FOR_SEEING"), small),
     Paragraph("I tre stati della macchina esposizione. NOMINAL = posa al valore base. BOOSTED_FOR_SNR = posa raddoppiata perché la stella è debole. BOOSTED_FOR_SEEING = posa alzata per gradini ×1,5 per mediare la turbolenza.", small)],
    [Paragraph(B("Baseline Guardian"), small),
     Paragraph("Sistema di salvaguardia: alla partenza salva i parametri PHD2 originali e li ripristina alla chiusura pulita (Ctrl+C) o quando rileva una baseline.json orfana di una sessione crashata. Garantisce che l'Agente non lasci mai PHD2 in uno stato modificato che tu non hai voluto.", small)],
]
gloss_tbl = Table(gloss_rows, colWidths=[55*mm, 108*mm])
gloss_tbl.setStyle(TableStyle([
    ("BACKGROUND",(0,0),(-1,0),ACCENT2),
    ("TEXTCOLOR",(0,0),(-1,0),colors.white),("FONTNAME",(0,0),(-1,0),"DJB"),
    ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,BGCARD]),
    ("LINEBELOW",(0,0),(-1,-1),0.4,LINEC),("BOX",(0,0),(-1,-1),0.5,LINEC),
    ("VALIGN",(0,0),(-1,-1),"TOP"),
    ("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6),
    ("LEFTPADDING",(0,0),(-1,-1),7),("RIGHTPADDING",(0,0),(-1,-1),7),
]))
S(gloss_tbl)

S(Spacer(1,6))
S(callout("NOTA FINALE", ACCENT,
    "Se hai qualsiasi domanda scrivi nel gruppo Telegram %s" % __contact_telegram__))

# ---------- DOC ----------
def on_page(canvas, doc):
    canvas.saveState()
    canvas.setFont("DJ",8); canvas.setFillColor(MUTED)
    if doc.page > 1:
        canvas.drawString(20*mm, 12*mm, f"{__project_name__} - Manuale Utente v{__version__}")
        canvas.drawRightString(190*mm, 12*mm, "pag. %d" % doc.page)
        canvas.setStrokeColor(LINEC); canvas.setLineWidth(0.4)
        canvas.line(20*mm,15*mm,190*mm,15*mm)
    canvas.restoreState()

# §26: path output relativo a questo script (doc/Manuale_Utente_Agent.pdf nel repo);
# override possibile via argv[1].
import sys as _sys2
_THIS_DIR = _os.path.dirname(_os.path.abspath(__file__))
if len(_sys2.argv) > 1:
    OUT = _sys2.argv[1]
else:
    OUT = _os.path.join(_THIS_DIR, "Manuale_Utente_Agent.pdf")

# §26: metadata PDF dal modulo __about__ (single source of truth del branding).
doc = BaseDocTemplate(
    OUT, pagesize=A4,
    leftMargin=20*mm, rightMargin=20*mm, topMargin=18*mm, bottomMargin=18*mm,
    title=f"{__project_name__} - Manuale Utente v{__version__}",
    author=__author__,
    subject=f"Manuale utente per astrofotografi - {__project_name__}",
    creator=f"{__project_name__} v{__version__}",
    keywords="PHD2, autoguida, astrofotografia, adaptive agent",
)
frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="main")
doc.addPageTemplates([PageTemplate(id="t", frames=[frame], onPage=on_page)])
doc.build(story)
print("PDF creato:", OUT)
