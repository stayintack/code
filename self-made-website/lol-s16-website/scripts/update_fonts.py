"""Regenerate fonts/noto-serif-sc-900.woff2 as a subset holding every CJK character in src/page.html.

Run this after adding new Chinese headline text. Google Fonts builds the subset (text= parameter);
the result is saved locally so visitors never load anything from Google.
"""
import pathlib, re, urllib.parse, urllib.request

root = pathlib.Path(__file__).resolve().parent.parent
page = (root / "src" / "page.html").read_text(encoding="utf-8")
chars = sorted({c for c in page if "　" <= c <= "鿿" or "＀" <= c <= "￯"})
text = "".join(chars) + "0123456789 ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz·—–-:#."
ua = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
css_url = "https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@900&text=" + urllib.parse.quote(text)
css = urllib.request.urlopen(urllib.request.Request(css_url, headers=ua), timeout=30).read().decode()
font_url = re.search(r"url\((https://fonts\.gstatic\.com[^)]+)\)", css).group(1)
data = urllib.request.urlopen(urllib.request.Request(font_url, headers=ua), timeout=60).read()
(root / "fonts" / "noto-serif-sc-900.woff2").write_bytes(data)
print(f"noto-serif-sc-900.woff2: {len(chars)} CJK characters, {len(data) // 1024} KB")
