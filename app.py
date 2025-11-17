import io
import re

import pdfplumber
import pandas as pd
from flask import Flask, render_template, request, send_file

app = Flask(__name__)


# ---------- FUNZIONI DI ESTRAZIONE DAI PDF ----------
def extract_text_from_pdf(file_storage):
    """
    Legge tutto il testo di un PDF caricato (FileStorage di Flask)
    e restituisce una stringa unica.
    """
    with pdfplumber.open(file_storage) as pdf:
        pages_text = []
        for page in pdf.pages:
            txt = page.extract_text() or ""
            pages_text.append(txt)
    return "\n".join(pages_text)


def extract_doc_number_and_date(text):
    """
    Cerca la riga con TDxx fattura / nota di credito e prende
    Numero documento + Data documento.
    Aggiunge automaticamente il prefisso '25IN_' al numero documento.
    """
    pattern = r"TD\d+\s+[^\n]*?\s+([0-9A-Za-z/]+)\s+(\d{2}-\d{2}-\d{4})"
    m = re.search(pattern, text)
    if m:
        numero = m.group(1).strip()
        data_doc = m.group(2).strip()

        # AGGIUNTA PREFISSO
        numero_con_prefisso = f"25IN_{numero}"

        return numero_con_prefisso, data_doc

    return "", ""


def extract_po(text):
    """
    Estrae la PO da:
    - 'Vs.Ord. 2025 - 124270'
    - 'Vs.Ord. 2025/122413'
    - 'Vs.Ord. PO 42519/42516'
    - 'PO 42519/42516'
    e limita la parte numerica a max 10 cifre.
    """

    # 1) caso Vs.Ord. con eventuale PO in mezzo
    m = re.search(
        r"Vs\.?Ord\.?\s*(?:PO\s*)?([0-9][0-9/\-\s]+)",
        text,
        re.IGNORECASE
    )
    if m:
        return limit_po_digits(m.group(1).strip())

    # 2) caso PO 42519/42516
    m = re.search(r"\bPO\s+([0-9/\-\s]+)", text, re.IGNORECASE)
    if m:
        return limit_po_digits(m.group(1).strip())

    # 3) fallback: Ordine XXXXXXX
    m = re.search(r"Ordine\s+([0-9/\-\s]+)", text, re.IGNORECASE)
    if m:
        return limit_po_digits(m.group(1).strip())

    return ""


def limit_po_digits(raw):
    """
    Mantiene i caratteri originali (/ e -),
    ma solo finché le cifre totali non superano 10.
    """

    result = ""
    digit_count = 0

    for char in raw:
        if char.isdigit():
            if digit_count < 10:
                result += char
                digit_count += 1
            else:
                break
        else:
            # mantieni / - spazi finché ci sono ancora cifre da aggiungere
            if digit_count < 10:
                result += char
            else:
                break

    return result.strip()


def extract_ddt_and_date(text):
    """
    Funzione definitiva per estrarre TUTTI i DDT e TUTTE le date,
    associandoli correttamente. Funziona con:
    - numeri spezzati
    - date spezzate
    - più DDT nella stessa fattura
    - qualsiasi formato 'Autry' ecc.
    - restituisce SOLO le ultime 5 cifre del DDT
    """

    ddt_final = []
    date_final = []

    lines = text.splitlines()

    for i, line in enumerate(lines):

        # 1) CERCA NUMERO DDT SULLA RIGA
        m = re.search(r"\bDDT\s+(.+)", line)
        if not m:
            continue

        numero_raw = m.group(1).strip()

        # Rimuovi tutto ciò che viene dopo "del"
        numero_raw = re.sub(r"del.*", "", numero_raw)

        # Rimuovi spazi interni
        numero_raw = numero_raw.replace(" ", "")

        #Estrai le cifre presenti
        digits = re.findall(r"\d", numero_raw)
        digits_str = "".join(digits)

        #Se almeno 5 cifre → tieni solo le ULTIME 5
        if len(digits_str) >= 5:
            numero_ddt = digits_str[-5:]
        else:
            continue  

        # 2) CERCA LA DATA
        data_found = None

        # --- Caso A: data completa sulla stessa riga ---
        m1 = re.search(r"del\s*([0-9]{2}-[0-9]{2}-[0-9]{4})", line)
        if m1:
            data_found = m1.group(1)

        # --- Caso B: data spezzata tipo "del 28-" + "10-2025" ---
        if data_found is None and i + 1 < len(lines):

            if "del" in line:
                tail = line.split("del", 1)[1]
            else:
                tail = line

            merged = tail.strip() + lines[i + 1].strip()

            m2 = re.search(r"([0-9]{2}-[0-9]{2}-[0-9]{4})", merged)
            if m2:
                data_found = m2.group(1)

        # --- Caso C: data su 3 righe ---
        if data_found is None and i + 2 < len(lines):
            merged = line + lines[i + 1] + lines[i + 2]
            m3 = re.search(r"([0-9]{2}-[0-9]{2}-[0-9]{4})", merged)
            if m3:
                data_found = m3.group(1)

        # Se ancora nulla → ignora il DDT
        if not data_found:
            continue

        # Format data
        data_ddt = data_found.replace("-", "/")

        # 3) EVITA DUPLICATI MANTENENDO L'ORDINE
        pair = (numero_ddt, data_ddt)
        if pair not in zip(ddt_final, date_final):
            ddt_final.append(numero_ddt)
            date_final.append(data_ddt)

    return ddt_final, date_final

""" PIU RIGHE PER PIU DDT """
def explode_ddt_rows(df):
    rows = []

    for _, row in df.iterrows():
        ddt_list = row["DDT"]
        date_list = row["Data DDT"]

        # se non ci sono DDT → una sola riga
        if not ddt_list:
            rows.append(row)
            continue

        # altrimenti crea tante righe quanti sono i DDT
        for ddt, ddt_date in zip(ddt_list, date_list):
            new_row = row.copy()
            new_row["DDT"] = ddt
            new_row["Data DDT"] = ddt_date
            rows.append(new_row)

    return pd.DataFrame(rows)

def parse_number_it(s):
    """
    Converte una stringa numero in formato italiano:
    - '1.016,18' -> 1016.18 (float)
    - '544'      -> 544.0
    """
    s = s.strip()
    if not s:
        return 0.0
    # separatore migliaia .
    s = s.replace(".", "")
    # separatore decimale ,
    s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0

""" PROBLEMA NON CALCOLA IL TOTALE CORRETTO """
def extract_totale_imponibile(text):
    """
    Estrae solo il vero totale imponibile dal riepilogo IVA.
    Esclude automaticamente tutte le righe dei dettagli articoli.
    """

    lines = text.splitlines()

    for line in lines:

        # ignora tutte le righe articoli: hanno l'unità e piccoli valori
        if "paia" in line.lower() or "pz" in line.lower() or "nr" in line.lower():
            continue

        # estrai importi tipo 14.532,25
        nums = re.findall(r"[0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2}", line)

        # la riga giusta ha esattamente:
        # IVA — Totale imponibile — Totale imposta
        if len(nums) == 3:
            iva, imponibile, imposta = nums
            return imponibile 
    # Se arriva qui → NON trovato
    return "CONSULTARE DOCUMENTO"

def extract_total_quantity(file_storage):
    """
    Prova prima con estrazione tabellare.
    Se non trova quantità valide, usa il metodo originale con coordinate.
    """
    total_from_tables = extract_quantity_from_tables(file_storage)

    if total_from_tables > 0:
        return int(total_from_tables)

    # Se le tabelle non hanno dato quantità, usa metodo originale
    return extract_quantity_by_coordinates(file_storage)


def extract_quantity_from_tables(file_storage):
    """
    Estrazione tramite tabelle (funziona per i casi con quantità=1)
    """
    quantita_tot = 0

    with pdfplumber.open(file_storage) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()

            for table in tables:
                if not table:
                    continue

                header = table[0]
                quantita_idx = None

                # Cerca colonna "Quantità"
                for idx, cell in enumerate(header):
                    if cell and "Quantit" in cell:
                        quantita_idx = idx
                        break

                if quantita_idx is None:
                    continue

                for row in table[1:]:
                    if quantita_idx < len(row):
                        cell = row[quantita_idx]
                        if not cell:
                            continue

                        val = cell.strip().replace(" ", "")

                        # Formato tipo "1,00"
                        if re.fullmatch(r"\d+(?:,\d{2})?", val):
                            try:
                                quantita_tot += float(val.replace(",", "."))
                            except:
                                pass

    return quantita_tot


def extract_quantity_by_coordinates(file_storage):
    """
    Il tuo metodo originale che funziona per quasi tutti i file.
    """
    quantita_tot = 0
    COL_MIN = 250
    COL_MAX = 300
    TOLERANCE_Y = 3

    with pdfplumber.open(file_storage) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            col_words = [w for w in words if COL_MIN <= w['x0'] <= COL_MAX]
            col_words.sort(key=lambda w: (round(w['top'] / TOLERANCE_Y), w['x0']))

            lines = []
            current_line = []
            last_y = None

            for word in col_words:
                current_y = round(word['top'] / TOLERANCE_Y)

                if last_y is None or current_y == last_y:
                    current_line.append(word['text'])
                else:
                    if current_line:
                        lines.append(' '.join(current_line))
                    current_line = [word['text']]

                last_y = current_y

            if current_line:
                lines.append(' '.join(current_line))

            # Estrazione numeri originale
            for line in lines:
                line_no_spaces = line.replace(" ", "")
                if re.fullmatch(r"\d{1,6}|\d{1,3}(?:\.\d{3})*|\d{1,3}(?:\.\d{3})*,\d{2}", line_no_spaces):
                    try:
                        quantita_tot += float(line_no_spaces.replace(".", "").replace(",", "."))
                    except:
                        pass

    return quantita_tot

def parse_invoice_from_pdf(file_storage):
    """
    Esegue tutte le varie estrazioni e ritorna un tables
    pronto per finire nella riga del DataFrame.
    """
    text = extract_text_from_pdf(file_storage)

    num_doc, data_doc = extract_doc_number_and_date(text)
    po = extract_po(text)
    #ddt, data_ddt = extract_ddt_and_date(text) 
    ddt_list, date_list = extract_ddt_and_date(text)
    totale_imponibile = extract_totale_imponibile(text)
    quantita = extract_total_quantity(file_storage)

    return {
        "Numero documento": num_doc,
        "Data documento": data_doc,
        "PO": po,
        "DDT": ddt_list,
        "Data DDT": date_list,
        "Totale Imponibile": totale_imponibile,
        "Quantità": quantita,
    }


# ---------- ROUTE FLASK ----------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
def upload():
    files = request.files.getlist("pdf_files")

    if not files or files[0].filename == "":
        return render_template("index.html", message="Nessun PDF selezionato.")

    rows = []
    for f in files:
        if f.filename.lower().endswith(".pdf"):
            rows.append(parse_invoice_from_pdf(f))

    if not rows:
        return render_template("index.html", message="Nessun PDF valido caricato.")

    df = pd.DataFrame(rows)

    # 👉 UNA RIGA PER OGNI DDT
    df = explode_ddt_rows(df)

    # 👉 PLACEHOLDERS PER CELLE VUOTE (come richiesto)
    df["Numero documento"] = df["Numero documento"].replace("", "MANCANTE_NUM_DOC")
    df["Data documento"] = df["Data documento"].replace("", "MANCANTE_DATA_DOC")
    df["PO"] = df["PO"].replace("", "MANCANTE_PO")

    # DDT e Data DDT possono essere liste → le normalizziamo
    df["DDT"] = df["DDT"].apply(
        lambda x: x if x not in ["", None, [], {}] else "MANCANTE_DDT"
    )
    df["Data DDT"] = df["Data DDT"].apply(
        lambda x: x if x not in ["", None, [], {}] else "MANCANTE_DATA_DDT"
    )

    df["Totale Imponibile"] = df["Totale Imponibile"].replace(
        "", "MANCANTE_IMPONIBILE"
    )

    # Quantità: se è None o "", usa placeholder
    df["Quantità"] = df["Quantità"].apply(
        lambda x: x if x not in ["", None] else "MANCANTE_QTA"
    )

    # 👉 CREA L’EXCEL
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Dati")

    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name="fatture_estratte.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )




if __name__ == "__main__":
    # Avvio server Flask
    app.run(debug=True)
