#!/usr/bin/env python3
"""
Flask wrapper for WCAG Scanner
------------------------------

This module provides a Flask application that wraps the accessibility scanner
functions defined in ``wcag_scanner.py``.  It exposes two endpoints:

  - ``GET /`` renders the dashboard page.
  - ``POST /scan`` accepts a URL or local file path and returns an Excel
    report as a file download.

It also serves static assets (the logo) and templates.  This application
requires the ``flask`` package.  When deploying to a platform like
PythonAnywhere, configure your WSGI file to import ``app`` from this module:

    from flask_app import app as application

and ensure that the working directory contains the ``templates`` and ``static``
folders.
"""

import io
import os
from datetime import datetime
from flask import Flask, request, render_template, send_file, jsonify

from wcag_scanner import (fetch_html_from_url, read_local_file,
                          run_accessibility_checks, write_report)

# Create Flask application
app = Flask(__name__, static_url_path='/static', static_folder='static',
            template_folder='templates')

# Default logo path used in report generation; can be overridden via
# environment variable ``LOGO_PATH``.
LOGO_PATH = os.environ.get('LOGO_PATH', os.path.join('static', 'logo.png'))


@app.route('/', methods=['GET'])
def index():
    """Render the dashboard page."""
    return render_template('index.html')


@app.route('/scan', methods=['GET', 'POST'])
def scan():
    """Perform an accessibility scan and return the report."""
    url = None
    file_path = None
    if request.method == 'POST':
        # Accept both form and JSON for POST
        if request.is_json:
            data = request.get_json(silent=True) or {}
            url = data.get('url')
            file_path = data.get('file')
        else:
            url = request.form.get('url')
            file_path = request.form.get('file')
    else:
        # GET: read from query string
        url = request.args.get('url')
        file_path = request.args.get('file')
    if not url and not file_path:
        return jsonify({'error': 'Please provide a URL or file parameter.'}), 400
    # Fetch HTML
    if url:
        html = fetch_html_from_url(url)
        if html is None:
            return jsonify({'error': f'Unable to retrieve content from {url}.'}), 500
    else:
        html = read_local_file(file_path)
        if html is None:
            return jsonify({'error': f'Unable to read file {file_path}.'}), 500
    # Run checks
    issues = run_accessibility_checks(html)
    # Prepare report
    timestamp = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    report_name = f'report_{timestamp}.xlsx'
    tmp_path = os.path.join('/tmp', report_name)
    # Provide the URL or file path to write_report so it can be shown in the summary sheet
    summary_id = url if url else file_path
    write_report(issues, tmp_path, LOGO_PATH, url=summary_id)
    buffer = io.BytesIO()
    with open(tmp_path, 'rb') as fh:
        buffer.write(fh.read())
    buffer.seek(0)
    try:
        os.remove(tmp_path)
    except OSError:
        pass
    return send_file(buffer,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True,
                     download_name=report_name)


if __name__ == '__main__':
    # Only for local testing.  Use a production WSGI server on hosting platforms.
    port = int(os.environ.get('PORT', '5000'))
    app.run(host='0.0.0.0', port=port, debug=True)