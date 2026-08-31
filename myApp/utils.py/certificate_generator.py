from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from reportlab.lib.utils import ImageReader
from io import BytesIO
from datetime import datetime
import os
import tempfile
import requests
import qrcode
try:
    from django.urls import reverse
    from django.conf import settings
    DJANGO_AVAILABLE = True
except ImportError:
    DJANGO_AVAILABLE = False
try:
    import fitz  # PyMuPDF
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False


DEFAULT_CERTIFICATE_TEMPLATE_RELATIVE_PATH = os.path.join(
    'myApp', 'static', 'certificates', 'KATALYST_Certificate.pdf'
)


def _normalize_overlay_color(overlay_color):
    color = str(overlay_color or 'white').strip().lower()
    return color if color in ('white', 'black') else 'white'


def _overlay_rgb(overlay_color):
    return (0, 0, 0) if _normalize_overlay_color(overlay_color) == 'black' else (1, 1, 1)


def _normalize_overlay_field_specs(field_positions, page_rect):
    if not field_positions:
        field_positions = {
            'student_name': {'xPercent': 50, 'yPercent': 54, 'visible': True, 'align': 'center'},
            'course_name': {'xPercent': 50, 'yPercent': 68, 'visible': True, 'align': 'center'},
            'date': {'xPercent': 14, 'yPercent': 12, 'visible': True, 'align': 'left'},
            'certificate_id': {'xPercent': 14, 'yPercent': 78, 'visible': True, 'align': 'left'},
            'qr_code': {'xPercent': 50, 'yPercent': 72, 'visible': True, 'align': 'center'},
        }
    specs = {}
    for name, pos in field_positions.items():
        spec = {'visible': True, 'align': 'left', 'fontsize': None}
        if isinstance(pos, (tuple, list)) and len(pos) >= 2:
            spec['x'] = float(pos[0])
            spec['y'] = float(pos[1])
            if name in ('student_name', 'course_name', 'qr_code'):
                spec['align'] = 'center'
        elif isinstance(pos, dict):
            spec['visible'] = pos.get('visible', True) is not False
            align = str(pos.get('align') or '').strip().lower()
            if align not in ('left', 'center', 'right'):
                align = 'center' if name in ('student_name', 'course_name', 'qr_code') else 'left'
            spec['align'] = align
            if pos.get('xPercent') is not None and pos.get('yPercent') is not None:
                spec['x'] = (float(pos['xPercent']) / 100.0) * page_rect.width
                spec['y'] = (float(pos['yPercent']) / 100.0) * page_rect.height
            elif pos.get('x') is not None and pos.get('y') is not None:
                spec['x'] = float(pos['x'])
                spec['y'] = float(pos['y'])
            else:
                continue
            try:
                if pos.get('fontsize'):
                    spec['fontsize'] = float(pos['fontsize'])
            except (TypeError, ValueError):
                pass
        else:
            continue
        specs[name] = spec
    return specs


def generate_certificate_from_template(template_path, user_name, course_name, issued_date, certificate_id=None, field_positions=None, verification_url=None, overlay_color='white'):
    """
    Generate a certificate by overlaying text on a PDF template.
    
    Args:
        template_path: Path to the PDF template file
        user_name: Full name of the student
        course_name: Name of the completed course
        issued_date: Date when certificate was issued (datetime object)
        certificate_id: Optional certificate ID/number
        field_positions: Dict with positions for fields like:
            {'student_name': (x, y), 'course_name': (x, y), 'date': (x, y), 'certificate_id': (x, y)}
            If None, uses default positions
        verification_url: Optional URL for certificate verification (for QR code)
        
    Returns:
        BytesIO object containing the PDF certificate
    """
    if not PDF_AVAILABLE:
        raise ImportError("PyMuPDF (fitz) is required for template-based certificates")
    
    # Using Times-Roman (built-in PDF font) for student name and course name
    # No need to load external fonts
    
    # Open the template PDF
    template_doc = fitz.open(template_path)
    page = template_doc[0]  # Use first page
    
    page_rect = page.rect
    field_specs = _normalize_overlay_field_specs(field_positions, page_rect)
    
    # Format date
    date_str = issued_date.strftime("%B %d, %Y")
    
    # Prepare text to overlay
    text_fields = {
        'student_name': user_name,
        'course_name': course_name,
        'date': date_str,
        'certificate_id': certificate_id or '',
    }
    
    # Overlay text on the PDF with proper positioning and formatting
    # Font sizes for different fields
    field_styles = {
        'student_name': {'fontsize': 28, 'align': 'center'},  # Increased from 20 to 28
        'course_name': {'fontsize': 18, 'align': 'center'},  # Increased from 16 to 18
        'date': {'fontsize': 11, 'align': 'left'},
        'certificate_id': {'fontsize': 9, 'align': 'right'},
    }
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
    bg_png = pix.tobytes('png')
    width = float(page_rect.width)
    height = float(page_rect.height)
    template_doc.close()

    # Rebuild as a fresh reportlab PDF. Overlaying onto the original template with
    # PyMuPDF produced files some Windows readers refuse to open.
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=(width, height))
    c.drawImage(
        ImageReader(BytesIO(bg_png)),
        0,
        0,
        width=width,
        height=height,
        preserveAspectRatio=False,
        mask='auto',
    )
    fill = (
        colors.HexColor('#000000')
        if _normalize_overlay_color(overlay_color) == 'black'
        else colors.HexColor('#FFFFFF')
    )
    c.setFillColor(fill)

    def reportlab_y(top_y):
        return height - float(top_y)

    for field_name, text in text_fields.items():
        spec = field_specs.get(field_name)
        if not spec or not spec.get('visible', True) or not text:
            continue
        style = field_styles.get(field_name, {'fontsize': 14, 'align': 'left'})
        fontsize = spec.get('fontsize') or style['fontsize']
        align = spec.get('align') or style.get('align') or 'left'
        x = float(spec['x'])
        y = reportlab_y(spec['y'])
        font = 'Times-Bold' if field_name in ('student_name', 'course_name') else 'Helvetica'
        c.setFont(font, fontsize)
        if align == 'center':
            c.drawCentredString(x, y, text)
        elif align == 'right':
            c.drawRightString(x, y, text)
        else:
            c.drawString(x, y, text)

    qr_spec = field_specs.get('qr_code') or {}
    if certificate_id and qr_spec.get('visible', True):
        try:
            qr = qrcode.QRCode(version=1, box_size=4, border=2)
            if verification_url:
                qr.add_data(verification_url)
            else:
                qr_data = (
                    f"Certificate ID: {certificate_id}\nStudent: {user_name}\n"
                    f"Course: {course_name}\nDate: {date_str}"
                )
                qr.add_data(qr_data)
            qr.make(fit=True)
            qr_img = qr.make_image(fill_color="black", back_color="white")
            qr_buffer = BytesIO()
            qr_img.save(qr_buffer, format='PNG')
            qr_buffer.seek(0)
            qr_size = min(width, height) * 0.12
            qr_left = float(qr_spec.get('x', width / 2.0)) - qr_size / 2.0
            qr_top = float(qr_spec.get('y', height * 0.72)) - qr_size / 2.0
            qr_bottom = reportlab_y(qr_top) - qr_size
            c.drawImage(
                ImageReader(qr_buffer),
                qr_left,
                qr_bottom,
                width=qr_size,
                height=qr_size,
                mask='auto',
            )
        except Exception as e:
            print(f"Could not add QR code to template certificate: {e}")

    c.save()
    buffer.seek(0)
    return buffer


def generate_certificate_pdf(user_name, course_name, issued_date, certificate_id=None, modules=None, template_path=None, field_positions=None, verification_url=None, overlay_color='white'):
    """
    Generate a PDF certificate for course completion.
    If template_path is provided, uses the template. Otherwise, generates from scratch.
    
    Args:
        user_name: Full name of the student
        course_name: Name of the completed course
        issued_date: Date when certificate was issued (datetime object)
        certificate_id: Optional certificate ID/number
        modules: Optional list of module names to display on certificate
        template_path: Optional path to PDF template file
        field_positions: Optional dict with field positions for template
        verification_url: Optional URL for certificate verification (for QR code)
        
    Returns:
        BytesIO object containing the PDF certificate
    """
    # If template is provided, use it
    if template_path and os.path.exists(template_path):
        try:
            print(f"Attempting to use template: {template_path}")
            return generate_certificate_from_template(
                template_path, user_name, course_name, issued_date, 
                certificate_id, field_positions, verification_url, overlay_color
            )
        except Exception as e:
            import traceback
            print(f"Error using template, falling back to default: {e}")
            print(f"Traceback: {traceback.format_exc()}")
            # Fall through to default generation
    elif template_path:
        print(f"Template path provided but file does not exist: {template_path}")
    
    # Otherwise, generate from scratch with Fluentory design
    buffer = BytesIO()
    # Use landscape orientation
    width, height = landscape(A4)
    
    # Dark teal color (matching the design)
    dark_teal = colors.HexColor("#0d9488")  # Adjust to match exact teal from design
    dark_gray = colors.HexColor("#374151")
    light_bg = colors.HexColor("#fefefe")  # Off-white background

    overlay_fill = colors.HexColor("#000000") if _normalize_overlay_color(overlay_color) == 'black' else colors.HexColor("#FFFFFF")

    c = canvas.Canvas(buffer, pagesize=landscape(A4))
    
    # ===== Background =====
    c.setFillColor(light_bg)
    c.rect(0, 0, width, height, fill=1, stroke=0)
    
    # ===== Wavy horizontal lines background texture =====
    c.setStrokeColor(colors.HexColor("#f5f5f5"))
    c.setLineWidth(0.3)
    import math
    for i in range(0, int(height), 20):
        # Create subtle wavy lines using sine wave
        path = c.beginPath()
        y_base = i
        path.moveTo(0, y_base)
        for x in range(0, int(width), 5):
            y = y_base + 1.5 * math.sin(x / 30)  # Subtle wave
            path.lineTo(x, y)
        c.drawPath(path, stroke=1, fill=0)

    # ===== Outer Border (thin dark teal) =====
    margin = 30
    c.setStrokeColor(dark_teal)
    c.setLineWidth(1)
    c.rect(margin, margin, width - 2*margin, height - 2*margin)

    # ===== Inner Border (slightly thicker dark teal) =====
    inner_margin = 50
    c.setLineWidth(2)
    c.rect(inner_margin, inner_margin, width - 2*inner_margin, height - 2*inner_margin)

    # ===== Logo in top left =====
    logo_url = "https://cdn.katalyst-crm.com/t1/cloudinary/fluentory-branding-logo.png"
    logo_size = 80  # Define logo size first
    try:
        logo_response = requests.get(logo_url, timeout=5)
        if logo_response.status_code == 200:
            logo_img = ImageReader(BytesIO(logo_response.content))
            c.drawImage(logo_img, inner_margin + 20, height - inner_margin - logo_size - 20, 
                       width=logo_size, height=logo_size, preserveAspectRatio=True)
    except Exception as e:
        print(f"Could not load logo: {e}")
        # Continue without logo if it fails to load

    # ===== Certificate Title (top right area, next to logo) =====
    c.setFont("Helvetica-Bold", 48)
    c.setFillColor(dark_teal)
    cert_x = inner_margin + logo_size + 40  # Position after logo
    cert_y = height - inner_margin - 50
    c.drawString(cert_x, cert_y, "CERTIFICATE")
    
    c.setFont("Helvetica", 18)
    c.setFillColor(dark_gray)
    c.drawString(cert_x, cert_y - 35, "OF COMPLETION")
    
    c.setFont("Helvetica", 14)
    c.setFillColor(dark_gray)
    c.drawString(cert_x, cert_y - 60, "Proudly presented to")

    # ===== Student Name Line =====
    name_y = height - inner_margin - 120
    c.setFont("Times-Bold", 36)  # Increased from 28 to 36 for more prominence
    c.setFillColor(overlay_fill)
    # Draw a line for the name
    line_length = 400
    line_start_x = (width - line_length) / 2
    c.setStrokeColor(colors.HexColor("#000000"))
    c.setLineWidth(1)
    c.line(line_start_x, name_y - 5, line_start_x + line_length, name_y - 5)
    # Draw the name centered, moved lower (from -35 to -25 to bring it closer to the line)
    c.drawCentredString(width / 2, name_y - 25, user_name)

    # ===== Course Name Section =====
    course_y = name_y - 80
    c.setFont("Helvetica-Oblique", 12)
    c.setFillColor(dark_gray)
    c.drawCentredString(width / 2, course_y, "for completing their course of")
    
    # Draw a line for the course name
    c.setStrokeColor(colors.HexColor("#000000"))
    c.setLineWidth(1)
    c.line(line_start_x, course_y - 25, line_start_x + line_length, course_y - 25)
    
    # Draw the course name, moved lower (from -50 to -40 to bring it closer to the line)
    c.setFont("Times-Bold", 20)  # Using Times-Roman Bold for elegant look
    c.setFillColor(overlay_fill)
    course_display = course_name
    if len(course_display) > 50:
        course_display = course_display[:47] + "..."
    c.drawCentredString(width / 2, course_y - 40, course_display)

    # ===== Footer Section =====
    footer_y = inner_margin + 60
    
    # Left: Date/Signature line
    c.setFont("Helvetica", 10)
    c.setFillColor(dark_gray)
    date_str = issued_date.strftime("%B %d, %Y")
    c.drawString(inner_margin + 20, footer_y, date_str)
    c.setStrokeColor(colors.HexColor("#000000"))
    c.setLineWidth(1)
    c.line(inner_margin + 20, footer_y - 15, inner_margin + 150, footer_y - 15)
    
    # Center: QR Code (with verification URL if provided, otherwise fallback to text data)
    try:
        qr = qrcode.QRCode(version=1, box_size=4, border=2)
        if verification_url and certificate_id:
            # Use verification URL for QR code
            qr.add_data(verification_url)
        else:
            # Fallback to text data if no verification URL
            qr_data = f"Certificate ID: {certificate_id or 'N/A'}\nStudent: {user_name}\nCourse: {course_name}\nDate: {date_str}"
            qr.add_data(qr_data)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white")
        qr_buffer = BytesIO()
        qr_img.save(qr_buffer, format='PNG')
        qr_buffer.seek(0)
        qr_reader = ImageReader(qr_buffer)
        qr_size = 100  # Larger size for better visibility and scanning
        qr_x = (width - qr_size) / 2
        c.drawImage(qr_reader, qr_x, footer_y - qr_size - 5,  # Lowered more (back to -5, which is lower) 
                   width=qr_size, height=qr_size, preserveAspectRatio=True)
    except Exception as e:
        print(f"Could not generate QR code: {e}")
    
    # Right: CEO Name and Title
    c.setFont("Helvetica", 12)
    c.setFillColor(colors.HexColor("#000000"))
    ceo_x = width - inner_margin - 150
    c.drawString(ceo_x, footer_y, "HABIB ZATER")
    c.setFont("Helvetica", 10)
    c.drawString(ceo_x, footer_y - 18, "CEO")

    c.save()
    buffer.seek(0)
    return buffer


def upload_certificate_to_cloudinary(pdf_buffer, user_id, course_slug):
    """
    Upload certificate PDF to Iceberg (Cloudflare R2).

    (Name kept for call-site stability; storage backend is now Iceberg.)

    Args:
        pdf_buffer: BytesIO object containing the PDF
        user_id: User ID for organizing files
        course_slug: Course slug for organizing files

    Returns:
        Dictionary with 'url' and 'public_id' (the Iceberg key) of the upload,
        or None on failure.
    """
    try:
        from myApp.utils import iceberg
        if not iceberg.is_configured():
            print("Certificate upload skipped: ICEBERG_* settings are missing.")
            return None

        key = f'certificates/{course_slug}/cert_{user_id}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf'
        try:
            pdf_buffer.seek(0)
        except Exception:
            pass
        url = iceberg.upload_bytes(pdf_buffer.read(), key, 'application/pdf')
        if not url:
            return None

        return {
            'url': url,
            'public_id': key,
        }
    except Exception as e:
        print(f"Error uploading certificate to Iceberg: {str(e)}")
        return None


def generate_certificate(user, course, issued_date=None, upload_to_cloudinary=True, request=None):
    """
    Generate a certificate for a user and course.
    
    Args:
        user: User object
        course: Course object
        issued_date: Optional datetime (defaults to now)
        upload_to_cloudinary: Whether to upload to Iceberg (param name kept
            for call-site stability; Cloudinary is no longer used).
        request: Optional HTTP request so the QR verification URL uses the
            live host instead of localhost / ALLOWED_HOSTS[0].
        
    Returns:
        Dictionary with certificate URL and certificate ID, or None if error
    """
    if issued_date is None:
        issued_date = datetime.now()
    
    # Generate certificate ID
    certificate_id = f"CERT-{course.slug.upper()}-{user.id}-{issued_date.strftime('%Y%m%d')}"
    
    # Get user's full name
    user_name = user.get_full_name() or user.username
    
    # Get course modules dynamically
    modules = []
    try:
        course_modules = course.modules.all().order_by('order', 'id')
        modules = [f"Module {i+1} - {module.name}" for i, module in enumerate(course_modules)]
    except Exception:
        # If modules don't exist or error, just use empty list
        pass
    
    # Check if course has a certificate template, otherwise use default
    template_path = None
    field_positions = None
    temp_template_path = None  # Track temp files for cleanup
    overlay_color = 'white'
    tenant_branding = {}

    if DJANGO_AVAILABLE:
        try:
            tenant = getattr(course, 'tenant', None)
            if tenant is not None:
                from myApp.utils.branding import get_tenant_branding
                tenant_branding = get_tenant_branding(tenant) or {}
                overlay_color = _normalize_overlay_color(tenant_branding.get('certificate_overlay_color'))
        except Exception as e:
            print(f"Could not load tenant branding for certificate: {e}")
    
    # First, try to use course-specific template (if this project has those fields)
    course_template_field = getattr(course, 'certificate_template', None)
    course_field_positions = getattr(course, 'certificate_field_positions', None)
    if course_template_field:
        # Get saved field positions
        try:
            if course_field_positions:
                # Convert JSON format to tuple format expected by generator
                positions = course_field_positions
                field_positions = {}
                for field_name, pos in positions.items():
                    if isinstance(pos, dict) and 'x' in pos and 'y' in pos:
                        field_positions[field_name] = (pos['x'], pos['y'])
        except (AttributeError, KeyError):
            # Field doesn't exist in database yet
            field_positions = None

        # Try to get local path first
        try:
            template_path = course_template_field.path
            # Verify file exists
            if not os.path.exists(template_path):
                template_path = None
        except (ValueError, NotImplementedError):
            # File might be in Cloudinary or remote storage
            # Download it temporarily
            try:
                template_url = course_template_field.url
                response = requests.get(template_url, timeout=10)
                if response.status_code == 200:
                    # Save to temporary file
                    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
                    temp_file.write(response.content)
                    temp_file.close()
                    template_path = temp_file.name
                    temp_template_path = template_path  # Track for cleanup
            except Exception as e:
                print(f"Could not download template: {e}")
                template_path = None

    if field_positions is None and tenant_branding:
        try:
            from myApp.utils.branding import resolve_certificate_field_layout
            field_positions = resolve_certificate_field_layout(tenant_branding)
        except Exception as e:
            print(f"Could not resolve certificate field layout: {e}")

    # Next, try tenant-level custom certificate template from branding settings.
    if not template_path:
        tenant_template_url = (tenant_branding.get('certificate_template_url') or '').strip()
        if tenant_template_url:
            try:
                response = requests.get(tenant_template_url, timeout=12)
                if response.status_code == 200:
                    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
                    temp_file.write(response.content)
                    temp_file.close()
                    template_path = temp_file.name
                    temp_template_path = template_path
            except Exception as e:
                print(f"Could not load tenant certificate template: {e}")
    
    # If no course-specific template, use local default template.
    if not template_path:
        if DJANGO_AVAILABLE:
            default_path = os.path.join(settings.BASE_DIR, DEFAULT_CERTIFICATE_TEMPLATE_RELATIVE_PATH)
        else:
            import pathlib
            base_dir = pathlib.Path(__file__).resolve().parent.parent.parent
            default_path = str(base_dir / DEFAULT_CERTIFICATE_TEMPLATE_RELATIVE_PATH)

        normalized_path = os.path.normpath(default_path)
        if os.path.exists(normalized_path):
            template_path = normalized_path
            print(f"Using local default certificate template: {normalized_path}")
        else:
            print(f"Default certificate template not found: {normalized_path}")
    
    # Build verification URL for QR code from the tenant's public domain —
    # never ALLOWED_HOSTS[0], which is often localhost after sorting.
    verification_url = None
    if DJANGO_AVAILABLE and certificate_id:
        try:
            from myApp.utils.domains import build_certificate_verification_url
            tenant = getattr(course, 'tenant', None)
            verification_url = build_certificate_verification_url(
                certificate_id,
                tenant=tenant,
                request=request,
            ) or None
        except Exception as e:
            print(f"Could not build verification URL: {e}")
    
    # Generate PDF (will use template if available)
    if template_path:
        print(f"Template path being used: {template_path}")
        print(f"Template path exists: {os.path.exists(template_path) if template_path else False}")
    
    try:
        pdf_buffer = generate_certificate_pdf(
            user_name=user_name,
            course_name=course.name,
            issued_date=issued_date,
            certificate_id=certificate_id,
            modules=modules,
            template_path=template_path,
            field_positions=field_positions,
            verification_url=verification_url,
            overlay_color=overlay_color,
        )
    finally:
        # Clean up temporary template file if it was downloaded
        if temp_template_path and os.path.exists(temp_template_path):
            try:
                os.remove(temp_template_path)
            except Exception as e:
                print(f"Could not clean up temporary template file: {e}")
    
    # Upload to Iceberg if requested
    if upload_to_cloudinary:
        upload_result = upload_certificate_to_cloudinary(
            pdf_buffer,
            user.id,
            course.slug
        )
        
        if upload_result:
            return {
                'certificate_url': upload_result['url'],
                'certificate_id': certificate_id,
                'public_id': upload_result['public_id']
            }
        else:
            # If upload fails, return None
            return None
    else:
        # Return PDF buffer for direct download
        return {
            'pdf_buffer': pdf_buffer,
            'certificate_id': certificate_id
        }
