import imaplib
import email
import requests
import datetime
import logging
import os

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load config from environment variables (from GitHub Actions secrets)
class Config:
    IMAP_HOST = os.getenv("IMAP_HOST")
    EMAIL_ACCOUNT = os.getenv("EMAIL_ACCOUNT")
    EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")

    @classmethod
    def validate(cls):
        missing = []
        for var in ["IMAP_HOST", "EMAIL_ACCOUNT", "EMAIL_PASSWORD", "WEBHOOK_URL"]:
            if not getattr(cls, var):
                missing.append(var)
        if missing:
            raise ValueError(f"Missing environment variables: {', '.join(missing)}")

# --- Email fetcher ---
class EmailFetcher:
    def __init__(self, host, user, password):
        self.host = host
        self.user = user
        self.password = password
        self.mail = None

    def connect(self):
        logging.info(f"Connecting to IMAP server {self.host}")
        self.mail = imaplib.IMAP4_SSL(self.host)
        self.mail.login(self.user, self.password)
        self.mail.select("INBOX")

    def get_email_ids_since(self, date):
        status, messages = self.mail.search(None, f'SINCE {date}')
        email_ids = messages[0].split()
        return [int(eid) for eid in email_ids]

    def fetch_email(self, eid):
        status, msg_data = self.mail.fetch(str(eid).encode(), "(RFC822)")
        msg = email.message_from_bytes(msg_data[0][1])
        return msg

    def logout(self):
        if self.mail:
            self.mail.logout()

# --- Email processor ---
class EmailProcessor:
    @staticmethod
    def extract_details(msg):
        sender = msg["From"]
        subject = msg["Subject"]
        date = msg["Date"]
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition")):
                    body = part.get_payload(decode=True).decode(errors="ignore")
                    break
        else:
            body = msg.get_payload(decode=True).decode(errors="ignore")
        return {"from": sender, "subject": subject, "date": date, "body": body}

# --- Webhook sender ---
class WebhookSender:
    def __init__(self, url):
        self.url = url

    def send(self, data):
        response = requests.post(self.url, json=data)
        if response.status_code == 200:
            logging.info("Webhook sent successfully")
            return True
        else:
            logging.error(f"Webhook failed: {response.status_code}, {response.text}")
            return False

# --- Email monitor ---
class EmailMonitor:
    def __init__(self, config):
        Config.validate()
        self.config = config
        self.fetcher = EmailFetcher(config.IMAP_HOST, config.EMAIL_ACCOUNT, config.EMAIL_PASSWORD)
        self.sender = WebhookSender(config.WEBHOOK_URL)
        self.last_processed_id = 0
        self.search_date = datetime.date.today().strftime('%d-%b-%Y')
        self._initialize_last_id()

    def _initialize_last_id(self):
        try:
            self.fetcher.connect()
            ids = self.fetcher.get_email_ids_since(self.search_date)
            if ids:
                self.last_processed_id = max(ids)
            self.fetcher.logout()
        except Exception as e:
            logging.error(f"Initial setup error: {e}")

    def run(self):
        """Run one check per execution."""
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
                            self.sender.send(data)
                    self.last_processed_id = latest_id

            self.fetcher.logout()
        except Exception as e:
            logging.error(f"Error: {e}")

# --- Main ---
if __name__ == "__main__":
    monitor = EmailMonitor(Config)
    monitor.run()
