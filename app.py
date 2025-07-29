#!/usr/bin/env python3
"""
Simple API and Dashboard for WCAG Scanner
========================================

This module implements a minimal web server that exposes an HTTP API for
running the WCAG scanner on a remote URL.  It also serves a lightweight
dashboard so non‑technical users can enter a URL, run the scan and download
the resulting spreadsheet.  The server is implemented using only Python's
built‑in ``http.server`` so that it can run without installing any third‑party
web frameworks.

Endpoints
---------

- ``GET /``: Render the dashboard page ``templates/index.html``.
- ``POST /scan``: Accept a URL via form data or JSON and return an Excel
  report.  Returns a JSON error on failure.
- ``GET /static/<path>``: Serve files from the ``static`` directory.

Internally the server delegates HTML retrieval, accessibility analysis and
report generation to functions defined in ``wcag_scanner.py``.  These helper
functions use requests, BeautifulSoup, pandas and openpyxl (which are
preinstalled in the environment) to perform the work.

To run the server:

    python app.py

It listens on port 5000 by default.  Set the environment variable
``PORT`` to change the port.  The ``LOGO_PATH`` environment variable may
also be set to override the default logo path used in reports.
"""

import io
import json
import os
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime

from wcag_scanner import (fetch_html_from_url, read_local_file,
                          run_accessibility_checks, write_report)


# Determine where to find the logo for reports.  By default we assume it
# lives in the static directory.
LOGO_PATH = os.environ.get('LOGO_PATH', os.path.join('static', 'logo.png'))


class WCAGRequestHandler(BaseHTTPRequestHandler):
    """Custom request handler serving the dashboard and scan endpoint."""

    server_version = "WCAGScannerHTTP/1.0"

    def _send_json(self, data: dict, status: int = 200):
        """Helper to send a JSON response."""
        body = json.dumps(data).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, file_path: str, content_type: str = 'application/octet-stream', disposition: str = None):
        """Serve a file from disk to the client."""
        try:
            with open(file_path, 'rb') as fh:
                data = fh.read()
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            if disposition:
                self.send_header('Content-Disposition', disposition)
            # Simple caching policy: do not cache HTML and JS to ensure latest updates
            if content_type.startswith('text/'):
                self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.end_headers()
            self.wfile.write(data)
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        """Handle GET requests for the dashboard and static files."""
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        # Serve root page
        if path == '/' or path == '':
            # Serve templates/index.html
            index_path = os.path.join('templates', 'index.html')
            return self._serve_file(index_path, content_type='text/html; charset=utf-8')
        # GET /scan?url=... or /scan?file=...
        if path == '/scan':
            # parse query parameters
            params = urllib.parse.parse_qs(parsed.query)
            url = params.get('url', [None])[0]
            file_path = params.get('file', [None])[0]
            if not url and not file_path:
                return self._send_json({'error': 'Please provide a url or file parameter.'}, 400)
            # Fetch HTML
            if url:
                html = fetch_html_from_url(url)
                if html is None:
                    return self._send_json({'error': f'Unable to retrieve content from {url}.'}, 500)
            else:
                html = read_local_file(file_path)
                if html is None:
                    return self._send_json({'error': f'Unable to read file {file_path}.'}, 500)
            # Run accessibility checks
            issues = run_accessibility_checks(html)
            # Generate report
            timestamp = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
            report_name = f'report_{timestamp}.xlsx'
            tmp_path = os.path.join('/tmp', report_name)
            # Provide the URL or file path to write_report so it can be shown in the summary sheet
            summary_id = url if url else file_path
            write_report(issues, tmp_path, LOGO_PATH, url=summary_id)
            disposition = f'attachment; filename="{report_name}"'
            self._serve_file(tmp_path,
                             content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                             disposition=disposition)
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            return
        # Serve static files
        if path.startswith('/static/'):
            rel_path = path.lstrip('/')  # remove leading slash
            return self._serve_file(rel_path, content_type=self._guess_mime_type(rel_path))
        # Unknown path
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        """Handle POST requests for the scan endpoint."""
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path != '/scan':
            self.send_response(404)
            self.end_headers()
            return
        # Determine content length and read body
        length = int(self.headers.get('Content-Length', 0))
        raw_body = self.rfile.read(length)
        content_type = self.headers.get('Content-Type', '')
        params = {}
        # Parse depending on content type
        if 'application/json' in content_type:
            try:
                params = json.loads(raw_body.decode('utf-8'))
            except json.JSONDecodeError:
                return self._send_json({'error': 'Invalid JSON body.'}, 400)
        elif 'application/x-www-form-urlencoded' in content_type:
            qs = raw_body.decode('utf-8')
            params = {k: v[0] for k, v in urllib.parse.parse_qs(qs).items()}
        else:
            # Unsupported content type
            return self._send_json({'error': f'Unsupported Content-Type: {content_type}'}, 415)

        url = params.get('url')
        file_path = params.get('file')  # not used in dashboard; reserved for API clients
        if not url and not file_path:
            return self._send_json({'error': 'Please provide a url or file parameter.'}, 400)
        # Fetch HTML
        if url:
            html = fetch_html_from_url(url)
            if html is None:
                return self._send_json({'error': f'Unable to retrieve content from {url}.'}, 500)
        else:
            html = read_local_file(file_path)
            if html is None:
                return self._send_json({'error': f'Unable to read file {file_path}.'}, 500)
        # Run accessibility checks
        issues = run_accessibility_checks(html)
        # Generate report to temporary file
        timestamp = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
        report_name = f'report_{timestamp}.xlsx'
        tmp_path = os.path.join('/tmp', report_name)
        # Provide the URL or file path to write_report so it can be shown in the summary sheet
        summary_id = url if url else file_path
        write_report(issues, tmp_path, LOGO_PATH, url=summary_id)
        # Serve the file back to the client
        disposition = f'attachment; filename="{report_name}"'
        self._serve_file(tmp_path,
                         content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                         disposition=disposition)
        # Clean up
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    @staticmethod
    def _guess_mime_type(filename: str) -> str:
        """Very simple MIME type guesser based on file extension."""
        ext = os.path.splitext(filename)[1].lower()
        if ext in ('.png', '.jpg', '.jpeg', '.gif'):
            return f'image/{ext.lstrip(".")}'
        if ext == '.css':
            return 'text/css; charset=utf-8'
        if ext == '.js':
            return 'application/javascript; charset=utf-8'
        if ext in ('.html', '.htm'):
            return 'text/html; charset=utf-8'
        return 'application/octet-stream'


def run_server(port: int = 5000):
    """Start the HTTP server on the given port."""
    server_address = ('', port)
    httpd = HTTPServer(server_address, WCAGRequestHandler)
    print(f"Serving on port {port}.  Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == '__main__':
    # Determine port from environment or default to 5000
    port = int(os.environ.get('PORT', '5000'))
    run_server(port)