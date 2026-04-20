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
import cloudinary
import cloudinary.uploader
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


def generate_certificate_from_template(template_path, user_name, course_name, issued_date, certificate_id=None, field_positions=None, verification_url=None):
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
    
    # Default field positions (adjusted based on actual certificate layout)
    if field_positions is None:
        # Coordinates in PyMuPDF are from top-left (0,0 at top-left)
        # y increases downward
        page_rect = page.rect
        center_x = page_rect.width / 2
        
        # Based on the actual certificate layout:
        # - Date: Top left (~1.5 inches from edges)
        # - Certificate ID: Top right, horizontal (not vertical)
        # - Student Name: On first horizontal line in middle section
        # - Course Name: On second horizontal line in middle section
        field_positions = {
            'date': (page_rect.width * 0.14, page_rect.height * 0.12),  # Top left
            'certificate_id': (page_rect.width * 0.14, page_rect.height * 0.78),  # Left side signature line (bottom left, aligned with date)
            'student_name': (center_x, page_rect.height * 0.54),  # Middle section, moved lower (from 0.51 to 0.54)
            'course_name': (center_x, page_rect.height * 0.68),  # Middle section, moved lower (from 0.65 to 0.68)
        }
    else:
        # Convert positions if they're in percentage format or need conversion
        page_rect = page.rect
        converted_positions = {}
        for field_name, pos in field_positions.items():
            if isinstance(pos, tuple):
                # Already in (x, y) format
                converted_positions[field_name] = pos
            elif isinstance(pos, dict):
                # Check if we have percentage values
                if 'xPercent' in pos and 'yPercent' in pos:
                    # Convert from percentage to PDF coordinates
                    x = (pos['xPercent'] / 100) * page_rect.width
                    y = (pos['yPercent'] / 100) * page_rect.height
                    converted_positions[field_name] = (x, y)
                elif 'x' in pos and 'y' in pos:
                    # Use pixel values directly (assuming they're already in PDF coordinates)
                    converted_positions[field_name] = (pos['x'], pos['y'])
        field_positions = converted_positions
    
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
    
    for field_name, text in text_fields.items():
        if field_name in field_positions and text:
            x, y = field_positions[field_name]
            style = field_styles.get(field_name, {'fontsize': 14, 'align': 'left'})
            
            # Certificate ID: Left-aligned, on left side
            if field_name == 'certificate_id':
                # Left-align the text (same as date)
                point = fitz.Point(x, y)
                page.insert_text(
                    point,
                    text,
                    fontsize=style['fontsize'],
                    color=(0, 0, 0),
                    render_mode=0,
                )
            # Student name and course name: Center-aligned with Times-Roman font
            elif field_name in ['student_name', 'course_name']:
                # Use insert_text with manual centering for more reliable results
                # Calculate approximate text width (Times-Roman is a serif font, slightly wider)
                text_width = len(text) * (style['fontsize'] * 0.6)
                
                # Center the text by adjusting x position
                point = fitz.Point(x - text_width/2, y)
                try:
                    # Use Times-Roman font (built-in PDF font)
                    # PyMuPDF uses 'times' as the font name for Times-Roman
                    page.insert_text(
                        point,
                        text,
                        fontsize=style['fontsize'],
                        color=(1, 1, 1),
                        render_mode=0,
                        fontname='times',  # Times-Roman in PyMuPDF
                    )
                except Exception as e:
                    # If that fails, try textbox as fallback
                    text_rect = fitz.Rect(x - 250, y - style['fontsize']*1.5, 
                                         x + 250, y + style['fontsize']*1.5)
                    try:
                        page.insert_textbox(
                            text_rect,
                            text,
                            fontsize=style['fontsize'],
                            color=(1, 1, 1),
                            align=1,  # Center alignment
                            fontname='times',  # Times-Roman in PyMuPDF
                        )
                    except:
                        # Final fallback without specifying font (uses default)
                        page.insert_textbox(
                            text_rect,
                            text,
                            fontsize=style['fontsize'],
                            color=(1, 1, 1),
                            align=1,
                        )
            # Date: Left-aligned
            else:
                point = fitz.Point(x, y)
                page.insert_text(
                    point,
                    text,
                    fontsize=style['fontsize'],
                    color=(0, 0, 0),
                    render_mode=0,
                )
    
    # Add QR code for verification (always add if certificate_id exists)
    if certificate_id:
        try:
            qr = qrcode.QRCode(version=1, box_size=4, border=2)
            # Use verification URL if provided, otherwise use certificate info as fallback
            if verification_url:
                qr.add_data(verification_url)
            else:
                # Fallback: include certificate details in QR code
                date_str = issued_date.strftime("%B %d, %Y")
                qr_data = f"Certificate ID: {certificate_id}\nStudent: {user_name}\nCourse: {course_name}\nDate: {date_str}"
                qr.add_data(qr_data)
            qr.make(fit=True)
            qr_img = qr.make_image(fill_color="black", back_color="white")
            
            # Save QR code to BytesIO buffer
            qr_buffer = BytesIO()
            qr_img.save(qr_buffer, format='PNG')
            qr_buffer.seek(0)
            
            # Position QR code at bottom center (matching the programmatic certificate layout)
            page_rect = page.rect
            qr_size = 100  # Larger size for better visibility and scanning
            qr_x = (page_rect.width - qr_size) / 2  # Center horizontally
            # Position near bottom center - in PyMuPDF y=0 is at top, so larger y = lower on page
            # Certificate ID is at 0.78 (78% from top = near bottom)
            # QR code should be in the bottom center area, lowered a bit more
            # Position it around 72% from top (28% from bottom) - lowered more
            qr_y = page_rect.height * 0.72  # 72% from top = 28% from bottom (lowered more)
            
            # Insert QR code image using stream (image bytes)
            qr_rect = fitz.Rect(qr_x, qr_y, qr_x + qr_size, qr_y + qr_size)
            page.insert_image(qr_rect, stream=qr_buffer.getvalue())
        except Exception as e:
            print(f"Could not add QR code to template certificate: {e}")
    
    # Save to buffer
    buffer = BytesIO()
    template_doc.save(buffer)
    template_doc.close()
    buffer.seek(0)
    return buffer


def generate_certificate_pdf(user_name, course_name, issued_date, certificate_id=None, modules=None, template_path=None, field_positions=None, verification_url=None):
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
                certificate_id, field_positions, verification_url
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
    logo_url = "https://res.cloudinary.com/dwooadxdj/image/upload/v1771294639/copy_of_copy_of_fluentory_-_branding-05_ijgdpz_a6f568_7b4fc3.png"
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
    c.setFillColor(colors.HexColor("#FFFFFF"))
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
    c.setFillColor(colors.HexColor("#FFFFFF"))
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
    Upload certificate PDF to Cloudinary.
    
    Args:
        pdf_buffer: BytesIO object containing the PDF
        user_id: User ID for organizing files
        course_slug: Course slug for organizing files
        
    Returns:
        Dictionary with 'url' and 'public_id' of uploaded certificate
    """
    try:
        # Configure Cloudinary if not already configured
        if not cloudinary.config().cloud_name:
            cloudinary.config(
                cloud_name=os.getenv('CLOUDINARY_CLOUD_NAME'),
                api_key=os.getenv('CLOUDINARY_API_KEY'),
                api_secret=os.getenv('CLOUDINARY_API_SECRET')
            )
        
        # Upload PDF to Cloudinary
        upload_result = cloudinary.uploader.upload(
            pdf_buffer,
            resource_type='raw',  # PDFs are raw files
            folder=f'certificates/{course_slug}',
            public_id=f'cert_{user_id}_{datetime.now().strftime("%Y%m%d_%H%M%S")}',
            format='pdf',
            overwrite=False
        )
        
        return {
            'url': upload_result['secure_url'],
            'public_id': upload_result['public_id']
        }
    except Exception as e:
        print(f"Error uploading certificate to Cloudinary: {str(e)}")
        return None


def generate_certificate(user, course, issued_date=None, upload_to_cloudinary=True):
    """
    Generate a certificate for a user and course.
    
    Args:
        user: User object
        course: Course object
        issued_date: Optional datetime (defaults to now)
        upload_to_cloudinary: Whether to upload to Cloudinary (default True)
        
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
    
    # Build verification URL for QR code
    verification_url = None
    if DJANGO_AVAILABLE and certificate_id:
        try:
            # Get base URL from settings or use default
            domain = settings.ALLOWED_HOSTS[0] if settings.ALLOWED_HOSTS else 'localhost:8000'
            if not domain.startswith('http'):
                protocol = 'https' if not settings.DEBUG else 'http'
                domain = f"{protocol}://{domain}"
            
            # Build verification URL
            verification_url = f"{domain}/verify-certificate/{certificate_id}/"
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
            verification_url=verification_url
        )
    finally:
        # Clean up temporary template file if it was downloaded
        if temp_template_path and os.path.exists(temp_template_path):
            try:
                os.remove(temp_template_path)
            except Exception as e:
                print(f"Could not clean up temporary template file: {e}")
    
    # Upload to Cloudinary if requested
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
