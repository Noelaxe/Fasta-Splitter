import os
import re
import zipfile
import shutil
import tempfile
from flask import Flask, request, send_file, render_template, jsonify
from werkzeug.utils import secure_filename

# Import the split_fasta function from the user's script
from Splitting_fasta_2 import split_fasta

app = Flask(__name__)

# Configure upload limit to 500MB as requested by the user
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024

def validate_fasta(file_path):
    """
    Validates a FASTA file.
    Checks:
    - If the file is not empty.
    - If the first non-empty line starts with '>'.
    - Counts total sequences.
    Returns (is_valid, error_message, sequence_count)
    """
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
                
                # First non-empty line must start with '>'
                if sequence_count == 0 and has_content:
                    return (
                        False, 
                        f"Validation Error: First non-empty line (line {line_num}) does not start with '>'. FASTA format requires headers to start with '>'.", 
                        0
                    )
    except Exception as e:
        return False, f"Failed to read file: {str(e)}", 0

    if not has_content:
        return False, "Validation Error: The input FASTA file is empty.", 0
        
    if sequence_count == 0:
        return False, "Validation Error: No sequences found. A valid FASTA file must contain at least one header starting with '>'.", 0
        
    return True, "", sequence_count

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/split', methods=['POST'])
def handle_split():
    # 1. Parse and validate split limit
    try:
        split_limit_val = request.form.get('split_limit', '10')
        split_limit = int(split_limit_val)
        if split_limit <= 0:
            return jsonify({'success': False, 'error': 'Number of sequences per file must be a positive integer greater than 0.'}), 400
    except ValueError:
        return jsonify({'success': False, 'error': 'Invalid number of sequences per file. Must be an integer.'}), 400

    # 2. Setup isolated temporary directory for thread-safe concurrent execution
    temp_dir = tempfile.mkdtemp()
    input_path = os.path.join(temp_dir, "input.fasta")
    
    # Default outputs
    download_filename = "fasta_split_parts.zip"
    output_prefix_base = "fasta_split"
    
    try:
        # Determine source: pasted text or uploaded file
        fasta_file = request.files.get('fasta_file')
        fasta_text = request.form.get('fasta_text', '').strip()
        
        has_file = fasta_file and fasta_file.filename != ''
        has_text = fasta_text != ''
        
        if not has_file and not has_text:
            return jsonify({'success': False, 'error': 'Please provide sequence data by either pasting FASTA text or uploading a file.'}), 400
            
        if has_file:
            # Secure the filename
            filename = secure_filename(fasta_file.filename)
            # Ensure it has a safe extension
            base_name, ext = os.path.splitext(filename)
            if ext.lower() not in ['.fasta', '.fa', '.txt', '.seq', '.fna', '.faa', '.zip']:
                return jsonify({'success': False, 'error': 'Invalid file format. Please upload a FASTA file (.fasta, .fa, .txt, .seq, .fna, .faa) or a ZIP archive (.zip).'}), 400
            
            uploaded_path = os.path.join(temp_dir, filename)
            fasta_file.save(uploaded_path)
            
            if ext.lower() == '.zip':
                # It is a zip archive, extract it
                if not zipfile.is_zipfile(uploaded_path):
                    return jsonify({'success': False, 'error': 'The uploaded file is not a valid ZIP archive.'}), 400
                
                extract_dir = os.path.join(temp_dir, "extracted")
                os.makedirs(extract_dir, exist_ok=True)
                with zipfile.ZipFile(uploaded_path, 'r') as ref:
                    ref.extractall(extract_dir)
                    
                # Search recursively for a valid FASTA file
                found_fasta = None
                for root, dirs, files in os.walk(extract_dir):
                    for file in files:
                        _, f_ext = os.path.splitext(file.lower())
                        if f_ext in ['.fasta', '.fa', '.txt', '.seq', '.fna', '.faa']:
                            found_fasta = os.path.join(root, file)
                            break
                    if found_fasta:
                        break
                        
                if not found_fasta:
                    return jsonify({'success': False, 'error': 'No valid FASTA files (.fasta, .fa, .txt, .seq, .fna, .faa) were found inside the uploaded ZIP archive.'}), 400
                    
                # Copy the found FASTA file to the input path
                shutil.copy(found_fasta, input_path)
            else:
                # Direct FASTA file
                shutil.move(uploaded_path, input_path)
            
            if base_name:
                output_prefix_base = base_name
                
            download_filename = f"{output_prefix_base}_parts.zip"
        else:
            # Save the pasted text to the input path
            with open(input_path, "w", encoding="utf-8") as f:
                f.write(fasta_text)
                
        # 3. Perform FASTA Safety and Validation Check
        is_valid, err_msg, seq_count = validate_fasta(input_path)
        if not is_valid:
            return jsonify({'success': False, 'error': err_msg}), 400
            
        # 4. Execute the splitting using the project's backend script
        output_prefix = os.path.join(temp_dir, output_prefix_base)
        split_fasta(input_path, output_prefix, split_limit)
        
        # 5. Pack the resulting split files into a ZIP archive
        zip_path = os.path.join(temp_dir, "fasta_split_parts.zip")
        
        files_to_zip = []
        for filename in os.listdir(temp_dir):
            if filename.startswith(f"{output_prefix_base}_Parts_") and filename.endswith(".fasta"):
                full_file_path = os.path.join(temp_dir, filename)
                # Skip the empty placeholder _Parts_0.fasta if it's empty
                if filename == f"{output_prefix_base}_Parts_0.fasta" and os.path.getsize(full_file_path) == 0:
                    continue
                # Also double-check size of other parts just in case
                if os.path.getsize(full_file_path) > 0:
                    files_to_zip.append(full_file_path)
                    
        if not files_to_zip:
            return jsonify({'success': False, 'error': 'Splitting resulted in no non-empty output files. Please check your FASTA sequence format.'}), 400
            
        # Sort files so they are added to ZIP in correct order
        files_to_zip.sort(key=lambda x: [int(s) if s.isdigit() else s for s in re.split(r'(\d+)', x)])
        
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for file_path in files_to_zip:
                # Add to zip using just the base name
                zip_file.write(file_path, os.path.basename(file_path))
                
        # 6. Serve the ZIP file, then clean up the entire temporary directory
        # To delete the directory after sending the file, we read the ZIP data into memory, 
        # or we send it and clean up using Flask's after_this_request
        
        # Safe cleanup: read zip file to memory first, then remove temp_dir, then send
        return_data = None
        with open(zip_path, 'rb') as f:
            return_data = f.read()
            
        # Remove the temp directory safely
        shutil.rmtree(temp_dir)
        
        # Create a dynamic in-memory response
        from io import BytesIO
        mem_file = BytesIO(return_data)
        mem_file.seek(0)
        
        return send_file(
            mem_file,
            mimetype='application/zip',
            as_attachment=True,
            download_name=download_filename
        )
        
    except Exception as e:
        # Guarantee cleanup in case of unexpected errors
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        return jsonify({'success': False, 'error': f'An unexpected error occurred during processing: {str(e)}'}), 500

if __name__ == '__main__':
    # Listen on localhost:5000 for local validation
    app.run(host='127.0.0.1', port=5000, debug=True)
