#!/usr/bin/env python3

"""
PDF Viewer Server for Spectacles
Python-based server - No build tool issues!
Installation:
pip install flask flask-cors flask-socketio pymupdf pillow

Usage:
python server.py
"""

from flask import Flask, jsonify, send_file
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import fitz  # PyMuPDF
from PIL import Image
import io
import os
import time
import base64
from pathlib import Path
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Configuration
PDF_DIR = Path('pdfs')
TEMP_DIR = Path('temp_pages')
CACHE_DIR = Path('cache')

# Create directories
PDF_DIR.mkdir(exist_ok=True)
TEMP_DIR.mkdir(exist_ok=True)
CACHE_DIR.mkdir(exist_ok=True)

# Global storage
sessions = {}
pdf_cache = {}

class PDFProcessor:
    """Handle all PDF processing operations"""
    
    @staticmethod
    def load_pdf(pdf_path):
        """Load PDF and return document info"""
        try:
            if pdf_path in pdf_cache:
                logger.info(f"Loading PDF from cache: {pdf_path}")
                return pdf_cache[pdf_path]
            
            doc = fitz.open(pdf_path)
            
            # Extract metadata
            metadata = doc.metadata or {}
            pdf_info = {
                'document': doc,
                'total_pages': doc.page_count,
                'path': pdf_path,
                'metadata': {
                    'title': metadata.get('title', 'Untitled'),
                    'author': metadata.get('author', 'Unknown'),
                    'subject': metadata.get('subject', ''),
                    'creator': metadata.get('creator', ''),
                    'pages': doc.page_count
                }
            }
            
            pdf_cache[pdf_path] = pdf_info
            logger.info(f"PDF loaded: {pdf_path} ({doc.page_count} pages)")
            return pdf_info
            
        except Exception as e:
            logger.error(f"Error loading PDF: {e}")
            raise

    @staticmethod
    def render_page(doc, page_num, quality='high', dpi=150):
        """Render a specific page to image"""
        try:
            # Get page (PyMuPDF uses 0-based indexing)
            page = doc.load_page(page_num - 1)
            
            # Set zoom based on quality
            zoom = 2.0 if quality == 'high' else 1.5
            mat = fitz.Matrix(zoom, zoom)
            
            # Render page to pixmap
            pix = page.get_pixmap(matrix=mat, alpha=False)
            
            # Convert to PIL Image
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            
            # Resize to target size (1024x1024 max)
            target_size = 1024 if quality == 'high' else 768
            img.thumbnail((target_size, target_size), Image.Resampling.LANCZOS)
            
            # Save to bytes
            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format='PNG', optimize=True)
            img_byte_arr.seek(0)
            
            return {
                'page_num': page_num,
                'width': img.width,
                'height': img.height,
                'image_data': img_byte_arr.getvalue(),
                'image_base64': base64.b64encode(img_byte_arr.getvalue()).decode('utf-8'),
                'timestamp': time.time()
            }
            
        except Exception as e:
            logger.error(f"Error rendering page {page_num}: {e}")
            raise

    @staticmethod
    def save_page_image(image_data, session_id, page_num):
        """Save rendered page to temp directory and return URL"""
        try:
            session_dir = TEMP_DIR / session_id
            session_dir.mkdir(exist_ok=True)
            
            filename = f"page_{page_num}.png"
            filepath = session_dir / filename
            
            # Save image
            with open(filepath, 'wb') as f:
                f.write(image_data)
            
            # Return URL path
            return f"/pages/{session_id}/{filename}"
            
        except Exception as e:
            logger.error(f"Error saving page image: {e}")
            raise

# Initialize processor
pdf_processor = PDFProcessor()

# ============================================
# REST API Routes
# ============================================

@app.route('/health')
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'uptime': time.time(),
        'active_sessions': len(sessions),
        'cached_pdfs': len(pdf_cache)
    })

@app.route('/api/pdfs')
def list_pdfs():
    """List all available PDF files"""
    try:
        pdf_files = []
        for file in PDF_DIR.glob('*.pdf'):
            pdf_files.append({
                'id': file.stem,
                'filename': file.name,
                'path': f"/pdfs/{file.name}"
            })
        
        return jsonify({
            'success': True,
            'pdfs': pdf_files,
            'count': len(pdf_files)
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/pdf/<pdf_id>/info')
def get_pdf_info(pdf_id):
    """Get PDF metadata and page count"""
    try:
        pdf_path = str(PDF_DIR / f"{pdf_id}.pdf")
        if not os.path.exists(pdf_path):
            return jsonify({
                'success': False,
                'error': 'PDF not found'
            }), 404
        
        pdf_info = pdf_processor.load_pdf(pdf_path)
        
        return jsonify({
            'success': True,
            'id': pdf_id,
            'total_pages': pdf_info['total_pages'],
            'metadata': pdf_info['metadata']
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# NEW: Add native PDF serving endpoints
@app.route('/api/pdf/<pdf_id>/raw')
def serve_raw_pdf(pdf_id):
    """Serve the raw PDF file directly"""
    try:
        pdf_path = PDF_DIR / f"{pdf_id}.pdf"
        if not pdf_path.exists():
            return jsonify({'error': 'PDF not found'}), 404
        
        return send_file(pdf_path, mimetype='application/pdf', 
                        as_attachment=False)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/pdf/<pdf_id>/base64')
def serve_pdf_base64(pdf_id):
    """Serve PDF as base64 for WebView embedding"""
    try:
        pdf_path = PDF_DIR / f"{pdf_id}.pdf"
        if not pdf_path.exists():
            return jsonify({'error': 'PDF not found'}), 404
            
        with open(pdf_path, 'rb') as f:
            pdf_data = base64.b64encode(f.read()).decode('utf-8')
            
        return jsonify({
            'success': True,
            'pdfData': f"data:application/pdf;base64,{pdf_data}",
            'filename': f"{pdf_id}.pdf"
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/pages/<session_id>/<filename>')
def serve_page_image(session_id, filename):
    """Serve rendered page images"""
    try:
        filepath = TEMP_DIR / session_id / filename
        if filepath.exists():
            return send_file(filepath, mimetype='image/png')
        else:
            return "File not found", 404
    except Exception as e:
        logger.error(f"Error serving image: {e}")
        return "Error serving image", 500

# ============================================
# WebSocket Event Handlers
# ============================================

@socketio.on('connect')
def handle_connect():
    """Handle new WebSocket connection"""
    session_id = f"session_{int(time.time())}_{os.urandom(4).hex()}"
    sessions[session_id] = {
        'sid': session_id,
        'current_pdf': None,
        'last_activity': time.time()
    }
    
    logger.info(f"Client connected: {session_id}")
    emit('connected', {
        'session_id': session_id,
        'message': 'Connected to PDF viewer server'
    })

@socketio.on('disconnect')
def handle_disconnect():
    """Handle WebSocket disconnection"""
    logger.info("Client disconnected")

@socketio.on('loadPDF')
def handle_load_pdf(data):
    """Handle PDF load request"""
    try:
        pdf_id = data.get('pdfId')
        pdf_path = str(PDF_DIR / f"{pdf_id}.pdf")
        
        if not os.path.exists(pdf_path):
            emit('pdfLoaded', {
                'success': False,
                'error': 'PDF file not found'
            })
            return
        
        # Load PDF
        pdf_info = pdf_processor.load_pdf(pdf_path)
        
        # Store in session
        session_data = next((s for s in sessions.values() if s.get('sid')), None)
        if session_data:
            session_data['current_pdf'] = pdf_path
        
        emit('pdfLoaded', {
            'success': True,
            'pdfId': pdf_id,
            'totalPages': pdf_info['total_pages'],
            'metadata': pdf_info['metadata']
        })
        
        logger.info(f"PDF loaded: {pdf_id}")
        
    except Exception as e:
        logger.error(f"Error loading PDF: {e}")
        emit('pdfLoaded', {
            'success': False,
            'error': str(e)
        })

@socketio.on('requestPage')
def handle_request_page(data):
    """Handle page render request"""
    try:
        page_num = data.get('pageNum')
        options = data.get('options', {})
        quality = options.get('quality', 'high')
        
        # Get current PDF path from session
        session_data = next((s for s in sessions.values() if s.get('sid')), None)
        if not session_data or not session_data.get('current_pdf'):
            emit('pageData', {'error': 'No PDF loaded'})
            return
        
        pdf_path = session_data['current_pdf']
        pdf_info = pdf_processor.load_pdf(pdf_path)
        
        # Render page
        page_data = pdf_processor.render_page(
            pdf_info['document'],
            page_num,
            quality=quality
        )
        
        # Save image and get URL
        session_id = session_data['sid']
        image_url = pdf_processor.save_page_image(
            page_data['image_data'],
            session_id,
            page_num
        )
        
        # Send response
        emit('pageData', {
            'pageNum': page_data['page_num'],
            'width': page_data['width'],
            'height': page_data['height'],
            'imageUrl': f"http://localhost:5000{image_url}",
            'imageBase64': page_data['image_base64'],
            'timestamp': page_data['timestamp']
        })
        
        logger.info(f"Page {page_num} rendered and sent")
        
    except Exception as e:
        logger.error(f"Error rendering page: {e}")
        emit('pageData', {'error': str(e)})

@socketio.on('preloadPages')
def handle_preload_pages(data):
    """Handle multiple page preload request"""
    try:
        page_nums = data.get('pageNums', [])
        options = data.get('options', {})
        quality = options.get('quality', 'medium')
        
        # Get current PDF
        session_data = next((s for s in sessions.values() if s.get('sid')), None)
        if not session_data or not session_data.get('current_pdf'):
            emit('pagesPreloaded', {'error': 'No PDF loaded'})
            return
        
        pdf_path = session_data['current_pdf']
        pdf_info = pdf_processor.load_pdf(pdf_path)
        
        pages = []
        for page_num in page_nums:
            if 1 <= page_num <= pdf_info['total_pages']:
                page_data = pdf_processor.render_page(
                    pdf_info['document'],
                    page_num,
                    quality=quality
                )
                
                session_id = session_data['sid']
                image_url = pdf_processor.save_page_image(
                    page_data['image_data'],
                    session_id,
                    page_num
                )
                
                pages.append({
                    'pageNum': page_data['page_num'],
                    'width': page_data['width'],
                    'height': page_data['height'],
                    'imageUrl': f"http://localhost:5000{image_url}",
                    'timestamp': page_data['timestamp']
                })
        
        emit('pagesPreloaded', {'pages': pages})
        logger.info(f"Preloaded {len(pages)} pages")
        
    except Exception as e:
        logger.error(f"Error preloading pages: {e}")
        emit('pagesPreloaded', {'error': str(e)})

@socketio.on('ping')
def handle_ping():
    """Handle ping for keepalive"""
    emit('pong', {'timestamp': time.time()})

# ============================================
# Cleanup Tasks
# ============================================

def cleanup_old_sessions():
    """Cleanup old session files periodically"""
    try:
        current_time = time.time()
        timeout = 30 * 60  # 30 minutes
        
        for session_id, session_data in list(sessions.items()):
            if current_time - session_data['last_activity'] > timeout:
                # Remove session directory
                session_dir = TEMP_DIR / session_id
                if session_dir.exists():
                    import shutil
                    shutil.rmtree(session_dir)
                    logger.info(f"Cleaned up session: {session_id}")
                del sessions[session_id]
    except Exception as e:
        logger.error(f"Cleanup error: {e}")

# ============================================
# Main Entry Point
# ============================================

if __name__ == '__main__':
    print("""
╔════════════════════════════════════════╗
║      PDF Viewer Server for Spectacles  ║
║        Python + Flask + PyMuPDF       ║
║         Running on port 5000           ║
╚════════════════════════════════════════╝
""")
    print("WebSocket: ws://localhost:5000")
    print("REST API: http://localhost:5000/api/pdfs")
    print(f"PDF Directory: {PDF_DIR.absolute()}\n")
    
    # Start background cleanup task
    import threading
    def cleanup_loop():
        while True:
            time.sleep(300)  # Run every 5 minutes
            cleanup_old_sessions()
    
    cleanup_thread = threading.Thread(target=cleanup_loop, daemon=True)
    cleanup_thread.start()
    
    # Start server
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)
