import sys
import fitz  # PyMuPDF
import pandas as pd
import re
import os
import io
import time
import shutil
import unicodedata
from email import encoders
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import gender_guesser.detector as gender
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QPushButton, QFileDialog,
    QVBoxLayout, QWidget, QLabel, QRadioButton, QButtonGroup, QMessageBox
)
from PySide6.QtCore import Qt

# ==========================================
# OCR LOCAL (Tesseract) - opcional
# ==========================================
# O OCR local (Tesseract) e MUITO mais rapido e confiavel do que o iLovePDF
# para os "Demonstrativos Analiticos de Pre Pagamento" da Unimed, que vem com
# o texto achatado em vetores (nao ha camada de texto utilizavel - so OCR le).
#
# Para instalar no Windows:
#   1) Baixe o instalador em: https://github.com/UB-Mannheim/tesseract/wiki
#   2) Durante a instalacao, marque o idioma "Portuguese".
#   3) pip install pytesseract pillow
# Se o tesseract.exe nao estiver no PATH, o codigo abaixo tenta localiza-lo
# nos caminhos padrao de instalacao do Windows automaticamente.
try:
    import pytesseract
    from PIL import Image

    def _localizar_tesseract():
        # 0) Tesseract embutido pelo launcher (se houver) tem prioridade.
        embutido = os.environ.get("LEITOR_TESSERACT")
        if embutido and os.path.exists(embutido):
            return embutido
        # 1) Ja esta no PATH?
        if shutil.which("tesseract"):
            return shutil.which("tesseract")
        # 2) Caminhos padrao de instalacao no Windows
        candidatos = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
        ]
        for c in candidatos:
            if c and os.path.exists(c):
                return c
        return None

    _CAMINHO_TESS = _localizar_tesseract()
    if _CAMINHO_TESS:
        pytesseract.pytesseract.tesseract_cmd = _CAMINHO_TESS
        OCR_LOCAL_DISPONIVEL = True
    else:
        OCR_LOCAL_DISPONIVEL = False
except Exception:
    OCR_LOCAL_DISPONIVEL = False

# Pasta tessdata embutida (definida pelo launcher via LEITOR_TESSDATA). Quando
# o Tesseract vem embutido no .exe, precisamos dizer onde estao os idiomas.
_tessdata_dir = os.environ.get("LEITOR_TESSDATA", "")
TESS_CONFIG = f'--tessdata-dir "{_tessdata_dir}"' if _tessdata_dir and os.path.isdir(_tessdata_dir) else ""


class GenderLogic:
    def __init__(self):
        self.detector = gender.Detector(case_sensitive=False)

    def limpar_texto(self, texto):
        if not isinstance(texto, str): return ""
        nfkd = unicodedata.normalize('NFKD', texto)
        return u"".join([c for c in nfkd if not unicodedata.combining(c)]).upper().strip()

    def descobrir(self, nome_completo):
        nome = self.limpar_texto(nome_completo).split()
        if not nome: return ""
        nome = nome[0]

        gen = self.detector.get_gender(nome.capitalize())
        if 'male' in gen and 'female' not in gen: return 'M'
        if 'female' in gen and 'male' not in gen: return 'F'

        masc = [
            'DOUGLAS', 'JONATAS', 'LUCAS', 'MATHEUS', 'MATEUS', 'NICOLAS', 'THOMAS',
            'SILAS', 'MESSIAS', 'ISAQUE', 'HENRIQUE', 'GUILHERME', 'FELIPE', 'LUIS',
            'LUIZ', 'JEAN', 'ADAN', 'CLEBER', 'ALEXCIO', 'ALMIR', 'WANDERSON',
            'WELLINGTON', 'ENDRICK', 'MAXSUEL', 'MAXUEL', 'THIAGO', 'RUBENS',
            'JHON', 'HEUBER', 'WALLEF', 'GABRYEL', 'YURI', 'KAUA', 'JOSHUA', 'NOA', 'WILLIAN', 'ODIRLEY', 'DAVI', 'ADONIAS', 'VANIM',
            'ELDES', 'MAGNEI', 'VANDERLEY', 'HEBERT'
        ]

        fem = [
            'BEATRIZ', 'LIZ', 'ESTER', 'RUTH', 'RAQUEL', 'INGRID', 'HELLEN', 'ELLEN',
            'SUELEN', 'KELLEN', 'YASMIN', 'EVELYN', 'EVILLYN', 'CARMEN', 'SUELI',
            'THAYNARA', 'CATIA', 'ZILMA', 'ALICE', 'SARA', 'LUCIANA', 'SAMARA',
            'THALITA', 'FRANCIELE', 'GRACIELE', 'MICHELE', 'MIRELLA', 'MAYRA',
            'LAIS', 'IRIS', 'THAIS', 'AGNES', 'JUCIRLEY', 'JULIETE', 'ANNE', 'ANNELIZE', 'EMANUELI',
            'THAYS', 'LARAH', 'KEVELLYN', 'TAMYRIS'
        ]

        if nome in masc: return 'M'
        if nome in fem: return 'F'

        if nome.endswith(('A', 'INE', 'ANE', 'ENE', 'ELE', 'ELY', 'LLY', 'NY', 'LY', 'IA', 'IELLE', 'YNE', 'YNA')):
            return 'F'

        if nome.endswith(('O', 'OS', 'R', 'L', 'K', 'U', 'J', 'SON', 'TON', 'EL', 'IL', 'US', 'IC', 'ON', 'EN')):
            return 'M'

        return "Indefinido"

# ==========================================
# OCR / LEITURA DE TEXTO
# ==========================================
def _imagem_pagina(page, escala):
    pix = page.get_pixmap(matrix=fitz.Matrix(escala, escala))
    return Image.open(io.BytesIO(pix.tobytes("png")))


def ocr_local_por_pagina(caminho_pdf_ou_doc, dpi_escala=3):
    """OCR local com Tesseract. Aceita caminho ou um fitz.Document.
    Retorna lista de textos (um por pagina)."""
    doc = caminho_pdf_ou_doc if isinstance(caminho_pdf_ou_doc, fitz.Document) else fitz.open(caminho_pdf_ou_doc)
    textos = []
    for page in doc:
        QApplication.processEvents()
        textos.append(pytesseract.image_to_string(_imagem_pagina(page, dpi_escala), lang="por", config=TESS_CONFIG))
    return textos


def remover_tarjas(doc):
    """
    Remove as 'tarjas falsas' do Demonstrativo da Unimed.

    Nesses PDFs os nomes nao foram apagados: eles continuam intactos por baixo,
    e foram apenas cobertos por anotacoes do tipo FreeText preenchidas com uma
    unica letra repetida (AAAA.../BBBB...). Apagando essas anotacoes, o nome
    real reaparece (legivel via OCR). Retorna a quantidade removida.
    """
    total = 0
    for page in doc:
        a = page.first_annot
        while a:
            prox = a.next
            try:
                cont = re.sub(r"\s", "", a.info.get("content", "") or "")
                # so remove se o conteudo for uma unica letra/caractere repetido
                if cont and re.fullmatch(r"(.)\1*", cont):
                    page.delete_annot(a)
                    total += 1
            except Exception:
                pass
            a = prox
    return total


def nomes_por_carteirinha(page, escala=5):
    """
    Recupera o nome a ESQUERDA de cada carteirinha (mesma linha) usando OCR
    com posicao (image_to_data). Deve ser chamada DEPOIS de remover_tarjas().
    Retorna um dict {carteirinha: nome}.
    """
    data = pytesseract.image_to_data(_imagem_pagina(page, escala), lang="por",
                                     config=TESS_CONFIG,
                                     output_type=pytesseract.Output.DICT)
    linhas = {}
    for i in range(len(data["text"])):
        t = data["text"][i].strip()
        if not t:
            continue
        chave = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        linhas.setdefault(chave, []).append((data["left"][i], t))

    cart_re = re.compile(r"\d{3}\.\d{4}\.\d{6}\.\d{2}-\d")
    lixo_re = re.compile(
        r"\b(PLANO|ASSISTENCIAL|Repassado|Custo|Operacional|Usuario|Usu[aá]rio|"
        r"Local|Plano|R\$|C[oó]d|Refer[eê]ncia|na|Empresa|Total)\b", re.I)

    resultado = {}
    for toks in linhas.values():
        toks.sort()
        cart = cart_x = None
        for x, t in toks:
            m = cart_re.search(t)
            if m:
                cart, cart_x = m.group(0), x
                break
        if not cart:
            continue
        nome = " ".join(t for x, t in toks if x < cart_x - 2)
        nome = lixo_re.sub("", nome)
        nome = re.sub(r"[^A-Za-zÀ-ÿ\s]", "", nome)
        nome = " ".join(nome.split()).strip()
        if len(nome) > 2:
            resultado[cart] = nome
    return resultado


def texto_simples_por_pagina(caminho_pdf):
    """Le a camada de texto (sem OCR). Retorna lista de textos (um por pagina)."""
    doc = fitz.open(caminho_pdf)
    return [page.get_text("text") for page in doc]


def precisa_ocr(textos):
    """Detecta se o PDF precisa de OCR (texto vazio ou 'lixo' como AAAA/BBBB)."""
    texto = " ".join(textos)
    limpo = re.sub(r"\s", "", texto)
    if len(limpo) < 80:
        return True
    letras = [c for c in limpo if c.isalpha()]
    if not letras:
        return True
    # Se sobram pouquissimas letras distintas (ex.: so 'A' e 'B'), e lixo de fonte quebrada.
    if len(set(c.upper() for c in letras)) < 8:
        return True
    # Se uma unica letra domina o texto, tambem e lixo.
    mais_comum = max(set(letras), key=letras.count)
    if letras.count(mais_comum) / len(letras) > 0.45:
        return True
    return False


def eh_demonstrativo(textos):
    """Identifica o 'Demonstrativo Analitico de Pre Pagamento' da Unimed."""
    t = " ".join(textos).lower()
    return ("demonstrativo" in t and ("pre pagamento" in t or "pré pagamento" in t)) \
        or ("resumo do demonstrativo" in t)

# ==========================================
# FUNCOES DE EXTRACAO DOS PDFs
# ==========================================
def tranformar_em_editavel(caminho_pdf):
    # Pega o caminho absoluto da pasta para não ter erro no Chrome
    pasta_download = os.path.abspath(os.path.dirname(caminho_pdf))
    caminho_absoluto_pdf = os.path.abspath(caminho_pdf)

    URL_IPDF = "https://www.ilovepdf.com/pt/ocr-pdf"

    opt = Options()
    opt.add_argument("--headless=new")
    opt.add_argument("--disable-popup-blocking")
    opt.add_argument("--window-size=1920,1080")
    opt.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    opt.add_argument("--disable-blink-features=AutomationControlled")
    opt.add_argument("--disable-gpu")
    opt.add_argument("--no-sandbox")
    opt.page_load_strategy = 'eager'

    # Correções para impedir totalmente o Adobe Acrobat de abrir:
    prefs = {
        "download.default_directory": pasta_download,
        "savefile.default_directory": pasta_download,
        "download.prompt_for_download": False,
        "plugins.always_open_pdf_externally": True,  # Força o download
        "download.extensions_to_open": "",  # Limpa a lista de arquivos que abrem sozinhos no Windows
        "profile.default_content_settings.popups": 0,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True
    }
    opt.add_experimental_option("prefs", prefs)
    opt.add_experimental_option("excludeSwitches", ["enable-automation"])
    opt.add_experimental_option('useAutomationExtension', False)

    # Inicia o WebDriver
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opt)

    try:
        driver.get(URL_IPDF)
        QApplication.processEvents()  # Descongela a interface
        wait = WebDriverWait(driver, 40)

        # 1. Enviar o arquivo PDF
        input_file = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@type='file']")))
        input_file.send_keys(caminho_absoluto_pdf)

        # 2. Aguardar o arquivo carregar e clicar em "Aplicar ROC"
        QApplication.processEvents()
        time.sleep(2)  # Pausa rápida para a animação do site
        btn_processar = wait.until(EC.element_to_be_clickable((By.ID, "processTask")))
        driver.execute_script("arguments[0].click();", btn_processar)

        # 3. Monitorar a pasta para pegar o arquivo assim que o download terminar
        arquivos_antes = set(os.listdir(pasta_download))
        tempo_maximo = 120  # Tempo máximo em segundos
        tempo_decorrido = 0
        caminho_novo_pdf = None

        while tempo_decorrido < tempo_maximo:
            QApplication.processEvents()  # Descongela a interface enquanto espera!

            arquivos_depois = set(os.listdir(pasta_download))
            novos_arquivos = arquivos_depois - arquivos_antes

            # Checa se existe arquivo baixando temporário (.crdownload)
            tem_crdownload = any(f.endswith('.crdownload') for f in os.listdir(pasta_download))
            arquivos_pdf_baixados = [f for f in novos_arquivos if f.endswith('.pdf')]

            # Só aceita o arquivo se não houver mais download em andamento e ele for maior que 0 bytes
            if arquivos_pdf_baixados and not tem_crdownload:
                caminho_novo = os.path.join(pasta_download, arquivos_pdf_baixados[0])
                if os.path.getsize(caminho_novo) > 0:
                    caminho_novo_pdf = caminho_novo
                    time.sleep(2)  # Dá 2 segundos pro Windows soltar o bloqueio do arquivo de vez
                    break

            time.sleep(1)
            tempo_decorrido += 1

        if caminho_novo_pdf:
            return caminho_novo_pdf
        else:
            raise Exception("Tempo limite de processamento e download excedido no iLovePDF.")

    finally:
        driver.quit()


def extrair_unimed_final_v3(caminho_pdf):
    doc = fitz.open(caminho_pdf)
    lista_final = []

    padrao_carteirinha = re.compile(r"\b\d{3}\.\d+\.\d+\.\d{2}-\d\b")

    for numero_pagina, page in enumerate(doc):
        QApplication.processEvents()
        texto_pagina = page.get_text("text")
        palavras = page.get_text("words")

        for p in palavras:
            texto_palavra = p[4]
            match = padrao_carteirinha.search(texto_palavra)

            if match:
                carteirinha_encontrada = match.group(0)
                x0, y0, x1, y1 = p[0], p[1], p[2], p[3]

                rect_nome = fitz.Rect(0, y0 - 2, x0, y1 + 2)
                nome_bruto = page.get_text("text", clip=rect_nome, flags=0)
                nome_limpo = " ".join(nome_bruto.split())

                lixos = ["Beneficiário", "Nome", ":", "Dependente"]
                for lixo in lixos:
                    nome_limpo = nome_limpo.replace(lixo, "")
                nome_limpo = nome_limpo.strip()

                tipo = "Dependente"
                match_tipo = re.search(r"\.(\d{2})-\d", carteirinha_encontrada)
                if match_tipo and match_tipo.group(1) == "00":
                    tipo = "Titular"

                idade = ""
                padrao_faixa = re.escape(carteirinha_encontrada) + r'[\s\S]{1,80}?(?:\bPLANO ASSISTENCIAL\b)?[\s\S]{1,30}?(\d{1,2}-\d{1,3})'
                match_faixa = re.search(padrao_faixa, texto_pagina)
                if match_faixa:
                    idade = match_faixa.group(1)

                if len(nome_limpo) > 2:
                    lista_final.append({
                        "Nome": nome_limpo,
                        "Carteirinha": carteirinha_encontrada,
                        "Data de Nascimento": "",
                        "Faixa Etária / Idade": idade,
                        "Tipo": tipo,
                        "Plano": "",
                        "Valor": "",
                        "Pagina": numero_pagina + 1
                    })

    df = pd.DataFrame(lista_final)

    if not df.empty:
        df = df.drop_duplicates(subset=["Carteirinha"], keep="first")
        df["Responsavel_Vinculado"] = None
        titular_atual = "Não Identificado"
        for index, row in df.iterrows():
            if row["Tipo"] == "Titular":
                titular_atual = row["Nome"]
            df.at[index, "Responsavel_Vinculado"] = titular_atual

    return df


def extrair_samp(caminho_pdf):
    doc = fitz.open(caminho_pdf)
    lista_final = []

    padrao_geral = re.compile(
        r"(\d{3}\.\d+)\s+"                 # 1. Carteirinha
        r"([A-Za-zÀ-ÖØ-öø-ÿ\s]+?)\s+"      # 2. Nome
        r"(\d{11})\s+"                     # 3. CPF
        r"(\S+)\s+"                        # 4. Plano (ex: 701, 070)
        r"(Titular|Dependente)\s+"         # 5. Tipo
        r"(\d{2}/\d{2}/\d{4})\s+"          # 6. Data Nascimento
        r"(\d{1,3})\s+"                    # 7. Idade
        r"(\d{2}/\d{2}/\d{4})\s+"          # 8. Data Inclusão
        r"([\d.,]+)"                       # 9. Valor
    )

    for numero_pagina, page in enumerate(doc):
        QApplication.processEvents()
        texto_pagina = page.get_text("text")

        for match in padrao_geral.finditer(texto_pagina):
            carteirinha = match.group(1).strip()
            nome = match.group(2).strip()
            nome = " ".join(nome.split())
            cpf = match.group(3).strip()
            plano = match.group(4).strip()
            tipo = match.group(5).strip()
            data_nasc = match.group(6).strip()
            idade = match.group(7).strip()
            valor = match.group(9).strip()

            lista_final.append({
                "Nome": nome,
                "CPF": cpf,
                "Data de Nascimento": data_nasc,
                "Faixa Etária / Idade": idade,
                "Carteirinha": carteirinha,
                "Tipo": tipo,
                "Plano": plano,
                "Valor": valor,
                "Pagina": numero_pagina + 1
            })

    df = pd.DataFrame(lista_final)

    if not df.empty:
        df['Valor_Num'] = df['Valor'].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
        df['Valor_Num'] = pd.to_numeric(df['Valor_Num'], errors='coerce').fillna(0)

        somas = df.groupby('Carteirinha')['Valor_Num'].sum().reset_index()
        somas.rename(columns={'Valor_Num': 'Valor_Total'}, inplace=True)

        df = df.merge(somas, on='Carteirinha', how='left')
        df['Valor'] = df['Valor_Total'].apply(lambda x: f"{x:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'))
        df = df.drop(columns=['Valor_Num', 'Valor_Total'])

        df["Responsavel_Vinculado"] = None
        titular_atual = "Não Identificado"
        for index, row in df.iterrows():
            if row["Tipo"] == "Titular":
                titular_atual = row["Nome"]
            df.at[index, "Responsavel_Vinculado"] = titular_atual

    return df


def extrair_unimed_demonstrativo(textos_paginas):
    """
    Extrai o 'Demonstrativo Analitico de Pre Pagamento' da Unimed a partir do
    TEXTO (ja extraido/OCR) de cada pagina.

    Retorna uma tupla (df_beneficiarios, df_resumo):
      - df_beneficiarios: uma linha por carteirinha (Carteirinha, Faixa, Categoria,
        Plano, Valor, Tipo, Pagina). OBS.: os nomes NAO sao recuperaveis pois vem
        ofuscados/borrados na origem deste documento.
      - df_resumo: a tabela "Resumo do Demonstrativo" (contagens por faixa etaria).
    """
    benef = []
    resumo = []

    cart_re = re.compile(r"\d{3}\.\d{4}\.\d{6}\.\d{2}-\d")

    for pno, texto in enumerate(textos_paginas, start=1):
        QApplication.processEvents()

        # ---- 1) Linhas por carteirinha (beneficiarios) ----
        carts = list(cart_re.finditer(texto))
        for i, m in enumerate(carts):
            cart = m.group(0)
            ini = m.end()
            fim = carts[i + 1].start() if i + 1 < len(carts) else len(texto)
            seg = texto[ini:fim]
            corte = re.search(r"\b(Total|Resumo do Demonstrativo|C[oó]d\. Refer)", seg)
            if corte:
                seg = seg[:corte.start()]

            faixa_m = re.search(r"\b(\d{1,2}\s*-\s*\d{1,3})\b", seg)
            faixa = re.sub(r"\s", "", faixa_m.group(1)) if faixa_m else ""

            if re.search(r"Repassado|Custo\s*Operacional|Operacional", seg, re.IGNORECASE):
                categoria = "Repassado em Custo Operacional"
            elif re.search(r"Usu[aá]rio\s*Local|Usuario\s*Local", seg, re.IGNORECASE):
                categoria = "Usuario Local"
            else:
                categoria = ""

            plano_m = re.search(r"Plano\s*([A-Z])\b", seg)
            plano = plano_m.group(1) if plano_m else ""

            val_m = re.search(r"R\$\s*([\d.]+,\d{2})", seg)
            valor = val_m.group(1) if val_m else ""

            tipo = "Titular" if re.search(r"\.00-\d$", cart) else "Dependente"

            benef.append({
                "Carteirinha": cart,
                "Faixa Etária / Idade": faixa,
                "Categoria": categoria,
                "Plano": plano,
                "Valor": valor,
                "Tipo": tipo,
                "Pagina": pno
            })

        # ---- 2) Tabela "Resumo do Demonstrativo" ----
        cols_contagem = ['Anterior', 'Incl.', 'Excl.', 'Mov. Incl.', 'Mov. Excl.', 'Atual']
        plano_atual = ""
        for ln in texto.splitlines():
            # Limpa ruido comum do OCR para zeros: (o) (0) jo)
            l = re.sub(r"\(\s*[o0O]\s*\)|jo\)", "0", ln.strip())

            # Linha com a letra do plano (A / B ...)
            m = re.match(
                r"^([A-Z])\s+(\d{1,3})\s+(\d{1,3})\s+(.*?)\s*"
                r"R\$\s*([\d.]+,\d{2})\s+R\$\s*([\d.]+,\d{2})\s+R\$\s*([\d.]+,\d{2})\s*$", l)
            if m:
                plano_atual = m.group(1)
                g = m.groups()
            else:
                # Linha sem a letra (OCR perdeu o plano) -> herda o plano anterior
                m = re.match(
                    r"^(\d{1,3})\s+(\d{1,3})\s+(.*?)\s*"
                    r"R\$\s*([\d.]+,\d{2})\s+R\$\s*([\d.]+,\d{2})\s+R\$\s*([\d.]+,\d{2})\s*$", l)
                if not m:
                    continue
                g = (plano_atual,) + m.groups()

            plano, fde, fate, meio, vunit, tdesc, vtot = g
            d = {"Plano": plano, "Faixa De": fde, "Faixa Ate": fate}
            nums = re.findall(r"\d+", meio)
            if len(nums) == len(cols_contagem):
                d.update(dict(zip(cols_contagem, nums)))
            else:
                d["Contagens"] = " ".join(nums)
            d.update({"Vl. Unitário": vunit, "Tot. Desc.": tdesc, "Vl. Total": vtot, "Pagina": pno})
            resumo.append(d)

    df_benef = pd.DataFrame(benef)
    if not df_benef.empty:
        df_benef = df_benef.drop_duplicates(subset=["Carteirinha"], keep="first")

    df_resumo = pd.DataFrame(resumo)
    return df_benef, df_resumo


def processar_demonstrativo(caminho_pdf, gender_logic=None):
    """
    Fluxo completo do 'Demonstrativo Analitico de Pre Pagamento' da Unimed:
      1) remove as tarjas falsas (anotacoes que cobrem os nomes);
      2) faz OCR (Tesseract local, com reserva no iLovePDF);
      3) extrai faixa/categoria/plano/valor + a tabela Resumo;
      4) recupera o NOME a esquerda de cada carteirinha (so com Tesseract local);
      5) deduz o Sexo a partir do nome.
    Retorna (df_beneficiarios, df_resumo, qtd_tarjas_removidas).
    """
    doc = fitz.open(caminho_pdf)
    qtd_tarjas = remover_tarjas(doc)

    mapa_nomes = {}
    if OCR_LOCAL_DISPONIVEL:
        textos = ocr_local_por_pagina(doc, dpi_escala=5)
        for page in doc:
            QApplication.processEvents()
            mapa_nomes.update(nomes_por_carteirinha(page))
    else:
        # Reserva: salva o PDF JA SEM tarjas e manda para o iLovePDF.
        base, _ = os.path.splitext(caminho_pdf)
        tmp = base + "_sem_tarjas.pdf"
        doc.save(tmp)
        novo = tranformar_em_editavel(tmp)
        textos = texto_simples_por_pagina(novo)
        # Sem Tesseract nao da para recuperar o nome por posicao (fica em branco).

    df_benef, df_resumo = extrair_unimed_demonstrativo(textos)

    if not df_benef.empty:
        df_benef.insert(0, "Nome", df_benef["Carteirinha"].map(mapa_nomes).fillna(""))
        if gender_logic is not None:
            df_benef.insert(1, "Sexo", df_benef["Nome"].apply(
                lambda n: gender_logic.descobrir(n) if str(n).strip() else ""))
        # ordem amigavel das colunas
        ordem = ["Nome", "Sexo", "Carteirinha", "Faixa Etária / Idade",
                 "Categoria", "Plano", "Valor", "Tipo", "Pagina"]
        df_benef = df_benef[[c for c in ordem if c in df_benef.columns]]

    return df_benef, df_resumo, qtd_tarjas

# ==========================================
# INTERFACE GRÁFICA PYSIDE6
# ==========================================
class LeitorFaturasApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Leitor de Faturas - Plano de Saúde")
        self.setFixedSize(420, 270)

        self.caminho_arquivo = None
        self.logic_genero = GenderLogic()

        layout = QVBoxLayout()

        self.label_instrucao = QLabel("Selecione o tipo de documento:")
        self.label_instrucao.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label_instrucao)

        # Uma unica opcao "Unimed": detecta sozinho se e listagem de
        # beneficiarios ou Demonstrativo Analitico de Pre-Pagamento.
        self.radio_unimed = QRadioButton("Unimed (listagem ou demonstrativo)")
        self.radio_unimed.setChecked(True)
        self.radio_samp = QRadioButton("SAMP")

        self.grupo_operadora = QButtonGroup()
        self.grupo_operadora.addButton(self.radio_unimed)
        self.grupo_operadora.addButton(self.radio_samp)

        layout.addWidget(self.radio_unimed)
        layout.addWidget(self.radio_samp)

        self.btn_selecionar = QPushButton("Selecionar Arquivo PDF")
        self.btn_selecionar.clicked.connect(self.selecionar_arquivo)
        layout.addWidget(self.btn_selecionar)

        self.label_arquivo = QLabel("Nenhum arquivo selecionado.")
        self.label_arquivo.setAlignment(Qt.AlignCenter)
        self.label_arquivo.setStyleSheet("color: gray;")
        layout.addWidget(self.label_arquivo)

        self.btn_processar = QPushButton("Extrair e Gerar Excel")
        self.btn_processar.clicked.connect(self.processar_arquivo)
        self.btn_processar.setEnabled(False)

        self.btn_processar.setStyleSheet("""
            QPushButton { background-color: #4CAF50; color: white; font-weight: bold; padding: 8px;}
            QPushButton:disabled { background-color: #a5d6a7; color: #f1f1f1; }
        """)
        layout.addWidget(self.btn_processar)

        widget = QWidget()
        widget.setLayout(layout)
        self.setCentralWidget(widget)

    def selecionar_arquivo(self):
        caminho, _ = QFileDialog.getOpenFileName(self, "Selecionar PDF", "", "PDF Files (*.pdf)")
        if caminho:
            self.caminho_arquivo = caminho
            nome_arquivo = os.path.basename(caminho)
            self.label_arquivo.setText(f"Arquivo: {nome_arquivo}")
            self.label_arquivo.setStyleSheet("color: blue;")
            self.btn_processar.setEnabled(True)

    def _obter_textos_com_ocr(self):
        """
        Devolve a lista de textos por pagina, fazendo OCR quando necessario.
        Prioriza o OCR local (Tesseract). Se nao estiver instalado, usa o
        iLovePDF (Selenium) como reserva.
        """
        textos = texto_simples_por_pagina(self.caminho_arquivo)
        if not precisa_ocr(textos):
            return textos

        # Precisa de OCR
        if OCR_LOCAL_DISPONIVEL:
            QMessageBox.information(
                self, "OCR",
                "O documento não tem texto legível (está em imagem/vetor).\n"
                "Lendo via OCR local (Tesseract). Isso é rápido, aguarde um instante."
            )
            return ocr_local_por_pagina(self.caminho_arquivo)

        # Reserva: iLovePDF
        QMessageBox.information(
            self, "Aviso de OCR",
            "Nenhum texto detectado e o Tesseract não está instalado.\n\n"
            "Iniciando conversão via iLovePDF (pode levar alguns instantes, "
            "por favor não feche o programa)."
        )
        novo_pdf = tranformar_em_editavel(self.caminho_arquivo)
        return texto_simples_por_pagina(novo_pdf)

    def _rodar_demonstrativo(self):
        df_benef, df_resumo, n_tarjas = processar_demonstrativo(self.caminho_arquivo, self.logic_genero)
        if df_benef.empty and df_resumo.empty:
            QMessageBox.warning(self, "Aviso", "Nenhum dado encontrado no demonstrativo.")
            return
        self._gerar_excel_demonstrativo(df_benef, df_resumo, n_tarjas)

    def _gerar_excel_demonstrativo(self, df_benef, df_resumo, n_tarjas=0):
        sugestao = f"Demonstrativo_Unimed_{len(df_benef)}benef.xlsx"
        caminho_salvar, _ = QFileDialog.getSaveFileName(self, "Salvar Excel", sugestao, "Excel Files (*.xlsx)")
        if not caminho_salvar:
            return
        try:
            with pd.ExcelWriter(caminho_salvar, engine="openpyxl") as writer:
                if not df_benef.empty:
                    df_benef.to_excel(writer, sheet_name="Beneficiarios", index=False)
                if not df_resumo.empty:
                    df_resumo.to_excel(writer, sheet_name="Resumo", index=False)
                if df_benef.empty and df_resumo.empty:
                    pd.DataFrame({"Aviso": ["Nenhum dado encontrado"]}).to_excel(writer, index=False)

            # Conta quantos nomes foram efetivamente recuperados
            nomes_ok = 0
            if not df_benef.empty and "Nome" in df_benef.columns:
                nomes_ok = int(df_benef["Nome"].astype(str).str.strip().ne("").sum())

            msg = (f"Arquivo gerado!\n"
                   f"Beneficiários: {len(df_benef)}\n"
                   f"Linhas no resumo: {len(df_resumo)}\n")
            if n_tarjas:
                msg += (f"\nForam removidas {n_tarjas} tarjas e {nomes_ok} de {len(df_benef)} "
                        f"nomes foram recuperados via OCR.\n"
                        f"Obs.: nomes muito longos (que quebram em duas linhas) podem sair "
                        f"imperfeitos — vale conferir esses casos.")
            QMessageBox.information(self, "Sucesso", msg)
        except PermissionError:
            QMessageBox.warning(
                self, "Aviso de Arquivo",
                "Não foi possível salvar porque o arquivo Excel já está aberto no seu computador.\n\n"
                "Feche o arquivo e tente gerar novamente."
            )

    def processar_arquivo(self):
        try:
            self.btn_processar.setText("Processando...")
            self.btn_processar.setEnabled(False)
            QApplication.processEvents()

            operadora = "Unimed" if self.radio_unimed.isChecked() else "SAMP"

            # ==================================================
            # CAMINHO B: Unimed (listagem OU demonstrativo) / SAMP
            # ==================================================
            df_resultado = pd.DataFrame()

            # --- TENTATIVA 1: Extração normal ---
            if operadora == "Unimed":
                # Se o PDF ja tem texto legivel e e um Demonstrativo, vai direto.
                textos_brutos = texto_simples_por_pagina(self.caminho_arquivo)
                if eh_demonstrativo(textos_brutos) and not precisa_ocr(textos_brutos):
                    self._rodar_demonstrativo()
                    return

                df_resultado = extrair_unimed_final_v3(self.caminho_arquivo)
                if not df_resultado.empty:
                    extraidos = df_resultado['Nome'].str.extract(r'\b(\d{3}\.\d{3}\.\d{3}-\d{2}|\d{11})\b')
                    df_resultado['CPF'] = extraidos[0]
                    df_resultado['Nome'] = df_resultado['Nome'].str.replace(r'\b(\d{3}\.\d{3}\.\d{3}-\d{2}|\d{11})\b', '', regex=True).str.strip()
            else:
                df_resultado = extrair_samp(self.caminho_arquivo)

            # --- TENTATIVA 2: OCR se o PDF for escaneado ---
            if df_resultado.empty:
                # Detecta automaticamente se na verdade e um Demonstrativo (texto em vetor)
                textos = self._obter_textos_com_ocr()

                if eh_demonstrativo(textos):
                    QMessageBox.information(
                        self, "Documento identificado",
                        "Detectei que este arquivo é um 'Demonstrativo Analítico de Pré "
                        "Pagamento'. Vou gerar a planilha nesse formato."
                    )
                    self._rodar_demonstrativo()
                    return

                # Caso contrario, e uma listagem escaneada: reaplica os extratores no PDF OCR'd
                novo_caminho_pdf = tranformar_em_editavel(self.caminho_arquivo)
                if operadora == "Unimed":
                    df_resultado = extrair_unimed_final_v3(novo_caminho_pdf)
                    if not df_resultado.empty:
                        extraidos = df_resultado['Nome'].str.extract(r'\b(\d{3}\.\d{3}\.\d{3}-\d{2}|\d{11})\b')
                        df_resultado['CPF'] = extraidos[0]
                        df_resultado['Nome'] = df_resultado['Nome'].str.replace(r'\b(\d{3}\.\d{3}\.\d{3}-\d{2}|\d{11})\b', '', regex=True).str.strip()
                else:
                    df_resultado = extrair_samp(novo_caminho_pdf)

                if df_resultado.empty:
                    QMessageBox.warning(self, "Aviso", "Nenhum dado encontrado, mesmo após a conversão (OCR).")
                    return

            # --- CONTINUAÇÃO DA LÓGICA ORIGINAL ---

            # Bloqueio de Duplicatas Limpo
            df_resultado['Nome_Upper'] = df_resultado['Nome'].str.upper().str.strip()
            df_resultado = df_resultado.drop_duplicates(subset=['Nome_Upper'], keep="first")
            df_resultado = df_resultado.drop(columns=['Nome_Upper'])

            # Preenchimento de Gênero
            df_resultado['Sexo'] = df_resultado['Nome'].apply(self.logic_genero.descobrir)

            # Garante a existência das colunas
            for col in ['Faixa Etária / Idade', 'Data de Nascimento', 'Plano', 'Valor']:
                if col not in df_resultado.columns:
                    df_resultado[col] = ""

            # Formatação especial para o Excel
            df_resultado['Carteirinha'] = df_resultado['Carteirinha'].astype(str) + '\u200B'
            df_resultado['Plano'] = df_resultado['Plano'].apply(lambda x: str(x) + '\u200B' if str(x).strip() != "" else "")

            # Reordenando as colunas
            colunas_ordenadas = ['Nome', 'CPF', 'Data de Nascimento', 'Faixa Etária / Idade', 'Sexo', 'Carteirinha', 'Plano', 'Valor', 'Tipo', 'Responsavel_Vinculado', 'Pagina']
            colunas_existentes = [col for col in colunas_ordenadas if col in df_resultado.columns]
            df_resultado = df_resultado[colunas_existentes]

            caminho_salvar, _ = QFileDialog.getSaveFileName(self, "Salvar Excel", f"Relatorio_{operadora}_{len(df_resultado)}.xlsx", "Excel Files (*.xlsx)")

            if caminho_salvar:
                try:
                    df_resultado.to_excel(caminho_salvar, index=False)
                    QMessageBox.information(self, "Sucesso", f"Arquivo gerado!\n{len(df_resultado)} registros processados.")
                except PermissionError:
                    QMessageBox.warning(self, "Aviso de Arquivo", "Não foi possível salvar porque o arquivo Excel já está aberto no seu computador.\n\nFeche o arquivo e tente gerar novamente.")

        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Erro", f"Ocorreu um erro na conversão ou extração:\n{str(e)}")

        finally:
            self.btn_processar.setText("Extrair e Gerar Excel")
            self.btn_processar.setEnabled(True)


def run():
    """Ponto de entrada chamado pelo launcher (e tambem ao rodar direto)."""
    # No Windows, sem isto o app fica agrupado sob o "Python" e a barra de
    # tarefas nao mostra o icone customizado. Define uma identidade propria.
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Tembo.LeitorFaturas")
    except Exception:
        pass

    app = QApplication.instance() or QApplication(sys.argv)
    # Icone da janela (definido pelo launcher via LEITOR_ICONE, se embutido)
    _icone = os.environ.get("LEITOR_ICONE")
    if _icone and os.path.exists(_icone):
        try:
            from PySide6.QtGui import QIcon
            app.setWindowIcon(QIcon(_icone))
        except Exception:
            pass
    window = LeitorFaturasApp()
    if _icone and os.path.exists(_icone):
        try:
            from PySide6.QtGui import QIcon
            window.setWindowIcon(QIcon(_icone))
        except Exception:
            pass
    window.show()
    # Nao usar sys.exit() aqui: quem controla o processo e o launcher.
    app.exec()


if __name__ == "__main__":
    run()