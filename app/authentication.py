# authentication.py
import jwt
from datetime import datetime, timedelta
from passlib.context import CryptContext
import os

from werkzeug.security import check_password_hash

# Define the algorithm you want to use for JWT
ALGORITHM = os.getenv('AUDIOBIO_JWT_ALGORITHM')

# define the Secret key
SECRET_KEY = os.getenv('AUDIOBIO_SECRET_AUTH_KEY')

# Get a crypt context for handling passwords
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class AuthenticationService:
    """
    Class to handle authentication

    :param user: single user object
    :param token_expire_minutes: Number of minutes before the token expires. Default is 30 minutes.
    """

    def __init__(self, user, token_expire_minutes=int(os.getenv('JWT_EXPIRATION_MINUTES', 30))):
        self.user = user
        self.secret_key = SECRET_KEY

        self.token_expire_minutes = token_expire_minutes

    def authenticate_user(self, password: str) -> bool:
        """
        Authenticate the users
        :param password: The password entered by the users
        :return: True if the users is authenticated, else False
        """
        # Verify the password
        if self.verify_password(entered_password=password, database_password=self.user.hashed_password):
            return True
        else:
            return False

    def create_token(self, email: str) -> str:
        """
        Create a JWT token for the users
        :param email: The email of the user which will be used as the subject of the JWT token
        :return: The JWT token
        """
        access_token_expires = timedelta(minutes=self.token_expire_minutes)
        to_encode = {"sub": str(email),
                     "exp": datetime.utcnow() + access_token_expires,}
        encoded_jwt = jwt.encode(to_encode, self.secret_key, algorithm=ALGORITHM)
        return encoded_jwt

    @classmethod
    def verify_password(cls, entered_password, database_password) -> bool:
        """
        Verify the password entered by the users
        :param entered_password:
        :param database_password:
        :return bool: True if the password is correct, else False
        """
        return check_password_hash(database_password, entered_password)






