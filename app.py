from flask import Flask, request, render_template_string, send_file, redirect, url_for, flash, get_flashed_messages
import os
import io
import csv
import fitz  # PyMuPDF for reading PDFs
import pdfplumber
from tqdm import tqdm

app = Flask(__name__)
app.secret_key = 'supersecretkey'

PDF_FOLDER = './pdfs'
app.config['UPLOAD_FOLDER'] = PDF_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

last_results = []

base_template = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{{ title }}</title>
<style>
  body { font-family: Arial, sans-serif; margin: 0; background-color: #f4f4f4; }
  .sidebar { width: 200px; background: #333; height: 100vh; position: fixed; top: 0; left: 0; padding-top: 20px; }
  .sidebar a { display: block; color: white; padding: 16px; text-decoration: none; }
  .sidebar a:hover { background-color: #575757; }
  .content { margin-left: 220px; padding: 20px; }
  .spinner { display: none; margin-top: 20px; }
  .flash { background-color: #dff0d8; color: #3c763d; padding: 10px; margin-bottom: 20px; border: 1px solid #d6e9c6; border-radius: 5px; }
</style>
<script>
  function showSpinner() {
    document.getElementById('spinner').style.display = 'block';
  }
</script>
</head>
<body>
<div class="sidebar">
  <a href="/">Home</a>
  <a href="/pdf-search">PDF Search Tool</a>
  <a href="/ocr-check">OCR Tool</a>
</div>
<div class="content">
  {% with messages = get_flashed_messages() %}
    {% if messages %}
      {% for message in messages %}
        <div class="flash">{{ message }}</div>
      {% endfor %}
    {% endif %}
  {% endwith %}
  {{ content|safe }}
</div>
</body>
</html>
"""

@app.route('/')
def home():
    return render_template_string(base_template, title="Home", content="""
    <h1>Welcome to the PDF Tools Suite</h1>
    <p>Select a tool from the sidebar.</p>
    """)

@app.route('/pdf-search', methods=['GET', 'POST'])
def upload_terms():
    global last_results
    last_results = []
    if request.method == 'POST':
        terms_text = request.form['terms']
        terms = [term.strip() for term in terms_text.splitlines() if term.strip()]
        results = search_pdfs_for_terms(terms)
        last_results = results
        rows_html = ''.join(
            f"<tr><td>{row['term']}</td><td>{row['filename']}</td><td>{row['page']}</td><td>{row['context']}</td></tr>"
            for row in results
        )
        return render_template_string(base_template, title="PDF Search", content=f"""
        <h1>PDF Search Tool</h1>

        <h2>Upload PDFs</h2>
        <form action="/upload" method="post" enctype="multipart/form-data">
          <input type="file" name="file" multiple><br><br>
          <input type="submit" value="Upload PDFs">
        </form>

        <hr>

        <h2>Search Terms</h2>
        <form method="post" onsubmit="showSpinner()">
          <textarea name="terms" rows="10" placeholder="Enter one search term per line..."></textarea><br><br>
          <input type="submit" value="Search">
        </form>

        <div id="spinner" class="spinner">
          <p>Searching PDFs... Please wait.</p>
        </div>

        <h2>Results</h2>
        <table border="1">
          <tr><th>Term</th><th>Filename</th><th>Page</th><th>Context</th></tr>
          {rows_html}
        </table>
        <br><a href="/download">Download CSV</a>
        """)
    return render_template_string(base_template, title="PDF Search", content="""
    <h1>PDF Search Tool</h1>

    <h2>Upload PDFs</h2>
    <form action="/upload" method="post" enctype="multipart/form-data">
      <input type="file" name="file" multiple><br><br>
      <input type="submit" value="Upload PDFs">
    </form>

    <hr>

    <h2>Search Terms</h2>
    <form method="post" onsubmit="showSpinner()">
      <textarea name="terms" rows="10" placeholder="Enter one search term per line..."></textarea><br><br>
      <input type="submit" value="Search">
    </form>

    <div id="spinner" class="spinner">
      <p>Searching PDFs... Please wait.</p>
    </div>
    """)

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return redirect(url_for('upload_terms'))
    files = request.files.getlist('file')
    uploaded_files = []
    for file in files:
        if file.filename.endswith('.pdf'):
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], file.filename))
            uploaded_files.append(file.filename)
    if uploaded_files:
        flash(f"Successfully uploaded: {', '.join(uploaded_files)}")
    else:
        flash("No valid PDF files uploaded.")
    return redirect(url_for('upload_terms'))

@app.route('/ocr-check', methods=['GET', 'POST'])
def ocr_check():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash("No file part")
            return redirect(request.url)
        file = request.files['file']
        if file.filename == '' or not file.filename.endswith('.pdf'):
            flash("Invalid file format. Please upload a PDF.")
            return redirect(request.url)
        filepath = os.path.join(PDF_FOLDER, file.filename)
        file.save(filepath)
        all_text = ''
        with pdfplumber.open(filepath) as pdf:
            for pdf_page in pdf.pages:
                page_text = pdf_page.extract_text()
                if page_text:
                    all_text += '\n' + page_text
        metadata = pdfplumber.open(filepath).metadata
        percent = "N/A (dictionary check disabled)"
        return render_template_string(base_template, title="OCR Tool", content=f"""
        <h1>How good is the OCR?</h1>
        <p><strong>File:</strong> {file.filename}</p>
        <p><strong>English Percentage:</strong> {percent}</p>
        <h2>Metadata:</h2>
        <pre>{metadata}</pre>
        <h2>Extracted Text:</h2>
        <pre>{all_text}</pre>
        <a href="/ocr-check">Analyze another file</a>
        """)
    return render_template_string(base_template, title="OCR Tool", content="""
    <h1>How good is the OCR?</h1>
    <form method="post" enctype="multipart/form-data">
      <input type="file" name="file" accept="application/pdf"><br><br>
      <input type="submit" value="Upload and Analyze">
    </form>
    """)

@app.route('/download')
def download_csv():
    if not last_results:
        return 'No results to download.', 400
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=['term', 'filename', 'page', 'context'])
    writer.writeheader()
    for row in last_results:
        writer.writerow(row)
    output.seek(0)
    return send_file(io.BytesIO(output.read().encode()), mimetype='text/csv', as_attachment=True, download_name='search_results.csv')

def search_pdfs_for_terms(terms):
    results = []
    pdf_files = [f for f in os.listdir(PDF_FOLDER) if f.lower().endswith('.pdf')]
    for filename in tqdm(pdf_files, desc="Processing PDFs"):
        filepath = os.path.join(PDF_FOLDER, filename)
        try:
            doc = fitz.open(filepath)
            for page_number, page in enumerate(doc):
                text = page.get_text().lower()
                for term in terms:
                    if term.lower() in text:
                        idx = text.find(term.lower())
                        start = max(0, idx - 30)
                        end = min(len(text), idx + len(term) + 30)
                        context = text[start:end].replace('\n', ' ')
                        results.append({
                            'term': term,
                            'filename': filename,
                            'page': page_number + 1,
                            'context': context
                        })
        except Exception as e:
            print(f"Error reading {filename}: {e}")
    return results

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    if not os.path.exists(PDF_FOLDER):
        os.makedirs(PDF_FOLDER)
    app.run(host='0.0.0.0', port=port)
