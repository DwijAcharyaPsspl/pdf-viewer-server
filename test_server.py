#!/usr/bin/env python3
"""Test script for PDF server"""

import socketio
import time

# Create Socket.IO client
sio = socketio.Client()

@sio.on('connected')
def on_connect(data):
    print(f"✓ Connected! Session: {data['session_id']}")
    
    # Load PDF
    sio.emit('loadPDF', {'pdfId': 'sample'})  # Change to your PDF name

@sio.on('pdfLoaded')
def on_pdf_loaded(data):
    if data.get('success'):
        print(f"✓ PDF Loaded: {data['totalPages']} pages")
        
        # Request first page
        sio.emit('requestPage', {
            'pageNum': 1,
            'options': {'quality': 'high'}
        })
    else:
        print(f"✗ PDF Load Failed: {data.get('error')}")

@sio.on('pageData')
def on_page_data(data):
    if 'error' not in data:
        print(f"✓ Page {data['pageNum']} received")
        print(f"  Size: {data['width']}x{data['height']}")
        print(f"  URL: {data['imageUrl']}")
        print(f"  Base64 length: {len(data.get('imageBase64', ''))} chars")
    else:
        print(f"✗ Page Error: {data['error']}")
    
    # Disconnect after test
    sio.disconnect()

try:
    print("Connecting to server...")
    sio.connect('http://localhost:5000')
    time.sleep(5)  # Wait for responses
except Exception as e:
    print(f"✗ Connection failed: {e}")