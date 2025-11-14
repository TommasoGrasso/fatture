import fitz
import re

doc = fitz.open("IT10077640968_Hqi53.pdf")

quantita_tot = 0
COL_MIN = 250
COL_MAX = 290

for page in doc:
    for (x0,y0,x1,y1,word, *_) in page.get_text("words"):
        if COL_MIN <= x0 <= COL_MAX:
            if re.fullmatch(r"\d{1,3},\d{2}", word):
                print("Trovata quantità:", word)
                quantita_tot += float(word.replace(",", "."))

print("\nSomma quantità =", quantita_tot)



""" metodo funzionante """
""" def extract_doc_number_and_date(text):
    pattern = r"TD\d+\s+[^\n]*?\s+([0-9A-Za-z/]+)\s+(\d{2}-\d{2}-\d{4})"
    m = re.search(pattern, text)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return "", "" """

def extract_po(text):
    """
    Estrae la PO e limita la parte numerica a max 10 cifre.
    Mantiene la logica originale ma evita di catturare numeri troppo lunghi.
    """

    # Ordine di estrazione (come prima)
    patterns = [
        r"Vs\.?Ord\.?\s*([0-9/\-\s]+)",
        r"\bPO\s+([0-9/\-\s]+)",
        r"Ordine\s+([0-9/\-\s]+)"
    ]

    for patt in patterns:
        m = re.search(patt, text, re.IGNORECASE)
        if m:
            raw = m.group(1).strip()

            # --- Limita a 10 cifre numeriche ----
            only_digits = re.sub(r"\D", "", raw)  # toglie tutto tranne le cifre
            only_digits = only_digits[:10]        # prime 10 cifre

            # Ora ricostruisco la PO mantenendo / e - ma tagliando dopo le 10 cifre
            new_raw = ""
            digit_count = 0
            for char in raw:
                if char.isdigit():
                    if digit_count < 10:
                        new_raw += char
                        digit_count += 1
                    else:
                        break
                else:
                    new_raw += char  # mantieni / -
            
            return new_raw.strip()

    return ""

def extract_ddt_and_date(text):
    """
    Estrae TUTTE le righe del tipo:
    DDT A1-2025-0000415 del 03-10-2025
    DDT 2025 41 0056596 del 28-10-2025
    E restituisce due stringhe separate da ';'
    """

    ddt_list = []
    date_list = []  

    # cattura sia formati con '-' sia con spazi
    pattern = r"DDT\s+([A-Za-z0-9\-\/ ]+?)\s+del\s+(\d{2}-\d{2}-\d{4})"

    matches = re.findall(pattern, text)

    for numero_ddt, data in matches:
        # pulisci numero ddt
        numero_ddt = numero_ddt.strip().replace(" ", "")
        ddt_list.append(numero_ddt)

        # formatta data
        data = data.replace("-", "/")
        date_list.append(data)

    # se non trovati → restituisci vuoto
    return "; ".join(ddt_list), "; ".join(date_list)

def extract_ddt_and_date(text):
    """
    Funzione definitiva per estrarre TUTTI i DDT e TUTTE le date,
    associandoli correttamente. Funziona con:
    - numeri spezzati
    - date spezzate
    - più DDT nella stessa fattura
    - qualsiasi formato 'Autry' ecc.
    """

    ddt_final = []
    date_final = []

    lines = text.splitlines()

    for i, line in enumerate(lines):

        # ============================================================
        # 1) CERCA NUMERO DDT SULLA RIGA
        # ============================================================
        m = re.search(r"\bDDT\s+(.+)", line)
        if not m:
            continue

        numero_raw = m.group(1).strip()

        # 🔵 Rimuovi tutto ciò che viene dopo "del"
        numero_raw = re.sub(r"del.*", "", numero_raw)

        # 🔵 Rimuovi spazi interni
        numero_ddt = numero_raw.replace(" ", "")

        # 🔵 Rimuovi valori troppo corti o palesemente rotti
        if len(numero_ddt) < 5:
            continue

        # 2) CERCA LA DATA

        data_found = None

        # --- Caso A: data completa sulla stessa riga ---
        m1 = re.search(r"del\s*([0-9]{2}-[0-9]{2}-[0-9]{4})", line)
        if m1:
            data_found = m1.group(1)

        # --- Caso B: data spezzata tipo "del 28-" + "10-2025" ---
        if data_found is None and i + 1 < len(lines):

            tail = ""
            if "del" in line:
                tail = line.split("del", 1)[1]
            else:
                tail = line

            merged = tail.strip() + lines[i + 1].strip()

            m2 = re.search(r"([0-9]{2}-[0-9]{2}-[0-9]{4})", merged)
            if m2:
                data_found = m2.group(1)

        # --- Caso C: data spezzata su 3 righe ---
        if data_found is None and i + 2 < len(lines):
            merged = line + lines[i + 1] + lines[i + 2]
            m3 = re.search(r"([0-9]{2}-[0-9]{2}-[0-9]{4})", merged)
            if m3:
                data_found = m3.group(1)

        # Se ancora nulla → ignora questa riga
        if not data_found:
            continue

        # 🟢 Formatta la data
        data_ddt = data_found.replace("-", "/")

        # 3) EVITA DUPLICATI MA MANTIENI L'ORDINE

        pair = (numero_ddt, data_ddt)
        if pair not in zip(ddt_final, date_final):
            ddt_final.append(numero_ddt)
            date_final.append(data_ddt)


    return "\n".join(ddt_final), "\n".join(date_final)
