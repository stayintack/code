"""Assemble index.html from src/page.html, the embedded team logos and the data snapshot."""
import pathlib

root = pathlib.Path(__file__).resolve().parent.parent
src = root / "src"
body = (src / "page.html").read_text().replace("/*LOGOS*/", (src / "logos.js").read_text()).replace("/*DATA*/", (src / "data.js").read_text())
# The page source is written as a body fragment; wrap it in a full document for static hosting.
doc = ('<!doctype html>\n<html lang="zh-CN">\n<head>\n<meta charset="utf-8">\n'
       '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n'
       '<style>[hidden]{display:none!important}body{margin:0}img{max-width:100%}:root{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}</style>\n'
       '</head>\n<body>\n' + body + '\n</body>\n</html>\n')
(root / "index.html").write_text(doc)
print("index.html", len(doc), "bytes")
