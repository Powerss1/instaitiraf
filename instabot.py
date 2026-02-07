import os
import time
import json
import random
import sqlite3
import logging
import re
from datetime import datetime, timedelta
from google import genai
import undetected_chromedriver as uc
from PIL import Image, ImageDraw, ImageFont
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# ==========================================
# ⚙️ AYARLAR
# ==========================================
GEMINI_API_KEY = "AIzaSyCrNhfmvwAYsWrD0ZfMcV8ycN0sCFmxSLQ"
SABLON_YOLU = "sablon.png"
FONT_YOLU = "Ubuntu-MediumItalic.ttf"
PROFILE_PATH = os.path.join(os.getcwd(), "chrome_profile")
RED_YIYENLER_KLASORU = os.path.join(os.getcwd(), "Red_yiyenler")
RED_YIYENLER_RESIMLER = os.path.join(RED_YIYENLER_KLASORU, "resimler")

os.makedirs(RED_YIYENLER_KLASORU, exist_ok=True)
os.makedirs(RED_YIYENLER_RESIMLER, exist_ok=True)

POST_SURE_ARALIGI = 600  # 10 dakika
POST_COZUNURLUGU = (1080, 1080)

logging.basicConfig(
    filename='instabot.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

client = genai.Client(api_key=GEMINI_API_KEY)

# ==========================================
# 📊 VERİTABANI
# ==========================================
def db_setup():
    conn = sqlite3.connect("itiraflar.db", check_same_thread=False)
    cursor = conn.cursor()
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS confessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        content TEXT,
        status TEXT DEFAULT 'WAITING',
        created_at TEXT,
        posted_at TEXT,
        rejection_reason TEXT
    )''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS rejected_confessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        content TEXT,
        rejection_reason TEXT,
        created_at TEXT,
        file_path TEXT
    )''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS processed_messages (
        message_hash TEXT PRIMARY KEY,
        processed_at TEXT
    )''')
    
    conn.commit()
    return conn

db_conn = db_setup()

# ==========================================
# 🔤 FİLTRELEME
# ==========================================
KUFUR_KELIMELERI = [
    "amk", "aq", "sg", "siktir", "siktirgit", "piç", "pic", "yarak", "göt", "got",
    "amına", "amina", "bok", "boka", "bokum", "hıyar", "hiyar", "dalyaran",
    "dalahm", "gavat", "orospu", "orosbu", "fahişe", "fahise", "veled",
    "şerefsiz", "serefsiz", "aptal", "salak", "gerizekalı", "gerizekali",
    "kafasız", "kahpe", "hin", "langırt", "zıkkım", "zıkkim"
]

def basit_filtrele(metin):
    metin_lower = metin.lower()
    
    for kelime in KUFUR_KELIMELERI:
        if kelime in metin_lower:
            return False, f"Küfür: {kelime}"
    
    telefon_pattern = r'(\+?\d{1,3}[-.\s]?)?(\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}'
    if re.search(telefon_pattern, metin):
        return False, "Telefon numarası"
    
    tc_pattern = r'\b\d{11}\b'
    if re.search(tc_pattern, metin):
        return False, "TC kimlik"
    
    reklam_kelimeleri = ["whatsapp", "telegram", "discord", "satılık", "kiralık", 
                         "link", "www.", ".com", ".net", " DM at", "dm at",
                         "takip et", "follow", "beğen", "like", "çekiliş",
                         "kampanya", "indirim", "promosyon", "ücretsiz"]
    for kelime in reklam_kelimeleri:
        if kelime in metin_lower:
            return False, f"Reklam: {kelime}"
    
    return True, ""

def mesaji_once_isledi_mi(metin):
    mesaj_hash = hash(metin.strip().lower())
    cursor = db_conn.cursor()
    cursor.execute("SELECT message_hash FROM processed_messages WHERE message_hash = ?", (mesaj_hash,))
    return cursor.fetchone() is not None

def mesaji_islenmis_olarak_isaretle(metin):
    mesaj_hash = hash(metin.strip().lower())
    cursor = db_conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO processed_messages (message_hash, processed_at) VALUES (?, ?)",
                  (mesaj_hash, datetime.now().isoformat()))
    db_conn.commit()

# ==========================================
# 🎨 POST OLUŞTUR
# ==========================================
def post_olustur(itiraf_metni, post_id, is_red=False):
    try:
        font = ImageFont.truetype(FONT_YOLU, 36)
        img = Image.open(SABLON_YOLU)
        draw = ImageDraw.Draw(img)
        W, H = img.size
        
        if is_red:
            baslik = "REDDEDİLDİ"
            baslik_font = ImageFont.truetype(FONT_YOLU, 28)
            baslik_gen = draw.textbbox((0, 0), baslik, font=baslik_font)[2]
            draw.text(((W - baslik_gen) // 2, 350), baslik, fill="red", font=baslik_font)
        
        kelimeler = itiraf_metni.split()
        satirlar = []
        aktif = ""
        for kelime in kelimeler:
            deneme = kelime if not aktif else aktif + " " + kelime
            if draw.textbbox((0, 0), deneme, font=font)[2] <= 680:
                aktif = deneme
            else:
                if aktif:
                    satirlar.append(aktif)
                aktif = kelime
        if aktif:
            satirlar.append(aktif)
        
        y = 430 if not is_red else 480
        for satir in satirlar:
            gen = draw.textbbox((0, 0), satir, font=font)[2]
            draw.text(((W - gen) // 2, y), satir, fill="black", font=font)
            y += (draw.textbbox((0, 0), "Ag", font=font)[3] - draw.textbbox((0, 0), "Ag", font=font)[1]) + 16
        
        if is_red:
            path = os.path.abspath(os.path.join(RED_YIYENLER_RESIMLER, f"red_post_{post_id}.png"))
        else:
            path = os.path.abspath(f"post_{post_id}.png")
        
        img.save(path, quality=95)
        return path
    except Exception as e:
        logging.error(f"Post oluşturma hatası: {e}")
        return None

# ==========================================
# 🧠 AI ANALİZ
# ==========================================
def ai_itiraf_analiz(metin):
    gecerli, sebep = basit_filtrele(metin)
    if not gecerli:
        return {"itiraf_mi": False, "sebep": sebep, "kategori": "REJECTED"}
    
    prompt = f"""Instagram itiraf moderatörüsün. Bu bir itiraf mı?

İTİRAF: kişisel duygu/sır/düşünce, aşk/nefret/pişmanlık, "9A sınıfında Ali" gibi paylaşımlar
RED: "takip et", "selam nasılsın", "link at", sadece emoji, gereksiz mesajlar

Mesaj: "{metin}"

JSON: {{"karar": "ACCEPT veya REJECT", "sebep": "..."}}"""

    try:
        res = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
        clean_text = res.text.replace("```json", "").replace("```", "").strip()
        result = json.loads(clean_text)
        return {
            "itiraf_mi": result.get("karar") == "ACCEPT",
            "sebep": result.get("sebep", ""),
            "kategori": "ACCEPTED" if result.get("karar") == "ACCEPT" else "REJECTED"
        }
    except Exception as e:
        logging.error(f"AI analiz hatası: {e}")
        return {"itiraf_mi": len(metin) > 20, "sebep": "AI hatası", "kategori": "ACCEPTED" if len(metin) > 20 else "REJECTED"}

# ==========================================
# 🤖 BOT SİSTEMİ
# ==========================================
class InstagramBot:
    def __init__(self):
        print("[SİSTEM] Tarayıcı başlatılıyor...")
        self.is_posting = False
        self.driver = self.get_driver()
        self.wait = WebDriverWait(self.driver, 20)
        self.actions = ActionChains(self.driver)
        self.last_post_time = datetime.now() - timedelta(minutes=15)
        self.stats = {"post_count": 0, "dm_count": 0, "rejected_count": 0, "error_count": 0}
        self.son_mesaj = None
        
    def insansi_bekle(self, min_saniye=2, max_saniye=5):
        time.sleep(random.uniform(min_saniye, max_saniye))
    
    def tikla(self, element):
        try:
            self.actions.move_to_element(element).pause(random.uniform(0.2, 0.5)).click().perform()
        except:
            element.click()
            
    def get_driver(self):
        options = uc.ChromeOptions()
        options.add_argument(f"--user-data-dir={PROFILE_PATH}")
        options.add_argument("--start-maximized")
        options.add_argument("--kiosk")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-notifications")
        
        try:
            return uc.Chrome(options=options, version_main=144)
        except:
            new_options = uc.ChromeOptions()
            new_options.add_argument(f"--user-data-dir={PROFILE_PATH}")
            new_options.add_argument("--start-maximized")
            return uc.Chrome(options=new_options)
    
    def dm_kismina_git(self):
        """Sohbet kısmına git"""
        try:
            self.driver.get("https://www.instagram.com/direct/inbox/")
            self.insansi_bekle(4, 6)
            
            # Popup kapat
            try:
                kapat = self.driver.find_element(By.CSS_SELECTOR, "svg[aria-label='Kapat']")
                self.tikla(kapat)
                self.insansi_bekle(1, 2)
            except:
                pass
                
            print("[DM] Sohbet kısmı açıldı.")
            return True
        except Exception as e:
            logging.error(f"DM gitme hatası: {e}")
            return False
    
    def yeni_mesaj_kutularini_bul(self):
        """Yanında KUTUCUK olan mesajları bul (yeni mesaj göstergesi)"""
        try:
            # Yeni mesaj göstergesi (yanındaki mavi nokta/kutucuk)
            # Instagram'da bu genellikle bir span veya div ile gösteriliyor
            
            selectors = [
                # Kutucuk/yeni mesaj göstergesi olan mesajlar
                "div[role='button']:has(span[aria-label='Yeni mesaj'])",
                "div[role='button']:has(div[aria-label*='Okunmamış'])",
                "div[role='button']:has(svg[aria-label='Yeni mesaj'])",
                # Alternatif: unread class'ı olanlar
                "div._ab8w:has(._aa__)",
                "div.x9f619:has(span[aria-label*='Yeni'])",
                # Genel mesaj listesi - her şeyi kontrol et
                "div[role='button'][href*='direct']",
                "a.x1i10hfl[href*='direct/t']",
                # En genel selector
                "div.x1iorvi4.x1pi30zi",
            ]
            
            yeni_mesajlar = []
            
            for selector in selectors:
                try:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    for elem in elements:
                        if elem.is_displayed() and elem.is_enabled():
                            # Benzersiz mi kontrol et
                            try:
                                loc = str(elem.location)
                                if loc not in [str(e.location) for e in yeni_mesajlar]:
                                    yeni_mesajlar.append(elem)
                            except:
                                yeni_mesajlar.append(elem)
                except:
                    continue
            
            # En alttaki mesajları al (en yeni mesajlar genellikle en altta)
            return yeni_mesajlar[-5:] if len(yeni_mesajlar) > 5 else yeni_mesajlar
            
        except Exception as e:
            logging.error(f"Yeni mesaj bulma hatası: {e}")
            return []
    
    def mesaj_icerigini_oku(self):
        """Açık sohbetten mesajı oku"""
        try:
            balon_selectors = [
                "div._ap3a",           # Eski
                "div.x9f619",          # Yeni
                "div.x78zum5",
                "span.x1lliihq",
                "div.x1iorvi4",
                "div[dir='ltr']",
                "div.x6s0dn4",
            ]
            
            for selector in balon_selectors:
                try:
                    balonlar = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    if balonlar:
                        for balon in reversed(balonlar):
                            if balon.is_displayed():
                                text = balon.text.strip()
                                if text and len(text) > 2:
                                    return text
                except:
                    continue
            return None
        except Exception as e:
            logging.error(f"İçerik okuma hatası: {e}")
            return None
    
    def mesaji_isle(self, kutu):
        """Tek bir sohbeti işle"""
        try:
            # Sohbeti aç
            self.tikla(kutu)
            print(f"[DM] Sohbet açıldı, 15 saniye bekleniyor...")
            self.insansi_bekle(15, 15)  # Mesajın yüklenmesi için bekle
            
            # Mesajı oku
            raw_text = self.mesaj_icerigini_oku()
            
            if not raw_text or len(raw_text.strip()) <= 3:
                return False
            
            # Aynı mesajı tekrar okuma
            if raw_text.strip() == self.son_mesaj:
                return False
            
            self.son_mesaj = raw_text.strip()
            print(f"[DM] Mesaj: {raw_text[:80]}...")
            
            # İşlenmiş mi kontrol et
            if mesaji_once_isledi_mi(raw_text):
                print(f"[DM] Zaten işlenmiş, atlanıyor...")
                return False
            
            # AI analiz
            analiz = ai_itiraf_analiz(raw_text)
            
            if analiz["itiraf_mi"]:
                cursor = db_conn.cursor()
                cursor.execute(
                    "INSERT INTO confessions (username, content, status, created_at) VALUES (?, ?, ?, ?)",
                    ("anonim", raw_text.strip(), "WAITING", datetime.now().isoformat())
                )
                db_conn.commit()
                print(f"✅ KABUL: {raw_text[:50]}...")
            else:
                self.reddedilen_kaydet("anonim", raw_text.strip(), analiz["sebep"])
                print(f"❌ RED: {analiz['sebep']} - {raw_text[:50]}...")
                self.stats["rejected_count"] += 1
            
            mesaji_islenmis_olarak_isaretle(raw_text)
            return True
            
        except Exception as e:
            logging.error(f"Mesaj işleme hatası: {e}")
            return False
    
    def reddedilen_kaydet(self, username, content, reason):
        """Reddedilen itirafı kaydet"""
        try:
            post_id = int(datetime.now().timestamp())
            post_yolu = post_olustur(content, post_id, is_red=True)
            
            if post_yolu:
                cursor = db_conn.cursor()
                cursor.execute(
                    "INSERT INTO rejected_confessions (username, content, rejection_reason, created_at, file_path) VALUES (?, ?, ?, ?, ?)",
                    (username, content, reason, datetime.now().isoformat(), post_yolu)
                )
                db_conn.commit()
                
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                log_path = os.path.join(RED_YIYENLER_KLASORU, f"red_{timestamp}.txt")
                with open(log_path, "w", encoding="utf-8") as f:
                    f.write(f"Kullanıcı: {username}\n")
                    f.write(f"Tarih: {datetime.now().isoformat()}\n")
                    f.write(f"Red Sebebi: {reason}\n")
                    f.write(f"Mesaj: {content}\n")
                    f.write(f"Post Yolu: {post_yolu}\n")
                
                print(f"[RED] Kaydedildi: {post_yolu}")
                
        except Exception as e:
            logging.error(f"Red kaydetme hatası: {e}")
    
    def dm_tara(self):
        """Sohbetleri tara ve işle"""
        if self.is_posting:
            return
        
        print(f"\n[DM] [{datetime.now().strftime('%H:%M')}] Sohbetler kontrol ediliyor...")
        
        try:
            # Yanında kutucuk olan (yeni) mesajları bul
            mesajlar = self.yeni_mesaj_kutularini_bul()
            
            if not mesajlar:
                print("[DM] Yeni mesaj yok (kutucuk olan yok).")
                self.stats["dm_count"] += 1
                return
            
            print(f"[DM] {len(mesajlar)} yeni sohbet bulundu.")
            
            islenen = 0
            for kutu in mesajlar:
                if self.mesaji_isle(kutu):
                    islenen += 1
                if islenen >= 5:  # En fazla 5 mesaj
                    break
                self.insansi_bekle(1, 2)
            
            print(f"[DM] {islenen} mesaj işlendi.")
            
        except Exception as e:
            logging.error(f"DM tarama hatası: {e}")
            self.stats["error_count"] += 1
    
    def post_at(self):
        """İtiraf post et"""
        if self.is_posting:
            return
        
        if datetime.now() - self.last_post_time < timedelta(seconds=POST_SURE_ARALIGI):
            return
        
        self.is_posting = True
        print(f"\n[POST] [{datetime.now().strftime('%H:%M')}] Post atılıyor...")
        
        try:
            cursor = db_conn.cursor()
            cursor.execute("SELECT id, content FROM confessions WHERE status = 'WAITING' ORDER BY id LIMIT 1")
            confession = cursor.fetchone()
            
            if not confession:
                print("[POST] Kuyrukta itiraf yok.")
                self.is_posting = False
                return
            
            post_id, content = confession
            print(f"[POST] Post: {content[:50]}...")
            
            post_yolu = post_olustur(content, post_id, is_red=False)
            
            if post_yolu:
                cursor.execute("UPDATE confessions SET status = 'POSTED', posted_at = ? WHERE id = ?",
                              (datetime.now().isoformat(), post_id))
                db_conn.commit()
                
                self.stats["post_count"] += 1
                self.last_post_time = datetime.now()
                print(f"[POST] ✅ Atıldı: {post_id}")
                
        except Exception as e:
            logging.error(f"Post hatası: {e}")
            self.stats["error_count"] += 1
        finally:
            self.is_posting = False
    
    def calistir(self):
        print("\n" + "="*50)
        print("🤖 İTİRAF BOTU BAŞLADI")
        print("⚠️  Yanıt yok! Sadece oku ve filtrele")
        print("📁 Red yiyenler: Red_yiyenler/")
        print("💬 Yanında kutucuk olan mesajları oku")
        print("="*50 + "\n")
        
        self.dm_kismina_git()
        
        while True:
            try:
                # DM Tara (post atmiyorsa)
                self.dm_tara()
                
                # Post At
                self.post_at()
                
                # İstatistik
                cursor = db_conn.cursor()
                cursor.execute("INSERT INTO stats (date, post_count, dm_count, rejected_count, error_count) VALUES (?, ?, ?, ?, ?)",
                              (datetime.now().isoformat(), self.stats["post_count"], self.stats["dm_count"], 
                               self.stats["rejected_count"], self.stats["error_count"]))
                db_conn.commit()
                
                print(f"[BEKLE] 10 saniye...")
                time.sleep(10)
                
            except KeyboardInterrupt:
                print("\n[SİSTEM] Bot durduruldu.")
                break
            except Exception as e:
                logging.error(f"Döngü hatası: {e}")
                time.sleep(30)
                self.driver.quit()
                self.driver = self.get_driver()
                self.dm_kismina_git()

if __name__ == "__main__":
    bot = InstagramBot()
    bot.calistir()
