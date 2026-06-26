# -*- coding: utf-8 -*-
# build_release.py — empacota o payload (codigo atualizavel) e gera o manifesto.
#
# Uso:   python build_release.py 1.1
#
# Saida (na pasta dist/):
#   app-<versao>.zip   -> o codigo (leitor_pdf.py) zipado
#   latest.json        -> {version, url, sha256}
#
# Depois e so criar uma Release no GitHub com a TAG = <versao> e subir
# os DOIS arquivos (app-<versao>.zip e latest.json) como assets. Nenhuma
# recompilacao do .exe e necessaria.

import os
import sys
import json
import zipfile
import hashlib

AQUI = os.path.dirname(os.path.abspath(__file__))
PAYLOAD = os.path.join(AQUI, "payload")
DIST = os.path.join(AQUI, "dist")

# ⚠️ AJUSTE: mesmo OWNER/REPO usado no launcher.py
OWNER_REPO = "Marcelo-Tembo/Leitor-Faturas-Saude"
SERVER_BASE = f"https://github.com/{OWNER_REPO}/releases/download"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for bloco in iter(lambda: f.read(8192), b""):
            h.update(bloco)
    return h.hexdigest()


def main():
    if len(sys.argv) < 2:
        print("Uso: python build_release.py <versao>   (ex.: python build_release.py 1.1)")
        sys.exit(1)
    versao = sys.argv[1].strip()

    if not os.path.exists(os.path.join(PAYLOAD, "leitor_pdf.py")):
        print("ERRO: nao encontrei payload/leitor_pdf.py")
        sys.exit(1)

    os.makedirs(DIST, exist_ok=True)
    zip_out = os.path.join(DIST, f"app-{versao}.zip")

    # Zipa TODO o conteudo de payload/ (mantendo nomes na raiz do zip)
    with zipfile.ZipFile(zip_out, "w", zipfile.ZIP_DEFLATED) as z:
        for raiz, _, arquivos in os.walk(PAYLOAD):
            for nome in arquivos:
                if nome.endswith((".pyc",)) or "__pycache__" in raiz:
                    continue
                caminho = os.path.join(raiz, nome)
                arc = os.path.relpath(caminho, PAYLOAD)
                z.write(caminho, arc)

    manifest = {
        "version": versao,
        "url": f"{SERVER_BASE}/{versao}/app-{versao}.zip",
        "sha256": sha256(zip_out),
    }
    with open(os.path.join(DIST, "latest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print("OK!")
    print(f"  {zip_out}")
    print(f"  {os.path.join(DIST, 'latest.json')}")
    print()
    print(f"Agora crie a Release no GitHub com a TAG '{versao}' e suba os dois "
          f"arquivos acima como assets.")


if __name__ == "__main__":
    main()
