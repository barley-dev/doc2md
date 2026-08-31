"""doc2md converters — format-specific conversion modules."""

from converters.pdf import convert_pdf_to_md
from converters.docx import convert_docx_native
from converters.pptx import convert_pptx_native
from converters.excel import convert_excel_native, convert_xls_native
from converters.odf import convert_ods_native, convert_odt_native
from converters.html import convert_html_native
from converters.plaintext import convert_plaintext
from converters.libreoffice import convert_via_libreoffice, convert_via_libreoffice_then_native

# Supported input formats
SUPPORTED_FORMATS = {
    '.pdf': 'pdf',
    '.doc': 'doc_via_docx',
    '.docx': 'docx_native',
    '.odt': 'odt_native',
    '.ods': 'ods_native',
    '.rtf': 'libreoffice',
    '.ppt': 'ppt_via_pptx',
    '.pptx': 'pptx_native',
    '.xls': 'xls_native',
    '.xlsx': 'excel_native',
    '.csv': 'plaintext',
    '.tsv': 'plaintext',
    '.txt': 'plaintext',
    '.html': 'html_native',
    '.htm': 'html_native',
}

# Map format type -> converter function
CONVERTER_MAP = {
    'pdf': convert_pdf_to_md,
    'excel_native': convert_excel_native,
    'xls_native': convert_xls_native,
    'docx_native': convert_docx_native,
    'pptx_native': convert_pptx_native,
    'html_native': convert_html_native,
    'ods_native': convert_ods_native,
    'odt_native': convert_odt_native,
    'libreoffice': convert_via_libreoffice,
    'plaintext': convert_plaintext,
    'doc_via_docx': lambda fp, od, cfg, args: convert_via_libreoffice_then_native(
        fp, od, cfg, args, 'docx', convert_docx_native),
    'ppt_via_pptx': lambda fp, od, cfg, args: convert_via_libreoffice_then_native(
        fp, od, cfg, args, 'pptx', convert_pptx_native),
}
