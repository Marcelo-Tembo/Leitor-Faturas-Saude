# -*- mode: python ; coding: utf-8 -*-
# launcher.spec — compila o launcher UMA vez.
#
# Primeira compilacao: deixe console=True para ver as mensagens [update].
# Depois de validar, troque para console=False e recompile.
#
#   pip install pyinstaller
#   python -m PyInstaller launcher.spec
#
# (use 'python -m PyInstaller' se o comando 'pyinstaller' nao estiver no PATH,
#  como acontece no Python da Microsoft Store)

from PyInstaller.utils.hooks import collect_all
import os

datas = [("payload", "payload")]   # embute o codigo inicial dentro do .exe
binaries = []
hiddenimports = ["openpyxl", "pytesseract", "smtplib", "email"]

# Tesseract EMBUTIDO: se a pasta tessbin/ existir (com tesseract.exe + DLLs +
# tessdata), ela e empacotada dentro do .exe. Fica FORA de payload/ de proposito
# (o payload e o que vai no zip de atualizacao; o Tesseract e estatico e pesado).
# Rode antes:  python preparar_tessbin.py
if os.path.isdir("tessbin"):
    datas += [("tessbin", "tessbin")]
    print(">>> tessbin encontrado: Tesseract sera EMBUTIDO no .exe")
else:
    print(">>> tessbin NAO encontrado: o app usara o Tesseract instalado na maquina")

# Coleta completa das libs que o PyInstaller costuma nao enxergar inteiras.
for pkg in ["PySide6", "fitz", "selenium", "webdriver_manager",
            "gender_guesser", "PIL", "pandas"]:
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["launcher.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="LeitorFaturas",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,          # 1a compilacao: True. Depois troque para False.
    icon=None,             # coloque "leitor.ico" se tiver um icone
)
