#!/usr/bin/env python3
"""
WCAG Automated Scanner
======================

This script provides a simple command‑line tool to perform a basic accessibility scan
on a web page or local HTML file.  It was inspired by the features offered in
popular open‑source accessibility scanners such as Pa11y, AInspector for Firefox
and Deque's axe‑core engine.  Those tools allow testers to choose a WCAG
conformance level, run automated rules against a page and export the results
in formats like CSV or JSON【249372618707913†L65-L97】.  They also support running
on the command line and generating reports in spreadsheets【249372618707913†L100-L127】.

Because this environment cannot install external Node packages at run time, this
implementation uses Python's standard libraries together with BeautifulSoup to
parse the markup and perform a handful of WCAG 2.2 Level A/AA checks.  It is not
a replacement for full rule engines like axe‑core—which includes rules for
WCAG 2.0, 2.1 and 2.2 across levels A, AA and AAA【299890540444768†L178-L182】—but it
demonstrates how an automated scan might work and how the results can be
written into a spreadsheet.  If you wish to test with a full rule set, you can
swap out the scanning logic for calls to an open‑source engine such as pa11y
(`pa11y <url> --runner axe --reporter json`) and parse its JSON output into
a DataFrame.

Usage
-----

Run the script with a URL or a path to a local HTML file:

```
python wcag_scanner.py --url https://www.example.com
python wcag_scanner.py --file path/to/page.html
```

The script fetches the markup, runs a small set of accessibility checks and
writes an Excel file (`report.xlsx`) with the results.  A custom
"Perspective Tester" logo is inserted at the top of the spreadsheet to brand
the report.
"""

import argparse
import os
from typing import List, Dict, Optional
import requests
from bs4 import BeautifulSoup
import pandas as pd
from pandas import ExcelWriter
from openpyxl.drawing.image import Image as XLImage


def fetch_html_from_url(url: str) -> Optional[str]:
    """Fetch HTML content from a remote URL.

    Args:
        url: The URL to fetch.

    Returns:
        A string containing the HTML, or ``None`` on failure.
    """
    try:
        response = requests.get(url, timeout=30)
        # If the server blocks requests (returns 403), instruct the user.
        if response.status_code != 200:
            print(
                f"Warning: received status code {response.status_code} from {url}.\n"
                "The script will continue but you might need to provide a local HTML file."
            )
        return response.text
    except Exception as exc:
        print(f"Error fetching {url}: {exc}")
        return None


def read_local_file(path: str) -> Optional[str]:
    """Read HTML content from a local file."""
    if not os.path.isfile(path):
        print(f"File not found: {path}")
        return None
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as fh:
            return fh.read()
    except Exception as exc:
        print(f"Error reading {path}: {exc}")
        return None


def check_images_have_alt(soup: BeautifulSoup) -> List[Dict[str, str]]:
    """Check that all <img> elements include non‑empty alt attributes.

    Returns a list of issue dictionaries.
    """
    issues = []
    for img in soup.find_all('img'):
        alt = img.get('alt')
        if alt is None or alt.strip() == '':
            # Build a CSS selector approximation using the tag's position.
            # We limit the selector to nth-of-type within the parent for readability.
            try:
                index = list(img.parent.find_all('img')).index(img) + 1
            except ValueError:
                index = 1
            selector = f"img:nth-of-type({index})"
            issues.append({
                'rule': 'IMG_ALT',
                'wcag_principle': 'Perceivable',
                'wcag_success_criterion': '1.1.1 Non-text Content',
                'level': 'A',
                'description': 'Image elements must have a text alternative (alt attribute).',
                'context': str(img)[:200],
                'selector': selector,
                'recommendation': 'Add a descriptive alt attribute to the <img> element.'
            })
    return issues


def check_form_inputs_have_labels(soup: BeautifulSoup) -> List[Dict[str, str]]:
    """Check that form controls have associated labels.

    For inputs, selects and textareas, a control should either have a <label> element
    referencing its id or wrap the control.  Controls of type hidden, submit and button
    are ignored.  The check maps to WCAG 2.2 success criterion 3.3.2 Labels or
    Instructions (Level A) and 1.3.1 Info and Relationships (Level A).
    """
    issues = []
    form_controls = soup.find_all(['input', 'select', 'textarea'])
    for control in form_controls:
        if control.name == 'input' and control.get('type') in ['hidden', 'submit', 'button', 'image']:
            continue
        # Determine if the control has an associated label
        has_label = False
        # Check if wrapped by a <label> ancestor
        for parent in control.parents:
            if parent.name == 'label':
                has_label = True
                break
        # Check for <label for="id"> association
        control_id = control.get('id')
        if not has_label and control_id:
            label = soup.find('label', attrs={'for': control_id})
            if label:
                has_label = True
        if not has_label:
            try:
                index = list(control.parent.find_all(control.name)).index(control) + 1
            except ValueError:
                index = 1
            selector = f"{control.name}:nth-of-type({index})"
            issues.append({
                'rule': 'FORM_LABEL',
                'wcag_principle': 'Understandable',
                'wcag_success_criterion': '3.3.2 Labels or Instructions / 1.3.1 Info and Relationships',
                'level': 'A',
                'description': 'Form controls must have associated labels.',
                'context': str(control)[:200],
                'selector': selector,
                'recommendation': 'Add a <label> element referencing the control or wrap the control in a <label>.'
            })
    return issues


def check_links_have_descriptive_text(soup: BeautifulSoup) -> List[Dict[str, str]]:
    """Check that link text is meaningful when read out of context.

    This addresses WCAG 2.2 success criterion 2.4.4 Link Purpose (In Context) at
    Level A and 2.4.9 Link Purpose (Link Only) at Level AAA.  The implementation
    warns when link text is generic (e.g. 'click here', 'more', 'read more').
    """
    generic_phrases = ['click here', 'more', 'read more', 'learn more', 'details']
    issues = []
    for link in soup.find_all('a', href=True):
        text = link.get_text().strip().lower()
        if not text or any(text == phrase or text.startswith(phrase + ' ') for phrase in generic_phrases):
            try:
                index = list(link.parent.find_all('a')).index(link) + 1
            except ValueError:
                index = 1
            selector = f"a:nth-of-type({index})"
            issues.append({
                'rule': 'LINK_TEXT',
                'wcag_principle': 'Understandable',
                'wcag_success_criterion': '2.4.4 Link Purpose (In Context)',
                'level': 'A',
                'description': 'Link text should be descriptive and convey the purpose of the link.',
                'context': str(link)[:200],
                'selector': selector,
                'recommendation': 'Replace generic link text with text that describes the destination or action.'
            })
    return issues


def run_accessibility_checks(html: str) -> List[Dict[str, str]]:
    """Run a series of accessibility checks against HTML.

    Returns a list of issue dictionaries.
    """
    soup = BeautifulSoup(html, 'html.parser')
    issues: List[Dict[str, str]] = []
    issues += check_images_have_alt(soup)
    issues += check_form_inputs_have_labels(soup)
    issues += check_links_have_descriptive_text(soup)
    return issues


def write_report(issues: List[Dict[str, str]], output_path: str, logo_path: str) -> None:
    """Write the collected issues to an Excel spreadsheet with branding.

    Args:
        issues: List of issue dictionaries.
        output_path: Path for the Excel file.
        logo_path: Path to the logo image.
    """
    df = pd.DataFrame(issues)
    expected_cols = [
        'rule',
        'wcag_principle',
        'wcag_success_criterion',
        'level',
        'description',
        'context',
        'selector',
        'recommendation',
    ]
    for col in expected_cols:
        if col not in df.columns:
            df[col] = ''
    df = df[expected_cols]
    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        start_row = 7
        df.to_excel(writer, sheet_name='Report', index=False, startrow=start_row)
        workbook = writer.book
        worksheet = writer.sheets['Report']
        # Insert logo if provided
        if os.path.isfile(logo_path):
            try:
                img = XLImage(logo_path)
                img.width = 200
                img.height = 80
                worksheet.add_image(img, 'A1')
            except Exception as exc:
                print(f"Could not insert logo: {exc}")
        # Title and summary
        worksheet['A4'] = 'WCAG Accessibility Scan Report'
        worksheet['A5'] = f'Total issues found: {len(issues)}'
        try:
            worksheet['A4'].font = worksheet['A4'].font.copy(bold=True)
            worksheet['A5'].font = worksheet['A5'].font.copy(italic=True)
        except Exception:
            pass
        # Adjust column widths
        for col_idx, col_name in enumerate(expected_cols, start=1):
            sample_values = df[col_name].astype(str).head(50)
            max_len = max(len(col_name), max(sample_values.apply(len))) if not sample_values.empty else len(col_name)
            worksheet.column_dimensions[chr(ord('A') + col_idx - 1)].width = min(max_len + 5, 60)


def main() -> None:
    parser = argparse.ArgumentParser(description='Run a basic WCAG accessibility scan.')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--url', help='URL of the page to scan')
    group.add_argument('--file', help='Local HTML file to scan')
    parser.add_argument('--output', default='report.xlsx', help='Output Excel file name')
    parser.add_argument('--logo', default='logo.png', help='Path to the Perspective Tester logo image')
    args = parser.parse_args()

    if args.url:
        html = fetch_html_from_url(args.url)
    else:
        html = read_local_file(args.file)
    if not html:
        print('No HTML content was retrieved. Exiting.')
        return
    issues = run_accessibility_checks(html)
    write_report(issues, args.output, args.logo)
    print(f'Report generated: {args.output} ({len(issues)} issues found)')


if __name__ == '__main__':
    main()