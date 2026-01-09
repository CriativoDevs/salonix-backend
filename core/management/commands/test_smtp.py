from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.conf import settings
import smtplib
import socket

class Command(BaseCommand):
    help = 'Tests SMTP connection and sends a test email'

    def add_arguments(self, parser):
        parser.add_argument('email', type=str, help='Email address to send test message to')
        parser.add_argument('--native', action='store_true', help='Use native smtplib instead of Django backend')

    def handle(self, *args, **options):
        to_email = options['email']
        use_native = options['native']
        
        self.stdout.write(f"Testing SMTP configuration...")
        self.stdout.write(f"HOST: {settings.EMAIL_HOST}")
        self.stdout.write(f"PORT: {settings.EMAIL_PORT}")
        self.stdout.write(f"USER: {settings.EMAIL_HOST_USER}")
        self.stdout.write(f"TLS: {settings.EMAIL_USE_TLS}")
        self.stdout.write(f"BACKEND: {settings.EMAIL_BACKEND}")
        
        if use_native:
            self.stdout.write("\nUsing native smtplib...")
            try:
                with smtplib.SMTP(settings.EMAIL_HOST, settings.EMAIL_PORT, timeout=10) as server:
                    server.set_debuglevel(1)
                    if settings.EMAIL_USE_TLS:
                        self.stdout.write("Starting TLS...")
                        server.starttls()
                    
                    self.stdout.write("Logging in...")
                    server.login(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD)
                    
                    msg = f"Subject: Test Email (Native)\n\nThis is a test email from Salonix using native smtplib."
                    self.stdout.write(f"Sending to {to_email}...")
                    server.sendmail(settings.EMAIL_HOST_USER, [to_email], msg)
                    self.stdout.write(self.style.SUCCESS('Successfully sent email via native smtplib'))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Failed native: {str(e)}'))
        else:
            self.stdout.write("\nUsing Django send_mail...")
            try:
                send_mail(
                    'Test Email (Django)',
                    'This is a test email from Salonix using Django send_mail.',
                    settings.EMAIL_HOST_USER,
                    [to_email],
                    fail_silently=False,
                )
                self.stdout.write(self.style.SUCCESS('Successfully sent email via Django'))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Failed Django: {str(e)}'))
                if hasattr(e, 'smtp_code'):
                    self.stdout.write(f"SMTP Code: {e.smtp_code}")
                if hasattr(e, 'smtp_error'):
                    self.stdout.write(f"SMTP Error: {e.smtp_error}")
