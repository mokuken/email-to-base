import imaplib
import email
import requests
import time
import datetime
import logging
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class Config:
    """Configuration class for email and webhook settings."""
    IMAP_HOST = os.getenv("IMAP_HOST")
    EMAIL_ACCOUNT = os.getenv("EMAIL_ACCOUNT")
    EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")

class EmailFetcher:
    """Handles IMAP connection and email fetching."""
    def __init__(self, host, user, password):
        self.host = host
        self.user = user
        self.password = password
        self.mail = None

    def connect(self):
        """Establish IMAP connection and select inbox."""
        self.mail = imaplib.IMAP4_SSL(self.host)
        self.mail.login(self.user, self.password)
        self.mail.select("INBOX")

    def get_email_ids_since(self, date):
        """Get email IDs since the given date."""
        status, messages = self.mail.search(None, f'SINCE {date}')
        email_ids = messages[0].split()
        return [int(eid) for eid in email_ids]

    def fetch_email(self, eid):
        """Fetch a specific email by ID."""
        status, msg_data = self.mail.fetch(str(eid).encode(), "(RFC822)")
        msg = email.message_from_bytes(msg_data[0][1])
        return msg

    def logout(self):
        """Close the IMAP connection."""
        if self.mail:
            self.mail.logout()

class EmailProcessor:
    """Processes email messages to extract details."""
    @staticmethod
    def extract_details(msg):
        """Extract sender, subject, date, and body from email message."""
        sender = msg["From"]
        subject = msg["Subject"]
        date = msg["Date"]
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_dispo = str(part.get("Content-Disposition"))
                if content_type == "text/plain" and "attachment" not in content_dispo:
                    body = part.get_payload(decode=True).decode(errors="ignore")
                    break
        else:
            body = msg.get_payload(decode=True).decode(errors="ignore")
        return {
            "from": sender,
            "subject": subject,
            "date": date,
            "body": body
        }

class WebhookSender:
    """Handles sending data to the webhook."""
    def __init__(self, url):
        self.url = url

    def send(self, data):
        """Send email data to the webhook."""
        response = requests.post(self.url, json=data)
        return response.status_code == 200

class EmailMonitor:
    """Monitors emails and sends new ones to webhook."""
    def __init__(self, config):
        self.config = config
        self.fetcher = EmailFetcher(config.IMAP_HOST, config.EMAIL_ACCOUNT, config.EMAIL_PASSWORD)
        self.sender = WebhookSender(config.WEBHOOK_URL)
        self.last_processed_id = 0
        self.search_date = datetime.date.today().strftime('%d-%b-%Y')
        self._initialize_last_id()

    def _initialize_last_id(self):
        """Initialize the last processed email ID to avoid reprocessing."""
        try:
            self.fetcher.connect()
            ids = self.fetcher.get_email_ids_since(self.search_date)
            if ids:
                self.last_processed_id = max(ids)
            self.fetcher.logout()
        except Exception as e:
            logging.error(f"Initial setup error: {e}")

    def run(self):
        """Run one email check cycle."""
        try:
            self.fetcher.connect()
            ids = self.fetcher.get_email_ids_since(self.search_date)

            if ids:
                latest_id = max(ids)
                if latest_id > self.last_processed_id:
                    for eid in ids:
                        if eid > self.last_processed_id:
                            msg = self.fetcher.fetch_email(eid)
                            data = EmailProcessor.extract_details(msg)
                            success = self.sender.send(data)

                            if success:
                                logging.info(f"Sent email {eid} to webhook")
                            else:
                                logging.error(f"Failed to send email {eid}")

                    self.last_processed_id = latest_id

            self.fetcher.logout()
        except Exception as e:
            logging.error(f"Error: {e}")

if __name__ == "__main__":
    monitor = EmailMonitor(Config)
    monitor.run()

