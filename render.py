"""Build a tafsir.daily video: one scene per verse (image + recitation), then join them.

Inputs come from environment variables (set by the GitHub workflow):
  SURAH, FROM_AYAH, TO_AYAH, RECITER  -> what to render
  MUKHTASAR_EMAIL, MUKHTASAR_PASSWORD, BOOK_AR, BOOK_EN -> repository secrets
Output: out/video.mp4
"""
import html, json, os, re, subprocess, sys, pathlib
import requests
from playwright.sync_api import sync_playwright

SURAH = int(os.environ["SURAH"]); A1 = int(os.environ["FROM_AYAH"]); A2 = int(os.environ["TO_AYAH"])
RECITER = os.environ["RECITER"].strip()
API = "https://admin.mokhtasr.com/api/v1"
ROOT = pathlib.Path(__file__).parent
WORK = ROOT / "work"; OUT = ROOT / "out"
WORK.mkdir(exist_ok=True); OUT.mkdir(exist_ok=True)
ARABIC_DIGITS = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")
S = requests.Session(); S.headers["User-Agent"] = "tafsir-daily-renderer"


def fail(msg, data=None):
    print("ERROR:", msg)
    if data is not None:
        print(json.dumps(data, ensure_ascii=False, indent=2)[:3000])
    sys.exit(1)


def login():
    r = S.post(f"{API}/app/login", params={"email": os.environ["MUKHTASAR_EMAIL"],
                                          "password": os.environ["MUKHTASAR_PASSWORD"]}, timeout=30)
    r.raise_for_status(); j = r.json()
    try:
        return j["data"]["token"]
    except (KeyError, TypeError):
        fail("Could not find data.token in the Mukhtasar login response", j)


def verse_text(aya):
    r = S.get("https://api.quran.com/api/v4/quran/verses/uthmani",
              params={"verse_key": f"{SURAH}:{aya}"}, timeout=30)
    r.raise_for_status(); j = r.json()
    try:
        return j["verses"][0]["text_uthmani"]
    except (KeyError, IndexError):
        fail(f"No Quran text for {SURAH}:{aya}", j)


def clean(text):
    """Remove HTML tags like <br>, </br>, <p> that sometimes appear in the tafsir text."""
    text = re.sub(r"<\s*/?\s*br\s*/?\s*>", " ", text, flags=re.I)   # <br>, </br>, <br/>
    text = re.sub(r"<[^>]+>", "", text)                               # any other tag
    text = html.unescape(text)                                        # &nbsp; &quot; ...
    return re.sub(r"\s+", " ", text).strip()


def tafsir(token, aya, lang, book):
    r = S.get(f"{API}/book-contents", headers={"Authorization": f"Bearer {token}"},
              params={"lang": lang, "sura": SURAH, "aya": aya, "books": book}, timeout=30)
    r.raise_for_status(); j = r.json()
    try:
        return clean(j["data"][0]["books"][0]["text"])
    except (KeyError, IndexError, TypeError):
        fail(f"Tafsir field not found ({lang}, {SURAH}:{aya}). Adjust the path in tafsir().", j)


RECITERS = {  # everyayah folder -> name shown on the cover (add more as you use them)
    "Yasser_Ad-Dussary_128kbps": "ياسر الدوسري",
    "Minshawy_Mujawwad_192kbps": "محمد صديق المنشاوي",
    "Alafasy_128kbps": "مشاري العفاسي",
}


def chapter_names():
    r = S.get(f"https://api.quran.com/api/v4/chapters/{SURAH}", params={"language": "en"}, timeout=30)
    r.raise_for_status(); c = r.json()["chapter"]
    return c["name_arabic"], c["name_simple"]


def make_cover(page):
    name_ar, name_en = chapter_names()
    ar = lambda n: str(n).translate(ARABIC_DIGITS)
    if A1 == A2:
        pre, rng = f"SURAH {SURAH} · VERSE {A1}", f"الآية {ar(A1)}"
    else:
        pre, rng = f"SURAH {SURAH} · VERSES {A1}–{A2}", f"الآيات {ar(A1)} – {ar(A2)}"
    rec = RECITERS.get(RECITER)
    rec_line = f'<div class="rec">بصوت الشيخ {html.escape(rec)}</div>' if rec else ""
    t = (ROOT / "cover.html").read_text(encoding="utf-8")
    t = (t.replace("{{PRE}}", pre).replace("{{NAME_AR}}", html.escape(name_ar))
          .replace("{{NAME_EN}}", html.escape(name_en)).replace("{{RANGE_AR}}", rng)
          .replace("{{RECITER_LINE}}", rec_line))
    f = ROOT / "_cover.html"; f.write_text(t, encoding="utf-8")
    page.goto(f.as_uri(), wait_until="networkidle")
    page.evaluate("document.fonts.ready")
    page.evaluate("fitTitle()")
    page.screenshot(path=str(OUT / "cover.png"))
    print("Cover:", OUT / "cover.png")


def download(url, path):
    r = S.get(url, timeout=60)
    if r.status_code != 200:
        fail(f"Download failed ({r.status_code}): {url}")
    path.write_bytes(r.content)


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        fail("Command failed: " + " ".join(cmd) + "\n" + p.stderr[-2000:])
    return p.stdout


def main():
    token = login()
    template = (ROOT / "template.html").read_text(encoding="utf-8")
    segments = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1080, "height": 1920})
        make_cover(page)
        for aya in range(A1, A2 + 1):
            tag = f"{SURAH:03d}{aya:03d}"
            print(f"Verse {SURAH}:{aya}")
            v = verse_text(aya)
            ar = tafsir(token, aya, "ar", os.environ["BOOK_AR"])
            en = tafsir(token, aya, "en", os.environ["BOOK_EN"])
            page_html = (template.replace("{{VERSE}}", html.escape(v))
                                 .replace("{{TAFSIR_AR}}", html.escape(ar))
                                 .replace("{{TAFSIR_EN}}", html.escape(en))
                                 .replace("{{NUM}}", str(aya).translate(ARABIC_DIGITS)))
            html_file = ROOT / f"_scene.html"   # next to background.png so the relative URL works
            html_file.write_text(page_html, encoding="utf-8")
            page.goto(html_file.as_uri(), wait_until="networkidle")
            page.evaluate("document.fonts.ready")
            page.evaluate("fitText()")
            img = WORK / f"{tag}.png"
            page.screenshot(path=str(img))

            mp3 = WORK / f"{tag}.mp3"
            download(f"https://everyayah.com/data/{RECITER}/{tag}.mp3", mp3)

            seg = WORK / f"{tag}.mp4"
            run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", "30", "-i", str(img),
                 "-i", str(mp3), "-vf", "fade=t=in:st=0:d=0.6,format=yuv420p",
                 "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage", "-crf", "20", "-r", "30",
                 "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2", "-shortest", str(seg)])
            segments.append(seg)
        browser.close()

    lst = WORK / "list.txt"
    lst.write_text("".join(f"file '{s.as_posix()}'\n" for s in segments))
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
         "-c", "copy", "-movflags", "+faststart", str(OUT / "video.mp4")])
    print("Done:", OUT / "video.mp4")


if __name__ == "__main__":
    main()
