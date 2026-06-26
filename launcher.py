# -*- coding: utf-8 -*-
# launcher.py — Compilado UMA vez com PyInstaller. Raramente muda.
#
# Responsabilidade: checar atualizacao do CODIGO (payload), baixar com
# verificacao de hash, trocar de forma atomica (com rollback) e entao
# carregar e rodar o seu leitor_pdf.py de verdade. As bibliotecas pesadas
# (PySide6, PyMuPDF, pandas, Selenium, Pillow, etc.) ficam congeladas AQUI
# dentro do .exe; o que voce atualiza pela rede e so o leitor_pdf.py.

import os
import sys
import json
import zipfile
import hashlib
import shutil
import tempfile
import traceback
import urllib.request

# ── Ancoras de importacao ─────────────────────────────────────────────
# O PyInstaller so congela o que enxerga em 'import'. Como o payload e
# importado DINAMICAMENTE, listamos aqui as dependencias pesadas para que
# sejam embutidas no .exe. Este bloco nunca executa (if False), mas o
# PyInstaller analisa as imports mesmo assim. NAO REMOVA.
if False:  # noqa
    import PySide6           # noqa  GUI
    import fitz              # noqa  PyMuPDF (leitura de PDF)
    import pandas            # noqa
    import openpyxl          # noqa  necessario para pandas.to_excel
    import PIL               # noqa  Pillow (imagens p/ OCR)
    import pytesseract       # noqa  OCR local
    import selenium          # noqa  reserva OCR (iLovePDF)
    import webdriver_manager # noqa
    import gender_guesser    # noqa  deducao de sexo (tem arquivos de dados!)
    import smtplib           # noqa
    import email             # noqa

APP_NOME = "LeitorFaturas"

# ⚠️ AJUSTE para o seu repositorio (dono/repo). Recomendado PUBLICO:
# este payload NAO tem credenciais, entao um repo publico simplifica o
# download (sem token). As Releases ficam em:
#   https://github.com/<OWNER_REPO>/releases
OWNER_REPO = "Marcelo-Tembo/Leitor-Faturas-Saude"
API_LATEST = f"https://api.github.com/repos/{OWNER_REPO}/releases/latest"

# Pasta de INSTALACAO = onde esta o .exe. Aqui ficam arquivos FIXOS locais
# (ex.: segredos.json, se um dia houver) e e onde o usuario salva os Excel.
if getattr(sys, "frozen", False):
    INSTALL_DIR = os.path.dirname(os.path.abspath(sys.executable))
    BUNDLE_DIR = sys._MEIPASS  # onde o PyInstaller extrai recursos embutidos
else:
    INSTALL_DIR = os.path.dirname(os.path.abspath(__file__))
    BUNDLE_DIR = INSTALL_DIR

# Pasta de CODIGO atualizavel (no APPDATA do usuario — sobrevive a updates).
APP_DIR = os.path.join(os.getenv("APPDATA") or os.path.expanduser("~"), APP_NOME)
CODE_DIR = os.path.join(APP_DIR, "code")           # versao ativa
BACKUP_DIR = os.path.join(APP_DIR, "code_backup")  # versao anterior (rollback)
VERSION_FILE = os.path.join(APP_DIR, "version.txt")

# (Opcional) Tesseract embutido: se voce empacotar o tesseract dentro do .exe
# em payload/tessbin/tesseract.exe e adicionar via --add-data, o launcher
# avisa o leitor_pdf.py via variavel de ambiente. Senao, o app usa o
# Tesseract instalado na maquina (detectado automaticamente).
def configurar_tesseract_embutido():
    candidato = os.path.join(BUNDLE_DIR, "tessbin", "tesseract.exe")
    if os.path.exists(candidato):
        os.environ["LEITOR_TESSERACT"] = candidato
        tessdata = os.path.join(BUNDLE_DIR, "tessbin", "tessdata")
        if os.path.isdir(tessdata):
            os.environ["LEITOR_TESSDATA"] = tessdata
            os.environ["TESSDATA_PREFIX"] = tessdata
        log("Tesseract embutido detectado.")


def log(msg):
    print(f"[update] {msg}")


def versao_local():
    try:
        return open(VERSION_FILE, encoding="utf-8").read().strip()
    except FileNotFoundError:
        return "0"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for bloco in iter(lambda: f.read(8192), b""):
            h.update(bloco)
    return h.hexdigest()


def _http_json(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": APP_NOME,
        "Accept": "application/vnd.github+json",
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def _baixar(url, destino):
    req = urllib.request.Request(url, headers={"User-Agent": APP_NOME})
    with urllib.request.urlopen(req, timeout=120) as r, open(destino, "wb") as f:
        shutil.copyfileobj(r, f)


def garantir_codigo_inicial():
    """Na 1a execucao (ou se o codigo sumiu), instala a copia embutida no .exe
    para o app funcionar mesmo offline, antes de qualquer download."""
    alvo = os.path.join(CODE_DIR, "leitor_pdf.py")
    if os.path.exists(alvo):
        return
    os.makedirs(CODE_DIR, exist_ok=True)
    origem = os.path.join(BUNDLE_DIR, "payload")
    if os.path.isdir(origem):
        for nome in os.listdir(origem):
            caminho = os.path.join(origem, nome)
            if nome == "__pycache__" or not os.path.isfile(caminho):
                continue
            shutil.copy2(caminho, os.path.join(CODE_DIR, nome))
        log("Codigo inicial instalado a partir do .exe.")


def aplicar_update():
    """Consulta a Release 'latest' no GitHub e atualiza o payload se houver
    versao nova. Falha de rede NUNCA derruba o app: cai no codigo ja instalado."""
    try:
        info = _http_json(API_LATEST)
        tag = (info.get("tag_name") or "").strip()
        assets = {a["name"]: a["browser_download_url"] for a in info.get("assets", [])}
        if not tag:
            log("Sem 'tag_name' na Release. Pulando update.")
            return
        if tag == versao_local() and os.path.exists(os.path.join(CODE_DIR, "leitor_pdf.py")):
            log(f"Ja esta na versao {tag}.")
            return

        if "latest.json" not in assets:
            log("Release sem 'latest.json'. Pulando update.")
            return

        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = os.path.join(tmp, "latest.json")
            _baixar(assets["latest.json"], manifest_path)
            manifest = json.load(open(manifest_path, encoding="utf-8"))

            zip_url = manifest.get("url") or assets.get(f"app-{tag}.zip")
            if not zip_url:
                log("Manifesto sem URL do zip. Pulando update.")
                return

            zip_path = os.path.join(tmp, "app.zip")
            _baixar(zip_url, zip_path)

            # Verificacao de integridade (o launcher EXECUTA o que baixa).
            if manifest.get("sha256") and sha256(zip_path) != manifest["sha256"]:
                log("SHA256 nao confere! Abortando update por seguranca.")
                return

            extr = os.path.join(tmp, "extr")
            os.makedirs(extr, exist_ok=True)
            with zipfile.ZipFile(zip_path) as z:
                z.extractall(extr)
            if not os.path.exists(os.path.join(extr, "leitor_pdf.py")):
                log("Zip nao contem leitor_pdf.py. Abortando.")
                return

            # Troca atomica com backup p/ rollback.
            if os.path.isdir(BACKUP_DIR):
                shutil.rmtree(BACKUP_DIR, ignore_errors=True)
            if os.path.isdir(CODE_DIR):
                shutil.move(CODE_DIR, BACKUP_DIR)
            shutil.move(extr, CODE_DIR)
            open(VERSION_FILE, "w", encoding="utf-8").write(tag)
            log(f"Atualizado para a versao {tag}.")
    except Exception as e:
        log(f"Update ignorado ({e.__class__.__name__}: {e}). Rodando versao local.")


def rodar_app():
    """Carrega o payload de CODE_DIR e chama leitor_pdf.run()."""
    if CODE_DIR not in sys.path:
        sys.path.insert(0, CODE_DIR)
    import importlib
    leitor = importlib.import_module("leitor_pdf")
    leitor.run()


def rollback_e_rodar():
    """Se o codigo novo quebrar na inicializacao, volta para o backup."""
    if not os.path.isdir(BACKUP_DIR):
        raise
    log("Falha ao iniciar a versao nova. Revertendo para a anterior...")
    if os.path.isdir(CODE_DIR):
        shutil.rmtree(CODE_DIR, ignore_errors=True)
    shutil.move(BACKUP_DIR, CODE_DIR)
    # limpa import em cache e tenta de novo
    for m in [m for m in list(sys.modules) if m == "leitor_pdf"]:
        del sys.modules[m]
    rodar_app()


def main():
    os.makedirs(APP_DIR, exist_ok=True)
    configurar_tesseract_embutido()
    garantir_codigo_inicial()
    aplicar_update()
    try:
        rodar_app()
    except Exception:
        traceback.print_exc()
        try:
            rollback_e_rodar()
        except Exception:
            traceback.print_exc()


if __name__ == "__main__":
    main()
