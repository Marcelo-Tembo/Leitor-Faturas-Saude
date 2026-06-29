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

# Icone do app: procura o .ico na pasta DESTE arquivo .spec (SPECPATH), assim
# funciona independente de onde voce roda o pyinstaller. Aceita varios nomes;
# usa o primeiro que encontrar. Vira o icone do .exe E e embutido para virar
# tambem o icone da janela/barra de tarefas em tempo de execucao.
_ico_nomes = ["leitor.ico", "unnamed.ico", "Boletos_Envio.ico"]
ICONE = next((os.path.join(SPECPATH, n) for n in _ico_nomes
              if os.path.exists(os.path.join(SPECPATH, n))), None)
if ICONE:
    datas += [(ICONE, ".")]
    print(f">>> Icone encontrado: {ICONE}")
else:
    print(">>> Nenhum .ico encontrado em", SPECPATH, "— o .exe sai com o icone padrao")

# Coleta completa das libs que o PyInstaller costuma nao enxergar inteiras.
# OBS: PySide6 SAIU desta lista de proposito. O collect_all("PySide6")
# empacotava o Qt inteiro (QtWebEngine, Qt3D, QtQuick, multimidia...), o que
# inflava MUITO o .exe. Sem ele, o hook nativo do PySide6 inclui apenas os
# modulos realmente usados (QtCore/QtGui/QtWidgets) + os plugins de plataforma.
for pkg in ["fitz", "selenium", "webdriver_manager",
            "gender_guesser", "PIL", "pandas"]:
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# Modulos pesados do Qt que este app NAO usa (so usa QtWidgets/QtCore/QtGui).
# Excluir corta dezenas/centenas de MB. Se o .exe parar de abrir reclamando de
# algum modulo Qt, remova o nome correspondente desta lista e recompile.
qt_excludes = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel", "PySide6.QtWebSockets",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D",
    "PySide6.QtQuickWidgets", "PySide6.QtQuickControls2",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput", "PySide6.Qt3DLogic",
    "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtUiTools",
    "PySide6.QtHelp", "PySide6.QtBluetooth", "PySide6.QtNfc",
    "PySide6.QtPositioning", "PySide6.QtLocation", "PySide6.QtSerialPort",
    "PySide6.QtSensors",
]

a = Analysis(
    ["launcher.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=qt_excludes,
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
    console=False,          # 1a compilacao: True. Depois troque para False.
    icon=ICONE,            # usa o .ico detectado acima (ou None se nao houver)
)
