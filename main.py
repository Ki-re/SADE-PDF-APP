import unicodedata
from flask import Flask, render_template, request, redirect, url_for, send_file
import os
import pandas as pd
import openpyxl
from openpyxl.styles import Font
from werkzeug.utils import secure_filename
import pdfplumber
import io
import re

app = Flask(__name__)

# Directorio donde se guardarán los archivos subidos
UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Extensiones permitidas
ALLOWED_EXTENSIONS = {'pdf'}

# Función para verificar si el archivo tiene una extensión permitida
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Cargar la lista de proveedores desde el archivo CSV
suppliers_df = pd.read_csv('suppliers.csv')

# Normalizar texto eliminando caracteres especiales
def normalize_text(text):
    text = text.lower()  # Convertir a minúsculas
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')  # Eliminar acentos y caracteres especiales
    text = re.sub(r'[^a-z0-9\s]', '', text)  # Eliminar cualquier símbolo especial restante
    return text

# Mapeo extendido de tamaño y tipo de contenedor a nomenclatura abreviada
size_type_map = {
    "20DRY": "20'DV",
    "40DRY": "40'DV",
    "40HIGH": "40'HC",
    "45HIGH": "45'HC",
    "20REEFER": "20'RF",
    "40REEFER": "40'RF",
    "40HCRF": "40'HCRF",
    "45REEFER": "45'RF",
    "20FLAT": "20'FR",
    "40FLAT": "40'FR",
    "40HIGHFLAT": "40'HFR",
    "20OPENTOP": "20'OT",
    "40OPENTOP": "40'OT",
    "40HIGHOPENTOP": "40'HOT",
    "20PLATFORM": "20'PL",
    "40PLATFORM": "40'PL"
}

# Lista de condiciones
condition_keywords = ["As Is", "Recycle", "Damage", "New", "IICL"]

# Función para extraer información de tipo y tamaño
def extract_size_type(text):
    for key in size_type_map:
        if key in text:
            return size_type_map[key]
    return "Unknown Size/Type"

# Función para extraer la condición
def extract_condition(text):
    for condition in condition_keywords:
        if condition.lower() in text.lower():
            return condition
    return "Unknown Condition"

# Función para buscar el SUPPLIER con coincidencias flexibles
def extract_supplier(text):
    normalized_text = normalize_text(text)
    for _, row in suppliers_df.iterrows():
        supplier_name = normalize_text(row['Company Name'])  # Normalizar el nombre del proveedor

        # Convertir el texto del PDF en minúsculas y buscar coincidencias más amplias
        if supplier_name in normalized_text:
            return row['Commercial Name']
    
    # Si no se encuentra coincidencia exacta, intentamos buscar usando variaciones
    if "maersk" in normalized_text:
        return "Maersk"
    
    return "Unknown Supplier"

# Nueva función para extraer el Proforma Invoice No o Invoice No
def extract_proforma_invoice(text):
    patterns = [
        r'Proforma Invoice No[:\s]+([A-Za-z0-9\-]+)',
        r'Invoice No[:\s]+([A-Za-z0-9\-]+)'
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    return "Unknown Proforma Invoice No"

# Función para extraer información estructurada del PDF usando pdfplumber
def extract_pdf_info(file_path):
    container_data = []
    size_type_data = []
    condition_data = []
    supplier_data = []
    release_ref_data = []

    with pdfplumber.open(file_path) as pdf:
        for page_num, page in enumerate(pdf.pages):
            text = page.extract_text()
            
            if text:
                lines = text.split("\n")
                for line in lines:
                    line = line.strip()

                    # Detectar contenedores según ISO 6346
                    container_match = re.findall(r'\b[A-Z]{4}[0-9]{7}\b', line)
                    if container_match:
                        container_data.extend(container_match)
                    
                    # Detectar tipos y tamaños
                    size_type = extract_size_type(line)
                    if size_type != "Unknown Size/Type":
                        size_type_data.append(size_type)

                    # Detectar condición
                    condition = extract_condition(line)
                    if condition != "Unknown Condition":
                        condition_data.append(condition)

                    # Detectar proveedor (SUPPLIER)
                    supplier = extract_supplier(text)
                    if supplier != "Unknown Supplier" and supplier not in supplier_data:
                        supplier_data.append(supplier)

                # Extraer Proforma Invoice No
                proforma_invoice = extract_proforma_invoice(text)
                if proforma_invoice != "Unknown Proforma Invoice No":
                    release_ref_data.append(proforma_invoice)

    # Asegurarnos de que todas las listas tengan la misma longitud
    min_length = min(len(container_data), len(size_type_data), len(condition_data))
    container_data = container_data[:min_length]
    size_type_data = size_type_data[:min_length]
    condition_data = condition_data[:min_length]

    # Si no se detecta SUPPLIER, asignamos "Unknown Supplier" a todas las filas
    if len(supplier_data) == 0:
        supplier_data = ["Unknown Supplier"] * min_length
    else:
        supplier_data = [supplier_data[0]] * min_length

    # Si no se detecta Proforma Invoice No, asignamos "Unknown Proforma Invoice No" a todas las filas
    if len(release_ref_data) == 0:
        release_ref_data = ["Unknown Proforma Invoice No"] * min_length
    else:
        release_ref_data = [release_ref_data[0]] * min_length

    return container_data, size_type_data, condition_data, supplier_data, release_ref_data

# Función para crear o actualizar el archivo Excel, verificando duplicados
# def create_or_update_excel(container_data, size_type_data, condition_data, supplier_data, release_ref_data, output_filename):
#     output_path = os.path.join(app.config['UPLOAD_FOLDER'], output_filename)

#     # Verificar si el archivo Excel ya existe
#     if os.path.exists(output_path):
#         existing_df = pd.read_excel(output_path)
#     else:
#         existing_df = pd.DataFrame(columns=["Container", "Size/Type", "Condition", "Supplier", "Supplier Release Ref"])

#     # Crear un nuevo DataFrame con los datos extraídos
#     new_data = pd.DataFrame({
#         "Container": container_data,
#         "Size/Type": size_type_data,
#         "Condition": condition_data,
#         "Supplier": supplier_data,
#         "Supplier Release Ref": release_ref_data
#     })

#     # Verificar duplicados antes de agregar al archivo Excel
#     duplicate_containers = existing_df['Container'].isin(new_data['Container'])
#     if duplicate_containers.any():
#         duplicate_list = existing_df[duplicate_containers]['Container'].tolist()
#         return None, duplicate_list

#     # Concatenar el DataFrame existente con el nuevo y eliminar duplicados
#     combined_df = pd.concat([existing_df, new_data]).drop_duplicates().reset_index(drop=True)

#     # Guardar el archivo Excel
#     combined_df.to_excel(output_path, index=False)

#     return output_path, None

# Función para crear o actualizar el archivo Excel, verificando duplicados
def create_or_update_excel(container_data, size_type_data, condition_data, supplier_data, release_ref_data):
    # Crear un nuevo DataFrame con los datos extraídos
    new_data = pd.DataFrame({
        "Container": container_data,
        "Size/Type": size_type_data,
        "Condition": condition_data,
        "Supplier": supplier_data,
        "Supplier Release Ref": release_ref_data
    })

    return new_data

@app.route('/', methods=['GET', 'POST'])
# def upload_file():
#     if request.method == 'POST':
#         if 'file' not in request.files:
#             return redirect(request.url)
#         file = request.files['file']
#         if file.filename == '':
#             return redirect(request.url)

#         if file and allowed_file(file.filename):
#             filename = secure_filename(file.filename)
#             file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
#             file.save(file_path)

#             container_data, size_type_data, condition_data, supplier_data, release_ref_data = extract_pdf_info(file_path)

#             if container_data:
#                 processed_file_path, duplicates = create_or_update_excel(container_data, size_type_data, condition_data, supplier_data, release_ref_data, "stock_sade.xlsx")

#                 if duplicates:
#                     return f"The following containers already exist in the file and cannot be added: {', '.join(duplicates)}"

#                 return redirect(url_for('confirmation', filename=os.path.basename(processed_file_path)))
#             else:
#                 return "No valid container numbers found in the PDF."

#     return render_template('upload.html')
@app.route('/', methods=['GET', 'POST'])
def upload_file():
    if request.method == 'POST':
        if 'file' not in request.files:
            return redirect(request.url)
        file = request.files['file']
        if file.filename == '':
            return redirect(request.url)

        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)

            container_data, size_type_data, condition_data, supplier_data, release_ref_data = extract_pdf_info(file_path)

            if container_data:
                df = create_or_update_excel(container_data, size_type_data, condition_data, supplier_data, release_ref_data)
                # Enumerate the data here
                enumerated_data = list(enumerate(df.to_dict(orient='records')))
                return render_template('index.html', data=enumerated_data)
            else:
                return render_template('index.html')

    return render_template('index.html')

@app.route('/download_excel')
def download_excel():
    # Crear el DataFrame con los datos
    container_data = request.args.getlist('Container')
    size_type_data = request.args.getlist('Size/Type')
    condition_data = request.args.getlist('Condition')
    supplier_data = request.args.getlist('Supplier')
    release_ref_data = request.args.getlist('Supplier Release Ref')

    df = pd.DataFrame({
        "Container": container_data,
        "Size/Type": size_type_data,
        "Condition": condition_data,
        "Supplier": supplier_data,
        "Supplier Release Ref": release_ref_data
    })

    # Crear un buffer para el archivo Excel
    excel_buffer = io.BytesIO()

    # Guardar el DataFrame en el buffer como un archivo Excel
    with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Containers')

    # Volver al inicio del buffer para que se pueda leer
    excel_buffer.seek(0)

    # Enviar el archivo como descarga
    return send_file(
        excel_buffer,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        download_name='container_data.xlsx',
        as_attachment=True
    )

@app.route('/confirmation/<filename>')
def confirmation(filename):
    return render_template('confirmation.html', filename=filename)

if __name__ == "__main__":
    app.run(debug=True)
