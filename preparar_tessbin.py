# -*- coding: utf-8 -*-
# preparar_tessbin.py — monta a pasta tessbin/ (Tesseract embutido) a partir
# do Tesseract JA INSTALADO na sua maquina Windows.
#
# Rode UMA vez antes de compilar:   python preparar_tessbin.py
#
# Ele copia o tesseract.exe + todas as DLLs e mantem apenas os idiomas
# necessarios (por, eng, osd) para nao inflar o .exe. Depois disso, e so
# compilar normalmente (python -m PyInstaller launcher.spec) que o spec
# detecta a pasta tessbin/ e embute tudo no executavel.

import os
import shutil

AQUI = os.path.dirname(os.path.abspath(__file__))
DESTINO = os.path.join(AQUI, "tessbin")

# Idiomas a manter (o resto do tessdata e descartado para economizar espaco).
# O app so usa portugues, entao por padrao embutimos apenas o 'por'. Se algum
# dia precisar de ingles, adicione "eng.traineddata" ao conjunto.
IDIOMAS = {"por.traineddata"}

CANDIDATOS = [
    r"C:\Program Files\Tesseract-OCR",
    r"C:\Program Files (x86)\Tesseract-OCR",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR"),
]


def achar_instalacao():
    for c in CANDIDATOS:
        if c and os.path.exists(os.path.join(c, "tesseract.exe")):
            return c
    return None


def main():
    origem = achar_instalacao()
    if not origem:
        print("ERRO: nao encontrei o Tesseract instalado.")
        print("Instale primeiro: https://github.com/UB-Mannheim/tesseract/wiki")
        print("(marque o idioma 'Portuguese' na instalacao) e rode este script de novo.")
        return

    print(f"Tesseract encontrado em: {origem}")
    if os.path.isdir(DESTINO):
        shutil.rmtree(DESTINO)
    os.makedirs(DESTINO)

    # Copia tudo da raiz (tesseract.exe + DLLs), menos a pasta tessdata.
    for nome in os.listdir(origem):
        caminho = os.path.join(origem, nome)
        if nome.lower() == "tessdata":
            continue
        if os.path.isfile(caminho):
            shutil.copy2(caminho, os.path.join(DESTINO, nome))

    # Copia o tessdata, mas so com os idiomas escolhidos.
    td_origem = os.path.join(origem, "tessdata")
    td_destino = os.path.join(DESTINO, "tessdata")
    os.makedirs(td_destino, exist_ok=True)
    achei_por = False
    if os.path.isdir(td_origem):
        for nome in os.listdir(td_origem):
            if nome in IDIOMAS:
                shutil.copy2(os.path.join(td_origem, nome), os.path.join(td_destino, nome))
                if nome == "por.traineddata":
                    achei_por = True
            elif nome.lower() in ("configs", "tessconfigs"):
                shutil.copytree(os.path.join(td_origem, nome),
                                os.path.join(td_destino, nome), dirs_exist_ok=True)

    if not achei_por:
        print("AVISO: 'por.traineddata' nao foi encontrado no tessdata.")
        print("Reinstale o Tesseract marcando o idioma 'Portuguese'.")

    # Tamanho final
    total = sum(os.path.getsize(os.path.join(r, f))
                for r, _, fs in os.walk(DESTINO) for f in fs)
    print(f"Pronto! Pasta '{DESTINO}' montada ({total/1e6:.1f} MB).")
    print("Agora compile:  python -m PyInstaller launcher.spec")


if __name__ == "__main__":
    main()
