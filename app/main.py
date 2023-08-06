# main.py
import datetime
import tempfile
import uuid
import logging
from fastapi import FastAPI, UploadFile, HTTPException, File, Form, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
import os
import openai
import boto3
from botocore.exceptions import NoCredentialsError
from botocore.client import Config
from boto3.exceptions import S3UploadFailedError
from app.mongo_db_logic import Users, UserManager, JournalManager, get_current_date, get_formatted_date
from fastapi.security import OAuth2PasswordBearer
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, EmailStr
from app.authentication import AuthenticationService, ALGORITHM, SECRET_KEY

from fastapi.security import OAuth2PasswordRequestForm
import jwt
from typing import Optional, List

from pymediainfo import MediaInfo
import mutagen

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

app = FastAPI()

# Allow CORS (Cross Origin Resource Sharing) for your React application
# Replace 'http://localhost:3000' with the address where your React app is running.
# In a production application, this should be your domain or a specific set of domains.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

s3 = boto3.client(
    's3',
    region_name='us-east-2',
    aws_access_key_id=os.environ['_AWS_ACCESS_KEY_ID_AUDIOBIO'],
    aws_secret_access_key=os.environ['_AWS_SECRET_ACCESS_KEY_AUDIOBIO'],
    config=Config(signature_version='s3v4')
)

# Initiate the database class
users = Users()

# set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def get_current_user(token: str = Depends(oauth2_scheme)) -> Users:
    """
    Get the current user from the JWT token

    What it does:
    - Gets the JWT token from the request
    - Decodes the JWT token
    - Gets the user from the database
    - Returns the user

    :param token: The JWT token
    :return: The user
    """
    logger.info("get_current_user: start")
    logger.info(f"get_current_user: token: {token}")

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(
            jwt=token,
            key=SECRET_KEY,
            algorithms=[ALGORITHM]
        )
        username: Optional[str] = payload.get("sub")
        logger.info(f"Successfully decoded token, username: {username}")
        if username is None:
            logger.info("username is None")
            raise credentials_exception

    except jwt.PyJWTError as e:
        logger.info(f"jwt.PyJWTError: Could not validate credentials, token: Error: {e}")
        raise credentials_exception
    user = UserManager.find_user_by_email(email=username)
    if user is None:
        logger.info("user is None: could not find that user")
        raise credentials_exception
    return user


class Token(BaseModel):
    access_token: str
    token_type: str


# Authenticate user and return a JWT token
import logging


@app.post("/login/", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()) -> Token:
    """
    FastAPI endpoint to authenticate a user and return a JWT token

    What it does:
    - Gets the user from the database
    - Checks if the user exists, if not, raises an HTTPException
    - Checks if the password is correct, if not, raises an HTTPException
    - Creates a JWT token and returns it

    :param form_data: The form data which contains the name and password
    :return:  JWT token
    """
    logging.info("Attempting to find user by email...")
    user = UserManager.find_user_by_email(email=form_data.username)

    # Initiate the authentication service
    auth = AuthenticationService(user)

    if not user:
        logging.error(f"User with email {form_data.username} not found.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect name or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    hashed_password = user.hashed_password

    if not auth.verify_password(entered_password=form_data.password, database_password=hashed_password):
        logging.error(f"Failed password verification for user {form_data.username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect name or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    logging.info(f"Creating token for user {form_data.username}...")
    access_token = auth.create_token(
        email=form_data.username,
    )
    logging.info("Token created successfully.")

    return Token(access_token=access_token, token_type="bearer")


class UserCreate(BaseModel):
    email: EmailStr
    name: str
    password: str


@app.post("/signup/", response_model=Token, status_code=201)
async def signup(new_user: UserCreate) -> Token:
    """
    FastAPI endpoint to create a new user and return a JWT token.

    The function does the following:
    - Checks if the user already exists, if so, raises an HTTPException.
    - Splits the name into first and last names.
    - Creates a new user.
    - Authenticates the new user and returns a JWT token.

    :param new_user: A UserCreate model instance containing the new user's email, name, and password.
    :return: A Token model instance containing the JWT access token and token type.
    :raises HTTPException: If the email is already registered or if user creation fails.
    """
    existing_user = UserManager.find_user_by_email(email=new_user.email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    # split the name into first and last name
    name = new_user.name.split()
    if len(name) == 1:
        first_name = name[0]
        last_name = None
    else:
        first_name = name[0]
        last_name = name[1]

    # Create a new user
    UserManager.create_user(email=new_user.email, first_name=first_name, last_name=last_name,
                            password=new_user.password)

    created_user = UserManager.find_user_by_email(email=new_user.email)

    if not created_user:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="User creation failed",
        )

    # Initiate the authentication service
    user_is_authenticated = AuthenticationService(user=created_user).authenticate_user(password=new_user.password)

    if not user_is_authenticated:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="User creation failed",
        )

    access_token = AuthenticationService(user=created_user).create_token(
        email=created_user.email
    )

    return Token(access_token=access_token, token_type="bearer")


@app.post("/upload/")
async def upload_audio(
        audio: UploadFile = File(...),
        current_user: Users = Depends(get_current_user),
        length_in_seconds: str = Form(...)
):
    """
    FastAPI endpoint to upload an audio file to the backend from the frontend

    What it does:
    - Checks if the audio file is an audio file
    - Reads the audio file
    - Creates a journal entry

    :param current_user: The current user
    :param audio: audio file
    :param length_in_seconds: length of the audio file
    :return: name of the audio file if successful, else error message
    """
    logger.info(f"current_user: {current_user.first_name}: entered the upload_audio endpoint")
    try:
        logger.info(f"current_user: {current_user.first_name}: entered the upload_audio endpoint")
        if length_in_seconds == None:
            logger.error(f'No length of audio file provided, User: {current_user.first_name}')

            raise HTTPException(status_code=400, detail="No length of audio file provided")
        elif audio.content_type.startswith('audio/'):
            audio_content = await audio.read()  # Store the audio content in a variable

            audio_filename, tmp_name = handle_upload(audio.filename, audio_content)
            audio_filename = upload_to_s3(tmp_name, audio_filename)

            logger.info(f"Length of audio file: {length_in_seconds} seconds, User: {current_user.first_name}")

            # Create a journal entry
            journal_manager = JournalManager(current_user)
            today_journal_bundle, this_journal_entry = journal_manager.add_journal_entry(
                recording_file_name=audio_filename,
                recording_seconds=float(length_in_seconds)
            )

            # delete the temp file
            os.remove(tmp_name)

            # Transcribe audio
            transcription_object = gpt_whisper(s3, 'audiobio-recordings', audio_filename)

            transcription = transcription_object["text"]

            journal_manager.add_entry_transcription(transcription=transcription, entry_id=this_journal_entry.id)

            return {"filename": audio_filename}
        else:
            logger.error(f'Invalid file type: {audio.content_type}, User: {current_user.first_name}')

            raise HTTPException(status_code=400, detail="Invalid file type")
    except Exception as e:
        logger.error(f'Failed to process audio upload: {str(e)}, User: {current_user.first_name}')
        raise HTTPException(status_code=500, detail="Internal server error")


def handle_upload(audio_filename, audio_content) -> tuple:
    """
    Writes an audio file to a temporary location

    What it does:
    - Creates a random UUID
    - Saves the audio file in a temporary directory

    :param audio_filename: name of the audio file
    :param audio_content: content of the audio file
    :return: name of the audio file and the temporary location
    """
    # Create a random UUID
    audio_filename = f"AudioBio_Recording_{uuid.uuid4()}.{audio_filename.split('.')[-1]}"

    # Save the audio file in a temporary directory
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(audio_content)  # Write audio content to the temp file
        print("temp file saved", tmp.name)

        return audio_filename, tmp.name


# TODO: Move this to a separate file and encapsulate it in an AWS/S3 class
def upload_to_s3(tmp_name, audio_filename) -> str or dict:
    """
    Uploads an audio file from a temporary location to S3 bucket

    What it does:
    - Uploads the audio file to S3 bucket
    - Returns the name of the audio file if successful, else error message

    :param tmp_name: name of the temporary file
    :param audio_filename: name of the audio file
    :return: name of the audio file if successful, else error message
    """

    logger.info(f"Uploading {tmp_name} to S3 bucket")
    # Upload to S3 bucket and return the name of the audio file
    try:
        with open(tmp_name, 'rb') as data:
            s3.upload_fileobj(
                data,
                'audiobio-recordings',
                audio_filename,
            )
    except NoCredentialsError as e:
        logger.info(f"Credentials not available: {e}")
        raise HTTPException(status_code=400, detail=f"Credentials not available: {e}")
    except S3UploadFailedError as e:
        logger.info(f"Upload failed: {e}")
        raise HTTPException(status_code=400, detail=f"Upload failed: {e}")
    except Exception as e:
        logger.info(f"Unknown error: {e}")
        raise HTTPException(status_code=400, detail=f"Unknown error: {e}")

    logger.info(f"Uploaded {tmp_name} to S3 bucket successfully")

    return audio_filename


# TODO: Move this to a separate file and encapsulate it in a gpt class
def gpt_whisper(s3_client, bucket_name, audio_filename) -> str:
    """
    Transcribes an audio file using OpenAI's GPT-3 API
    :param s3_client: s3 client object
    :param bucket_name: name of s3 the bucket where the audio file is stored
    :param audio_filename: name of the audio file
    :return: transcript of the audio file
    """
    openai.api_key = os.getenv("OPENAI_API_KEY")

    # Get file extension
    _, file_extension = os.path.splitext(audio_filename)

    # Create a temp file with the same extension
    with tempfile.NamedTemporaryFile(suffix=file_extension) as tmp:
        # Download the file from S3 to the temp file
        s3_client.download_file(bucket_name, audio_filename, tmp.name)

        # Transcribe the audio file
        with open(tmp.name, 'rb') as s3_audio_file:
            transcript = openai.Audio.transcribe("whisper-1", file=s3_audio_file)

    return transcript


class ProgressTimeToday(BaseModel):
    """
    Progress time today
    """
    progress_time: float


@app.get("/progress_time_today", response_model=ProgressTimeToday)
async def get_progress_time_today(current_user: Users = Depends(get_current_user)) -> ProgressTimeToday:
    """
    Get progress time today
    :param current_user: The current user
    :return: progress time today
    """
    logger.info(f"current_user: {current_user.first_name}: entered the get_progress_time_today endpoint")
    try:
        journal_manager = JournalManager(current_user)

        today = get_current_date()
        progress_time = journal_manager.get_progress_time(today)

        return ProgressTimeToday(progress_time=progress_time)
    except Exception as e:
        logger.error(f'Failed to get progress time today: {str(e)}, User: {current_user.first_name}')
        raise HTTPException(status_code=500, detail="Internal server error")


class Streak(BaseModel):
    """
    A model to represent a streak, which consists of a date and a progress time.
    """
    date: str
    progress_time: float


@app.get("/get_streak/{month}/{year}", response_model=List[Streak])
async def get_streak(month: int, year: int, current_user: Users = Depends(get_current_user)) -> List[Streak]:
    """
    Get streak for the entire month.
    :param year: the year for which to fetch the streaks. For instance, '2023' for 2023.
    :param month: The month for which to fetch the streaks in the format of M. For instance, '1' for January.
    :param current_user: The current user.
    :return: A list of Streak objects, each representing a streak for a given day in the month.
    """
    logger.info(f"current_user: {current_user.first_name}: entered the get_streak endpoint")
    try:
        date_requested = f"01_{month}_{year}"

        formatted_date = get_formatted_date(date_requested)

        journal_manager = JournalManager(current_user, formatted_date)

        streaks_for_the_month = journal_manager.get_streaks_for_month(month=month, year=year)
        print(f"Streaks for the month: {streaks_for_the_month}")

        return streaks_for_the_month

    except Exception as e:
        logger.error(f'Failed to get streak: {str(e)}, User: {current_user.first_name}, Date: {date_requested}')
        raise HTTPException(status_code=500, detail="Internal server error")


class JournalDay(BaseModel):
    id: str
    date: str
    transcripts: List[str]

@app.get("/all_journals", response_model=List[JournalDay])
async def all_journals(current_user: Users = Depends(get_current_user)) -> List[JournalDay]:
    """
        Get all the journals for the current user.
        :param current_user: The current user.
        :return: A list of show_month_journal objects, each representing a journal for a given day.
        """
    logger.info(f"current_user: {current_user.first_name}: entered the all_journals endpoint")
    try:
        journal_manager = JournalManager(current_user)

        # Get all journal entries from the DB
        all_journals = journal_manager.get_all_journals()

        # Sort entries by date in descending order
        all_journals.sort(key=lambda x: datetime.datetime.strptime(x['date'], '%d_%b_%Y'), reverse=True)

        return all_journals

    except Exception as e:
        logger.error(f'Failed to get journals: {str(e)}, User: {current_user.first_name}')
        raise HTTPException(status_code=500, detail="Internal server error")







class delete_status(BaseModel):
    """
    A model to represent the status of a delete operation.
    """
    status: str


@app.delete("/delete_journal/{day}/{month}/{year}", response_model=delete_status)
async def delete_journal(day: int, month: int, year: int,
                         current_user: Users = Depends(get_current_user)) -> delete_status:
    """
    Delete a journal for a given date.
    :param date: The date of the journal to delete in the format of DD_MM_YYYY. For instance, '01_01_2023' for January 1st, 2023.
    :param current_user: The current user.
    :return: A delete_status object, which contains the status of the delete operation.
    """
    logger.info(f"current_user: {current_user.first_name}: entered the delete_journal endpoint")
    try:
        formatted_date = get_formatted_date(f"{day}_{month}_{year}")

        journal_manager = JournalManager(current_user, formatted_date)

        journal_manager.delete_day_bundle(formatted_date)

        return delete_status(status="success")

    except Exception as e:
        logger.error(f'Failed to delete journal: {str(e)}, User: {current_user.first_name}, Date: {formatted_date}')
        raise HTTPException(status_code=500, detail="Internal server error")
