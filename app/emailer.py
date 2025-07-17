import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
import os

load_dotenv()

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
FROM_EMAIL = os.getenv("FROM_EMAIL")

def create_html_template(unit, distance_km):
    """Create a beautiful HTML email template for Voyager 2 notifications"""
    distance_million_km = distance_km / 1e6
    distance_au = distance_km / 149597870.7  # 1 AU in km
    
    html_template = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Voyager 2 Update</title>
    </head>
    <body style="margin: 0; padding: 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: linear-gradient(135deg, #0a0a0a 0%, #1a1a2e 50%, #16213e 100%); color: #ffffff;">
        <div style="max-width: 600px; margin: 0 auto; background: rgba(255, 255, 255, 0.05); backdrop-filter: blur(10px); border-radius: 20px; overflow: hidden; box-shadow: 0 20px 40px rgba(0, 0, 0, 0.3);">
            
            <!-- Header -->
            <div style="background: linear-gradient(45deg, #667eea 0%, #764ba2 100%); padding: 40px 30px; text-align: center; position: relative;">
                <div style="font-size: 60px; margin-bottom: 10px;">🚀</div>
                <h1 style="margin: 0; font-size: 28px; font-weight: 300; letter-spacing: 2px;">VOYAGER 2</h1>
                <p style="margin: 10px 0 0 0; font-size: 14px; opacity: 0.8; letter-spacing: 1px;">DEEP SPACE EXPLORER</p>
                <div style="position: absolute; top: 20px; right: 20px; width: 80px; height: 80px; border: 2px solid rgba(255,255,255,0.3); border-radius: 50%; animation: rotate 20s linear infinite;"></div>
            </div>
            
            <!-- Main Content -->
            <div style="padding: 40px 30px;">
                <div style="text-align: center; margin-bottom: 30px;">
                    <h2 style="color: #667eea; font-size: 24px; margin: 0 0 10px 0; font-weight: 300;">🌌 Journey Update</h2>
                    <p style="font-size: 16px; opacity: 0.9; margin: 0; line-height: 1.6;">Voyager 2 has traveled another <strong style="color: #667eea;">{unit.replace('_', ' ')}</strong> through the cosmos!</p>
                </div>
                
                <!-- Distance Stats -->
                <div style="background: rgba(102, 126, 234, 0.1); border-left: 4px solid #667eea; padding: 25px; margin: 30px 0; border-radius: 10px;">
                    <h3 style="margin: 0 0 20px 0; color: #667eea; font-size: 18px; font-weight: 400;">📍 Current Position</h3>
                    <div style="display: grid; gap: 15px;">
                        <div style="display: flex; justify-content: space-between; align-items: center; padding: 10px 0; border-bottom: 1px solid rgba(255,255,255,0.1);">
                            <span style="color: #cccccc;">Distance from Earth:</span>
                            <span style="color: #667eea; font-weight: 600; font-size: 16px;">{distance_million_km:.2f} million km</span>
                        </div>
                        <div style="display: flex; justify-content: space-between; align-items: center; padding: 10px 0; border-bottom: 1px solid rgba(255,255,255,0.1);">
                            <span style="color: #cccccc;">In Astronomical Units:</span>
                            <span style="color: #667eea; font-weight: 600; font-size: 16px;">{distance_au:.2f} AU</span>
                        </div>
                        <div style="display: flex; justify-content: space-between; align-items: center; padding: 10px 0;">
                            <span style="color: #cccccc;">Light Travel Time:</span>
                            <span style="color: #667eea; font-weight: 600; font-size: 16px;">{distance_km / 299792.458:.1f} seconds</span>
                        </div>
                    </div>
                </div>
                
                <!-- Mission Info -->
                <div style="background: rgba(118, 75, 162, 0.1); border-radius: 10px; padding: 25px; margin: 30px 0;">
                    <h3 style="margin: 0 0 15px 0; color: #764ba2; font-size: 16px; font-weight: 400;">🛰️ Mission Status</h3>
                    <p style="margin: 0; font-size: 14px; line-height: 1.6; opacity: 0.9;">
                        Launched in 1977, Voyager 2 continues its incredible journey through interstellar space, 
                        carrying humanity's message to the stars on the Golden Record.
                    </p>
                </div>
                
                <!-- Footer -->
                <div style="text-align: center; margin-top: 40px; padding-top: 30px; border-top: 1px solid rgba(255,255,255,0.1);">
                    <p style="margin: 0; font-size: 12px; opacity: 0.6; line-height: 1.5;">
                        This notification was sent because you subscribed to Voyager 2 distance updates.<br>
                        Data courtesy of NASA JPL Horizons System.
                    </p>
                    <div style="margin-top: 20px;">
                        <span style="font-size: 20px;">⭐</span>
                        <span style="font-size: 16px; margin: 0 10px;">✨</span>
                        <span style="font-size: 20px;">🌟</span>
                    </div>
                </div>
            </div>
        </div>
        
        <style>
            @keyframes rotate {{
                from {{ transform: rotate(0deg); }}
                to {{ transform: rotate(360deg); }}
            }}
        </style>
    </body>
    </html>
    """
    return html_template

def send_email(to_email, subject, unit=None, distance_km=None):
    """Send an HTML email with a beautiful template"""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = FROM_EMAIL
    msg["To"] = to_email
    
    # Create HTML content
    if unit and distance_km:
        html_content = create_html_template(unit, distance_km)
        # Create a plain text fallback
        text_content = f"""
        Voyager 2 Distance Update
        
        Voyager 2 has traveled another {unit.replace('_', ' ')} through space!
        
        Current distance from Earth: {distance_km/1e6:.2f} million km
        In Astronomical Units: {distance_km/149597870.7:.2f} AU
        Light travel time: {distance_km/299792458:.1f} seconds
        
        This incredible spacecraft continues its journey through interstellar space,
        carrying humanity's message to the stars.
        
        Data courtesy of NASA JPL Horizons System.
        """
    else:
        # Fallback for other types of emails
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #333;">{subject}</h2>
            <p>Thank you for subscribing to Voyager 2 updates!</p>
        </body>
        </html>
        """
        text_content = f"{subject}\n\nThank you for subscribing to Voyager 2 updates!"
    
    # Create MIMEText objects
    text_part = MIMEText(text_content, "plain")
    html_part = MIMEText(html_content, "html")
    
    # Add parts to message
    msg.attach(text_part)
    msg.attach(html_part)
    
    # Send email
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
