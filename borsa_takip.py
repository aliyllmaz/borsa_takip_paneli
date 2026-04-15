import tkinter as tk
from tkinter import messagebox
import yfinance as yf
import threading
import pandas as pd
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from datetime import datetime
import pytz
import json
import os

# ─────────────────────────────────────────────────────────────
# AYARLAR
# ─────────────────────────────────────────────────────────────
AYARLAR_DOSYASI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ayarlar.json")

VARSAYILAN_TAKIP = {
    "BIST 100":    "XU100.IS",
    "DOLAR":       "TRY=X",
    "EURO":        "EURTRY=X",
    "ALTIN (ONS)": "GC=F",
    "GRAM ALTIN":  "HESAPLA",
    "THY":         "THYAO.IS",
    "ASELSAN":     "ASELS.IS",
    "BITCOIN":     "BTC-USD",
    "ETHEREUM":    "ETH-USD",
    "NASDAQ 100":  "^NDX",
}

GUNCELLEME_HIZI = 30  # saniye

ZAMAN_DILIMLERI = {
    "1G":  {"period": "1d",  "interval": "5m"},
    "5G":  {"period": "5d",  "interval": "90m"},
    "1A":  {"period": "1mo", "interval": "1d"},
    "3A":  {"period": "3mo", "interval": "1wk"},
    "1Y":  {"period": "1y",  "interval": "1wk"},
}

# Piyasa saatleri (UTC)
PIYASALAR = {
    "BIST":   {"tz": "Europe/Istanbul",   "ac": (10, 0),  "kapat": (18, 0),  "haftasonu": False},
    "NYSE":   {"tz": "America/New_York",  "ac": (9,  30), "kapat": (16, 0),  "haftasonu": False},
    "KRIPTO": {"tz": "UTC",               "ac": (0,  0),  "kapat": (23, 59), "haftasonu": True},
}

BUYUK_SAYILAR = {"GRAM ALTIN", "ALTIN (ONS)", "BITCOIN", "ETHEREUM", "BIST 100", "NASDAQ 100"}

# ─────────────────────────────────────────────────────────────
# RENKLER
# ─────────────────────────────────────────────────────────────
ANA_ARKA_PLAN = "#000000"
KUTU_RENGI    = "#0d0d0d"
YAZI_RENGI    = "#ffffff"
YESIL         = "#00e676"
KIRMIZI       = "#ff1744"
MOR           = "#d500f9"
NOTR          = "#9e9e9e"
MAVI          = "#00e5ff"
ALARM_RENK    = "#ff6d00"
SARI          = "#ffd600"

# ─────────────────────────────────────────────────────────────
# YARDIMCI FONKSİYONLAR
# ─────────────────────────────────────────────────────────────
def ayarlar_yukle():
    if os.path.exists(AYARLAR_DOSYASI):
        try:
            with open(AYARLAR_DOSYASI, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"alarmlar": {}, "secili_zaman": "5G", "portfolyo": {}}


def ayarlar_kaydet(ayarlar):
    try:
        with open(AYARLAR_DOSYASI, "w", encoding="utf-8") as f:
            json.dump(ayarlar, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Ayarlar kaydedilemedi: {e}")


def piyasa_durumu(piyasa_adi):
    """Piyasanın açık/kapalı olduğunu döndürür."""
    try:
        p = PIYASALAR[piyasa_adi]
        tz   = pytz.timezone(p["tz"])
        simdi = datetime.now(tz)
        hafta_gunu = simdi.weekday()  # 0=Pzt, 6=Paz

        if not p["haftasonu"] and hafta_gunu >= 5:
            return False

        ac_h, ac_m      = p["ac"]
        kapat_h, kapat_m = p["kapat"]
        ac_dk    = ac_h * 60 + ac_m
        kapat_dk = kapat_h * 60 + kapat_m
        simdi_dk  = simdi.hour * 60 + simdi.minute
        return ac_dk <= simdi_dk <= kapat_dk
    except Exception:
        return None


def fiyat_formatla(isim, fiyat):
    if isim in BUYUK_SAYILAR:
        return f"{fiyat:,.0f}"
    if fiyat < 10:
        return f"{fiyat:.4f}"
    return f"{fiyat:.2f}"


def hacim_formatla(hacim):
    try:
        if pd.isna(hacim) or hacim == 0:
            return ""
    except (TypeError, ValueError):
        return ""
    if hacim >= 1_000_000_000:
        return f"Vol: {hacim/1e9:.2f}Mlyr"
    if hacim >= 1_000_000:
        return f"Vol: {hacim/1e6:.2f}M"
    if hacim >= 1_000:
        return f"Vol: {hacim/1e3:.1f}B"
    return f"Vol: {int(hacim)}"


# ─────────────────────────────────────────────────────────────
# ANA UYGULAMA
# ─────────────────────────────────────────────────────────────
class BorsaPaneli:
    def __init__(self, root):
        self.root = root
        self.root.title("Borsa Takip v3")
        self.root.configure(bg=ANA_ARKA_PLAN)
        self.root.attributes("-fullscreen", True)
        self.root.bind("<Escape>", lambda e: self.root.destroy())

        self.ayarlar       = ayarlar_yukle()
        self.secili_zaman  = tk.StringVar(value=self.ayarlar.get("secili_zaman", "5G"))
        self.alarmlar      = self.ayarlar.get("alarmlar", {})
        self.portfolyo     = self.ayarlar.get("portfolyo", {})
        # portfolyo yapısı: {"DOLAR": {"adet": 1000, "maliyet": 32.50}, ...}

        self.son_fiyatlar  = {}
        self.alarm_aktif   = {}

        self._ust_panel()
        self._piyasa_panel()
        self._izgara()
        self._alt_panel()
        self._portfolyo_panel()

        self.saati_guncelle()
        self.piyasa_guncelle()
        self.verileri_baslat()

    # ─────────────────────────────────────────────
    # ÜST PANEL — başlık + saatler + zaman butonları
    # ─────────────────────────────────────────────
    def _ust_panel(self):
        ust = tk.Frame(self.root, bg=ANA_ARKA_PLAN)
        ust.pack(fill="x", padx=15, pady=(8, 0))

        tk.Label(ust, text="📈 PİYASA TAKİP v3",
                 font=("Arial", 18, "bold"), fg="cyan", bg=ANA_ARKA_PLAN).pack(side="left")

        # Sağ: saatler
        saat_frame = tk.Frame(ust, bg=ANA_ARKA_PLAN)
        saat_frame.pack(side="right")
        self.yerel_saat_lbl = tk.Label(saat_frame, text="TR: --:--:--",
                                        font=("Consolas", 15, "bold"), fg="yellow", bg=ANA_ARKA_PLAN)
        self.yerel_saat_lbl.pack(side="left", padx=8)
        self.ny_saat_lbl = tk.Label(saat_frame, text="NY: --:--",
                                     font=("Consolas", 15, "bold"), fg="orange", bg=ANA_ARKA_PLAN)
        self.ny_saat_lbl.pack(side="left", padx=8)

        # Orta: zaman butonları
        zaman_frame = tk.Frame(ust, bg=ANA_ARKA_PLAN)
        zaman_frame.pack(side="left", padx=25)
        tk.Label(zaman_frame, text="GRAFİK:", font=("Verdana", 8),
                 fg=NOTR, bg=ANA_ARKA_PLAN).pack(side="left", padx=(0, 4))
        self.zaman_butonlari = {}
        for z in ZAMAN_DILIMLERI:
            btn = tk.Button(zaman_frame, text=z, font=("Consolas", 10, "bold"),
                            width=4, relief="flat", cursor="hand2",
                            command=lambda z=z: self.zaman_degistir(z))
            btn.pack(side="left", padx=2)
            self.zaman_butonlari[z] = btn
        self._zaman_buton_guncelle()

    # ─────────────────────────────────────────────
    # PİYASA DURUM PANEL — BIST / NYSE / Kripto
    # ─────────────────────────────────────────────
    def _piyasa_panel(self):
        self.piyasa_frame = tk.Frame(self.root, bg=ANA_ARKA_PLAN)
        self.piyasa_frame.pack(fill="x", padx=15, pady=(3, 0))

        self.piyasa_lbls = {}
        piyasa_bilgi = {
            "BIST":   "🇹🇷 BIST",
            "NYSE":   "🇺🇸 NYSE",
            "KRIPTO": "₿ KRİPTO",
        }
        for anahtar, etiket in piyasa_bilgi.items():
            cerceve = tk.Frame(self.piyasa_frame, bg="#111111",
                               highlightthickness=1, highlightbackground="#222222")
            cerceve.pack(side="left", padx=4, pady=2)
            lbl = tk.Label(cerceve, text=f"{etiket}  ···",
                           font=("Consolas", 10, "bold"), fg=NOTR, bg="#111111",
                           padx=10, pady=2)
            lbl.pack()
            self.piyasa_lbls[anahtar] = lbl

    def piyasa_guncelle(self):
        for anahtar, lbl in self.piyasa_lbls.items():
            durum = piyasa_durumu(anahtar)
            isim_map = {"BIST": "🇹🇷 BIST", "NYSE": "🇺🇸 NYSE", "KRIPTO": "₿ KRİPTO"}
            isim = isim_map[anahtar]
            if durum is True:
                lbl.config(text=f"{isim}  ● AÇIK", fg=YESIL)
            elif durum is False:
                lbl.config(text=f"{isim}  ● KAPALI", fg=KIRMIZI)
            else:
                lbl.config(text=f"{isim}  ● ?", fg=NOTR)
        self.root.after(60_000, self.piyasa_guncelle)

    # ─────────────────────────────────────────────
    # ANA IZGARA — fiyat kutuları
    # ─────────────────────────────────────────────
    def _izgara(self):
        self.container = tk.Frame(self.root, bg=ANA_ARKA_PLAN)
        self.container.pack(expand=True, fill="both", padx=15, pady=4)
        self.bilesenler = {}

        n = len(VARSAYILAN_TAKIP)
        COL_COUNT = 5 if n >= 10 else (4 if n > 6 else 3)
        row, col = 0, 0

        for isim in VARSAYILAN_TAKIP:
            kutu = tk.Frame(self.container, bg=KUTU_RENGI, bd=0,
                            highlightthickness=1, highlightbackground="#2a2a2a")
            kutu.grid(row=row, column=col, sticky="nsew", padx=4, pady=3)

            # Başlık satırı
            baslik = tk.Frame(kutu, bg=KUTU_RENGI)
            baslik.pack(fill="x", padx=5, pady=(3, 0))
            tk.Label(baslik, text=isim, font=("Verdana", 8, "bold"),
                     fg="#666666", bg=KUTU_RENGI).pack(side="left")

            # Hata ikonu
            hata_ikon = tk.Label(baslik, text="", font=("Arial", 9),
                                  fg="#ff4444", bg=KUTU_RENGI)
            hata_ikon.pack(side="right", padx=1)

            # Alarm ikonu
            alarm_ikon = tk.Label(baslik, text="＋", font=("Arial", 9),
                                   fg="#333333", bg=KUTU_RENGI, cursor="hand2")
            alarm_ikon.pack(side="right", padx=2)
            alarm_ikon.bind("<Button-1>", lambda e, n=isim: self.alarm_duzenle(n))

            # Portföy ikonu
            pf_ikon = tk.Label(baslik, text="💼", font=("Arial", 9),
                                fg="#333333", bg=KUTU_RENGI, cursor="hand2")
            pf_ikon.pack(side="right", padx=2)
            pf_ikon.bind("<Button-1>", lambda e, n=isim: self.portfolyo_duzenle(n))

            fiyat_lbl = tk.Label(kutu, text="···", font=("Impact", 24),
                                  fg=YAZI_RENGI, bg=KUTU_RENGI)
            fiyat_lbl.pack()

            yuzde_lbl = tk.Label(kutu, text="···", font=("Arial", 10, "bold"),
                                  fg=YAZI_RENGI, bg=KUTU_RENGI)
            yuzde_lbl.pack()

            # Portföy kâr/zarar satırı
            pf_lbl = tk.Label(kutu, text="", font=("Consolas", 8),
                               fg=NOTR, bg=KUTU_RENGI)
            pf_lbl.pack()

            hacim_lbl = tk.Label(kutu, text="", font=("Consolas", 8),
                                  fg="#444444", bg=KUTU_RENGI)
            hacim_lbl.pack()

            # Grafik
            fig = Figure(figsize=(2.6, 1.0), dpi=65, facecolor=KUTU_RENGI)
            ax  = fig.add_subplot(111)
            ax.set_facecolor(KUTU_RENGI)
            ax.axis("off")
            fig.subplots_adjust(left=0, right=1, top=1, bottom=0)

            canvas = FigureCanvasTkAgg(fig, master=kutu)
            canvas.get_tk_widget().pack(fill="both", expand=True, padx=3, pady=(0, 0))

            # Min/Max etiket satırı — grafiğin altında, kutucuk içinde
            minmax_frame = tk.Frame(kutu, bg=KUTU_RENGI)
            minmax_frame.pack(fill="x", padx=4, pady=(0, 3))
            min_lbl = tk.Label(minmax_frame, text="", font=("Consolas", 9, "bold"),
                                fg=KIRMIZI, bg=KUTU_RENGI, anchor="w")
            min_lbl.pack(side="left")
            max_lbl = tk.Label(minmax_frame, text="", font=("Consolas", 9, "bold"),
                                fg=YESIL, bg=KUTU_RENGI, anchor="e")
            max_lbl.pack(side="right")

            self.bilesenler[isim] = {
                "fiyat": fiyat_lbl, "yuzde": yuzde_lbl,
                "hacim": hacim_lbl, "pf": pf_lbl,
                "kutu": kutu, "ax": ax, "canvas": canvas, "fig": fig,
                "alarm_ikon": alarm_ikon, "pf_ikon": pf_ikon,
                "hata_ikon": hata_ikon,
                "min_lbl": min_lbl, "max_lbl": max_lbl,
            }

            col += 1
            if col >= COL_COUNT:
                col = 0
                row += 1

        for i in range(COL_COUNT):
            self.container.columnconfigure(i, weight=1)
        for i in range(row + 1):
            self.container.rowconfigure(i, weight=1)

    # ─────────────────────────────────────────────
    # ALT PANEL — durum + geri sayım
    # ─────────────────────────────────────────────
    def _alt_panel(self):
        alt = tk.Frame(self.root, bg="#080808")
        alt.pack(fill="x", padx=15, pady=(0, 3))

        self.durum_lbl = tk.Label(alt, text="⏳ Bekleniyor...",
                                   font=("Consolas", 9), fg=NOTR, bg="#080808")
        self.durum_lbl.pack(side="left", padx=8)

        self.son_guncelleme_lbl = tk.Label(alt, text="",
                                            font=("Consolas", 9), fg="#444444", bg="#080808")
        self.son_guncelleme_lbl.pack(side="left", padx=15)



    # ─────────────────────────────────────────────
    # PORTFÖY PANEL — en altta özet
    # ─────────────────────────────────────────────
    def _portfolyo_panel(self):
        self.pf_ozet_frame = tk.Frame(self.root, bg="#050505")
        self.pf_ozet_frame.pack(fill="x", padx=15, pady=(0, 4))

        self.pf_ozet_lbl = tk.Label(
            self.pf_ozet_frame,
            text="💼  Portföy: veri bekleniyor...",
            font=("Consolas", 9), fg="#555555", bg="#050505"
        )
        self.pf_ozet_lbl.pack(side="left", padx=8)



    # ─────────────────────────────────────────────
    # ZAMAN DİLİMİ
    # ─────────────────────────────────────────────
    def zaman_degistir(self, z):
        self.secili_zaman.set(z)
        self.ayarlar["secili_zaman"] = z
        ayarlar_kaydet(self.ayarlar)
        self._zaman_buton_guncelle()
        self.durum_lbl.config(text=f"🔄 {z} grafikler yükleniyor...", fg="cyan")
        threading.Thread(target=self.veri_cek, daemon=True).start()

    def _zaman_buton_guncelle(self):
        s = self.secili_zaman.get()
        for z, btn in self.zaman_butonlari.items():
            if z == s:
                btn.config(bg=MAVI, fg="#000000")
            else:
                btn.config(bg="#1a1a1a", fg=NOTR)

    # ─────────────────────────────────────────────
    # HATA İKONU
    # ─────────────────────────────────────────────
    def _hata_ikon_guncelle(self, isim, hata_var, mesaj=""):
        if isim not in self.bilesenler:
            return
        ikon = self.bilesenler[isim]["hata_ikon"]
        if hata_var:
            ikon.config(text="⚠", fg="#ff4444")
            ikon.bind("<Button-1>", lambda e, m=mesaj, n=isim:
                      self._hata_detay_goster(n, m))
        else:
            ikon.config(text="")
            ikon.unbind("<Button-1>")

    def _hata_detay_goster(self, isim, mesaj):
        pencere = tk.Toplevel(self.root)
        pencere.title(f"{isim} — Hata")
        pencere.configure(bg="#111111")
        pencere.geometry("380x130")
        pencere.resizable(False, False)
        pencere.grab_set()

        tk.Label(pencere, text=f"⚠  {isim} verisi alınamadı",
                 font=("Arial", 11, "bold"), fg="#ff4444", bg="#111111").pack(pady=(14, 4))
        tk.Label(pencere, text=mesaj if mesaj else "Bilinmeyen hata",
                 font=("Consolas", 9), fg=NOTR, bg="#111111",
                 wraplength=340).pack(padx=15)
        tk.Label(pencere, text="Bir sonraki güncellemede otomatik tekrar denenecek.",
                 font=("Consolas", 8), fg="#444444", bg="#111111").pack(pady=(6, 0))
        tk.Button(pencere, text="Kapat", bg="#222222", fg="white",
                   font=("Arial", 9), relief="flat", cursor="hand2",
                   command=pencere.destroy).pack(pady=10)

    # ─────────────────────────────────────────────
    # ALARM
    # ─────────────────────────────────────────────
    def alarm_duzenle(self, isim):
        mevcut   = self.alarmlar.get(isim, {})
        son_fiyat = self.son_fiyatlar.get(isim, 0)

        pencere = tk.Toplevel(self.root)
        pencere.title(f"{isim} — Alarm")
        pencere.configure(bg="#111111")
        pencere.geometry("300x185")
        pencere.resizable(False, False)
        pencere.grab_set()

        tk.Label(pencere, text=f"🔔  {isim} Alarm Seviyeleri",
                 font=("Arial", 11, "bold"), fg="cyan", bg="#111111").pack(pady=(12, 3))
        if son_fiyat:
            tk.Label(pencere, text=f"Güncel: {fiyat_formatla(isim, son_fiyat)}",
                     font=("Consolas", 9), fg=NOTR, bg="#111111").pack()

        fr = tk.Frame(pencere, bg="#111111")
        fr.pack(pady=8)

        tk.Label(fr, text="↑ Üst:", font=("Arial", 10), fg=YESIL, bg="#111111").grid(
            row=0, column=0, sticky="e", padx=8, pady=3)
        ust_e = tk.Entry(fr, width=13, bg="#1e1e1e", fg="white",
                          font=("Consolas", 11), insertbackground="white")
        ust_e.grid(row=0, column=1)
        if mevcut.get("ust"):
            ust_e.insert(0, str(mevcut["ust"]))

        tk.Label(fr, text="↓ Alt:", font=("Arial", 10), fg=KIRMIZI, bg="#111111").grid(
            row=1, column=0, sticky="e", padx=8, pady=3)
        alt_e = tk.Entry(fr, width=13, bg="#1e1e1e", fg="white",
                          font=("Consolas", 11), insertbackground="white")
        alt_e.grid(row=1, column=1)
        if mevcut.get("alt"):
            alt_e.insert(0, str(mevcut["alt"]))

        bf = tk.Frame(pencere, bg="#111111")
        bf.pack()

        def kaydet():
            try:
                ust_v = float(ust_e.get()) if ust_e.get().strip() else None
                alt_v = float(alt_e.get()) if alt_e.get().strip() else None
                self.alarmlar[isim] = {"ust": ust_v, "alt": alt_v}
                self.ayarlar["alarmlar"] = self.alarmlar
                ayarlar_kaydet(self.ayarlar)
                self._alarm_ikon_guncelle(isim)
                pencere.destroy()
            except ValueError:
                messagebox.showerror("Hata", "Geçerli bir sayı girin.", parent=pencere)

        def sil():
            self.alarmlar.pop(isim, None)
            self.alarm_aktif.pop(isim, None)
            self.ayarlar["alarmlar"] = self.alarmlar
            ayarlar_kaydet(self.ayarlar)
            self._alarm_ikon_guncelle(isim)
            pencere.destroy()

        tk.Button(bf, text="✔ Kaydet", bg=YESIL, fg="black",
                   font=("Arial", 9, "bold"), relief="flat", cursor="hand2",
                   command=kaydet).pack(side="left", padx=5, pady=6)
        tk.Button(bf, text="🗑 Sil", bg=KIRMIZI, fg="white",
                   font=("Arial", 9, "bold"), relief="flat", cursor="hand2",
                   command=sil).pack(side="left", padx=5)

    def _alarm_ikon_guncelle(self, isim):
        if isim not in self.bilesenler:
            return
        alarm  = self.alarmlar.get(isim, {})
        aktif  = self.alarm_aktif.get(isim, False)
        ikon   = self.bilesenler[isim]["alarm_ikon"]
        if aktif:
            ikon.config(text="🔔", fg=ALARM_RENK)
        elif alarm.get("ust") or alarm.get("alt"):
            ikon.config(text="🔕", fg="#555555")
        else:
            ikon.config(text="＋", fg="#333333")

    def _alarm_kontrol(self, isim, fiyat):
        alarm = self.alarmlar.get(isim)
        if not alarm:
            self.alarm_aktif[isim] = False
            return False
        ust, alt = alarm.get("ust"), alarm.get("alt")
        tetiklendi = (ust and fiyat >= ust) or (alt and fiyat <= alt)
        self.alarm_aktif[isim] = bool(tetiklendi)
        return bool(tetiklendi)

    # ─────────────────────────────────────────────
    # PORTFÖY
    # ─────────────────────────────────────────────
    def portfolyo_duzenle(self, isim):
        mevcut   = self.portfolyo.get(isim, {})
        son_fiyat = self.son_fiyatlar.get(isim, 0)

        pencere = tk.Toplevel(self.root)
        pencere.title(f"{isim} — Portföy")
        pencere.configure(bg="#111111")
        pencere.geometry("300x200")
        pencere.resizable(False, False)
        pencere.grab_set()

        tk.Label(pencere, text=f"💼  {isim} Portföy Girişi",
                 font=("Arial", 11, "bold"), fg="cyan", bg="#111111").pack(pady=(12, 3))
        if son_fiyat:
            tk.Label(pencere, text=f"Güncel fiyat: {fiyat_formatla(isim, son_fiyat)}",
                     font=("Consolas", 9), fg=NOTR, bg="#111111").pack()

        fr = tk.Frame(pencere, bg="#111111")
        fr.pack(pady=8)

        tk.Label(fr, text="Adet / Miktar:", font=("Arial", 10), fg=SARI, bg="#111111").grid(
            row=0, column=0, sticky="e", padx=8, pady=4)
        adet_e = tk.Entry(fr, width=13, bg="#1e1e1e", fg="white",
                           font=("Consolas", 11), insertbackground="white")
        adet_e.grid(row=0, column=1)
        if mevcut.get("adet"):
            adet_e.insert(0, str(mevcut["adet"]))

        tk.Label(fr, text="Ort. Maliyet:", font=("Arial", 10), fg=SARI, bg="#111111").grid(
            row=1, column=0, sticky="e", padx=8, pady=4)
        maliyet_e = tk.Entry(fr, width=13, bg="#1e1e1e", fg="white",
                              font=("Consolas", 11), insertbackground="white")
        maliyet_e.grid(row=1, column=1)
        if mevcut.get("maliyet"):
            maliyet_e.insert(0, str(mevcut["maliyet"]))

        # Anlık kâr/zarar önizleme
        onizleme_lbl = tk.Label(pencere, text="", font=("Consolas", 9), bg="#111111")
        onizleme_lbl.pack()

        def onizle(*_):
            try:
                a = float(adet_e.get())
                m = float(maliyet_e.get())
                if son_fiyat and m > 0:
                    kz   = (son_fiyat - m) * a
                    yuzde = ((son_fiyat - m) / m) * 100
                    renk = YESIL if kz >= 0 else KIRMIZI
                    isaret = "+" if kz >= 0 else ""
                    onizleme_lbl.config(
                        text=f"K/Z: {isaret}{kz:,.2f}  ({isaret}{yuzde:.2f}%)",
                        fg=renk)
            except ValueError:
                onizleme_lbl.config(text="")

        adet_e.bind("<KeyRelease>", onizle)
        maliyet_e.bind("<KeyRelease>", onizle)
        onizle()

        bf = tk.Frame(pencere, bg="#111111")
        bf.pack()

        def kaydet():
            try:
                a = float(adet_e.get())
                m = float(maliyet_e.get())
                self.portfolyo[isim] = {"adet": a, "maliyet": m}
                self.ayarlar["portfolyo"] = self.portfolyo
                ayarlar_kaydet(self.ayarlar)
                self._portfolyo_kutu_guncelle(isim)
                self._portfolyo_ozet_guncelle()
                pencere.destroy()
            except ValueError:
                messagebox.showerror("Hata", "Geçerli sayılar girin.", parent=pencere)

        def sil():
            self.portfolyo.pop(isim, None)
            self.ayarlar["portfolyo"] = self.portfolyo
            ayarlar_kaydet(self.ayarlar)
            self._portfolyo_kutu_guncelle(isim)
            self._portfolyo_ozet_guncelle()
            pencere.destroy()

        tk.Button(bf, text="✔ Kaydet", bg=YESIL, fg="black",
                   font=("Arial", 9, "bold"), relief="flat", cursor="hand2",
                   command=kaydet).pack(side="left", padx=5, pady=6)
        tk.Button(bf, text="🗑 Sil", bg=KIRMIZI, fg="white",
                   font=("Arial", 9, "bold"), relief="flat", cursor="hand2",
                   command=sil).pack(side="left", padx=5)

    def _portfolyo_kutu_guncelle(self, isim):
        """Tek bir kutunun portföy satırını güncelle."""
        if isim not in self.bilesenler:
            return
        pf  = self.portfolyo.get(isim)
        lbl = self.bilesenler[isim]["pf"]
        ikon = self.bilesenler[isim]["pf_ikon"]

        if not pf:
            lbl.config(text="")
            ikon.config(fg="#333333")
            return

        son_fiyat = self.son_fiyatlar.get(isim)
        if not son_fiyat:
            lbl.config(text=f"💼 {pf['adet']} × {pf['maliyet']}", fg="#555555")
            return

        kz     = (son_fiyat - pf["maliyet"]) * pf["adet"]
        yuzde  = ((son_fiyat - pf["maliyet"]) / pf["maliyet"]) * 100
        renk   = YESIL if kz >= 0 else KIRMIZI
        isaret = "+" if kz >= 0 else ""
        lbl.config(text=f"💼 {isaret}{kz:,.0f} ({isaret}{yuzde:.1f}%)", fg=renk)
        ikon.config(fg=renk)

    def _portfolyo_ozet_guncelle(self):
        """Alt bardaki toplam portföy özetini güncelle."""
        if not self.portfolyo:
            self.pf_ozet_lbl.config(text="💼  Portföy: — (💼 butonuna tıklayarak ekleyin)",
                                     fg="#444444")
            return

        toplam_maliyet = 0.0
        toplam_deger   = 0.0
        eksik_veri     = []

        for isim, pf in self.portfolyo.items():
            fiyat = self.son_fiyatlar.get(isim)
            if fiyat is None:
                eksik_veri.append(isim)
                continue
            toplam_maliyet += pf["maliyet"] * pf["adet"]
            toplam_deger   += fiyat         * pf["adet"]

        if toplam_maliyet == 0:
            self.pf_ozet_lbl.config(text="💼  Portföy: veri bekleniyor...", fg="#444444")
            return

        toplam_kz  = toplam_deger - toplam_maliyet
        yuzde      = (toplam_kz / toplam_maliyet) * 100
        renk       = YESIL if toplam_kz >= 0 else KIRMIZI
        isaret     = "+" if toplam_kz >= 0 else ""
        ozet_metin = (
            f"💼  Portföy  |  "
            f"Maliyet: {toplam_maliyet:,.0f}  "
            f"Güncel: {toplam_deger:,.0f}  "
            f"K/Z: {isaret}{toplam_kz:,.0f} ({isaret}{yuzde:.2f}%)"
        )
        if eksik_veri:
            ozet_metin += f"  · Beklenen: {', '.join(eksik_veri)}"

        self.pf_ozet_lbl.config(text=ozet_metin, fg=renk)

    # ─────────────────────────────────────────────
    # SAAT
    # ─────────────────────────────────────────────
    def saati_guncelle(self):
        self.yerel_saat_lbl.config(text=f"TR: {datetime.now().strftime('%H:%M:%S')}")
        try:
            ny = datetime.now(pytz.timezone('America/New_York')).strftime("%H:%M")
            self.ny_saat_lbl.config(text=f"NY: {ny}")
        except Exception:
            pass
        self.root.after(1000, self.saati_guncelle)

    # ─────────────────────────────────────────────
    # VERİ ÇEKME
    # ─────────────────────────────────────────────
    def verileri_baslat(self):
        threading.Thread(target=self.veri_cek, daemon=True).start()
        self.root.after(GUNCELLEME_HIZI * 1000, self.verileri_baslat)

    def veri_cek(self):
        self.root.after(0, self.durum_lbl.config,
                        {"text": "🔄 Güncelleniyor...", "fg": "cyan"})

        zaman    = self.secili_zaman.get()
        period   = ZAMAN_DILIMLERI[zaman]["period"]
        interval = ZAMAN_DILIMLERI[zaman]["interval"]

        for isim, sembol in VARSAYILAN_TAKIP.items():
            try:
                if sembol == "HESAPLA":
                    # Daha geniş period çek, sonra keseriz
                    dl_map = {"1d": "1mo", "5d": "3mo", "1mo": "6mo",
                              "3mo": "1y", "1y": "2y"}
                    dl_period = dl_map.get(period, "1y")

                    # USDTRY=X — TRY=X'e göre daha kararlı
                    ons_raw = yf.Ticker("GC=F").history(period=dl_period, interval="1d")
                    dol_raw = yf.Ticker("USDTRY=X").history(period=dl_period, interval="1d")

                    # TRY=X dene, USDTRY boşsa
                    if dol_raw.empty:
                        dol_raw = yf.Ticker("TRY=X").history(period=dl_period, interval="1d")

                    if ons_raw.empty or dol_raw.empty:
                        self.root.after(0, self._hata_ikon_guncelle, isim, True, "Veri yetersiz")
                        continue

                    # Timezone tamamen kaldır, sadece tarihi tut
                    def idx_normalize(df_):
                        idx = df_.index
                        if hasattr(idx, "tz") and idx.tz is not None:
                            idx = idx.tz_convert("UTC").tz_localize(None)
                        return df_.set_index(idx.normalize())

                    ons_raw = idx_normalize(ons_raw)
                    dol_raw = idx_normalize(dol_raw)

                    # Her iki seriden sadece Close al, tarihe göre inner join
                    ons_s = ons_raw["Close"].rename("ons")
                    dol_s = dol_raw["Close"].rename("dolar")

                    # merge_asof: en yakın tarihi eşleştir (1 gün tolerans)
                    ons_df  = ons_s.reset_index()
                    dol_df  = dol_s.reset_index()
                    ons_df  = ons_df.sort_values("Date")
                    dol_df  = dol_df.sort_values("Date")

                    merged = pd.merge_asof(
                        ons_df, dol_df,
                        on="Date",
                        tolerance=pd.Timedelta("2d"),
                        direction="nearest"
                    ).dropna()

                    if merged.empty:
                        self.root.after(0, self._hata_ikon_guncelle, isim, True, "Veri eşleştirilemedi")
                        continue

                    merged = merged.set_index("Date")
                    merged["gram"] = (merged["ons"] * merged["dolar"]) / 31.1035

                    # Seçilen döneme göre kes
                    kesim_map = {"1d": 2, "5d": 7, "1mo": 31, "3mo": 92, "1y": 366}
                    gun = kesim_map.get(period, 92)
                    kesim = pd.Timestamp.now() - pd.Timedelta(days=gun)
                    grafik_df = merged[merged.index >= kesim]["gram"]

                    # 3A ve 1Y için haftalık özetle
                    if period in ("3mo", "1y"):
                        grafik_df = grafik_df.resample("1W").last().dropna()

                    if grafik_df.empty:
                        self.root.after(0, self._hata_ikon_guncelle, isim, True, "Dönem verisi boş")
                        continue

                    son = grafik_df.iloc[-1]

                    # Günlük değişim
                    if len(merged) >= 2:
                        prev = merged["gram"].iloc[-2]
                        degisim = ((son - prev) / prev) * 100 if prev != 0 else 0.0
                    else:
                        degisim = 0.0

                    self.root.after(0, self.gorseli_yenile,
                                    isim, son, degisim, grafik_df.tolist(), 0)
                    self.root.after(0, self._hata_ikon_guncelle, isim, False)
                    continue

                ticker = yf.Ticker(sembol)
                hist   = ticker.history(period=period, interval=interval)
                if hist.empty:
                    self.root.after(0, self._hata_ikon_guncelle, isim, True, "Veri boş")
                    continue

                son_fiyat     = hist["Close"].iloc[-1]
                grafik_verisi = hist["Close"].tolist()
                hacim         = hist["Volume"].iloc[-1] if "Volume" in hist.columns else 0

                daily   = ticker.history(period="5d")
                degisim = 0.0
                if len(daily) >= 2:
                    prev = daily["Close"].iloc[-2]
                    if prev != 0:
                        degisim = ((son_fiyat - prev) / prev) * 100

                self.root.after(0, self.gorseli_yenile,
                                isim, son_fiyat, degisim, grafik_verisi, hacim)
                self.root.after(0, self._hata_ikon_guncelle, isim, False)

            except Exception as e:
                import traceback
                detay = traceback.format_exc().strip().split("\n")[-1]
                print(f"Hata ({isim}): {detay}")
                self.root.after(0, self._hata_ikon_guncelle, isim, True, detay)

        now = datetime.now().strftime("%H:%M:%S")
        self.root.after(0, self.durum_lbl.config,
                        {"text": "✔ Güncellendi", "fg": YESIL})
        self.root.after(0, self.son_guncelleme_lbl.config,
                        {"text": f"Son güncelleme: {now}"})
        self.root.after(0, self._portfolyo_ozet_guncelle)

    # ─────────────────────────────────────────────
    # GÖRSEL GÜNCELLEME
    # ─────────────────────────────────────────────
    def gorseli_yenile(self, isim, fiyat, degisim, grafik_verisi, hacim=0):
        try:
            comp = self.bilesenler[isim]
            self.son_fiyatlar[isim] = fiyat

            alarm_caldi = self._alarm_kontrol(isim, fiyat)
            self._alarm_ikon_guncelle(isim)

            if alarm_caldi:
                renk, ok = ALARM_RENK, "⚠"
            elif degisim >= 10:
                renk, ok = MOR, "🚀"
            elif degisim > 0:
                renk, ok = YESIL, "▲"
            elif degisim < 0:
                renk, ok = KIRMIZI, "▼"
            else:
                renk, ok = NOTR, "─"

            comp["fiyat"].config(text=fiyat_formatla(isim, fiyat), fg=renk)
            comp["yuzde"].config(text=f"{ok}  %{abs(degisim):.2f}", fg=renk)
            comp["kutu"].config(
                highlightbackground=ALARM_RENK if alarm_caldi else renk,
                highlightthickness=3 if (alarm_caldi or abs(degisim) >= 5) else 1
            )
            comp["hacim"].config(text=hacim_formatla(hacim))

            self._portfolyo_kutu_guncelle(isim)

            # ── Grafik ──
            ax  = comp["ax"]
            fig = comp["fig"]
            ax.clear()
            ax.axis("off")
            ax.set_facecolor(KUTU_RENGI)
            fig.set_facecolor(KUTU_RENGI)
            fig.subplots_adjust(left=0, right=1, top=1, bottom=0)

            if len(grafik_verisi) >= 2:
                x = list(range(len(grafik_verisi)))
                mn_val = min(grafik_verisi)
                ax.fill_between(x, grafik_verisi, mn_val,
                                 alpha=0.12, color=renk)
                ax.plot(x, grafik_verisi, color=renk, linewidth=1.6, alpha=0.9)

                mx_val = max(grafik_verisi)
                mx_idx = grafik_verisi.index(mx_val)
                mn_idx = grafik_verisi.index(mn_val)

                ax.scatter([mx_idx], [mx_val], color=YESIL,  s=22, zorder=5)
                ax.scatter([mn_idx], [mn_val], color=KIRMIZI, s=22, zorder=5)

                fmt = ".0f" if isim in BUYUK_SAYILAR else ".2f"
                comp["min_lbl"].config(text=f"▼ {mn_val:{fmt}}")
                comp["max_lbl"].config(text=f"▲ {mx_val:{fmt}}")
            else:
                comp["min_lbl"].config(text="")
                comp["max_lbl"].config(text="")

            comp["canvas"].draw()

        except Exception as e:
            print(f"Görsel hata ({isim}): {e}")


# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    root = tk.Tk()
    app  = BorsaPaneli(root)
    root.mainloop()
