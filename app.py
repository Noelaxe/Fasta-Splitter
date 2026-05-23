import os
import re
import zipfile
import shutil
import tempfile
from flask import Flask, request, send_file, render_template, jsonify, after_this_request
from werkzeug.utils import secure_filename

# Import the split_fasta function from the user's script
from Splitting_fasta_2 import split_fasta

app = Flask(__name__)

# Reduced for 2GB RAM server - leave headroom for processing
app.config['MAX_CONTENT_LENGTH'] = 800 * 1024 * 1024  # 800MB max upload

def validate_fasta(file_path):
    """Memory-efficient FASTA validation"""
    sequence_count = 0
    has_content = False
    
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            for line_num, line in enumerate(f, 1):
                stripped = line.strip()
                if not stripped:
                    continue
                has_content = True
                if stripped.startswith(">"):
                    sequence_count += 1
                
                if sequence_count == 0 and has_content and not stripped.startswith(">"):
                    return False, f"Validation Error: First non-empty line (line {line_num}) does not start with '>'.", 0
    except Exception as e:
        return False, f"Failed to read file: {str(e)}", 0

    if not has_content:
        return False, "Validation Error: The input FASTA file is empty.", 0
    if sequence_count == 0:
        return False, "Validation Error: No sequences found.", 0
        
    return True, "", sequence_count


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/split', methods=['POST'])
def handle_split():
    temp_dir = None
    try:
        # 1. Parse split limit
        try:
            split_limit = int(request.form.get('split_limit', '10'))
            if split_limit <= 0:
                return jsonify({'success': False, 'error': 'Number of sequences per file must be > 0.'}), 400
        except ValueError:
            return jsonify({'success': False, 'error': 'Invalid number of sequences per file.'}), 400

        # 2. Create temp directory
        temp_dir = tempfile.mkdtemp()
        input_path = os.path.join(temp_dir, "input.fasta")
        
        # 3. Handle input (file or text)
        fasta_file = request.files.get('fasta_file')
        fasta_text = request.form.get('fasta_text', '').strip()

        output_prefix_base = "fasta_split"
        download_filename = "fasta_split_parts.zip"

        if fasta_file and fasta_file.filename:
            filename = secure_filename(fasta_file.filename)
            _, ext = os.path.splitext(filename.lower())
            
            if ext not in ['.fasta', '.fa', '.txt', '.seq', '.fna', '.faa', '.zip']:
                return jsonify({'success': False, 'error': 'Invalid file format.'}), 400

            uploaded_path = os.path.join(temp_dir, filename)
            fasta_file.save(uploaded_path)

            if ext == '.zip':
                # Extract ZIP and find FASTA
                extract_dir = os.path.join(temp_dir, "extracted")
                os.makedirs(extract_dir, exist_ok=True)
                with zipfile.ZipFile(uploaded_path, 'r') as ref:
                    ref.extractall(extract_dir)
                
                found_fasta = None
                for root, dirs, files in os.walk(extract_dir):
                    for file in files:
                        if file.lower().endswith(('.fasta', '.fa', '.txt', '.seq', '.fna', '.faa')):
                            found_fasta = os.path.join(root, file)
                            break
                    if found_fasta:
                        break
                        
                if not found_fasta:
                    return jsonify({'success': False, 'error': 'No FASTA file found in ZIP.'}), 400
                    
                shutil.copy(found_fasta, input_path)
            else:
                shutil.move(uploaded_path, input_path)

            if filename:
                output_prefix_base = os.path.splitext(filename)[0]
                download_filename = f"{output_prefix_base}_parts.zip"

        elif fasta_text:
            with open(input_path, "w", encoding="utf-8") as f:
                f.write(fasta_text)
        else:
            return jsonify({'success': False, 'error': 'No input data provided.'}), 400

        # 4. Validate
        is_valid, err_msg, _ = validate_fasta(input_path)
        if not is_valid:
            return jsonify({'success': False, 'error': err_msg}), 400

        # 5. Split the FASTA
        output_prefix = os.path.join(temp_dir, output_prefix_base)
        split_fasta(input_path, output_prefix, split_limit)

        # 6. Create ZIP (on disk)
        zip_path = os.path.join(temp_dir, "fasta_split_parts.zip")
        files_to_zip = [
            os.path.join(temp_dir, f) for f in os.listdir(temp_dir)
            if f.startswith(f"{output_prefix_base}_Parts_") and f.endswith(".fasta")
            and os.path.getsize(os.path.join(temp_dir, f)) > 0
        ]
        
        if not files_to_zip:
            return jsonify({'success': False, 'error': 'No output files generated.'}), 400

        files_to_zip.sort(key=lambda x: [int(s) if s.isdigit() else s for s in re.split(r'(\d+)', x)])

        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zip_file:
            for file_path in files_to_zip:
                zip_file.write(file_path, os.path.basename(file_path))

        # 7. Stream the file + cleanup after response (Memory efficient)
        @after_this_request
        def cleanup(response):
            if temp_dir and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                except Exception:
                    pass  # Best effort cleanup
            return response

        return send_file(
            zip_path,
            mimetype='application/zip',
            as_attachment=True,
            download_name=download_filename
        )

    except Exception as e:
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass
        return jsonify({'success': False, 'error': f'Processing error: {str(e)}'}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)  # Change to 0.0.0.0 for server