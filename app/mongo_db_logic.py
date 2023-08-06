# mongo_db_logic.py
# defines the logic for interacting with the mongo database using the mongoengine library
import calendar
import os
import uuid
import certifi
from mongoengine import connect, Document, StringField, DateTimeField, FloatField, ListField, DictField, \
    EmbeddedDocumentField, EmbeddedDocument, BooleanField, register_connection, EmailField
from datetime import datetime
from werkzeug.security import generate_password_hash
from typing import Optional, Callable
import logging
import pytz

# set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Connect to MongoDB
connect(
    'AudioBio_db',
    host=os.environ['AUDIOBIO_MONGO_CONNECTION_STRING'],
    tls=True,
    tlsCAFile=certifi.where()
)


def generate_random_id():
    """Generate a random 9 character users id from Upper Case letters and numbers"""
    user_id = uuid.uuid4().hex[:9].upper()
    return user_id


def get_current_date() -> str:
    """
    Get the current date in the format of DD_MMM_YYYY eg. 01_JAN_2021
    :return: The current date in the format of DD_MMM_YYYY eg. 01_JAN_2021
    """
    return datetime.utcnow().strftime("%d_%b_%Y").upper()


def get_current_date_in_user_tz(timezone_name):
    tz = pytz.timezone(timezone_name)
    return datetime.now(tz).strftime("%d_%b_%Y").upper()


def get_formatted_date(date: str) -> str:
    """
    Get the date in the format of DD_MMM_YYYY eg. 01_JAN_2021
    :param date:
    :return:
    """
    from datetime import datetime
    logger.info(f"entered get_formatted_date with date: {date}")
    # assuming date string is in the format 'DD_MM_YYYY'
    date_obj = datetime.strptime(date, "%d_%m_%Y")
    return date_obj.strftime("%d_%b_%Y").upper()


class JournalEntry(EmbeddedDocument):
    """
    A single journal entry that contains a unique id, recordings, and the text content of the journal entry
    """
    id = StringField(required=True, default=generate_random_id)
    recording_file_name = StringField(required=True)
    recording_length_in_seconds = FloatField()
    transcription = StringField()
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)


class DayEntryBundle(EmbeddedDocument):
    """
    A collection of journal entries for a single day that contain the summarized daily journal entry and the
    individual journal entries for the day
    """
    id = StringField(required=True, default=lambda: datetime.utcnow().strftime("%d_%b_%Y"), unique=True)
    title = StringField(required=True, default=lambda: datetime.utcnow().strftime("%d-%b-%Y"))
    summary = StringField()
    processed_entry = StringField()
    entries = ListField(EmbeddedDocumentField(JournalEntry))
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)


class Users(Document):
    """
    A users that has a unique id and email. Within the users, there is a collection of journal entries organized by day
    """
    # id = StringField(required=True, default=generate_random_id)
    email = EmailField(required=True, unique=True)
    _hashed_password = StringField(required=True, min_length=5, max_length=255)
    first_name = StringField(required=True, min_length=2, max_length=100)
    last_name = StringField(min_length=2, max_length=100)
    journal = DictField(field=EmbeddedDocumentField(DayEntryBundle), default={})
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    def save(self, *args, **kwargs):
        self.updated_at = datetime.utcnow()
        return super(Users, self).save(*args, **kwargs)

    @property
    def password(self) -> str:
        raise AttributeError('user_password is not a readable attribute.')

    @password.setter
    def password(self, password) -> None:
        """Create hashed password."""
        self._hashed_password = generate_password_hash(password, method='scrypt')

    @property
    def hashed_password(self) -> str:
        return self._hashed_password


class UserManager:
    """
    A class that contains the logic for interacting with the Users model
    """

    @staticmethod
    def find_user_by_email(email):
        return Users.objects(email=email).first()

    @staticmethod
    def create_user(email, password, first_name, last_name) -> Users:
        """
        Create a new users in the database
        :param email: The email of the users
        :param password: The password of the users
        :param first_name: The first name of the users
        :param last_name: The last name of the users
        :return: The newly created users object
        """

        user = Users(email=email, first_name=first_name, last_name=last_name)
        user.password = password
        user.save()
        return user


class JournalManager:
    """
    A class that contains the logic for interacting with the Journal model
    :param user: The Journal object eg Users.journal
    :param date: The date of the journal entry in the format of DD_MMM_YYYY eg. 01_JAN_2021
    """

    def __init__(self, user: Users, date: str = get_current_date()):
        if not self.is_valid_date(date):
            raise ValueError(f"Date must be in 'DD_MMM_YYYY' format, date provided: {date}")
        self.user = user
        self.journal = user.journal
        self.date = date

    @staticmethod
    def is_valid_date(date: str) -> bool:
        try:
            # Try to parse the date string. If it's in the correct format,
            # this will succeed; otherwise, it will raise a ValueError
            datetime.strptime(date, "%d_%b_%Y")
            return date == date.upper()
        except ValueError:
            return False

    def add_journal_entry(self, recording_file_name, recording_seconds) -> (DayEntryBundle, JournalEntry):
        """
        Creates a new journal entry for the users for that day if one does not already exist then adds a new single
        journal entry to the day journal bundle
        :param recording_file_name: The name of the audio file
        :param transcription: The transcription of the audio file
        :return: tuple of the day journal entry and the single journal entry that has just been added
        """
        today = get_current_date()
        if today not in self.journal:
            self.journal[today] = DayEntryBundle()
        journal_entry = JournalEntry(recording_file_name=recording_file_name,
                                     recording_length_in_seconds=recording_seconds)
        self.journal[today].entries.append(journal_entry)
        self.user.save()

        return self.journal[today], journal_entry

    def add_entry_transcription(self, transcription, entry_id) -> JournalEntry:
        """
        Save the transcription for a journal entry
        :param journal_entry_object: The journal entry object
        :param transcription: The transcription of the audio file
        :return: The updated journal entry
        """
        today = get_current_date()

        # for entry in self.user.journal[today].entries:
        #     if entry.id == entry_id:
        #         journal_entry = entry
        #         break
        day_bundle = self.user.journal[today]

        # iterate through the day bundle and find the entry with the matching id. If no entry is found, return None
        journal_entry = next((entry for entry in day_bundle.entries if entry.id == entry_id), None)

        journal_entry.transcription = transcription
        self.user.save()

        return journal_entry

    def get_progress_time(self, date_requested=None):
        """
        Get the total time of all the journal entries for today
        :return:  The total time of all the journal entries for today
        """
        if date_requested is None:
            date_requested = self.date

        if date_requested not in self.journal:
            return 0
        return sum([entry.recording_length_in_seconds for entry in self.journal[date_requested].entries])

    def get_streaks_for_month(self, month, year) -> list:
        """
        Get the streaks for the chosen month
        :param month: The month in the format of MM
        :param year: The year in the format of YYYY
        :return: list of the date and the progress times for each day in the month
        """

        streaks = []
        for day in calendar.Calendar().itermonthdates(year, month):
            if day.month == month:
                formatted_date = day.strftime("%d_%b_%Y").upper()
                streaks.append({
                    "date": day.strftime("%d_%b_%Y"),
                    "progress_time": self.get_progress_time(date_requested=formatted_date)
                })
        return streaks


    def get_journal_entries_for_day(self, date_requested=None) -> list:
        """
        Get the journal entries for today
        :return: list of the journal entries for today
        """
        if date_requested is None:
            date_requested = self.date

        if date_requested not in self.journal:
            return []
        # extract the individual transcriptions from the journal entries
        return [entry.transcription for entry in self.journal[date_requested].entries]

    def get_all_journals(self):
        """
        Get all journal entries for the current user.
        :return: A list of dictionaries, each representing a journal for a given day.
        """
        logger.info(f"Entered the get_all_journals method")
        journals = []
        for day, day_entry in self.journal.items():
            journals.append({
                "id": day_entry.id,
                "date": day,
                "transcripts": [entry.transcription for entry in day_entry.entries]
            })

        logger.info(f"Left the get all journals method. Returning the journals: {journals}")
        return journals



    def delete_day_bundle(self, date_requested):
        """
        Delete the day bundle for the requested date
        :param date_requested: The date of the day bundle to be deleted
        """

        try:
            del self.journal[date_requested]
            self.user.save()
        except Exception as e:
            raise e

